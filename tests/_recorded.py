"""The recorded fixture calls, as pytest params — what every replay test drives.

`tests/sample/fixtures/inputs/` holds the 90 transcripts, `outputs/` what the
pipeline wrote for each, including the sentiment row's `traces` block: every
decision a model made. `tests/_replay.py` turns that block into stubs.
"""
from __future__ import annotations

import json

import pytest

from tests._paths import ROOT

FIXTURES = ROOT / "tests" / "sample" / "fixtures"
INPUTS, OUTPUTS = FIXTURES / "inputs", FIXTURES / "outputs"

CRITERIA = "Thái độ ĐTV"


def _depends_on_an_unrecorded_pool(block: dict) -> bool:
    """True when the verdict was decided against a pool nobody wrote down.

    The primary decider is the stage that sets `Score_offset`: it cites a
    corpus entry, resolves that entry's severity, and the severity outranks
    the scanner's category — it is what produces `Thái độ warning` and
    `Thái độ cao`. It cites from its **own** retrieval pool, run from a
    different query than the filter decider's.

    That pool is the one input in the whole pipeline that is not recorded.
    The block keeps `pool_map` (slot to id) but not the entries, and the
    two pools differ in membership, not merely order — so rebuilding the
    primary's pool from the filter decider's recording is approximate, and an
    approximate pool resolves `P1` to the wrong entry and loses the
    severity silently.

    Rather than compare against a value known to be wrong for a reason
    unrelated to the code under test, any call the primary flagged is
    reported as an expected gap. That is blunt — some would replay
    correctly — but a replay harness that is right by luck is worse than
    one that is honest about its edge.

    **The fix belongs to the recording.** The primary decider should write
    its pool the way the filter decider writes `traces.retrieval`. It is the
    stage that decides the score and the only one whose input is invisible,
    which is a gap worth closing for review as much as for replay. It needs
    a fixture rebuild to take effect, so it is not folded into a refactor
    whose entire claim is that nothing changes.
    """
    sec = block.get("primary_decider")
    if not isinstance(sec, dict) or not sec.get("enabled"):
        return False
    return bool(sec.get("verdict"))


def _recorded() -> list:
    out = []
    for path in sorted(OUTPUTS.glob("*.json")):
        if not (INPUTS / path.name).exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = [
            r for r in (data.get("Sentiment") or [])
            if r.get("Criteria") == CRITERIA and "traces" in r
        ]
        if not rows:
            continue
        marks = []
        if _depends_on_an_unrecorded_pool(rows[0]["traces"]):
            marks.append(pytest.mark.xfail(
                reason="the primary decider flagged this call, and its "
                       "own retrieval pool — which sets the severity — is "
                       "not in the trace block",
                strict=True,
            ))
        out.append(pytest.param(path.name, rows[0], id=path.stem[:40], marks=marks))
    return out


RECORDED = _recorded()

#: The same calls with the xfail marks stripped. The marks are `strict=True`
#: and they are about the *verdict* — the primary decider's unrecorded pool.
#: A class-level `parametrize` applies them to every test in the class, so the
#: trace-block assertion inherited them, passed, and was reported as XPASS ⇒
#: failure. Different question, different parametrisation.
RECORDED_ALL = [pytest.param(p.values[0], p.values[1], id=p.id) for p in RECORDED]
