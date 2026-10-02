"""Layer 1 — cheap gates.

Everything that can end a call before an expensive model sees it, in the
order that costs least first: a scope check on `call_code`, a silent-agent
check on the formatted transcript, the keyword/LLM pre-filter, a regex bot
check, and finally the kid detector — the only LLM call in the layer, and
the only gate that runs on short calls alone.

The wiring is carried across from the flat graph unchanged. What is new is
the **boundary**: a layer has to say not only what it decided but what the
next layer needs, because a subgraph's ops cannot reach into a sibling's.

Two ways out, and the difference is the whole contract:

* a gate fired — `result` carries the verdict and `_trace_meta["exit"]`
  names which gate. `is_decided` reads that stamp downstream.
* nothing fired — `proceed` emits `result: None` plus `content` and
  `filter_meta`, which layers 2 and 3 need and can no longer take from
  `fmt` and `apply_gate` directly.

`result: None` is deliberately not a verdict. A later layer that mistook
absence for a clean call would be the 2026-09-23 defect again, so
`is_decided` answers False for it and the call flows on to be judged.
"""
from operonx.core import END, START, GraphOp, graph
from operonx.core.ops import if_
from operonx.providers import LLMOp

from ....core.config import LLM_RESOURCE_KEY
from ....core.conversation import Conversation
from ....core.prompts import PROMPTS
from ..._shared.ops import exit_fn, format_fn, parsed
from .ops import (
    KID_DETECTOR_TURN_CAP,
    is_bot_customer_fn,
    is_kid_fn,
    proceed_fn,
)
from .prefilter import apply_filter_gate_fn
from .prefilter import filter_sentiment_agent

__all__ = ["l1_gates", "KID_DETECTOR_TURN_CAP"]

_KID_CACHED_TEMPLATE = PROMPTS.pair("KID_DETECTOR_PROMPT")


@graph
def l1_gates(conversation: Conversation, call_code: str = "") -> GraphOp:
    """Cheap gates — scope, silence, pre-filter, bot, short-call, kid."""

    exit_code = exit_fn(
        reason="Bỏ qua case sentiment ĐTV với call_code Ben_thu_3_DVKD / Ben_thu_3_DVKD_AF",
        exit_stage="scope",
    )

    fmt = format_fn(conversation=conversation)

    quiet = exit_fn(category="im_lang",
                    exit_stage="agent_silent")

    # C12 side-chatter detector DISABLED (2026-07-29). Live diagnostic on
    # 969-call batch showed ~408/665 flagged calls were C12 with ~100% FP —
    # detector mistook AGENT identity-verification turns ("em hỏi có phải
    # số của anh X không") for "nói chuyện riêng với đồng nghiệp". Real C12
    # cases are rare per QC. Re-enable only after prompt+corpus rewrite.

    prefilter = filter_sentiment_agent(conversation=conversation)
    # Apply/shadow gate: `apply_gate["gate"] == "block"` only when
    # `SENTIMENT_FILTER_APPLY=true` (default) AND filter says clean. In
    # shadow mode (apply=false) gate always passes; verdict rides on
    # `filter_meta` and gets stashed on the final result's
    # `_trace_meta["filter"]`.
    apply_gate = apply_filter_gate_fn(
        should_scan=prefilter["should_scan"],
        reason=prefilter["reason"],
        kw_hit=prefilter["kw_hit"],
        llm_verdict=prefilter["llm_verdict"],
    )
    filter_exit = exit_fn(
        reason="Pre-filter không phát hiện dấu hiệu vi phạm",
        filter_meta=apply_gate["filter_meta"],
        exit_stage="filter",
    )

    bot_check = is_bot_customer_fn(conversation=conversation)
    exit_bot = exit_fn(
        category="khach_la_bot",
        reason="Người nghe là trợ lý ảo / IVR — bỏ qua đánh giá thái độ ĐTV",
        exit_stage="bot",
        filter_meta=apply_gate["filter_meta"],
    )

    kid_check = LLMOp.of(
        description="Detect whether the customer on the call is a child",
        resource=LLM_RESOURCE_KEY,
        prompt=_KID_CACHED_TEMPLATE,
        transcript=fmt["content"],
        fields=["result: dict"],
        parser="xml",
    )
    kid_check_parsed = parsed(error=kid_check["error"])
    exit_kid = exit_fn(
        category="khach_la_tre_em",
        reason="Người nghe là trẻ em — bỏ qua đánh giá thái độ ĐTV",
        exit_stage="kid",
        filter_meta=apply_gate["filter_meta"],
    )

    proceed = proceed_fn(
        content=fmt["content"],
        filter_meta=apply_gate["filter_meta"],
    )

    # Long calls skip the kid detector; short ones only pass once it has
    # cleared them. One comparison against a cap, so it goes on the edge.
    short_gate = if_(fmt["n_turns"] <= KID_DETECTOR_TURN_CAP, kid_check).else_(proceed)

    # ─── Wiring ────────────────────────────────────────────────────────
    START >> fmt >> (
        if_(call_code == 'Ben_thu_3_DVKD', exit_code)
        .if_(call_code == 'Ben_thu_3_DVKD_AF', exit_code)
        .if_(fmt["agent_silent"], quiet)
        .else_(prefilter)
    )

    prefilter >> apply_gate >> if_(apply_gate["gate"] == "block", filter_exit).else_(bot_check)

    bot_check >> if_(bot_check["is_bot"], exit_bot).else_(short_gate)

    kid_check >> kid_check_parsed >> if_(is_kid_fn(result=kid_check["result"]), exit_kid).else_(proceed)

    [exit_code, quiet, filter_exit, exit_bot, exit_kid, proceed] >> END
