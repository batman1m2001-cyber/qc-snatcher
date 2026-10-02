"""Card-number row — what `_finalize` writes for this case's verdict."""
from .._shared.spec import HVC_PENALTY, hvc_row


def format_card_number(result: dict | None) -> dict:
    """Card-number row formatter — violation → -100 QC score offset."""
    return hvc_row(result, score_offset=HVC_PENALTY)
