# CLAUDE.md

## Project Overview

Sentiment is a Vietnamese call center QC scoring system. It scores collection calls
by detecting compliance violations (HVC) and analyzing sentiment, using LLM pipelines
built on the operonx graph framework (1.11).

## Tech Stack

- **Python 3.12+** with **uv** for package management
- **operonx 1.17** (PyPI) — graph engine (`@graph`, `@op`), Jobs (`items`, `steps`), `Application`.
  Its guide ships in the package: `uv run python -m operonx.guide` lists the pages;
  read `04-gotchas.md` before changing a graph — every failure there raises nothing
- **pytest + pytest-asyncio** — test suite
- Tracing: local JSON tracer only. Langfuse / any remote tracer removed to eliminate
  PII leakage (pipeline passes full transcripts through every LLM op). The local
  tracer is `QCLocalConsumer` (`src/jobs/score/_tracing.py`, flat layout): every op, timing
  and output is kept, but the transcript, the query vector and the static half of
  each prompt are replaced by references. Traces went from 1.38 MB per call to
  ~0.05 MB; `Conversation.source_path` is what makes the transcript pointer
  resolvable back to the input file.

## Key Commands

```powershell
# Install dependencies
uv sync

# Run tests (no LLM, no network), the 90-call snapshot included
uv run pytest tests/
uv run pytest tests/ -m "not snapshot"          # the same without the snapshot (~20 s faster)
uv run python -m tests._snapshot                 # the snapshot alone, with a report; --write re-records

# The main flow, as the pods run it: preflight ▶ ingest ▶ score ▶ report.
# Configured by PIPELINE_* only (defaults from .env) — main.py takes no other flag
uv run python main.py
$env:PIPELINE_INPUT_PATH="samples"; $env:PIPELINE_OUTPUT_PATH="outputs/qc"; uv run python main.py
$env:PIPELINE_FILES_LIST="files.txt"; uv run python main.py      # a file of paths, one per line
uv run python main.py --ingest                                    # let ingest seed a stale corpus store

# The seven jobs, declared in app/main.py
uv run operonx-run --list
uv run operonx-run <name> --show            # what would run
uv run operonx-run <name> --set key=value   # a graph input

# Selfcheck: preflight, seed a stale corpus store, score the fixture sample against the baseline — costs LLM calls
uv run operonx-run selfcheck
uv run operonx-run selfcheck_build           # accept the drift as the new baseline (after reading it)

# F1 against QC's labels on a QC batch (review .xlsx + transcripts in one folder), and the
# stage behind every wrong call — the debug/fix loop; costs LLM calls (src/jobs/qc_eval/README.md)
uv run operonx-run qc_eval --set batch=data/qc/<round>

# The corpus store: check it, seed it, create its tables
uv run operonx-run ingest                    # exit 1 when stale, naming the fix
uv run operonx-run ingest --set seed=true
uv run operonx-run create_schema

# The deploy gate (MLE runs it once, before the pods): the selfcheck job (steps), with MLE's secrets
uv run python main.py --selfcheck

# Rough tools — QC batches, the corpus workbook, the scan report: plain scripts
uv run python -m tools.<name> --help         # see tools/README.md

# Upgrade operonx
uv lock --upgrade-package operonx
```

## Architecture

### Execution Flow

1. Input: `Conversation` (VADs from ASR) + `call_code` + `closed_by` (+ `is_chinh_chu`, `queue_id`).
2. The `score_cases` @graph dispatches 7 cases **in parallel**, driven by `CASES`.
3. Each case runs its own sub-graph (LLM calls, heuristics).
4. `_finalize` collects each case's raw `result` dict, calls each case's `format_<id>(...)`,
   partitions into HVC vs Sentiment, sums `Score_offset` → `qc_score_total_offset`.

