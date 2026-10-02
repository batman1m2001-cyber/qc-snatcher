# UAT 03–08/08/2026 — Tổng hợp điểm chưa nhất quán trong kết quả chấm của BU

Tiêu chí: **Thái độ ĐTV** (sentiment_agent). Gửi BU để chốt lại chính sách.

> Lưu ý cách đọc: giai đoạn hiện tại `thái độ warning` = `Thái độ cao` của hệ
> thống, nên các case BU ghi "bắt đúng nhưng để ngưỡng warning" được tính là
> **AI bắt đúng**, không nằm trong danh sách sai dưới đây.

---

## 1. Tóm tắt

| Chỉ số | Số lượng |
|---|---|
| Cuộc gọi UAT | 272 |
| Cuộc gọi BU đã chấm tay | 259 |
| BU chấm **Tích cực** nhưng AI bắt lỗi (FP) | **203** |
| BU xác nhận có vi phạm | 56 |

Phân rã 203 FP theo nguyên nhân:

| Nguyên nhân | Số FP | Thuộc về |
|---|---|---|
| Chính sách BU đã đổi / mâu thuẫn nhau | **187** | 🔴 **Cần BU chốt lại** |
| Lỗi ASR / tạp âm (AI nghe sai từ) | 16 | 🔵 Team AI tự sửa |

Phân rã 187 case chính sách theo nhóm:

| Nhóm chính sách | Số FP |
|---|---|
| Lịch sự / xin phép ngắt máy | 44 |
| Nghiệp vụ thu nợ (nhắc nợ, hứa hẹn, khả năng trả) | 35 |
| Nhóm từ "bình tĩnh" | 27 |
| Hỏi mối quan hệ / xác minh thông tin | 17 |
| Yêu cầu phối hợp / lắng nghe | 6 |
| Chưa phân nhóm rõ | 58 |

**Vấn đề lớn nhất**: có **16 chính sách** mà trong cùng đợt UAT này, BU chấm
**cả hai chiều** — cùng một mẫu câu, cuộc này bắt lỗi, cuộc kia không.

---

## 2. Cách tổng hợp

1. Lấy corpus tại commit **trước** bản sửa ngày 13/08 (`acb66c5^`) — đây đúng là
   bộ chính sách đã chạy trên UAT.
2. Với mỗi FP, xác định **chính xác** chính sách đã kích hoạt: model trả về
   `cited_positives` dạng `P1..Pn` — đây là số thứ tự trong pool truy hồi, ánh xạ
   **1:1** sang `retrieval.positives`. Từ đó tra ngược về đúng entry trong corpus
   `acb66c5^` bằng cách so **từng biến thể** (tách bằng ` | `) — pool chỉ nối các
   biến thể *được truy hồi* nên so nguyên chuỗi sẽ trượt. **293/293 dòng tra được,
   0 dòng thất bại**; 2 case thiếu citation dùng entry rank-0.
3. Đối chiếu `description` của chính sách — phần lớn được viết **từ chính nhận
   xét của BU ở các đợt trước** (nhiều mô tả ghi rõ "theo QC…").

Nghĩa là: khi AI bắt theo chính sách đó mà BU nói "bắt sai", tức là BU đang
**đảo ngược quy định do chính BU đặt ra trước đó**.

📎 **File gửi BU**: [`UAT_20260803_0808_FP_POLICY.xlsx`](UAT_20260803_0808_FP_POLICY.xlsx)
— 187 call, **114 chính sách**, 4 sheet:

| Sheet | Nội dung |
|---|---|
| `Tổng kết` | số liệu đầu mục |
| `Chi tiết` | 293 dòng (call × chính sách) — sheet để BU lọc / pivot |
| `Theo chính sách` | 114 dòng, xếp theo số call bị bắt sai; dòng tô cam = chính sách **vẫn còn hiệu lực** |
| `Theo call` | 187 dòng, mỗi cuộc gọi một dòng |

Sinh lại bằng: `uv run python scripts/eval/build_bu_fp_report.py`

---

