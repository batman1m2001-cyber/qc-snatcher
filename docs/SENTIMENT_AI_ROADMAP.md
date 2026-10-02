# Sentiment AI — Long-term Roadmap

> **Vision**: Xây dựng hệ thống QC tự động có khả năng tự cải thiện, giảm dependency vào team kỹ thuật,
> hướng tới **F1 > 0.8** và giảm chi phí inference thông qua Local LLM.

---

## Target Architecture

```mermaid
graph TD
    subgraph "Feedback Loop"
        A[QC / BU Feedback] --> B[Knowledge / Policy / Workflow Management]
    end

    subgraph "Data Layer"
        B --> C[(PostgreSQL + pgvector)]
        C --> D[Embedding Service<br/>Databricks]
    end

    subgraph "Processing Pipeline"
        E[Audio WAV] --> F[VAD<br/>Silero / New Model]
        F --> G[ASR<br/>Zipformer Unified]
        G --> H[Sentiment Scanner<br/>Multi-turn]
    end

    subgraph "Model Layer"
        D --> H
        H --> I{Model Router}
        I -->|Complex cases| J[Cloud LLM<br/>Claude / Gemini]
        I -->|Standard cases| K[Local LLM<br/>Gemma / Fine-tuned]
    end

    subgraph "Quality Gate"
        J --> L[Evaluation & Monitoring]
        K --> L
        L --> M{Quality Check}
        M -->|Pass| N[Production Deploy]
        M -->|Fail| O[Rollback / Alert]
    end

    N --> A

    style A fill:#ff9800,color:#fff
    style C fill:#2196f3,color:#fff
    style H fill:#9c27b0,color:#fff
    style L fill:#4caf50,color:#fff
    style N fill:#00bcd4,color:#fff
```

---

## Transformation Goal

```mermaid
graph LR
    subgraph "Current State ❌"
        direction LR
        X1[AI chạy] --> X2[QC phát hiện lỗi] --> X3[Dev sửa] --> X4[Deploy]
    end

    subgraph "Target State ✅"
        direction LR
        Y1[Feedback] --> Y2[Knowledge Update] --> Y3[Auto Evaluation] --> Y4[Approval] --> Y5[Deploy] --> Y6[Monitoring]
        Y6 --> Y1
    end

    style X1 fill:#ffcdd2
    style X2 fill:#ffcdd2
    style X3 fill:#ffcdd2
    style X4 fill:#ffcdd2
    style Y1 fill:#c8e6c9
    style Y2 fill:#c8e6c9
    style Y3 fill:#c8e6c9
    style Y4 fill:#c8e6c9
    style Y5 fill:#c8e6c9
    style Y6 fill:#c8e6c9
```

---

## Phase Overview

```mermaid
gantt
    title Sentiment AI Roadmap Timeline
    dateFormat YYYY-MM
    axisFormat %b %Y

    section Phase 1 - Stabilize
    Sentiment Scanner Multi-turn       :p1a, 2025-08, 6w
    Golden Dataset & Evaluation        :p1b, 2025-08, 8w
    Label Standardization              :p1c, 2025-08, 3w
    C12 Coverage                       :p1d, after p1a, 4w

    section Phase 2 - Standardize
    ASR Zipformer Unification          :p2a, 2025-10, 6w
    VAD Model Evaluation               :p2b, 2025-10, 4w
    RAG → PostgreSQL + pgvector        :p2c, 2025-10, 8w
    Embedding on Databricks            :p2d, after p2c, 4w

    section Phase 3 - Optimize
    Local LLM Deploy (UAT)             :p3a, 2026-01, 6w
    Benchmark vs Gemini 3 Flash        :p3b, after p3a, 4w
    Hybrid Architecture                :p3c, after p3b, 6w
    Production Monitoring              :p3d, after p3c, 4w

    section Phase 4 - Represent
    Policy Ontology Research           :p4a, 2026-04, 8w
    Prototype & Evaluation             :p4b, after p4a, 6w

    section Phase 5 - Platform
    AI Feedback UI (Knowledge)         :p5a, 2026-03, 8w
    Workflow Management UI             :p5b, after p5a, 8w
    Automated AI Training              :p5c, after p5b, 10w

    section Phase 6 - Auto-tune
    Prompt Optimizer                   :p6a, 2026-07, 8w
```

