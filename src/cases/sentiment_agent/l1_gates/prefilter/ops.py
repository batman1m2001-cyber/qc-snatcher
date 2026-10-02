"""Pre-filter ops — dispatch, the pass-through exits, chunking and aggregation.

`dispatch_fn` picks one route: both filters off, keyword hit, LLM scan, or
keyword miss with the LLM off. The LLM route chunks the transcript
(`CHUNK` turns, `OVERLAP` overlap) and ORs the per-chunk verdicts.
`apply_filter_gate_fn` then decides whether a clean result blocks the call
(gate mode) or is only recorded (shadow mode).
"""
from __future__ import annotations

import json
from typing import Any

from operonx.core import op

from .....core.config import filter_apply_enabled, filter_keyword_enabled, filter_llm_enabled
from .....core.conversation import Conversation
from ._keyword_filter import concat_agent_text, has_hit

# The chunking the standalone scan was validated with on live_20260629.
CHUNK = 100


OVERLAP = 10


FILTER_CHUNK_WORKERS = 2


# Semantic reasons emitted at graph output.
REASON_NO_CHUNKS = "filter_no_chunks"


REASON_PARSE_ERROR = "filter_parse_error"


REASON_FLAGGED = "filter_llm_flagged"


REASON_CLEAN = "filter_llm_clean"


REASON_DISABLED = "filter_disabled"        # both LLM + KW disabled


REASON_KW_HIT = "filter_kw_hit"            # keyword filter caught it


REASON_KW_MISS_CLEAN = "filter_kw_miss_clean"  # KW miss + LLM disabled


# Route tokens emitted by dispatch_fn (single-dispatcher wiring).
ROUTE_DISABLED = "disabled_pass"


ROUTE_KW_HIT = "kw_hit_pass"


ROUTE_LLM_SCAN = "llm_scan"


ROUTE_KW_CLEAN = "kw_clean_pass"


def _fmt_turn(t: dict) -> str:
    """`[N] AGENT: text` for agent turns, `[x] CUSTOMER: text` for others."""
    is_agent = (t.get("role") or "").lower() == "agent"
    idx = t["turn_idx"] if is_agent else "x"
    role_label = "AGENT" if is_agent else "CUSTOMER"
    return f"[{idx}] {role_label}: {(t.get('content') or '').strip()}"


def _chunk_content_turns(turns: list[dict]) -> list[list[dict]]:
    """Sliding CHUNK-turn window with OVERLAP; only content-bearing turns."""
    contentful = [t for t in turns if (t.get("content") or "").strip()]
    if not contentful:
        return []
    if len(contentful) <= CHUNK:
        return [contentful]
    out: list[list[dict]] = []
    s = 0
    while s < len(contentful):
        out.append(contentful[s : s + CHUNK])
        if s + CHUNK >= len(contentful):
            break
        s += CHUNK - OVERLAP
    return out


def _prepare_filter_chunks(conversation: Conversation) -> dict:
    """Convert Conversation → parallel lists of transcripts + turn ranges."""
    turns = list(conversation.vads) if conversation else []
    chunks = _chunk_content_turns(turns)
    return {
        "transcripts": ["\n".join(_fmt_turn(t) for t in ch) for ch in chunks],
        "turn_ranges": [
            [ch[0]["turn_idx"], ch[-1]["turn_idx"]] for ch in chunks
        ],
    }


