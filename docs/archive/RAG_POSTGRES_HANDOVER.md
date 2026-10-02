# Bàn giao & refactor luồng RAG trên Postgres

Kế hoạch đưa retrieval từ FAISS local sang pgvector + Triton, và những gì MLE
cần để vận hành.

Giả định: kết nối tới Postgres và Triton trên prod đã thông.

---

## 1. Hiện trạng

| | |
|---|---|
| schema | 4 bảng / 2 view / 19 constraint, khớp DDL của MLE |
| dữ liệu | 81 group / 1611 policy / 707 pos / 904 cvo |
| `batch_id` | `db792192299b` = corpus.yaml hiện tại |
| toàn vẹn | 0 orphan, 0 trùng hai bảng, 0 lệch side |
| identity faiss↔pg | 1611/1611 (0 ORDER / SET / VARIANT / FIELD) |
| Phase 4 | **chưa bật** — `.env` không có `CORPUS_*` / `PG_DSN` |

---

## 2. Lỗ hổng cần bịt

| # | vấn đề | hậu quả | ưu tiên |
|---|---|---|---|
| 1 | pgvector không có preflight so corpus↔DB | quên ingest → chấm sai, **không lỗi** | **P0** |
| 2 | `deployment/` chưa có bước ingest | thuần túy nhớ hay quên | **P0** |
| 3 | entry thiếu `id:` bị builder bỏ qua im lặng | entry mới biến mất | P1 |
| 4 | sửa content dưới `policy_id` cũ vẫn được ghi | phá luật add-only | P1 |
| 5 | hai UUID trùng nội dung, khác severity | retrieve trúng cái nào chấm cái đó | P2 |
| 6 | không có snapshot trước ingest | ingest sai không rollback được | P2 |
| 7 | §8.2 Triton vs ONNX chưa đo | vector lệch, không có gì báo | **blocked (VPN)** |

### Chi tiết #1

```python
# _retrieval.py:558
if api != "faiss":
    return          # pgvector: không kiểm gì cả
```

FAISS thì pod tự phát hiện index cũ và build lại. Postgres thì không. Cột
`batch_id` sinh ra đúng để trả lời câu này nhưng **không ai đọc**.

---

## 3. Refactor

### P0-1 — preflight `batch_id`

`check_corpus_freshness` khi backend là pgvector: query
`SELECT DISTINCT batch_id FROM knowledge_policy`, so với sha corpus, lệch thì
dừng. Đối xứng với đường FAISS.

Không auto-ingest như FAISS auto-reindex: ingest ghi vào DB dùng chung, không
phải file cục bộ của pod.

### P0-2 — ingest vào pipeline deploy

Chạy `ingest.py` một lần, trước khi pod đầu tiên phục vụ — cùng chỗ
`selfcheck.py` đang chạy.

### P1-3 — entry thiếu `id` là lỗi cứng

`YamlDocStore` có báo, `02_build_index.py` bỏ qua im lặng. Dưới luật
add-only, "thêm entry mới" là thao tác thường xuyên nhất.

### P1-4 — chặn edit

Seed so content/severity/description với DB trước khi ghi. Khác → dừng.
Cột `status` đã tính `NEW`/`UPDATE`/`UNCHANGED`; dưới luật add-only,
`UPDATE` không bao giờ được phép xuất hiện.

### P2-5 — cảnh báo trùng nội dung

Hai UUID khác nhau, cùng content → warning. Đây là failure mode do chính luật
add-only sinh ra (thêm bản mới mà quên xoá bản cũ).

### P2-6 — snapshot trước ingest

`pg_dump` 4 bảng vào S3 trước khi prune. Ingest nằm trong một transaction nên
lỗi giữa chừng tự rollback, nhưng ingest **thành công với corpus sai** thì
không có đường lùi.

---

## 4. Quy trình vận hành

### Lần đầu

```bash
uv run operonx-run create_schema --set dsn="$PG_DSN"   # cần quyền owner; bỏ qua nếu bảng đã có
uv run operonx-run ingest --set seed=true               # nạp corpus vào store (DSN từ PG_DSN)
uv run operonx-run ingest                               # store khớp corpus.yaml? sai thì exit 1 kèm cách sửa
```

### Corpus thay đổi (thêm / xoá)

```bash
uv run python -m tools.corpus_stamp_ids --apply        # UUID cho entry mới
uv run operonx-run ingest --set seed=true              # prune mặc định; store `multi` cần --set reseed=true
```

Bước deploy (`python -m app.deploy`) tự chạy create_schema → preflight →
ingest (seed) → selfcheck trước khi pod phục vụ.

Chạy **trước** khi pod phục vụ. Cùng một lệnh cho mọi thay đổi.

### Luật corpus: chỉ ADD và DELETE

Không sửa entry tại chỗ. Sửa = xoá entry cũ + thêm entry mới với UUID mới.

Lý do: `#n` là **vị trí**, không phải danh tính. Bớt một variant giữa chừng
làm variant sau dịch lên, variant cuối nằm lại mang severity cũ — cùng một câu
tồn tại ở hai severity.

### Xoá dữ liệu

| | |
|---|---|
| embedding | tự xoá theo `ON DELETE CASCADE` |
| `knowledge_info` | **không** bị xoá, chỉ báo ra |
| cache | không có — `main.py` là batch job, mỗi lần chạy là process mới |
| VACUUM | không cần; autovacuum bật sẵn |

Sau đợt xoá lớn (vài trăm dòng): dòng đã xoá vẫn nằm trong đồ thị HNSW và
chiếm chỗ trong `ef_search` candidates cho tới khi được dọn.

```sql
VACUUM ANALYZE positive_embedding, carveout_embedding;
```

### Chốt an toàn có sẵn

- prune quá 50% bảng → **dừng và hỏi** (dùng nhầm corpus thì mọi dòng thành orphan)
- toàn bộ seed nằm trong **một transaction**
- `ingest.py` dừng ngay khi một bước lỗi, không để hai store lệch nhau

---

## 5. Bàn giao MLE

### Env — 5 biến, đã có trong `settings.py`

```
CORPUS_VECTOR_STORE_POS=corpus-pos-pg
CORPUS_VECTOR_STORE_CVO=corpus-cvo-pg
CORPUS_DOC_STORE=corpus-pg
CORPUS_EMBEDDING_RESOURCE=corpus-triton
PG_DSN=postgresql://...
```

**Đủ 5 hoặc không cái nào.** Thiếu một biến là rơi ngầm về local, không lỗi.

### Checklist

| # | việc | ai | tần suất |
|---|---|---|---|
| 1 | Áp `schema.sql` (cần owner cho `ef_search`) | MLE / DBA | 1 lần |
| 2 | Set 5 biến env | MLE | 1 lần |
| 3 | Chạy `ingest.py` | pipeline | mỗi lần corpus đổi |
| 4 | `VACUUM ANALYZE` | MLE | sau đợt xoá lớn |

### Cần MLE xác nhận

1. Có quyền owner trên database không? (`ALTER DATABASE ... ef_search`)
2. Bước ingest đặt ở đâu trong pipeline deploy?
3. Bật VPN để chạy §8.2 — Triton và ONNX có cho vector giống nhau không

---

## Liên quan

| file | |
|---|---|
| `src/jobs/ingest/README.md` | các job `ingest`, `create_schema` — cách chạy, input |
| `docs/RAG_PGVECTOR_REFACTOR_PLAN.md` | thiết kế + lịch sử quyết định |
| `app/main.py` | khai báo mọi job; `operonx-run --list` |
| `src/jobs/ingest/schema.sql` | DDL, chạy 1 lần |
