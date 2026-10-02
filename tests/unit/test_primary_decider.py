"""Unit tests for primary_decider — gate + apply logic.

Focus on the silent-fail path that caused the 425-call UAT explosion:
when `SECONDARY_DECIDER_LLM_RESOURCE_KEY` was unset, the primary
subgraph passed every filter-decider verdict through unchanged with no warning.
These tests lock the four skip conditions + the three apply outcomes,
plus the corpus-retrieval wiring added after the incident.
"""
from __future__ import annotations

import pytest

from src.cases._shared.spec import is_true
from src.cases.sentiment_agent.l4_verify import ops as sd
from src.cases.sentiment_agent.l4_verify.graph import l4_verify
from src.core import config
from src.core.conversation import Conversation


def _unwrap(op_wrapper):
    return getattr(op_wrapper, "__wrapped__", op_wrapper)


def _mk_vad(role: str, content: str, turn_idx: int, start: float = 0.0) -> dict:
    return {
        "role": role, "content": content, "start": start, "end": start + 1.0,
        "turn_idx": turn_idx,
    }


class _StubRetriever:
    """In-memory retriever stub — no BGE, no FAISS, no ONNX."""

    def __init__(self, positives: list[dict] | None = None,
                 carveouts: list[dict] | None = None):
        self._pos = positives or [
            {"parent_id": "pos_1", "text": "cút đi cho khuất mắt", "description": "chửi tục", "category": "C8"},
        ]
        self._neg = carveouts or [
            {"parent_id": "neg_1", "text": "anh giữ máy giúp em", "description": "hướng dẫn giao dịch", "category": "C8"},
        ]

    def search(self, query: str, k: int = 10) -> dict:
        return {"positives": list(self._pos), "carveouts": list(self._neg)}


# ---------------------------------------------------------------------------
# is_true — the one yes/no reading (src/cases/_shared/spec.py)
# ---------------------------------------------------------------------------


class TestIsTrue:
    def test_bool_true(self):
        assert is_true(True) is True

    def test_bool_false(self):
        assert is_true(False) is False

    @pytest.mark.parametrize("token", ["true", "True", "TRUE", " true "])
    def test_string_true(self, token):
        assert is_true(token) is True

    @pytest.mark.parametrize("token", ["false", "False", "", "no", "1"])
    def test_non_true_string_is_false(self, token):
        assert is_true(token) is False

    @pytest.mark.parametrize("value", [None, 1, {"x": 1}])
    def test_anything_else_is_false(self, value):
        assert is_true(value) is False


# ---------------------------------------------------------------------------
# build_primary_inputs_fn — gate (4 skip conditions) + retrieval wiring
# ---------------------------------------------------------------------------


class TestBuildPrimaryInputsGate:
    """All four skip paths return the placeholder inputs (needs_verify=False)."""

    def test_env_unset_skips(self, monkeypatch):
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "")
        raw = {"violation": True, "evidence_idxs": [1], "category": "C8"}
        out = _unwrap(sd.build_primary_inputs_fn)(raw_result=raw,
                                                     conversation=Conversation(vads=[]))
        assert out == {"needs_verify": False, "category": "", "ai_reason": "",
                       "evidence": "", "context": "", "retrieval_query": ""}
        assert out["needs_verify"] is False

    def test_non_violation_skips(self, monkeypatch):
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        raw = {"violation": False, "evidence_idxs": [1], "category": "C8"}
        out = _unwrap(sd.build_primary_inputs_fn)(raw_result=raw,
                                                     conversation=Conversation(vads=[]))
        assert out["needs_verify"] is False

    def test_missing_evidence_idxs_skips(self, monkeypatch):
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        raw = {"violation": True, "evidence_idxs": [], "category": "C8"}
        out = _unwrap(sd.build_primary_inputs_fn)(raw_result=raw,
                                                     conversation=Conversation(vads=[]))
        assert out["needs_verify"] is False

    def test_none_raw_result_skips(self, monkeypatch):
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        out = _unwrap(sd.build_primary_inputs_fn)(raw_result=None,
                                                     conversation=Conversation(vads=[]))
        assert out["needs_verify"] is False

    def test_string_violation_true_still_fires(self, monkeypatch):
        """LLM output can serialise violation as 'true' string — must not skip."""
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        raw = {"violation": "true", "evidence_idxs": [0], "category": "C8",
               "reason": "agent said 'cút đi'", "evidence": "[00:03]: cút đi"}
        vads = [_mk_vad("agent", "cút đi khỏi đây", turn_idx=0)]
        out = _unwrap(sd.build_primary_inputs_fn)(raw_result=raw,
                                                     conversation=Conversation(vads=vads))
        assert out["needs_verify"] is True