def _parse_violation(raw: Any) -> bool | None:
    """Parse LLM output → True / False / None (unparseable)."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        if isinstance(raw.get("result"), dict):
            v = raw["result"].get("violation")
        else:
            v = raw.get("violation")
    elif isinstance(raw, str):
        if not raw.strip() or raw.startswith("<ERROR"):
            return None
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            return None
        r = d.get("result") if isinstance(d.get("result"), dict) else d
        v = r.get("violation") if isinstance(r, dict) else None
    else:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() == "true"
    return None


def _aggregate_llm_verdict(chunk_raws: list | None) -> bool | None:
    """OR across LLM chunk results.

      - any chunk True  → True
      - all False       → False
      - all unparseable → None (caller decides fail-open policy)
      - empty list      → None (nothing scanned)
    """
    if not chunk_raws:
        return None
    parsed = [_parse_violation(r) for r in chunk_raws]
    if all(v is None for v in parsed):
        return None
    if any(v is True for v in parsed):
        return True
    return False


@op
def each_chunk(transcripts: list = None):
    """Yield one frame per chunk — this is what fans the scan out.

    Deliberately NOT `@op(transient=True)`. Transient releases a frame as
    soon as it is consumed, and `.collect()` refuses such a source: there
    would be nothing left to buffer. Transience is for a stream that must
    not be retained — a call's worth of audio packets. A handful of
    transcript chunks is the opposite case.
    """
    for transcript in transcripts or []:
        yield {"transcript": transcript}


def _check_keyword_hit(conversation: Conversation | None) -> bool:
    """Deterministic keyword substring match on agent-only concat text.

    Returns False if the keyword filter is disabled OR the conversation
    has no agent content (short-circuit avoids any regex work).
    """
    if not filter_keyword_enabled() or conversation is None:
        return False
    return has_hit(concat_agent_text(conversation.vads or []))


@op
def dispatch_fn(conversation: Conversation) -> dict:
    """Single-shot toggle + keyword read → routing decision + trace flags.

    Collapses the old `check_toggles_fn` + `check_keyword_hit_fn` +
    2-tier `if_()` chain into one op. Env is read fresh so tests + hot
    reload keep working.
    """
    llm_on = filter_llm_enabled()
    kw_on = filter_keyword_enabled()
    if not (llm_on or kw_on):
        return {"route": ROUTE_DISABLED, "kw_hit": False}
    kw_hit = _check_keyword_hit(conversation) if kw_on else False
    if kw_hit:
        return {"route": ROUTE_KW_HIT, "kw_hit": True}
    if llm_on:
        return {"route": ROUTE_LLM_SCAN, "kw_hit": False}
    return {"route": ROUTE_KW_CLEAN, "kw_hit": False}


@op
def disabled_pass_fn() -> dict:
    """Neither filter enabled → pass-through (scanner runs on everything)."""
    return {
        "should_scan": True,
        "reason": REASON_DISABLED,
        "kw_hit": False,
        "llm_verdict": None,
    }


@op
def kw_hit_pass_fn() -> dict:
    """Keyword filter hit → short-circuit past the LLM branch."""
    return {
        "should_scan": True,
        "reason": REASON_KW_HIT,
        "kw_hit": True,
        "llm_verdict": None,
    }


@op
def no_chunks_pass_fn() -> dict:
    """Nothing to scan — a conversation with no content turns.

    `MapOp` used to reach the aggregator with an empty list and let it
    decide. A generator cannot: yielding nothing dispatches nothing, so
    the aggregator's own empty-input branch became unreachable. The
    decision moves into the graph, where it is also easier to see.
    """
    return {
        "should_scan": False,
        "reason": REASON_NO_CHUNKS,
        "kw_hit": False,
        "llm_verdict": None,
    }


@op
def kw_clean_pass_fn() -> dict:
    """KW miss and LLM filter disabled → trust KW's negative signal."""
    return {
        "should_scan": False,
        "reason": REASON_KW_MISS_CLEAN,
        "kw_hit": False,
        "llm_verdict": None,
    }


@op
def prepare_filter_chunks_fn(conversation: Conversation) -> dict:
    """The chunk transcripts, their turn ranges, and how many there are —
    `n_chunks` is what the graph routes a call with nothing to scan on."""
    prep = _prepare_filter_chunks(conversation)
    return {
        "transcripts": prep["transcripts"],
        "turn_ranges": prep["turn_ranges"],
        "n_chunks": len(prep["transcripts"]),
    }


@op
def aggregate_llm_result_fn(chunk_raws: list = None) -> dict:
    """Turn the collected chunk results into the 4-field contract.

    The empty case is handled upstream by `no_chunks_pass_fn` — a
    generator that yields nothing never reaches here — but the branch
    stays as a guard, since a collect that somehow flushes empty must
    still produce the contract rather than a half-filled row.
    """
    llm_verdict = _aggregate_llm_verdict(chunk_raws)
    if not chunk_raws:
        return {
            "should_scan": False,
            "reason": REASON_NO_CHUNKS,
            "kw_hit": False,
            "llm_verdict": None,
        }
    if llm_verdict is None:
        # every chunk unparseable → fail-open, prefer wasted scanner tokens
        # over silent recall loss.
        return {
            "should_scan": True,
            "reason": REASON_PARSE_ERROR,
            "kw_hit": False,
            "llm_verdict": None,
        }
    if llm_verdict:
        return {
            "should_scan": True,
            "reason": REASON_FLAGGED,
            "kw_hit": False,
            "llm_verdict": True,
        }
    return {
        "should_scan": False,
        "reason": REASON_CLEAN,
        "kw_hit": False,
        "llm_verdict": False,
    }


@op
def apply_filter_gate_fn(
    should_scan: bool = True,
    reason: str = "",
    kw_hit: bool = False,
    llm_verdict: bool = None,
) -> dict:
    """Decide whether filter verdict blocks the main flow.

    Reads `SENTIMENT_FILTER_APPLY` fresh per call:
      - apply=true + should_scan=false → gate=block  (short-circuit to filter_exit)
      - apply=true + should_scan=true  → gate=pass
      - apply=false (shadow mode)      → gate=pass ALWAYS, meta rides on result

    Filter subgraph fields are threaded as individual kwargs — Operon only
    propagates explicitly-subscripted outputs (`filter_node["field"]`);
    passing the subgraph reference bare gives an OpRef, not a dict.

    `filter_meta` carries the subgraph output + an `applied` bool so
    downstream eval can tell shadow verdicts from real gate verdicts.
    """
    applied = filter_apply_enabled()
    scan = bool(should_scan) if isinstance(should_scan, bool) else True
    gate = "block" if (applied and not scan) else "pass"
    meta = {
        "should_scan": scan,
        "reason": reason or "",
        "kw_hit": bool(kw_hit),
        "llm_verdict": llm_verdict,
        "applied": applied,
    }
    return {"gate": gate, "filter_meta": meta}
