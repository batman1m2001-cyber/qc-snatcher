# Use Case POC — QC Call Center: Case RABA

## 1. Bối cảnh

Hệ thống Quality Control (QC) cho các cuộc gọi thu hồi nợ (collection calls). Sau mỗi cuộc gọi, agent (nhân viên thu hồi nợ) **gán thủ công một `call_code`** phản ánh kết quả cuộc gọi — ví dụ khách hàng hứa trả, bên thứ 3 hứa trả, không liên lạc được, v.v.

Vấn đề: call_code do agent tự gán có thể sai (vô tình hoặc cố ý để đạt KPI). QC cần một hệ thống tự động **xác minh call_code có đúng với nội dung cuộc gọi thực tế hay không**, dựa trên transcript của cuộc gọi.

POC này tập trung vào **một case duy nhất** — **Case RABA** — để vendor demo năng lực agent platform giải quyết bài toán.

## 2. Phạm vi Case RABA

Case RABA kích hoạt khi agent gán một trong hai call_code sau:
- `Hua_tra` — **Khách hàng tự hứa trả** nợ (Case 2A)
- `Ben_thu_3_hua_tra` — **Bên thứ 3** (người nhà/người quen) hứa trả thay (Case 2B)

**Câu hỏi cần trả lời:** Cuộc gọi có thực sự ghi nhận được cam kết trả nợ hợp lệ tương ứng với call_code đã gán hay không?

- Nếu **có** → không vi phạm
- Nếu **không** → vi phạm (agent gán sai call_code)

## 3. Tiêu chí Vi phạm / Không Vi phạm

### 3.1. Case 2A — `call_code = "Hua_tra"`

Một cam kết trả nợ **hợp lệ** cần có **đồng thời 5 điều kiện**:

| # | Điều kiện | Giải thích |
|---|---|---|
| C1 | **Có nhắc nợ** | Cuộc gọi phải có nội dung nhắc nợ — có thể là nhắc **trước hạn** (loan chưa tới hạn) hoặc nhắc **quá hạn** (loan đã trễ hạn). Nếu cuộc gọi hoàn toàn không nhắc nợ (ví dụ: chỉ xác minh thông tin, khiếu nại hệ thống) → vi phạm |
| C2 | **Có đề cập số tiền** | Transcript phải có mention về tiền — số tiền nợ, số tiền sẽ trả, hoặc nghĩa vụ tài chính. Có thể đến từ agent hoặc customer |
| C3 | **Có đề cập thời gian trả** | Phải có mốc thời gian gắn với hành động trả nợ (agent đề xuất hoặc customer cam kết) |
| C4 | **Thời gian phải "actionable"** (chỉ áp dụng khi nhắc quá hạn) | Với loan đã quá hạn, thời gian cam kết phải đủ cụ thể để hành động. "Lúc nào rảnh", "khi nào có tiền" → **không actionable** → vi phạm |
| C5 | **Khách hàng KHÔNG phản đối** | Khách không được **phủ nhận khoản vay** hoặc **từ chối trách nhiệm trả nợ** tính đến cuối cuộc gọi |

→ Thiếu bất kỳ điều kiện nào trong C1–C4, HOẶC vi phạm C5 = **Vi phạm**. Đủ cả 5 = **Không vi phạm**.

### 3.2. Case 2B — `call_code = "Ben_thu_3_hua_tra"`

Cần thêm **bước xác minh danh tính người nghe máy** trước khi áp dụng C1–C5:

| Danh tính người nghe | Kết luận |
|---|---|
| **CUSTOMER** — chính là chủ nợ | **Vi phạm** (agent gán sai code, đáng ra phải là `Hua_tra`) |
| **UNKNOWN** — không đủ thông tin xác định | **Không xác định** (không chấm vi phạm, cần reviewer xem lại) |
| **THIRD_PARTY** — người nhà/người quen của chủ nợ | Tiếp tục kiểm tra C1–C5 như Case 2A |

**Nhận biết THIRD_PARTY:**
- Customer nói về người khác: "nó là con tôi", "chồng tôi", "anh ấy không có nhà"
- Customer dùng ngôi thứ 3: "để tôi nhắc nó", "tôi sẽ bảo anh ấy"
- Agent hỏi mối quan hệ ("anh là chồng chị X à?") và customer xác nhận/không phản đối
- **Không khớp giới tính**: agent gọi tên nữ nhưng customer xưng "anh" (hoặc ngược lại)
- Customer nói "tôi hỗ trợ trả" — xác định vai trò hỗ trợ, không phải chính chủ
- Agent nói khoản vay "của anh X" (khác tên người đang nghe máy)

