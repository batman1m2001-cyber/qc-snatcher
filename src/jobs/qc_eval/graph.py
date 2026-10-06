"""Graphs of the `qc_eval` job (steps) — `score_agent`, what the `qc_eval_score`
eval runs per call, and `qc_eval_report`. Declared in `app/main.py`; usage in `README.md`."""
from operonx.core import END, START, graph

from src.cases import verify_sentiment_agent

from ..score.ops import load_call
from .ops import write_report


# ── score_agent ── load the call ──▶ sentiment_agent alone; the eval judges its result


@graph
def score_agent(item: dict):
    call = load_call(item=item)
    agent = verify_sentiment_agent(conversation=call["conversation"], call_code=call["call_code"])
    START >> call >> agent >> END


# ── qc_eval_report ── the last qc_eval_score run ──▶ F1, the stage funnel, the diff


@graph
def qc_eval_report(batch: str, record_dir: str):
    report = write_report(batch=batch, record_dir=record_dir)
    START >> report >> END
