"""The graph must actually produce a result — not merely build.

On 2026-09-24 a selfcheck scored 90 calls, reported `OK` on every one, and
wrote `{}` to all 90 output files. The cause was one edge: a branch whose
condition is an op that is also its own source wired `check >> check`, and
an op waiting on itself never runs. `_finalize` never dispatched, so
`call_scoring` was absent, and the runner's success path never asks whether
anything came out.

Every test in the suite passed throughout. They assert on graph structure,
and a self-edge is structurally valid — it only fails when something runs.

So these run the real `score_cases` with every case disabled: no LLM, no
network, a couple of seconds. Disabled ops still participate in the
topology, which is exactly the part that broke.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest
from operonx.core import PARENT

from src.cases import CASES
from src.core.conversation import Conversation
from tests._engine import apply_case_selection, children, create_engine, edges


def _edges(graph):
    return edges(graph)


def _build_case(case):
    kwargs = {p: PARENT for p in inspect.signature(case.verify).parameters}
    return case.verify(**kwargs)


# ── topology ───────────────────────────────────────────────────────────


class TestNoSelfEdges:
    """An op that waits on itself is never dispatched, and says nothing.

    There is no error, no log line and no missing-output check — the graph
    simply stops, and every downstream verdict is absent rather than wrong.
    """

    @pytest.mark.parametrize("case_id", sorted(CASES))
    def test_case_graph_has_no_self_edge(self, case_id):
        graph = _build_case(CASES[case_id])
        loops = [(u, v) for u, v in _edges(graph) if u == v]
        assert loops == [], f"{case_id} has an op waiting on itself: {loops}"

    def test_orchestrator_has_no_self_edge(self):
        engine, _ = create_engine(tracer_kind="none")
        loops = [(u, v) for u, v in _edges(engine.graph) if u == v]
        assert loops == []


class TestEveryCaseStillBuilds:
    @pytest.mark.parametrize("case_id", sorted(CASES))
    def test_case_graph_builds(self, case_id):
        graph = _build_case(CASES[case_id])
        assert children(graph), f"{case_id} built an empty graph"


# ── it runs, and something comes out ───────────────────────────────────


@pytest.fixture(scope="module")
def scored_with_all_cases_off():
    """Run the real `score_cases` with every case disabled.

    `apply_case_selection(engine, set())` clears `enabled` on all seven, so
    no LLM op fires and no network is touched — but the topology is the
    production one, including the fan-in to `_finalize`, which is where the
    deadlock lived.
    """
    engine, _ = create_engine(tracer_kind="none")
    apply_case_selection(engine, set())
    conversation = Conversation(
        vads=[{"role": "agent", "content": "xin chào anh", "start": 0, "end": 2}]
    )
    # Run once for the module and hand back the dict, not the coroutine —
    # a coroutine can only be awaited once, so sharing one across tests
    # gives the first test a result and the rest a RuntimeError.
    # The config must agree that all seven are off: `_finalize` refuses an
    # enabled case that produced nothing.
    from src.core import config

    was, config.ENABLED_CASES = config.ENABLED_CASES, frozenset()
    try:
        return asyncio.run(
            engine.run(
                inputs={
                    "conversation": conversation,
                    "call_code": "Ngat_may",
                    "closed_by": "AGENT",
                    "is_chinh_chu": False,
                    "queue_id": 0,
                }
            )
        )
    finally:
        config.ENABLED_CASES = was


class TestProducesOutput:
    def test_call_scoring_is_produced(self, scored_with_all_cases_off):
        """The one assertion the 90-empty-files run needed and nobody made."""
        result = scored_with_all_cases_off
        assert "call_scoring" in result, (
            "the graph returned no outputs — a terminal op never dispatched. "
            "Check for a self-edge or an unsatisfied merge before looking "
            "anywhere else."
        )

    def test_the_result_has_the_shape_the_writer_expects(
        self, scored_with_all_cases_off
    ):
        """`score_one` dumps this straight to the output file."""
        scoring = scored_with_all_cases_off.get("call_scoring")
        assert isinstance(scoring, dict)
        for key in ("Sentiment", "HVC", "qc_score_total_offset"):
            assert key in scoring, f"output file would be missing {key!r}"

    def test_it_is_not_empty(self, scored_with_all_cases_off):
        """`{}` is what 90 files held while the runner reported OK."""
        scoring = scored_with_all_cases_off.get("call_scoring")
        assert scoring != {}
        assert scoring.get("Sentiment"), "no sentiment rows at all"
