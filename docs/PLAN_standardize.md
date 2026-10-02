# Plan — six jobs, one main flow, and one standard shape for everything else

**Status:** 2026-09-28 · branch `refactor/operonx-1.10` · **Part 1 built** (`14ad884` code,
docs after it; where the build differs from this text, see "Part 1 as built") ·
**Phase 2 built** (selfcheck is one `Eval`; sampling and `PIPELINE_SELFCHECK_STRICT`
dropped — threshold 0 is warn-only; S3 keyed by run id) · **Phase 3 built** (below) ·
**Phase 4 built**: every run variable is read once (`app/settings.py`, `SETTINGS`)
and reaches the jobs as inputs; `src/core/config.py` keeps what is scored, as pure
functions of a mapping (`enabled_cases(env)`); traces reach the formatter as data
(`include_traces`), so selfcheck no longer flips `config.INCLUDE_TRACES`; tests run
in a pinned environment (`tests/_env.py`) and never reload a module; `HUSH_CONFIG`
is gone · **Phase 5 built** (below; on operonx 1.10.2) · **Phase 6 built**: tests by
kind (`contract/`, `repo/`, `graphs/`, `unit/`, harness `tests/_*.py`), the 90-call
snapshot a marked test, no test imports another or touches operonx internals
outside the harness; the suite runs on a clean checkout — it had needed `.env`
and fetched a Databricks token on every run — and `.gitlab-ci.yml` has a `pytest`
job (runner tags still the team's) · **Phase 7 built**: `docs/` keeps the FLOW diagram, this plan, the roadmap and `docs/MLE.md` (the deployment contract, stopping at our commands); 45 dated docs are in `docs/archive/` · **Phase 8 in progress**: A3 built here (soften reads the evidence the primary decider reads; wording only); A4 built on branch `fix/a4-l4-context-window` (l4's window counted in turns via `build_verifier_context`) — merge only after F1 against QC labels holds; A5 waits on QC; typed fields not started.

**Phase 5 as built.** raba's call-type check is one `_by_call_type` subgraph for
the customer and a third party; `_finalize` loops over `CASES`; the root graph
is `score_cases` (was `orchestrator`) and `ENABLED_CASES` is always a set;
`is_true` and `turn_idxs` in `_shared/spec.py` replace four and seven copies;
one config name per model stage (no module aliases); hangup uses `hvc_row`;
dead code out (four prompts, `_flatten_corpus`, `Conversation.save`,
`usage_postfix`, `hits`, `trigger_filter`, the `timestamps` fallback, stale
docstrings). Branches stay inline (three or more arms one per line in
`( ... )`) with operonx's `route_N` names; the branches operonx named after a
kwarg above them (`role`, `filter_meta`) are fixed in operonx 1.10.2.
Decided against, and why:

| planned | decision | why |
|---|---|---|
| every terminal stamps `_trace_meta.exit`; `_finalize` asserts the stamp | dropped | ~30 exit sites, and one missed stamp would fail production calls; phase 3's check — an enabled case with no result raises — already catches a lost verdict |
| hangup's bot LLM declared once | left twice | the two subgraphs are the two hangup kinds; hoisting the check changes which calls pay for it |
| typed fields (`result.violation: bool`) | phase 8 | a field type changes what the parser accepts, so it moves verdicts — needs F1 on the VPN |
| ops renamed verb_noun, no `_fn` | skipped | renames every trace op name for no behavioural gain |
| every branch named (`by_bot = if_(...)`, or operonx deriving `if_is_bot`) | tried, reverted | ~30 more lines, or long names, for one trace line that already shows what was tested; `route_N` is enough |
| `config.stage("name")` for model resolution | not needed | each stage already has one config name once the aliases went |
| one evidence renderer, one context window, one bot detector | left | the copies differ on purpose (order/dedupe; A4 is phase 8; regex vs substring vocabularies) |
| the case switch outside the graph | left in `score_cases` | operonx cannot switch a built graph's child from a Job; the switch is process-wide anyway |

