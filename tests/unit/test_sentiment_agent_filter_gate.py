"""Unit tests for v4 sentiment_agent filter — gate + dispatch + shape.

Focus on the surfaces where drift has bitten (or would bite silently):

  * `apply_filter_gate_fn` — 4 explicit kwargs threaded from the subgraph.
    Historical bug: when passed the subgraph reference bare instead of
    subscripted, all fields collapsed to defaults and every call fell
    through as "pass, filter disabled". This test locks the contract:
    real values must propagate into `filter_meta`, and the apply/shadow
    switch must flip gate correctly.

  * `dispatch_fn` — single-shot routing decision. Locks the 4 route
    tokens against the (llm_on, kw_on, kw_hit) truth table.

  * `{disabled, kw_hit, kw_clean}_pass_fn` + `aggregate_llm_result_fn`
    — the 4-field subgraph contract that downstream `apply_filter_gate_fn`
    expects. Shape drift here would silently break `filter_meta`.
"""
from __future__ import annotations

from src.cases.sentiment_agent.l1_gates.prefilter import ops as flt
from src.cases.sentiment_agent.l1_gates.prefilter.graph import filter_sentiment_agent
from src.core.config import SENTIMENT_FILTER_APPLY_ENV
from src.core.config import SENTIMENT_FILTER_KEYWORD_ENABLE_ENV as KEYWORD_ENABLE_ENV
from src.core import config
from src.core.conversation import Conversation


def _mk_vad(role: str, content: str, start: float = 0.0) -> dict:
    return {"role": role, "content": content, "start": start, "end": start + 1.0}


def _unwrap(op_wrapper):
    return getattr(op_wrapper, "__wrapped__", op_wrapper)


# ---------------------------------------------------------------------------
# apply_filter_gate_fn — the historical-bug surface
# ---------------------------------------------------------------------------


class TestApplyFilterGate:
    """Truth table: (apply_env, should_scan) → gate + meta faithful."""

    def _run(self, monkeypatch, *, apply: bool, **kwargs):
        monkeypatch.setenv(SENTIMENT_FILTER_APPLY_ENV, "true" if apply else "false")
        return _unwrap(flt.apply_filter_gate_fn)(**kwargs)

    def test_apply_true_should_scan_false_blocks(self, monkeypatch):
        out = self._run(monkeypatch, apply=True, should_scan=False,
                        reason=flt.REASON_CLEAN, kw_hit=False, llm_verdict=False)
        assert out["gate"] == "block"
        assert out["filter_meta"]["should_scan"] is False
        assert out["filter_meta"]["reason"] == flt.REASON_CLEAN
        assert out["filter_meta"]["kw_hit"] is False
        assert out["filter_meta"]["llm_verdict"] is False
        assert out["filter_meta"]["applied"] is True

    def test_apply_true_should_scan_true_passes(self, monkeypatch):
        out = self._run(monkeypatch, apply=True, should_scan=True,
                        reason=flt.REASON_FLAGGED, kw_hit=False, llm_verdict=True)
        assert out["gate"] == "pass"
        assert out["filter_meta"]["applied"] is True
        assert out["filter_meta"]["should_scan"] is True

    def test_shadow_mode_never_blocks(self, monkeypatch):
        """apply=false → gate=pass even when should_scan=false."""
        out = self._run(monkeypatch, apply=False, should_scan=False,
                        reason=flt.REASON_CLEAN, kw_hit=False, llm_verdict=False)
        assert out["gate"] == "pass"
        assert out["filter_meta"]["applied"] is False
        assert out["filter_meta"]["should_scan"] is False
        # Verdict still reflected in meta for shadow eval.
        assert out["filter_meta"]["reason"] == flt.REASON_CLEAN

    def test_kw_hit_propagates(self, monkeypatch):
        """Regression: kw_hit must reach filter_meta unchanged."""
        out = self._run(monkeypatch, apply=True, should_scan=True,
                        reason=flt.REASON_KW_HIT, kw_hit=True, llm_verdict=None)
        assert out["filter_meta"]["kw_hit"] is True
        assert out["filter_meta"]["llm_verdict"] is None

    def test_llm_verdict_none_preserved(self, monkeypatch):
        """LLM verdict None (unparseable) must NOT be coerced to False."""
        out = self._run(monkeypatch, apply=True, should_scan=True,
                        reason=flt.REASON_PARSE_ERROR, kw_hit=False, llm_verdict=None)
        assert out["filter_meta"]["llm_verdict"] is None

    def test_llm_verdict_true_preserved(self, monkeypatch):
        out = self._run(monkeypatch, apply=True, should_scan=True,
                        reason=flt.REASON_FLAGGED, kw_hit=False, llm_verdict=True)
        assert out["filter_meta"]["llm_verdict"] is True

    def test_all_defaults_produces_pass(self, monkeypatch):
        """No kwargs = every field default. Verifies the bug scenario
        (subgraph output not subscripted → all defaults) is at least SAFE
        for the main flow (no block), even though meta shows filter_disabled
        semantics. Real fix is verified via kw_hit/llm_verdict propagation
        tests above."""
        monkeypatch.setenv(SENTIMENT_FILTER_APPLY_ENV, "true")
        out = _unwrap(flt.apply_filter_gate_fn)()
        assert out["gate"] == "pass"
        assert out["filter_meta"] == {
            "should_scan": True,
            "reason": "",
            "kw_hit": False,
            "llm_verdict": None,
            "applied": True,
        }

    def test_should_scan_non_bool_coerced_safely(self, monkeypatch):
        """Malformed upstream output (non-bool should_scan) must default to
        scan=True — fail-open, prefer wasted scan over silent drop."""
        monkeypatch.setenv(SENTIMENT_FILTER_APPLY_ENV, "true")
        out = _unwrap(flt.apply_filter_gate_fn)(should_scan="yes")
        assert out["filter_meta"]["should_scan"] is True
        assert out["gate"] == "pass"

    def test_apply_env_read_fresh_per_call(self, monkeypatch):
        """SENTIMENT_FILTER_APPLY must be read fresh each call — flip env
        mid-run and gate must reflect the new value."""
        monkeypatch.setenv(SENTIMENT_FILTER_APPLY_ENV, "true")
        out1 = _unwrap(flt.apply_filter_gate_fn)(should_scan=False, reason="x")
        assert out1["gate"] == "block"

        monkeypatch.setenv(SENTIMENT_FILTER_APPLY_ENV, "false")
        out2 = _unwrap(flt.apply_filter_gate_fn)(should_scan=False, reason="x")
        assert out2["gate"] == "pass"