## 3. Nhóm A — Cùng một chính sách, BU chấm ngược nhau trong cùng đợt

Đây là bằng chứng rõ nhất. Cùng mẫu câu, cùng đợt chấm, hai kết luận trái nhau.

### A1. Hỏi "trao đổi lịch sự được không"

| Call ID | Câu thoại | BU chấm | Nhận xét BU |
|---|---|---|---|
| 545808001 | `anh trao đổi lịch sự được không anh` | **Vi phạm** | "Bắt đúng, **bắt lỗi nếu CB hỏi kh có trao đổi lịch sự được không**" |
| 540042219 | `...trao đổi mình tên lịch sự được không chị` | **Vi phạm** | "**bắt vào lỗi thái độ warning khi Cb hỏi KH có lịch sự trao đổi được không**" |
| 537859039 | `mình trao đổi lịch sự lại được không anh` | **Vi phạm** | "bắt đúng, Cb không hỏi kh có lịch sự trao đổi được không" |
| 539763327 | `chưa trao đổi lịch sự được cháu xin phép ngắt máy` | **Tích cực** | "Cb xin phép ngắt máy khi nói KH 'chưa lịch sự trao đổi' **không bắt lỗi**" |
| 544777143 | `mình vui lòng trao đổi lịch sự giúp em` | **Tích cực** | "CB đưa ra câu hỏi nhằm điều hướng KH… dùng cụm từ lịch sự như 'giúp em'" |

**Câu hỏi cần chốt**: hỏi KH "trao đổi lịch sự được không" là vi phạm hay không?
Nếu có softener ("vui lòng", "giúp em") thì được miễn — vậy ranh giới softener
là gì? Nếu đi kèm xin phép ngắt máy thì được miễn — vậy 545808001 khác gì?

### A2. Nhóm từ "bình tĩnh"

| Call ID | Câu thoại | BU chấm | Nhận xét BU |
|---|---|---|---|
| 542669899 | `chị trao đổi bình tĩnh đi chị nhá` | **Tích cực** | "Không bắt lỗi với nhóm từ 'bình tĩnh'" |
| (5 case) | `mình có bình tĩnh để trao đổi được không ạ` | **Tích cực** | "Không bắt lỗi với tất cả câu Cb nói về việc bình tĩnh **kể cả là câu hỏi** hay câu chào kết thúc" |

Chính sách trong corpus (viết từ nhận xét BU đợt trước):

> "AGENT đặt **CÂU HỎI** 'mình có BÌNH TĨNH để trao đổi được không' — **theo QC
> được nói statement định vị, KHÔNG được [hỏi]'"

**Đảo ngược trực tiếp**: trước đây BU quy định dạng câu hỏi là vi phạm, nay BU
nói kể cả câu hỏi cũng không bắt lỗi.

### A3. Trong cùng một nhận xét, BU nêu hai chuẩn khác nhau

| Call ID | Nhận xét BU |
|---|---|
| 541445561 | "Không bắt lỗi về nhóm từ 'tập trung trao đổi' **nhưng bắt lỗi với câu Cb hỏi Trao đổi lịch sự**" |
| 539763327 | "Cb xin phép ngắt máy khi nói KH 'chưa lịch sự trao đổi' **không bắt lỗi**" |

Hai case cùng đợt, cùng cụm "trao đổi lịch sự", kết luận ngược nhau.

### A4. Các chính sách còn lại BU chấm hai chiều

| Chính sách | FP | Vi phạm |
|---|---|---|
| `tôi thấy mình trao đổi rất là bất lịch sự… xin phép ngắt máy` | 5 | 1 |
| `mình trao đổi chưa lịch sự bên em xin phép ngắt máy` | 4 | 1 |
| `nếu mình không trao đổi lịch sự thì em xin phép ngắt máy nhá` | 3 | 1 |
| `anh chị trao đổi lịch sự được không?` | 3 | 1 |
| `anh có hiểu câu hỏi không anh` | 1 | 2 |
| `đừng hứa hẹn nữa nhé` | 1 | 1 |
| `cố tình kéo dài thời gian` | 1 | 1 |
| `Kêu khó khăn mà vẫn đi vay được cũng giỏi đấy` | 1 | 1 |