**Phase 3 as built.** Decision #1 taken as (a): a failed call keeps its
`{"error"}` file; MLE's merge must skip files with an `error` key (one line to
hand them). A1/A2: a `parsed` check after each of the 25 structured model calls
raises on a parse `error`, so the call is recorded as `{"error"}` — never scored
clean or −100. `_finalize` refuses an enabled case with no result. B2: the score
job's sink (`Outputs`) does not count an `{"error"}` file as done. B4: the deploy
door tolerates only a missing `settings` module. B6: one strict boolean reader,
`src/core/env.py`, for every variable (`HUSH_USAGE_LOG=false` now means off;
`PIPELINE_SKIP_IF_EXISTS=on` now means on; a typo raises). Deferred to phase 5,
where the case shape is rebuilt: "every terminal stamps `_trace_meta.exit`" —
`_finalize` checks that a result exists instead.
Part 1: the six jobs and the main flow. Part 2: the audit — bugs first, then the
standard patterns and the phases to apply them. Your decisions are in §2.7.

## Summary

| | now | after |
|---|---|---|
| jobs in the application | 17 jobs + 3 runbooks | **7** (as of 2026-09-30): `main`, `selfcheck`, `selfcheck_build`, `ingest`, `create_schema`, `qc_eval`, `qc_eval_report` |
| the main flow | `main.py`: ~190 lines wiring `preflight` and `score` by hand, beside the `main` runbook | one runbook, `main = preflight >> ingest >> score >> report`; `main.py` is a 5-line delegate |
| seeding the corpus store | two entry points: `rag_seed`, and preflight's own seed path | one: `ingest` |
| rough tools (QC batches, corpus workbook, scan report) | 7 jobs in the application | plain scripts in `tools/`, outside the product |
| configuring a run | CLI flags **and** `PIPELINE_*` env vars, defaults in two places | `PIPELINE_*` env vars only — what MLE already sets |
| MLE's command | `python main.py [--ingest]` | **unchanged** |
| operonx | — | **no change needed** |
| bugs found by the audit | — | 6 in scoring (2 score a failed model reply as clean or as −100), 6 in the tooling and the MLE boundary — fixed before any tidying |
| selfcheck | two jobs handing files through three directories | one operonx `Eval`; same metric |

---

## Part 1 — the jobs

### The six

| job | kind | does | writes |
|---|---|---|---|
| `main` | runbook | preflight ▶ ingest ▶ score ▶ report | one JSON per call |
| `selfcheck` | job | the 90 fixture calls through the scoring graph, compared with the baseline; exit 0/1 | a report; never the baseline |
| `selfcheck_build` | job | promote the last `selfcheck` run to be the baseline; refuses unless every call scored | `tests/sample/fixtures/` (commit it) |
| `ingest` | job | make the corpus store current: nothing when it already is; otherwise one pod takes the lock and seeds (prune by default) | Postgres + pgvector |
| `create_schema` | job | create the corpus tables when they are absent | Postgres DDL |
| `selfcheck` | runbook | preflight ▶ ingest (seed) ▶ selfcheck_score — MLE's deploy gate, `python main.py --selfcheck` (was the `deploy` runbook + `app/deploy.py` until 2026-09-30) | — |

`selfcheck_build` is its own job, not a flag on `selfcheck`: it overwrites
committed files, and a separate command means reading the drift before
accepting it. It costs no LLM calls — it promotes the run just checked.

The shape of `selfcheck` itself (one `Eval`, or one Job load → score →
compare, instead of a job writing files the next one reads back) is decided
in Part 2.

### The main flow

```text
main = preflight >> ingest >> score >> report         app/main.py, configured from PIPELINE_* env

  preflight   the backends are remote and reachable; prints stage → resource    (was main.py's banner)
  ingest      the corpus store is current — seed=false: check, and fail if stale;
              seed=true: seed it (python main.py --ingest)                        (was preflight's seed path)
  score       one run per call, one JSON out per call; on_error="record":
              a failed call writes {"error"} and does not fail the batch;
              one progress line per call                                          (was main.py's exit rule, _Progress)
  report      calls scored / failed / skipped, LLM tokens and cost                (was main.py's summary)
```

