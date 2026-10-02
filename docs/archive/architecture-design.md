# Tài liệu Thiết kế Kiến trúc — Hệ thống QC Call Center (ASR + Sentiment)

| Thông tin | Giá trị |
|---|---|
| **Phiên bản** | 0.1 (draft) |
| **Ngày** | 2026-04-20 |
| **Tác giả** | Le Quang Thang (EDA – AI.DS) |
| **Stakeholders** | Cham Tran Thi Ngoc (EDA – DPC.DA), Cuong Vu Manh (EDA – DS&Innovation) |
| **Trạng thái** | Draft for review |

---

## 1. Giới thiệu

### 1.1. Mục tiêu tài liệu

Tài liệu này mô tả **kiến trúc hệ thống Quality Control (QC) Call Center** cho nghiệp vụ thu hồi nợ, bao gồm hai module chính:

1. **ASR** — chuyển file audio cuộc gọi thành transcript có phân biệt người nói (agent/customer)
2. **Sentiment (QC Analyze)** — phân tích transcript để phát hiện vi phạm quy định và đánh giá thái độ

Hai module được xây dựng trên nền thư viện chung **Hush AI** — một framework orchestration kiểu graph-based cho pipeline AI/ML.

### 1.2. Phạm vi

- Nghiệp vụ: chấm điểm chất lượng cuộc gọi thu hồi nợ (collection calls) tiếng Việt
- Input: file WAV stereo (2 kênh — agent/customer) + metadata cuộc gọi
- Output: JSON vi phạm theo 7 case nghiệp vụ + sentiment

### 1.3. Thuật ngữ

| Thuật ngữ | Giải thích |
|---|---|
| VAD | Voice Activity Detection — phát hiện đoạn có giọng nói |
| ASR | Automatic Speech Recognition — nhận dạng giọng nói → text |
| Diarization | Phân biệt ai nói lúc nào trong cuộc gọi |
| RABA | Record Agreement / Ben ang to pay analysis — case kiểm tra cam kết trả nợ |
| HVC | High-Value Compliance — tập các vi phạm quan trọng |
| Hush AI | Framework orchestration kiểu graph dùng nội bộ |

---

## 2. Bối cảnh nghiệp vụ

Mỗi ngày call center xử lý hàng nghìn cuộc gọi thu hồi nợ. Sau mỗi cuộc, agent gán call_code (ví dụ `Hua_tra`, `Ngat_may`, `Ben_thu_3_hua_tra`) để phản ánh kết quả. QC cần:

1. **Xác minh call_code** có đúng nội dung cuộc gọi không (chống gian lận KPI)
2. **Phát hiện vi phạm quy định** (đọc số thẻ qua điện thoại, tiết lộ thông tin bên thứ 3, v.v.)
3. **Đánh giá thái độ** agent và customer

Hiện trạng: QC thủ công chỉ cover được ~5% cuộc gọi. Hệ thống tự động sẽ nâng lên 100%.

---

## 3. Kiến trúc tổng thể

### 3.1. Sơ đồ khối

```
┌────────────────────────────────────────────────────────────────┐
│                      Data Source Layer                          │
│  ┌──────────────┐                    ┌──────────────────────┐   │
│  │ Audio WAV    │                    │ Call Metadata        │   │
│  │ (stereo)     │                    │ (call_code,closed_by)│   │
│  └──────┬───────┘                    └──────────┬───────────┘   │
└─────────┼──────────────────────────────────────┼───────────────┘
          │                                      │
          ▼                                      │
┌─────────────────────────┐                      │
│  Module 1: ASR          │                      │
│  ├─ Split channels      │                      │
│  ├─ VAD (Silero ONNX)   │                      │
│  ├─ Transcribe (NeMo)   │                      │
│  └─ Aggregate timeline  │                      │
│  Output: transcribed_vads│                     │
└────────────┬────────────┘                      │
             │                                   │
             ▼                                   ▼
      ┌───────────────────────────────────────────────┐
      │   Module 2: Sentiment (QC Analyze)            │
      │   ┌─────────────────────────────────────────┐ │
      │   │ Quality Scorer Graph (7 cases parallel) │ │
      │   │  - Hangup     - Card Number             │ │
      │   │  - RABA       - Phone Source            │ │
      │   │  - Disclosure - Sentiment (agent/cust)  │ │
      │   └─────────────────────────────────────────┘ │
      │   Output: call_scoring JSON                    │
      └────────────┬───────────────────────────────────┘
                   │
                   ▼
       ┌──────────────────────────┐
       │ QC Review / Dashboard    │
       │ (ngoài phạm vi tài liệu) │
       └──────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│                    Cross-cutting Foundation                     │
├────────────────────────────────────────────────────────────────┤
│  Hush AI Framework    │  LLM Providers │  Observability         │
│  (graph orchestration)│  (Claude,GPT)  │  (Langfuse tracing)    │
│                       │                │                        │
│  Embedding (BGE-M3)   │  ONNX Runtime  │  Config (resources.yaml)│
└────────────────────────────────────────────────────────────────┘
```

