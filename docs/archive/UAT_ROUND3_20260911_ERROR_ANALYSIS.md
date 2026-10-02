# Round 3 UAT — phân tích nguyên nhân lỗi

Batch `runs/20260911_round3`, 235 cuộc gọi ngày 21–27/08/2026, đối chiếu với
`QC HVC Round 3 UAT.xlsx` (sheet `R3 UAT `, cột `KQ QC hiện tại` là ground truth).

> Chi tiết từng ca nằm ở `runs/20260911_round3/error_cases.tsv` — **không commit**,
> vì mỗi dòng chứa nguyên văn lượt nói của cuộc gọi. File này chỉ giữ số liệu,
> id entry và câu chữ chính sách.

## Tóm tắt

| | |
|---|---|
| Nguyên nhân chính | Hai decider chặn nhầm, **không phải** retrieval và **không phải** scanner |
| Tỷ lệ vá được bằng KB | **85/101 lỗi (84%)** |
| Trần lý thuyết nếu vá hết | F1 ≈ 0.94 |
| Chặn đường đo | Sàn nhiễu model 18% — lớn hơn mọi khác biệt đang bàn |

## Kết quả đo

Cả ba lần chạy trên đúng 235 cuộc này, cùng công thức QC dùng (TP = khớp
chính xác mức độ). Con số 0.642 của non-prod đã tái tạo được, nên cách tính khớp.

| lần chạy | gắn cờ | TP | P | R | F1 |
|---|---|---|---|---|---|
| non-prod | 213 | 113 | 0.531 | 0.813 | 0.642 |
| local · quoted span | 144 | 84 | 0.583 | 0.604 | 0.594 |
| local · evidence only | 128 | 79 | 0.617 | 0.568 | 0.592 |

Lưu ý khi đọc: non-prod đạt F1 cao hơn bằng cách gắn cờ 213/235 = 91% số cuộc
và **nhận đúng 0/96 cuộc sạch**. Theo accuracy thì thứ tự đảo ngược —
evidence-only 0.553, non-prod 0.481. QC gắn cờ 59% số cuộc nên lớp positive là
đa số; gán `Thái độ warning` cho tất cả được F1 0.684, cao hơn cả ba. Đây là
đặc tính của dữ liệu lệch về positive, không phải lỗi công thức — nhưng nó có
nghĩa là **F1 một mình không đủ để chọn cấu hình trên batch này**.

## Phân bố lỗi

| | số cuộc |
|---|---|
| Đúng | 130 |
| FP — QC sạch, mình bắt | 45 |
| FN — QC bắt, mình bỏ | 56 |
| Đúng vi phạm, sai mức | 4 |

## Lỗi mất ở tầng nào

Phễu của run evidence-only:

```
scanner gắn cờ       229 / 235   (97%)
sau filter decider   174          (chặn 55)
sau secondary        128          (chặn 46)
QC thực tế           139
```

| tầng | số FN |
|---|---|
| secondary decider chặn | 29 |
| filter decider chặn | 24 |
| scanner bỏ sót | 2 |
| không giải thích được | 1 |

Với FP, **0/45 trường hợp thiếu carve-out trong pool** — tri thức luôn được lấy
lên đủ. Retrieval không gây ra lỗi nào.

## Tại sao hai decider chặn nhiều

1. **Scanner gần như không lọc** — gắn cờ 97%, đúng thiết kế "scanner = recall".
   Toàn bộ gánh nặng phân loại dồn vào hai decider: phải cắt 229 xuống ~139.
2. **Hai cổng chỉ-chặn mắc nối tiếp** — cuộc bị filter decider đánh rớt thì
   secondary không bao giờ lấy lại được. Sai sót cộng dồn một chiều.
3. **KB nghiêng về phía chặn** — carveouts 498 entry / 904 variant so với
   positives 421 / 707. Mỗi vòng tune chủ yếu thêm carve-out để dập FP.
4. **26% entry không có `description`** — 163 positive + 79 carve-out vào prompt
   với `(không có mô tả)`, decider chỉ còn khớp mặt chữ.

## Cách vá

| nhóm | n | việc |
|---|---|---|
| FN · carve-out đang thắng | 38 | thêm **positive** sát nghĩa hơn |
| FN · không có mẫu nào khớp | 18 | thêm **positive** |
| FP · nghiệp vụ THN / giao tiếp / keyword | 36 | thêm **carve-out** theo lời QC |
| FP · ASR sai | 13 | ❌ không phải việc của KB |

Toàn bộ theo hướng **cộng thêm entry**, không sửa `description` đang có — tránh
rủi ro một description mới làm hỏng các ca mà entry đó đang phủ đúng.

Cảnh báo: thêm positive để gỡ FN và thêm carve-out để gỡ FP kéo ngược chiều
nhau. Mỗi vòng sẽ đẻ lỗi mới ở đầu kia, nên phải đo lại sau từng vòng.

