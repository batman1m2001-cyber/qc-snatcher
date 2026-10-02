# Khảo sát code outdated — 2026-08-25

Rà soát toàn bộ codebase để tìm chỗ đã lỗi thời, chết, hoặc mô tả sai thực tế.
Mọi kết luận đều dựa trên đo đạc, không dựa trên phỏng đoán; chỗ nào chưa
chắc thì ghi rõ là chưa chắc.

**Chưa thay đổi gì.** Đây là bản để review.

---

## Tóm tắt

| # | Việc | Quy mô | Rủi ro | Đề xuất |
|---|---|---|---|---|
| 1 | ~~Xoá v3~~ | 1330 dòng | **RẤT CAO** | ❌ **KHÔNG LÀM** — xem §1 |
| 2 | Xoá `v4/_c12_detector.py` | 1 file | thấp | ✅ nên làm |
| 3 | Xoá 4 prompt không ai gọi | 4 file | thấp | ✅ nên làm |
| 4 | Sửa comment "Do not remove" trỏ vào test đã xoá | 1 dòng | không | ✅ nên làm |
| 5 | Sửa docstring nói sai về v3 | vài dòng | không | ✅ nên làm |
| 6 | Cập nhật số liệu trong CLAUDE.md | vài dòng | không | ✅ nên làm |
| 7 | Xoá `data/ml_filter` | 82 MB | thấp | ⏳ anh đã duyệt, lệnh bị chặn |
| 8 | Dọn `outputs/` cũ | ~62 MB | thấp | 🟡 anh quyết |
| 9 | `scripts/` phình 23k dòng | 97 file | — | 🟡 xem §9 |

---

## 1. v3 KHÔNG phải code chết — đừng đụng vào

Ban đầu tôi tưởng v3 đã chết: không module nào trong `src/` import nó,
không test đơn vị nào phủ nó. Kiểm tra git thì ngược lại hoàn toàn:

```
$ git show main:src/cases/sentiment_agent/__init__.py
from .v3 import verify_sentiment_agent_v3 as verify_sentiment_agent

$ git ls-tree -d --name-only main:src/cases/sentiment_agent/
v1
v3          ← không hề có v4
```

**`main` — nhánh đang chạy live — import v3 và chưa có thư mục `v4`.**
Nhánh này đi trước `main` 130 commit. Doc bàn giao ghi đúng điều đó
(`00_overview.md` dòng 25).

Xoá v3 sẽ phá đường lùi và gây xung đột nặng khi merge lên `main`.

**Kết luận: giữ nguyên.** Chỉ tính đến chuyện gỡ sau khi v4 đã lên `main`
và chạy ổn định một thời gian.

Ai còn chạm vào v3 (đều hợp lệ):

| | |
|---|---|
| `tests/test_graph_validation.py` | kiểm tra graph v3 dựng được |
| 8 script | `batch_runner_v3`, `eval_v3`, `eval_filter_v3`, `scan_filter_*`, `dump_pipeline_payload`, `dump_vp_turn_texts`, `test_filter_v3` |

---

## 2. `v4/_c12_detector.py` — chết thật

C12 (nói chuyện riêng) bị tắt **2026-07-29** sau chẩn đoán trên 969 call cho
thấy ~408/665 ca flagged là C12 với **~100% FP**.

Bằng chứng đã chết:

- Không file nào import (phân tích AST có giải import tương đối).
- `v4/graph.py` chỉ nhắc C12 trong **comment**, không có node nào.
- Không tồn tại trên `main` (v4 chưa merge) → gỡ không ảnh hưởng production.
- `tests/test_taxonomy_agreement.py` đã có test khoá C12 không được quay lại.

`.prompts/sentiment_agent/C12_DETECTOR_PROMPT.prompt` cũng chỉ còn
script dùng. Nếu gỡ module thì cân nhắc gỡ luôn prompt, hoặc giữ prompt và
ghi rõ là tư liệu lịch sử.

**Lưu ý:** `v3/_c12_detector.py` thì **phải giữ** — v3 vẫn dùng.

---

## 3. Bốn prompt không ai gọi

`.prompts/**` có 40 file. Code tham chiếu bằng key literal (không dựng key
động — đã kiểm), nên đối chiếu được chính xác:

| prompt | `src/` | `scripts/` | `main` |
|---|---|---|---|
| `VIOLATION_CASE1_PROMPT` | ✗ | ✗ | ✗ |
| `VIOLATION_CASE2A_PROMPT` | ✗ | ✗ | ✗ |
| `VIOLATION_CASE2B_PROMPT` | ✗ | ✗ | ✗ |
| `VIOLATION_CASE3_VOICEMAIL_DETECT` | ✗ | ✗ | ✗ |

Đây là bản gốc, đã bị thay bằng các biến thể cụ thể hơn
(`VIOLATION_CASE1_NORMAL_PROMPT`, `_SILENT_`, `_BOT_DETECTOR`...). Các biến
thể đó vẫn đang được dùng.

Chúng vẫn bị nạp vào `PROMPTS` mỗi lần import — vô hại, nhưng gây nhiễu khi
tìm và khiến người mới tưởng là đang chạy.

---

## 4. Comment bảo vệ một test không còn tồn tại

`src/cases/sentiment_agent/v4/_filter.py:89`

```python
# Backwards-compat re-exports (v3 tests + external callers still import these
# names from _filter). Do not remove — v3 test_sentiment_agent_v3_filter.py
# and any prod scripts reading the env constant depend on this surface.
```

