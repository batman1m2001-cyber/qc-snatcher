"""`score_call` — one call through the scoring graph, as a job runs it.

    item (path, name, metadata) ──▶ load_call ──▶ score_cases ──▶ finalize_row

`score_cases` is `src.qc.graph`'s, unchanged: this graph only feeds it one
call and turns its `call_scoring` into the row written to disk. No doors —
the job binds the item to `item` and writes the run's result.
"""
from operonx.core import END, START, graph

from src.qc.graph import score_cases

from .ops import finalize_row, load_call


@graph
def score_call(item: dict, trace_root: str, session_id: str):
    call = load_call(item=item)
    qc_flow = score_cases(
        conversation=call["conversation"],
        call_code=call["call_code"],
        closed_by=call["closed_by"],
        is_chinh_chu=call["is_chinh_chu"],
        queue_id=call["queue_id"],
    )
    row = finalize_row(
        call_scoring=qc_flow["call_scoring"],
        trace_id=call["trace_id"],
        trace_root=trace_root,
        session_id=session_id,
    )
    START >> call >> qc_flow >> row >> END
