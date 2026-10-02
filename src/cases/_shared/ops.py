"""Reusable operonx ops shared across case graphs.

  - `exit_fn`             — emit a `{result: {...}}` terminal node
  - `format_fn`           — stringify the conversation + silent flags + n_turns
  - `expand_evidence_fn`  — validate LLM's `<evidence>` turn_idxs + expand
                            to display text; anti-hallucinate gate downgrades
                            violation=true+empty-idxs → violation=false
  - `is_decided`          — did an upstream layer already stamp a verdict
  - `parsed`              — stop the call when a model's reply did not parse
"""
from typing import Any, Dict, Optional

from operonx.core import op

from ...core.conversation import Conversation, format_mmss
from .spec import turn_idxs


def _coerce_violation(raw) -> bool:
    """Accept `True`, `"true"`, `"True "` — reject `False`, `"false"`, "" as false.

    XML parsers leave `<violation>true</violation>` as a string, and
    `bool("false")` is True in Python — explicit compare needed.
    """
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() == "true"
    return bool(raw)


@op
def parsed(error: Optional[str] = None) -> dict[str, Any]:
    """Raise when the model call before it could not parse its reply.

    A structured `LLMOp` reports a parse failure in `error` and hands on
    `None` for every field — and every router and verdict here reads `None`
    as "no": a clean call, or, where "missing" means a violation, a −100
    one. Raising fails the call instead, so it is recorded as `{"error"}`
    and never as a verdict nobody reached. Wired right after each model call.
    """
    if error:
        first = str(error).strip().splitlines()[0]
        raise ValueError(f"the model's reply did not parse: {first}")
    return {"ok": True}


@op
def exit_fn(
    reason: str = "",
    violation: bool = False,
    category: Optional[str] = None,
    evidence: Optional[str] = None,
    evidence_idxs: Optional[list[int]] = None,
    violation_probs: Optional[list[float]] = None,
    filter_meta: Optional[dict] = None,
    exit_stage: Optional[str] = None,
) -> dict[str, Any]:
    """Terminal node — emit a violation result.

    Args:
        reason: Explanation of the decision.
        violation: Whether there is a violation.
        category: Optional violation category.
        evidence: Optional pre-rendered evidence text ("[mm:ss]: content<br/>...").
        evidence_idxs: Optional validated turn_idx list (for qc-monitor UI).
        violation_probs: Optional list of violation probabilities.
        filter_meta: Optional pre-filter verdict trace (sentiment_agent's
            pre-filter, incl. shadow mode). Stashed under `_trace_meta["filter"]`.
        exit_stage: Which gate ended the graph here, recorded under
            `_trace_meta["exit"]`. Opt-in, so the cases that share this op
            are unaffected. Without it an early exit and a crashed scanner
            produce the same empty output — both score "Tích cực" with no
            trace of why, and a reviewer cannot tell "we deliberately did
            not judge this call" from "the judgement was lost".
    """
    result: dict[str, Any] = {"violation": violation, "reason": reason}
    if category is not None:
        result["category"] = category
    if evidence is not None:
        result["evidence"] = evidence
    if evidence_idxs is not None:
        result["evidence_idxs"] = evidence_idxs
    if violation_probs is not None:
        result["violation_probs"] = violation_probs
    if filter_meta is not None:
        result.setdefault("_trace_meta", {})["filter"] = filter_meta
    if exit_stage is not None:
        result.setdefault("_trace_meta", {})["exit"] = {
            "stage": exit_stage,
            "category": category or "",
            "reason": reason,
        }
    return {"result": result}


def has_exit_stamp(result: object) -> bool:
    """True when *result* is a verdict some terminal stamped on its way out.

    Every terminal writes `_trace_meta["exit"]`, so "has this call been
    decided?" is already written down and no new field is invented for it.

    `False` for anything that is not a dict, including `None`. A lost result
    is not a decided one — treating it as decided would route it past the
    stages that would have caught the loss and turn a transport failure
    into a clean verdict.
    """
    if not isinstance(result, dict):
        return False
    return bool((result.get("_trace_meta") or {}).get("exit"))


@op
def is_decided(result: dict = None) -> bool:
    """True when an upstream layer already ended the call. See `has_exit_stamp`."""
    return has_exit_stamp(result)


@op
def format_fn(
    conversation: Conversation,
    istart: int = 0,
    iend: Optional[int] = None,
    cite_role: str = "agent",
) -> Dict[str, Any]:
    """Stringify the conversation + emit gate flags used by case routers.

    Args:
        conversation: Conversation with VAD turns.
        istart: Starting index (supports negative indexing).
        iend: Ending index (supports negative indexing, defaults to None).
        cite_role: which role's turn_idx is exposed; the other is `[x]`
            masked. Default "agent" — 4/5 HVC cases cite agent turns.
            Set "customer" for sentiment_customer.

    Returns:
        - content: Formatted "[N] ROLE: text" string.
        - agent_silent: True if no agent content turns.
        - customer_silent: True if no customer content turns.
        - n_turns: Total VAD count (incl. empty turns).
    """
    return {
        "content": conversation.format(start=istart, end=iend, cite_role=cite_role),
        "agent_silent": conversation.is_silent(role="agent"),
        "customer_silent": conversation.is_silent(role="customer"),
        "n_turns": len(conversation.vads),
    }


def _build_turn_map(conversation: Conversation, role: str) -> dict[int, dict]:
    """turn_idx → vad dict for the given role, from the canonical turn_idx
    assigned at Conversation load."""
    if conversation is None:
        return {}
    out: dict[int, dict] = {}
    for turn in conversation.vads:
        if turn.get("turn_idx") is None:
            continue
        if (turn.get("role") or "").lower() != role:
            continue
        out[int(turn["turn_idx"])] = turn
    return out


@op
def expand_evidence_fn(
    llm_result: dict = None,
    conversation: Conversation = None,
    role: str = "agent",
) -> dict[str, Any]:
    """Validate LLM `<evidence>` turn_idxs; expand to display text.

    Hard anti-hallucinate gate: any idx not in the target-role turn map is
    dropped. If `violation=true` but the cleaned list is empty → downgrade
    to `violation=false` with `drop_reason=empty_evidence_after_validation`.

    Mutates `llm_result`:
      - `evidence` → "[mm:ss]: content<br/>[mm:ss]: content2"
      - `evidence_idxs` → validated int list

    Args:
        role: which role's turn_idxs the LLM was allowed to cite. Should
            match the `cite_role` passed to `format_fn` for this case.
    """
    if not isinstance(llm_result, dict):
        return {"result": llm_result}
    out = dict(llm_result)

    turn_map = _build_turn_map(conversation, role)
    requested = turn_idxs(out.get("evidence"))
    valid = [i for i in requested if i in turn_map]

    lines = []
    for idx in valid:
        t = turn_map[idx]
        ts = format_mmss(t.get("start") or 0.0)
        lines.append(f"[{ts}]: {(t.get('content') or '').strip()}")
    out["evidence"] = "<br/>".join(lines)
    out["evidence_idxs"] = valid

    if _coerce_violation(out.get("violation")) and not valid:
        out["violation"] = "false"
        out["category"] = "none"
        out["drop_reason"] = "empty_evidence_after_validation"

    return {"result": out}