```python
# main.py — MLE's command, unchanged; the `main` runbook does the work
import sys

from operonx.cli.run import main as operonx_run

argv = ["main", *(["--set", "seed=true"] if "--ingest" in sys.argv[1:] else [])]
raise SystemExit(operonx_run(argv))
```

`python -m operonx.cli.run` rather than the `operonx-run` script because MLE
starts us with `sys.executable`, which needs no PATH.

`on_error="record"` is required, not a preference: with today's `"skip"` a
failed call fails the score job (operonx 1.10, `app/jobs/runner.py:56`),
which inside a runbook fails `main` — and MLE's worker would fail the batch.

### What changes for whom

| who | before | after |
|---|---|---|
| MLE's pods | `python main.py`, `python main.py --ingest` | same |
| MLE's deploy step | (never handed over) | `python main.py --selfcheck` (was `python -m app.deploy`) |
| a person, a batch | `python main.py --input-path in --output-path out --max-concurrency 5` | `$env:PIPELINE_INPUT_PATH="in"; $env:PIPELINE_OUTPUT_PATH="out"; $env:PIPELINE_MAX_CONCURRENCY="5"; uv run python main.py` |
| a person, a file list | `--files-list files.txt` | `$env:PIPELINE_FILES_LIST="files.txt"` (new) |
| a tool reading progress | `--progress-jsonl` | dropped — nothing reads it (MLE passes only `--ingest`) |
| exit status | 1 only when preflight fails | 1 when preflight or ingest fails; a failed call is recorded, not a failure |
| run records | `.runs/preflight/…`, `.runs/score/…` | the same, plus `.runs/main/<run>/` tying them together |
| a rough tool | `operonx-run scan_report --set input=…` | `uv run python -m tools.scan_report --input …` |

### Removed from the application

| job | goes | why |
|---|---|---|
| `score`, `preflight`, `score_fixtures`, `selfcheck_compare` | steps inside `main` / `selfcheck`, no longer listed | nobody runs them alone |
| `rag_seed` | becomes `ingest` | one seed path, not two |
| `rag_schema` | renamed `create_schema` | says what it does |
| `baseline_write` | renamed `selfcheck_build` | |
| `seed_race` | deleted | a one-off test that proved the seed lock; done |
| `probe_llm`, `probe_embedder` | deleted | preflight already proves reachability |
| `smoke` | deleted | the offline routing tests cover it; a real check is `main` on a sample folder |
| `corpus_export`, `corpus_import`, `corpus_stamp_ids`, `qc_prepare`, `qc_compare`, `qc_f1`, `scan_report` | `tools/<name>.py`, plain scripts | rough tools, not the product; the qc-batch and corpus-update skills keep working |

`tools/` is the archive for rough tools: plain `python -m tools.<name>`
scripts with argparse, no graph, no Job — the op-wrapping-a-script layer
(`src/jobs/_shared/_argv.py`) goes with them. Nothing in `src/` or `app/`
imports `tools/`.

### Target layout

```text
app/main.py               the six, and APP
main.py --selfcheck       the deploy gate (was app/deploy.py)
main.py                   the 5-line delegate
src/qc, cases, core, corpus   the product (unchanged)
src/jobs/
  _shared/                store, seed, schema
  preflight/  ingest/  score/  report/  selfcheck/     graph.py · ops.py · README.md
tools/
  scan_report.py  qc_prepare.py  qc_compare.py  qc_f1.py
  corpus_export.py  corpus_import.py  corpus_stamp_ids.py      argparse scripts
```

### Work

| step | gate |
|---|---|
| `ingest`: one graph — check the store's corpus hash; seed under the lock when `seed=true`; prune, dry-run and force as inputs. `rag_seed` and preflight's seed path fold into it | unit tests on the check / seed decision; the store tests keep passing |
| `preflight` checks backends only; prints routing | unit tests |
| `score` with `on_error="record"`, a progress `on_item`, `PIPELINE_FILES_LIST` | snapshot 90/90 byte-identical, incl. a replayed failure |
| `report` job — reads the score run's record, never raises | unit test on a fake record |
| `main` / `deploy` runbooks; `main.py` delegate | `test_main_front_door` rewritten: `--ingest` → `seed=true`; exit 1 iff preflight/ingest fails; a failed call exits 0 |
| rename `rag_schema` → `create_schema`, `baseline_write` → `selfcheck_build` | `operonx-run --list` shows exactly the six |
| rough tools → `tools/`; `_argv.py`, probes, seed_race, smoke deleted | their tests move with them; `tools/` is not imported by `src/` or `app/` |
| docs: CLAUDE.md, README, the three skills | grep for removed job names and flags |

