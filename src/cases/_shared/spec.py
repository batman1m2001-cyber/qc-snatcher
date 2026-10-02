"""Helpers every case shares: the output rows, and the two readings of a
model's reply — `is_true` (a yes/no field) and `turn_idxs` (cited turns).

Each case's `format_<id>(result) → row_dict` function reuses the row
helpers to keep output rows uniform. No registry / dataclass indirection —
the case wiring lives in `src/cases/__init__.py::CASES` and `src/qc/graph.py`.
"""

from __future__ import annotations

from typing import Any, Optional

#: `Score_offset` of any HVC violation (raba, disclosure, card_number,
#: phone_source). hangup scores -25 and sets its own.
HVC_PENALTY = -100


def default_hvc_row() -> dict:
    """Default row for an HVC case that did not produce a violation."""
    return {"Reasoning": "", "Result": "Không vi phạm", "Evidence": "", "Score_offset": 0}


def default_sentiment_row() -> dict:
    """Default row for a Sentiment case that did not produce a result."""
    return {"Reasoning": "", "Result": "Tích cực", "Evidence": "", "Score_offset": 0}


def is_true(value) -> bool:
    """A model's yes/no field as a bool: `True`, or a string reading "true"
    once stripped and lowercased ("True", " TRUE "). Anything else — "false",
    "yes", 1, None — is False. XML parsers leave `<violation>true</violation>`
    a string, and `bool("false")` is True."""
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return value is True


def turn_idxs(raw: Any) -> list[int]:
    """The turn indexes a model cited, as ints: a list, or a string "3, 5"
    (`;` also separates). Bad tokens (`3a`, "", None) are dropped; anything
    else is no indexes."""
    if isinstance(raw, str):
        raw = raw.replace(";", ",").split(",")
    elif not isinstance(raw, list):
        return []
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def is_violation(result: Optional[dict]) -> bool:
    """True if the LLM-emitted result is flagged as a violation."""
    return bool(result) and is_true(result.get("violation"))


def hvc_row(result: Optional[dict], score_offset: int) -> dict:
    """Standard HVC row formatter — violation → fixed score offset.

    `evidence` is the pre-rendered display text (built by expand_evidence_fn
    from the LLM's `<evidence>` turn_idx list); `evidence_idxs` is the
    validated int list qc-monitor can render as clickable refs.
    """
    if is_violation(result):
        return {
            "Reasoning": result.get("reason", ""),
            "Result": "Vi phạm",
            "Evidence": result.get("evidence", ""),
            "Score_offset": score_offset,
            "EvidenceIdxs": list(result.get("evidence_idxs") or []),
        }
    return default_hvc_row()
