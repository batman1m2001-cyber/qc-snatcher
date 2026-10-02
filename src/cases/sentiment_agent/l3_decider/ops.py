"""Layer 3 ops — the filter decider and the ASR-check route.

Filter decider route:

  1. `build_retrieval_query_fn` picks the text to retrieve on; the graph's
     `retrieve_corpus` returns top-K positives + top-K carveouts.
  2. `build_matcher_inputs_fn` renders them as ``[P1..PK]`` / ``[C1..CK]``
     pools with ``sample:`` / ``description:`` labels — a loose reference,
     the model is not bound to match them verbatim.
  3. One LLM call sees evidence + context + both pools and outputs
     ``{violation, reason, cited_positives, cited_carveouts}``. The
     citations are for audit; the verdict is the model's holistic call.
  4. `apply_decider_result_fn` keeps or drops the scanner's verdict.

ASR-check route: `route_check_fn` sends heavy-keyword turns to a
tone-continuity check instead (see the section at the bottom).
"""

from __future__ import annotations

import re
from typing import Any

from operonx.core import op

from ....core.conversation import Conversation
from ..._shared.spec import is_true, turn_idxs
from .._context import build_verifier_context, window_for
from .._pools import (
    _format_indexed_pool,
    _parse_cited,
    pool_id_map,
    remap_cited,
)
from .._trace import _plain_evidence, _scanner_trace, evidence_query

# ---- ASR-check verdict -----------------------------------------------------


@op
def apply_asr_check_result_fn(
    llm_result: dict = None,
    verify_out: dict = None,
    asr_check_resource: str = None,
    filter_meta: dict = None,
) -> dict[str, Any]:
    """Apply the ASR-check verdict — suppress the scanner's flag if keep=false.

    Heavy-keyword route only (see `_HEAVY_KW_PATTERNS`). Malformed output
    keeps the flag.
    """
    if not isinstance(llm_result, dict):
        return {"result": llm_result}
    # Snapshot scanner-side fields even when verify_out is malformed, so the
    # trace still shows what got flagged.
    scanner_trace = _scanner_trace(llm_result)
    if not isinstance(verify_out, dict):
        out = dict(llm_result)
        trace_meta: dict[str, Any] = {
            "scanner":   scanner_trace,
            "asr_check": {"verdict": None, "reason": "", "resource": asr_check_resource or "", "malformed": True},
        }
        if filter_meta is not None:
            trace_meta["filter"] = filter_meta
        out["_trace_meta"] = trace_meta
        return {"result": out}
    keep_raw = verify_out.get("keep")
    if isinstance(keep_raw, bool):
        keep = keep_raw
    elif isinstance(keep_raw, str):
        keep = keep_raw.strip().lower() != "false"
    else:
        keep = True
    reason = (verify_out.get("reason") or "")[:200]
    if keep:
        out = dict(llm_result)
    else:
        out = dict(llm_result)
        out["original_category"] = out.get("category")
        out["violation"] = "false"
        out["category"] = "none"
        out["drop_reason"] = f"asr_check_suppress: {reason}"
    trace_meta = {
        "scanner":   scanner_trace,
        "asr_check": {"verdict": keep, "reason": reason, "resource": asr_check_resource or ""},
    }
    if filter_meta is not None:
        trace_meta["filter"] = filter_meta
    out["_trace_meta"] = trace_meta
    return {"result": out}


# ---- inputs ---------------------------------------------------------------


@op
def build_retrieval_query_fn(llm_result: dict = None) -> dict[str, Any]:
    """Scanner result -> the text to retrieve on: the evidence turn.

    Not the phrase the scanner quoted in its reason. The quote is shorter
    (~9 words vs ~25) but it is LLM prose: on round 3, 68 of 235 calls had
    byte-identical evidence and a different quote, and each retrieved a
    different pool (mean Jaccard 0.31). The evidence retrieved identically
    30/30 on those pairs, pools no smaller, F1 against QC unchanged (0.592
    vs 0.594). l4 queries with the same text — see `evidence_query`.
    A separate op so retrieval is a traced graph edge.

    Empty query is legitimate and means "skip retrieval": the pools are
    then empty and the decider judges on evidence + context alone.
    """
    return {"query": evidence_query(llm_result)}