### Part 1 as built — where it differs from the text above

| planned | built | why |
|---|---|---|
| store, seed, schema stay in `src/jobs/_shared/` | moved into `src/jobs/ingest/` with `schema.sql` | the layout rule: one user → the helper lives with it |
| `main.py`, 5 lines | ~50: it also rejects each old flag, naming the `PIPELINE_*` variable that replaced it | the Risks row below; a flag MLE never passes still must not be silently ignored |
| `ingest` branches with `if_` | a straight line, `read_store ▶ seed_store ▶ verify`; keep / seed / refuse is the pure `_store.decide` | the decision is unit-tested without a graph; the lock + re-check + write stay one op |
| `verify` every run | after every **write** | a pod start does not pay a second query for rows it did not touch |
| `ingest` takes `corpus`, `dsn` | neither: it makes the configured store hold the corpus on disk | the two inputs let a hand run seed something the pods never read |
| — | a stale-store message ends with one `Fix:` line | a job's record keeps only an error's last line |
| — | `preflight` alone: `operonx-run app.main:preflight` | not one of the six, still runnable |

### Risks

| risk | handling |
|---|---|
| `report` fails and turns a finished batch into exit 1 | it never raises; a missing record prints "no score run" |
| `on_error="record"` writes a failed call's file differently from `"skip"` | the snapshot compares every file; a replayed failure is added |
| a script still passes `--input-path` to `main.py` | the delegate rejects unknown flags, naming the env var to set |
| merging the seed paths changes when a pod seeds | the lock and the stale check move unchanged; the store tests pin them |

---

## Part 2 — the audit, and one standard shape per kind of thing

Three read-only reviews (the tooling, the product, and cross-cutting
concerns), each judged against operonx's own guide
(`uv run python -m operonx.guide`). The findings that decide what to do
first were checked against the code; each is marked **checked** where it was.

### 2.1 Bugs — these come before any tidying

