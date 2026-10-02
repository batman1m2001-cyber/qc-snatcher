"""Snapshotting what the scanner said — read by two layers.

`_scanner_trace` is written on every path that has a scanner verdict,
including the clean one. Layer 2 records it when it ends a call itself,
layer 3 when it applies a decider or ASR-check verdict, so it sits between
them rather than inside either.

It used to be built inline on the flagged paths only, which made the block
present if and only if `violation` was true — a boolean that was never
false, and an absence meaning three different things at once: the scanner
cleared the call, never ran, or failed.

Moved verbatim from `_matcher.py`.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .._shared.ops import _coerce_violation


def _normalize_vn(text: str) -> str:
    """Lowercase, strip diacritics, strip punctuation, collapse whitespace."""
    if not isinstance(text, str):
        return ""
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _plain_evidence(raw_ev) -> tuple[str, str]:
    """Extract plain evidence text for retrieval + prompt display.

    Returns (retrieval_query, display_string). Display converts '<br/>'
    to newlines; query strips [mm:ss] markers and collapses whitespace.
    """
    if raw_ev is None:
        return "", ""
    if isinstance(raw_ev, str):
        display = raw_ev.replace("<br/>", "\n")
        stripped = re.sub(r"\[\d{1,2}:\d{2}\]:\s*", "", display)
        query = re.sub(r"\s+", " ", stripped).strip()
        return query, display
    s = str(raw_ev)
    return s, s


def evidence_query(result: dict | None) -> str:
    """The corpus retrieval query for a flagged result: its evidence turn.

    l3 and l4 both call this, so the two layers retrieve on the same text
    and consult the same pools for one call.
    """
    if not isinstance(result, dict):
        return ""
    return _plain_evidence(result.get("evidence"))[0]


def _scanner_trace(llm_result: dict) -> dict[str, Any]:
    """Snapshot of what the scanner said, for `_trace_meta["scanner"]`.

    Written on every path that has a scanner verdict — including the clean
    one. It used to be built inline on the three flagged paths only, which
    made the block present if and only if `violation` was true: a boolean
    that was never false, and an absence that meant three different things
    (scanner cleared the call / scanner never ran / scanner failed). A
    reviewer asking "why was this call not flagged?" got the same empty
    output either way.
    """
    return {
        "violation":         _coerce_violation(llm_result.get("violation")),
        "category_raw":      (llm_result.get("category") or "").strip(),
        "reason":            (llm_result.get("reason") or "").strip(),
        "evidence":          (llm_result.get("evidence") or "").strip(),
        "evidence_idxs_raw": list(llm_result.get("evidence_idxs") or []),
    }
