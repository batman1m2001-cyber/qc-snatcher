"""The turns around a flagged one — shared by the layer that finds evidence
and the layer that judges it.

`l2_scanner` builds this window to show a decider what surrounded the turn
the scanner cited; `l3_decider` builds it again for the ASR-check route.
Both did, before the four-layer split: the window table and its two helpers
lived once in `_matcher.py`, and splitting that file left `l3` holding
verbatim copies of the functions without the table they read, and `l2`
holding neither.

Six `NameError`s shipped that way and none of them failed a test, because
`tests/_replay.py` stubs op *cores* — so a body that would raise on its
first line is never entered. What surfaced instead was five identical
`[llm timeout]` lines: the decider was reached with empty evidence, sent a
4,211-character prompt on every call regardless of transcript, and the
model stalled on a question with nothing in it.

So this module exists to be imported twice rather than copied twice.
"""
from __future__ import annotations

from ...core.conversation import Conversation

__all__ = [
    "SKIP_MATCHER_CODES",
    "build_verifier_context",
    "window_for",
]

#: Scanner-assigned codes that mean "there is nothing here to verify", so
#: no verifier is asked and no retrieval is paid for.
SKIP_MATCHER_CODES = {"none", ""}

#: Per-category context window, `(before, after)` in turns. Categories that
#: turn on a build-up need more history than ones that turn on a single
#: sentence.
_WINDOW_BY_CODE: dict[str, tuple[int, int]] = {
    "C8": (20, 5),
    "C11": (15, 5),
    "N1": (20, 5),
}
_DEFAULT_WINDOW: tuple[int, int] = (10, 2)


def window_for(code: str) -> tuple[int, int]:
    """`(before, after)` for a scanner category, defaulting for unknown ones."""
    return _WINDOW_BY_CODE.get(code, _DEFAULT_WINDOW)


def build_verifier_context(
    conversation: Conversation,
    evidence_idxs: list[int],
    before: int = 10,
    after: int = 2,
) -> str:
    """Pull one or more windows of turns around the flagged evidence.

    Builds a `(pos - before, pos + after + 1)` window around EACH evidence
    turn, then merges overlapping windows. Non-adjacent windows are
    separated by a single `...` line so the LLM can tell that two target
    turns are far apart in the call (not adjacent chunks of the same
    context).
    """
    if not evidence_idxs or conversation is None:
        return ""
    flat = [
        (
            (t.get("role") or "").upper(),
            (t.get("content") or "").strip(),
            int(t["turn_idx"]),
        )
        for t in (conversation.vads or [])
        if t.get("turn_idx") is not None
    ]
    if not flat:
        return ""
    ev_set = {int(i) for i in evidence_idxs}
    ev_positions = sorted({i for i, (_, _, ti) in enumerate(flat) if ti in ev_set})
    if not ev_positions:
        return ""
    ranges: list[tuple[int, int]] = []
    for pos in ev_positions:
        lo = max(0, pos - before)
        hi = min(len(flat), pos + after + 1)
        if ranges and lo <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], hi))
        else:
            ranges.append((lo, hi))
    ev_positions_set = set(ev_positions)
    blocks: list[list[str]] = []
    for lo, hi in ranges:
        block: list[str] = []
        for pos in range(lo, hi):
            role, content, ti = flat[pos]
            marker = " <<<" if pos in ev_positions_set else ""
            if role == "AGENT":
                block.append(f"[{ti}] AGENT: {content}{marker}")
            elif role == "CUSTOMER":
                block.append(f"[x] CUSTOMER: {content}{marker}")
            else:
                block.append(f"[{ti}] {role or '?'}: {content}{marker}")
        blocks.append(block)
    return "\n...\n".join("\n".join(b) for b in blocks)