| # | bug | where | effect today | fix | verdict risk |
|---|---|---|---|---|---|
| A1 | a scanner reply that fails to parse scores **clean** — **checked** | `l2_scanner/ops.py:291` passes a `None` result through without an exit stamp; l3 then runs the decider on empty evidence; l4 wraps `{}`; `_format` → `Tích cực` | a lost judgement reads as "no violation", and a decider call is paid for nothing. hangup, card_number, phone_source, sentiment_customer have the same shape | a parse failure raises: the call becomes a recorded `{"error"}`, never a clean row; `_finalize` asserts every enabled case left an exit stamp | none on the 90 fixtures (no parse failures there); only failed parses change |
| A2 | a reply that fails to parse can score a **−100 violation** | disclosure: the implicit check failing falls to `else_(violation_raw)` (`disclosure/graph.py:89`); raba: a failed money/time detector counts as "thiếu thông tin" (`raba/ops.py`) | a model hiccup becomes the heaviest penalty | same rule as A1: a failed detector raises | only failed parses change |
| A3 | soften never sees the evidence — **checked** | l4 reads `evidence_text` (`l4_verify/ops.py:108,308`); nothing in `src/` writes it | the wording pass rewrites a reason blind to what was said | pass the evidence the primary decider used | wording only; `Result` unchanged |
| A4 | l4's context window is offset from the cited turn — **checked** | `l4_verify/ops.py:96` compares `enumerate(vads)` positions with `turn_idx`, which skips empty turns | 62/90 fixture calls have empty turns; drift median 1, max 10, window ±3 — the `<<<` marker can miss the evidence | reuse `build_verifier_context` (l3 already does) | **high** — the primary decider can downgrade; gate on F1 against QC labels |
| A5 | "first 60 s" is the first 60 VAD entries | `disclosure/graph.py:37` (`iend=2*30`), hangup `istart=-10` slice `vads`, empty entries included | the window depends on ASR segmentation, not time | slice by content turn or by seconds — **QC decides which was meant** | medium |
| A6 | phone_source skips `Ben_thu_3_DVKD` but not `Ben_thu_3_DVKD_AF`; sentiment_agent skips both | `phone_source/graph.py:47` vs `l1_gates/graph.py:118` | — | **question for QC** | — |
| B1 | MLE's merge counts a failed call as **clean** — **checked** | our failed call writes `{"error": …}`; `sentiment.py:112` reads `data.get("qc_score_total_offset", 0)` | a failed call lands in the BU report with offset 0 | **your and MLE's decision** (§2.7) | high |
| B2 | a failed call is never retried | `skip_existing` also skips `{"error"}` files (operonx `sinks.py:273`) | `PIPELINE_SKIP_IF_EXISTS=true` reruns keep old failures | a sink whose "exists" ignores error files | none |
| B3 | every deploy overwrites the previous deploy's selfcheck evidence on S3 — **checked** | the key is `prefix/selfcheck/<basename(dirname(report.log))>` = always `…/selfcheck/selfcheck` (`selfcheck/ops.py:114`) | no history of deploy gates | key by run id (§2.2) | none |
| B4 | a Secrets Manager failure is swallowed on the deploy gate | `app/deploy.py:33` catches `Exception`, logs at DEBUG | the gate runs without secrets and fails somewhere far away | catch only `ModuleNotFoundError` for `settings` | none |
| B5 | importing the application sets `QC_LOCAL_STACK=false` | the probes' modules write `os.environ` at import (`probes/_check.py:20`, `_load.py:38`) | on Windows, any child process then reads `.env` (the cluster) — the half-local mix `_bootstrap` exists to prevent | removed with the probes (Part 1) | none |
| B6 | seven boolean grammars for env vars | e.g. `HUSH_USAGE_LOG=false` turns the log **on**; `PIPELINE_SELFCHECK_SHUFFLE=true` is ignored; `PIPELINE_SKIP_IF_EXISTS=on` reads false | the same token means different things | one strict reader (§2.4) | none |

### 2.2 selfcheck becomes one `Eval`

Today: `score_fixtures` (clears directories, flips `config.INCLUDE_TRACES`
at run time) writes 90 files → `selfcheck_compare` finds the latest run on
disk, re-reads the files, glues the stage blocks back in, compares, writes
`report.log`, uploads, and a separate `verdict` op raises. `baseline_write`
finds the same run again and re-reads everything. Data moves through three
directories; nothing flows through a graph.

operonx already has this exact thing: an **`Eval`** — a dataset of cases,
the system under test, an evaluator per case, a threshold. The unit of
pass/fail today is already the call (`passed_n` counts calls with zero
HARD diffs, `rate = passed_n / total` — **checked**), which is exactly an
`Eval`'s pass rate. The metric does not change.

```python
# src/jobs/selfcheck/ops.py
class FixtureCases(Dataset):
    """The 90 manifest calls; the baseline sentiment row is `expected`."""
    def rows(self):
        rows = [{"id": stem, "input": {"path": ..., "name": stem, "metadata": ...},
                 "expected": baseline_row(stem)} for stem in manifest_calls()]
        if not rows:
            raise RuntimeError("no fixture cases")          # an empty Eval would pass
        return rows

def compare_to_baseline(output: dict = None, expected: dict = None) -> dict:
    row = sentiment_row(output)
    if not has_traces(row, expected):
        return {"passed": False, "reason": "blind: no traces block to compare"}
    hard, soft = compare(row, expected)
    return {"passed": not hard, "score": 1 - len(hard) / len(HARD_RULES),
            "reason": "; ".join(hard[:3]) or None, "hard": hard, "soft": soft,
            "scored": output}                                # what selfcheck_build promotes

# app/main.py
selfcheck = Eval("selfcheck", graph=score_call, dataset=FixtureCases(),
                 evaluators=[compare_to_baseline], item_input="item",
                 inputs={"include_traces": True},
                 threshold=settings.selfcheck_threshold, trace=[], record_dir=RUNS)
```

