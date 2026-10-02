"""Layer 2 ops — the scanner's evidence, checked before anyone trusts it.

The scanner names a turn and quotes it. Three things then happen before a
decider is asked anything, and each can end the call:

* `remap_evidence_fn` — if the quoted phrase is not in the cited turn,
  search every agent turn for it and correct the index. Regex and
  substring; no model.
* `attr_check_fn` — every substantial quote must actually appear in the
  agent's text at those indices. One fabricated quote routes to the halu
  check, even when the others are genuine.
* `halu_suppress_fn` — the halu check agreed the citation was invented, so
  the verdict is dropped.

`needs_matcher_fn` / `skip_matcher_fn` then decide whether a verifier is
worth asking at all: a cleared scanner or a category with no matchable
rule ends here rather than paying for retrieval.

Moved verbatim from `_matcher.py`.
"""
from __future__ import annotations

import re
from typing import Any

from operonx.core import op

from ....core.conversation import Conversation, format_mmss
from ..._shared.ops import _coerce_violation
from ..._shared.spec import turn_idxs
from .._context import SKIP_MATCHER_CODES, build_verifier_context, window_for
from .._trace import _normalize_vn, _plain_evidence, _scanner_trace

_ATTR_MIN_WORDS = 3


@op
def attr_check_fn(
    llm_result: dict = None,
    conversation: Conversation = None,
) -> dict[str, Any]:
    """Deterministic substring check for scanner attribution.

    Extracts quoted phrases from `reason`, normalizes, and searches inside
    the AGENT text at `evidence_idxs`. EVERY substantial quote (>=
    `_ATTR_MIN_WORDS` words) must be a substring — one fabricated quote is
    enough to route through halu_check, even when the other quotes are
    genuine. Short fragments are skipped: the scanner routinely uses 1-2
    word snippets as its own paraphrase, not as verbatim citation.

    Returns `attribution_ok=True` when there is nothing to verify (no
    quotes, no evidence idxs, no agent turn at those idxs).
    """
    if not isinstance(llm_result, dict):
        return {"attribution_ok": True}
    reason = llm_result.get("reason") or ""
    quoted = re.findall(r"'([^']+)'", reason)
    if not quoted:
        return {"attribution_ok": True}
    idxs = set(turn_idxs(llm_result.get("evidence_idxs")))
    if not idxs or conversation is None:
        return {"attribution_ok": True}
    agent_texts = [
        (t.get("content") or "")
        for t in (conversation.vads or [])
        if t.get("turn_idx") is not None
        and int(t["turn_idx"]) in idxs
        and (t.get("role") or "").lower() == "agent"
    ]
    if not agent_texts:
        return {"attribution_ok": True}
    agent_norm = _normalize_vn(" ".join(agent_texts))
    for phrase in quoted:
        p_norm = _normalize_vn(phrase)
        if not p_norm or len(p_norm.split()) < _ATTR_MIN_WORDS:
            continue
        if p_norm not in agent_norm:
            return {"attribution_ok": False}
    # No substantial quote to verify — nothing to attribute, let it through.
    return {"attribution_ok": True}


@op
def build_halu_check_inputs_fn(
    llm_result: dict = None,
    conversation: Conversation = None,
) -> dict[str, Any]:
    """Compose {evidence, scanner_reason, context} for the halu_check prompt."""
    if not isinstance(llm_result, dict):
        return {"evidence": "", "scanner_reason": "", "context": ""}
    _, evidence_display = _plain_evidence(llm_result.get("evidence"))
    scanner_reason = (llm_result.get("reason") or "").strip()
    cat = (llm_result.get("category") or "").strip() or "none"
    before, after = window_for(cat)
    context = build_verifier_context(conversation, turn_idxs(llm_result.get("evidence_idxs")),
                                     before=before, after=after)
    return {
        "evidence": evidence_display,
        "scanner_reason": scanner_reason,
        "context": context,
    }


@op
def is_halu_fn(result: dict = None) -> bool:
    """True when halu_check says the scanner cited something not said.

    Same string/bool tolerance as every other verdict off an LLM parser:
    `bool("false")` is True in Python, so the compare has to be explicit.
    """
    if not isinstance(result, dict):
        return False
    return _coerce_violation(result.get("hallucinated"))


@op
def halu_suppress_fn(
    llm_result: dict = None,
    halu_result: dict = None,
    filter_meta: dict = None,
) -> dict[str, Any]:
    """Suppress scanner verdict when halu_check flags misattribution/hallucination."""
    if not isinstance(llm_result, dict):
        return {"result": llm_result}
    scanner_trace = _scanner_trace(llm_result)
    out = dict(llm_result)
    out["original_category"] = out.get("category")
    out["violation"] = "false"
    out["category"] = "none"
    reason = ""
    if isinstance(halu_result, dict):
        reason = (halu_result.get("reason") or "")[:200]
    out["drop_reason"] = f"halu_suppress: {reason}"
    trace_meta: dict[str, Any] = {
        "scanner":    scanner_trace,
        "halu_check": {"verdict": True, "reason": reason},
        # A terminal, so it says so. The row it produces is clean, and a
        # clean row with no exit stamp reads as "never judged".
        "exit": {
            "stage": "halu",
            "category": scanner_trace.get("category_raw") or "",
            "reason": reason,
        },
    }
    if filter_meta is not None:
        trace_meta["filter"] = filter_meta
    out["_trace_meta"] = trace_meta
    return {"result": out}