---

## Phase 1 — Stabilize & Improve Quality

> **Goal**: Đạt F1 > 0.8, xây nền tảng evaluation chắc chắn

```mermaid
graph TB
    subgraph "1.1 Sentiment Scanner Upgrade"
        S1[Single-turn Detection] -->|upgrade| S2[Multi-turn Detection]
        S2 --> S3[C12 Group Coverage]
        S2 --> S4[Label Standardization]
    end

    subgraph "1.2 Golden Dataset"
        G1[Normal Cases] --> G5[Golden Dataset]
        G2[FP/FN Cases] --> G5
        G3[Hard Cases] --> G5
        G4[C12 Cases] --> G5
        G5 --> G6[Regression Test Suite]
        G6 --> G7[P / R / F1 Tracking]
    end

    S4 --> G6

    style S2 fill:#e91e63,color:#fff
    style G5 fill:#ff9800,color:#fff
    style G7 fill:#4caf50,color:#fff
```

### Label Mapping

| Label cũ | Label mới (chuẩn hóa) | Score Offset |
|-----------|----------------------|--------------|
| `vi_pham_thai_do_warning` | **Thái độ Warning** | -5 |
| `vi_pham_thai_do_cao` | **Thái độ cao** | -10 |
| `vi_pham_thai_do_nghiem_trong` | **Thái độ nghiêm trọng** | -20 |
| `khong_vi_pham` | Không vi phạm | 0 |

### Key Metrics

| Metric | Current | Target |
|--------|---------|--------|
| **F1** | ~0.7x | > 0.80 |
| **Precision** | TBD | > 0.85 |
| **Recall** | TBD | > 0.75 |
| False Positive Rate | High | < 15% |

---

## Phase 2 — Standardize Audio & RAG Architecture

> **Goal**: Chuẩn hóa toàn bộ pipeline từ Audio → Embedding, đảm bảo consistency Local/UAT/Prod

```mermaid
graph LR
    subgraph "2.1 Audio Pipeline (Unified)"
        A1[Audio WAV] --> A2[VAD<br/>New Model TBD]
        A2 --> A3[ASR Zipformer<br/>Agent + Customer]
        A3 --> A4[Transcript JSON]
    end

    subgraph "2.2 RAG Migration"
        R1[Local FAISS<br/>+ BGE-M3 ONNX] -->|migrate| R2[(PostgreSQL<br/>+ pgvector)]
        R3[Local Embedding] -->|migrate| R4[Databricks<br/>Embedding Service]
        R4 --> R2
    end

    A4 --> R2

    style A3 fill:#2196f3,color:#fff
    style R2 fill:#ff5722,color:#fff
    style R4 fill:#9c27b0,color:#fff
```

### ASR Unification Plan

```
┌─────────────────────────────────────────────────────────────────┐
│                    BEFORE (Current)                              │
├─────────────────────────────────────────────────────────────────┤
│  Agent:    Gipformer v4 (Zipformer + ChainAttention, ONNX)      │
│  Customer: NeMo Parakeet CTC 0.6B (.nemo checkpoint)            │
│  VAD:      Silero VAD (ONNX) × 2                                │
├─────────────────────────────────────────────────────────────────┤
│                    AFTER (Target)                                │
├─────────────────────────────────────────────────────────────────┤
│  Agent:    Zipformer (unified)                                  │
│  Customer: Zipformer (unified)                                  │
│  VAD:      New VAD model (evaluate) / Silero upgraded           │
│  Denoise:  Optional (evaluate ROI)                              │
└─────────────────────────────────────────────────────────────────┘
```

### RAG Migration Checklist

