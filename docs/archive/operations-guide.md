# Hướng dẫn vận hành

Tài liệu này mô tả cách vận hành hệ thống QC Analyze ở môi trường thực tế.

## 1. Mục tiêu vận hành

- Chạy batch scoring cho nhiều file ASR JSON.
- Theo dõi tiến độ, lỗi và trace.
- Giữ output JSON ở thư mục nhất quán.
- Dễ dàng đổi provider hoặc bật tracing khi cần debug.

## 2. Yêu cầu môi trường

- Python 3.12+
- Dependency đã cài qua `requirements.txt` hoặc `uv sync`
- File `.env` có cấu hình đủ cho LLM và tracing
- File `resources.yaml` có resource definitions cần thiết

## 3. Cấu hình chính

### 3.1 Biến môi trường quan trọng

- `PIPELINE_INPUT_PATH`: thư mục input mặc định
- `PIPELINE_OUTPUT_PATH`: thư mục output mặc định
- `PIPELINE_SKIP_IF_EXISTS`: bỏ qua file đã có output
- `PIPELINE_TRACER_KIND`: `none | local | langfuse`
- `PIPELINE_MAX_CONCURRENCY`: số file chạy song song
- `LLM_RESOURCE_KEY`: resource key cho LLM chính
- `FALLBACK_LLM_RESOURCE_KEY`: resource key dự phòng

### 3.2 Cấu hình tracing

- `none`: không ghi trace
- `local`: ghi trace JSON vào thư mục `./traces`
- `langfuse`: gửi trace sang Langfuse

## 4. Cách chạy

### 4.1 Chạy toàn bộ thư mục input

```bash
python main.py
```

### 4.2 Chạy một danh sách file cụ thể

```bash
python main.py --files path/to/a.json path/to/b.json
```

### 4.3 Chạy từ file danh sách

```bash
python main.py --files-list manifests/files.txt
```

### 4.4 Bật progress JSONL

```bash
python main.py --progress-jsonl
```

## 5. Cấu trúc output

Mỗi file input sẽ tạo một file JSON trong thư mục output. Output gồm:

- `Sentiment`: danh sách kết quả sentiment
- `HVC`: danh sách kết quả vi phạm
- `qc_score_total_offset`: tổng offset điểm

Nếu pipeline lỗi, output có thể ghi một object `error` thay vì kết quả đầy đủ.

## 6. Giám sát và theo dõi

### 6.1 Log

Pipeline ghi log thông tin về:
- số file quét được
- số file thành công / thất bại / bỏ qua
- thời gian chạy từng file

### 6.2 Trace

Bật tracer local hoặc Langfuse để theo dõi:
- prompt / response của LLM
- thời gian từng node
- lỗi parse hoặc retry

## 7. Kịch bản vận hành thường gặp

### 7.1 Chạy lại batch sau khi sửa config

```bash
python main.py --input-path samples --output-path outputs/qc --skip-if-exists
```

### 7.2 Chỉ chạy một subset case bằng whitelist

- chuẩn bị file CSV có cột `audio_name,case`
- chạy pipeline với `--whitelist-path`

### 7.3 Xử lý file đã tồn tại output

- dùng `--skip-if-exists` để tránh re-score lại file cũ
- nếu cần rerun, xóa file output tương ứng hoặc đổi output path

## 8. Bảo trì

- Theo dõi dung lượng thư mục `outputs/qc` và `traces`
- Định kỳ kiểm tra tài nguyên LLM và token
- Cập nhật prompt/resource khi business rule thay đổi
- Bảo trì whitelist và mẫu input mới

## 9. Checklist vận hành hàng ngày

- [ ] Đã có `.env` và `resources.yaml` đúng
- [ ] Input folder có file mới cần chạy
- [ ] Output folder có đủ quyền ghi
- [ ] Tracing đã bật nếu cần debug
- [ ] Kết quả summary đã được kiểm tra sau khi chạy