@op
def remap_evidence_fn(
    llm_result: dict = None,
    conversation: Conversation = None,
) -> dict[str, Any]:
    """Correct scanner's evidence_idxs when the quoted violation phrase is
    NOT in the cited AGENT turn(s).

    Scanner sometimes picks the wrong turn_idx between two adjacent AGENT
    turns — reason quotes phrase X from turn 68, but returns evidence_idxs
    = [72] (a benign nearby turn). Downstream matcher then sees a trivial
    turn and can't cite anything → false negative.

    Fix: for each quoted phrase in `reason` that isn't found in the cited
    turn(s), search ALL AGENT turns for that phrase (VN-normalized
    substring). Pick the match closest to the current evidence_idxs
    anchor. Rebuild `evidence` display string from the updated idxs.

    If a phrase can't be found in ANY AGENT turn → leave unchanged. The
    downstream `attr_check` will still catch the mismatch and route to
    `halu_check` for LLM adjudication.
    """
    if not isinstance(llm_result, dict):
        return {"result": llm_result}
    if not _coerce_violation(llm_result.get("violation")):
        return {"result": llm_result}

    reason = llm_result.get("reason") or ""
    quoted = re.findall(r"'([^']+)'", reason)
    if not quoted:
        return {"result": llm_result}

    cur_idxs = list(llm_result.get("evidence_idxs") or [])

    # Build AGENT turn map: turn_idx → (content, start_seconds)
    agent_turns: dict[int, tuple[str, float]] = {}
    for t in (conversation.vads or []):
        if t.get("turn_idx") is None:
            continue
        if (t.get("role") or "").lower() != "agent":
            continue
        idx = int(t["turn_idx"])
        content = (t.get("content") or "").strip()
        agent_turns[idx] = (content, float(t.get("start") or 0.0))

    if not agent_turns:
        return {"result": llm_result}

    # Which quoted phrases are already covered by current evidence_idxs?
    cur_norm = _normalize_vn(
        " ".join(agent_turns.get(i, ("", 0.0))[0] for i in cur_idxs)
    )
    missing = [
        q for q in quoted
        if _normalize_vn(q) and _normalize_vn(q) not in cur_norm
    ]
    if not missing:
        return {"result": llm_result}

    # Search all AGENT turns for each missing phrase; pick match closest to
    # current evidence_idxs anchor.
    anchor = sum(cur_idxs) / len(cur_idxs) if cur_idxs else 0

    def _nearest_match(phrase_norm: str) -> int | None:
        matches = [
            idx for idx, (content, _) in agent_turns.items()
            if phrase_norm in _normalize_vn(content)
        ]
        if not matches:
            return None
        return min(matches, key=lambda i: abs(i - anchor))

    new_idxs = set(cur_idxs)
    remap_notes: list[str] = []
    for phrase in missing:
        pn = _normalize_vn(phrase)
        if not pn:
            continue
        found = _nearest_match(pn)
        if found is None:
            continue
        if found not in new_idxs:
            new_idxs.add(found)
            remap_notes.append(f"'{phrase[:40]}' → turn[{found}]")

    if new_idxs == set(cur_idxs):
        return {"result": llm_result}

    # Rebuild evidence display string from updated idxs.
    sorted_idxs = sorted(new_idxs)
    lines = []
    for idx in sorted_idxs:
        content, start = agent_turns.get(idx, ("", 0.0))
        ts = format_mmss(start)
        lines.append(f"[{ts}]: {content}")

    out = dict(llm_result)
    out["evidence"] = "<br/>".join(lines)
    out["evidence_idxs"] = sorted_idxs
    out["remap_note"] = "; ".join(remap_notes)
    return {"result": out}


@op
def needs_matcher_fn(llm_result: dict = None) -> dict[str, Any]:
    """True if scanner flagged a violation with a category that has matchable rules."""
    if not isinstance(llm_result, dict):
        return {"needs_verify": False}
    if not _coerce_violation(llm_result.get("violation")):
        return {"needs_verify": False}
    cat = (llm_result.get("category") or "").strip()
    if cat in SKIP_MATCHER_CODES:
        return {"needs_verify": False}
    return {"needs_verify": True}


@op
def skip_matcher_fn(
    llm_result: dict = None,
    filter_meta: dict = None,
) -> dict[str, Any]:
    """Terminal for a call the scanner cleared, or one with no matchable rule.

    Stamps `_trace_meta["exit"]` like every other terminal. Without it a
    reviewer cannot tell "the verifier was deliberately not asked" from
    "the verifier was asked and something went wrong" — the two produce the
    same clean row, and only one of them is fine.
    """
    if not isinstance(llm_result, dict):
        return {"result": llm_result}
    out = dict(llm_result)
    trace_meta = dict(out.get("_trace_meta") or {})
    if filter_meta is not None:
        trace_meta["filter"] = filter_meta
    # The scanner ran and cleared the call. Record that verdict — without it
    # a clean call is indistinguishable from one the scanner never reached.
    trace_meta["scanner"] = _scanner_trace(llm_result)
    trace_meta["exit"] = {
        "stage": "no_violation",
        "category": (llm_result.get("category") or "").strip(),
        "reason": "scanner cleared, or category has no matchable rule",
    }
    out["_trace_meta"] = trace_meta
    return {"result": out}


@op
def proceed_fn(llm_result: dict = None, filter_meta: dict = None) -> dict:
    """Evidence held up — hand the verdict on to be judged.

    `result: None` means "not decided here", and layer 3 is what decides
    it. `llm_result` is the scanner verdict after remapping, which is the
    thing every stage downstream actually reads.
    """
    return {"result": None, "llm_result": llm_result, "filter_meta": filter_meta}
