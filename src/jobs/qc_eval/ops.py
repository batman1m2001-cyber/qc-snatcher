"""What the `qc_eval` runbook is made of.

    qc_eval_score    QCBatch (the labelled calls) ──▶ score_agent (graph.py) ──▶ agrees_with_qc
    qc_eval_report   the last qc_eval_score run ──▶ data/qc/<batch>/runs/<run id>/

Only sentiment_agent runs: it is the case QC labels, and the other six
would be LLM cost for nothing. Each call's verdict carries the row, its
stage block, and the stage that decided it — so an error points at a stage.
"""
from __future__ import annotations

import json
import logging
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from operonx.app import Dataset
from operonx.app.jobs import last_run
from operonx.core import op

from src.cases.sentiment_agent import format_sentiment_agent

from . import _batch

logger = logging.getLogger(__name__)

EVALUATOR = "agrees_with_qc"
CLEAN = "Tích cực"


# ── qc_eval_score ── an operonx Eval, declared in app/main.py


class QCBatch(Dataset):
    """The calls QC labelled, as cases: the prepared transcript is the input,
    QC's verdict the `expected`.

    The folder is the eval's `batch` input, read when the run starts — so
    `--set batch=data/qc/<round>` (applied before the run) names it, and
    `QC_BATCH` is only the default. `inputs` is the eval's own dict,
    handed over once the eval exists."""

    def __init__(self) -> None:
        self.inputs: Dict[str, Any] = {}
        self.batch: Optional[Path] = None
        self.size: Optional[int] = None  # set when the run reads the batch
        super().__init__(Path("data/qc"))

    def rows(self) -> list:
        batch = self.inputs.get("batch")
        if not batch:
            raise ValueError("no batch — run with --set batch=data/qc/<round>, or set QC_BATCH")
        self.batch = self.path = Path(batch)
        found = _batch.prepare(self.batch)
        for what in ("no_row", "unlabelled", "no_transcript"):
            if found[what]:
                logger.warning("%s: %d %s, not scored (e.g. %s)", self.batch.name, len(found[what]),
                               what.replace("_", " "), found[what][0])
        rows = []
        for cid, r in sorted(found["review"].items()):
            if r["violation"] is None or "file" not in r:
                continue
            path = self.batch / "inputs" / f"{r['file']}.json"
            meta = json.loads(path.read_text(encoding="utf-8")).get("metadata") or {}
            rows.append({"id": r["file"],
                         "input": {"path": str(path), "name": r["file"], "metadata": meta},
                         "expected": {"call_id": cid, "violation": r["violation"],
                                      "label": r["label"], "comment": r["comment"]}})
        if not rows:
            raise RuntimeError(f"{self.batch}: no labelled call has a transcript — nothing to score")
        self.size = len(rows)
        return rows


def _is(value) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def decided_by(traces: dict) -> str:
    """The stage whose answer made the verdict: the one that cleared the
    call, or `flagged` when every stage let it through. For a false
    negative that is where to look; a false positive is always `flagged`."""
    exit_ = traces.get("exit") or {}
    stage = exit_.get("stage")
    if stage == "no_violation":
        return "scanner"
    if stage == "halu":
        return "halu_check"
    if stage:
        return f"gate:{stage}"
    for name in ("asr_check", "decider"):
        block = traces.get(name)
        if isinstance(block, dict) and "verdict" in block and not _is(block["verdict"]):
            return name
    primary = traces.get("primary_decider") or {}
    if _is(primary.get("enabled")) and primary.get("verdict") is not None and not _is(primary["verdict"]):
        return "primary"
    return "flagged"


def agrees_with_qc(output: dict = None, expected: dict = None) -> Dict[str, Any]:
    """One call against QC's verdict: TP / FP / FN / TN, the stage that
    decided it, and the row itself — the report reads it from here."""
    result = (output or {}).get("result")
    if not isinstance(result, dict):
        return {"passed": False, "reason": "sentiment_agent produced no result", "outcome": "error"}
    row = format_sentiment_agent(result, include_traces=True)
    ours = row["Result"] != CLEAN
    qc = bool(expected["violation"])
    outcome = {(True, True): "TP", (True, False): "FP", (False, True): "FN", (False, False): "TN"}[(ours, qc)]
    stage = decided_by(row.get("traces") or {})
    return {"passed": ours == qc, "reason": None if ours == qc else f"{outcome} at {stage}",
            "outcome": outcome, "stage": stage, "row": row}


agrees_with_qc.eval_name = EVALUATOR


