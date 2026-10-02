"""Conversation — VAD-indexed transcript with turn_idx-based citation.

Each VAD gets a canonical `turn_idx` (content-position across the full
conversation) assigned at load time. Downstream code — `format()` for the
LLM-facing transcript and `expand_evidence_fn` for post-op idx→content
resolution — reads that field directly, so callers never recount turns
or look them up by mm:ss.

Non-content-bearing vads (silence gaps) carry `turn_idx = None` and are
skipped uniformly by both format + expand.

Also exports `format_mmss` — the mm:ss display prefix used by
`expand_evidence_fn` when rendering `[00:03]: <content>` evidence lines.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# ASR fixes — remove when the ASR is retrained.
#
# The current ASR confuses "máy" (phone) with "mày" (rude "you") in
# certain contexts. Patch only context-bound patterns where the noun must
# clearly mean "phone" (e.g. "nghe mày" → "nghe máy"). Bare "mày" stays
# untouched so customer-rude turns and real agent violations are not
# silently erased.
# ---------------------------------------------------------------------------
_ASR_FIX_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bnghe\s+mày\b"),    "nghe máy"),
    (re.compile(r"\bbắt\s+mày\b"),     "bắt máy"),
    (re.compile(r"\bchuyển\s+mày\b"),  "chuyển máy"),
    (re.compile(r"\bgác\s+mày\b"),     "gác máy"),
    (re.compile(r"\btắt\s+mày\b"),     "tắt máy"),
    (re.compile(r"\bngắt\s+mày\b"),    "ngắt máy"),
    (re.compile(r"\bcầm\s+mày\b"),     "cầm máy"),
    (re.compile(r"\bmày\s+bận\b"),     "máy bận"),
]


def normalize_asr(text: str) -> str:
    """Apply all ASR fix rules sequentially. Idempotent."""
    for pattern, repl in _ASR_FIX_RULES:
        text = pattern.sub(repl, text)
    return text


# ---------------------------------------------------------------------------
# mm:ss display helper — evidence prefix used by expand_evidence_fn.
# ---------------------------------------------------------------------------
def format_mmss(seconds: float) -> str:
    """Convert seconds to zero-padded mm:ss."""
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


# ---------------------------------------------------------------------------
# Conversation dataclass — the invariant enforcer.
# ---------------------------------------------------------------------------
@dataclass
class Conversation:
    """Turn-indexed transcript. `vads[i]["turn_idx"]` is the canonical id."""

    vads: list[dict[str, Any]] = field(default_factory=list)
    #: Where `load()` read this from. Traces record a pointer to the input
    #: file instead of copying the transcript, and without this the pointer
    #: is only a filename stem — you have to guess which batch directory it
    #: came from. Empty for conversations built in memory (tests).
    source_path: str = ""

    def __post_init__(self):
        """Normalise ASR text + assign canonical `turn_idx` in one pass.

        `turn_idx` counts CONTENT-bearing vads only (both roles), so the
        idx the LLM sees in `[N] AGENT: ...` matches the same key
        `expand_evidence_fn` looks up. Non-content vads carry None.
        """
        content_pos = -1
        for turn in self.vads:
            content = turn.get("content")
            if content:
                turn["content"] = normalize_asr(content)
            if turn.get("content", "").strip():
                content_pos += 1
                turn["turn_idx"] = content_pos
            else:
                turn["turn_idx"] = None

    # -------------------------
    # Factory methods
    # -------------------------

    @classmethod
    def load(cls, path: str, zscore_threshold: float | None = None) -> Conversation:
        """Load from JSON file: ASR output (`transcribed_vads`) or plain `vads`."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "transcribed_vads" in data:
            vads = data["transcribed_vads"]
            if zscore_threshold is not None:
                vads = [v for v in vads if v.get("peak_db_zscore", 0) >= zscore_threshold]
            if not vads:
                import logging
                logging.getLogger(__name__).warning(
                    f"Conversation.load: {path} has empty transcribed_vads"
                )
            return cls(vads=vads, source_path=str(path))

        vads = data.get("vads", [])
        if not vads and "vads" not in data:
            import logging
            logging.getLogger(__name__).warning(
                f"Conversation.load: {path} has neither 'transcribed_vads' nor 'vads' — "
                f"returning empty Conversation, downstream cases will see no turns"
            )
        return cls(vads=vads, source_path=str(path))

    # -------------------------
    # Core methods
    # -------------------------

    def format(
        self,
        start: int = 0,
        end: int | None = None,
        cite_role: str | None = "agent",
    ) -> str:
        """Format conversation turns for LLM consumption.

        Lines are `[N] AGENT: ...` for the citable role and `[x] OTHER: ...`
        for the masked role. `N` is `turn["turn_idx"]`. Non-content vads
        are skipped. `start`/`end` slice the vads list before rendering.

        Args:
            cite_role: which role's turn_idx to expose. Any other role
                is masked as `[x]` so the LLM cannot cite by mistake.
                `None` exposes both roles (defence off — for debug only).
        """
        lines = []
        for turn in self.vads[start:end]:
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            role = (turn.get("role") or "").lower()
            label = "AGENT" if role == "agent" else "CUSTOMER"
            if cite_role is None or role == cite_role:
                idx = turn["turn_idx"]
                lines.append(f"[{idx}] {label}: {content}")
            else:
                lines.append(f"[x] {label}: {content}")
        return "\n".join(lines)

    def is_silent(self, role: str | None = None) -> bool:
        """True if no content-bearing turn matches the role (None → any)."""
        if role is not None and role not in ("customer", "agent"):
            raise ValueError(f"Invalid role: {role}")
        for turn in self.vads:
            if not (turn.get("content") or "").strip():
                continue
            if role is None or turn.get("role") == role:
                return False
        return True

    # -------------------------
    # Dunder methods
    # -------------------------

    def __len__(self) -> int:
        return len(self.vads)

    def __repr__(self) -> str:
        agent_n = sum(1 for v in self.vads if v.get("role") == "agent" and (v.get("content") or "").strip())
        customer_n = sum(1 for v in self.vads if v.get("role") == "customer" and (v.get("content") or "").strip())
        return f"Conversation(turns={len(self.vads)}, agent={agent_n}, customer={customer_n})"