**Lưu ý quan trọng:** Customer dùng "tôi trả", "khoản vay của tôi" **không đủ** để kết luận là chính chủ — vợ/chồng/người nhà thường dùng ngôi 1 khi nói về khoản vay gia đình.

### 3.3. Định nghĩa chi tiết "phản đối" (C5)

| Loại phát ngôn của customer | Có phản đối? |
|---|---|
| "Tôi không vay khoản này", "không phải của tôi", "đừng gọi cho tôi nữa" | ✅ Phản đối |
| "Ừ", "vâng", "dạ", "ok", "được", "rồi rồi", "ừ ừ", "vâng vâng" | ❌ Không phản đối |
| "Để tôi xem đã", "tôi bận, gọi lại sau" | ❌ Không phản đối (né tránh ≠ phủ nhận) |
| Ban đầu thắc mắc "tôi không biết khoản này" → cuối chấp nhận "à vâng, tôi sẽ chuyển" | ❌ Không phản đối (**ưu tiên phản hồi cuối**) |
| Ban đầu "tôi không vay" → cuối vẫn "tôi không vay, đừng gọi nữa" | ✅ Phản đối |
| "Chuyển luôn đây đây", "để tôi chuyển", "tôi sẽ trả" | ❌ Không phản đối (cam kết hành động) |

**Quy tắc trọng số:** Phản hồi **cuối cùng** của customer có trọng số cao hơn phản ứng ban đầu. Khách hàng có quyền thắc mắc lúc đầu — chỉ tính là phản đối nếu phủ nhận kéo dài đến cuối cuộc gọi.

### 3.4. Định nghĩa "actionable time" (C4, chỉ cho nhắc quá hạn)

| Biểu thức thời gian | Actionable? |
|---|---|
| "hôm nay", "mai", "chiều nay", "3h chiều", "ngày 15", "15/06", "tối nay" | ✅ Có |
| "luôn đây đây", "chuyển ngay", "bây giờ luôn", "trong hôm nay" | ✅ Có |
| "lúc nào rảnh", "khi nào có tiền", "để hôm nào", "sang tuần", "đợi lương về", "qua tết" | ❌ Không |
| "cuối tháng", "đầu tháng" (mốc chu kỳ mơ hồ) | ❌ Không |

### 3.5. Ví dụ minh hoạ

**Ví dụ 1 — KHÔNG vi phạm** (Case 2A, quá hạn)
```
Agent: Khoản vay 5 triệu của anh đã quá hạn 3 ngày, anh thu xếp thanh toán giúp em.
Customer: Chiều nay tôi chuyển.
```
→ C1=nhắc quá hạn ✓, C2=5 triệu ✓, C3=chiều nay ✓, C4=actionable ✓, C5=không phản đối ✓

**Ví dụ 2 — VI PHẠM** (thiếu thời gian actionable)
```
Agent: Khoản 10 triệu của anh quá hạn rồi, khi nào anh trả?
Customer: Khi nào có tiền tôi trả.
```
→ C4=không actionable → **vi phạm**

**Ví dụ 3 — VI PHẠM** (khách hàng phản đối)
```
Agent: Em gọi về khoản vay 5 triệu ngày 25 đến hạn.
Customer: Tôi không vay khoản này, đừng gọi cho tôi nữa.
```
→ C5=phản đối → **vi phạm**

**Ví dụ 4 — VI PHẠM** (Case 2B, sai danh tính)
```
call_code = "Ben_thu_3_hua_tra"
Agent: Em chào anh Minh, em gọi về khoản vay của anh.
Customer: Ừ anh nghe đây, anh sẽ trả tuần sau.
```
→ Người nghe là CUSTOMER (chính chủ) → agent gán sai code → **vi phạm**

**Ví dụ 5 — KHÔNG vi phạm** (Case 2B, bên thứ 3)
```
call_code = "Ben_thu_3_hua_tra"
Agent: Em chào anh, cho em hỏi anh Tuấn có ở đó không ạ?
Customer: Nó là em trai tôi, đang đi làm. Để tôi đóng 3 triệu cho nó mai.
```
→ Identity=THIRD_PARTY, C1=OVD ✓, C2=3 triệu ✓, C3=mai ✓, C4=actionable ✓, C5=không phản đối ✓

## 4. Dữ liệu đầu vào

### 4.1. Transcript (JSON)

Transcript đã được diarize (phân biệt agent/customer) và chia segment theo VAD:

