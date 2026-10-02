"""What the `selfcheck` eval and the `selfcheck_build` job are made of.

    selfcheck         Fixtures (the cases) ──▶ score_fixture (graph.py) ──▶ matches_baseline
    selfcheck_build   read_run ──▶ promote

The eval is operonx's: it runs the graph once per case, calls the
evaluator, and keeps each verdict in its run record (`.runs/selfcheck_score/<run>/`).
`selfcheck_build` promotes the run from that record — no files in between.
"""
from __future__ import annotations

import collections
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from operonx.app import Dataset
from operonx.app.jobs import last_run
from operonx.core import op

from . import _baseline as baseline

logger = logging.getLogger(__name__)

EVALUATOR = "matches_baseline"


# ── selfcheck ── an operonx Eval, declared in app/main.py


class Fixtures(Dataset):
    """The manifest's calls as cases: the transcript is the input, its
    baseline sentiment row the `expected`."""

    def __init__(self) -> None:
        super().__init__(baseline.MANIFEST)

    def rows(self) -> list:
        in_sync, was, now = baseline.corpus_drift()
        if not in_sync:
            logger.warning("STALE BASELINE — recorded on corpus %s, the corpus is now %s: the match rate "
                           "measures that change. Rebuild: operonx-run selfcheck, then operonx-run "
                           "selfcheck_build", was, now)
        rows = []
        for entry in baseline.manifest().get("selected", []):
            name = entry["filename"]
            call = json.loads((baseline.FX_INPUTS / name).read_text(encoding="utf-8"))
            recorded = json.loads((baseline.FX_OUTPUTS / name).read_text(encoding="utf-8"))
            rows.append({
                "id": name[:-5],
                "input": {"path": str(baseline.FX_INPUTS / name), "name": name[:-5], "metadata": call.get("metadata") or {}},
                "expected": baseline.sentiment_row(recorded),
            })
        if not rows:
            raise RuntimeError(f"no fixture calls in {baseline.MANIFEST} — an eval with no cases would pass")
        return rows


def matches_baseline(output: dict = None, expected: dict = None) -> Dict[str, Any]:
    """One call against its baseline row: a HARD difference fails it, SOFT
    ones are listed. `scored` rides on the verdict so `selfcheck_build` can
    promote the run from its record, which clips `output` to 4000 characters."""
    scored = (output or {}).get("call_scoring")
    row = baseline.sentiment_row(scored)
    if row is None or expected is None:
        return {"passed": False, "reason": "no sentiment_agent row on one side", "scored": scored}
    if not isinstance(row.get(baseline.TRACE_ROOT), dict) or not isinstance(expected.get(baseline.TRACE_ROOT), dict):
        # Without it 7 of the 10 HARD rules compare None to None and agree.
        return {"passed": False, "reason": "blind: no stage block to compare", "scored": scored}
    hard, soft = baseline.compare(row, expected)
    return {"passed": not hard, "reason": hard[0] if hard else None, "hard": hard, "soft": soft,
            "scored": scored}


matches_baseline.eval_name = EVALUATOR


class Show:
    """One line per call — `[3/90] PASS name`, or FAIL with the first HARD
    difference. One per run: the count starts at zero."""

    def __init__(self) -> None:
        self.done, self.total = 0, None

    def __call__(self, result: Any) -> None:
        if self.total is None:
            self.total = len(baseline.manifest().get("selected", []))
        self.done += 1
        verdict = result.verdict or {}
        if verdict.get("passed"):
            line = f"PASS  {result.key}"
        else:
            check = (verdict.get("checks") or {}).get(EVALUATOR) or {}
            line = f"FAIL  {result.key}  {check.get('reason') or verdict.get('error') or result.status}"
        print(f"[{self.done}/{self.total}] {line}", flush=True)


# ── selfcheck_build ── promote the last selfcheck run


@op
def read_run(record_dir: str = ".runs") -> Dict[str, Any]:
    """Every manifest call's scored output from the last selfcheck run — or
    refuse: a half-scored baseline is worse than an old one."""
    run = last_run(record_dir, "selfcheck_score")
    if run is None:
        raise RuntimeError("no selfcheck_score run — run operonx-run selfcheck first")
    scored = {i.key: (((i.verdict or {}).get("checks") or {}).get(EVALUATOR) or {}).get("scored")
              for i in run.items}
    wanted = [e["filename"][:-5] for e in baseline.manifest().get("selected", [])]
    unusable = [k for k in wanted if not isinstance((baseline.sentiment_row(scored.get(k)) or {}).get(baseline.TRACE_ROOT), dict)]
    if unusable:
        raise RuntimeError(f"run {run.run_id}: {len(unusable)} of {len(wanted)} calls have no scored row "
                           f"with its stage block, e.g. {unusable[:3]} — refusing a half-scored baseline")
    return {"run": run.run_id, "scored": {k: scored[k] for k in wanted}}


@op
def promote(scored: dict = None, dry_run: bool = False) -> Dict[str, Any]:
    """Print how the run differs from the baseline; unless *dry_run*, make
    it the baseline and stamp the manifest."""
    hard, soft = {}, collections.Counter()
    for key, data in scored.items():
        old = json.loads((baseline.FX_OUTPUTS / f"{key}.json").read_text(encoding="utf-8"))
        diffs, noise = baseline.compare(baseline.sentiment_row(data), baseline.sentiment_row(old) or {})
        if diffs:
            hard[key] = diffs
        soft.update(d.split(":", 1)[0] for d in noise)
    print(f"{len(hard)}/{len(scored)} calls differ from the baseline on a HARD field", flush=True)
    for key, diffs in hard.items():
        print(f"  · {key}: {'; '.join(diffs)}", flush=True)
    if soft:
        print("SOFT drift: " + ", ".join(f"{field} {n}" for field, n in soft.most_common()), flush=True)
    if dry_run:
        return {"report": {"differ": len(hard), "written": False}}

    for key, data in scored.items():
        (baseline.FX_OUTPUTS / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    m = baseline.manifest()
    _, _, corpus = baseline.corpus_drift()
    m.update({
        "corpus_hash": corpus or m.get("corpus_hash", ""),
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "pipeline_rev": baseline.git_rev(),
        "rebuilt_by": "operonx-run selfcheck_build",
        "prompt_hashes": {Path(rel).name: baseline.sha1_lf(baseline.ROOT / rel) for rel in baseline.TRACKED_PROMPTS},
    })
    baseline.MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    print("baseline promoted — commit tests/sample/fixtures/", flush=True)
    return {"report": {"differ": len(hard), "written": True}}
