"""Hangup row — what `_finalize` writes for this case's verdict."""
from .._shared.spec import hvc_row


def format_hangup(result: dict | None) -> dict:
    """Hangup row formatter — violation → -25 QC score offset."""
    return hvc_row(result, score_offset=-25)