# ---------------------------------------------------------------------------
# dispatch_fn — routing truth table
# ---------------------------------------------------------------------------


class TestDispatchRouting:
    """(llm_on, kw_on, kw_hit) → route token. Locks the 4 branches."""

    def _dispatch(self, monkeypatch, *, llm_on: bool, kw_on: bool, conv: Conversation):
        # The LLM pre-filter is routed by models.yaml, read through config.
        monkeypatch.setattr(config, "PREFILTER_LLM_RESOURCE_KEY", "e4b-local" if llm_on else "")
        if kw_on:
            monkeypatch.setenv(KEYWORD_ENABLE_ENV, "true")
        else:
            monkeypatch.delenv(KEYWORD_ENABLE_ENV, raising=False)
        return _unwrap(flt.dispatch_fn)(conversation=conv)

    def test_both_disabled_routes_disabled_pass(self, monkeypatch):
        conv = Conversation(vads=[_mk_vad("agent", "xin chào")])
        out = self._dispatch(monkeypatch, llm_on=False, kw_on=False, conv=conv)
        assert out == {"route": flt.ROUTE_DISABLED, "kw_hit": False}

    def test_kw_on_with_hit_routes_kw_hit(self, monkeypatch):
        # "cút đi" is in keyword_filter.yaml
        conv = Conversation(vads=[_mk_vad("agent", "cút đi khỏi đây")])
        out = self._dispatch(monkeypatch, llm_on=True, kw_on=True, conv=conv)
        assert out == {"route": flt.ROUTE_KW_HIT, "kw_hit": True}

    def test_kw_on_miss_llm_on_routes_llm_scan(self, monkeypatch):
        conv = Conversation(vads=[_mk_vad("agent", "xin chào anh chị")])
        out = self._dispatch(monkeypatch, llm_on=True, kw_on=True, conv=conv)
        assert out == {"route": flt.ROUTE_LLM_SCAN, "kw_hit": False}

    def test_llm_only_routes_llm_scan(self, monkeypatch):
        conv = Conversation(vads=[_mk_vad("agent", "xin chào")])
        out = self._dispatch(monkeypatch, llm_on=True, kw_on=False, conv=conv)
        assert out == {"route": flt.ROUTE_LLM_SCAN, "kw_hit": False}

    def test_kw_only_miss_routes_kw_clean(self, monkeypatch):
        conv = Conversation(vads=[_mk_vad("agent", "xin chào anh chị")])
        out = self._dispatch(monkeypatch, llm_on=False, kw_on=True, conv=conv)
        assert out == {"route": flt.ROUTE_KW_CLEAN, "kw_hit": False}

    def test_kw_only_hit_routes_kw_hit(self, monkeypatch):
        conv = Conversation(vads=[_mk_vad("agent", "cút đi")])
        out = self._dispatch(monkeypatch, llm_on=False, kw_on=True, conv=conv)
        assert out == {"route": flt.ROUTE_KW_HIT, "kw_hit": True}