### 3.2. Luồng dữ liệu tổng thể

1. File audio WAV stereo được đưa vào **Module ASR**
2. ASR trả về JSON có `transcribed_vads` (danh sách segment với timestamp, role, content)
3. **Module Sentiment** nhận JSON + call metadata, chạy 7 case song song
4. Output final là `call_scoring` JSON với danh sách vi phạm

### 3.3. Nguyên lý thiết kế

| Nguyên lý | Lý do |
|---|---|
| **Graph-based orchestration (Hush AI)** | Workflow phức tạp, nhiều nhánh song song, dễ visualize và maintain hơn imperative code |
| **Async-first** | Nhiều LLM call I/O-bound, async tận dụng được concurrency |
| **Local ML inference (ONNX)** | Giảm chi phí LLM bằng pre-filter; giữ embedding/VAD không phụ thuộc external API |
| **Config externalize (resources.yaml)** | Đổi model/endpoint không cần code change |
| **LLM làm arbiter, ML làm filter** | ML xử lý nhanh các case rõ ràng, LLM xử lý case biên/phức tạp |

---

## 4. Thư viện nền tảng — Hush AI

### 4.1. Vai trò

Hush AI là framework orchestration được dùng làm nền cho cả hai module. Nó cung cấp:

- Mô hình **graph** cho pipeline AI (tương tự Airflow nhưng async, cho AI workload)
- **Resource registry** quản lý LLM, embedding, observability config tập trung
- **Provider ops** sẵn có cho LLM (OpenAI-compatible), embedding, reranking
- **Tracer** tích hợp Langfuse cho observability

Repo: `D:\platform.hush-ai`

### 4.2. Các khái niệm chính

| Khái niệm | Mô tả | Ví dụ |
|---|---|---|
| `@op` | Decorator biến Python function thành pipeline node | `@op async def format_fn(...)` |
| `@graph` | Decorator tạo reusable sub-graph | `@graph def verify_raba(...)` |
| `GraphOp` | Composite node chứa nhiều op, wire qua edges | `START >> node1 >> node2 >> END` |
| `if_()` | Branch operator cho conditional routing | `if_(x == "A", "node_a").else_("node_b")` |
| `ChainOp.of(...)` | Helper dựng LLM call (prompt → LLM → parser) | `ChainOp.of(resource=..., template=..., extract=[...])` |
| `Hush(graph).run(inputs=...)` | Engine compile + execute graph async | Entry point runtime |

### 4.3. Resource Registry

`resources.yaml` khai báo tập trung tất cả external dependencies:

```yaml
llm:claude-4-sonnet:
  _class: OpenAIConfig
  base_url: ${DATABRICKS_ENDPOINT}
  api_key: keycloak:aihub
  model: databricks-claude-4-sonnet
  retry: { max_attempts: 3, backoff: exponential }

embedding:corpus:
  _class: ONNXEmbeddingConfig
  model_path: models/bge-m3.onnx

langfuse:default:
  _class: LangfuseConfig
  host: ${LANGFUSE_HOST}
```

Ops reference bằng key: `ChainOp.of(resource="claude-4-sonnet", ...)`.

### 4.4. Parallelism

Hush AI tự detect nhánh độc lập trong graph và chạy song song trên async event loop. Ví dụ trong case RABA, 3 detector (money/time/agreement) được wire `START >> [time, money, agreement] >> decision` — engine tự chạy cả 3 song song, chờ đủ → tiếp tục.

### 4.5. Observability

Langfuse tracer truyền vào `engine.run(..., tracer=tracer)` tự động record:
- Mỗi LLM call: prompt, response, token, latency, cost
- Graph execution: thời gian từng node, input/output state
- Tags động để filter (ví dụ `call_id`, `case_name`)

---

## 5. Module 1: ASR Pipeline

### 5.1. Vị trí

Repo: `D:\callbot-assistant\mle-ds2-pilot\asr`

### 5.2. Mục đích

Chuyển file audio WAV stereo (2 kênh — left=agent, right=customer) thành transcript có phân biệt người nói và timestamp.

### 5.3. Kiến trúc