class Show:
    """One line per call — `[3/235] FN   <name>  at primary`. One per run;
    the total is the batch's, known once the run has read it."""

    def __init__(self, batch: Optional["QCBatch"] = None) -> None:
        self.batch, self.done = batch, 0

    def __call__(self, result: Any) -> None:
        self.done += 1
        check = ((result.verdict or {}).get("checks") or {}).get(EVALUATOR) or {}
        outcome = check.get("outcome") or "ERR"
        where = f"  at {check.get('stage')}" if outcome in ("FP", "FN") else ""
        total = f"/{self.batch.size}" if self.batch is not None and self.batch.size else ""
        print(f"[{self.done}{total}] {outcome:3s} {result.key}{where}", flush=True)


# ── qc_eval_report ── the last qc_eval_score run ──▶ the batch's runs/ folder


def _f1(counts: Counter) -> dict:
    tp, fp, fn, tn = (counts[k] for k in ("TP", "FP", "FN", "TN"))
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "errors": counts["error"],
            "precision": round(p, 3), "recall": round(r, 3),
            "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "qc_flagged": tp + fn, "we_flagged": tp + fp}


def _funnel(calls: List[dict]) -> List[str]:
    """How many calls each stage let through, beside how many QC flagged."""
    def reached(c, stage):
        tr = (c.get("row") or {}).get("traces") or {}
        if stage == "scanner":
            return _is((tr.get("scanner") or {}).get("violation"))
        if stage == "decider":
            return reached(c, "scanner") and decided_by(tr) not in ("scanner", "halu_check", "decider", "asr_check")
        return c.get("ours_flagged")
    judged = [c for c in calls if c["outcome"] != "error"]
    lines = [f"{'scanner flagged':22s} {sum(reached(c, 'scanner') for c in judged):4d}",
             f"{'after decider':22s} {sum(reached(c, 'decider') for c in judged):4d}",
             f"{'after primary (final)':22s} {sum(reached(c, 'final') for c in judged):4d}",
             f"{'QC flagged':22s} {sum(c['qc_flagged'] for c in judged):4d}", ""]
    for outcome in ("FN", "FP"):
        by = Counter(c["stage"] for c in judged if c["outcome"] == outcome)
        lines.append(f"{outcome} by the stage that decided them: " + (", ".join(f"{s} {n}" for s, n in by.most_common()) or "none"))
    return lines


def _stamp() -> dict:
    """What produced the run: code, corpus, prompts, models."""
    from importlib.metadata import version

    from src.core import config
    from src.corpus.loader import CORPUS_YAML, corpus_file_hash
    from src.jobs.selfcheck import _baseline as baseline

    return {"git": baseline.git_rev(), "operonx": version("operonx"), "corpus": corpus_file_hash(CORPUS_YAML),
            "prompts": {Path(p).stem: baseline.sha1_lf(baseline.ROOT / p) for p in baseline.TRACKED_PROMPTS},
            "models": {"default": config.LLM_RESOURCE_KEY, "decider": config.DECIDER_LLM_RESOURCE_KEY,
                       "primary": config.PRIMARY_DECIDER_LLM_RESOURCE_KEY, "soften": config.SOFTEN_LLM_RESOURCE_KEY,
                       "prefilter": config.PREFILTER_LLM_RESOURCE_KEY}}


def _previous(runs: Path, run_id: str) -> Optional[Dict[str, dict]]:
    earlier = sorted(p for p in runs.iterdir() if p.is_dir() and p.name < run_id and (p / "calls.json").exists())
    return json.loads((earlier[-1] / "calls.json").read_text(encoding="utf-8")) if earlier else None


def _diff(now: Dict[str, dict], before: Optional[Dict[str, dict]]) -> List[str]:
    if before is None:
        return ["no earlier run of this batch — nothing to compare"]
    fixed, broke = [], []
    for key, c in sorted(now.items()):
        was = before.get(key)
        if not was or was["outcome"] == c["outcome"]:
            continue
        line = f"{was['outcome']} -> {c['outcome']}  {key}  (was at {was['stage']}, now at {c['stage']})"
        (fixed if c["outcome"] in ("TP", "TN") else broke).append(line)
    return [f"fixed {len(fixed)}", *fixed, "", f"broke {len(broke)}", *broke]


def _slim(calls: Dict[str, dict]) -> Dict[str, dict]:
    """The rows as `calls.json` keeps them: retrieval pools by corpus id —
    their text is in the run's `corpus.yaml` snapshot — so a run is ~1 MB,
    not ~3 MB of corpus text repeated per call."""
    out = json.loads(json.dumps(calls))
    for c in out.values():
        pools = ((c.get("row") or {}).get("traces") or {}).get("retrieval") or {}
        for side in ("positives", "carveouts"):
            if isinstance(pools.get(side), list):
                pools[side] = [x.get("id") if isinstance(x, dict) else x for x in pools[side]]
    return out


