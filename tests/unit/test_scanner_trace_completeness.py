"""A cleared call must say so, and a skipped call must say why.

`traces.scanner` used to be written only on the three paths where the
scanner flagged something. That made `scanner.violation` a boolean that was
never false, and made its absence mean three different things at once:

    scanner ran and cleared the call
    scanner never ran (a gate ended the graph first)
    the scanner op failed

All three scored "Tích cực" with an empty Reasoning and no trace, so a
reviewer asking "why was this not flagged?" — or an engineer asking "did
this call actually get judged?" — could not tell them apart. It cost a real
misdiagnosis: ten clean calls in the 2026-08-11..13 QC batch were read as
lost to an LLM timeout and queued for a rerun they did not need.

These tests pin both halves of the repair: the clean path records the
verdict, and each gate names itself.

No LLM, no network — both are plain dict assembly.
"""

import pytest

from src.cases._shared.ops import exit_fn
from src.cases.sentiment_agent._format import _build_traces
from src.cases.sentiment_agent.l2_scanner.ops import skip_matcher_fn


def unwrap(op):
    """Reach the plain function behind an @op."""
    return getattr(op, "__wrapped__", op)


FILTER_META = {"should_scan": True, "reason": "filter_disabled", "kw_hit": False,
               "llm_verdict": None, "applied": True}


# ── the clean path records the scanner's verdict ──────────────────────


def test_cleared_call_records_violation_false():
    out = unwrap(skip_matcher_fn)(
        llm_result={"violation": False, "category": "none", "reason": "",
                    "evidence": "", "evidence_idxs": []},
        filter_meta=FILTER_META,
    )["result"]
    scanner = out["_trace_meta"]["scanner"]
    # The point of the fix: present AND false, not absent.
    assert scanner["violation"] is False
    assert scanner["category_raw"] == "none"


def test_cleared_call_keeps_the_filter_block():
    """The filter verdict was the one thing this path already recorded —
    adding the scanner block must not displace it."""
    out = unwrap(skip_matcher_fn)(
        llm_result={"violation": False, "category": "none"},
        filter_meta=FILTER_META,
    )["result"]
    assert out["_trace_meta"]["filter"] == FILTER_META
    assert set(out["_trace_meta"]) == {"filter", "scanner", "exit"}


@pytest.mark.parametrize("llm_result", [None, "not a dict", 42])
def test_malformed_scanner_result_is_passed_through(llm_result):
    """Nothing to snapshot, and inventing `violation: false` here would
    report a clean verdict the scanner never gave."""
    assert unwrap(skip_matcher_fn)(llm_result=llm_result,
                                   filter_meta=FILTER_META)["result"] == llm_result


def test_no_filter_meta_still_records_the_verdict():
    """Without `filter_meta` this used to be a no-op, which lost the lot.

    The op early-returned, so a cleared call got no scanner block and no
    exit stamp — the same empty row a crashed scanner produces. In
    practice `filter_meta` is always supplied, so the branch was
    defensive rather than used; the cost of it firing was silence exactly
    where the trace matters most.
    """
    r = {"violation": False, "category": "none"}
    out = unwrap(skip_matcher_fn)(llm_result=r, filter_meta=None)["result"]
    assert out["violation"] is False, "the verdict itself is untouched"
    assert "filter" not in out["_trace_meta"], "nothing to record, nothing recorded"
    assert out["_trace_meta"]["scanner"]["violation"] is False
    assert out["_trace_meta"]["exit"]["stage"] == "no_violation"


# ── a gate that ends the graph names itself ───────────────────────────


@pytest.mark.parametrize("stage, category", [
    ("scope", None), ("agent_silent", "im_lang"), ("filter", None),
    ("bot", "khach_la_bot"), ("kid", "khach_la_tre_em"),
])
def test_exit_records_which_gate_fired(stage, category):
    out = unwrap(exit_fn)(reason="r", category=category, exit_stage=stage)["result"]
    assert out["_trace_meta"]["exit"]["stage"] == stage
    assert out["_trace_meta"]["exit"]["category"] == (category or "")


def test_exit_stage_is_opt_in():
    """`exit_fn` is shared by all seven cases. Cases that do not pass
    `exit_stage` must keep emitting exactly what they emitted before —
    including no `_trace_meta` at all."""
    assert "_trace_meta" not in unwrap(exit_fn)(reason="r")["result"]


def test_exit_stage_coexists_with_filter_meta():
    out = unwrap(exit_fn)(reason="r", category="khach_la_tre_em",
                          filter_meta=FILTER_META, exit_stage="kid")["result"]
    assert out["_trace_meta"]["filter"] == FILTER_META
    assert out["_trace_meta"]["exit"]["stage"] == "kid"


# ── the blocks survive into the public output ─────────────────────────
#
# `_build_traces` returns None when INCLUDE_TRACES is off, and
# `test_config_env` sets that env var process-wide — so pin the flag on the
# module rather than inheriting whatever ran first.


@pytest.fixture
def traces_on(monkeypatch):
    monkeypatch.setattr("src.core.config.INCLUDE_TRACES", True)




def test_exit_block_is_emitted_and_ordered_before_scanner(traces_on):
    """Stage order is load-bearing for the UI, and `exit` is chronologically
    a pre-scanner event."""
    traces = _build_traces({"_trace_meta": {"scanner": {"violation": False},
                                            "exit": {"stage": "kid"},
                                            "filter": FILTER_META}})
    assert list(traces) == ["filter", "exit", "scanner"]


def test_the_three_silent_states_are_now_distinguishable(traces_on):
    """The whole point, stated as one assertion.

    A cleared call, a gated call, and a call whose scanner produced nothing
    must no longer look identical.
    """
    cleared = _build_traces({"_trace_meta": unwrap(skip_matcher_fn)(
        llm_result={"violation": False, "category": "none"},
        filter_meta=FILTER_META)["result"]["_trace_meta"]})
    gated = _build_traces({"_trace_meta": unwrap(exit_fn)(
        reason="r", category="khach_la_tre_em", filter_meta=FILTER_META,
        exit_stage="kid")["result"]["_trace_meta"]})
    lost = _build_traces({"_trace_meta": {"filter": FILTER_META}})

    assert cleared["scanner"]["violation"] is False   # judged, and clean
    assert gated["exit"]["stage"] == "kid"            # deliberately not judged
    assert "scanner" not in lost and "exit" not in lost   # unexplained
    assert cleared != gated != lost
