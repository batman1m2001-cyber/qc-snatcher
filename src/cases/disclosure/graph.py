"""Case: Disclosure of personal info without identity verification.

Order:
  1. is_chinh_chu short-circuit
  2. format first 60s
  3. disclosure → if disclosed=false → exit no violation
  4. (disclosed=true) direct identity → if verified → exit no violation
  5. implicit identity → if verified → exit no violation
  6. → VIOLATION (with evidence expanded from disclosure's agent turn_idxs)
"""

from typing import Any

from operonx.core import END, START, GraphOp, graph
from operonx.core.ops import if_
from operonx.providers import LLMOp

from ...core.config import LLM_RESOURCE_KEY
from ...core.prompts import PROMPTS
from .._shared.ops import exit_fn, expand_evidence_fn, format_fn, parsed
from .ops import (
    _violation_from_disclosure,
)


@graph
def verify_disclosure(conversation: Any, is_chinh_chu: bool = False) -> GraphOp:
    """Verify violation case 3: disclosing personal info without identity verification.

    If `is_chinh_chu` is True (SDT chính chủ), skip the check entirely — exposing
    loan info to the loan owner is not a third-party disclosure violation.
    """

    # Step 1: chính chủ short-circuit (metadata-driven)
    chinh_chu_exit = exit_fn(reason="SDT chính chủ — không kiểm tra cung cấp thông tin BT3")

    format = format_fn(conversation=conversation, iend=2*30)

    # Step 3: Disclosure FIRST — if no disclosure, nothing to violate
    disclosure = LLMOp.of(
        description="Check if loan info was disclosed",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE3_DISCLOSURE_PROMPT"],
        transcript=format["content"],
        fields=["disclosed: bool", "reason: str", "evidence: str"],
        parser="xml",
    )
    disclosure_parsed = parsed(error=disclosure["error"])
    no_disclosure_exit = exit_fn(reason=disclosure["reason"])

    # Step 4: Direct identity verification (full 60s transcript)
    direct = LLMOp.of(
        description="Check for direct identity verification",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE3_IDENTITY_DIRECT_PROMPT"],
        transcript=format["content"],
        fields=["verified: bool", "reason: str"],
        parser="xml",
    )
    direct_parsed = parsed(error=direct["error"])
    direct_exit = exit_fn(reason=direct["reason"])

    # Step 5: Implicit identity verification (full 60s — covers TH2 ambiguous-then-confirm)
    implicit = LLMOp.of(
        description="Check for implicit identity verification",
        resource=LLM_RESOURCE_KEY,
        prompt=PROMPTS["VIOLATION_CASE3_IDENTITY_IMPLICIT_PROMPT"],
        transcript=format["content"],
        fields=["verified: bool", "reason: str"],
        parser="xml",
    )
    implicit_parsed = parsed(error=implicit["error"])
    implicit_exit = exit_fn(reason=implicit["reason"])

    # Step 6: Violation — disclosure detected, no identity confirmation anywhere.
    # Feed disclosure's raw evidence idxs through the shared expander so the
    # display text is built and anti-hallucinate gate runs uniformly.
    violation_raw = _violation_from_disclosure(
        reason=disclosure["reason"],
        evidence=disclosure["evidence"],
    )
    violation_exit = expand_evidence_fn(
        llm_result=violation_raw["result"],
        conversation=conversation,
        role="agent",
    )

    # Wiring
    START >> format >> if_(is_chinh_chu, chinh_chu_exit).else_(disclosure)
    disclosure >> disclosure_parsed >> if_(disclosure["disclosed"], direct).else_(no_disclosure_exit)
    direct >> direct_parsed >> if_(direct["verified"], direct_exit).else_(implicit)
    implicit >> implicit_parsed >> if_(implicit["verified"], implicit_exit).else_(violation_raw)
    violation_raw >> violation_exit >> END
    [chinh_chu_exit, no_disclosure_exit, direct_exit, implicit_exit] >> END