```
        WAV stereo file
              │
              ▼
      ┌───────────────┐
      │ Split Channels│  (in-memory, không ghi file tạm)
      └───────┬───────┘
      ┌───────┴────────┐
      │                │
      ▼                ▼
  ┌─────────┐     ┌─────────┐
  │ VAD L   │     │ VAD R   │   (Silero VAD ONNX, 2 instance song song)
  │(agent)  │     │(customer)│
  └────┬────┘     └────┬────┘
       │               │
       ▼               ▼
  ┌─────────┐     ┌─────────┐
  │ ASR L   │     │ ASR R   │   (NeMo CTC-BPE, 2 model riêng cho agent/customer)
  │(batch)  │     │(batch)  │
  └────┬────┘     └────┬────┘
       │               │
       └───────┬───────┘
               ▼
      ┌────────────────┐
      │ Merge & Sort   │  (theo timestamp)
      └────────┬───────┘
               ▼
      transcribed_vads JSON
```

### 5.4. Thành phần chính

| Module | File | Trách nhiệm |
|---|---|---|
| Pipeline graph | `src/pipeline.py` | Định nghĩa `@graph` ASR workflow |
| VAD | `src/vad.py` | Split stereo, chạy Silero VAD từng kênh |
| ASR | `src/asr.py` | Transcribe batch VAD segment bằng NeMo |
| Model Hub | `src/model_hub.py` | Load 4 model (2 ASR + 2 VAD) song song, thread-safe |
| Entry | `main.py` | Batch process folder WAV |

### 5.5. Model & Resource

| Loại | Model | Kích thước | Nguồn |
|---|---|---|---|
| VAD | Silero VAD ONNX | ~2MB | Pre-trained |
| ASR agent | NeMo CTC-BPE (tiếng Việt, giọng miền) | ~500MB | Fine-tuned nội bộ |
| ASR customer | NeMo CTC-BPE (tiếng Việt, giọng đa vùng) | ~500MB | Fine-tuned nội bộ |

Tách 2 model ASR vì agent có giọng chuẩn call center, customer đa dạng vùng miền → tách để tối ưu độ chính xác.

### 5.6. Output format

```json
{
  "transcribed_vads": [
    {
      "start": 0.066, "end": 7.87, "duration": 7.804,
      "peak_db": -0.137, "harmonic_clarity": 0.040,
      "peak_db_zscore": 0.0,
      "content": "alo tổng đài ngân hàng nghe anh chị",
      "role": "agent"
    }
  ]
}
```

Metadata âm thanh (`peak_db`, `harmonic_clarity`, `peak_db_zscore`) được tính kèm từ VAD để hỗ trợ sentiment ML ở module sau.

### 5.7. Performance

- Latency: ~1:10 realtime (audio 5 phút xử lý ~30s) trên GPU T4
- Throughput: phụ thuộc GPU, scale bằng cách tăng worker process

---

## 6. Module 2: Sentiment (QC Analyze) Pipeline

### 6.1. Vị trí

Repo: `D:\callbot-assistant\mle-ds2-pilot\analyze`

### 6.2. Mục đích

Nhận transcript từ ASR + call metadata, chạy **7 case kiểm tra song song**, trả về JSON vi phạm.

### 6.3. Kiến trúc tổng thể

```
           transcribed_vads + call_code + closed_by
                          │
                          ▼
              ┌─────────────────────┐
              │  Conversation obj   │  (index by timestamp,
              │  (src/conversation) │   query by role)
              └──────────┬──────────┘
                         │
                         ▼
         ┌────────────────────────────────┐
         │  quality_scorer @graph         │
         │                                 │
         │  START >> [7 case graphs] >>   │
         │           aggregate >> END      │
         └────────────────────────────────┘
                         │
              ┌──────────┼──────────┬──────────┬──────────┬──────────┐──────────┐
              ▼          ▼          ▼          ▼          ▼          ▼          ▼
        ┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐┌─────────┐
        │ Hangup  ││  RABA   ││Disclosure││ Card   ││ Phone   ││Sentiment││Sentiment│
        │         ││         ││          ││ Number ││ Source  ││ Agent   ││Customer │
        └─────────┘└─────────┘└─────────┘└─────────┘└─────────┘└─────────┘└─────────┘
              │          │          │          │          │          │          │
              └──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
                         │
                         ▼
                 ┌──────────────┐
                 │ _aggregate    │ (gom kết quả 7 case)
                 └──────┬───────┘
                        ▼
                 ┌──────────────┐
                 │ _post_process│ (transform schema cuối)
                 └──────┬───────┘
                        ▼
                call_scoring JSON
```

### 6.4. Bảy case vi phạm

