"""Graphs of the selfcheck — `score_fixture`, what the `selfcheck` eval runs
per call, and `selfcheck_build`. Declared in `app/main.py`; usage in `README.md`."""
from operonx.core import END, START, graph

from src.qc.graph import score_cases

from ..score.ops import load_call
from .ops import promote, read_run


# ── score_fixture ── load the call ──▶ the scoring graph; the eval judges what comes out


@graph
def score_fixture(item: dict):
    call = load_call(item=item)
    qc_flow = score_cases(
        conversation=call["conversation"],
        call_code=call["call_code"],
        closed_by=call["closed_by"],
        is_chinh_chu=call["is_chinh_chu"],
        queue_id=call["queue_id"],
        include_traces=True,  # 7 of the 10 HARD rules read the stage block
    )
    START >> call >> qc_flow >> END


# ── selfcheck_build ── read the last selfcheck run ──▶ promote it


@graph
def selfcheck_build(dry_run: bool, record_dir: str):
    run = read_run(record_dir=record_dir)
    promoted = promote(scored=run["scored"], dry_run=dry_run)
    START >> run >> promoted >> END
