"""`score_cases` — one call through the seven cases, into one result.

    START ──▶ the seven verify_<id>, in parallel ──▶ _finalize ──▶ END

`_finalize` formats each case's verdict into its row, splits HVC from
Sentiment and sums `Score_offset`: `{"call_scoring": {"Sentiment": [...],
"HVC": [...], "qc_score_total_offset": int}}`. What a case is (criteria
label, section, row formatter) lives in `src/cases/__init__.py::CASES`.
"""
from operonx.core import END, START, GraphOp, graph

from ..cases import (
    verify_card_number,
    verify_disclosure,
    verify_hangup,
    verify_phone_source,
    verify_raba,
    verify_sentiment_agent,
    verify_sentiment_customer,
)
from ..core import config
from ..core.conversation import Conversation
from .ops import _finalize


@graph
def score_cases(
    conversation: Conversation,
    call_code: str,
    closed_by: str,
    is_chinh_chu: bool = False,
    queue_id: int = 0,
    include_traces: bool = None,
) -> GraphOp:
    """Score one call on the seven cases; each gets only the inputs it reads.

    *include_traces* puts the sentiment row's stage block in the result;
    unset, `INCLUDE_TRACES` decides (selfcheck passes True — its rules read it).
    A case switched off by `QC_ENABLE_<CASE_ID>=false` is built disabled: it
    runs nothing and its row reads `Không chạy`.
    """
    hangup             = verify_hangup            (conversation=conversation, call_code=call_code, closed_by=closed_by)
    raba               = verify_raba              (conversation=conversation, call_code=call_code, queue_id=queue_id)
    disclosure         = verify_disclosure        (conversation=conversation, is_chinh_chu=is_chinh_chu)
    card_number        = verify_card_number       (conversation=conversation)
    phone_source       = verify_phone_source      (conversation=conversation, call_code=call_code)
    sentiment_agent    = verify_sentiment_agent   (conversation=conversation, call_code=call_code)
    sentiment_customer = verify_sentiment_customer(conversation=conversation)

    finalize = _finalize(
        hangup             = hangup["result"],
        raba               = raba["result"],
        disclosure         = disclosure["result"],
        card_number        = card_number["result"],
        phone_source       = phone_source["result"],
        sentiment_agent    = sentiment_agent["result"],
        sentiment_customer = sentiment_customer["result"],
        include_traces     = include_traces,
    )

    # Each node is named after its variable, the case id. operonx has no
    # public way to reach a built graph's child, so the switch is set here.
    cases = [hangup, 
             raba, 
             disclosure, 
             card_number, 
             phone_source, 
             sentiment_agent, 
             sentiment_customer]
    for case in cases:
        case.enabled = case.name in config.ENABLED_CASES
    START >> cases >> finalize >> END
