"""Customer-sentiment row — what `_finalize` writes for this case's verdict."""
from .._shared.spec import default_sentiment_row, is_violation


def format_sentiment_customer(result: dict | None) -> dict:
    """Customer sentiment row — three outcomes:

      - category == "im_lang"            → "KH im lặng"
      - violation flag set               → "Tiêu cực"
      - no result emitted                → default "Tích cực"

    All three carry score_offset=0 (KH sentiment never penalizes the agent).
    """
    if not result:
        return default_sentiment_row()
    cat = result.get("category")
    if cat == "im_lang":
        label = "KH im lặng"
    elif is_violation(result):
        label = "Tiêu cực"
    else:
        return default_sentiment_row()
    return {
        "Reasoning": result.get("reason", ""),
        "Result": label,
        "Evidence": result.get("evidence", ""),
        "Score_offset": 0,
        "EvidenceIdxs": list(result.get("evidence_idxs") or []),
    }
