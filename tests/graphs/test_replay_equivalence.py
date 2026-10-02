"""Replay 90 recorded calls and assert the verdict is *equal*, not close.

Step 0a, T4 of `docs/archive/PLAN_sentiment_agent_layers.md`, and the guarantee the
layer refactor rests on. Selfcheck cannot provide it: on a ~27% Result-flip
floor it can say *close enough*, never *identical*, so a real regression
hides under the noise and a clean run proves little.

So the models are not called. Every decision they made is already recorded
in `tests/sample/fixtures/outputs/`, and the recording turned out to be
complete enough to drive the graph — checked field by field in
`tests/_replay.py`. The pipeline runs for real; only the models are
replayed.

**Offline by construction, not by intention.** `install_stubs` poisons
every LLM op and every retrieval subgraph first, then overwrites the ones
the recording covers. A path the recording cannot drive raises
`WouldHaveCalledOut` instead of dialling a live endpoint. An earlier
version stubbed only what the block carried and left two ops live — which
is exactly how a "no network" harness quietly makes network calls.
"""
from __future__ import annotations

import asyncio

import pytest

from src.core.conversation import Conversation
from tests._engine import apply_case_selection, create_engine
from tests._recorded import CRITERIA, INPUTS, OUTPUTS, RECORDED, RECORDED_ALL
from tests._replay import build_stubs, install_stubs

#: Fields that are the verdict. `traces` is excluded — it is diagnosis, and
#: it is also the input to the replay, so comparing it would be circular.
VERDICT_FIELDS = ("Result", "Score_offset", "Evidence", "Reasoning", "CriteriaCode")

#: One replay per call, shared by the two assertions that read it. Keyed on
#: name: the block is a dict and the graph is deterministic once the models
#: are stubbed, so two calls with the same name cannot differ.
_MEMO: dict = {}


def _replay_once(name: str, block: dict) -> dict:
    """The formatted sentiment row for one replayed call."""
    return _replay_both(name, block)[0]


def _replay_meta(name: str, block: dict) -> dict:
    """The case's own `_trace_meta`, read from state rather than the row.

    Not `row["traces"]`. That key only appears when `INCLUDE_TRACES` is on,
    and other tests in this suite reload `src.config` with their own
    environment — so the row arrives trace-less depending on what ran before
    it. All 90 of these assertions passed in isolation and failed in the full
    suite for exactly that reason. `_trace_meta` is stamped unconditionally,
    which is what the assertion is actually about.
    """
    return (_replay_both(name, block)[1] or {}).get("_trace_meta") or {}


def _replay_both(name: str, block: dict) -> tuple:
    if name not in _MEMO:
        _MEMO[name] = _replay(name, block)
    return _MEMO[name]


def _replay(name: str, block: dict) -> tuple:
    """Run the real graph for one call with the models replayed.

    Returns `(row, verdict)` — the formatted sentiment row and the case's own
    result dict. Both come from one run.
    """
    engine, _ = create_engine(tracer_kind="none")
    apply_case_selection(engine, {"sentiment_agent"})
    install_stubs(engine.graph, build_stubs(block))

    conversation = Conversation.load(str(INPUTS / name))
    result = asyncio.run(engine.run(inputs={
        "conversation": conversation,
        "call_code": "",
        "closed_by": "YES",
        "is_chinh_chu": False,
        "queue_id": 0,
    }))
    rows = [
        r for r in ((result.get("call_scoring") or {}).get("Sentiment") or [])
        if r.get("Criteria") == CRITERIA
    ]
    state = result.get("$state")
    verdict = state.get("qc_flow.sentiment_agent", "result") if state is not None else None
    return (rows[0] if rows else {}), verdict


class TestTheRecordingIsUsable:
    def test_there_are_fixtures_to_replay(self):
        assert len(RECORDED) >= 80, f"only {len(RECORDED)} recorded calls found"

    def test_every_fixture_has_an_input(self):
        missing = [p.name for p in OUTPUTS.glob("*.json") if not (INPUTS / p.name).exists()]
        assert missing == [], missing


