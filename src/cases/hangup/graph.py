"""Case: Agent hangs up on customer."""

from operonx.core import END, START, GraphOp, graph
from operonx.core.ops import if_
from operonx.providers import LLMOp

from ...core.config import LLM_RESOURCE_KEY
from ...core.conversation import Conversation
from ...core.prompts import PROMPTS
from .._shared.ops import exit_fn, expand_evidence_fn, format_fn, parsed
from .ops import gate_flags


@graph
def _detect_intentional(conversation: Conversation, content: str) -> GraphOp:
    """Detect intentional hangup (customer has response)."""

    # Bot template check
    bot = LLMOp.of(
        description="Detect bot template usage",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE1_BOT_DETECTOR"],
        transcript=content,
        fields=["is_bot: bool", "reason: str"],
        parser="xml",
    )
    bot_parsed = parsed(error=bot["error"])
    bot_exit = exit_fn(reason=bot["reason"])

    # Implicit silent check
    silent_check = LLMOp.of(
        description="Check implicit silent customer",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE1_IMPLICIT_SILENT_PROMPT"],
        transcript=content,
        fields=["is_implicit_silent: bool", "reason: str"],
        parser="xml",
    )
    silent_check_parsed = parsed(error=silent_check["error"])
    silent_exit = exit_fn(reason=silent_check["reason"])

    # Verify intentional hangup
    verify = LLMOp.of(
        description="Verify intentional hangup",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE1_NORMAL_PROMPT"],
        transcript=content,
        fields=["result: dict"],
        parser="xml",
    )
    verify_parsed = parsed(error=verify["error"])
    mapping = expand_evidence_fn(
        llm_result=verify["result"],
        conversation=conversation,
        role="agent",
    )

    START >> bot >> bot_parsed >> if_(bot["is_bot"], bot_exit).else_(silent_check)
    silent_check >> silent_check_parsed >> if_(silent_check["is_implicit_silent"], silent_exit).else_(verify)
    verify >> verify_parsed >> mapping >> END
    [bot_exit, silent_exit] >> END


@graph
def _detect_silent(conversation: Conversation, content: str) -> GraphOp:
    """Detect silent hangup (customer is silent)."""

    # Bot template check
    bot = LLMOp.of(
        description="Detect bot template usage",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE1_BOT_DETECTOR"],
        transcript=content,
        fields=["is_bot: bool", "reason: str"],
        parser="xml",
    )
    bot_parsed = parsed(error=bot["error"])
    bot_exit = exit_fn(reason=bot["reason"])

    # Verify silent hangup
    verify = LLMOp.of(
        description="Verify silent hangup",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE1_SILENT_PROMPT"],
        transcript=content,
        fields=["result: dict"],
        parser="xml",
    )
    verify_parsed = parsed(error=verify["error"])
    mapping = expand_evidence_fn(
        llm_result=verify["result"],
        conversation=conversation,
        role="agent",
    )

    START >> bot >> bot_parsed >> if_(bot["is_bot"], bot_exit).else_(verify)
    verify >> verify_parsed >> mapping >> END
    bot_exit >> END


@graph
def verify_hangup(conversation: Conversation, call_code: str, closed_by: str) -> GraphOp:
    """Verify violation case 1: agent hangs up on customer."""

    exit_code = exit_fn(reason="Case này không phải là call_code Ngat_may")

    format = format_fn(conversation=conversation, istart=-10)
    flags = gate_flags(conversation=conversation)

    # Order matters — first match wins:
    # 1. mutual_silence (agent_silent AND customer_empty): real no-pickup /
    #    both-side silence → not a violation. Per QC: "Không bắt lỗi nếu
    #    cuộc gọi nhận diện: ĐTV im lặng và KH im lặng".
    # 2. agent_no_response (agent_silent but KH spoke — incl bot voicemail):
    #    violation regardless of closed_by. Per QC: agent must at least leave
    #    a closing message even when KH is voicemail/AI assistant.
    # 3. closed_by != AGENT (and agent did speak): KH chủ động ngắt → not a
    #    violation.
    # 4. customer_empty (agent spoke into the void): agent monologue / left
    #    voicemail-style message → run silent LLM to verify closure.
    # 5. customer_bot_only (agent had content + KH is all bot voicemail):
    #    agent already left voicemail-style message → not a violation.
    # 6. customer_silent: KH có turn nhưng không có nội dung → silent LLM.
    # 7. else: real customer interaction → run the intentional LLM check.
    exit_silent = exit_fn(reason="Agent phạm lỗi treo máy (agent im lặng)", violation=True)
    exit_customer = exit_fn(reason="Đây là trường hợp khách hàng ngắt máy")
    exit_no_real = exit_fn(reason="Cuộc gọi không có tương tác thật của KH (voicemail/không bắt máy/ĐTV và KH cùng im lặng)")

    silent = _detect_silent(conversation=conversation, content=format["content"])
    intentional = _detect_intentional(conversation=conversation, content=format["content"])

    START >> format >> if_(call_code == 'Ngat_may', flags).else_(exit_code)
    flags >> (
        if_(flags["mutual_silence"], exit_no_real)
        .if_(flags["agent_no_response"], exit_silent)
        .if_(closed_by != 'AGENT', exit_customer)
        .if_(flags["customer_empty"], silent)
        .if_(flags["customer_bot_only"], exit_no_real)
        .if_(flags["customer_silent"], silent)
        .else_(intentional)
    )
    [exit_silent, exit_customer, exit_no_real, silent, intentional, exit_code] >> END
