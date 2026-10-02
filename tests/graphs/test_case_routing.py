"""Routing of the four HVC cases no other test drives, offline.

Every LLM op is poisoned, then the ones a path needs are given a canned
answer, so a path that would dial out fails loudly instead. Each test pins
which exit a call reaches — the thing a graph rewiring could change without
touching a single verdict string.

The parse tests pin phase 3's rule: a model reply that fails to parse
sets its fields to `None` and says why in `error`; the `parsed` check after
every model call turns that into a failed call — recorded as `{"error"}` —
never a verdict (`None` reads as "no", a clean call, or a −100 one).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from operonx.core import PARENT, Operon

from src.cases.card_number.graph import verify_card_number
from src.cases.disclosure.graph import verify_disclosure
from src.cases.hangup.graph import verify_hangup
from src.cases.phone_source.graph import verify_phone_source
from src.cases.raba.graph import verify_raba
from src.cases.sentiment_agent.l1_gates.prefilter.ops import prepare_filter_chunks_fn
from src.core.conversation import Conversation
from tests._engine import recorded_errors
from tests._replay import answer_ops

TALK = Conversation(vads=[
    {"role": "agent", "content": "Chào anh, em gọi từ công ty tài chính", "start": 0, "end": 3},
    {"role": "customer", "content": "Vâng tôi nghe đây", "start": 3, "end": 5},
    {"role": "agent", "content": "Khoản vay của anh đã đến hạn thanh toán", "start": 5, "end": 9},
    {"role": "customer", "content": "Mai tôi trả nhé", "start": 9, "end": 11},
])
CARD_READ = Conversation(vads=[
    {"role": "agent", "content": "số thẻ của anh là một hai ba bốn sáu bảy tám chín "
                                 "không một hai ba bốn sáu bảy tám", "start": 0, "end": 9},
    {"role": "customer", "content": "vâng", "start": 9, "end": 10},
])


def _run(graph_fn, answers: Dict[str, Any], **inputs) -> tuple:
    """`(result, errors, seen)` — *answers* maps an op's name to its canned
    output; *seen* records the inputs each answered op was called with."""
    g = graph_fn(**{k: PARENT for k in inputs}, name="case")
    seen = answer_ops(g, answers)
    out = asyncio.run(Operon(g).run(inputs=inputs))
    return out.get("result"), recorded_errors(out.get("$state")), seen


# ── raba ────────────────────────────────────────────────────────────────


def test_raba_skips_its_queue():
    result, _, _ = _run(verify_raba, {}, conversation=TALK, call_code="Hua_tra", queue_id=583)
    assert result["violation"] is False and "queue_id=583" in result["reason"]


def test_raba_refuses_another_call_code():
    result, _, _ = _run(verify_raba, {}, conversation=TALK, call_code="Ngat_may", queue_id=0)
    assert result == {"violation": False, "reason": "call_code không hợp lệ"}


def test_raba_no_reminder_is_a_violation():
    result, _, _ = _run(verify_raba, {"classifier": {"call_type": "NO_REMINDER"}},
                        conversation=TALK, call_code="Hua_tra", queue_id=0)
    assert result["violation"] is True and "nhắc nợ" in result["reason"]


def test_raba_third_party_who_is_the_customer_is_a_violation():
    result, _, _ = _run(verify_raba, {"identity": {"identity": "CUSTOMER", "reasoning": "chính chủ"}},
                        conversation=TALK, call_code="Ben_thu_3_hua_tra", queue_id=0)
    assert result == {"violation": True, "reason": "chính chủ"}


def test_raba_a_detector_that_fails_to_parse_fails_the_call():
    """A2: `money` failing to parse left `has_money_mention` None, which
    `_decide` read as missing money — a −100 violation from a model hiccup.
    Now the call fails before any verdict is reached."""
    answers = {
        "classifier": {"call_type": "PRE_DUE_REMINDER"},
        "money": {"has_money_mention": None, "mentions": None, "error": "Expecting value: line 1 column 1"},
        "time": {"has_time_mention": True, "has_actionable_time_mention": True, "mentions": {}},
        "agreement": {"is_opposed": False, "reasoning": "hứa trả"},
        "response": {"reason": {"text": "thiếu số tiền"}},
    }
    result, errors, seen = _run(verify_raba, answers, conversation=TALK, call_code="Hua_tra", queue_id=0)
    assert any(k.endswith("money_parsed") and "did not parse" in v for k, v in errors.items()), errors
    assert "response" not in seen and result is None


# ── hangup ──────────────────────────────────────────────────────────────


def test_hangup_ignores_another_call_code():
    result, _, _ = _run(verify_hangup, {}, conversation=TALK, call_code="Hua_tra", closed_by="AGENT")
    assert result == {"violation": False, "reason": "Case này không phải là call_code Ngat_may"}


def test_hangup_the_customer_hung_up():
    result, _, _ = _run(verify_hangup, {}, conversation=TALK, call_code="Ngat_may", closed_by="CUSTOMER")
    assert result == {"violation": False, "reason": "Đây là trường hợp khách hàng ngắt máy"}


# ── disclosure ──────────────────────────────────────────────────────────


def test_disclosure_skips_the_account_holders_own_phone():
    result, _, _ = _run(verify_disclosure, {}, conversation=TALK, is_chinh_chu=True)
    assert result["violation"] is False and "chính chủ" in result["reason"]


def test_disclosure_nothing_disclosed():
    result, _, _ = _run(verify_disclosure, {"disclosure": {"disclosed": False, "reason": "không tiết lộ",
                                                           "evidence": ""}},
                        conversation=TALK, is_chinh_chu=False)
    assert result == {"violation": False, "reason": "không tiết lộ"}


# ── phone_source ────────────────────────────────────────────────────────


def test_phone_source_skips_bt3_dvkd():
    result, _, _ = _run(verify_phone_source, {}, conversation=TALK, call_code="Ben_thu_3_DVKD")
    assert result["violation"] is False and "Ben_thu_3_DVKD" in result["reason"]


def test_phone_source_no_keyword_no_llm():
    result, _, _ = _run(verify_phone_source, {}, conversation=TALK, call_code="Hua_tra")
    assert result == {"violation": False, "reason": "Không phát hiện từ khóa nghi ngờ"}


# ── card_number ─────────────────────────────────────────────────────────


def test_card_number_a_reply_that_fails_to_parse_fails_the_call():
    """A1's shape: the parse-failure None used to be read as no violation."""
    result, errors, _ = _run(verify_card_number, {"verify": {"result": None, "error": "no <result> tag"}},
                             conversation=CARD_READ)
    assert any(k.endswith("verify_parsed") for k in errors), errors
    assert result is None


