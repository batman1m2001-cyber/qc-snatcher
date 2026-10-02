"""Test-side helpers for driving the scoring graph directly.

Production runs it through the `score` job (`app/main.py`, graph in `src/jobs/score`); tests that stub
ops need the engine in hand, a case selection, and the errors a run
recorded — operonx catches an op's exception, stores it at
`state[op, "error"]` and lets the graph carry on, which is exactly why the
job reads the run's trace to fail a call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from operonx.core import PARENT, Operon

from src.cases import CASES
from src.qc.graph import score_cases


def children(graph: Any) -> Dict[str, Any]:
    """A built graph's ops by name (operonx keeps them private, `_ops`)."""
    return graph._ops


def edges(graph: Any) -> list:
    """A built graph's edges as `(from, to)` (operonx keeps them private, `_edges`)."""
    return [(e.from_node, e.to_node) for e in graph._edges.values()]


def create_engine(tracer_kind: str = "none"):
    """`score_cases` as one Operon, and no tracer — `(engine, None)`.

    The root is pinned `qc_flow`: every state key the tests read
    (`qc_flow.sentiment_agent`) starts with it, and operonx would otherwise
    name it after whichever variable holds it.
    """
    qc_flow = score_cases(conversation=PARENT, call_code=PARENT, closed_by=PARENT,
                           is_chinh_chu=PARENT, queue_id=PARENT, name="qc_flow")
    return Operon(qc_flow), None


def apply_case_selection(engine: Operon, selected: Optional[set]) -> None:
    """Enable only *selected* case nodes (all when None)."""
    for case_id in CASES:
        op = children(engine.graph).get(case_id)
        if op is not None:
            op.enabled = selected is None or case_id in selected


def recorded_errors(state: Any) -> Dict[str, str]:
    """`{op name: last line of its error}` for every op that raised."""
    out: Dict[str, str] = {}
    if state is None:
        return out
    for op_name, var in state:
        if var == "error":
            err = state.get(op_name, "error")
            if err:
                out[str(op_name)] = str(err).strip().splitlines()[-1][:200]
    return out
