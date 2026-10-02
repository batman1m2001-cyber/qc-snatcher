# Sentiment — what the deployment runs

The contract between this repo and the deployment (`deployment/score_sentiment/`):
one command in two modes, what they read, what they write, how they exit. Where the
commands run — pods, schedules, S3 layout, secrets storage — is the deployment's
side and is not described here.

## At a glance

| | command | when | exit |
|---|---|---|---|
| deploy gate | `python main.py --selfcheck` | once per deploy, before any pod starts | 0 pass · 1 fail |
| scoring | `python main.py` | every pod, every batch | 0 batch done · 1 stack unfit |
| scoring, may seed | `python main.py --ingest` | a pod allowed to seed a stale corpus store | as above |

Both run from the repo root with `sys.executable`; neither needs anything on
`PATH`. operonx is pinned in `deployment/score_sentiment/requirements.txt`
(`operonx[openai,pgvector,triton]==1.11.0`).

## `python main.py`

Runs `preflight ▶ ingest ▶ score ▶ report` (the `main` runbook in `app/main.py`).

| step | does | fails the run when |
|---|---|---|
| preflight | checks every model and retrieval endpoint answers; prints stage → resource | an endpoint is unreachable or a resource is misconfigured |
| ingest | checks the corpus store holds `corpus.yaml`; with `--ingest`, seeds it under a lock | the store is stale and this pod may not seed (the message ends with the fix) |
| score | one output file per input call | never — a failed call is recorded, the batch goes on |
| report | prints calls scored / failed / skipped, tokens, cost | never |

**Exit 1 only when preflight or ingest fails.** A call that fails does not
change the exit code.

### Input

Every `*.json` in `PIPELINE_INPUT_PATH` (or the paths listed in
`PIPELINE_FILES_LIST`, one per line). Each file is the ASR output
(`transcribed_vads`) plus:

| `metadata.` | required | used for |
|---|---|---|
| `call_code` | **yes** — a file without it is skipped with a warning | routing (`Ngat_may`, `Hua_tra`, `Ben_thu_3_hua_tra`, `Ben_thu_3_DVKD`, …) |
| `closed_by` | no (`YES`) | hangup: `AGENT` arms the case |
| `is_chinh_chu` | no (`false`) | disclosure is skipped for the loan owner's number |
| `queueid` | no (`0`) | raba is skipped for queue 583 |

### Output

`PIPELINE_OUTPUT_PATH/<input file stem>.json`, one per call:

```json
{"Sentiment": [ ...rows ], "HVC": [ ...rows ], "qc_score_total_offset": -10}
```

Each row: `Criteria`, `CriteriaCode` (`TC_1`…`TC_7`), `Reasoning`, `Result`,
`Evidence`, `Score_offset`, `EvidenceIdxs`.

| `Result` | meaning | `Score_offset` |
|---|---|---|
| `Vi phạm` | HVC violation (hangup −25, others −100) | −25 / −100 |
| `Không vi phạm` | HVC clean | 0 |
| `Tích cực` | sentiment clean | 0 |
| `Thái độ warning` | agent phrasing QC wants surfaced, not penalised | 0 |
| `Thái độ cao` | agent attitude, high | −10 |
| `Thái độ nghiêm trọng` | agent attitude, severe | −25 |
| `ĐTV im lặng` / `KH im lặng` | agent / customer silent | 0 |
| `Tiêu cực` | customer sentiment negative | 0 |
| `Không chạy` | case switched off by `QC_ENABLE_<CASE>=false` | 0 |

**`Thái độ warning` is a fourth agent-sentiment value.** A reader that maps an
unknown `Result` to `Tích cực` shows a flagged call as clean.

**A failed call writes `{"error": "<op>: <reason>"}` instead.** It has no
`qc_score_total_offset`: the merge must skip files with an `error` key —
reading the missing offset as 0 would count a call nobody scored as clean.
With `PIPELINE_SKIP_IF_EXISTS=true` a rerun scores `{"error"}` files again.

### Settings

Environment variables, read once at start (`app/settings.py` is the full table).
Booleans are `1 true yes on` / `0 false no off`; anything else stops the run,
naming the variable.

| variable | default | |
|---|---|---|
| `PIPELINE_INPUT_PATH` | `samples` | folder of calls |
| `PIPELINE_FILES_LIST` | — | file of input paths, instead of the folder |
| `PIPELINE_OUTPUT_PATH` | `outputs/qc` | one JSON per call |
| `PIPELINE_SKIP_IF_EXISTS` | `false` | skip calls already scored |
| `PIPELINE_MAX_CONCURRENCY` | `2` | calls scored at once |
| `PIPELINE_TRACER_KIND` | `none` | `local` writes redacted traces to `PIPELINE_TRACER_LOCAL_DIR` |
| `CORPUS_SEED_WAIT_S` | `900` | how long a pod waits for another pod's seed |
| `QC_ENABLE_<CASE>` | `true` | per case: `HANGUP`, `RABA`, `DISCLOSURE`, `CARD_NUMBER`, `PHONE_SOURCE`, `SENTIMENT_AGENT`, `SENTIMENT_CUSTOMER` |
| `INCLUDE_TRACES` | `false` | a stage file per call (`<stem>_<id>.json`) in `PIPELINE_TRACER_LOCAL_DIR` |

Which model serves each stage is `models.yaml`, not an environment variable.
Endpoints and keys come from `resources.yaml`, which reads `DATABRICKS_HOST`,
`DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`, `PG_DSN`, and optionally
`TRITON_EMBEDDING_URL` / `TRITON_EMBEDDING_SSL` and `E4B_LOCAL_BASE_URL` (only
when `models.yaml` routes the pre-filter to it).

`main.py` takes no flag but `--ingest` or `--selfcheck`. The old flags (`--input-path`,
`--output-path`, `--max-concurrency`, …) exit 2, naming the variable that
replaced each.

## `python main.py --selfcheck`

Scores only the selfcheck fixture, never a batch. Imports the deployment's
`settings` module first (it writes the secrets into `.env`; a pod gets them
from `sentiment.py`), then runs `preflight ▶ ingest (seed) ▶ selfcheck`.
If it exits 0, start the pods with `python main.py --ingest`.

| step | does |
|---|---|
| preflight, ingest | as above; ingest seeds when stale, so a `corpus.yaml` change is judged on the new corpus |
| selfcheck | scores the 90 fixture calls and compares each with its recorded baseline; **fails under `PIPELINE_SELFCHECK_MATCH_THRESHOLD`** (default `0.85`; `0` = warn only) |

A healthy run matches about 90–93%: a few calls flip between identical runs. When `S3_BUCKET` and `SENTIMENT_OUTPUT_S3_KEY`
are set, the selfcheck record (`run.json`, `items.jsonl`) is uploaded to
`<SENTIMENT_OUTPUT_S3_KEY>/selfcheck/<run id>/`, pass or fail; a failed upload
is printed and does not change the exit code.

The corpus tables must exist; on a new database run
`uv run operonx-run create_schema` once (ingest names it when they are missing).

## No longer read

| variable | since | instead |
|---|---|---|
| `PIPELINE_SELFCHECK_STRICT` | the selfcheck became an operonx `Eval` | the threshold decides; `0` = warn only |
| `PIPELINE_SELFCHECK_N`, `_SEED`, `_SHUFFLE` | same | always the fixture's 90 calls |
| `CORPUS_AUTO_SEED` | `ingest` replaced the two seed paths | `python main.py --ingest` |

| command | since | instead |
|---|---|---|
| `python -m scripts.selfcheck` | the operonx move | `python main.py --selfcheck` |
