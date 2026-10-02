"""Pre-filter for sentiment_agent — union of keyword + cheap-LLM checks.

Two independent gates, either one can pass a call to the expensive scanner:

  1. **Keyword filter** — deterministic substring match against phrases in
     `knowledge/sentiment_agent/keyword_filter.yaml`. Toggle with
     `SENTIMENT_FILTER_KEYWORD_ENABLE`.
  2. **LLM filter** — cheap local model (e.g. gemma4-e4b via llama.cpp)
     runs `FILTER_PROMPT` per chunk. On when `llm.prefilter` in
     `models.yaml` names a resource.

Union semantics: `should_scan = kw_hit OR llm_violation`. KW short-circuits
past the LLM branch to save the call. Both disabled → pass-through
(should_scan=True, reason=filter_disabled).

Chunks of CHUNK=100 turns, OVERLAP=10, scanned in parallel (`scan_chunks`).

Subgraph output contract:

    {
        "should_scan": bool,
        "reason": str,               # semantic reason (filter_disabled, ...)
        "kw_hit": bool,              # KW verdict (False if disabled)
        "llm_verdict": bool | None,  # LLM verdict (None if disabled/unparseable)
    }

Runtime routing:

    START → dispatch → route ∈ {
        disabled_pass   both filters off → pass, no cost
        kw_hit_pass     KW matched → pass, skip LLM
        llm_scan        LLM enabled + KW missed → chunk scans + aggregate
        kw_clean_pass   KW ran, missed, LLM off → clean pass
    }

`apply_filter_gate_fn` (in `l1_gates/graph.py`, after this subgraph) reads
`SENTIMENT_FILTER_APPLY` to decide whether should_scan=false blocks the
main flow (gate mode) or is annotated only (shadow mode).
"""
from __future__ import annotations

from operonx.core import END, PARENT, START, GraphOp, graph
from operonx.core.ops import if_
from operonx.providers import LLMOp

from ...._shared.ops import parsed
from .....core.config import SENTIMENT_FILTER_LLM_RESOURCE_KEY
from .....core.conversation import Conversation
from .....core.prompts import PROMPTS
from .ops import (
    FILTER_CHUNK_WORKERS,
    ROUTE_DISABLED,
    ROUTE_KW_CLEAN,
    ROUTE_KW_HIT,
    aggregate_llm_result_fn,
    disabled_pass_fn,
    dispatch_fn,
    each_chunk,
    kw_clean_pass_fn,
    kw_hit_pass_fn,
    no_chunks_pass_fn,
    prepare_filter_chunks_fn,
)

__all__ = ["filter_sentiment_agent", "scan_chunks"]


# ---------------------------------------------------------------------------


@graph
def scan_chunks(transcripts: list) -> GraphOp:
    """Fan the cheap scan across chunks, concurrently.

    Exists as a subgraph rather than two ops in the parent purely so the
    parent has something to `.collect()` from: a subgraph ends once, a
    fanned-out op ends once per item.

    `.parallel(max=FILTER_CHUNK_WORKERS)` caps the chunks in flight (enforced
    since operonx 1.11). A call has one chunk per 100 content turns, so in
    practice that is one to three.
    """
    fan = each_chunk(transcripts=transcripts)
    scan = LLMOp.of(
        description="filter — cheap scan per chunk",
        resource=SENTIMENT_FILTER_LLM_RESOURCE_KEY,
        prompt=PROMPTS["FILTER_PROMPT"],
        transcript=fan["transcript"].parallel(max=FILTER_CHUNK_WORKERS),
        parser="json",
        fields=["result: dict"],
    )
    scan_parsed = parsed(error=scan["error"])
    START >> fan >> scan >> scan_parsed >> END
    scan["result"] >> PARENT["result"]


@graph
def filter_sentiment_agent(conversation: Conversation) -> GraphOp:
    """Pre-filter with runtime enable/disable for BOTH keyword + LLM checks.

    Runtime routing (single compiled graph, decisions at runtime):

        START → dispatch → route:
            disabled_pass → END       (should_scan=True, reason=filter_disabled)
            kw_hit_pass   → END       (should_scan=True, reason=filter_kw_hit)
            kw_clean_pass → END       (should_scan=False, reason=filter_kw_miss_clean)
            llm_scan      → prep → scan_chunks → agg → END  (LLM verdict)

    Graph outputs the 4-field contract:
      - should_scan (bool)
      - reason (str)
      - kw_hit (bool)
      - llm_verdict (bool | None)
    """
    dispatch = dispatch_fn(
        conversation=conversation,
        return_keys=["route", "kw_hit"],
    )
    disabled_pass = disabled_pass_fn(
        return_keys=["should_scan", "reason", "kw_hit", "llm_verdict"],
    )
    kw_hit_pass = kw_hit_pass_fn(
        return_keys=["should_scan", "reason", "kw_hit", "llm_verdict"],
    )
    kw_clean_pass = kw_clean_pass_fn(
        return_keys=["should_scan", "reason", "kw_hit", "llm_verdict"],
    )

    prep = prepare_filter_chunks_fn(conversation=conversation)

    no_chunks_pass = no_chunks_pass_fn(
        return_keys=["should_scan", "reason", "kw_hit", "llm_verdict"],
    )
    chunk_scans = scan_chunks(transcripts=prep["transcripts"])

    # `.collect()` needs a source that emits exactly ONE end-of-stream
    # event. A generator is one; a **subgraph** is one too, which is why
    # the fan-out is wrapped rather than inlined. A bare fanned-out op is
    # not: it ends once per item, so a collect placed directly on it
    # flushes a one-element batch per item instead of the whole set.
    agg = aggregate_llm_result_fn(
        chunk_raws=chunk_scans["result"].collect(),
        return_keys=["should_scan", "reason", "kw_hit", "llm_verdict"],
    )

    START >> dispatch >> (
        if_(dispatch["route"] == ROUTE_DISABLED, disabled_pass)
        .if_(dispatch["route"] == ROUTE_KW_HIT, kw_hit_pass)
        .if_(dispatch["route"] == ROUTE_KW_CLEAN, kw_clean_pass)
        .else_(prep)
    )
    prep >> if_(prep["n_chunks"] == 0, no_chunks_pass).else_(chunk_scans)
    chunk_scans >> agg >> END
    [no_chunks_pass, disabled_pass, kw_hit_pass, kw_clean_pass] >> END