class TestBuildPrimaryInputsPayload:
    """When gate opens, retrieval must fire and pool strings must appear."""

    def _mk_raw(self, **overrides) -> dict:
        base = {
            "violation": True,
            "category": "C8",
            "reason": "agent nói 'cút đi cho khuất mắt' — thái độ cao",
            "evidence": "[00:03]: cút đi cho khuất mắt",
            "evidence_idxs": [0],
        }
        base.update(overrides)
        return base

    def _run(self, monkeypatch, raw=None, conv=None):
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        return _unwrap(sd.build_primary_inputs_fn)(
            raw_result=raw or self._mk_raw(),
            conversation=conv or Conversation(vads=[_mk_vad("agent", "cút đi khỏi đây", turn_idx=0)]),
        )

    def test_full_path_returns_payload(self, monkeypatch):
        out = self._run(monkeypatch)
        assert out["needs_verify"] is True
        assert out["category"] == "C8"
        assert "cút đi" in out["ai_reason"]
        assert out["evidence"]  # non-empty
        assert out["context"]   # non-empty
        # Gate emits the query; retrieval itself is a downstream graph node
        # so the ~98% of calls that are not violations never pay for an embed.
        assert "cút đi cho khuất mắt" in out["retrieval_query"]

    def test_query_is_the_quote_when_the_scanner_quoted_one(self, monkeypatch):
        """Corpus entries are short phrases; the quoted cue lands near them and
        a whole turn does not. Querying the turn instead (4ced162) dropped 18
        of the 24 entries l4 had cited on round 3, and F1 fell 0.856 -> 0.743."""
        raw = self._mk_raw(reason="agent nói 'khuất mắt' — thái độ cao",
                           evidence="[00:03]: cút đi cho khuất mắt")
        out = self._run(monkeypatch, raw=raw)
        assert out["retrieval_query"] == "khuất mắt"

    def test_with_no_quote_the_query_matches_l3_on_multi_turn_evidence(self, monkeypatch):
        """Without a quote l4 falls back to the evidence, built the way l3
        builds it. It used to strip only the first timestamp and keep the
        `<br/>` joins."""
        from src.cases.sentiment_agent.l3_decider import ops as l3
        raw = self._mk_raw(
            reason="thái độ không tốt",
            evidence="[00:47]: anh trao đổi nhỏ tiếng thôi<br/>[00:57]: anh có nghe không")
        l4_query = self._run(monkeypatch, raw=raw)["retrieval_query"]
        l3_query = _unwrap(l3.build_retrieval_query_fn)(llm_result=raw)["query"]
        assert l4_query == l3_query == "anh trao đổi nhỏ tiếng thôi anh có nghe không"

    def test_evidence_fallback_query_when_no_quotes(self, monkeypatch):
        """No quoted phrases → query = stripped evidence text."""
        out = self._run(monkeypatch, raw=self._mk_raw(reason="thái độ không tốt"))
        assert "cút đi cho khuất mắt" in out["retrieval_query"]
        assert "[00:03]" not in out["retrieval_query"]


    def test_context_window_around_evidence(self, monkeypatch):
        """Context must include turns within ±_CONTEXT_WINDOW of evidence_idx."""
        vads = [_mk_vad("agent" if i % 2 == 0 else "customer", f"turn {i}", turn_idx=i)
                for i in range(10)]
        conv = Conversation(vads=vads)
        raw = self._mk_raw(evidence_idxs=[5])
        out = self._run(monkeypatch, raw=raw, conv=conv)
        # ±3 around idx 5 → turns 2..8 must appear.
        for i in range(2, 9):
            assert f"turn {i}" in out["context"]
        # Far turns must NOT appear.
        assert "turn 0" not in out["context"]
        assert "turn 9" not in out["context"]

    def test_evidence_marker_on_target_turn(self, monkeypatch):
        """Target turn(s) must be marked with ' <<<' in context."""
        vads = [_mk_vad("agent", f"turn {i}", turn_idx=i) for i in range(6)]
        conv = Conversation(vads=vads)
        raw = self._mk_raw(evidence_idxs=[3])
        out = self._run(monkeypatch, raw=raw, conv=conv)
        # Only the target line ends with <<<.
        target_lines = [ln for ln in out["context"].splitlines() if ln.endswith("<<<")]
        assert len(target_lines) == 1
        assert "turn 3" in target_lines[0]

    def test_empty_turns_do_not_shift_the_window(self, monkeypatch):
        """A4: turn_idx skips empty turns, and the window was counted in list
        positions — with four empty turns before it, the cited turn fell
        outside its own window and lost its marker."""
        vads = [_mk_vad("agent", "earlier", turn_idx=0),
                *[{"role": "customer", "content": "", "start": 0, "end": 0}] * 4,
                _mk_vad("agent", "the cited turn", turn_idx=1)]
        out = self._run(monkeypatch, raw=self._mk_raw(evidence_idxs=[1]), conv=Conversation(vads=vads))
        marked = [ln for ln in out["context"].splitlines() if ln.endswith("<<<")]
        assert len(marked) == 1 and "the cited turn" in marked[0]


