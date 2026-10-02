"""Agent-sentiment row — what `_finalize` writes for this case's verdict.

Corpus severity outranks the scanner's category (see `_SEVERITY_ROW`).
"""
from ...core import config
from .._shared.spec import default_sentiment_row, turn_idxs


def _build_traces(result: dict) -> dict:
    """Reshape the internal `_trace_meta` block into the public `traces` output.

    Every call gets traces (empty dict when no meta is present); the public
    `Result` already says whether the call was flagged, so callers filter
    downstream if needed.
    """
    meta = result.get("_trace_meta") if isinstance(result.get("_trace_meta"), dict) else {}
    # Stages in pipeline order, for a predictable UI. `filter` carries the
    # pre-filter verdict + apply/shadow flag. `exit` names the terminal that
    # ended the call, which tells a reviewer the call was deliberately not
    # judged further rather than judged and cleared.
    stages = ("filter", "exit", "scanner", "retrieval", "halu_check", "decider",
              "asr_check", "primary_decider", "soften")
    return {k: meta[k] for k in stages if k in meta}


#: Corpus severity -> (Result label, Score_offset). `warning` is QC's tier
#: for phrasings that are worth surfacing but not worth penalising, so it
#: scores 0 while still reporting a distinct Result — a reviewer sees it,
#: the agent's score does not move.
#:
#: NOTE for consumers: "Thái độ warning" is a FOURTH Result value. Anything
#: reading these strings needs to know it exists; a consumer that lets an
#: unrecognised value fall through to "Tích cực" makes a warning call look
#: clean.
_SEVERITY_ROW = {
    "warning":      ("Thái độ warning", 0),
    "cao":          ("Thái độ cao", -10),
    "nghiem_trong": ("Thái độ nghiêm trọng", -25),
}


def format_sentiment_agent(result: dict | None, include_traces: bool | None = None) -> dict:
    """Agent sentiment row formatter — severity, else category, sets label + score.

    `severity_final` (the corpus severity the primary decider cited) wins
    when present; see `_SEVERITY_ROW`. Otherwise the scanner category:
      - C1..C11 (cao)             → "Thái độ cao",         -10
      - N1..N4  (nghiêm trọng)    → "Thái độ nghiêm trọng", -25
      - im_lang                   → "ĐTV im lặng",          0
      - khach_la_tre_em / none / other non-violation, or None result
                                  → default "Tích cực"

    "ĐTV im lặng" is reserved for the agent_silent exit (no agent content
    turns). A kid pickup and a `none` verdict are both "no violation" →
    "Tích cực" (per QC: kid pickup = không bắt lỗi).

    With *include_traces* (unset: `INCLUDE_TRACES`), appends a `traces` key
    with intermediate signal (scanner / retrieval / decider / primary /
    soften) — purely additive, does not touch Reasoning / Result / Score_offset.
    """
    if include_traces is None:
        include_traces = config.INCLUDE_TRACES
    if not result:
        return default_sentiment_row()
    cat = (result.get("category") or "").strip() if isinstance(result.get("category"), str) else ""
    # Corpus severity, resolved from the entry the primary decider cited,
    # outranks the scanner's category — corpus.yaml is what QC maintains, and
    # it carries a `warning` tier the scanner has no code for. When the
    # primary decider is off or nothing resolved, the category decides.
    sev = (result.get("severity_final") or "").strip()
    if sev in _SEVERITY_ROW:
        label, score = _SEVERITY_ROW[sev]
    elif cat.startswith("C"):
        label, score = _SEVERITY_ROW["cao"]
    elif cat.startswith("N"):
        label, score = _SEVERITY_ROW["nghiem_trong"]
    elif cat == "im_lang":
        label, score = "ĐTV im lặng", 0
    elif include_traces and isinstance(result, dict) and result.get("_trace_meta"):
        # Non-violation path but has trace meta (e.g., primary downgrade,
        # decider drop). Build a Tích cực row that still carries traces.
        row = default_sentiment_row()
        row["traces"] = _build_traces(result)
        return row
    else:
        return default_sentiment_row()
    # `Evidence` is the "[mm:ss]: content<br/>..." display text; `EvidenceIdxs`
    # the validated agent turn_idxs, for consumers that render clickable turn refs.
    row = {
        "Reasoning": result.get("reason", ""),
        "Result": label,
        "Evidence": result.get("evidence") or "",
        "Score_offset": score,
        "EvidenceIdxs": turn_idxs(result.get("evidence_idxs")),
    }
    if include_traces:
        row["traces"] = _build_traces(result)
    return row
