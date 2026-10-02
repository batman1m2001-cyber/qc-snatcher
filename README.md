# Sentiment

QC scoring for Vietnamese collection calls: HVC violations and agent / customer
sentiment, one JSON verdict per call. Full deployment contract: [docs/MLE.md](docs/MLE.md).

## Run

```bash
uv sync
python main.py --selfcheck   # 1. once per deploy — exit 0 = pass
python main.py --ingest      # 2. the pods, only after a pass
```

| command | does | exit 1 when |
|---|---|---|
| `--selfcheck` | preflight ▶ seed a stale corpus store ▶ score the 90 fixture calls against their baseline | match rate < `PIPELINE_SELFCHECK_MATCH_THRESHOLD` (0.85), or a step fails |
| `--ingest` | preflight ▶ seed a stale corpus store ▶ score the batch ▶ report | preflight or ingest fails — a failed call never fails the batch |

## Configure

Credentials in `.env` (never in git): `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`,
`DATABRICKS_CLIENT_SECRET`, `PG_DSN`, `TRITON_EMBEDDING_URL`, `TRITON_EMBEDDING_SSL`.

| variable | default | |
|---|---|---|
| `PIPELINE_INPUT_PATH` | `samples` | folder of `*.json` calls |
| `PIPELINE_OUTPUT_PATH` | `outputs/qc` | one JSON per call |
| `PIPELINE_MAX_CONCURRENCY` | `2` | calls scored at once |

Models per stage: `models.yaml`. Endpoints: `resources.yaml`.

## Input / output

- **Input:** ASR output (`transcribed_vads`) plus `metadata.call_code` (required). Examples in `samples/`.
- **Output:** `{"Sentiment": [...], "HVC": [...], "qc_score_total_offset": -10}`.
- A failed call writes **`{"error": "..."}`**; the merge must skip it.
- `Result` includes **`Thái độ warning`** (score 0), a fourth agent value.

## Seminar demo (offline, no data)

```bash
uv sync
uv run python -m demo            # 5 synthetic calls -> one QC table per call
uv run python -m demo --graph    # the root graph's shape only
uv run python -m demo -v         # plus operonx's log of the failing call
```

Runs the production root graph `src.qc.graph:score_cases` (seven
`verify_<case>` subgraphs in parallel, then `_finalize`) on five invented
calls in `demo/calls.py`. Real: every gate, prompt render, the XML/JSON
parsers, the `parsed` guards, corpus ranking and `_finalize`. Canned
(`demo/offline.py`): the text each model would return, and the
Triton / pgvector / Postgres answers, which are three real `corpus.yaml`
entries. No network, `.env` or production file is touched.

`DEMO-005` gets a reply that does not parse, so the call is recorded as an
error rather than as "Không vi phạm": a failure is never a verdict. Each
call is traced to `.operonx/runs/adhoc/qc_flow/<date>/DEMO-00N/`
(`view.txt`, `nodes.jsonl`).

## Development

See [CLAUDE.md](CLAUDE.md). Tests: `uv run pytest tests/` (offline).