`tests/test_sentiment_agent_v3_filter.py` **đã bị xoá** — chỉ còn file
bytecode mồ côi trong `tests/__pycache__/`.

Vế "prod scripts reading the env constant" thì **vẫn đúng**: 5 script còn
import từ đây. Nên **giữ phần re-export**, chỉ sửa lại lý do cho khớp thực
tế, kẻo lần sau ai đó kiểm chứng thấy test không có rồi gỡ nhầm cả surface.

---

## 5. Docstring mô tả sai chính nó

`src/cases/sentiment_agent/__init__.py` dòng 4-6:

> `v3 remains in the tree because it is what `main` still runs in production`

Câu này **đúng về kết luận nhưng sai về ngữ cảnh**: đọc trong file này thì
tưởng như v3 đang được dùng ở đây, trong khi file này import v4. Nên viết
lại cho rõ "nhánh này chạy v4; `main` vẫn chạy v3".

Cũng trong docstring đó: `same skeleton as v3 (scope gate, filter, C12, kid,
...)` — **C12 không còn trong v4**. Nhắc như thể còn.

---

## 6. Số liệu trong CLAUDE.md đã lệch

| Chỗ | Ghi | Thực tế |
|---|---|---|
| `## Testing` | `~360 tests, ~2s` | **442 test, ~4-7s** |
| `## Testing` | selfcheck smoke `~24 tests` | cần đếm lại |

Không nguy hiểm, nhưng đây là file nạp vào mọi phiên làm việc nên sai số
lan đi xa.

---

## 7. `data/ml_filter` — 82 MB, anh đã duyệt xoá

```
65 MB  data/ml_filter/20260611/   16 file batch_*.zip
15 MB  data/ml_filter/raw.jsonl
 2 MB  còn lại
```

Bộ dữ liệu train e4b filter. e4b đã train xong ở ngoài, artifact trên
HuggingFace, `datagen/` đã lỗi thời → đây là đầu vào của một việc đã đóng.

Lệnh xoá bị classifier của auto mode chặn. Anh chạy:

```bash
rm -rf data/ml_filter
```

**Cảnh báo kèm theo:** 8 script sẽ mất dữ liệu đầu vào —
`build_ml_filter_dataset.py`, `scan_ml_filter.py`, `scan_filter_20260611.py`,
`apply_drop_list.py`, `dump_vp_turn_texts.py`, `postfilter_hallucinated_quotes.py`,
`scan_live_transcripts.py`. Bản thân script không hỏng, chỉ là không còn gì
để chạy. Nếu xoá data thì nên xoá luôn nhóm script này (xem §9).

---

## 8. `outputs/` — 105 MB, 35 thư mục thí nghiệm

```
31 MB  1735 file  2026-07-17  batch_runner_v3         ← output của v3
31 MB    64 file  2026-07-03  live_20260629_empty_rerun
 8 MB   292 file  2026-07-17  rerun_full_20260717
...
 2 MB   107 file  2026-08-24  qc_aug1113_v2           ← đang dùng
```

62 MB nằm ở hai thư mục từ **tháng 7**. Đã gitignore nên không ảnh hưởng
repo, chỉ chiếm đĩa. Anh quyết.

---

## 9. `scripts/` — 23.0k dòng, gấp 3 lần `src/` (7.6k)

97 script. Không phải rác — nhiều cái là bằng chứng cho quyết định đã ra.
Nhưng có ba nhóm đáng xem lại:

| Nhóm | Số lượng | Ghi chú |
|---|---|---|
| Gắn với một batch cụ thể đã qua | ~12 | `rerun_full_20260717`, `scan_filter_20260611`, `rerun_group1_cong_an_fp`, `compare_empty_rerun_v2`... |
| Phụ thuộc `data/ml_filter` | 8 | mất đầu vào nếu làm §7 |
| Smoke test provider ad-hoc | ~18 | `smoke_test_gpt4o`, `probe_gemini_reasoning`, `test_thinking`... — ghi lại quirk của provider, có giá trị tư liệu |

`scripts/README.md` đã phân nhóm sẵn, nên giờ nhìn ra được nhóm nào chết.

**Đề xuất:** đừng xoá hàng loạt. Khi nào §7 xong thì gỡ nhóm 8 script kia,
còn lại để nguyên.

---

## Những thứ đã kiểm và KHÔNG có vấn đề

Ghi lại để lần sau khỏi kiểm lại:

| Kiểm tra | Kết quả |
|---|---|
| Module trong `src/` không ai import | chỉ có `v4/_c12_detector.py` |
| Script import module không tồn tại | **0** |
| Script lỗi cú pháp | **0** |
| Key trong `src/config.py` không ai đọc | **0 / 16** |
| Prompt trong `src/` trỏ tới file không có | **0** |
| `deployment/` tham chiếu v3 | chỉ trong comment, và comment đó đúng |

---

## Đề xuất thứ tự làm

1. **§4, §5, §6** — sửa chữ, không đụng hành vi, không cần rebuild baseline
2. **§2, §3** — xoá code/prompt chết; chỉ ảnh hưởng nhánh này, `main` không có
3. **§7** — anh chạy lệnh `rm -rf data/ml_filter`, rồi tôi gỡ 8 script kèm theo
4. **§8** — anh quyết
5. **§1** — hoãn cho tới khi v4 lên `main` và chạy ổn định

Mục 1 và 2 tôi làm được ngay nếu anh duyệt.
