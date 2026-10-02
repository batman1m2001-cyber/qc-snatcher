# selfcheck

Does the pipeline still score the fixture calls the way the baseline does?
And, when a change is meant to move them, make the new scores the baseline.

## selfcheck — the 90 fixture calls, each against its baseline row.

```
    python main.py --selfcheck            # the deploy gate: MLE's secrets, then the runbook, then S3
    operonx-run selfcheck                 # the runbook alone; LLM cost; exit 1 under the threshold

A runbook (app/main.py): preflight ▶ ingest, seeding a stale store ▶
selfcheck_score, an operonx Eval:

    Fixtures ──▶ score_fixture ──▶ matches_baseline
    the 90        load_call ▶        the call's sentiment row against its
    manifest      score_cases       baseline row: a HARD difference fails
    calls         (the scoring       it, SOFT ones are listed
                  graph)

HARD  what the QC UI shows + the deterministic gates: Result, Score_offset,
      EvidenceIdxs, filter.*, scanner/decider/primary verdicts
SOFT  LLM-noisy intermediates: scanner category and turns, cited pool ids
blind a row without its stage block fails: 7 of the 10 HARD rules read it

pass  = the share of calls that match ≥ PIPELINE_SELFCHECK_MATCH_THRESHOLD
        (default 0.85; 0 makes it warn-only). A healthy run matches about 90–93%.

One line per call as it finishes (PASS, or FAIL with the first HARD
difference), then the pass rate. Every call's verdict and scored output is
in the run record, `.runs/selfcheck_score/<run>/items.jsonl`; `python
main.py --selfcheck` uploads that record to S3 (`_gate.py`), one folder
per run id. A baseline
recorded on another corpus is warned about at the start: the rate would
measure the corpus change.

Needs : VPN. Cost: one scoring run of the 90 calls.
```


## selfcheck_build — make the last selfcheck_score run the baseline.

```
    operonx-run selfcheck                             # score, and read the drift
    operonx-run selfcheck_build --set dry_run=true    # every HARD difference, SOFT counts
    operonx-run selfcheck_build                       # accept it: promote the run

    read_run ──▶ promote

Reads the last selfcheck_score run's record and refuses unless every manifest
call scored with its stage block — a half-scored baseline is worse than an
old one. Writes each call's scored output to `tests/sample/fixtures/outputs/`
(stage block inline) and stamps the manifest: corpus hash, prompt hashes,
git rev, time.

A person decides the drift is intended; this only writes. Commit
`tests/sample/fixtures/` afterwards.
Needs : nothing (reads the record). Cost: none.
```
