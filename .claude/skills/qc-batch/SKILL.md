---
name: qc-batch
description: Score a QC batch drop (transcript zip + review xlsx) end to end — prepare inputs, run the pipeline, verify the run actually scored every call, and compare verdicts against QC's labels. Use when a new batch arrives from QC or when asked to rerun/check a scored batch.
---

# Scoring a QC batch

QC sends two files per batch: a zip of ASR transcripts and an xlsx listing the
same calls. Neither is runnable as delivered, and the failure modes are silent
in both directions — a batch can score zero files without erroring, and a batch
can score every file while losing calls to LLM failures.

## 1. Confirm the two files describe the same calls

Join on **Call ID** (the trailing integer in the filename). Do not join on the
filename — the xlsx masks the phone (`CLID_038****519`) so filenames never
compare equal. Do not join on `Ngày gọi` — Excel reads `dd/mm` as `mm/dd`, so
most rows have month and day swapped and only the rows with day > 12 survive
as text.

Expect a 1:1 match. Any orphan on either side is worth raising before running.

## 2. Check whether the xlsx actually carries QC's verdicts

```
KQ thủ công / Dẫn chứng thủ công / Chấm AI
```

A blank review template and a returned review look identical at a glance. Two
checks that settle it: at raw XML level an unfilled column has exactly one cell
(the header), and an untouched workbook has `created == modified` in
`docProps/core.xml`. If those columns are empty there is **no ground truth** —
you can score the batch, but you cannot compute precision or sweep FPs, and you
should say so rather than producing a comparison that looks authoritative.

## 3. Prepare the inputs

```powershell
uv run python -m tools.qc_prepare --zip "<batch>_trans.zip" --xlsx "<review>.xlsx" --out data/<batch>/inputs
```

Never plain-unzip. Two independent reasons it would score **zero files while
reporting success**:

| | |
|---|---|
| entries are named `.wav` but hold JSON | the `score` job reads `*.json` only |
| transcripts carry no `metadata.call_code` | the `score` job skips those with only a warning |

The tool folds `call_code` + `closed_by` in from the xlsx and exits non-zero
if any transcript fails to match a row. Take `closed_by` from `Bên ngắt máy`,
never from the filename's `YES`/`NO` token — they are different things, and
`closed_by == 'AGENT'` is what arms the hangup case.

## 4. Check the LLM config before spending money

```bash
cat models.yaml                                     # which model serves each stage
grep -E '^(INCLUDE_TRACES|PIPELINE_TRACER)' local.env .env
```

Read them; do not assume them from earlier in the conversation. `main.py`
prints the resolved routing at startup too. Two that matter:

- **`llm.primary_decider` must not be `null`** in `models.yaml`, or the
  corpus-severity override never fires and no call can score `Thái độ warning`.
- **`PIPELINE_TRACER_KIND=local`** is what makes step 6 possible. Without it
  there is no way to tell a cleared call from a lost one after the fact.

`db-*` resources need VPN. Never invoke them yourself — hand the command over.

## 5. Run

```powershell
$env:PIPELINE_INPUT_PATH="data/<batch>/inputs"; $env:PIPELINE_OUTPUT_PATH="outputs/<batch>"
$env:PIPELINE_MAX_CONCURRENCY="5"; uv run python main.py
```

`main.py` takes no path flags; the `PIPELINE_*` variables configure the run,
the way the pods configure it. A failed call is recorded — it gets an
`{"error": ...}` file and the batch goes on — so the exit code says nothing
about individual calls (step 6).

Verify the discovery count before the LLM spend, not after:

```python
import asyncio
from src.jobs.score._calls import Calls

async def count(calls):
    return len([i async for i in calls.items()])

calls = Calls("data/<batch>/inputs")
print(len(calls.paths()), asyncio.run(count(calls)), calls.skipped)   # want N, N, 0
```

## 6. Verify the run — from traces, not from the exit code

**An output file existing does not mean the call was scored.** Counting files
and checking for `error` keys is not enough; both pass while calls are missing.

Each scored call writes one file to `$PIPELINE_TRACER_LOCAL_DIR`, named
for the call and carrying the stage block plus `cost_usd`:

```python
import json, glob
d = json.load(open(glob.glob("traces/<batch>/<call>_*.json")[0], encoding="utf-8"))
d["cost_usd"]          # what this call cost
d["traces"]["scanner"] # and every decision that produced the verdict
```

It is written whenever `INCLUDE_TRACES=on`, with or without op tracing —
`PIPELINE_TRACER_KIND=local` adds operonx's full op trace beside it, for a
deep debug.

Read the stage block first; it answers the question directly:

| block | meaning |
|---|---|
| `scanner.violation: false` | scanner judged it and cleared it |
| `exit.stage` = `scope` / `agent_silent` / `filter` / `bot` / `kid` / `halu` / `no_violation` | deliberately not judged, and which gate said so |
| neither present | **unexplained — investigate** |

Every terminal stamps `exit.stage`, so the third row means a lost call
rather than a quiet one.

A logged LLM timeout is not by itself a lost call. `db-gemini-3-flash` is
configured `max_retries: 10`, and the `attempt 2/2` in the timeout line is a
timeout-specific counter, not the retry budget. Confirm against the trace
before concluding anything was lost.

Only the cases enabled by `QC_ENABLE_*` in `.env` will appear. If six of seven
are missing from every trace, check the toggles before calling it a bug.

## 7. Compare against QC

```powershell
uv run python -m tools.qc_compare --scored outputs/<batch> --xlsx "<review>.xlsx" --out outputs/<batch>_vs_qc.xlsx
```

Report the before/after cross-tab of QC's `KQ Tự động` against the new
`Result`, plus the score movement. That is the artefact QC needs in order to
review — far more useful than a blank sheet plus a request.

## Traps

- A batch drop is **not** ground truth by default (step 2).
- `Ngày gọi` is corrupt; join on Call ID.
- Concurrency 5 is where the unattributed `matcher_inputs` KeyError has
  appeared. It now fails the file loudly rather than writing `OK`.
