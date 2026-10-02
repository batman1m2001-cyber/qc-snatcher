"""Seminar demo: the real QC root graph on five synthetic calls, fully offline.

    uv run python -m demo            # QC table per call + a trace per call
    uv run python -m demo --graph    # just print the root graph's shape
    uv run python -m demo -v         # also show operonx's log of the failure
    uv run python -m demo --real     # real models per models.yaml (needs the seminar runner on :8000)
    source seminar/env.sh && uv run python -m demo --real
                                     # ... and real retrieval: Triton BGE-M3 + pgvector
                                     # from seminar/docker-compose.yml

The graph is `src.qc.graph:score_cases` exactly as production builds it —
seven `verify_<case>` subgraphs in parallel, joined by `_finalize`. Only
the model replies and the corpus retrieval are canned (`demo/offline.py`,
`demo/calls.py`). Each run is traced with operonx's local consumer into
`traces/`, where operonx.toml points OperonX Studio.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from .offline import CURRENT_CALL, go_offline, pin_environment, real_retrieval, walk

REAL = "--real" in sys.argv   # models.yaml's resources, through the seminar runner's router
pin_environment(real=REAL)  # before `src` is imported
#: `--real` with seminar/env.sh sourced: the local Triton + pgvector too.
REAL_RETRIEVAL = REAL and real_retrieval()

from operonx.core import PARENT, Operon  # noqa: E402
from operonx.telemetry.consumers.local import LocalConsumer  # noqa: E402

from src.cases import CASES  # noqa: E402
from src.core.conversation import Conversation  # noqa: E402
from src.qc.graph import score_cases  # noqa: E402

from .calls import CALLS, CORPUS_POOL, DEFAULT, SCRIPT  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "traces"   # where operonx.toml points Studio ([studio] traces)


def build():
    """The production root graph, named `qc_flow` as in operonx.toml."""
    return score_cases(conversation=PARENT, call_code=PARENT, closed_by=PARENT,
                       is_chinh_chu=PARENT, queue_id=PARENT, name="qc_flow")


def print_graph(graph) -> None:
    graph.build()
    print(f"graph {graph.name}: {len(graph._ops)} nodes at the root, "
          f"{sum(1 for _ in walk(graph))} ops in total")
    for e in graph._edges.values():
        print(f"  {e.from_node} -> {e.to_node}")


async def score(engine: Operon, call: dict) -> dict:
    CURRENT_CALL.set(call["call_id"])
    conv = Conversation(vads=[dict(v) for v in call["vads"]])
    out = await engine.run(inputs={
        "conversation": conv, "call_code": call["call_code"], "closed_by": call["closed_by"],
        "is_chinh_chu": call["is_chinh_chu"], "queue_id": 0,
    }, session_id="seminar-demo", request_id=call["call_id"])
    # operonx records a raising op in `$errors` and carries on, so a failure
    # has to be looked for — the score job does the same.
    errors = {k: str(v).strip().splitlines()[-1][:110] for k, v in (out.get("$errors") or {}).items()}
    return {"scoring": out.get("call_scoring"), "errors": errors}


def report(call: dict, res: dict) -> None:
    print(f"\n{call['call_id']}  {call['title']}  (call_code={call['call_code']})")
    scoring, errors = res["scoring"], res["errors"]
    # Which case did each failing op belong to? (`qc_flow.<case>.…`)
    failed = {}
    for op_name, msg in errors.items():
        parts = op_name.split(".")
        case = parts[1] if len(parts) > 1 and parts[0] == "qc_flow" else parts[0]
        if case in CASES:
            failed.setdefault(case, msg)
    rows = {}
    if scoring:
        for r in scoring["HVC"] + scoring["Sentiment"]:
            rows[r["Criteria"]] = r
    for case_id, case in CASES.items():
        if case_id in failed:
            verdict, extra = "ERROR", failed[case_id]
        elif case.criteria in rows:
            r = rows[case.criteria]
            verdict, extra = f"{r['Result']} ({r['Score_offset']:+d})", r.get("Reasoning", "")
        else:
            verdict, extra = "—", "no verdict (call failed)"
        print(f"  {case_id:<19} {verdict:<28} {str(extra)[:70]}")
    if scoring and not errors:
        print(f"  => total offset {scoring['qc_score_total_offset']:+d}")
    else:
        print(f"  => CALL RECORDED AS ERROR — a failure is never a verdict "
              f"({len(errors)} op error(s), first: {next(iter(errors.values()), '?')})")


async def main() -> int:
    if "-v" not in sys.argv:
        # The failing call's traceback is operonx logging what it caught;
        # the table below says the same in one line. `-v` shows it.
        for name in [n for n in logging.root.manager.loggerDict if n.startswith("operonx")]:
            logging.getLogger(name).setLevel(logging.CRITICAL)
    graph = build()
    counts = go_offline(graph, SCRIPT, DEFAULT, CORPUS_POOL, models=not REAL,
                        retrieval=not REAL_RETRIEVAL)
    engine = Operon(graph, trace=LocalConsumer(config={"root": str(RUNS)}))
    if REAL:
        where = ("Triton BGE-M3 + pgvector (seminar/docker-compose.yml)" if REAL_RETRIEVAL
                 else f"{counts['retrieval']} backends answered in memory (source seminar/env.sh for real ones)")
        print("qc_flow on real models (models.yaml): l1-l3 and the other cases on the in-house model, "
              f"l4 on gpt-4o; retrieval: {where}")
    else:
        print(f"qc_flow offline: {counts['llm']} LLM ops answered by script, "
              f"{counts['retrieval']} retrieval backends (Triton/pgvector) answered in memory")
    failed = 0
    for call in CALLS:
        res = await score(engine, call)
        report(call, res)
        failed += bool(res["errors"] or not res["scoring"])
    print(f"\n{len(CALLS)} calls, {failed} recorded as error. Traces: {RUNS.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    if "--graph" in sys.argv:
        print_graph(build())
        sys.exit(0)
    sys.exit(asyncio.run(main()))
