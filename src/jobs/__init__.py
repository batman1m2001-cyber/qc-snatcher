"""The tooling: one folder per graph a Job in `app/main.py` runs.

Nothing outside `src/jobs/` imports it — the scoring product (`src/qc/`,
`src/cases/`) never depends on the jobs that operate on it.
"""
