"""The selfcheck baseline: where it lives, and how a scored row is compared to it.

Pass = a call's sentiment row agrees with its baseline row on every HARD
field. HARD fields are what the QC UI shows plus the deterministic gates;
SOFT fields are LLM-noisy intermediates (category picks, cited pool ids) —
reported, never blocking. If a SOFT drift ever flips the verdict, the HARD
`Result` / `Score_offset` rule catches it.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "tests" / "sample" / "fixtures"
FX_INPUTS = FIXTURE_DIR / "inputs"
FX_OUTPUTS = FIXTURE_DIR / "outputs"
MANIFEST = FIXTURE_DIR / "manifest.json"

#: The prompts whose hashes the manifest records, so a prompt edit shows as
#: drift. Every path must exist — tests/repo/test_selfcheck_tracked_prompts.py.
TRACKED_PROMPTS = (
    "src/cases/sentiment_agent/l2_scanner/prompts/SCANNER_PROMPT.prompt",
    "src/cases/sentiment_agent/l3_decider/prompts/DECIDER_PROMPT.prompt",
    "src/cases/sentiment_agent/l4_verify/prompts/PRIMARY_DECIDER_PROMPT.prompt",
    "src/cases/sentiment_agent/l4_verify/prompts/SOFTEN_REASON_PROMPT.prompt",
)

CRITERIA = "Thái độ ĐTV"
TRACE_ROOT = "traces"

HARD_RULES: List[Tuple[str, list]] = [
    ("Result", ["Result"]),
    ("Score_offset", ["Score_offset"]),
    ("EvidenceIdxs", ["EvidenceIdxs"]),
    ("filter.should_scan", ["traces", "filter", "should_scan"]),
    ("filter.kw_hit", ["traces", "filter", "kw_hit"]),
    ("filter.llm_verdict", ["traces", "filter", "llm_verdict"]),
    ("filter.applied", ["traces", "filter", "applied"]),
    ("scanner.violation", ["traces", "scanner", "violation"]),
    ("decider.verdict", ["traces", "decider", "verdict"]),
    ("primary.verdict", ["traces", "primary_decider", "verdict"]),
]

SOFT_RULES: List[Tuple[str, list]] = [
    ("scanner.category", ["traces", "scanner", "category_raw"]),
    ("scanner.ev_idxs", ["traces", "scanner", "evidence_idxs_raw"]),
    ("decider.cited_p", ["traces", "decider", "cited_positives"]),
    ("decider.cited_c", ["traces", "decider", "cited_carveouts"]),
    ("primary.cited_p", ["traces", "primary_decider", "cited_positives"]),
    ("primary.cited_c", ["traces", "primary_decider", "cited_carveouts"]),
]


def manifest() -> Dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}


def sentiment_row(scoring: Optional[dict]) -> Optional[dict]:
    for row in (scoring or {}).get("Sentiment") or []:
        if row.get("Criteria") == CRITERIA:
            return row
    return None


def pick(d: Any, path: list) -> Any:
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def compare(actual: dict, baseline: dict) -> Tuple[List[str], List[str]]:
    """(hard diffs, soft diffs) — empty lists mean identical on that tier."""
    def diff(rules):
        return [f"{label}: {pick(actual, p)!r} != {pick(baseline, p)!r}"
                for label, p in rules if pick(actual, p) != pick(baseline, p)]
    return diff(HARD_RULES), diff(SOFT_RULES)


def corpus_drift() -> Tuple[bool, str, str]:
    """(in sync, baseline corpus hash, current). A corpus edit moves HARD
    fields, so a baseline recorded against another corpus is stale."""
    from src.corpus.loader import CORPUS_YAML, corpus_file_hash

    baseline = manifest().get("corpus_hash", "")
    if not baseline or not Path(CORPUS_YAML).exists():
        return True, baseline, ""
    current = corpus_file_hash(CORPUS_YAML)
    return baseline == current, baseline, current


def sha1_lf(path: Path) -> str:
    """LF-normalised sha1, so Windows and Linux agree on identical content."""
    return hashlib.sha1(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]


def git_rev() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""
