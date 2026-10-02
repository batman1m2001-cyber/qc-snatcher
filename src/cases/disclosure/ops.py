"""Disclosure ops — turn the disclosure detector's answer into a verdict.
"""
from __future__ import annotations

from typing import Any

from operonx.core import op


@op
def _violation_from_disclosure(
    reason: str = "",
    evidence: str = "",
) -> dict[str, Any]:
    """Package the disclosure detector's evidence idxs into an
    expand_evidence_fn-compatible dict so the shared helper can validate +
    render. Emits `violation=True` regardless (this node fires only after
    both identity checks failed)."""
    return {
        "result": {
            "violation": True,
            "reason": reason,
            "evidence": evidence,
        }
    }