**Corpus severity outranks the scanner's category.** The primary decider
reports which corpus entries it cited; `resolve_cited_severity` takes the most
severe of those and `format_sentiment_agent` scores on it, falling back to the
category only when nothing resolved. So `corpus.yaml` — what QC maintains —
decides the score:

| severity | `Result` | `Score_offset` |
|---|---|---|
| `warning` | **`Thái độ warning`** | 0 |
| `cao` | `Thái độ cao` | -10 |
| `nghiem_trong` | `Thái độ nghiêm trọng` | -25 |

`Thái độ warning` is a **fourth** `Result` value, added 2026-08-24. Anything
reading these strings must know it exists — an unrecognised value falls through
to `Tích cực`, so a flagged call would read as clean downstream (QC UI and the
BU report have not been told yet).

### Key Patterns

- **Registry-driven**: each case lives under `src/cases/<id>/` and exports `verify_<id>`
  + `format_<id>`. `src/cases/__init__.py` collects them into `CASES: dict[str, Case]`
  (a NamedTuple with `section, criteria, code, verify, format`) plus a matching
  `CASE_IDS` tuple (`src/core/case_ids.py`). Adding a case = drop a folder + append to
  both `CASES` and `CASE_IDS` + add one kwarg to `_finalize` in `src/qc/ops.py`.
- **operonx ops**: All pipeline nodes use `@op` decorator. Graphs use `@graph` with `START`,
  `END`, `PARENT` wiring.
