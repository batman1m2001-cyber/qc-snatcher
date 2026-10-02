# Backlog — engineering

Improvements deferred because they need an architecture change, not because
nobody got to them. Add here when we spot value but can't justify the work
yet.

---

## Scanner: multi-evidence output

**Trigger case**: FN batch 1 case 2 (E_anhpt62_...082214) — QC caught "con chị
cái vấn đề ở đây con chị không thanh toán đúng hạn là con chị đang sai rồi"
(C4 gán nhân thân, ~[04:20]), scanner picked a benign closer turn at [04:29]
"chị vui lòng đọc rõ điều lệ giúp em ạ" instead. QC and scanner referenced
different violation phrases in same call.

**Root cause**: scanner returns exactly 1 `evidence_idxs` list per call. If
multiple violations exist, scanner picks 1 (usually strongest or most recent),
loses the others. Multi-violation calls silently drop N-1 candidate turns.

**Cost of miss**: ~5-8% of positive-labelled calls have multi-violation
structure (rough estimate). When scanner picks the weaker one, decider may
drop it (FN), even though the stronger QC-cited turn would have been kept.

**Proposed fix**: scanner returns `evidences: [{idxs, phrase, category}, ...]`
list, up to N=3. Downstream stages run per-evidence, aggregate final
verdict as max(violations).

**Impact**: +1-2pp recall on multi-violation calls. But requires:
- scanner prompt rewrite (schema change)
- graph rewiring (per-evidence fanout or loop)
- attr/halu/decider per-evidence
- final aggregation logic

**Priority**: P2 — pilot with quick wins first, revisit after corpus tuning
plateaus.

---