- [ ] Setup PostgreSQL + pgvector infrastructure
- [ ] Migrate corpus from local YAML/FAISS → pgvector
- [ ] Deploy embedding model on Databricks
- [ ] Implement versioning mechanism for knowledge
- [ ] Validate retrieval quality (before vs after)
- [ ] Update Hush resource config to point to new services
- [ ] Ensure Local/UAT/Prod use identical configs

---

## Phase 3 — Local LLM & Cost Optimization

> **Goal**: Giảm chi phí inference, đảm bảo quality không giảm

```mermaid
graph TD
    subgraph "Deployment"
        L1[Local LLM<br/>Gemma / Fine-tuned] --> L2[Deploy UAT]
        L2 --> L3[Benchmark]
    end

    subgraph "Benchmark Criteria"
        L3 --> B1[F1 / Precision / Recall]
        L3 --> B2[Latency p50 / p95]
        L3 --> B3[Throughput calls/min]
        L3 --> B4[Stability over 1000 calls]
        L3 --> B5[Cost per call]
    end

    subgraph "Decision"
        B1 --> D1{Quality ≥ Cloud?}
        D1 -->|Yes| D2[Full Local LLM]
        D1 -->|No| D3{Acceptable gap?}
        D3 -->|Yes| D4[Hybrid: Local + Cloud]
        D3 -->|No| D5[Stay Cloud<br/>Re-evaluate later]
    end

    style L1 fill:#673ab7,color:#fff
    style D2 fill:#4caf50,color:#fff
    style D4 fill:#ff9800,color:#fff
    style D5 fill:#f44336,color:#fff
```

### Cost Comparison Model

```
┌────────────────────┬──────────────┬──────────────┬──────────────┐
│                    │  Cloud Only  │   Hybrid     │  Local Only  │
├────────────────────┼──────────────┼──────────────┼──────────────┤
│ Cost / 1000 calls  │    $$$       │     $$       │      $       │
│ Latency (p95)      │   ~3-5s      │    ~2-4s     │    ~1-2s     │
│ Quality (F1)       │   Baseline   │   ~Baseline  │    TBD       │
│ Dependency         │   High       │    Medium    │    Low       │
│ GPU Required       │    No        │    Yes       │    Yes       │
└────────────────────┴──────────────┴──────────────┴──────────────┘
```

### Production Monitoring Dashboard

| Metric | Alert Threshold |
|--------|----------------|
| F1 drop | > 5% drop vs baseline |
| Latency p95 | > 10s |
| Error rate | > 2% |
| Fallback rate | > 10% |
| Cost/day | > budget × 1.2 |

---

## Phase 4 — Policy & Knowledge Representation

> **Goal**: Giảm dependency vào prompt dài, dễ cập nhật policy

```mermaid
graph TB
    subgraph "Current: Prompt-based"
        P1[Long Prompts<br/>Vietnamese] --> P2[LLM Reasoning]
        P3[Corpus YAML] --> P2
    end

    subgraph "Target: Structured Representation"
        O1[Ontology /<br/>Knowledge Graph] --> O2[Policy Rules<br/>Structured Format]
        O2 --> O3[Dynamic Prompt<br/>Generation]
        O3 --> O4[LLM Reasoning<br/>with Context]
    end

    P2 -.->|evolution| O4

    style O1 fill:#009688,color:#fff
    style O2 fill:#00bcd4,color:#fff
```

### Benefits vs Risks

| Aspect | Prompt-based (Current) | Ontology (Target) |
|--------|----------------------|-------------------|
| Update policy | Edit prompt files | Edit structured rules |
| Trace reasoning | Hard | Easy (rule → evidence) |
| BU can modify | No | Yes (with UI) |
| Complexity | Low | Medium-High |
| Risk | Prompt drift | Over-engineering |

### Evaluation Criteria (Go/No-Go)

- [ ] Quality improvement ≥ 5% F1 trên prototype
- [ ] Maintenance effort giảm ≥ 50%
- [ ] BU có thể update mà không cần dev intervention
- [ ] Không tăng latency > 20%