@op
def build_matcher_inputs_fn(
    llm_result: dict = None,
    conversation: Conversation = None,
    positives: list = None,
    carveouts: list = None,
) -> dict[str, Any]:
    """Compose the decider's inputs from the scanner result + retrieved pools.

    `positives` / `carveouts` arrive as a graph edge from `retrieve_corpus`
    rather than being fetched here, so the retrieval hop is traced.

    Returns the shared context (``evidence`` / ``scanner_reason`` /
    ``context``), the formatted pool strings ``positives_indexed`` /
    ``carveouts_indexed``, and the raw ``positives_items`` /
    ``carveouts_items`` that `apply_decider_result_fn` uses to map cited
    slots back to corpus ids for the trace.
    """
    if not isinstance(llm_result, dict):
        return {
            "code": "none",
            "evidence": "",
            "scanner_reason": "",
            "context": "",
            "positives_indexed": "",
            "carveouts_indexed": "",
            "positives_items": [],
            "carveouts_items": [],
        }

    cat = (llm_result.get("category") or "").strip() or "none"
    _, evidence_display = _plain_evidence(llm_result.get("evidence"))
    scanner_reason = (llm_result.get("reason") or "").strip()

    before, after = window_for(cat)
    context = build_verifier_context(conversation, turn_idxs(llm_result.get("evidence_idxs")),
                                     before=before, after=after)

    pos_str, pos_items = _format_indexed_pool(positives or [], "P")
    neg_str, neg_items = _format_indexed_pool(carveouts or [], "C")

    return {
        "code": cat,
        "evidence": evidence_display,
        "scanner_reason": scanner_reason,
        "context": context,
        "positives_indexed": pos_str,
        "carveouts_indexed": neg_str,
        "positives_items": pos_items,
        "carveouts_items": neg_items,
    }


# ---- apply verdict --------------------------------------------------------


def _drop(llm_result: dict, drop_reason: str) -> dict[str, Any]:
    out = dict(llm_result)
    out["original_category"] = out.get("category")
    out["violation"] = "false"
    out["category"] = "none"
    out["drop_reason"] = drop_reason
    return out


def _slim_retrieval_items(items: list) -> list[dict]:
    """Reduce retrieval items to {id, content, description, severity}.

    `id` is the corpus entry uuid, and it is here so a pool the decider was
    shown can be tied back to `corpus.yaml` — without it the trace shows the
    text that was retrieved but not which entry it came from, and the two
    stop being the same question the moment QC edits a phrasing.
    """
    out = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "id":          it.get("entry_id") or it.get("parent_id") or "",
            "content":     it.get("text") or "",
            "description": it.get("description") or "",
            "severity":    it.get("severity") or "",
        })
    return out


@op
def apply_decider_result_fn(
    llm_result: dict = None,
    decider_out: dict = None,
    positives_items: list = None,
    carveouts_items: list = None,
    decider_resource: str = None,
    filter_meta: dict = None,
) -> dict[str, Any]:
    """Apply the filter decider's verdict and attach `matcher_debug` for audit.

    Reads ``decider_out.violation`` (bool):
      - true → keep the scanner's verdict (category preserved)
      - false → suppress (violation=false, category=none, drop_reason set)

    Malformed output drops with drop_reason=decider_malformed: a violation
    must be certain ("vi phạm cần chắc chắn").

    Cited samples (``cited_positives`` / ``cited_carveouts``) are stored in
    ``matcher_debug`` for root-cause analysis — they do not bind the decision.

    ``positives_items`` / ``carveouts_items`` are optional; when given they
    go into ``_trace_meta.retrieval`` for the QC UI to render beside the
    decider's cited ids.
    """
    if not isinstance(llm_result, dict):
        return {"result": llm_result}

    # Snapshot scanner-side fields BEFORE any drop, so the trace shows what
    # the scanner flagged even when the decider suppressed it.
    scanner_trace = _scanner_trace(llm_result)

    retrieval_trace = {
        "top_k":     len(positives_items or []),
        "positives": _slim_retrieval_items(positives_items or []),
        "carveouts": _slim_retrieval_items(carveouts_items or []),
    }

    if not isinstance(decider_out, dict):
        out = _drop(llm_result, "decider_malformed")
        out["matcher_debug"] = {
            "cited_positives": [],
            "cited_carveouts": [],
            "reasoning": "",
            "decider_violation": None,
        }
        trace_meta: dict[str, Any] = {
            "scanner":    scanner_trace,
            "retrieval":  retrieval_trace,
            "decider":    {
                "verdict":         None,
                "reason":          "",
                "cited_positives": [],
                "cited_carveouts": [],
                "resource":        decider_resource or "",
                "malformed":       True,
            },
        }
        if filter_meta is not None:
            trace_meta["filter"] = filter_meta
        out["_trace_meta"] = trace_meta
        return {"result": out}

    keep = is_true(decider_out.get("violation"))
    cited_p = _parse_cited(decider_out.get("cited_positives"), "P")
    cited_c = _parse_cited(decider_out.get("cited_carveouts"), "C")
    reason = (decider_out.get("reason") or "")[:300]

    if keep:
        out = dict(llm_result)
    else:
        summary = f"cited_c={cited_c or '[]'} cited_p={cited_p or '[]'}: {reason}"
        out = _drop(llm_result, f"decider_drop [{summary}]")

    out["matcher_debug"] = {
        "cited_positives": cited_p,
        "cited_carveouts": cited_c,
        "reasoning": reason,
        "decider_violation": keep,
    }
    pool_map = pool_id_map(positives_items, carveouts_items)
    trace_meta = {
        "scanner":    scanner_trace,
        "retrieval":  retrieval_trace,
        "decider":    {
            "verdict":         keep,
            "reason":          reason,
            # Corpus entry ids, not the `P1`/`C2` slots the model cited.
            # `pool_map` is what translated them, and inverting it recovers
            # exactly what the model said.
            "cited_positives": remap_cited(cited_p, pool_map),
            "cited_carveouts": remap_cited(cited_c, pool_map),
            "pool_map":        pool_map,
            "resource":        decider_resource or "",
        },
    }
    if filter_meta is not None:
        trace_meta["filter"] = filter_meta
    out["_trace_meta"] = trace_meta
    return {"result": out}