| part | today | after |
|---|---|---|
| per-call verdict | a loop inside one opaque op | `compare_to_baseline`, one call at a time, in the run record |
| the gate | a `verdict` op + `PIPELINE_SELFCHECK_STRICT` (False here, true in every deployed env) | `threshold`; the run fails under it. Warn-only = `threshold=0` |
| a blind run (no traces) | a separate check | every case fails → 0% → fails |
| traces on | `config.INCLUDE_TRACES = True` flipped inside a source | an `include_traces` input carried to the row formatter |
| the report | `.runs/selfcheck/report.log` | the run record (`run.json` + `items.jsonl`); the human drift report is `selfcheck_build --set dry_run=true` |
| S3 upload | inside the graph, a constant key (B3) | in `main.py --selfcheck` after the runbook, keyed by run id, pass or fail |
| `selfcheck_build` | re-reads outputs from disk | promotes each case's `scored` from the last `selfcheck` record; refuses unless all 90 ran |
| sampling (`PIPELINE_SELFCHECK_N/SEED/SHUFFLE`) | a random subset per run | **dropped** — always the manifest's 90 (§2.7) |

```powershell
uv run operonx-run selfcheck                            # LLM cost; exit 1 under 0.85
uv run operonx-run selfcheck_build --set dry_run=true   # the drift, read from the record
uv run operonx-run selfcheck_build                      # promote; then commit tests/sample/fixtures/
```

Risks: the promoted row must travel in the verdict's `scored` (operonx
clips `output`/`expected` at 4000 chars; 79/90 rows are longer) — pinned by
an offline test; `tools/qc_f1` reads `.runs/selfcheck/outputs` and must read
the record instead.

### 2.3 `ingest` — what merging the two seed paths must keep

They share one core (plan → embed → write, `_shared/_seed.py:316`) but
not their guards: the auto path has the lock, the stale check and no
dry-run; `rag_seed` has prune/dry-run options and **no lock** (a hand seed
races the pods).

```python
@graph
def ingest(seed: bool, reseed: bool, prune: bool, force_prune: bool, dry_run: bool):
    store = read_store()                     # dsn, current sha, seeded shas, state
    plan = decide(state=store["state"], seed=seed, reseed=reseed, dry_run=dry_run)
    seeded = seed_locked(...)                # one op: lock, re-check, write, re-classify
    kept = keep(state=store["state"])
    checked = verify(...)                    # embedder identity of the rows, every time
    START >> store >> plan >> if_(plan["seed"] == True, seeded).else_(kept)
    seeded >> checked
    kept >> checked
    checked >> END
```

Must keep: the stale check (`DISTINCT batch_id` vs the corpus hash); the
state messages deploy logs are grepped for; the advisory lock **whole in
one op** (it is a live connection) with `CORPUS_SEED_WAIT_S`; one
transaction, prune refused above 50% without `force_prune`, the partner's
`knowledge_info` rows never deleted; `verify` after every seed. `seed` is
the only switch — `CORPUS_AUTO_SEED` goes. `reseed` is how an `ok` store is
re-embedded or a `multi` store repaired; never automatic on pods.

### 2.4 The standard patterns

**Configuration**

| rule | example |
|---|---|
| three homes: `models.yaml` picks models; `resources.yaml` holds endpoints (`${VAR}`); env holds the rest | — |
| env is read in exactly two modules, each once, with one strict reader: `src/core/config.py` (what is scored) and `app/settings.py` (how a run executes) | `settings = RunSettings.from_env(os.environ)` |
| settings flow as data: Job `inputs` or op arguments; nothing writes `os.environ` or a config global at run time | `Job("ingest", inputs={"seed": settings.seed})` |
| one table of defaults | `PIPELINE_MAX_CONCURRENCY` is 2 here, 5 in MLE's settings, 1 in the README today |
| every knob is documented in one place | seven knobs appear in no doc today (`LLM_CALL_*`, `CORPUS_SEED_WAIT_S`, …) |

**A case** (the seven scoring cases)