Tổng: **16 chính sách** bị chấm hai chiều trong cùng đợt UAT.

---

## 4. Nhóm B — BU đảo ngược quy định do chính BU đặt ra

Các chính sách này được thêm vào corpus **từ nhận xét của BU ở các đợt trước**.
Đợt này BU nói "bắt sai".

Số liệu dưới đây là **quy kết chính xác** theo `cited_positives`, không phải ước lượng.

| Chính sách đã kích hoạt | Nhóm corpus | Nhận xét BU đợt này | Số call | Trạng thái sau 13/08 |
|---|---|---|---|---|
| `mình có bình tĩnh để trao đổi được không ạ` | step50_20260805 | "Không bắt lỗi… **kể cả là câu hỏi**" | **17** | đã gỡ |
| `anh thấy mình tập trung trao đổi em xin phép ngắt máy gọi lại` | step46_20260805 | "Bắt sai" | **15** | ⚠️ **vẫn còn** |
| `mình là người nhà là vợ sao lại không biết…` | step12_20260711 | "Không bắt lỗi với nhóm câu đơn giản chỉ là hỏi về mối quan hệ" | **15** | ⚠️ **vẫn còn** |
| `nếu như hiện tại anh không trao đổi lịch sự được thì em xin phép ngắt máy` | step48_20260805 | "bắt sai" | **11** | đã gỡ |
| `nếu như hiện tại anh không trao đổi lịch sự được thì em xin phép ngắt máy` | step48_20260805 | "bắt sai" | **11** | đã gỡ |
| `cô là mẹ anh hoàng thì cô phải nắm rõ được thông tin chứ` | step34_20260718 | "Không bắt lỗi… hỏi về mối quan hệ" | **10** | ⚠️ **vẫn còn** |
| `nếu mà mình không trao đổi được lịch sự thì bên em xin phép là ngắt máy` | step49_20260805 | "bắt sai" | **10** | đã gỡ |
| `trao đổi bình tĩnh lịch sự được không anh` | step46_20260805 | "Không bắt lỗi với nhóm từ 'bình tĩnh'" | **9** | ⚠️ **vẫn còn** |
| `nếu mình không trao đổi lịch sự thì em xin phép ngắt máy nhá` | step49_20260805 | "bắt sai" | **7** | đã gỡ |
| `anh có bình tĩnh được không` | step49_20260805 | "Không bắt lỗi với nhóm từ 'bình tĩnh'" | **6** | → ngoại lệ |
| `em thấy vợ chồng vẫn ở với nhau mà thế nào mà lại không liên quan` | step22_20260717 | "Không bắt lỗi… hỏi về mối quan hệ" | **6** | ⚠️ **vẫn còn** |
| `mình trao đổi chưa lịch sự bên em xin phép ngắt máy` | step49_20260805 | "Không bắt lỗi với nhóm câu Cb nói 'kh nói sai sự thật'" | **6** | → ngoại lệ |

**Bản sửa 13/08 chưa giải quyết được gốc vấn đề.** Trong 114 chính sách gây FP:

| Trạng thái sau bản sửa 13/08 | Số chính sách |
|---|---|
| ⚠️ **Vẫn đang là positive** | **100** |
| Đã gỡ khỏi positives | 10 |
| Đã chuyển thành ngoại lệ (carveout) | 4 |

Bản sửa chủ yếu **thêm 210 ngoại lệ** để chặn bớt, chỉ gỡ **18 biến thể** positive.
Tức là quy định gốc vẫn còn nguyên trong hệ thống — nếu BU chốt khác đi, phải rà
lại toàn bộ 100 chính sách này.

---

## 5. Nhóm C — Khác biệt giữa đợt tháng 7 và đợt tháng 8

Đối chiếu với đợt UAT 24–26/07 (file `qc_labels.xlsx`):