---

## Phase 5 — AI Feedback & Training Platform

> **Goal**: BU/QC tự quản lý knowledge và workflow, hệ thống tự cải thiện

```mermaid
graph LR
    subgraph "Phase 5.1 - Knowledge Management"
        K1[BU/QC User] --> K2[Knowledge UI]
        K2 --> K3[Edit / Add / Delete]
        K3 --> K4[Preview & Test]
        K4 --> K5[Approve]
        K5 --> K6[(PostgreSQL<br/>+ pgvector)]
    end

    subgraph "Phase 5.2 - Workflow Management"
        W1[BU/QC User] --> W2[Workflow UI]
        W2 --> W3[Adjust Pipeline Logic]
        W3 --> W4[Test on Golden Dataset]
        W4 --> W5[Approve & Publish]
    end

    subgraph "Phase 5.3 - Automated Improvement"
        A1[Collect Feedback] --> A2[Generate Training Data]
        A2 --> A3[Train / Tune Candidate]
        A3 --> A4[Auto Evaluate]
        A4 --> A5{Threshold Met?}
        A5 -->|Yes| A6[Deploy]
        A5 -->|No| A7[Alert & Retry]
        A6 --> A8[Monitor]
        A8 --> A1
    end

    style K2 fill:#ff9800,color:#fff
    style W2 fill:#2196f3,color:#fff
    style A4 fill:#4caf50,color:#fff
```

### Knowledge Management Flow

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Feedback │───▶│   Edit   │───▶│   Test   │───▶│ Approve  │───▶│ Publish  │
│  from QC  │    │Knowledge │    │  Preview │    │  by Lead │    │  to Prod │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
                      │                                                │
                      ▼                                                ▼
              ┌──────────────┐                                ┌──────────────┐
              │  Version     │                                │  Audit Log   │
              │  Control     │                                │  + Rollback  │
              └──────────────┘                                └──────────────┘
```

---

## Phase 6 — Prompt Optimization (Medium/Low Priority)

> **Prerequisite**: Golden Dataset + Automated Evaluation phải stable trước

```mermaid
graph TD
    PO1[Analyze FP/FN Patterns] --> PO2[Identify Error Categories]
    PO2 --> PO3[Generate Prompt Candidates]
    PO3 --> PO4[Benchmark on Golden Dataset]
    PO4 --> PO5{Better than current?}
    PO5 -->|Yes| PO6[Propose to Team]
    PO5 -->|No| PO7[Log & Discard]
    PO6 --> PO8[A/B Test in UAT]
    PO8 --> PO9[Deploy if confirmed]

    style PO3 fill:#9c27b0,color:#fff
    style PO4 fill:#4caf50,color:#fff
```

---

## Priority Matrix

```mermaid
quadrantChart
    title Priority vs Impact
    x-axis Low Effort --> High Effort
    y-axis Low Impact --> High Impact
    quadrant-1 Do First
    quadrant-2 Plan Carefully
    quadrant-3 Consider Later
    quadrant-4 Delegate/Defer

    Golden Dataset: [0.3, 0.9]
    UAT Issue Fix: [0.2, 0.95]
    pgvector RAG: [0.5, 0.85]
    Multi-turn Scanner: [0.6, 0.8]
    ASR Unification: [0.55, 0.7]
    Local LLM: [0.7, 0.75]
    Knowledge UI: [0.65, 0.7]
    Workflow UI: [0.75, 0.6]
    Policy Ontology: [0.8, 0.5]
    Prompt Optimizer: [0.85, 0.45]
    Auto Training: [0.9, 0.55]