## Mâu thuẫn trong KB

Trước khi sửa: **5 variant nằm ở cả hai phía**. Ba trong số đó không phải xung
đột chính sách mà là **lỗi soạn thảo** — dấu `|` vừa dùng làm dấu ngăn variant
vừa dùng làm dấu "hoặc" bên trong một mẫu câu, làm mẫu bị băm vụn.

### Đã sửa

| entry | vấn đề | xử lý |
|---|---|---|
| `289421d6` (positive) | Mẫu `AC là giáo viên \| công an \| ... mà lại để nợ xấu à` băm thành 10 variant rác, trong đó có `công an` đứng một mình và `... mà lại để nợ xấu à` | Tách thành từng câu đầy đủ. Variant `công an` trần là nguyên nhân FP ở ca đầu tiên trong sheet QC — CB thông báo báo công an để xác minh nghiệp vụ |
| `b1b7f1f9` (carve-out) | `có dấu hiệu trốn tránh \| né tránh \| lảng tránh` — variant 2 và 3 **mất** chữ "dấu hiệu", đúng cái tiêu chí QC nêu | Viết lại đủ: `có dấu hiệu trốn tránh \| có dấu hiệu né tránh \| có dấu hiệu lảng tránh` |

Mâu thuẫn còn **2**. Cả hai đều là xung đột chính sách thật, cần QC chốt.

### Còn chờ quyết

**A. `sao mà anh cứ trả lời mãi cái vấn đề cá nhân của mình`**

| | |
|---|---|
| POSITIVE `68f73343` | `qc_review_20260819`, warning — vi phạm nếu CB đánh giá tiêu cực cách trao đổi của KH |
| CARVE-OUT `18e12002` | `step6_20260710`, tich_cuc — business feedback dài, không áp dụng nếu là cáo buộc ngắn |

QC đưa vào làm positive tháng 8; carve-out là tuning nội bộ tháng 7. Positive
còn 13 variant khác nên bỏ riêng câu này không làm yếu quy tắc. **Chưa quyết** —
đây là QC nói ngược nhau giữa hai đợt.

**B. `trao đổi bình tĩnh lịch sự được không anh`**

| | |
|---|---|
| POSITIVE `7d9a7210` | `step46_20260805_manual_fn_batch1`, warning |
| CARVE-OUT `7d94cfd5` | `qc_review_20260819`, tich_cuc |

Nghiêng về carve-out: hai nguồn QC độc lập cùng nói không vi phạm — review
tháng 8, và phân loại round 3 ghi thẳng *"Bắt sai ngữ cảnh giao tiếp… các câu
hỏi kh (có bình tĩnh…)"*, nhóm này 8 FP. Positive đến từ đợt tune FN nội bộ.

**C. `90d8a212` — "để cho em nói nhá"**, positive warning, chọi carve-out
`b98c2f8d`. Round-3 QC: *"Cb xin phép nói lịch sự và có được sự đồng ý của KH
để làm chủ cuộc gọi"*. Bị trích 3 lần trong nhóm FP. Đề nghị chuyển sang
carveouts.

### Trùng lặp khác chưa xử lý

11 variant trùng nhau trong `positives`, 7 trong `carveouts`. Chưa có cổng chặn
trùng khi ingest — đây là mục P2-5 còn tồn trong backlog.

## Thay đổi code liên quan

`08c5c71` — retrieval truy vấn trên evidence thay vì trên cụm scanner trích
trong `reason`. Nguyên nhân: 68/235 cuộc có evidence giống hệt nhau nhưng cụm
trích khác, và cả 68 ra pool khác. Tương quan tuyệt đối:

```
query giống nhau -> pool giống nhau : 127
query giống nhau -> pool KHÁC nhau  :   0
query khác nhau                     : 100
```

Đổi sang evidence: F1 0.594 → 0.592 (hoà), nhưng retrieval trở thành tất định.
Bật mặc định, `RETRIEVAL_QUERY_FROM_EVIDENCE=false` để quay lại.

## Chạy lại

Corpus vừa đổi nên digest đổi. Postgres đang giữ `batch_id` cũ và runtime sẽ
**từ chối chấm** — phải seed lại trước.

```bash
# 1. dựng lại index + seed lại Postgres (local, không cần VPN)
#    cần Postgres + Triton shim đang chạy
uv run python -m scripts.rag

# 2. chấm (cần VPN)
uv run python main.py \
    --input-path  runs/20260911_round3/input \
    --output-path runs/20260911_round3/local_v2 \
    --skip-if-exists
```

Sau khi corpus ổn định, còn phải dựng lại selfcheck baseline — xem skill
`selfcheck`. `Result` và `Score_offset` là HARD field, đổi corpus là chúng đổi.
