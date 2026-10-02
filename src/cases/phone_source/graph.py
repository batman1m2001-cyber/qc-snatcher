"""Case: Agent reveals source of customer/third-party phone number."""

from operonx.core import END, START, GraphOp, graph
from operonx.core.ops import if_
from operonx.providers import LLMOp

from ...core.config import LLM_RESOURCE_KEY
from ...core.conversation import Conversation
from ...core.prompts import PROMPTS
from .._shared.ops import exit_fn, expand_evidence_fn, format_fn, parsed
from .ops import (
    is_suspicious,
)


@graph
def verify_phone_source(conversation: Conversation, call_code: str) -> GraphOp:
    """Verify violation case 5: agent reveals source of phone number.

    Scope rule (per QC, pilot/Issue_details.csv): bỏ qua case này khi
    call_code = "Ben_thu_3_DVKD" — bối cảnh BT3 DVKD không tính vi phạm
    "tiết lộ nguồn truy dấu thông tin".
    """

    exit_code = exit_fn(reason="Bỏ qua case này khi call_code = Ben_thu_3_DVKD")

    check = is_suspicious(conversation=conversation)
    exit_kw = exit_fn(reason="Không phát hiện từ khóa nghi ngờ")

    format = format_fn(conversation=conversation)

    verify = LLMOp.of(
        description="Verify phone source disclosure violation",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE5_PROMPT"],
        transcript=format["content"],
        fields=["result: dict"],
        parser="xml",
    )
    verify_parsed = parsed(error=verify["error"])

    mapping = expand_evidence_fn(
        llm_result=verify["result"],
        conversation=conversation,
        role="agent",
    )

    START >> format >> if_(call_code == 'Ben_thu_3_DVKD', exit_code).else_(check)
    check >> if_(check, verify).else_(exit_kw)
    verify >> verify_parsed >> mapping >> END
    [exit_code, exit_kw] >> END
