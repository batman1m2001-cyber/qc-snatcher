# Hướng dẫn Hotfix

Tài liệu này giúp team xử lý sự cố nhanh khi pipeline QC Analyze không chạy đúng.

## 1. Khi nào dùng hotfix

Dùng hotfix khi có một trong các tình huống sau:

- Pipeline không khởi động được.
- Một hoặc nhiều file score thất bại.
- Kết quả output bị thiếu hoặc sai schema.
- LLM resource bị lỗi auth hoặc endpoint không khả dụng.
- Case selection / whitelist gây kết quả không đúng mong đợi.

## 2. Quy trình nhanh 5 bước

1. Xác nhận lỗi bằng log và output file.
2. Kiểm tra biến môi trường và resource key.
3. Chạy lại với file nhỏ hoặc một file cụ thể để reproduce.
4. Áp dụng patch tối thiểu, không sửa nhiều thứ cùng lúc.
5. Verify bằng một lần chạy mẫu và so sánh output.

## 3. Các tình huống thường gặp

### 3.1 Import hoặc startup lỗi

Dấu hiệu:
- lỗi import hush / dotenv / module not found
- chương trình dừng ngay khi chạy

Kiểm tra:
- đảm bảo môi trường Python đã được kích hoạt
- chạy lại dependency install
- kiểm tra file [main.py](../main.py) và [src/_bootstrap.py](../src/_bootstrap.py)

Khởi chạy thử:

```bash
python main.py --files samples/sample.json --progress-jsonl
```

### 3.2 LLM auth hoặc resource lỗi

Dấu hiệu:
- lỗi 401/403/timeout
- case không trả về kết quả hợp lệ

Kiểm tra:
- giá trị `LLM_RESOURCE_KEY` trong `.env`
- `resources.yaml` có resource key đúng không
- endpoint / token / secret còn hợp lệ không

Command kiểm tra nhanh:

```bash
python main.py --files samples/sample.json --tracer-kind local --progress-jsonl
```

### 3.3 Output bị thiếu field `call_scoring`

Dấu hiệu:
- file kết quả có lỗi hoặc output không đúng schema

Nguyên nhân thường gặp:
- orchestrator không chạy tới `_post_process`
- case graph lỗi và dừng trước lúc aggregate

Khắc phục:
- mở log và kiểm tra exception ở file đang chạy
- chạy với một file đơn lẻ để xem stacktrace
- kiểm tra [src/orchestrator.py](../src/orchestrator.py)

### 3.4 Một case cụ thể không chạy

Dấu hiệu:
- output có trường `Không chạy` hoặc thiếu row theo case

Kiểm tra:
- whitelist / selection có giới hạn case không
- spec của case có được đăng ký trong [src/cases/__init__.py](../src/cases/__init__.py) không
- case graph có chạy được không

### 3.5 File input thiếu metadata

Dấu hiệu:
- file bị skip vì thiếu `metadata.call_code`

Khắc phục:
- kiểm tra payload đầu vào
- đảm bảo file JSON có đúng metadata như `call_code` và `closed_by`

## 4. Hướng dẫn rerun an toàn

### Chạy một file duy nhất

```bash
python main.py --files path/to/file.json --output-path outputs/qc --progress-jsonl
```

### Bỏ qua file đã có output

```bash
python main.py --input-path samples --skip-if-exists
```

### Chỉ chạy một vài case

```bash
python main.py --files path/to/file.json --whitelist-path path/to/whitelist.csv
```

## 5. Checklist trước khi deploy hotfix

- Đã reproduce lỗi trên một file mẫu.
- Patch đã giới hạn ở root cause.
- Log hiện tại đã rõ hơn trước khi sửa.
- Output mới có schema hợp lệ.
- Đã test lại ít nhất một file thành công.