#: Stages every call passes through, so every trace block must name them.
#: `filter` is stamped in l1 and `scanner` in l2; a block missing either means
#: a later layer rebuilt `_trace_meta` instead of carrying it forward.
#:
#: Not asserting the whole shape. `decider` and `retrieval` appear only on the
#: l3 path, which this harness does not reach — see
#: `TestTheHarnessKnowsItsOwnLimits` below.
_ALWAYS_STAMPED = ("filter", "scanner")


@pytest.mark.parametrize("name,recorded", RECORDED)
class TestReplayedVerdictIsIdentical:
    def test_the_verdict_matches(self, name, recorded):
        """Equal, not close. A refactor that changes no logic must land here."""
        got = _replay_once(name, recorded["traces"])
        assert got, "the graph produced no sentiment row at all"
        diffs = [
            f"{f}: {got.get(f)!r} != {recorded.get(f)!r}"
            for f in VERDICT_FIELDS
            if got.get(f) != recorded.get(f)
        ]
        assert diffs == [], "\n  ".join([""] + diffs)

@pytest.mark.parametrize("name,recorded", RECORDED_ALL)
class TestTheTraceBlockSurvivesEveryLayer:
    """Separate class because the xfail marks on `RECORDED` do not apply here.

    Those marks are about the verdict on calls whose severity came from the
    primary decider's unrecorded pool. The trace block is a different
    question and is expected to hold on every call, flagged or not.
    """

    def test_the_trace_block_survives_every_layer(self, name, recorded):
        """The earlier layers' stamps must still be there at the end.

        This is the assertion the 2026-09-24 wiring defect failed, and the
        reason it needed a paid run to find: `l4`'s data ref named `l3`, so a
        call an earlier layer decided arrived with `result=None` and `l4`
        stamped a fresh `_trace_meta`. Ten of ninety calls came back carrying
        `primary_decider, soften` and nothing else.

        `test_the_verdict_matches` could not see it. A gate-cleared call
        scores `Tích cực` whether the verdict came from the gate or from the
        default row, so all 80 looked identical while the audit trail — the
        one thing that separates "deliberately cleared" from "silently lost"
        — was being dropped.
        """
        block = _replay_meta(name, recorded["traces"])
        assert block, "nothing stamped `_trace_meta` at all"
        missing = [s for s in _ALWAYS_STAMPED if s not in block]
        assert missing == [], (
            f"trace block lost {missing} — it holds {sorted(block)}. Every "
            f"call passes through l1 and l2, so a later layer overwrote "
            f"`_trace_meta` rather than carrying it forward."
        )


class TestTheHarnessKnowsItsOwnLimits:
    """What this harness does *not* cover, asserted so it cannot be forgotten.

    Two defects shipped in one day behind the phrase "80 calls replay
    verdict-identical", which sounded like broad cover and is not. The
    recorded block feeds stubbed evidence, and attribution routing then sends
    every replayed call to an l2 exit — so `l3` is never entered here. The
    decider, its retrieval and the ASR-check route are exercised by selfcheck
    and by nothing offline.

    Stated as a test rather than a comment so that the day someone makes the
    harness drive l3, this fails and tells them to widen the assertions above
    instead of leaving `_ALWAYS_STAMPED` understating what is checkable.
    """

    def test_no_replayed_call_reaches_the_decider(self):
        reached = [
            name for name, recorded in ((p.values[0], p.values[1]) for p in RECORDED)
            if "decider" in _replay_meta(name, recorded["traces"])
        ]
        assert reached == [], (
            f"{len(reached)} replayed call(s) now reach l3 — the harness got "
            f"better. Add 'decider' and 'retrieval' to `_ALWAYS_STAMPED` for "
            f"those calls and delete this test."
        )