def _write_xlsx(path: Path, calls: List[dict]) -> None:
    from openpyxl import Workbook

    def block(c, name):
        return ((c.get("row") or {}).get("traces") or {}).get(name) or {}

    wb = Workbook()
    ws = wb.active
    ws.title = "calls"
    ws.append(["call_id", "file", "outcome", "stage", "qc_label", "qc_comment", "ours", "reasoning", "evidence",
               "scanner_category", "scanner_reason", "decider_verdict", "decider_reason", "decider_cited",
               "primary_verdict", "primary_reason", "primary_cited", "severity_final"])
    order = {"FN": 0, "FP": 1, "error": 2, "TP": 3, "TN": 4}
    for c in sorted(calls, key=lambda c: (order.get(c["outcome"], 9), c["stage"], c["file"])):
        row, sc, de, pr = c.get("row") or {}, block(c, "scanner"), block(c, "decider"), block(c, "primary_decider")
        ws.append([c["call_id"], c["file"], c["outcome"], c["stage"], c["qc_label"], c["qc_comment"],
                   row.get("Result"), row.get("Reasoning"), row.get("Evidence"),
                   sc.get("category_raw"), sc.get("reason"), str(de.get("verdict")), de.get("reason"),
                   ", ".join(map(str, de.get("cited_positives") or [])), str(pr.get("verdict")), pr.get("reason"),
                   ", ".join(map(str, pr.get("cited_positives") or [])), pr.get("severity_final")])
    wb.save(path)


@op
def write_report(batch: str = "", record_dir: str = ".runs") -> Dict[str, Any]:
    """F1 and where the errors came from, for the last `qc_eval_score` run, into
    `<batch>/runs/<run id>/`: summary.json, calls.xlsx, calls.json (the rows
    with their stage blocks, pools by corpus id), corpus.yaml (the corpus the
    run used), stages.txt and diff.txt."""
    run = last_run(record_dir, "qc_eval_score")
    if run is None:
        raise RuntimeError(f"no qc_eval_score run under {record_dir} — run `operonx-run qc_eval` first")
    calls: Dict[str, dict] = {}
    for item in run.items:
        v = item.verdict or {}
        check = (v.get("checks") or {}).get(EVALUATOR) or {}
        expected = v.get("expected") or {}
        outcome = check.get("outcome") or "error"
        calls[item.key] = {
            "file": item.key, "call_id": expected.get("call_id"), "qc_label": expected.get("label"),
            "qc_comment": expected.get("comment"), "qc_flagged": bool(expected.get("violation")),
            "outcome": outcome, "stage": check.get("stage") or (v.get("error") or item.status or "error"),
            "ours_flagged": outcome in ("TP", "FP"), "row": check.get("row")}
    counts = Counter(c["outcome"] for c in calls.values())
    out = Path(batch) / "runs" / run.run_id
    out.mkdir(parents=True, exist_ok=True)
    summary = {"batch": str(batch), "run_id": run.run_id, "calls": len(calls), **_f1(counts), "stamp": _stamp()}
    diff = _diff(calls, _previous(out.parent, run.run_id))
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "calls.json").write_text(json.dumps(_slim(calls), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    from src.corpus.loader import CORPUS_YAML

    shutil.copyfile(CORPUS_YAML, out / "corpus.yaml")
    (out / "stages.txt").write_text("\n".join(_funnel(list(calls.values()))) + "\n", encoding="utf-8")
    (out / "diff.txt").write_text("\n".join(diff) + "\n", encoding="utf-8")
    _write_xlsx(out / "calls.xlsx", list(calls.values()))
    print(f"\n{Path(batch).name} · run {run.run_id} · {len(calls)} calls\n"
          f"  F1 {summary['f1']:.3f}   precision {summary['precision']:.3f}   recall {summary['recall']:.3f}\n"
          f"  TP {summary['TP']}  FP {summary['FP']}  FN {summary['FN']}  TN {summary['TN']}  errors {summary['errors']}\n"
          + "\n".join("  " + line for line in _funnel(list(calls.values())))
          + f"\n  {diff[0]}" + (f", {diff[diff.index('') + 1]}" if "" in diff else "")
          + f"\n  -> {out}", flush=True)
    return {"f1": summary["f1"], "out": str(out)}