# ---------------------------------------------------------------------------
# apply_primary_fn — merge verdict + trace attachment
# ---------------------------------------------------------------------------


class TestApplyPrimary:
    """3 branches × trace correctness."""

    _BASE = {
        "violation": True, "category": "C8", "reason": "filter decider said violation",
        "evidence": "[00:03]: quote", "evidence_idxs": [0],
    }

    def test_skip_branch_passes_through_with_trace(self, monkeypatch):
        """primary_out is None → LLM never fired → pass-through + trace."""
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        out = _unwrap(sd.apply_primary_fn)(raw_result=dict(self._BASE), primary_out=None)
        result = out["result"]
        assert result["violation"] is True
        assert result["category"] == "C8"
        trace = result["_trace_meta"]["primary_decider"]
        assert trace["enabled"] is True
        assert trace["verdict"] is None
        assert "not invoked" in trace["reason"]

    def test_env_unset_skip_branch_marks_disabled(self, monkeypatch):
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "")
        out = _unwrap(sd.apply_primary_fn)(raw_result=dict(self._BASE), primary_out=None)
        trace = out["result"]["_trace_meta"]["primary_decider"]
        assert trace["enabled"] is False

    def test_agree_keeps_verdict(self, monkeypatch):
        """primary says violation=true → keep the filter decider's category + trace verdict=True."""
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        primary = {"violation": True, "reason": "confirmed",
                     "cited_positives": ["P1"], "cited_carveouts": []}
        out = _unwrap(sd.apply_primary_fn)(raw_result=dict(self._BASE), primary_out=primary)
        result = out["result"]
        assert result["violation"] is True   # unchanged
        assert result["category"] == "C8"    # unchanged
        assert "original_category" not in result  # no downgrade
        trace = result["_trace_meta"]["primary_decider"]
        assert trace["verdict"] is True
        assert trace["cited_positives"] == ["P1"]

    def test_disagree_downgrades(self, monkeypatch):
        """primary says violation=false → downgrade to category=none."""
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        primary = {"violation": False, "reason": "actually fine",
                     "cited_positives": [], "cited_carveouts": ["C1", "C3"]}
        out = _unwrap(sd.apply_primary_fn)(raw_result=dict(self._BASE), primary_out=primary)
        result = out["result"]
        assert result["violation"] == "false"
        assert result["category"] == "none"
        assert result["original_category"] == "C8"
        assert result["drop_reason"] == "primary_disagree"
        assert result["primary_reason"] == "actually fine"
        # Reason blanked (no longer accusatory).
        assert result["reason"] == ""
        # Evidence + evidence_idxs preserved for audit.
        assert result["evidence"] == "[00:03]: quote"
        assert result["evidence_idxs"] == [0]
        trace = result["_trace_meta"]["primary_decider"]
        assert trace["verdict"] is False
        assert trace["cited_carveouts"] == ["C1", "C3"]

    def test_string_false_downgrades(self, monkeypatch):
        """LLM can serialise violation as 'false' string — must downgrade."""
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        primary = {"violation": "false", "reason": "fine"}
        out = _unwrap(sd.apply_primary_fn)(raw_result=dict(self._BASE), primary_out=primary)
        assert out["result"]["category"] == "none"

    def test_malformed_primary_keeps_filter_verdict(self, monkeypatch):
        """Fail-safe: unclear primary output → keep the filter decider's verdict."""
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        primary = {"reason": "no violation field"}  # missing violation
        out = _unwrap(sd.apply_primary_fn)(raw_result=dict(self._BASE), primary_out=primary)
        result = out["result"]
        assert result["violation"] is True   # unchanged
        assert result["category"] == "C8"

    def test_trace_preserves_upstream_meta(self, monkeypatch):
        """primary_decider trace merges into existing _trace_meta without
        clobbering scanner/decider/etc set upstream."""
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        base = dict(self._BASE)
        base["_trace_meta"] = {
            "scanner": {"violation": True, "category_raw": "C8"},
            "decider": {"verdict": True, "reason": "filter decider"},
        }
        primary = {"violation": False, "reason": "downgrade"}
        out = _unwrap(sd.apply_primary_fn)(raw_result=base, primary_out=primary)
        meta = out["result"]["_trace_meta"]
        assert "scanner" in meta
        assert "decider" in meta
        assert "primary_decider" in meta

    def test_none_raw_result_passthrough(self, monkeypatch):
        """Defensive: raw_result=None must not crash."""
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        out = _unwrap(sd.apply_primary_fn)(raw_result=None, primary_out=None)
        assert "result" in out
        # trace attached to empty dict
        assert out["result"]["_trace_meta"]["primary_decider"]["verdict"] is None


