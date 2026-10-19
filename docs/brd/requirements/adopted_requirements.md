# qc-snatcher: requirements found in the project

Extracted from the project's own docs, code and tests (`operonx-project adopt`, 2026-10-19). The quote is the source's own words, at the location given; the reading is ours. Status is not here: see [`requirements_traceability.md`](requirements_traceability.md).

## Functional requirements

| ID | Location | Quote (source language) | Reading | Doc status |
|---|---|---|---|---|
| QCS-REQ-OUTPUT-01 | README.md, Input / output | Output: {"Sentiment": [...], "HVC": [...], "qc_score_total_offset": -10}. | Each scored call yields HVC rows, Sentiment rows and a summed Score_offset total. | documented |
| QCS-REQ-OUTPUT-03 | README.md, Configure (PIPELINE_OUTPUT_PATH) | one JSON per call | The score job writes one output file per call, and an unwritable output root does not fail the call. | documented |
| QCS-REQ-FAIL-05 | tests/graphs/test_soften_failure.py | test_a_soften_timeout_keeps_the_verdict_and_the_reason | A timeout in the wording (soften) stage keeps the verdict and its reason. | documented |
| QCS-REQ-CASES-01 | CLAUDE.md, Execution Flow | The `score_cases` @graph dispatches 7 cases in parallel, driven by `CASES`. | Seven cases (hangup, raba, disclosure, card_number, phone_source, sentiment_agent, sentiment_customer) run as sub-graphs from one registry, then merge in _finalize. | documented |
| QCS-REQ-CASES-08 | CLAUDE.md, Key Patterns | Per-case toggle: `QC_ENABLE_<CASE_ID>` boolean env vars gate each case. Default is all-on | A case can be switched off by an env var; it then reads 'khong chay' and cannot fail the call. | documented |
| QCS-REQ-SENT-04 | CLAUDE.md, sentiment_agent — four layers | l1_gates/ cheap gates: scope · agent silent · pre-filter · bot · kid | Cheap deterministic gates end a call before any scanner or decider is paid for. | documented |
| QCS-REQ-SENT-05 | tests/unit/test_retrieval_determinism.py; CLAUDE.md, Shared between layers | Retrieval determinism ... corpus ranking | Retrieval over the corpus (shared by l3 and l4) returns a stable, deterministic ranking. | documented |
| QCS-REQ-SENT-06 | BACKLOG.md, Scanner: multi-evidence output | Scanner: multi-evidence output ... scanner returns exactly 1 evidence_idxs list per call. | The scanner should return up to 3 evidences per call, verified per evidence and aggregated as the max violation; today it returns one. | documented |
| QCS-REQ-DEPLOY-01 | README.md, Run | python main.py --ingest # the pods, only after a pass (preflight ▶ seed ▶ score ▶ report; exit 1 when preflight or ingest fails) | The pods' command runs preflight, ingest, score and report; exit 1 only when preflight or ingest fails, and nothing is scored then. | documented |
| QCS-REQ-DEPLOY-02 | README.md, Run | `--selfcheck` \| preflight ▶ seed a stale corpus store ▶ score the 90 fixture calls against their baseline \| match rate < PIPELINE_SELFCHECK_MATCH_THRESHOLD (0.85), or a step fails | The deploy gate exits 1 when the share of fixture calls matching their baseline on every HARD field is below the threshold or a step fails. | documented |
| QCS-REQ-DEMO-01 | README.md, Seminar demo | a failure is never a verdict ... DEMO-005 gets a reply that does not parse, so the call is recorded as an error | The offline demo scores five invented calls through the production graph with canned model replies, and a bad reply is recorded as an error. | documented |

## Non-functional requirements

