---
name: selfcheck
description: Rebuild and interpret the selfcheck baseline in tests/sample/fixtures — which jobs to run, what counts as expected drift vs real regression, and what to commit. Use after a corpus, prompt, or pipeline change, or when selfcheck fails.
---

# Selfcheck baseline

`selfcheck` is a runbook — preflight ▶ ingest (seeding a stale store) ▶
`selfcheck_score`, an operonx `Eval`: the 90 fixture calls through the
scoring graph, each compared with its recorded baseline row in
`tests/sample/fixtures/`. In the deploy pipeline it runs as
`python main.py --selfcheck`, once, before the `main.py` pods start.

## The jobs

| command | does |
|---|---|
| `operonx-run selfcheck` | scores the 90 calls, one PASS/FAIL line each, then the pass rate; exits 1 under the threshold |
| `operonx-run selfcheck_build` | **promote** the last selfcheck_score run to be the baseline — no LLM calls |

To rebuild:

```powershell
uv run operonx-run selfcheck                           # costs LLM calls; read the drift
uv run operonx-run selfcheck_build --set dry_run=true  # what would change
uv run operonx-run selfcheck_build                     # accept it
```

`selfcheck_build` reads the last selfcheck_score run's record and refuses unless
every manifest call scored with its stage block — a half-scored baseline is worse than
an old one. Each promoted row carries its stage block inline (`traces`).

Re-selecting which calls are in the sample is a rare task with no job;
the old selection script is in `scripts/_archive/`.

Needs VPN for `db-*` resources — hand the command to the user rather than
running it.

## Match rate, not exact match

Pass = HARD-field match rate ≥ `PIPELINE_SELFCHECK_MATCH_THRESHOLD`
(default **0.85**, the deployment's value). A healthy run matches about 90–93%
on this fixture (four runs, 2026-09-29/30): a few calls are coin flips on the
Databricks models, so two runs disagree on 6–8 of 90 even on identical code, and
re-recording the baseline only moves which side it holds. On a UAT
batch the Databricks endpoints flipped ~27% of Results between identical
runs (272 calls; `seed` has no effect), so a threshold near 1.0 would fail
on noise alone — and the global rate can hide a fault confined to the
flagged third, so check that subset.
Under the threshold the run fails, and so does the deploy;
`PIPELINE_SELFCHECK_MATCH_THRESHOLD=0` makes it warn-only.

| tier | fields | on diff |
|---|---|---|
| HARD | `Result`, `Score_offset`, `EvidenceIdxs`, `filter.*`, `scanner.violation`, `decider.verdict`, `primary.verdict` | counts against match rate |
| SOFT | `scanner.category`, `scanner.ev_idxs`, `decider.cited_*`, `primary.cited_*` | reported, never blocks |

A missing key reads as `None` and the compare tests `a != b`, so a
newly-*added* trace field reads as a HARD diff on every call that gains it.
A change that only adds observability still costs a full rebuild.

## Reading a diff

Each FAIL line names the call's first HARD difference. Every call's verdict
— all HARD and SOFT differences, and what it scored — is in
`.runs/selfcheck_score/<run>/items.jsonl`; `operonx-run selfcheck_build --set
dry_run=true` prints them all against the baseline. F1 against QC's labels
is the `qc_eval` job, on a QC batch (`src/jobs/qc_eval/README.md`).

| what you see | reading |
|---|---|
| scattered `Result` flips, no pattern, rate still ≥ 0.85 | LLM noise floor — expected |
| a HARD field flips the same way on many calls | real change; confirm it is the one you intended |
| `filter.*` diffs | **not** noise — the filter gate is pure Python and deterministic |
| a field goes `X != None` on a subset | you added or removed a trace field |
| match rate collapses toward 0 | config drift, not model drift — wrong resource key, empty corpus. Read the preflight and ingest lines above the scoring |

The runbook's first two steps name a wrong or unreachable resource
(preflight) and seed a corpus store that does not hold this corpus
(ingest) — so a hand-run `operonx-run selfcheck` seeds the store it points
at, as the deploy gate does.

## Afterwards

**Commit `tests/sample/fixtures/`** — the manifest and all rescored outputs.
An uncommitted rebuild means the next selfcheck compares against the old
baseline and fails on exactly the calls you just fixed.

The eval turns `INCLUDE_TRACES` on when it starts; most HARD fields live
under `traces.*` and the config default is `off`, so inheriting the deploy env
would null them. A row without its stage block fails as `blind`.
