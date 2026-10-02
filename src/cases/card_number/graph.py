"""Case: Agent reads 16-digit card number to customer."""

from typing import Any

from operonx.core import END, START, GraphOp, graph
from operonx.core.ops import if_
from operonx.providers import LLMOp

from ...core.config import LLM_RESOURCE_KEY
from ...core.prompts import PROMPTS
from .._shared.ops import exit_fn, expand_evidence_fn, format_fn, parsed
from .ops import gate_digit_count, is_suspicious


@graph
def verify_card_number(conversation: Any) -> GraphOp:
    """Verify violation case 4: agent reads 16-digit card number to customer."""

    check = is_suspicious(conversation=conversation)
    exit_verify = exit_fn(reason="Không phát hiện nghi ngờ đọc số thẻ")

    format = format_fn(conversation=conversation)

    verify = LLMOp.of(
        description="Verify card number reading violation",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE4_PROMPT"],
        transcript=format["content"],
        fields=["result: dict"],
        parser="xml",
    )
    verify_parsed = parsed(error=verify["error"])

    gated = gate_digit_count(
        llm_result=verify["result"],
        conversation=conversation,
    )

    mapping_result = expand_evidence_fn(
        llm_result=gated["result"],
        conversation=conversation,
        role="agent",
    )

    START >> check >> if_(check, format).else_(exit_verify)
    format >> verify >> verify_parsed >> gated >> mapping_result >> END
    exit_verify >> END
