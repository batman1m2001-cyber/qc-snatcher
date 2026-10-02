"""Agent sentiment — four layers, named after the blocks QC and IT already read.

The layers match the four blocks of
`docs/FLOW_sentiment_agent_end_to_end.html`, so the diagram and the graph
describe the same thing.

    l1_gates    cheap gates      scope · silence · pre-filter · bot · kid
    l2_scanner  scanner          scan → remap → attribution → halu
    l3_decider  filter decider   retrieval → decider, or the ASR-check route
    l4_verify   primary decider  strict re-verify → severity → wording

Each layer exports `result`: a verdict when it decided, `None` when it did
not. `is_decided` tells them apart by reading `_trace_meta["exit"]`, which
every terminal stamps.

**`None` is not a clean call.** A layer that read absence as a verdict
would skip the stages meant to catch a loss and emit `Tích cực` for a call
nothing judged — which is why `is_decided` checks for the stamp instead of
truthiness.

Every path reaches `l4`, decided or not: both of its stages gate on
`violation` and pass anything else through.
"""

from operonx.core import END, START, GraphOp, graph
from operonx.core.ops import if_

from ...core.conversation import Conversation
from .._shared.ops import is_decided
from .l1_gates import KID_DETECTOR_TURN_CAP, l1_gates
from .l2_scanner import l2_scanner
from .l3_decider import _verify_result_ok, l3_decider
from .l4_verify import l4_verify
from .ops import pick_decided

__all__ = [
    "verify_sentiment_agent",
    "KID_DETECTOR_TURN_CAP",
    "_verify_result_ok",
]


@graph
def verify_sentiment_agent(conversation: Conversation, call_code: str = "") -> GraphOp:
    """Verify AGENT sentiment violations across four layers."""
    l1 = l1_gates(conversation=conversation, call_code=call_code)
    l2 = l2_scanner(
        conversation=conversation,
        content=l1["content"],
        filter_meta=l1["filter_meta"],
    )
    l3 = l3_decider(
        conversation=conversation,
        llm_result=l2["llm_result"],
        filter_meta=l2["filter_meta"],
    )
    decided = pick_decided(l1=l1["result"], l2=l2["result"], l3=l3["result"])
    l4 = l4_verify(conversation=conversation, result=decided["result"])

    # A layer that decided jumps to `decided`; one that did not hands on.
    START >> l1 >> if_(is_decided(result=l1["result"]), decided).else_(l2)
    l2 >> if_(is_decided(result=l2["result"]), decided).else_(l3)
    l3 >> decided >> l4 >> END
