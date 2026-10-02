"""Case: Fraud detection - RABA (customer or third party promises to pay).

    verify_raba ── queue skip / call_code ──▶ _by_call_type            (2a: the customer)
                                          └─▶ _verify_3rd ─ identity ─▶ _by_call_type   (2b: a third party)

`_by_call_type` classifies the reminder (before due / overdue / none) and
runs `_detect` for it: the money, time and agreement detectors side by
side, aggregated by the rule-based `_decide` in `ops.py`. The customer and
the third-party variants differ only in the agreement prompts they pass.
"""

from operonx.core import END, START, GraphOp, graph
from operonx.core.ops import if_
from operonx.providers import LLMOp

from ...core.config import LLM_RESOURCE_KEY
from ...core.conversation import Conversation
from ...core.prompts import PROMPTS
from .._shared.ops import exit_fn, format_fn, parsed
from .ops import (
    _decide,
)

# ---- detection phase ------------------------------------------------------
#
# The money, time and agreement detectors in parallel, aggregated by
# `_decide` (rule-based, no LLM); then either exit `Không vi phạm` or
# fire the violation response generator.


@graph
def _detect(transcript: str, call_type: str, time_prompt: str, agreement_prompt: str) -> GraphOp:
    """Shared RABA detector: checks money, time, agreement then decides."""

    money = LLMOp.of(
        description="Detect money amount",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE2A_MONEY_DETECTOR"],
        transcript=transcript,
        parser="json",
        fields=["has_money_mention: bool", "mentions: dict"],
    )
    money_parsed = parsed(error=money["error"])

    time = LLMOp.of(
        description="Detect repayment time",
        resource=LLM_RESOURCE_KEY,
        prompt=time_prompt,
        transcript=transcript,
        parser="json",
        fields=["has_time_mention: bool", "has_actionable_time_mention: bool = True", "mentions: dict"],
    )
    time_parsed = parsed(error=time["error"])

    agreement = LLMOp.of(
        description="Detect customer agreement/opposition",
        resource=LLM_RESOURCE_KEY,
        prompt=agreement_prompt,
        transcript=transcript,
        parser="json",
        fields=["is_opposed: bool", "reasoning: str"],
    )
    agreement_parsed = parsed(error=agreement["error"])

    decision = _decide(
        money_found=money["has_money_mention"],
        time_mention=time["has_time_mention"],
        oppose_found=agreement["is_opposed"],
        actionable_time_mention=time["has_actionable_time_mention"],
        agreement_reason=agreement["reasoning"],
    )

    response = LLMOp.of(
        description="Generate violation response",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE2A_RESPONSE_GENERATOR"],
        task_type=call_type,
        money_found=decision["money_found"],
        time_found=decision["time_found"],
        oppose_found=decision["oppose_found"],
        agreement_reason=decision["agreement_reason"],
        fields=["result.reason: dict"],
        parser="xml",
    )
    response_parsed = parsed(error=response["error"])

    violation_exit = exit_fn(violation=True, reason=response["reason"])
    no_violation = exit_fn(reason="N/A")

    # The three detectors run side by side; each reply is checked, and
    # `decision` waits for all three checks.
    START >> [time, money, agreement]
    time >> time_parsed
    money >> money_parsed
    agreement >> agreement_parsed
    [time_parsed, money_parsed, agreement_parsed] >> decision >> if_(decision["violation"], response).else_(no_violation)
    response >> response_parsed >> violation_exit >> END
    no_violation >> END


# ---------------------------------------------------------------------------
# By call type — shared by the customer (2a) and a third party (2b)
# ---------------------------------------------------------------------------


