"""Cases package — declarative catalog of the 7 QC cases.

`CASES` is a flat dict keyed by case id. Each value carries the metadata
consumed uniformly by the pipeline (whitelist parsing, case selection) and
by `score_cases`'s row rendering. Case topology (which node wires to
which) lives explicitly in `src/qc/graph.py`.

Render order matches CASES insertion order — HVC section first, Sentiment
second. Preserved inside each section by `_finalize`.
"""

from typing import Callable, NamedTuple

from ..core.case_ids import CASE_IDS

from .card_number        import format_card_number,        verify_card_number
from .disclosure         import format_disclosure,         verify_disclosure
from .hangup             import format_hangup,             verify_hangup
from .phone_source       import format_phone_source,       verify_phone_source
from .raba               import format_raba,               verify_raba
from .sentiment_agent    import format_sentiment_agent,    verify_sentiment_agent
from .sentiment_customer import format_sentiment_customer, verify_sentiment_customer


class Case(NamedTuple):
    section: str       # "HVC" | "Sentiment"
    criteria: str      # Vietnamese label written into the output JSON
    code: str          # QC criterion code (TC_1..TC_7) — IT mapping key
    verify: Callable   # @graph runner
    format: Callable   # result dict → row body


CASES: dict[str, Case] = {
    "hangup":             Case("HVC",       "Treo máy/cố tình ngắt máy",                        "TC_7", verify_hangup,             format_hangup),
    "raba":               Case("HVC",       "Gian lận Raba",                                    "TC_5", verify_raba,               format_raba),
    "disclosure":         Case("HVC",       "Lỗi trao đổi thông tin của KH cho BT3 không quen biết", "TC_6", verify_disclosure,     format_disclosure),
    "card_number":        Case("HVC",       "Cung cấp 16 số in dập nổi trên thẻ của KH",        "TC_3", verify_card_number,        format_card_number),
    "phone_source":       Case("HVC",       "Cung cấp nguồn truy dấu thông tin của KH/BT3",     "TC_4", verify_phone_source,       format_phone_source),
    "sentiment_agent":    Case("Sentiment", "Thái độ ĐTV",                                       "TC_2", verify_sentiment_agent,    format_sentiment_agent),
    "sentiment_customer": Case("Sentiment", "Thái độ KH",                                        "TC_1", verify_sentiment_customer, format_sentiment_customer),
}


assert tuple(CASES) == CASE_IDS, (
    "CASE_IDS drifted from CASES — update src/core/case_ids.py to match "
    "the CASES insertion order."
)


CRITERIA_TO_CASE_ID: dict[str, str] = {c.criteria: cid for cid, c in CASES.items()}


__all__ = ["CASES", "CASE_IDS", "Case", "CRITERIA_TO_CASE_ID"]
