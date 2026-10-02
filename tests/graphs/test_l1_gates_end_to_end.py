"""The l1 gates, end to end, with every network op poisoned.

**Nothing else covers these.** All 90 fixture calls carry both `filter` and
`scanner` in their recorded trace block, which means every one of them
reached l2 — so selfcheck and `test_replay_equivalence.py` between them
exercise none of l1's five exits. That is the gap this closes, and it is
the same gap that let the 2026-09-24 wiring defect through: `l4`'s data ref
named `l3`, so a call that a gate decided reached `l4` with `result=None`
and lost `filter`, `scanner` and its own `exit.stage` stamp. On the l1
paths the *verdict* came from the default row too, not from the gate.

Two properties per gate, and the second is the one that broke:

1. the call ends at the intended stage, without reaching a model
2. the verdict and the trace survive the trip through l4

Every network op is poisoned rather than stubbed. A gate that stops the
call cannot touch a model, so reaching one is itself the failure — and the
poison says which op it was instead of quietly dialling out. `kid` is
absent on purpose: it is the one l1 exit that needs an LLM verdict to
reach, so it cannot be driven this way.
"""
from __future__ import annotations

import asyncio

import pytest

from src.core.conversation import Conversation
from tests._engine import apply_case_selection, create_engine
from tests._engine import recorded_errors as _failed_case_ops
from tests._replay import install_stubs

CASE = "qc_flow.sentiment_agent"

#: Enough turns of plain collection talk that no keyword filter fires and no
#: gate other than the one under test has a reason to trip.
_NEUTRAL = [
    {"role": "agent", "content": "Dạ em chào anh, em gọi từ ngân hàng ạ", "start": 0, "end": 4},
    {"role": "customer", "content": "Vâng anh nghe", "start": 4, "end": 6},
    {"role": "agent", "content": "Dạ anh vui lòng thanh toán khoản vay giúp em ạ", "start": 6, "end": 11},
    {"role": "customer", "content": "Để tôi xem lại", "start": 11, "end": 14},
]


def _score(vads: list, call_code: str = "") -> tuple:
    """Score one synthetic call with every model poisoned.

    Returns `(verdict, state)`. The verdict is the case's own `result` read
    from state rather than the formatted row, because the row deliberately
    drops a non-violation's reason and `_trace_meta` is what the assertions
    are about. The state comes back too so a test can ask which ops failed.
    """
    engine, _ = create_engine(tracer_kind="none")
    apply_case_selection(engine, {"sentiment_agent"})
    install_stubs(engine.graph, {})  # stubs nothing → poisons every network op

    result = asyncio.run(engine.run(inputs={
        "conversation": Conversation(vads=vads),
        "call_code": call_code,
        "closed_by": "YES",
        "is_chinh_chu": False,
        "queue_id": 0,
    }))
    state = result.get("$state")
    return (state.get(CASE, "result") if state is not None else None), state


def _run(vads: list, call_code: str = "") -> dict:
    """Just the verdict, for the gate assertions."""
    return _score(vads, call_code)[0]


def _exit_stage(verdict: dict) -> "str | None":
    meta = (verdict or {}).get("_trace_meta") or {}
    return ((meta.get("exit") or {}).get("stage")) if isinstance(meta, dict) else None


class TestAGateEndsTheCallWithoutAModel:
    """Each gate stops the call, and the poison proves no model was asked."""

    @pytest.mark.parametrize("call_code", ["Ben_thu_3_DVKD", "Ben_thu_3_DVKD_AF"])
    def test_out_of_scope_call_codes_exit_immediately(self, call_code):
        verdict = _run(_NEUTRAL, call_code=call_code)
        assert verdict is not None, "the case produced no verdict at all"
        assert _exit_stage(verdict) == "scope"

    def test_a_call_with_no_agent_speech_exits_at_agent_silent(self):
        customer_only = [t for t in _NEUTRAL if t["role"] == "customer"]
        verdict = _run(customer_only)
        assert _exit_stage(verdict) == "agent_silent"

    def test_an_ivr_customer_exits_at_bot(self):
        ivr = [
            {"role": "agent", "content": "Dạ em chào anh", "start": 0, "end": 3},
            {"role": "customer",
             "content": "Thuê bao quý khách vừa gọi hiện ngoài vùng phủ sóng",
             "start": 3, "end": 8},
        ]
        verdict = _run(ivr)
        assert _exit_stage(verdict) == "bot"


class TestTheVerdictSurvivesLayerFour:
    """A gate's verdict must arrive intact, not be rebuilt from defaults.

    This is the assertion the 2026-09-24 defect failed. `l4` received
    `result=None` on every gated path and stamped a fresh `_trace_meta`, so
    the gate's own stage marker — the single thing that distinguishes
    "deliberately not judged" from "nobody judged it" — was gone by the time
    the row was written. `Result` was unaffected, which is why it took a
    live run to notice.
    """

    def test_the_gate_stamp_reaches_the_final_verdict(self):
        verdict = _run(_NEUTRAL, call_code="Ben_thu_3_DVKD")
        meta = verdict.get("_trace_meta") or {}
        assert "exit" in meta, (
            "l4 replaced the gate's _trace_meta instead of carrying it — the "
            f"block holds {sorted(meta)}. A call nothing judged is now "
            "indistinguishable from one a gate cleared."
        )

    def test_a_gated_call_is_not_a_violation(self):
        verdict = _run(_NEUTRAL, call_code="Ben_thu_3_DVKD")
        assert str(verdict.get("violation")).lower() in ("false", "none", ""), verdict


class TestTheHarnessCanFail:
    """A poisoned run that reaches a model must raise, not pass quietly."""

    def test_reaching_a_model_is_recorded_as_a_failed_op(self):
        """No gate trips on a neutral call, so it must hit a poisoned op.

        **The poison does not reach the caller.** operonx catches an op's
        exception, records it at `state[op, "error"]` and lets the graph carry
        on — so `engine.run()` returns a degraded verdict rather than raising,
        and `pytest.raises` here would never fire. That is the same swallowing
        that let six `NameError`s score ninety calls, and the `score` job's
        answer to it is to read the run's recorded errors and fail the call.
        This asserts that the error is recorded, which is what that reads.

        If poisoning ever stopped working, every test above would pass for the
        wrong reason — and quietly, over the network.
        """
        _, state = _score(_NEUTRAL)
        failed = _failed_case_ops(state)
        assert failed, (
            "a neutral call reached no poisoned op and recorded no error. "
            "Either a gate is now swallowing every call, or the poison is "
            "not being applied — in which case these tests are making live "
            "calls."
        )
        assert any("WouldHaveCalledOut" in err for err in failed.values()), (
            f"ops failed, but not from the poison: {failed}"
        )
