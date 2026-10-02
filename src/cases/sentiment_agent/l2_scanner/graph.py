"""Layer 2 — the scanner, and whether its evidence holds up.

One model call sweeps the transcript and names a suspect turn. Everything
after that is checking the citation before a decider is asked to rule on
it: expand the evidence, correct the index if the quoted phrase sits
elsewhere, then verify the quote is really in the agent's text. A
fabricated quote goes to the halu check, and a confirmed fabrication ends
the call here.

Two ways out, the same contract layer 1 uses:

* decided — `result` carries a verdict stamped with `_trace_meta["exit"]`,
  either `halu` (the citation was invented) or `no_violation` (the scanner
  cleared it, or the category has no matchable rule).
* continue — `proceed` emits `result: None` and hands on `llm_result`,
  the remapped scanner verdict that layer 3 judges.

`llm_result` and `result` are deliberately different fields. One is a
verdict in flight, the other is a verdict reached, and collapsing them is
how "not yet decided" turns into "decided clean".
"""
from operonx.core import END, START, GraphOp, graph
from operonx.core.ops import if_
from operonx.providers import LLMOp

from ....core.config import DECIDER_LLM_RESOURCE_KEY, LLM_RESOURCE_KEY
from ....core.conversation import Conversation
from ....core.prompts import PROMPTS
from ..._shared.ops import expand_evidence_fn, parsed
from .ops import (
    attr_check_fn,
    build_halu_check_inputs_fn,
    halu_suppress_fn,
    is_halu_fn,
    needs_matcher_fn,
    proceed_fn,
    remap_evidence_fn,
    skip_matcher_fn,
)

__all__ = ["l2_scanner"]

_CACHED_TEMPLATE = PROMPTS.pair("SCANNER_PROMPT")
_HALU_CACHED_TEMPLATE = PROMPTS.pair("HALU_CHECK_PROMPT")


@graph
def l2_scanner(
    conversation: Conversation,
    content: str = "",
    filter_meta: dict = None,
) -> GraphOp:
    """Scan the transcript, then check the citation before trusting it."""

    scanner = LLMOp.of(
        description="scanner — sweeps transcript, flags one suspect violation",
        resource=LLM_RESOURCE_KEY,
        # validators=_verify_result_ok is deliberately NOT wired here.
        # hush only consulted `validator` on the fallback path, and this
        # site has no fallback — so the predicate has never run. operonx
        # would make it live, which is a verdict change, not a port. It
        # lands as its own commit with its own F1 check.
        prompt=_CACHED_TEMPLATE,
        parser="json",
        transcript=content,
        fields=["result: dict"],
    )
    scanner_parsed = parsed(error=scanner["error"])

    mapping = expand_evidence_fn(
        llm_result=scanner["result"],
        conversation=conversation,
    )

    # Deterministic evidence_idxs re-map — if scanner's reason quotes a
    # phrase not found in cited turn(s), search all AGENT turns for the
    # phrase and correct evidence_idxs before matcher runs. Cheap (regex +
    # substring); no LLM call.
    remap = remap_evidence_fn(
        llm_result=mapping["result"],
        conversation=conversation,
    )

    attr_check = attr_check_fn(
        llm_result=remap["result"],
        conversation=conversation,
    )

    halu_check_inputs = build_halu_check_inputs_fn(
        llm_result=remap["result"],
        conversation=conversation,
    )
    halu_check = LLMOp.of(
        description="halu-check — LLM verifies scanner attribution when substring miss",
        resource=DECIDER_LLM_RESOURCE_KEY,
        prompt=_HALU_CACHED_TEMPLATE,
        parser="json",
        evidence=halu_check_inputs["evidence"],
        scanner_reason=halu_check_inputs["scanner_reason"],
        context=halu_check_inputs["context"],
        fields=["result: dict"],
    )
    halu_check_parsed = parsed(error=halu_check["error"])
    halu_suppress = halu_suppress_fn(
        llm_result=remap["result"],
        halu_result=halu_check["result"],
        filter_meta=filter_meta,
    )

    needs_verify = needs_matcher_fn(llm_result=remap["result"])
    skip_verify = skip_matcher_fn(
        llm_result=remap["result"],
        filter_meta=filter_meta,
    )

    proceed = proceed_fn(llm_result=remap["result"], filter_meta=filter_meta)

    # ─── Wiring ────────────────────────────────────────────────────────
    START >> scanner >> scanner_parsed >> mapping >> remap >> attr_check

    # Good attribution goes straight to the verify gate; bad attribution
    # asks the halu-check LLM first, and a "not halu" verdict rejoins the
    # same node.
    attr_check >> if_(attr_check["attribution_ok"], needs_verify).else_(halu_check_inputs)
    halu_check_inputs >> halu_check >> halu_check_parsed >> (
        if_(is_halu_fn(result=halu_check["result"]), halu_suppress).else_(needs_verify)
    )

    # Verify gate: khong_vi_pham verdicts short-circuit here.
    needs_verify >> if_(needs_verify["needs_verify"], proceed).else_(skip_verify)
    [halu_suppress, skip_verify, proceed] >> END
