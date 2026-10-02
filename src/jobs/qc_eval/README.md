# qc_eval

Are the verdicts right? A QC batch scored against QC's own labels — F1, and
for every call we got wrong, the stage that decided it. Built for the loop:
fix a corpus entry or a prompt, run again, read what it fixed and what it broke.

## A batch

One folder per QC round, named by the dates of its calls — `aug0308`,
`aug2127`: the round's sheet, transcripts and every run of it in one place.

```
data/qc/<round>/                 (gitignored)
  review.xlsx                    QC's sheet — exactly one .xlsx
  <anything>.zip | transcripts/  the transcripts as QC sent them (.wav names holding JSON)
  inputs/                        written: one JSON per labelled call, call_code + closed_by folded in
  runs/<run id>/                 written by qc_eval_report
```

It is gitignored for a reason: a transcript is the whole call verbatim, and a
row quotes the evidence turns. None of it goes into the repo, a ticket, a chat
or a doc without being reduced to counts first.

The sheet's layout changes between batches, so columns are found by name:
the header is the first row (within five, on any sheet) with `Call ID` and a
label column — `KQ QC hiện tại` (round 3), `KQ thủ công` (Aug 11–13) or
`QC result`. Rows are filtered to `Tiêu chí = Thái độ ĐTV` where that column
exists. A label other than `Tích cực` is a violation (case ignored); a blank
label is not scored. Transcripts join rows on **Call ID**, the trailing
integer of the file name. Transcripts with no row, rows with no transcript
and unlabelled rows are counted in the log, never scored.

## qc_eval — the batch, end to end

```powershell
uv run operonx-run qc_eval --set batch=data/qc/aug2127        # LLM cost: one sentiment_agent run per call
```

    preflight ──▶ qc_eval_score ────────────────────────▶ qc_eval_report
    endpoints     QCBatch ──▶ score_agent ──▶ agrees_with_qc
    answer?       labelled    load_call ▶      TP / FP / FN / TN,
                  calls       sentiment_agent  the deciding stage,
                              alone            the row + stage block

`--set batch=` names the batch folder (`QC_BATCH` is the default).
Only sentiment_agent runs — it is the case QC labels; the other six would be
LLM cost for nothing. `QC_CONCURRENCY` (default 5) calls at once, one line
each: `[12] FN  <call>  at primary`. Disagreeing with QC does not fail the
run; the report measures it.

## qc_eval_report — what the run means

```powershell
uv run operonx-run qc_eval_report --set batch=data/qc/aug2127   # again, from the last qc_eval_score run
```

Into `data/qc/<round>/runs/<run id>/`:

| file | holds |
|---|---|
| `summary.json` | F1, precision, recall, TP/FP/FN/TN, errors — and the stamp: git rev, operonx, corpus hash, prompt hashes, the model of each stage |
| `calls.xlsx` | one row per call, errors first: QC's label and comment, our Result, outcome, deciding stage, scanner / decider / primary verdict, reason and cited corpus ids |
| `calls.json` | the same calls with their whole row and stage block (retrieval pools as corpus ids) — what `diff.txt` compares |
| `corpus.yaml` | the corpus the run used — the text behind every id, as it was |
| `stages.txt` | the funnel — scanner flagged ▶ after decider ▶ final ▶ QC flagged — and FN / FP counted by deciding stage |
| `diff.txt` | against the batch's previous run: calls fixed and calls broken, each with where it was decided before and now |

The deciding stage: `gate:<scope|agent_silent|filter|bot|kid>` (not judged),
`scanner` (cleared it), `halu_check` (citation invented), `decider` /
`asr_check` (the filter decider dropped it), `primary` (the primary decider
downgraded it), `flagged` (every stage let it through — where every FP is).

## Reading it

The endpoints flip ~27% of final Results between identical runs, so F1
moves a few points on its own; `diff.txt` shows the calls that moved. A fix
that mends its target and breaks as many elsewhere is the pattern to catch
(round 3: 12 fixed, 12 broken on held-out calls). A call QC's comment gave
a corpus entry to is in-sample: its F1 is not accuracy.