@graph
def _by_call_type(transcript: str, nyd_agreement_prompt: str, ovd_agreement_prompt: str) -> GraphOp:
    """Classify the reminder, then detect a RABA promise for that kind of call."""

    classifier = LLMOp.of(
        description="Classify call type",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE2A_TASK_CLASSIFIER"],
        transcript=transcript,
        parser="json",
        fields=["call_type: str"],
    )
    classifier_parsed = parsed(error=classifier["error"])

    call_type = classifier["call_type"]

    nyd = _detect(
        transcript=transcript,
        call_type=call_type,
        time_prompt=PROMPTS["VIOLATION_CASE2A_NYD_TIME_DETECTOR"],
        agreement_prompt=nyd_agreement_prompt,
    )
    ovd = _detect(
        transcript=transcript,
        call_type=call_type,
        time_prompt=PROMPTS["VIOLATION_CASE2A_OVD_TIME_DETECTOR"],
        agreement_prompt=ovd_agreement_prompt,
    )

    no_reminder = exit_fn(violation=True, reason="không hề có nhắc nợ trong cuộc gọi.")
    no_violation = exit_fn(reason="N/A")

    START >> classifier >> classifier_parsed >> (
        if_(call_type == 'PRE_DUE_REMINDER', nyd)
        .if_(call_type == 'OVERDUE_REMINDER', ovd)
        .if_(call_type == 'NO_REMINDER', no_reminder)
        .else_(no_violation)
    )
    [nyd, ovd, no_reminder, no_violation] >> END


# ---------------------------------------------------------------------------
# Case 2b: Third party promises to pay
# ---------------------------------------------------------------------------


@graph
def _verify_3rd(transcript: str) -> GraphOp:
    """Verify case 2b: whoever picked up must be a third party, then the same check."""

    identity = LLMOp.of(
        description="Classify receiver identity",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE2B_IDENTITY_CLASSIFIER"],
        transcript=transcript,
        parser="json",
        fields=["identity: str", "reasoning: str"],
    )
    identity_parsed = parsed(error=identity["error"])

    customer_exit = exit_fn(violation=True, reason=identity["reasoning"])
    unknown_exit = exit_fn(reason="không thể xác định danh tính người nhận cuộc gọi")
    third_party = _by_call_type(
        transcript=transcript,
        nyd_agreement_prompt=PROMPTS["VIOLATION_CASE2B_NYD_AGREEMENT_DETECTOR"],
        ovd_agreement_prompt=PROMPTS["VIOLATION_CASE2B_OVD_AGREEMENT_DETECTOR"],
    )

    START >> identity >> identity_parsed >> (
        if_(identity["identity"] == "CUSTOMER", customer_exit)
        .if_(identity["identity"] == "THIRD_PARTY", third_party)
        .else_(unknown_exit)
    )
    [third_party, customer_exit, unknown_exit] >> END


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# Queues for which RABA case is not enforced (per QC).
# 583 = RB_PRE_GB_UNDER_100K_FROM_6_OVD.
RABA_SKIP_QUEUE_ID = 583


@graph
def verify_raba(conversation: Conversation, call_code: str, queue_id: int = 0) -> GraphOp:
    """Verify violation case 2: RABA fraud detection.

    If `queue_id` matches a skip queue (e.g. 583 = RB_PRE_GB_UNDER_100K_FROM_6_OVD),
    bypass the check entirely — QC does not enforce RABA on these queues.
    """

    # Queue-based short-circuit (metadata-driven)
    queue_exit = exit_fn(reason=f"queue_id={RABA_SKIP_QUEUE_ID} (RB_PRE_GB_UNDER_100K_FROM_6_OVD) — không kiểm tra RABA")

    format = format_fn(conversation=conversation)

    first = _by_call_type(  # case 2a: the customer promises to pay
        transcript=format["content"],
        nyd_agreement_prompt=PROMPTS["VIOLATION_CASE2A_NYD_AGREEMENT_DETECTOR"],
        ovd_agreement_prompt=PROMPTS["VIOLATION_CASE2A_OVD_AGREEMENT_DETECTOR"],
    )
    third = _verify_3rd(transcript=format["content"])
    exit_code = exit_fn(reason="call_code không hợp lệ")

    START >> format >> (
        if_(queue_id == RABA_SKIP_QUEUE_ID, queue_exit)
        .if_(call_code == "Hua_tra", first)
        .if_(call_code == "Ben_thu_3_hua_tra", third)
        .else_(exit_code)
    )
    [first, third, exit_code, queue_exit] >> END
