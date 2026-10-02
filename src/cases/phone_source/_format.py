"""Phone-source row — what `_finalize` writes for this case's verdict."""
from .._shared.spec import HVC_PENALTY, hvc_row


def format_phone_source(result: dict | None) -> dict:
    """Phone-source row formatter — violation → -100 QC score offset."""
    return hvc_row(result, score_offset=HVC_PENALTY)
