# tools

Rough tools, run by hand: plain argparse scripts, no graph, no job.
Nothing in `src/` or `app/` imports them. `--help` on each says more.

| tool | does | reads → writes |
|---|---|---|
| `qc_prepare` | a QC batch (transcript zip + review xlsx) as inputs `main.py` can score | zip + xlsx → a folder of JSON |
| `qc_compare` | our sentiment verdicts against QC's, as a cross-tab | scored outputs + xlsx → xlsx |
| `scan_report` | a day's production export as one four-layer review workbook | export JSON → xlsx |
| `corpus_export` | corpus.yaml as an xlsx, for QC to review | corpus.yaml → xlsx |
| `corpus_import` | QC's corpus xlsx back into corpus.yaml | xlsx → corpus.yaml (+ backup, review tsv) |
| `corpus_stamp_ids` | a UUID on every corpus entry that has none | corpus.yaml → corpus.yaml + id map |

None needs VPN, an LLM or a database.

## A QC batch

```powershell
uv run python -m tools.qc_prepare --zip "<batch>_trans.zip" --xlsx "<review>.xlsx" --out data/<batch>/inputs
$env:PIPELINE_INPUT_PATH="data/<batch>/inputs"; $env:PIPELINE_OUTPUT_PATH="outputs/<batch>"
uv run python main.py
uv run python -m tools.qc_compare --scored outputs/<batch> --xlsx "<review>.xlsx" --out outputs/<batch>_vs_qc.xlsx
```

Never plain-unzip a batch: the zip's entries are named `.wav` but hold
JSON, and they carry no call_code — both would score zero files while
reporting success. `qc_prepare` joins each transcript to its xlsx row on
Call ID, folds in call_code and closed_by (from `Bên ngắt máy`), and exits
1 if any transcript has no row.

`qc_compare` joins on **Call ID** too — the xlsx masks the phone and its
date column is not reliable. If QC's manual column is empty everywhere it
says so: there is no ground truth, and a table would only look
authoritative.

## Against QC's labels

F1 against QC's verdicts, and the stage behind each wrong call, is a job:
`operonx-run qc_eval` — see `src/jobs/qc_eval/README.md`.

## A production export

```powershell
uv run python -m tools.scan_report --input scanner_violations_20260924.json --output outputs/scan_20260924.xlsx
```

One row per call, four layers wide (gates · scanner · decider · primary
decider), each a yes/no plus its evidence — the first `no` is where the
call stopped. Phones are masked unless `--with-phone`.

## The corpus and QC's workbook

```powershell
uv run python -m tools.corpus_export                      # docs/corpus.xlsx
uv run python -m tools.corpus_import --dry-run            # what would change
uv run python -m tools.corpus_import                      # write corpus.yaml
uv run python -m tools.corpus_stamp_ids --dry-run
uv run python -m tools.corpus_stamp_ids --apply
uv run operonx-run ingest --set seed=true                 # then the store follows the corpus
```

The xlsx is the source of truth: an entry QC removed is gone. Ids are
recovered conservatively; rows `corpus_import` cannot place go to
`knowledge/sentiment_agent/qc_import_review.tsv` — resolve those before
shipping. Conflicting QC comments are a person's call, never a script's.
`corpus_stamp_ids` rewrites only the `- id:` lines, so comments and
layout survive.
