"""Layer 3 — the filter decider, and the ASR-check route beside it.

By here the scanner has flagged something and its citation has survived
layer 2, so the question is whether the flagged turn actually breaks a
rule QC wrote down. Two routes answer it, and which one a call takes is
decided by keyword, not by model:

* **heavy keywords** (`mày` / `tao` / `con nợ`) go to a dedicated ASR-check
  model. These are words ASR mishears often enough that the useful
  question is "was this really said", not "is this a violation".
* **everything else** retrieves two pools from the corpus — violations and
  carve-outs — and asks the filter decider to rule with both in front of it.

The e2e flow diagram has no box for the ASR-check route; it is a live
production path all the same.

Unlike layers 1 and 2, **this layer always decides**. Both routes end in a
verdict, so the only thing it exports is `result`.
"""
from operonx.core import END, START, GraphOp, graph
from operonx.core.ops import if_
from operonx.providers import LLMOp

from ..._shared.ops import parsed
from ....core.config import DECIDER_LLM_RESOURCE_KEY
from ....core.conversation import Conversation
from ....core.prompts import PROMPTS
from ..retrieval.graph import retrieve_corpus
from .ops import (
    apply_asr_check_result_fn,
    apply_decider_result_fn,
    build_asr_check_inputs_fn,
    build_matcher_inputs_fn,
    build_retrieval_query_fn,
    route_check_fn,
)

__all__ = ["l3_decider"]

_DECIDER_TEMPLATE = PROMPTS.pair("DECIDER_PROMPT")


@graph
def l3_decider(
    conversation: Conversation,
    llm_result: dict = None,
    filter_meta: dict = None,
) -> GraphOp:
    """Judge the flagged turn — ASR-check for heavy keywords, else decider."""

    route_check = route_check_fn(llm_result=llm_result)

    asr_check_inputs = build_asr_check_inputs_fn(
        llm_result=llm_result,
        conversation=conversation,
        keyword=route_check["keyword"],
    )
    asr_check = LLMOp.of(
        description="ASR-check verifier — tone continuity for mày/tao/con nợ",
        resource=DECIDER_LLM_RESOURCE_KEY,
        prompt=PROMPTS["ASR_CHECK_PROMPT"],
        parser="json",
        keyword=asr_check_inputs["keyword"],
        evidence=asr_check_inputs["evidence"],
        context=asr_check_inputs["context"],
        fields=["result: dict"],
    )
    asr_check_parsed = parsed(error=asr_check["error"])
    apply_asr_check = apply_asr_check_result_fn(
        llm_result=llm_result,
        verify_out=asr_check["result"],
        asr_check_resource=DECIDER_LLM_RESOURCE_KEY,
        filter_meta=filter_meta,
    )

    # One LLM call sees both pools + evidence + context and outputs a
    # violation bool directly.
    #
    # Retrieval is a composed subgraph rather than a call inside an op: it
    # is the slowest hop in the case (embed + two vector searches + two
    # hydrates), and as a node it gets its own trace spans.
    retrieval_query = build_retrieval_query_fn(llm_result=llm_result)
    retrieval = retrieve_corpus(query=retrieval_query["query"])

    matcher_inputs = build_matcher_inputs_fn(
        llm_result=llm_result,
        conversation=conversation,
        positives=retrieval["positives"],
        carveouts=retrieval["carveouts"],
    )

    decider = LLMOp.of(
        description="decider — single call: taxonomy + P/C pools → violation bool",
        resource=DECIDER_LLM_RESOURCE_KEY,
        prompt=_DECIDER_TEMPLATE,
        parser="json",
        evidence=matcher_inputs["evidence"],
        context=matcher_inputs["context"],
        positives=matcher_inputs["positives_indexed"],
        carveouts=matcher_inputs["carveouts_indexed"],
        fields=["result: dict"],
    )
    decider_parsed = parsed(error=decider["error"])

    apply_decider = apply_decider_result_fn(
        llm_result=llm_result,
        decider_out=decider["result"],
        positives_items=matcher_inputs["positives_items"],
        carveouts_items=matcher_inputs["carveouts_items"],
        decider_resource=DECIDER_LLM_RESOURCE_KEY,
        filter_meta=filter_meta,
    )

    # ─── Wiring ────────────────────────────────────────────────────────
    START >> route_check >> if_(route_check["is_heavy_kw"], asr_check_inputs).else_(retrieval_query)
    asr_check_inputs >> asr_check >> asr_check_parsed >> apply_asr_check >> END
    retrieval_query >> retrieval >> matcher_inputs >> decider >> decider_parsed >> apply_decider >> END
