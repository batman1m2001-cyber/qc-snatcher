"""Layer 4 ops — the primary decider's strict re-verify, then soften.

**Primary decider.** A stronger model (`llm.primary_decider` in
`models.yaml`) re-reads every violation the filter decider kept, against
the same corpus. It fires only when all hold:

  1. `llm.primary_decider` is not null
  2. `violation` is true
  3. `evidence_idxs` is non-empty — it needs an anchor for the context window

On disagreement the verdict is downgraded — `violation` false, `category`
`none` — with the original kept in `original_category` for audit, so the
row scores 0 instead of -10/-25. On agreement `resolve_cited_severity`
resolves the most severe corpus entry it cited, and that outranks the
scanner's category: it is what sets `Score_offset`. Unclear output keeps the
filter decider's verdict (precision-conservative).

**Soften.** Rewrites an accusatory `reason` into a descriptive one for QC to
read. Fires only for C*/N* verdicts with a non-empty reason; never touches
the verdict. `llm.soften: null` falls back to the default model.
"""
from __future__ import annotations

import logging
import re

from operonx.core import op

from ....core.conversation import Conversation
from ..._shared.spec import is_true, turn_idxs
from .._context import build_verifier_context
from .._pools import _format_indexed_pool, _parse_cited, pool_id_map, remap_cited
from .._trace import evidence_query
from ....core import config

_LOG = logging.getLogger(__name__)


_CONTEXT_WINDOW = 3   # ± N turns around each evidence_idx


_TIMESTAMP = re.compile(r"^\s*\[\d{1,2}:\d{2}\]\s*:\s*")

#: A phrase the scanner quoted in its reason.
_QUOTED = re.compile(r"'([^']+)'")


def _evidence_text(r: dict) -> str:
    """The cited turns as the two l4 prompts read them: `evidence` without
    its leading `[mm:ss]:`. The primary decider and soften read the same text;
    soften used to read an `evidence_text` key nothing writes, and rewrote
    reasons blind to what was said."""
    return _TIMESTAMP.sub("", r.get("evidence") or "").strip()


@op
def build_primary_inputs_fn(
    raw_result: dict = None,
    conversation: Conversation = None,
) -> dict:
    """Gate + build inputs for the primary decider.

    Skips when `llm.primary_decider` is null, when the call is not a
    violation, or when there is no evidence anchor.
    """
    r = raw_result or {}
    idx_set = set(turn_idxs(r.get("evidence_idxs")))
    if not (config.PRIMARY_DECIDER_LLM_RESOURCE_KEY and is_true(r.get("violation")) and idx_set):
        # The LLM never fires on this branch; the values are placeholders.
        return {
            "needs_verify":      False,
            "category":          "",
            "ai_reason":         "",
            "evidence":          "",
            "context":           "",
            "retrieval_query":   "",
        }

    # The window is counted in turns, as l3's is. It used to compare list
    # positions with turn_idx, which skips empty turns: on 62 of the 90
    # fixture calls the window drifted (median 1, max 10) and could miss the
    # cited turn and its `<<<` marker entirely.
    context = build_verifier_context(conversation, sorted(idx_set),
                                     before=_CONTEXT_WINDOW, after=_CONTEXT_WINDOW)

    ev_text = _evidence_text(r)
    if not context:
        context = ev_text  # last-resort fallback

    cat = (r.get("category") or "").strip()
    ai_reason = (r.get("reason") or "").strip()

    # Query: the phrases the scanner quoted — the violation cue — else the
    # evidence turn, as l3 builds it. Corpus entries are short phrases, many
    # quoted by QC; a whole turn embeds away from them. On round 3, querying
    # the turn (4ced162) dropped 18 of the 24 entries this decider had cited
    # and flipped 23 true violations to clean (F1 0.856 -> 0.743).
    # Retrieval is a graph node behind this gate and must stay there: this
    # op returns early for the ~98% of calls that are not violations, and
    # those must not pay for an embed.
    quoted = _QUOTED.findall(ai_reason)

    # Turn indexes, never the words: this line reaches pod stdout, which is
    # outside the redacting tracer, and the transcript is PII.
    _LOG.warning(f"[primary] FIRE — cat={cat} evidence_idxs={sorted(idx_set)}")
    return {
        "needs_verify":      True,
        "category":          cat,
        "ai_reason":         ai_reason,
        "evidence":          ev_text,
        "context":           context,
        "retrieval_query":   " ".join(quoted) if quoted else evidence_query(r),
    }


