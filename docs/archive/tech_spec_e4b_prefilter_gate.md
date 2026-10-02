# [Sent-HVC] Tech Spec — Triển khai LLM Pre-Filter Gate cục bộ (`gemma4-e4b-mini`)

| | |
|---|---|
| Owner | Thang Le Quang (EDA - AI.DS) |
| PM | *[chốt với PM]* |
| Status | Ready for Go-live |
| Go-live date | *[chốt lịch]* |
| Version | 1.0 |

**Phạm vi:** Triển khai [`gemma4-e4b-mini`](https://huggingface.co/thanglq150188/gemma4-e4b-mini) làm cổng lọc tiền xử lý cục bộ trên T4 GPU nodepool của Databricks, đứng trước luồng sentiment chính (scanner + verifier chạy trên Databricks LLM API). Cổng lọc loại ~85% cuộc gọi sạch trước khi chúng chạm luồng chính → cắt cost LLM API ~85% và giảm compute pod từ 9 xuống 4–5, không đổi schema output.

---

## TL;DR

| Hạng mục | Production cũ (không filter) | Với filter cục bộ (mới) |
|---|---|---|
| **Cost tổng / tháng** | ~$3,685–4,982 | **~$1,019–1,551 (−55 đến −80%)** |
| Cost LLM API (Claude Sonnet + Gemini Flash) | ~$2,100–3,000/tháng ($70–100/ngày) | **~$315–450/tháng (−85%)** |
| Compute pod T4 | **9 pod** | **4–5 pod (−45 đến −55%)** |
| % traffic đến Databricks LLM API | 100% | **~15%** |
| **Pipeline F1 e2e** | 0.852 | **0.849 (−0.3 pp — flat)** |
| Recall vi phạm (vs QC ground truth) | 0.844 | 0.823 (−2.1 pp) |
| Precision | 0.862 | **0.877 (+1.5 pp)** |
| Throughput cổng lọc | N/A | **44 calls/min/pod** (fleet 176–220 rpm) |
| Batch window | Ràng buộc bởi cloud rate limit | **~2–2.5 h trên 4–5 pod fleet** |
| Model | N/A | **`gemma4-e4b-mini`** (Q8_0 GGUF, 5.21 GB) |
| Runtime | N/A | **llama.cpp server-cuda** trên T4 nodepool |
| Output schema | *(luồng chính, không đổi)* | **Giữ nguyên** — filter trả `should_scan: true/false`, không đổi contract xuống downstream |

**Điểm cốt lõi:** filter tiết kiệm ~$2,100–3,900/tháng (~$25k–47k/năm) với F1 pipeline thực chất không đổi (−0.3 pp), đổi lại 2.1 pp recall đã được QC team ký duyệt. Cost rollback < 30s qua env-var (không cần redeploy).

---

## As-is — Hạn chế của luồng hiện tại

1. **100% cuộc gọi đi qua Databricks LLM API.** Mỗi ngày 25–30k call đều phải chạy đầy đủ scanner + verifier trên Claude Sonnet / Gemini Flash → chi phí API ~$70–100/ngày (~$2.1–3k/tháng).
2. **Cần 9 T4 pod duy trì throughput.** Do luồng chính phải sustain 100% traffic, cụm phải cấp 9 pod chạy 8–10 h/ngày để không trượt batch window.
3. **Bị chi phối bởi cloud API rate limits + provider queue.** Peak load dễ chạm quota → throttling / backoff / retry, batch window không dự báo được.
4. **Không có cơ chế lọc rẻ.** Không có bước phân loại rẻ để loại call sạch — mọi call, kể cả các đoạn thoại rõ ràng không vi phạm, đều phải chạy full pipeline.

---

## Solution — `gemma4-e4b-mini` làm Local Pre-Filter Gate

### 1. Model & artefact

- **Model:** [`thanglq150188/gemma4-e4b-mini`](https://huggingface.co/thanglq150188/gemma4-e4b-mini) — customised Gemma-4 E4B-IT text-only (~5 B params effective, 42 layers, hidden 2560).
- **Customisation vs stock Gemma-4 E4B:**
  1. Text-only (bỏ vision + audio tower).
  2. Prune vocabulary xuống 69,246 tokens (VN + EN).
  3. Merge LoRA train trên public Vietnamese reasoning corpus (~30 k samples curated subset, 1.7 epochs) — **không có Win data trong weights**.
  4. Quantise Q8_0 GGUF → 5.21 GB trên disk, ~11–12 GB VRAM khi serve trên T4.
- **Chi tiết chọn model + benchmark base model:** xem DAB `docs/DAB_e4b_prefilter_gate.md`.

### 2. Runtime — `llama.cpp` trên T4 nodepool

- **Image:** `ghcr.io/ggml-org/llama.cpp:server-cuda` (upstream, pin by commit digest — cache-reuse behavior đã đổi ngầm giữa các version, phải pin để tránh regression).
- **Flags production** (không thay đổi runtime patch trên T4 `sm_75`):
  ```
  --n-gpu-layers 99 --ctx-size 8192 --parallel 4
  --swa-full --cache-reuse 256 -fa on
  --jinja --chat-template-file /models/gemma4_chat.jinja
  ```
  - **Bắt buộc:** `--swa-full`, `--cache-reuse 256`, `-fa on`. Thiếu `--swa-full` → cache-reuse tắt ngầm, throughput sụt xuống ~19 rpm (dưới SLO 40 rpm).
- **Chat template:** `gemma4_chat.jinja` (trích từ HF repo, mount vào container lúc startup — chat template của Gemma-4 khác Gemma-3, dùng sai template → chất lượng sập).
- **Topology:** 1 pod = 1 T4 GPU; 4–5 pod cho batch hàng ngày trên T4 GPU nodepool của Databricks.
- **VRAM working set:** ~11–12 GB / 16 GB T4 (weights 5.21 GB + KV cache pool ~2–3 GB + CUDA activations & workspace ~3–4 GB). Headroom ~4 GB.

### 3. Integration — batch runner gọi filter trước scanner

- **API surface:** filter lộ OpenAI-compatible `/v1/chat/completions` trên port 8080.
- **Cách gọi:** batch runner của luồng chính gọi filter async cho từng chunk trước khi vào scanner + verifier. Filter trả JSON `should_scan: true/false` + short reason.
  - `should_scan=false` → drop, không gọi luồng chính. Log lại.
  - `should_scan=true` → chuyển tiếp đến scanner + verifier trên Databricks LLM API như luồng cũ.
- **Cấu hình filter runtime:** biến môi trường `SENTIMENT_FILTER_LLM_RESOURCE_KEY` trong `resources.yaml`.
  - `SENTIMENT_FILTER_LLM_RESOURCE_KEY=e4b-local` → filter bật.
  - `SENTIMENT_FILTER_LLM_RESOURCE_KEY=""` → filter tắt, 100% traffic quay về luồng chính. **Kill-switch runtime, không cần redeploy.**
- **CASE_SPEC không đổi.** Output cuối của pipeline giữ nguyên format (`Reasoning / Result / Evidence / Score_offset`) — QC dashboard, downstream consumer không phải đổi gì.

### 4. Safety — fail-open + kill-switch + audit workflow

| Cơ chế | Hành vi | Trigger |
|---|---|---|
| **Fail-open on parse error** | LLM trả JSON sai format → filter ép `should_scan=true`, forward call sang luồng chính | Any parse failure |
| **Kill-switch runtime** | Set env-var `SENTIMENT_FILTER_LLM_RESOURCE_KEY=""` → 100% traffic về luồng chính | Ops decision |
| **Periodic recall audit** | Rerun luồng chính trên mẫu ngẫu nhiên các call bị filter drop, so sánh recall | Manual today (Phase-2: automated daily audit + alert khi recall < 0.95) |
| **Structured logs per call** | Mỗi routing decision log lại (`should_scan`, `reason`, chunk_count) | Every call — go-live shipped |

---

## Triển khai go-live

| | |
|---|---|
| **Artifact** | (1) Docker image `ghcr.io/ggml-org/llama.cpp:server-cuda` (pinned commit digest — vd `sha256:…`). (2) GGUF file `gemma4-e4b-envi-pruned-q8_0.gguf` (5.21 GB, từ HF repo `thanglq150188/gemma4-e4b-mini`) đẩy sang S3 / Databricks Volumes, checksum SHA256 verified trước khi load — đây cũng là `model` name mà client gửi vào OpenAI-compat endpoint. (3) Chat template `gemma4_chat.jinja` mount vào pod lúc startup. **Không cần build image custom.** |
| **Tương thích interface** | Filter lộ OpenAI-compat `/v1/chat/completions` — bất kỳ HTTP client async nào cũng gọi được. Batch runner của luồng chính thêm 1 async call trước scanner; **output schema pipeline giữ nguyên** → downstream consumer + QC dashboard không cần đổi. |
| **Constraint** | (1) Pin `llama.cpp` version bằng commit digest — cache-reuse behavior đã đổi ngầm 1 lần giữa các version, phải freeze để tránh silent regression. (2) Mandatory flags `--swa-full --cache-reuse 256 -fa on` (thiếu → throughput sụt). (3) `gemma4_chat.jinja` bắt buộc mount lúc startup. (4) Chunk truyền theo thứ tự thời gian trong cùng call (cache-reuse hoạt động trong-call); router phân call (không phải chunk) về cùng pod. |
| **Người deploy & quản lý** | *[chốt với ops team]* |
| **Rollback plan** | Set env-var `SENTIMENT_FILTER_LLM_RESOURCE_KEY=""` trong Databricks job config → filter tắt ngay lập tức, 100% traffic quay về luồng cũ. **Không cần redeploy image / restart pod. < 30 giây.** Nếu cần rollback sâu hơn (revert integration code), revert merge commit trên `dev` — CASE_SPEC không đổi nên downstream không cần can thiệp. |

---

## Kết luận

`gemma4-e4b-mini` triển khai làm cổng lọc cục bộ trên T4 GPU nodepool tiết kiệm ~**$2,100–3,900/tháng** (~55–80% total cost, ~85% API cost, giảm 9 → 4–5 T4 pod) với **F1 pipeline gần như không đổi** (0.852 → 0.849, −0.3 pp). Đổi lại là 2.1 pp recall — đã được QC team review và ký duyệt trước submission. Không đổi output schema → downstream consumer không phải thay đổi gì. Kill-switch runtime qua env-var (< 30 s) đảm bảo có thể rollback ngay khi cần. Filter chạy trên hạ tầng T4 nodepool sẵn có — không phát sinh capex, chỉ dùng lại pod của cụm cũ.

---

### Phụ lục — Cost breakdown chi tiết

**Giả định:** traffic 25–30 k call/ngày (~750–900 k call/tháng). Databricks T4 pod rate = $0.734/hr (= 10.48 DBU × $0.07/DBU Model Serving). Pod utilization measured hiện tại: 8–10 h/ngày cho cấu hình 9 pod. Cấu hình đề xuất 4–5 pod chưa đo utilization thực → tạm dùng cùng 8–10 h/ngày làm upper bound.

| Hạng mục | Hiện tại (9 pod, không filter) | Đề xuất (4–5 pod + filter) |
|---|---:|---:|
| T4 pod compute | 9 × $0.734 × 8–10 h × 30 d = **~$1,585–1,982/tháng** | 4–5 × $0.734 × 8–10 h × 30 d = **~$704–1,101/tháng** |
| Databricks LLM API (Claude Sonnet + Gemini Flash) | **~$2,100–3,000/tháng** ($70–100/ngày, per Ops data) | **~$315–450/tháng** (~85% lower — chỉ 15% traffic đến API) |
| **Tổng monthly** | **~$3,685–4,982** | **~$1,019–1,551** |
| **Tiết kiệm monthly** | — | **~$2,100–3,900/tháng** (~55–80% total) |
| **Tiết kiệm annual** | — | **~$25,000–47,000/năm** |
| Capex | 0 (nodepool đã có) | 0 (dùng cùng nodepool) |

**Hai đòn bẩy tiết kiệm:**
1. **Filter drop 85% call** → giảm ~85% LLM API cost (chỉ 15% call đến Claude Sonnet / Gemini Flash).
2. **Giảm số pod luồng chính** từ 9 → 4–5 (do luồng chính không còn phải sustain 100% traffic throughput) → giảm ~55% compute cost.

---

### Phụ lục — Throughput & VRAM benchmark

**Đo đạc trên T4 với cấu hình production (`ctx-size 8192, parallel 4, --swa-full --cache-reuse 256 -fa on`):**

| Config | Throughput | Ghi chú |
|---|---|---|
| 1× T4 pod | **44 calls/min** | Đo trên T4 Kaggle với đầy đủ mandatory flags |
| 1× T4 pod **thiếu `--swa-full`** | 19 calls/min | Cache-reuse tắt ngầm — **KHÔNG deploy config này** |
| Fleet 4–5× T4 pod trên T4 nodepool | **176–220 calls/min aggregate** | Đủ clear batch 25–30k call/ngày trong ~2–2.5 h |

**VRAM footprint per pod (measured/estimated):**

| Component | Size |
|---|---|
| Weights (Q8_0 GGUF) | 5.21 GB |
| KV cache pool (shared 4 slot × 2048 tok) | ~2–3 GB |
| CUDA activations + workspace | ~3–4 GB |
| **Total working set** | **~11–12 GB / 16 GB T4** (headroom ~4 GB) |

---

### Phụ lục — Benchmark quality

**Golden Set:** `live_20260716` + `live_20260722` full-day held-outs (~15 k call mỗi ngày, n = 361 audited, 147 confirmed violations + 214 clean).

**Filter (gemma4-e4b-mini) đo riêng:**
- Violation Recall: **97.2%** (target ≥ 95%)
- Clean Call Filter Rate: **84.6%** (target ≥ 70%)

**Pipeline e2e (filter + luồng chính) vs luồng chính alone:**

| Config | TP | FN | FP | TN | Precision | Recall | **F1** |
|---|---:|---:|---:|---:|---:|---:|---:|
| Luồng chính alone (không filter) | 124 | 23 | 20 | 194 | 0.862 | 0.844 | **0.852** |
| Filter + luồng chính (production config) | 121 | 26 | 17 | 197 | 0.877 | 0.823 | **0.849** |
| Δ | −3 | +3 | −3 | +3 | +1.5 pp | −2.1 pp | **−0.3 pp** |

**Chi tiết methodology + head-to-head base model comparison** (Gemma-4 E4B-IT 0.85/0.74 vs Gemma-4 E2B 0.62/0.67 vs Qwen 3.5 4B 0.54/0.72): xem DAB `docs/DAB_e4b_prefilter_gate.md`.

---

### Phụ lục — Tham chiếu code & config

| Thành phần | Đường dẫn |
|---|---|
| Filter case code | `src/cases/sentiment_agent/v4/_filter.py` |
| Filter prompt template | `.prompts/sentiment_agent/FILTER_PROMPT.prompt` |
| Resource registry | `resources.yaml` (resource key `e4b-local`) |
| Runtime env-var (kill-switch) | `SENTIMENT_FILTER_LLM_RESOURCE_KEY` |
| Model artefact | `gemma4-e4b-envi-pruned-q8_0.gguf` (5.21 GB) trên S3 / Databricks Volumes, SHA256-verified — cũng là `model` name mà client gửi vào endpoint |
| HF model card | https://huggingface.co/thanglq150188/gemma4-e4b-mini |
| Chat template | `gemma4_chat.jinja` (extracted từ HF repo, mount vào container) |
| Docker image | `ghcr.io/ggml-org/llama.cpp:server-cuda` (pin commit digest) |
| DAB (design justification) | `docs/DAB_e4b_prefilter_gate.md` |
| Branch tích hợp | `thanglq2_dev` → merge `dev` của repo `analyze` |