# ---------------------------------------------------------------------------
# @graph symbol — build-time wiring works even when env unset
# ---------------------------------------------------------------------------


class TestPrimaryGraphSymbol:
    def test_graph_symbol_exists(self):
        assert l4_verify is not None
        assert callable(l4_verify)

    def test_graph_instantiates_when_env_unset(self, monkeypatch):
        """Graph must build with the primary decider switched off
        (`llm.primary_decider: null`) — the default model keeps the LLMOp's
        registration valid."""
        # The graph reads `config` when it is built; the ops read it per call.
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "")
        # Pin the fallback to a resource with a literal api_key. LLMOp.of
        # resolves the resource at build time, so inheriting whatever .env
        # happens to set (today `db-gemini-3-flash`, api_key `oauth2:databricks`)
        # makes this test fetch a token over the VPN. Same fallback branch,
        # no network.
        monkeypatch.setattr(config, "LLM_RESOURCE_KEY", "e4b-local")
        # l4 builds soften's LLM op too, and it resolves the same way.
        monkeypatch.setattr(config, "SOFTEN_LLM_RESOURCE_KEY", "e4b-local")
        from operonx.core import PARENT
        node = l4_verify(result=PARENT, conversation=PARENT)
        assert node is not None


class TestFormatPrimaryPools:
    """Retrieved items -> pool strings, and the empty-query guard."""

    def test_items_become_indexed_pools(self):
        stub = _StubRetriever()
        got = stub.search("x")
        out = _unwrap(sd.format_primary_pools_fn)(
            query="cút đi", positives=got["positives"], carveouts=got["carveouts"])
        assert "sample" in out["positives_indexed"]
        assert "sample" in out["carveouts_indexed"]

    def test_empty_query_yields_placeholder_not_arbitrary_hits(self):
        """An empty query has nothing to retrieve on. Whatever the embedder
        returns for "" would be arbitrary neighbours presented to the LLM as
        relevant corpus policy."""
        stub = _StubRetriever()
        got = stub.search("x")
        out = _unwrap(sd.format_primary_pools_fn)(
            query="  ", positives=got["positives"], carveouts=got["carveouts"])
        assert out["positives_indexed"] == "(không có mẫu nào được retrieve)"
        assert out["carveouts_indexed"] == "(không có mẫu nào được retrieve)"


