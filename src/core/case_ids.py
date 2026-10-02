"""The seven case ids, in render order — HVC first, Sentiment second.

A leaf module: `config` reads it to parse `QC_ENABLE_<CASE_ID>`, and
`src.cases` builds `CASES` in the same order (an assert there catches
drift). Importing `src.cases` from `config` instead would load every case
graph and point an import upward.
"""

CASE_IDS: tuple[str, ...] = (
    "hangup",
    "raba",
    "disclosure",
    "card_number",
    "phone_source",
    "sentiment_agent",
    "sentiment_customer",
)