| Mẫu câu | BU tháng 7 | BU tháng 8 |
|---|---|---|
| CB nói KH "không lịch sự" (dạng câu điều kiện + ngắt máy) | Call 518131985: "**Bắt lỗi mọi trường hợp** Cb nói KH 'không lịch sự'" | Không bắt lỗi dạng closing |
| Hỏi KH "có bình tĩnh được không" | Call 520601557: "CB có thể định vị thái độ KH **nhưng không nên đặt câu hỏi**" | "Không bắt lỗi… **kể cả là câu hỏi**" |

Hệ quả kỹ thuật: bộ nhãn tháng 7 và corpus hiện tại đã lệch chuẩn nhau, nên
không dùng chung một tập nhãn để đo chất lượng được nữa.

---

## 6. Nhóm D — 29 case BU không nêu lý do

29/187 case BU chỉ ghi **"bắt sai"**, "không vi phạm", hoặc để trống. Không suy
ra được quy định để cập nhật hệ thống.

**Đề nghị**: với case chấm khác AI, ghi thêm 1 câu lý do theo mẫu
"không bắt lỗi khi CB … vì …". Đây là đầu vào trực tiếp để chỉnh chính sách.

---

## 7. Không thuộc trách nhiệm BU — team AI tự xử lý

16 FP do lỗi kỹ thuật, không phải do chính sách. Liệt kê để BU thấy team đã tách bạch:

| Nguyên nhân | Ví dụ | Số case |
|---|---|---|
| ASR nghe sai từ | Call 546791587 — CB nói "thả trôi", ASR ra "trốn" | 16 |
| | Call 543316919 — "Sai asr" | |
| | Call 537842405 — "tạp âm" | |

---

## 8. Đề nghị BU chốt

| # | Câu hỏi | Liên quan |
|---|---|---|
| 1 | Hỏi KH "trao đổi lịch sự được không" — vi phạm hay không? Nếu có softener ("vui lòng", "giúp em") thì miễn, ranh giới ở đâu? | 44 FP |
| 2 | Nhóm từ "bình tĩnh" — miễn **toàn bộ** (kể cả câu hỏi, câu mệnh lệnh, câu chào kết thúc) hay chỉ miễn một số dạng? | 27 FP |
| 3 | Câu điều kiện "nếu KH không lịch sự / không hợp tác → xin phép ngắt máy" — miễn hoàn toàn? Có phụ thuộc thời điểm (ngắt sớm trong 5 lượt đầu) không? | 44 FP |
| 4 | Hỏi mối quan hệ ("là vợ sao lại không biết") — miễn hoàn toàn, hay chỉ miễn khi câu hỏi trung tính không kèm ý trách? | 17 FP |
| 5 | Nhóm nghiệp vụ thu nợ (nhắc khả năng trả, hứa hẹn nhiều lần) — ranh giới giữa "giải thích nghiệp vụ" và "gây áp lực"? | 35 FP |
| 6 | Với case chấm khác AI, BU bổ sung lý do ngắn gọn thay vì chỉ ghi "bắt sai" | 29 case |

Sau khi BU chốt, team AI cập nhật corpus **một lần** theo chuẩn mới và chạy lại
toàn bộ 272 cuộc để đo lại.

---

## Phụ lục — Dữ liệu gốc

| Nội dung | Vị trí |
|---|---|
| **187 call + đúng chính sách đã kích hoạt** (114 chính sách) | [`UAT_20260803_0808_FP_POLICY.xlsx`](UAT_20260803_0808_FP_POLICY.xlsx) |
| Script sinh file trên | `scripts/eval/build_bu_fp_report.py` |
| Nhãn BU đã chấm (259 case + nhận xét) | `scripts/eval/uat_aug38_qc_reviewed.json` |
| Corpus tại thời điểm chạy UAT | `git show acb66c5^:.prompts/sentiment_agent/corpus.yaml` |
| Corpus sau khi sửa (13/08) | `.prompts/sentiment_agent/corpus.yaml` |
| Nhãn đợt tháng 7 | `qc_labels.xlsx`, sheet `DataCuocGoi_from24072026to26072` |