# ---------------------------------------------------------------------------
# Logs carry no transcript — pod stdout is outside the redacting tracer
# ---------------------------------------------------------------------------


class TestPrimaryLogsNoTranscript:
    """The FIRE and DISAGREE lines used to print the evidence text and the
    model's reason, which quotes the transcript. Found in the 2026-09-25
    selfcheck log."""

    _SECRET = "câu nói bí mật của khách"

    def test_gate_log_has_no_evidence_text(self, monkeypatch, caplog):
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        raw = {"violation": "true", "evidence_idxs": [0], "category": "C8",
               "reason": f"agent said '{self._SECRET}'",
               "evidence": f"[00:03]: {self._SECRET}"}
        vads = [_mk_vad("agent", self._SECRET, turn_idx=0)]
        with caplog.at_level("DEBUG"):
            out = _unwrap(sd.build_primary_inputs_fn)(
                raw_result=raw, conversation=Conversation(vads=vads))
        assert out["needs_verify"] is True
        assert "[primary] FIRE" in caplog.text
        assert self._SECRET not in caplog.text

    @pytest.mark.parametrize("verdict", [True, False])
    def test_apply_log_has_no_reason_text(self, monkeypatch, caplog, verdict):
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        base = {"violation": True, "category": "C8", "reason": self._SECRET,
                "evidence": f"[00:03]: {self._SECRET}", "evidence_idxs": [0]}
        primary = {"violation": verdict, "reason": f"khớp '{self._SECRET}'",
                   "cited_positives": ["P1"], "cited_carveouts": []}
        with caplog.at_level("DEBUG"):
            _unwrap(sd.apply_primary_fn)(raw_result=base, primary_out=primary)
        assert "[primary]" in caplog.text
        assert self._SECRET not in caplog.text


class TestSoftenSeesTheEvidence:
    """A3: soften read `evidence_text`, a key nothing writes, so every reason
    was rewritten with an empty evidence slot."""

    RAW = {"violation": "true", "category": "C8", "reason": "x",
           "evidence": "[00:03]: cút đi", "evidence_idxs": [0]}

    def test_soften_gets_the_cited_turn(self):
        assert _unwrap(sd.build_soften_inputs_fn)(raw_result=self.RAW)["evidence_text"] == "cút đi"

    def test_soften_reads_what_the_primary_reads(self, monkeypatch):
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "claude-4-sonnet")
        conv = Conversation(vads=[_mk_vad("agent", "cút đi", turn_idx=0)])
        primary = _unwrap(sd.build_primary_inputs_fn)(raw_result=self.RAW, conversation=conv)
        soften = _unwrap(sd.build_soften_inputs_fn)(raw_result=self.RAW)
        assert primary["evidence"] == soften["evidence_text"] == "cút đi"


class TestAFailedSoftenKeepsTheVerdict:
    """Soften rewords a reason and never decides. Its timeout used to fail the
    whole call — three of 235 on aug2127, their verdicts lost to a rewording."""

    BASE = {"violation": True, "category": "C8", "reason": "ĐTV quát khách"}

    def test_the_reason_stays_as_written_and_the_trace_says_why(self):
        out = _unwrap(sd.apply_soften_fn)(raw_result=dict(self.BASE), soften_out=None,
                                          soften_error="TimeoutError: exceeded 90s\ntraceback…")["result"]
        assert out["reason"] == "ĐTV quát khách" and out["violation"] is True
        assert out["_trace_meta"]["soften"]["enabled"] is False
        assert out["_trace_meta"]["soften"]["error"] == "TimeoutError: exceeded 90s"

    def test_a_soften_that_worked_is_unchanged(self):
        out = _unwrap(sd.apply_soften_fn)(raw_result=dict(self.BASE), soften_out={"reason": "ĐTV nói to"},
                                          soften_error=None)["result"]
        assert out["reason"] == "ĐTV nói to" and "error" not in out["_trace_meta"]["soften"]
