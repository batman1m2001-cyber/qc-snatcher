"""The root's own op: `_finalize` collects each case's verdict, formats it,
splits HVC from Sentiment and sums `Score_offset`. See `graph.py`.
"""
from __future__ import annotations

from typing import Any, Dict

from operonx.core import op

from ..core import config
from ..cases import CASES


#: The row of a case switched off by `QC_ENABLE_<CASE_ID>=false`. Its node
#: ran nothing (see `graph.py`), so the formatter's default — "Không vi
#: phạm" / "Tích cực" — would read as a verdict nobody computed.
NOT_RUN = {"Result": "Không chạy", "Reasoning": "", "Evidence": "", "Score_offset": 0, "EvidenceIdxs": []}


def _row(case_id: str, formatted: dict, raw: Any = None) -> dict:
    """Assemble one criterion row — Criteria + CriteriaCode + formatter body.

    CriteriaCode (TC_1..TC_7) is the IT mapping key; it must appear right
    after Criteria in the JSON so downstream systems can key on it without
    reflowing keys.

    A switched-off case that produced nothing (*raw* is None) reads
    `Không chạy`; a verdict that exists is never overwritten. An enabled
    case that produced nothing raises: its formatter would write the
    default — `Không vi phạm` / `Tích cực` — a verdict nothing reached.
    """
    c = CASES[case_id]
    row = {"Criteria": c.criteria, "CriteriaCode": c.code, **formatted}
    if raw is None:
        if case_id in config.ENABLED_CASES:
            raise RuntimeError(f"{case_id} produced no verdict — refusing to write {formatted['Result']!r} for it")
        row.update(NOT_RUN)
    return row


@op
def _finalize(
    hangup: dict = None,
    raba: dict = None,
    disclosure: dict = None,
    card_number: dict = None,
    phone_source: dict = None,
    sentiment_agent: dict = None,
    sentiment_customer: dict = None,
    include_traces: bool = None,
) -> Dict[str, Any]:
    """Collect raw case results → format rows → partition → sum score.

    Row order below == render order in the output JSON. *include_traces*
    unset means `INCLUDE_TRACES` decides.
    """
    raw = {"hangup": hangup, "raba": raba, "disclosure": disclosure, "card_number": card_number,
           "phone_source": phone_source, "sentiment_agent": sentiment_agent,
           "sentiment_customer": sentiment_customer}
    rows: Dict[str, list] = {"HVC": [], "Sentiment": []}
    for case_id, case in CASES.items():
        formatted = (case.format(raw[case_id], include_traces) if case_id == "sentiment_agent"
                     else case.format(raw[case_id]))
        rows[case.section].append(_row(case_id, formatted, raw[case_id]))
    total = sum(r["Score_offset"] for r in rows["HVC"] + rows["Sentiment"])
    return {"call_scoring": {"Sentiment": rows["Sentiment"], "HVC": rows["HVC"], "qc_score_total_offset": total}}