# ---------------------------------------------------------------------------
# Subgraph exit shape — 4-field contract downstream depends on
# ---------------------------------------------------------------------------


class TestPassBranchesShape:
    """All three synchronous pass branches must emit the 4-field contract."""

    _EXPECTED_KEYS = {"should_scan", "reason", "kw_hit", "llm_verdict"}

    def test_disabled_pass_shape(self):
        out = _unwrap(flt.disabled_pass_fn)()
        assert set(out.keys()) == self._EXPECTED_KEYS
        assert out["should_scan"] is True
        assert out["reason"] == flt.REASON_DISABLED
        assert out["kw_hit"] is False
        assert out["llm_verdict"] is None

    def test_kw_hit_pass_shape(self):
        out = _unwrap(flt.kw_hit_pass_fn)()
        assert set(out.keys()) == self._EXPECTED_KEYS
        assert out["should_scan"] is True
        assert out["reason"] == flt.REASON_KW_HIT
        assert out["kw_hit"] is True

    def test_kw_clean_pass_shape(self):
        out = _unwrap(flt.kw_clean_pass_fn)()
        assert set(out.keys()) == self._EXPECTED_KEYS
        assert out["should_scan"] is False
        assert out["reason"] == flt.REASON_KW_MISS_CLEAN
        assert out["kw_hit"] is False


class TestAggregateLlmResult:
    """LLM branch's aggregator must emit the same 4-field contract."""

    _EXPECTED_KEYS = {"should_scan", "reason", "kw_hit", "llm_verdict"}

    def test_empty_chunks_shape(self):
        out = _unwrap(flt.aggregate_llm_result_fn)(chunk_raws=[])
        assert set(out.keys()) == self._EXPECTED_KEYS
        assert out == {
            "should_scan": False,
            "reason": flt.REASON_NO_CHUNKS,
            "kw_hit": False,
            "llm_verdict": None,
        }

    def test_none_chunks_shape(self):
        out = _unwrap(flt.aggregate_llm_result_fn)(chunk_raws=None)
        assert out["reason"] == flt.REASON_NO_CHUNKS
        assert out["should_scan"] is False

    def test_all_parse_error_fails_open(self):
        out = _unwrap(flt.aggregate_llm_result_fn)(
            chunk_raws=["<ERROR>", None, "not json"]
        )
        assert out["should_scan"] is True
        assert out["reason"] == flt.REASON_PARSE_ERROR
        assert out["llm_verdict"] is None

    def test_any_violation_flagged(self):
        out = _unwrap(flt.aggregate_llm_result_fn)(
            chunk_raws=[{"violation": False}, {"violation": True}]
        )
        assert out["should_scan"] is True
        assert out["reason"] == flt.REASON_FLAGGED
        assert out["llm_verdict"] is True

    def test_all_clean(self):
        out = _unwrap(flt.aggregate_llm_result_fn)(
            chunk_raws=[{"violation": False}, {"violation": False}]
        )
        assert out["should_scan"] is False
        assert out["reason"] == flt.REASON_CLEAN
        assert out["llm_verdict"] is False


# ---------------------------------------------------------------------------
# _aggregate_llm_verdict — pure OR logic
# ---------------------------------------------------------------------------


class TestAggregateLlmVerdict:
    def test_empty(self):
        assert flt._aggregate_llm_verdict([]) is None
        assert flt._aggregate_llm_verdict(None) is None

    def test_all_unparseable_returns_none(self):
        assert flt._aggregate_llm_verdict(["<ERROR>", None]) is None

    def test_any_true(self):
        assert flt._aggregate_llm_verdict(
            [{"violation": False}, {"violation": True}, {"violation": False}]
        ) is True

    def test_all_false(self):
        assert flt._aggregate_llm_verdict(
            [{"violation": False}, {"violation": False}]
        ) is False

    def test_mixed_error_and_false_still_false(self):
        assert flt._aggregate_llm_verdict(
            ["<ERROR>", {"violation": False}]
        ) is False


# ---------------------------------------------------------------------------
# @graph symbol — build-time wiring works
# ---------------------------------------------------------------------------


class TestFilterGraphSymbol:
    def test_graph_symbol_exists(self):
        assert filter_sentiment_agent is not None
        assert callable(filter_sentiment_agent)

    def test_graph_instantiates(self):
        from operonx.core import PARENT
        node = filter_sentiment_agent(conversation=PARENT)
        assert node is not None
