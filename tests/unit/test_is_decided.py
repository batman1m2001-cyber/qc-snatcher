"""`is_decided` — has an upstream gate already ended this call?

The one question the layer split needs answered between stages. Every
terminal stamps `_trace_meta["exit"]` on its way out, so the answer is
already written down; this reads it rather than inventing a field.

The case it has to get right is the empty one. A result that is `None`
because something upstream failed is **not** a decided call, and saying
otherwise would route it straight past the stages that would have caught
the loss — a transport failure arriving as a clean verdict, which is
exactly what happened on 2026-09-23.
"""
from __future__ import annotations

import pytest

from src.cases._shared.ops import exit_fn, is_decided

DECIDE = is_decided(result={}).core
EXIT = exit_fn().core


class TestDecided:
    def test_a_stamped_exit_is_decided(self):
        assert DECIDE(result={"_trace_meta": {"exit": {"stage": "kid"}}}) is True

    @pytest.mark.parametrize("stage", [
        "scope", "agent_silent", "filter", "bot", "kid", "halu", "no_violation",
    ])
    def test_every_terminal_stage_counts(self, stage):
        """Each is a real exit_stage in the graph; none may be missed."""
        assert DECIDE(result={"_trace_meta": {"exit": {"stage": stage}}}) is True

    def test_a_real_exit_fn_result_is_decided(self):
        """Against the op that actually stamps it, not a hand-made dict."""
        produced = EXIT(reason="skip", exit_stage="bot")
        assert DECIDE(result=produced["result"]) is True


class TestNotDecided:
    def test_a_verdict_still_in_flight_is_not(self):
        assert DECIDE(result={"violation": True, "category": "C3"}) is False

    def test_other_trace_blocks_do_not_count(self):
        """`scanner` and `filter` are recorded mid-flight, not at an exit."""
        result = {"_trace_meta": {"scanner": {"violation": True}, "filter": {}}}
        assert DECIDE(result=result) is False

    def test_an_empty_exit_block_is_not_a_decision(self):
        assert DECIDE(result={"_trace_meta": {"exit": {}}}) is False

    def test_an_exit_fn_without_a_stage_does_not_count(self):
        """`exit_stage` is opt-in — the cases sharing `exit_fn` do not pass it."""
        produced = EXIT(reason="no stage given")
        assert DECIDE(result=produced["result"]) is False


class TestAbsentIsNotDecided:
    """The distinction the 2026-09-23 defects turned on.

    A lost result must not be read as a finished one. If it were, the call
    would skip every remaining stage — including the ones whose job is to
    notice that something went missing — and arrive at the output as a
    clean verdict with nothing to show why.
    """

    @pytest.mark.parametrize("result", [None, "", [], 0, "not a dict", 42])
    def test_nothing_is_not_a_decision(self, result):
        assert DECIDE(result=result) is False

    def test_a_null_trace_meta_is_not_a_decision(self):
        assert DECIDE(result={"_trace_meta": None}) is False

    def test_it_returns_a_real_bool(self):
        """A branch tests this directly; a truthy dict would route the same
        way by accident and stop being checkable."""
        out = DECIDE(result={"_trace_meta": {"exit": {"stage": "kid"}}})
        assert out is True or out is False
