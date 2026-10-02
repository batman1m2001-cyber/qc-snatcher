"""An empty retrieval pool must fail the call, never score it clean.

The 2026-09-23 selfcheck is the case this guards. Triton degraded part
way through a 90-call batch; from file 79 onward retrieval returned
nothing. An empty pool is not a neutral input — the decider and the
primary are asked whether the evidence matches a corpus entry, and
handed nothing to match against they answer "no matching pattern",
correctly. The call scores `Tích cực`.

Every one of those 90 files was written as OK. Two were violations the
pre-migration baseline had flagged, with a near-verbatim corpus entry
for each. Nothing in the output, the logs or the batch summary said a
transport failure had become a verdict.

Two halves, so both are tested: `merge_sides` refuses to emit the empty
pool, and `_failed_case_ops` notices the raise. Either alone leaves the
call scoring clean.
"""
from __future__ import annotations

import pytest


# ── half one: the pool refuses to be empty ────────────────────────────
from src.cases.sentiment_agent.retrieval import merge_sides

#: `.core` is the plain function behind the @op — the same handle
#: `test_retrieval_determinism.py` uses to exercise `assemble_side`.
MERGE = merge_sides(positives=[], carveouts=[]).core


def _merge(positives, carveouts):
    return MERGE(positives=positives, carveouts=carveouts)


class TestMergeSides:
    def test_a_normal_pool_passes_through(self):
        out = _merge([{"id": "p1"}], [{"id": "c1"}])
        assert out == {"positives": [{"id": "p1"}], "carveouts": [{"id": "c1"}]}

    def test_one_side_empty_is_fine(self):
        """A query can genuinely match positives and no carve-out."""
        assert _merge([{"id": "p1"}], [])["carveouts"] == []
        assert _merge([], [{"id": "c1"}])["positives"] == []

    @pytest.mark.parametrize("pos,cvo", [([], []), (None, None), ([], None)])
    def test_both_sides_empty_raises(self, pos, cvo):
        """Not 'found nothing' — a vector search always returns its k nearest."""
        with pytest.raises(RuntimeError, match="empty pool"):
            _merge(pos, cvo)

    def test_the_message_says_what_it_costs(self):
        """Whoever reads this log needs to know it is not a clean call."""
        with pytest.raises(RuntimeError) as exc:
            _merge([], [])
        text = str(exc.value)
        assert "clean" in text, "must say a violation would score as clean"
        assert "Failing the call" in text


# ── half two: the raise fails the call ─────────────────────────────────
#
# operonx catches an op's exception and lets the graph carry on, so a
# raise deep in retrieval would otherwise surface as an empty pool, a
# "no matching pattern" decision, and a violation scored `Tích cực` in a
# file written as OK. The `score` job reads the run's trace and fails the
# call instead — asserted here through the real job, on a real fixture.

import json  # noqa: E402

from app._score import build_job  # noqa: E402
from tests._replay import build_stubs, install_stubs  # noqa: E402
from tests._recorded import INPUTS, RECORDED_ALL  # noqa: E402


def _flagged_call():
    """A recorded call that reaches retrieval — so poisoning it matters."""
    for p in RECORDED_ALL:
        name, row = p.values
        if "retrieval" in row["traces"]:
            return name, row["traces"]
    pytest.skip("no recorded call reaches retrieval")


def _score_one(tmp_path, name, block, *, enabled, drop=()):
    import src.core.config as cfg

    before = cfg.ENABLED_CASES
    cfg.ENABLED_CASES = enabled
    try:
        job = build_job(files=[str(INPUTS / name)], output_path=tmp_path / "out",
                        tracer_local_dir=str(tmp_path / "tr"), record_dir=tmp_path / "runs")
        stubs = {k: v for k, v in build_stubs(block).items() if k not in drop}
        install_stubs(job.engine().graph, stubs)
        run = job.run_sync()
    finally:
        cfg.ENABLED_CASES = before
    return run, json.loads((tmp_path / "out" / name).read_text(encoding="utf-8"))


def test_an_error_nested_inside_a_case_fails_the_call(tmp_path):
    """`qc_flow.sentiment_agent.l2.scanner` raises (its recording is left
    out, so the replay harness's poison fires) — three levels down, and
    the job still fails the call and writes the error file."""
    name, block = _flagged_call()
    run, out = _score_one(tmp_path, name, block, enabled=frozenset({"sentiment_agent"}),
                          drop=("scanner",))
    assert run.items[0].status == "failed"
    assert list(out) == ["error"] and "scanner" in out["error"]


def test_the_same_call_scores_when_nothing_raises(tmp_path):
    name, block = _flagged_call()
    run, out = _score_one(tmp_path, name, block, enabled=frozenset({"sentiment_agent"}))
    assert run.items[0].status == "ok" and "Sentiment" in out


def test_a_disabled_case_cannot_fail_the_call(tmp_path):
    """Every network op is poisoned and every case is off: nothing runs,
    nothing raises, and every row reads `Không chạy`."""
    name, _ = _flagged_call()
    run, out = _score_one(tmp_path, name, {}, enabled=frozenset())
    assert run.items[0].status == "ok"
    assert {r["Result"] for r in out["Sentiment"] + out["HVC"]} == {"Không chạy"}