| ID | Location | Quote (source language) | Reading | Doc status |
|---|---|---|---|---|
| QCS-REQ-PRIVACY-01 | CLAUDE.md, Tech Stack | Langfuse / any remote tracer removed to eliminate PII leakage ... the transcript, the query vector and the static half of each prompt are replaced by references. | Only a local tracer is used, and traces never hold the transcript text or the query vectors. | documented |
| QCS-REQ-TEST-01 | CLAUDE.md, Testing | No LLM calls, no network, no `.env` — the `pytest` job in `.gitlab-ci.yml` runs it on a clean checkout. | The whole test suite runs offline in a pinned environment. | documented |

## Business rules

| ID | Location | Quote (source language) | Reading | Doc status |
|---|---|---|---|---|
| QCS-REQ-OUTPUT-02 | README.md, Input / output | A failed call writes {"error": "..."}; the merge must skip it. | A call that fails is recorded as an error file and does not fail the batch. | documented |
| QCS-REQ-FAIL-01 | CLAUDE.md, Key Patterns | A failure is never a verdict: a structured LLMOp that cannot parse its reply hands on None fields and says why in error | Every model call is followed by a parsed check that raises on a parse error, so the call is recorded as an error rather than scored clean or -100. | documented |
| QCS-REQ-FAIL-02 | CLAUDE.md, Key Patterns | `_finalize` likewise refuses an enabled case that produced no result. | The finalizer raises when an enabled case has no verdict. | documented |
| QCS-REQ-FAIL-03 | CLAUDE.md, sentiment_agent — four layers | `result: None` is not a clean call. | A layer that did not decide is told apart from a decided one by the exit stamp (is_decided), not read as a clean call. | documented |
| QCS-REQ-FAIL-04 | tests/graphs/test_empty_pool_guard.py (TestMergeSides) | both sides empty raises | An empty retrieval pool on both sides raises rather than letting the call be scored on nothing. | documented |
| QCS-REQ-CASES-02 | CLAUDE.md, Violation Cases | `hangup` — `call_code == 'Ngat_may'` and `closed_by == 'AGENT'` | The hangup check runs only for agent-closed Ngat_may calls. | documented |
| QCS-REQ-CASES-03 | CLAUDE.md, Violation Cases | `raba` — `call_code in ('Hua_tra', 'Ben_thu_3_hua_tra')` | The raba (payment-promise reminder) check runs only for those call codes and flags a missing reminder. | documented |
| QCS-REQ-CASES-04 | CLAUDE.md, Violation Cases | `disclosure` — Always runs (checks first 60s of call) | The disclosure check runs on every call except the account holder's own phone, and reports a violation when nothing was disclosed. | documented |
| QCS-REQ-CASES-05 | CLAUDE.md, Violation Cases | `phone_source` — Keyword detection triggers LLM | The phone-source LLM runs only when a keyword is found, and is skipped for BT3/DVKD. | documented |
| QCS-REQ-CASES-06 | CLAUDE.md, Violation Cases | `card_number` — Heuristic digit pattern match triggers LLM | The card-number LLM runs only after a digit-pattern heuristic matches. | documented |
| QCS-REQ-CASES-07 | CLAUDE.md, Violation Cases | `sentiment_customer` — LLM verify; skip if customer silent | Customer sentiment is judged by an LLM and skipped when the customer said nothing. | documented |
| QCS-REQ-SENT-01 | CLAUDE.md, Execution Flow | Corpus severity outranks the scanner's category. | The most severe cited corpus entry decides the score, falling back to the category only when no citation resolves. | documented |
| QCS-REQ-SENT-02 | CLAUDE.md, Execution Flow severity table | Thái độ warning is a fourth Result value ... Score_offset 0 (cao -10, nghiem_trong -25) | Severity maps to Result and Score_offset: warning 0, cao -10, nghiêm trọng -25. | documented |
| QCS-REQ-SENT-03 | CLAUDE.md, sentiment_agent — four layers | Every path reaches `l4`, decided or not: both of its stages gate on `violation` and pass anything else through. | The primary decider runs only on violations with evidence and a configured model; otherwise it passes through, and a disagreement downgrades. | documented |
| QCS-REQ-CORPUS-01 | CLAUDE.md, Key Commands (corpus store) | Pass = ... corpus store ... ingest exit 1 when stale, naming the fix | The ingest job checks that the pgvector store matches corpus.yaml, fails when stale naming the fix, and seeds under a lock with seed=true. | documented |
| QCS-REQ-CORPUS-02 | CLAUDE.md, Testing (tests/contract/) | the partner DDL | The schema carries the partner's DDL verbatim and keeps our additions separate; the severity vocabulary is a reversible one-to-one map to the partner's values. | documented |
| QCS-REQ-CONFIG-01 | CLAUDE.md, Key Patterns (Stage routing) | `models.yaml` ... is the only source: no environment variable overrides it | Model routing per stage comes only from models.yaml; null switches a stage off; a missing stage refuses at import. | documented |
| QCS-REQ-CONFIG-02 | CLAUDE.md, Key Patterns (Toggles) | Every boolean and number has one grammar, `src/core/env.py`: `1 true yes on` / `0 false no off`, empty = default, anything else raises naming the variable. | Env variables use one strict parser; a typo raises and names the variable. | documented |
| QCS-REQ-CONFIG-03 | README.md, Configure | PIPELINE_INPUT_PATH samples; PIPELINE_OUTPUT_PATH outputs/qc; PIPELINE_MAX_CONCURRENCY 2 | Run settings are PIPELINE_* variables read once into Settings with fixed defaults, and nothing writes the environment at run time. | documented |
| QCS-REQ-DEPLOY-03 | CLAUDE.md, Deploy-time selfcheck | The run record ... is uploaded to S3 under its run id, pass or fail. | The selfcheck record is uploaded keyed by run id when a bucket is set, whatever the verdict. | documented |
| QCS-REQ-DEPLOY-04 | docs/PLAN_standardize.md, Part 1 The six | selfcheck_build ... refuses unless every call scored | The baseline is rebuilt only from a selfcheck run that scored every manifest call. | documented |
| QCS-REQ-DEPLOY-05 | CLAUDE.md, Key Commands | main.py takes no other flag | main.py accepts only --ingest and --selfcheck; old flags and unknown arguments fail, and the two cannot be combined. | documented |
| QCS-REQ-QUALITY-02 | CLAUDE.md, Testing | the snapshot gate ... the score job over the 90 fixture calls, each output byte for byte against tests/sample/snapshot.json | With models replayed, every one of the 90 fixture outputs must be byte-identical to the recorded snapshot. | documented |
| QCS-REQ-ARCH-01 | CLAUDE.md, Layout rule | The product never imports the tooling, and nothing in `src/` imports `app/`. | The product code under src/qc, cases, core and corpus stays independent of src/jobs, tools/ and app/. | documented |
| QCS-REQ-ARCH-02 | CLAUDE.md, Layout rule | graph.py: the package's @graphs and nothing else | Graphs live only in graph.py and ops only in ops.py, wiring is written once, and ops are not named explicitly. | documented |
| QCS-REQ-ARCH-03 | CLAUDE.md, Key Patterns (Prompts) | each .prompt file sits in a prompts/ folder beside the op that sends it ... A duplicate stem raises at import. | Prompts are loaded into one PROMPTS dict keyed by file stem, and a duplicate stem fails. | documented |

## Success metrics

| ID | Location | Quote (source language) | Reading | Doc status |
|---|---|---|---|---|
| QCS-REQ-QUALITY-01 | CLAUDE.md, Deploy-time selfcheck | A healthy run matches about 90–93% on this fixture ... default 0.85 | Scoring the 90 fixture calls must match baseline at at least 85%, and healthy runs reach 90-93%. | documented |
| QCS-REQ-QUALITY-03 | docs/SENTIMENT_AI_ROADMAP.md, Vision | hướng tới F1 > 0.8 | The long-term goal is F1 above 0.8 against QC labels. | documented |