def test_disclosure_an_implicit_check_that_fails_to_parse_is_not_a_violation():
    """A2: `implicit` failing to parse fell to `violation_raw` — −100."""
    answers = {
        "disclosure": {"disclosed": True, "reason": "có nhắc khoản vay", "evidence": "[00:05]"},
        "direct": {"verified": False, "reason": "không trực tiếp"},
        "implicit": {"verified": None, "reason": None, "error": "no <verified> tag"},
    }
    result, errors, _ = _run(verify_disclosure, answers, conversation=TALK, is_chinh_chu=False)
    assert any(k.endswith("implicit_parsed") for k in errors), errors
    assert result is None


def test_the_check_passes_a_reply_that_parsed_and_names_one_that_did_not():
    from src.cases._shared.ops import parsed

    assert parsed.__wrapped__(error=None) == {"ok": True}
    with pytest.raises(ValueError, match="did not parse: bad JSON$"):
        parsed.__wrapped__(error="bad JSON\n  line 2 of the parser's message")


# ── sentiment_agent pre-filter ──────────────────────────────────────────


def test_prefilter_chunk_prep_reports_its_count():
    """Regression: the op returned its helper's dict, which never carried
    `n_chunks`, so the graph's `n_chunks == 0` branch could never fire."""
    assert prepare_filter_chunks_fn(conversation=Conversation(vads=[]))()["n_chunks"] == 0
    assert prepare_filter_chunks_fn(conversation=TALK)()["n_chunks"] >= 1