```json
{
  "transcribed_vads": [
    {
      "start": 0.066,
      "end": 7.87,
      "duration": 7.804,
      "content": "alo anh Minh đúng không, em gọi từ Win",
      "role": "agent"
    },
    {
      "start": 8.12,
      "end": 10.45,
      "duration": 2.33,
      "content": "ừ anh nghe đây",
      "role": "customer"
    }
  ]
}
```

Field bắt buộc:
- `content`: text tiếng Việt
- `role`: `"agent"` hoặc `"customer"`
- `start`, `end`, `duration`: giây (float) tính từ đầu cuộc gọi

### 4.2. Metadata cuộc gọi

```json
{
  "call_id": "20260411_001234",
  "call_code": "Hua_tra"
}
```

`call_code` trong POC này chỉ có 2 giá trị: `"Hua_tra"` hoặc `"Ben_thu_3_hua_tra"`.

### 4.3. Đặc điểm dữ liệu

- Ngôn ngữ: **tiếng Việt**, văn phong thoại (informal), nhiều từ viết tắt, rút gọn
- Có thể chứa lỗi ASR: thiếu từ, sai chính tả, câu bị cắt
- Độ dài cuộc gọi: 30 giây – 10 phút (trung bình ~3–5 phút, 30–80 turns)
- Agent nói nhiều hơn customer (~70/30)

## 5. Dữ liệu đầu ra (mong đợi)

```json
{
  "call_id": "20260411_001234",
  "case": "raba",
  "violation": true,
  "category": "thieu_thoi_gian_cu_the",
  "reason": "Khách hàng không đưa ra mốc thời gian cụ thể để trả nợ — chỉ nói 'khi nào có tiền'",
  "evidence_timestamps": [
    { "start": 45.2, "end": 48.9, "text": "khi nào có tiền tôi trả" }
  ]
}
```

**Yêu cầu output:**
- `violation`: `true` / `false` / `null` (null cho trường hợp UNKNOWN của Case 2B)
- `category`: nhóm lý do vi phạm (ví dụ: `thieu_tien`, `thieu_thoi_gian`, `thieu_thoi_gian_cu_the`, `khach_phan_doi`, `sai_danh_tinh`, `khong_nhac_no`, `khong_vi_pham`)
- `reason`: câu giải thích ngắn bằng tiếng Việt (cho reviewer đọc)
- `evidence_timestamps`: các đoạn transcript làm bằng chứng (giúp reviewer tua đến đúng chỗ)

## 6. Yêu cầu phi chức năng

| Yêu cầu | Mục tiêu |
|---|---|
| **Độ chính xác** | ≥ 85% agreement với QC nhân viên trên tập test |
| **Recall vi phạm** | ≥ 90% (ưu tiên phát hiện sót hơn là báo nhầm) |
| **Latency** | ≤ 20 giây/cuộc gọi (p95) |
| **Throughput** | ≥ 500 cuộc/giờ |
| **Observability** | Trace được các bước xử lý của agent (input/output từng bước) |
| **Cost** | Báo cáo chi phí LLM trung bình/call |
| **Ổn định** | Tự retry khi lỗi tạm thời, không crash pipeline toàn bộ |
| **Giải thích được** | Mỗi kết luận vi phạm phải có evidence/reason cụ thể, không được "hộp đen" |

## 7. Khối lượng POC

- **Tập test**: 300 cuộc gọi đã có transcript + call_code + ground truth chấm tay bởi QC
  - 100 `Hua_tra` vi phạm / 100 `Hua_tra` không vi phạm
  - 50 `Ben_thu_3_hua_tra` vi phạm / 50 không vi phạm
- **Đa dạng**: bao gồm cả nhắc trước hạn và quá hạn, đủ các nhóm vi phạm C1–C5
- **Thời gian POC**: 3 tuần
- **Báo cáo cuối POC**: confusion matrix, precision/recall từng category, cost/latency thực tế, ví dụ fail case

## 8. Ngoài phạm vi POC

- ASR (audio → transcript): dữ liệu transcript được cung cấp sẵn
- Các case vi phạm khác ngoài RABA (sentiment, disclosure, card number, phone source, hangup)
- UI review kết quả — team nội bộ tự xây
- Tích hợp production — sau POC mới bàn

## 9. Tiêu chí nghiệm thu

POC thành công nếu thoả **tất cả** các điều kiện:
1. Accuracy ≥ 85%, recall vi phạm ≥ 90% trên tập test
2. Latency p95 ≤ 20s, throughput ≥ 500 call/giờ
3. Output đúng schema ở mục 5, có evidence cụ thể
4. Vendor demo được khả năng mở rộng sang case khác (không cần triển khai, chỉ trình bày cách tiếp cận)
5. Chi phí LLM/call ở mức chấp nhận được (bàn cụ thể ở buổi demo)