| # | Case | File | Điều kiện kích hoạt | Phương pháp |
|---|---|---|---|---|
| 1 | Hangup | `cases/hangup.py` | `call_code="Ngat_may"` và `closed_by="AGENT"` | LLM |
| 2 | RABA | `cases/raba.py` | `call_code∈{"Hua_tra","Ben_thu_3_hua_tra"}` | ML pre-filter + LLM |
| 3 | Disclosure | `cases/disclosure.py` | Luôn chạy (60s đầu) | LLM |
| 4 | Card Number | `cases/card_number.py` | Heuristic digit pattern match | Regex + LLM |
| 5 | Phone Source | `cases/phone_source.py` | Keyword detection | Keyword + LLM |
| 6 | Sentiment Agent | `cases/sentiment_agent.py` | Luôn chạy | ML MLP (threshold 0.78) |
| 7 | Sentiment Customer | `cases/sentiment_customer.py` | Luôn chạy | ML MLP (threshold 0.9) |

### 6.5. Mẫu thiết kế sub-graph (ví dụ RABA)

Mỗi case là một `@graph`. RABA là case phức tạp nhất, minh hoạ pattern chung:

```
START
  │
  ▼
ML Pre-filter  (ONNX cascade: 6 MLP model — call_type, money, is_predue, time, actionable + keyword)
  │
  ├── should_pass=False ──► exit (skip LLM, confident no violation)
  │
  └── should_pass=True
      │
      ▼
  Route by call_code
      │
      ├── "Hua_tra"              → Case 2A graph
      │
      └── "Ben_thu_3_hua_tra"    → Case 2B graph
                                     │
                                     ▼
                              Identity Classifier (LLM)
                              ├── CUSTOMER    → vi phạm
                              ├── UNKNOWN     → không xác định
                              └── THIRD_PARTY → tiếp tục Case 2A flow

  Case 2A flow:
      │
      ▼
  Task Classifier (LLM) → PRE_DUE / OVERDUE / NO_REMINDER
      │
      ├── NO_REMINDER → vi phạm luôn
      │
      └── PRE_DUE hoặc OVERDUE
            │
            ▼
       ┌────┴────┐
       │  3 LLM song song      │
       ├─────────┼─────────────┤
       │ Money   │ Time        │ Agreement
       │Detector │ Detector    │ Detector
       └─────────┴─────────────┘
            │
            ▼
       Rule-based Decide (money + time + actionable + !opposed)
            │
            ├── violation=True  → Response Generator (LLM) → exit
            │
            └── violation=False → exit
```

**Điểm đáng lưu ý:**
- **ML pre-filter** dùng cascade 6 model nhỏ (~10MB tổng) để skip ≥40% LLM call — tiết kiệm chi phí
- **Prompt Vietnamese** lưu ở `.prompts/*.prompt`, load thành dict `PROMPTS` ở `src/prompts.py` (read-once at import)
- **3 detector song song** nhờ Hush AI engine tự parallel
- **Rule-based decide** (Python function) thay vì LLM — deterministic, giải thích được

### 6.6. Sentiment Classifier

- Input: embedding BGE-M3 của từng turn (ONNX inference local)
- Model: MLP đơn giản (PyTorch), pre-trained với dataset nội bộ
- Threshold: agent=0.78, customer=0.9 (customer khoan dung hơn vì bức xúc là hợp lý)
- Cache: embedding được cache SQLite để tránh re-compute khi re-run

### 6.7. Output format

```json
{
  "call_id": "20260411_001234",
  "violations": [
    {
      "case": "raba",
      "violation": true,
      "category": "thieu_thoi_gian_cu_the",
      "reason": "Khách hàng không đưa mốc thời gian cụ thể",
      "timestamps": "02:15 - 02:22"
    },
    {
      "case": "sentiment_agent",
      "violation": false,
      "category": "khong_vi_pham",
      "reason": "",
      "timestamps": ""
    }
    // ... 5 case khác
  ]
}
```

---

## 7. Data Contracts giữa các module

### 7.1. ASR → Sentiment

Transcript JSON (đã mô tả ở 5.6) là interface giữa hai module. Class `Conversation` trong module Sentiment auto-detect field `transcribed_vads` và load trực tiếp:

```python
conversation = Conversation.load("path/to/asr_output.json")
```

Không cần adapter layer. Nếu ASR đổi format → chỉ cần update `Conversation.load()`.

### 7.2. Sentiment → Downstream (QC dashboard)

Schema `call_scoring` (đã mô tả ở 6.7) là contract với hệ thống QC review. Thay đổi schema phải version (ví dụ `schema_version: "1.0"`).

---