# ---- scanner validator -----------------------------------------------------


def _verify_result_ok(parsed: dict) -> bool:
    """Validator for the scanner LLMOp: a `result` dict with a `violation` key."""
    result = parsed.get("result")
    return isinstance(result, dict) and "violation" in result


# ---- ASR-check route -------------------------------------------------------
#
# Rule-based router. If the scanner's evidence contains an ASR-flip-risk
# keyword (`_HEAVY_KW_PATTERNS`), the turn goes to the ASR-check verifier
# instead of the filter decider. A benign word ("máy", "tôi", "còn nợ") is
# often transcribed as one of these, and corpus retrieval cannot tell the
# two apart — a tone-continuity check on ±2 turns can.
#
# The ASR-check verdict is final for those turns; the filter decider is
# skipped.

# Case-insensitive whole-word patterns. Order matters only for logging
# (first match wins as the "keyword" reported to the prompt).
_HEAVY_KW_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("mày", re.compile(r"\bmày\b", re.IGNORECASE)),
    ("tao", re.compile(r"\btao\b", re.IGNORECASE)),
    ("con nợ", re.compile(r"\bcon nợ\b", re.IGNORECASE)),
    ("ngu", re.compile(r"\bngu\b", re.IGNORECASE)),
    ("chúng mày", re.compile(r"\bchúng mày\b", re.IGNORECASE)),
    ("bọn mày", re.compile(r"\bbọn mày\b", re.IGNORECASE)),
    ("bọn tao", re.compile(r"\bbọn tao\b", re.IGNORECASE)),
]


def _first_heavy_kw(text: str) -> str | None:
    for label, pat in _HEAVY_KW_PATTERNS:
        if pat.search(text):
            return label
    return None


# Skip ASR-check routing when the evidence ALSO contains a clear C3 label
# word: the real violation is the label, and `mày/tao` is likely ASR garble
# on a nearby token (e.g. "trao đổi bất lịch sự mà hình tao rồi" = "hình
# thao"). ASR-check would over-suppress the C3 violation.
_C3_LABEL_GUARD = re.compile(
    r"\b(bất lịch sự|khiếm nhã|khiếm ngại|cợt nhả|lung tung|linh tinh|lằng nhằng|vòng vo|quanh co)\b",
    re.IGNORECASE,
)


@op
def route_check_fn(llm_result: dict = None) -> dict[str, Any]:
    """Decide whether this turn goes to the ASR-check verifier.

    Returns {is_heavy_kw: bool, keyword: str}. The graph branches on
    `is_heavy_kw` — true → ASR-check, false → filter decider.
    """
    if not isinstance(llm_result, dict):
        return {"is_heavy_kw": False, "keyword": ""}
    evidence = llm_result.get("evidence") or ""
    if not isinstance(evidence, str):
        return {"is_heavy_kw": False, "keyword": ""}
    # A C3 label in the evidence goes to the filter decider (see guard above).
    if _C3_LABEL_GUARD.search(evidence):
        return {"is_heavy_kw": False, "keyword": ""}
    kw = _first_heavy_kw(evidence)
    return {"is_heavy_kw": bool(kw), "keyword": kw or ""}


@op
def build_asr_check_inputs_fn(
    llm_result: dict = None,
    conversation: Conversation = None,
    keyword: str = "",
) -> dict[str, Any]:
    """Compose {keyword, evidence, context} for the ASR-check prompt.

    Uses a tight ±2 turn window — enough to judge tone continuity around
    the flagged keyword.
    """
    if not isinstance(llm_result, dict):
        return {"keyword": "", "evidence": "", "context": ""}
    _, evidence_display = _plain_evidence(llm_result.get("evidence"))
    context = build_verifier_context(conversation, turn_idxs(llm_result.get("evidence_idxs")),
                                     before=2, after=2)
    return {
        "keyword": keyword or "",
        "evidence": evidence_display,
        "context": context,
    }