@op
def format_primary_pools_fn(
    query: str = None,
    positives: list = None,
    carveouts: list = None,
) -> dict:
    """Retrieved items -> the indexed pool strings the prompt renders.

    An empty query means there was nothing to retrieve on; emit the
    placeholder rather than whatever the embedder returns for "", which
    would be arbitrary neighbours presented as relevant corpus policy.
    """
    if not (query or "").strip():
        return {"positives_indexed": "(không có mẫu nào được retrieve)",
                "carveouts_indexed": "(không có mẫu nào được retrieve)",
                "severity_by_id": {}, "pool_map": {}}
    pos_str, pos_items = _format_indexed_pool(positives or [], "P")
    neg_str, neg_items = _format_indexed_pool(carveouts or [], "C")
    # `P1 -> "warning"`. Only the positive side: a carveout is a reason NOT
    # to flag, so it has no severity to contribute.
    severity_by_id = {
        it["id"]: it.get("severity") or ""
        for it in pos_items if it.get("id")
    }
    # This node retrieves its own pool, so its `P1` is not the decider's
    # `P1`. The map is per-node for that reason, and is what lets the trace
    # report a corpus id instead of a slot number nobody can resolve later.
    return {"positives_indexed": pos_str, "carveouts_indexed": neg_str,
            "severity_by_id": severity_by_id,
            "pool_map": pool_id_map(pos_items, neg_items)}


#: Ranked so the most severe cited entry wins. A call citing both a
#: `warning` and a `nghiem_trong` phrase is a serious call — a mild entry
#: cited alongside must not mask it.
SEVERITY_RANK = {"warning": 1, "cao": 2, "nghiem_trong": 3}


def resolve_cited_severity(cited_ids: list, severity_by_id: dict) -> str:
    """Highest-ranked corpus severity among the cited positives.

    Returns "" when nothing resolves — no citations, or ids the pool does
    not know — which leaves the scanner's category in charge rather than
    inventing a verdict from an empty lookup.
    """
    best, best_rank = "", 0
    for pool_id in cited_ids or []:
        sev = (severity_by_id or {}).get(pool_id) or ""
        rank = SEVERITY_RANK.get(sev, 0)
        if rank > best_rank:
            best, best_rank = sev, rank
    return best


def _attach_primary_trace(
    base: dict,
    enabled: bool,
    verdict,
    reason: str,
    cited_positives: list = None,
    cited_carveouts: list = None,
    severity_final: str = "",
    pool_map: dict = None,
) -> None:
    """Merge primary block into base['_trace_meta']. Preserves any existing
    trace fields (scanner/retrieval/decider from upstream).

    Citations are translated from pool slots to corpus entry ids here, on
    the way out — deliberately after `resolve_cited_severity`, which looks
    up by slot. Remapping earlier would mean rekeying that lookup too, and
    scoring is not a thing to touch for a reporting change.
    """
    meta = base.setdefault("_trace_meta", {})
    meta["primary_decider"] = {
        "enabled":         enabled,
        "verdict":         verdict,
        "reason":          reason,
        "cited_positives": remap_cited(cited_positives, pool_map),
        "cited_carveouts": remap_cited(cited_carveouts, pool_map),
        "pool_map":        pool_map or {},
        # Which corpus severity won, and therefore what scored the call.
        # Empty means nothing resolved and the scanner's category stood.
        "severity_final":  severity_final or "",
        "resource":        config.PRIMARY_DECIDER_LLM_RESOURCE_KEY,
    }