## 8. Cross-cutting Concerns

### 8.1. Config

| Layer | File | Nội dung |
|---|---|---|
| Secret | `.env` | API key, endpoint URL, Keycloak credentials — **không commit** |
| Resource | `resources.yaml` | Khai báo LLM/embedding/langfuse cho Hush AI |
| Code config | `src/config.py` | Constant (LLM_RESOURCE_KEY, threshold, path) |

### 8.2. Observability

- **Langfuse**: trace mọi LLM call (prompt, response, token, cost, latency). Filter bằng tag `call_id`, `case_name`.
- **Metrics**: Prometheus exporter (TBD) cho throughput, latency per case
- **Logging**: structlog JSON format, forward lên ELK

### 8.3. Secrets Management

- Keycloak integration cho LLM API key (token refresh tự động)
- `.env` chỉ dùng ở dev; production dùng Vault/K8s secret

### 8.4. Deployment (dự kiến)

| Component | Runtime | Scaling |
|---|---|---|
| ASR worker | Container GPU (T4/A10) | Horizontal theo queue depth |
| Sentiment worker | Container CPU (có ONNX) | Horizontal theo queue depth |
| LLM | External API (Claude via Databricks) | N/A |
| Queue | Kafka / Redis Stream | Managed |

Hai module tách container riêng vì GPU của ASR đắt, Sentiment không cần GPU. Tách để scale độc lập.

### 8.5. Error Handling

- LLM call: retry 3 lần exponential backoff (config trong `resources.yaml`)
- ASR failure: cuộc gọi đánh dấu `failed`, chuyển queue retry
- Sentiment case failure (1 trong 7): các case khác vẫn chạy, case failed trả `error` thay vì block pipeline

---

## 9. Yêu cầu phi chức năng

| Yêu cầu | Mục tiêu |
|---|---|
| **Latency (E2E audio → scoring)** | p95 ≤ 60s cho cuộc gọi 5 phút |
| **Throughput** | ≥ 1000 cuộc/giờ/cụm |
| **Độ chính xác QC** | ≥ 85% agreement với QC nhân viên |
| **Chi phí LLM** | ≤ $0.015/call trung bình |
| **Availability** | 99.5% (7×12h business) |
| **Data retention** | Audio 90 ngày, transcript 2 năm, scoring vĩnh viễn |
| **Compliance** | Không log số thẻ/CCCD vào trace; mask PII trước khi gửi LLM external |

---

## 10. Rủi ro & Giảm thiểu

| Rủi ro | Mức độ | Giảm thiểu |
|---|---|---|
| LLM external downtime | Cao | Fallback sang LLM thứ 2 (GPT-4o) qua config `resource=[list]` với ratio |
| Chi phí LLM tăng vọt | Trung bình | ML pre-filter; monitor cost/call; alert khi vượt ngưỡng |
| ASR sai → sentiment sai | Trung bình | Đo WER, giữ audio gốc để re-process; sentiment có threshold cao để tránh false positive |
| Drift dữ liệu (giọng mới, từ lóng mới) | Trung bình | Retrain định kỳ; QC thủ công sample 1% để phát hiện drift |
| PII leak | Cao | Prompt có instruction redact; log không chứa content raw; audit định kỳ |

---

## 11. Giới hạn & Roadmap

### 11.1. Giới hạn hiện tại

- Chỉ hỗ trợ tiếng Việt
- Chưa có UI review (đang dùng notebook)
- 7 case cứng trong code, thêm case mới phải deploy code

### 11.2. Roadmap

| Giai đoạn | Mục tiêu |
|---|---|
| **Q2/2026** | Production hoá, UI review, dashboard metrics |
| **Q3/2026** | Plugin system cho case mới (khai báo rule qua config thay vì code) |
| **Q4/2026** | Hỗ trợ đa ngôn ngữ (tiếng Anh cho khách VIP) |

---

## 12. Phụ lục

### 12.1. Tham chiếu repo

| Repo | Đường dẫn |
|---|---|
| ASR | `D:\callbot-assistant\mle-ds2-pilot\asr` |
| Sentiment | `D:\callbot-assistant\mle-ds2-pilot\analyze` |
| Hush AI | `D:\platform.hush-ai` |

### 12.2. Tham khảo

- Hush AI documentation: `D:\platform.hush-ai\README.md`
- QC business rule spec: (link Confluence — TBD)
- Langfuse dashboard: (link internal — TBD)

### 12.3. Lịch sử phiên bản

| Version | Ngày | Người | Thay đổi |
|---|---|---|---|
| 0.1 | 2026-04-20 | thanglq12 | Draft đầu tiên |
