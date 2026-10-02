# Kiến trúc hệ thống theo mô hình C4

Tài liệu này tóm tắt kiến trúc hiện tại của hệ thống QC Analyze dựa trên code trong repo và luồng chạy từ entrypoint [main.py](../main.py).

## Mục tiêu hệ thống

Hệ thống nhận file ASR JSON của cuộc gọi, chạy các case kiểm tra vi phạm và phân tích sentiment, rồi ghi kết quả ra file JSON để dùng cho QC review.

## 1. Context diagram

```mermaid
C4Context
    title QC Analyze System Context

    Person(qcReviewer, "QC Reviewer", "Xem và kiểm tra kết quả chấm điểm")
    Person(opsEngineer, "Ops Engineer", "Chạy batch job, theo dõi lỗi và hotfix")

    System_Ext(asrPipeline, "ASR Pipeline", "Sinh ra JSON transcript đã diarize và có VAD")
    System(qcAnalyze, "QC Analyze", "Phân tích vi phạm HVC và sentiment cho cuộc gọi")
    System_Ext(llmProvider, "LLM Provider", "Claude/GPT endpoints dùng cho verification")
    System_Ext(observability, "Langfuse", "Theo dõi trace, latency và chi phí")

    Rel(qcReviewer, qcAnalyze, "Nhận kết quả JSON chấm điểm")
    Rel(opsEngineer, qcAnalyze, "Khởi chạy batch và xử lý sự cố")
    Rel(qcAnalyze, asrPipeline, "Đọc file ASR JSON đầu vào")
    Rel(qcAnalyze, llmProvider, "Gọi LLM cho case phức tạp")
    Rel(qcAnalyze, observability, "Gửi trace và telemetry")
```

## 2. Container diagram

```mermaid
C4Container
    title QC Analyze Container Diagram

    Container(cli, "CLI Entry Point", "Python", "main.py, parse args và gọi pipeline")
    Container(batchPipeline, "Batch Pipeline", "Python", "app/main.py + src/jobs/score: job `score`, mỗi file một lần chạy")
    Container(orchestrator, "Orchestrator", "Python + Hush", "src/orchestrator, fan-out 7 case")
    Container(caseModules, "Case Modules", "Python", "src/cases/*, mỗi case có graph và spec riêng")
    Container(conversationLayer, "Conversation Layer", "Python", "src/conversation, load/normalize/format transcript")
    Container(configLayer, "Configuration Layer", "YAML/Env/Prompt", "resources.yaml, .env, .prompts")
    Container(storage, "Artifacts", "JSON/Trace Files", "outputs/qc, traces, logs")

    Rel(cli, batchPipeline, "Gọi run()")
    Rel(batchPipeline, conversationLayer, "Tạo Conversation từ input JSON")
    Rel(batchPipeline, orchestrator, "Tạo engine và chạy workflow")
    Rel(orchestrator, caseModules, "Kích hoạt 7 case song song")
    Rel(caseModules, conversationLayer, "Đọc/format transcript")
    Rel(caseModules, configLayer, "Đọc prompt và resource key")
    Rel(batchPipeline, storage, "Ghi output JSON và trace")
```

## 3. Component diagram

```mermaid
C4Component
    title QC Analyze Component Diagram

    Component(cliArgParser, "Argument Parser", "argparse", "Parse CLI và env")
    Component(workPlanner, "Work Planner", "collect_work", "Quét file đầu vào và tạo work item")
    Component(engineFactory, "Engine Factory", "create_engine", "Build Hush engine với tracer")
    Component(fileRunner, "File Runner", "score_one", "Chạy một file input và ghi output")
    Component(conversationModel, "Conversation Model", "Conversation", "Chuẩn hóa transcript, tìm turn theo timestamp")
    Component(caseRegistry, "Case Registry", "CASE_SPECS", "Đăng ký các case và thứ tự render")
    Component(caseGraph, "Case Graph", "@graph", "Thực thi logic cho một case")
    Component(resultAggregator, "Result Aggregator", "_aggregate/_post_process", "Thu thập và format kết quả cuối")
    Component(promptLoader, "Prompt Loader", "PROMPTS", "Load prompt template từ .prompts")
    Component(llmOps, "LLM Ops", "Hush ChainOp", "Gọi model và parse JSON")

    Rel(cliArgParser, workPlanner, "Truyền file list và config")
    Rel(workPlanner, fileRunner, "Cung cấp work item")
    Rel(fileRunner, engineFactory, "Yêu cầu engine")
    Rel(fileRunner, conversationModel, "Load transcript thành Conversation")
    Rel(engineFactory, caseRegistry, "Lấy danh sách case")
    Rel(caseRegistry, caseGraph, "Wire graph cho mỗi case")
    Rel(caseGraph, conversationModel, "Đọc transcript và timestamp")
    Rel(caseGraph, promptLoader, "Lấy prompt")
    Rel(caseGraph, llmOps, "Thực hiện LLM call")
    Rel(caseGraph, resultAggregator, "Trả raw result")
```

## Luồng thực thi chính

1. Entry point [main.py](../main.py) đọc tham số, chạy job `preflight` rồi job `score` (khai báo trong [app/main.py](../app/main.py)).
2. [src/jobs/score/_calls.py](../src/jobs/score/_calls.py) liệt kê file đầu vào có `call_code`.
3. Job `score` chạy graph [src/jobs/score/graph.py](../src/jobs/score/graph.py) cho từng file và ghi output JSON.
4. Graph đó gọi [src/qc/graph.py](../src/qc/graph.py) — orchestrator.
5. Orchestrator fan-out 7 case.
6. Mỗi case dùng graph riêng và trả raw result.
7. Orchestrator tổng hợp kết quả thành cấu trúc Sentiment/HVC.

## Điểm nhấn thiết kế

- Registry-driven: thêm case mới chỉ cần đăng ký spec và cập nhật orchestrator.
- Async-first: các LLM call và workflow chạy trên event loop.
- Tracing-first: có thể bật Langfuse hoặc tracer local để debug.
- Config externalized: prompt, resource key và endpoint nằm ngoài code.