```python
@graph                                           # graph.py — wiring only
def verify_raba(conversation, call_code, queue_id):
    scope = scope_raba(conversation=conversation, call_code=call_code, queue_id=queue_id)
    skip = exit_fn(stage="scope", reason=scope["reason"])
    judge = LLMOp.of(resource=config.stage("default"), prompt=PROMPTS.pair("RABA_PROMPT"),
                     parser="json", transcript=scope["content"],
                     fields=["result.violation: bool", "result.reason: str", "result.evidence: str"])
    verdict = verdict_fn(stage="judge", violation=judge["violation"], reason=judge["reason"],
                         evidence=judge["evidence"], error=judge["error"], conversation=conversation)
    in_scope = if_(scope["in_scope"] == True, judge).else_(skip)       # every branch named
    START >> scope >> in_scope
    judge >> verdict >> END
    skip >> END
```

| rule | today |
|---|---|
| every terminal stamps `_trace_meta.exit.stage`: `exit_fn(stage=…)` or `verdict_fn` | only l1 and two l2 terminals do; six cases and l3 never |
| `verdict_fn` raises when the model errored or `violation` is None (A1, A2) | eight hand-written coercers, `"false"` strings that are truthy |
| typed fields (`result.violation: bool`) instead of `result: dict` + coercion | mixed; raba uses json and xml in one graph |
| one result shape `{violation, reason, category, evidence, evidence_idxs, _trace_meta}`; trace blocks merged, never overwritten | l3 overwrites `_trace_meta` in 4 places |
| `_finalize` loops over `CASE_IDS`, asserts the stamp, calls `CASES[cid].format` | the case list is written out 5 times |
| prompts: `PROMPTS.pair()` at the `LLMOp` in `graph.py` | four loading patterns |
| a stage's model: `config.stage("name")` | "null means default" resolved in 3 places, 4 import aliases |
| shared helpers once: turn-index parsing (×7), evidence rendering (×2), context windows (×3), bot detection (×2), corpus flattening (×2) | copies drift — `_context.py` records 6 NameErrors from exactly this |

**A job**

| rule | today |
|---|---|
| a graph only wires; its params have no defaults — values live in `Job(inputs=)` | operonx compiles every graph param as a runtime input, so signature defaults are dead (**checked** by probe) and duplicated in three places |
| data flows through the graph or the run record, never a directory another job was meant to fill | selfcheck (§2.2) |
| one op per external boundary (a lock, a transaction, an upload); blocking work is `@op(bound="cpu")` | `_store` waits up to 900 s on a lock inside an async function |
| failures raise; no `ok` flags carried "so later checks can skip" — an op after a raise never runs | preflight carries `ok` flags |
| checking against expected values is an `Eval` | selfcheck |

**Errors and output**

| rule | today |
|---|---|
| ops raise; only entry points exit; nothing that failed is written as something that looks clean | helpers `sys.exit`; `except …: pass` in the batch summary; B1, A1, A2 |
| `logging` in `src/`; `print` only in `tools/` and the report step | 133 prints in `src/jobs`, `\r` progress lines in pod logs |
| `from operonx import op`, absolute `src.` imports | 56 files `from operonx.core import`; 5-dot relative imports |
| ops named verb_noun, no `_fn`, no leading underscore on ops | three conventions; two ops both named `proceed_fn` |

**Tests**

| rule | today |
|---|---|
| a hermetic env: conftest pins it before `src` is imported | tests read the developer's `.env` — `PIPELINE_SELFCHECK_SEED=abc` fails 3 tests (**checked** by the reviewer) |
| settings are passed as a dict, never by reloading modules | `importlib.reload(config)` in 3 files |
| private operonx internals (`_ops`, `_set_core`, `_edges`) only in `tests/harness/` | spread over 7+ files; one operonx upgrade breaks them all |
| tests never import other test modules; shared data in fixtures | 5 files import `test_replay_equivalence`; three stubbing helpers |
| layout: `tests/unit/<pkg>/`, `tests/graphs/` (replay), `tests/contract/` (MLE: env names, output keys, exit code), `tests/repo/` (AST rules), `tests/harness/` | by history (`test_operonx_110`, `test_format_regressions`) |
| a CI job runs `pytest`; the 90-call snapshot is a marked test | `.gitlab-ci.yml` runs only a manual Fortify scan |