@op
def apply_primary_fn(raw_result: dict = None, primary_out: dict = None,
                       severity_by_id: dict = None,
                       pool_map: dict = None) -> dict:
    """Merge the primary decider's verdict.

    On disagreement, downgrade the category to 'none' — evidence and
    evidence_idxs are kept for audit. On agreement, resolve the cited corpus
    severity into `severity_final`.

    Pass-through cases:
      - primary_out is None (skip branch, LLM never fired)
      - primary_out['violation'] is not explicitly false (agree → keep raw)
      - primary_out malformed
    """
    base = raw_result or {}
    # Skip branch: LLM never fired. Mark as disabled/skipped in trace.
    if not isinstance(primary_out, dict):
        out = dict(base)
        _attach_primary_trace(out, enabled=bool(config.PRIMARY_DECIDER_LLM_RESOURCE_KEY),
                                verdict=None, reason="(not invoked — non-violation)")
        return {"result": out}

    v = primary_out.get("violation")
    # Downgrade only on an EXPLICIT false. Anything else (missing key,
    # malformed, true) keeps the filter decider's verdict — fail-safe
    # toward it.
    is_false = (v is False) or (isinstance(v, str) and v.strip().lower() == "false")
    reason = (primary_out.get("reason") or "").strip() or "primary_disagree"
    cited_p = _parse_cited(primary_out.get("cited_positives"), "P")
    cited_c = _parse_cited(primary_out.get("cited_carveouts"), "C")

    if not is_false:
        out = dict(base)
        # Corpus severity of the cited entry beats the scanner's category —
        # see the note above SEVERITY_RANK. Applied only on the agree path:
        # a disagreement drops the violation entirely, and there is no
        # severity to assign to something that is not a violation.
        final_sev = resolve_cited_severity(cited_p, severity_by_id)
        if final_sev:
            out["severity_final"] = final_sev
        _LOG.warning(f"[primary] AGREE — cat={base.get('category')} "
                     f"severity_final={final_sev or '(none — category stands)'} "
                     f"cited_p={cited_p} cited_c={cited_c}")
        _attach_primary_trace(out, enabled=True, verdict=True, reason=reason,
                                cited_positives=cited_p, cited_carveouts=cited_c,
                                severity_final=final_sev, pool_map=pool_map)
        return {"result": out}

    # No reason text: the model quotes the transcript in it.
    _LOG.warning(f"[primary] DISAGREE — downgrade {base.get('category')} → none. "
                 f"cited_p={cited_p} cited_c={cited_c}")
    out = dict(base)
    out["violation"]         = "false"
    out["category"]          = "none"
    out["original_category"] = base.get("category", "")
    out["drop_reason"]       = "primary_disagree"
    out["primary_reason"]  = reason
    # Blank the accusatory reason since it's no longer a violation. Keep
    # evidence + evidence_idxs so QC can still see WHY the filter decider flagged.
    out["reason"] = ""
    _attach_primary_trace(out, enabled=True, verdict=False, reason=reason,
                            cited_positives=cited_p, cited_carveouts=cited_c,
                            pool_map=pool_map)
    return {"result": out}


@op
def build_soften_inputs_fn(raw_result: dict = None) -> dict:
    """Extract soften inputs + gate flag. Fire only for C*/N* violations
    with non-empty reason — everything else is either not a violation or
    has nothing to rewrite."""
    r = raw_result or {}
    cat_raw = r.get("category")
    cat = cat_raw.strip() if isinstance(cat_raw, str) else ""
    reason = (r.get("reason") or "").strip()
    needs = bool(cat.startswith(("C", "N")) and reason)
    return {
        "needs_soften":    needs,
        "category":        cat,
        "evidence_text":   _evidence_text(r),
        "original_reason": reason,
    }


def _attach_soften_trace(base: dict, enabled: bool, before: str, after: str, error: str = None) -> None:
    meta = base.setdefault("_trace_meta", {})
    meta["soften"] = {
        "enabled":  enabled,
        "before":   before,
        "after":    after,
        "resource": config.SOFTEN_LLM_RESOURCE_KEY,
    }
    if error:
        meta["soften"]["error"] = error


@op
def apply_soften_fn(raw_result: dict = None, soften_out: dict = None, soften_error: str = None) -> dict:
    """Merge softened reason back into raw result. Pass-through when the
    LLM branch was skipped (soften_out=None), returned empty, or failed —
    a failed soften keeps the reason as written and says why in the trace:
    it rewords, it never decides, so it must not cost the call its verdict."""
    base = raw_result or {}
    reason_before = (base.get("reason") or "").strip()
    if soften_error:
        out = dict(base)
        _attach_soften_trace(out, enabled=False, before=reason_before, after=reason_before,
                             error=str(soften_error).splitlines()[0][:200])
        return {"result": out}
    if not soften_out:
        out = dict(base)
        _attach_soften_trace(out, enabled=False, before=reason_before, after=reason_before)
        return {"result": out}
    new_reason = (soften_out.get("reason") or "").strip()
    if not new_reason:
        out = dict(base)
        _attach_soften_trace(out, enabled=True, before=reason_before, after=reason_before)
        return {"result": out}
    out = {**base, "reason": new_reason}
    _attach_soften_trace(out, enabled=True, before=reason_before, after=new_reason)
    return {"result": out}