```

---

## Priority Table

| Priority | Workstream | Goal | Status |
|:--------:|-----------|------|:------:|
| 🔴 **P0** | UAT & Issue Fix | F1 > 0.8 | 🟡 In Progress |
| 🔴 **P0** | Golden Dataset | Standardize evaluation | 🔵 Planning |
| 🔴 **P0** | PostgreSQL + pgvector | Standardize RAG | 🔵 Planning |
| 🟠 **P1** | ASR / VAD Unification | Standardize audio pipeline | 🔵 Planning |
| 🟠 **P1** | Local LLM | Reduce inference cost | 🔵 Planning |
| 🟠 **P1** | AI Feedback UI (Phase 1) | BU manages knowledge | 🔵 Planning |
| 🟡 **P2** | Multi-turn Scanner / C12 | Increase violation coverage | 🔵 Planning |
| 🟡 **P2** | AI Workflow UI (Phase 2) | BU tunes workflow | ⚪ Future |
| 🟡 **P2** | Policy/Ontology | Reduce prompt dependency | ⚪ Future |
| 🟢 **P3** | Prompt Optimizer | Automate tuning | ⚪ Future |
| 🟢 **P3** | Automated AI Training | Closed-loop improvement | ⚪ Future |

---

## Success Metrics

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         KPIs Dashboard                                   │
├─────────────────────┬───────────────┬───────────────┬───────────────────┤
│      Metric         │   Current     │   Phase 1     │   Final Target    │
├─────────────────────┼───────────────┼───────────────┼───────────────────┤
│  F1 Score           │    ~0.7x      │    > 0.80     │     > 0.85        │
│  Cost / 1000 calls  │    $$$        │    $$$        │     $  (Local)    │
│  Latency p95        │    ~5s        │    ~4s        │     < 2s          │
│  BU Update Time     │    Days       │    Days       │     Hours (UI)    │
│  Deploy Frequency   │    Weekly     │    Weekly     │     Daily (Auto)  │
│  Violation Coverage │    6/7 groups │    7/7        │     7/7 + expand  │
└─────────────────────┴───────────────┴───────────────┴───────────────────┘
```

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|------------|
| Local LLM quality < Cloud | High | Medium | Hybrid fallback architecture |
| pgvector migration data loss | High | Low | Parallel run + validation |
| BU resistance to new UI | Medium | Medium | Training + gradual rollout |
| Ontology over-engineering | Medium | Medium | Prototype first, Go/No-Go gate |
| ASR model regression | High | Low | A/B test + rollback mechanism |
| Prompt optimizer hallucinations | Medium | High | Human approval gate |

---

## Dependencies & Integration Map

```mermaid
graph TD
    subgraph "Infrastructure"
        INF1[(PostgreSQL + pgvector)]
        INF2[Databricks<br/>Embedding Service]
        INF3[GPU Server<br/>Local LLM]
        INF4[S3 / SFTP]
    end

    subgraph "Services"
        SVC1[ASR Pipeline<br/>asr/]
        SVC2[QC Pipeline<br/>analyze/]
        SVC3[qc-monitor<br/>Real-time UI]
    end

    subgraph "External"
        EXT1[Claude API<br/>AIHub Proxy]
        EXT2[Gemini API<br/>Databricks]
        EXT3[Airflow<br/>Orchestration]
    end

    EXT3 --> SVC1
    SVC1 --> INF4
    INF4 --> SVC2
    SVC2 --> INF1
    INF2 --> SVC2
    INF3 --> SVC2
    EXT1 --> SVC2
    EXT2 --> SVC2
    SVC2 --> SVC3

    style SVC2 fill:#e91e63,color:#fff
    style INF1 fill:#2196f3,color:#fff
    style INF3 fill:#673ab7,color:#fff
```

---

## Quick Links

| Resource | Location |
|----------|----------|
| Codebase (ASR) | `asr/` |
| Codebase (sentiment) | this repository |
| Architecture | `CLAUDE.md`, `docs/FLOW_sentiment_agent_end_to_end.html` |
| Prompt Files | `src/**/prompts/` |
| Resources Config | `resources.yaml`, `models.yaml` |
| Selfcheck Fixtures | `tests/sample/fixtures/` |
| Deployment contract | `docs/MLE.md` |
| Past plans, reports, board docs | `docs/archive/` |

---

*Last updated: August 2026*
*Author: MLE/DS2 Team*