### 2.5 Smaller findings (all S effort, no verdict risk)

- `app/_score.py` is imported as a public SDK (README) — rename `app/score.py`.
- `session_id` is minted once at app import, so every run in a process shares it.
- `_bootstrap` reads `HUSH_CONFIG` "because settings.py still writes it" — it does not; delete.
- 11 separate `parents[N]` repo-root lookups → `src/core/paths.py`.
- `_seed.py` imports private `operonx.providers.vector_stores._pg.get_pool`.
- pyproject is named `analyze` with a placeholder description; `requirements.txt` duplicates it with other pins; the image lacks `openpyxl` directly; `psycopg` is dev-only but used at runtime — pyproject becomes the one source, image requirements from `uv export`.
- raba duplicates its classifier and detector block (`graph.py:112-137` ≈ `175-201`); hangup declares its bot LLM twice.
- hangup re-implements `hvc_row`; clean rows lack `EvidenceIdxs`, so row keys vary by verdict.
- 33 unnamed branches are auto-named `route_N` and pinned by the graph-signature test; adding one renumbers the rest.
- Dead: 4 unused prompts, unused params (`trigger_filter`, `final_label`, `checked`), a `timestamps` fallback nothing writes, stale "MapOp"/`score_one`/`03_seed_db.py` references.
- The deploy gate's dataset lives in `tests/sample/fixtures/` and ships in the image — the guide puts eval data in `datasets/`.
- docs/: 45 files in three naming styles; `hotfix-guide.md` and `operations-guide.md` point at files and flags that no longer exist — dated plans and reports go to `docs/archive/`, about five current docs stay; MLE gets one contract page that stops at our commands.

### 2.6 Phases

Each phase is its own commits, gated like the last refactor. "Snapshot" is
the 90-call byte comparison; "F1" is a VPN run scored against QC labels.

| # | phase | gate | verdicts move? |
|---|---|---|---|
| 1 | Part 1: six jobs, `main` runbook, `main.py` delegate, `ingest` merge, `tools/` | tests · snapshot · `--list` = six | no |
| 2 | selfcheck as an `Eval`; S3 keyed by run id (B3) | tests · offline Eval test on stubbed scoring · `selfcheck_build --set dry_run=true` on the record | no |
| 3 | fail loudly: A1, A2, B2, B4, B6; every terminal stamps; `_finalize` asserts | tests (new ones fail first) · snapshot | only calls whose model reply failed to parse |
| 4 | configuration standard: `RunSettings`, one reader per layer, no run-time globals, hermetic tests | tests · snapshot | no |
| 5 | the case shape: `verdict_fn`, typed fields, `config.stage`, one prompt pattern, shared helpers, names, dead code | tests · snapshot (trace op names change; output files do not) | no |
| 6 | tests layout, contract tests, CI job | the suite, reorganised, same count | no |
| 7 | docs: archive, one MLE contract page, one job list | grep | no |
| 8 | on the VPN, one at a time: A3, A4, then A5 once QC answers | F1 against QC labels, before and after | **yes** |

### 2.7 Decisions for you

1. **B1 — failed calls at MLE's boundary.** (a) keep writing `{"error"}` and
   MLE's merge drops files with an `error` key; or (b) write nothing for a
   failed call, so it is absent from the merge. (a) keeps the evidence;
   either way MLE's reader must know. I'd pick (a) and hand MLE one line.
2. **selfcheck sampling.** The `Eval` always runs the manifest's 90;
   `PIPELINE_SELFCHECK_N/SEED/SHUFFLE` go. OK?
3. **A5, A6** are questions for QC: 60 VAD entries or 60 seconds; should
   phone_source also skip `Ben_thu_3_DVKD_AF`.
4. **PII in committed files.** 95 transcripts under `samples/` and
   `tests/sample/fixtures/` carry phone numbers in their filenames. Renaming
   them to ids re-keys the baseline (one `selfcheck_build`).
5. **docs/archive/.** Move the dated plans and reports there, keep ~5 current docs?
