"""RABA ops — `_decide` aggregates money + time + agreement into a verdict.

Rule-based and deterministic; no LLM call. Shared by the 1st- and
3rd-person routes through `_detect` in `graph.py`.
"""
from __future__ import annotations

from operonx.core import op


@op
def _decide(
    money_found: bool = None,
    time_mention: bool = None,
    oppose_found: bool = None,
    actionable_time_mention: bool = True,
    agreement_reason: str = "",
) -> dict:
    """Rule-based decision for RABA case.

    Also hands on the facts it judged, as plain bools and a string, for
    `response` to quote. A detector whose reply fails to parse leaves its
    fields None, and None does not bind to a template variable: fed the
    raw fields, `response` failed and the violation decided here never
    reached its exit.
    """
    actionable = actionable_time_mention if actionable_time_mention is not None else True
    money, time, oppose = bool(money_found), bool(time_mention), bool(oppose_found)

    if not money or not time or not actionable:
        violation, reason = True, "thiếu thông tin về tiền hoặc thời gian"
    elif oppose:
        violation, reason = True, agreement_reason or "khách hàng từ chối trả nợ"
    else:
        violation, reason = False, agreement_reason or "khách hàng có hứa trả nợ và không từ chối"

    return {
        "violation": violation,
        "reason": reason,
        "money_found": money,
        "time_found": time,
        "oppose_found": oppose,
        "agreement_reason": agreement_reason or "",
    }