- **Conditional routing**: `if_()` from operonx, written inline — `bot >> if_(bot["is_bot"], bot_exit).else_(verify)`;
  three or more arms go one per line inside `( ... )`, never `\`. Assign a branch only when
  another op refers to it (`short_gate`). An inline branch is `route_N` in traces (before operonx
  1.10.2 some borrowed a nearby kwarg's name, e.g. `role`).
- **Wiring, written once**: a `@graph` uses its parameters by name (they already are
  `PARENT[name]`); a fan-out that rejoins is one chain —
  `qvec >> [positives, carveouts] >> merge`; exits end together —
  `[exit_code, quiet, proceed] >> END`, not a line each. Same edges, fewer lines;
  `tests/repo/test_graph_conventions.py` holds all three.
- **Shared graph nodes**: `exit_fn`, `format_fn`, `expand_evidence_fn`, `is_decided`,
  `parsed` in `src/cases/_shared/ops.py` are reused across cases.
- **A failure is never a verdict**: a structured `LLMOp` that cannot parse its reply
  hands on `None` fields and says why in `error`; `None` reads as "no" — a clean
  call, or a −100 one where "missing" means a violation. So every model call is
  followed by `x_parsed = parsed(error=x["error"])`, wired `x >> x_parsed >> ...`,
  which raises; any op that raises fails the call, and the call is recorded as
  `{"error": ...}` (the batch goes on). `_finalize` likewise refuses an enabled case
  that produced no result. `tests/repo/test_graph_conventions.py` fails on an unchecked
  model call.
- **Stage routing**: `models.yaml` at the repo root names the resource each stage
  uses — default, filter decider, primary decider, soften, pre-filter, and the four
  retrieval resources. It is the **only** source: no environment variable overrides
  it, and `tests/unit/test_config_env.py` fails if any code reads one. `null` switches a
  stage off. Resource definitions (endpoints, credentials) live in `resources.yaml`.
- **Toggles**: `INCLUDE_TRACES`, `QC_ENABLE_<CASE_ID>`, the pre-filter keyword and
  apply switches stay in the environment, read by `src/core/config.py`; how a run
  executes (`PIPELINE_*` and the rest) is `app/settings.py`, read once into
  `SETTINGS` in `app/main.py` and handed to the jobs as inputs. Nothing writes the
  environment or a config global at run time. Every boolean and number has one
  grammar, `src/core/env.py`: `1 true yes on` / `0 false no off`, empty = default,
  anything else raises naming the variable.
- **Prompts**: each `.prompt` file sits in a `prompts/` folder beside the op that sends
  it, and `src/core/prompts.py` loads every one under `src/` into a flat `PROMPTS`
  dict (key = file stem). A duplicate stem raises at import.
- **Per-case toggle**: `QC_ENABLE_<CASE_ID>` boolean env vars gate each case. Default is
  all-on; the runtime skips disabled cases entirely and preserves prior verdicts.

### Layout rule

Every package reads the same way:

| file | holds |
|---|---|
| `graph.py` | the package's `@graph`s and nothing else — wiring (`tests/repo/test_graph_conventions.py`) |
| `_format.py` | a case's `format_<id>` — the row `_finalize` writes |
| `ops.py` | the `@op`s that root wires, plus private helpers only they use |
| `_*.py` | non-op helpers shared by more than one file in the package |
| `prompts/` | `.prompt` files sent by this package's ops |

A stage gets its own package only when it has to be a **subgraph node**:
reused by more than one graph (`sentiment_agent/retrieval/`, composed by l3
and l4), or needing the boundary itself (`l1_gates/prefilter/`, whose chunk
fan-out must end in a single stream for `.collect()`). Stages that simply
run in sequence stay flat in their layer's graph — l4's primary decider and
soften are two gated steps in one `l4_verify/graph.py`. A helper moves up only when a second package needs it, and only
to the lowest common parent. QC-maintained data lives outside `src/`, in
`knowledge/<case>/`.

`src/` holds two kinds of code, and the line between them is tested
(`tests/repo/test_jobs_layout.py`): **the product** — `src/qc/`, `src/cases/`,
`src/core/`, `src/corpus/`, what the pods run per call — and **the tooling**,
`src/jobs/<feature>/`, the graphs the jobs in `app/main.py` run around it.
The product never imports the tooling, and nothing in `src/` imports `app/`.
Rough tools run by hand live outside both, in `tools/` — plain argparse
scripts that nothing in `src/` or `app/` imports.

### Module Responsibilities

| Module | Purpose |
|--------|---------|
| `main.py`                  | MLE's command: the `main` job (steps) (`--ingest` → `seed=true`; exit 1 iff preflight or ingest fails), or `--selfcheck`, the deploy gate |
| `app/main.py`              | `APP = Application(...)`: the seven jobs, and the graph each runs — read first |
| `app/settings.py`          | How a run executes: every run variable, read once into `Settings`, with its default — the table |
| `app/_score.py`            | `build_job`: the score job from those settings; the progress line |
| `src/qc/graph.py`          | `@graph score_cases` — 7 cases fan out from START, fan into `_finalize` |
| `src/qc/ops.py`            | `_finalize` — format each case's verdict, split HVC / Sentiment, sum `Score_offset` |
| `src/core/_bootstrap.py`   | Load the env file + install the ResourceHub (import-time side effects) |
| `src/core/config.py`       | Every env-driven setting, plus `KNOWLEDGE_DIR` |
| `src/core/case_ids.py`     | The seven case ids — a leaf, so `config` never imports `src.cases` |
| `src/core/prompts.py`      | Load every `*.prompt` under `src/` into `PROMPTS` (key = stem) |
| `src/core/conversation.py` | `Conversation` dataclass + ASR fixes + `format_mmss` timestamp helper |
| `src/corpus/`              | `variants.py` — one row per phrasing; `loader.py` — read corpus.yaml: hash, flatten, severity |
| `src/cases/__init__.py`    | `CASES: dict[str, Case]` registry + `CRITERIA_TO_CASE_ID` map |
| `src/cases/_shared/`       | `ops.py` — shared ops; `spec.py` — row helpers every `format_<id>` uses |
| `src/cases/<id>/`          | `graph.py` `@graph verify_<id>` · `ops.py` · `_format.py` `format_<id>` |
| `src/jobs/<feature>/`      | preflight · ingest · score · report · selfcheck — each with a README |
| `tools/`                   | rough tools: qc_prepare · qc_compare · scan_report · corpus_export · corpus_import · corpus_stamp_ids |

### Violation Cases

| Case id | Folder | Trigger Conditions |
|---------|--------|--------------------|
| `hangup`             | `cases/hangup/`             | `call_code == 'Ngat_may'` and `closed_by == 'AGENT'` |
| `raba`               | `cases/raba/`               | `call_code in ('Hua_tra', 'Ben_thu_3_hua_tra')` |
| `disclosure`         | `cases/disclosure/`         | Always runs (checks first 60s of call) |
| `card_number`        | `cases/card_number/`        | Heuristic digit pattern match triggers LLM |
| `phone_source`       | `cases/phone_source/`       | Keyword detection triggers LLM |
| `sentiment_agent`    | `cases/sentiment_agent/`   | Four layers — see below |
| `sentiment_customer` | `cases/sentiment_customer/` | LLM verify; skip if customer silent |

**`main` still runs v3; this branch does not carry it.** `git show
main:src/cases/sentiment_agent/__init__.py` imports `v3`, and `main` has no
`v4/` directory at all — so `main` is the rollback target, and rolling back
means deploying `main` rather than flipping a flag here. With one
implementation left, the version suffix is gone from module paths, prompt
keys and the manifest: `src/cases/sentiment_agent/graph.py`,
`l2_scanner/prompts/SCANNER_PROMPT.prompt`. (v1 removed 2026-08-14;
there was never a v2; v5 removed 2026-08-19, recoverable at `310c4b9`.)

### sentiment_agent — four layers

Named after the blocks in `docs/FLOW_sentiment_agent_end_to_end.html`, so
the diagram QC and IT read and the code are the same thing.

| package | block | what ends a call here |
|---|---|---|
| `l1_gates/`   | cheap gates     | scope · agent silent · pre-filter · bot · kid |
| `l2_scanner/` | scanner         | halu-suppressed citation · nothing to verify |
| `l3_decider/` | filter decider  | always decides — decider, or the ASR-check route for `mày`/`tao`/`con nợ` |
| `l4_verify/`  | primary decider | strict re-verify → **severity** → wording |

Each layer exports `result`: a verdict when it decided, `None` when it did
not. `is_decided` (`src/cases/_shared/ops.py`) tells them apart by reading
`_trace_meta["exit"]`, which every terminal stamps.

**`result: None` is not a clean call.** Reading absence as a verdict would
skip the stages meant to catch a loss and emit `Tích cực` for a call
nothing judged — see `[[feedback_silent_failure_shape]]`.

Every path reaches `l4`, decided or not: both of its stages gate on
`violation` and pass anything else through. **`l4` is not
post-processing** — `resolve_cited_severity` runs there and outranks the
scanner's category, so it is what sets `Score_offset`. With
`llm.primary_decider: null` in `models.yaml` the whole layer is a
passthrough and no call can score `Thái độ warning`.

Shared between layers: `retrieval/` (l3 and l4 both retrieve),
`_pools.py` (slot formatting, citation parsing), `_trace.py`
(`_scanner_trace`).

## Code Style

- All async functions use `async def` with `await`
- Type hints throughout (dataclasses, NamedTuple, `Dict`, `List`, `Literal`)
- Vietnamese category names in violation results (e.g., `vi_pham_thai_do_cao`, `khong_vi_pham`)
- Prompts are in Vietnamese

## Testing

One `pytest` run, ~1700 tests, ~65 s. No LLM calls, no network, no `.env` — the
`pytest` job in `.gitlab-ci.yml` runs it on a clean checkout. The environment is
pinned (`tests/_env.py`, from `conftest.py` and `tests/_snapshot.py`) before `src`
is imported, so no test reads a developer's `local.env`: the switches, the run
knobs, placeholders for every variable `resources.yaml` names, and a fixed token
for every token provider — building a graph resolves `oauth2:databricks`, and
operonx fetches a token right then. A test that needs a setting passes it
(`Settings.from_env({...})`, `config.enabled_cases({...})`) rather than setting the
environment or reloading a module.

| folder | holds |
|---|---|
| `tests/contract/` | what MLE's deployment relies on: `main.py`'s flags and exit code, the output file, the `PIPELINE_*` names, the partner DDL, the severity scale |
| `tests/repo/` | static rules over the repository: AST conventions, layout, prompts, graph shape and validation |
| `tests/graphs/` | graphs run with every model replayed or stubbed — incl. the **snapshot gate**, `test_snapshot.py` (marker `snapshot`): the score job over the 90 fixture calls, each output byte for byte against `tests/sample/snapshot.json`; a change meant to move outputs re-records it with `python -m tests._snapshot --write` |
| `tests/unit/` | one function or op at a time |
| `tests/_*.py` | the harness: env pinning, paths, the recording (`_recorded`), replay stubs (`_replay`), the engine (`_engine`) |

A test file never imports another test file, and reaches operonx's private graph
internals only through the harness — `tests/repo/test_tests_layout.py` holds both.

### Deploy-time selfcheck

`python main.py --selfcheck` runs **once in the deploy pipeline, before**
the pods start — its own flag, because the pods scale horizontally and
would each rerun it. It imports MLE's `settings` (the secrets), then runs
the `selfcheck` job (steps): preflight ▶ ingest with seed (the fixture must
not judge a corpus the store does not hold yet) ▶ `selfcheck_score`, an
operonx `Eval`: the 90 fixture calls through the scoring graph, each
compared with its recorded baseline row in `tests/sample/fixtures/`. Pass =
the share of calls that match on every HARD field >=
`PIPELINE_SELFCHECK_MATCH_THRESHOLD` (default 0.85, the deployment's value;
0 = warn-only). The run record (`.runs/selfcheck_score/<run>/`) holds every
call's verdict, and is uploaded to S3 under its run id, pass or fail. A healthy run matches about 90–93% on this fixture (a few calls flip between identical runs); drift from a wrong
resource or an empty corpus collapses it far below.

Rebuilding the baseline, the HARD/SOFT field tiers, and how to tell expected
drift from a real regression: **see the `selfcheck` skill**.

## Workflows

Recurring procedures live as skills, loaded on demand rather than sitting in
this file. Invoke by name.

| skill | use when |
|---|---|
| `qc-batch` | a transcript zip + review xlsx arrives from QC, or a scored batch needs checking |
| `selfcheck` | rebuilding the baseline, or reading a selfcheck failure |
| `corpus-update` | editing `corpus.yaml` or acting on QC feedback about violation wording |

`app/main.py` lists the seven jobs (`operonx-run --list`); `tools/README.md` the rough
tools. Old one-off and eval scripts sit in `scripts/_archive/` (on disk, gitignored,
still in history).

## Git Commit Rules

- Never include `Co-Authored-By` lines in commit messages. All commits are authored solely by thanglq12.

## Important Files

- `.env` — API keys (never commit)
- `resources.yaml` — operonx resource registry (LLM, keycloak, oauth2, embedding configs)
- `operonx.toml` — names the application (`app = "app.main:APP"`) for `operonx-run`
- `src/**/prompts/*.prompt` — LLM prompt templates, beside the op that sends each
- `knowledge/sentiment_agent/corpus.yaml` — sentiment_agent retrieval corpus (QC maintains)
- `knowledge/sentiment_agent/keyword_filter.yaml` — deterministic keyword pre-filter list
- `docs/MLE.md` — the deployment contract: the two commands, their settings, output, exit codes.
  Keep it in step when a command, a `PIPELINE_*` variable or the output shape changes
- `docs/` — four current docs; dated plans, reports and board docs are in `docs/archive/`
