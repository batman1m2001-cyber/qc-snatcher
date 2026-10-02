"""Phone-source ops — the keyword trigger that decides whether the LLM runs.
"""
from __future__ import annotations

from operonx.core import op

from ...core.conversation import Conversation

TRIGGER_KEYWORDS = [
    "facebook", "face book", "phây búc", "phay buc", "phê bút", "phe but", "fb",
    "zalo", "za lo", "gia lô", "gia lo", "da lo",
    "instagram", "tiktok", "tik tok", "linkedin",
]


@op
def is_suspicious(conversation: Conversation) -> bool:
    """Check if AGENT turns contain social media keywords.

    Only agent-side mentions can constitute a source-disclosure violation.
    Customer turns that mention FB/Zalo (e.g. accusatory complaints, asking
    "did you find my number on Facebook?") are not violations and should
    not even pay the LLM cost.
    """
    if not conversation or not conversation.vads:
        return False

    agent_text = " ".join(
        (v.get("content") or "").strip()
        for v in conversation.vads
        if v.get("role") == "agent"
    ).lower()
    return any(kw in agent_text for kw in TRIGGER_KEYWORDS)
