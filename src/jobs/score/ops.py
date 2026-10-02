"""The ops `score_call` wires around `score_cases`. See `graph.py`."""
from __future__ import annotations

import copy
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict

from operonx.core import op

from src.core.conversation import Conversation

logger = logging.getLogger(__name__)


@op
def load_call(item: dict = None) -> Dict[str, Any]:
    """One input file → `score_cases`'s inputs.

    `trace_id` names the call's stage file: the input stem, so it is
    findable from the call, plus a short uuid so a re-score does not
    overwrite the previous attempt.
    """
    meta = item["metadata"]
    return {
        "conversation": Conversation.load(item["path"]),
        "call_code": meta["call_code"],
        "closed_by": meta.get("closed_by") or "YES",
        "is_chinh_chu": bool(meta.get("is_chinh_chu", False)),
        "queue_id": int(meta.get("queueid") or 0),
        "trace_id": f"{item['name']}_{uuid.uuid4().hex[:8]}",
    }


@op
def finalize_row(
    call_scoring: dict = None,
    trace_id: str = "",
    trace_root: str = "./traces",
    session_id: str = "",
) -> Dict[str, Any]:
    """`call_scoring` → the row written to disk; its stage block → a file.

    Returns the row's own three fields, named: that makes the graph's result
    *the row*, which the job writes as the call's output file.

    The stage block is diagnostic, not part of the verdict, so it leaves
    the row (the QC UI has no field for it) and is written unchanged to
    `<trace_root>/<trace_id>.json` under the same `traces` key — selfcheck's
    rules are literal paths rooted at it. It is there only when
    INCLUDE_TRACES is on. Losing that file must not fail a call whose
    verdict is already computed, so a write error is only logged.
    """
    if not isinstance(call_scoring, dict):
        raise RuntimeError("the scoring graph produced no call_scoring")
    row = copy.deepcopy(call_scoring)
    stages = None
    for entry in row.get("Sentiment") or []:
        if isinstance(entry, dict) and "traces" in entry:
            stages = entry.pop("traces")
            break
    if stages is not None:
        try:
            target = Path(trace_root or "./traces")
            target.mkdir(parents=True, exist_ok=True)
            payload = {
                "request_id": trace_id,
                "workflow_name": "qc_flow",
                "session_id": session_id,
                "cost_usd": None,
                "traces": stages,
            }
            (target / f"{trace_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            logger.warning("could not write stage file for %s: %s", trace_id, e)
    return {
        "Sentiment": row["Sentiment"],
        "HVC": row["HVC"],
        "qc_score_total_offset": row["qc_score_total_offset"],
    }
