"""The seven case graphs still have the shape we recorded.

Step 0a of `docs/archive/PLAN_sentiment_agent_layers.md`. The layer refactor moves
40 ops into four subgraphs while changing nothing they do, so the property
worth asserting is that the *wiring* survived — and that has to be checked
without depending on names, because the refactor changes them on purpose
and operonx's auto-naming changes them by accident (`card_number`'s branch
is currently called `role`, read off a nearby assignment).

A golden alone proves little: it passes the day you write it. So half of
this file mutates a graph on purpose and asserts the comparison notices.
A harness that cannot fail is not a harness.

When the shape changes deliberately:

    uv run pytest tests/repo/test_graph_signature.py                         # what moved
    uv run pytest tests/repo/test_graph_signature.py --update-signatures     # record it

Re-recording to turn a red test green discards the only evidence of what
the graph used to be. Read the diff first.
"""
from __future__ import annotations

import copy
import inspect
import json

import pytest
from operonx.core import PARENT

from src.cases import CASES
from tests._graph_signature import diff_signatures, graph_signature

from tests._paths import ROOT

GOLDEN = ROOT / "tests" / "fixtures" / "graph_signatures.json"


def _signature(case_id: str) -> dict:
    verify = CASES[case_id].verify
    kwargs = {p: PARENT for p in inspect.signature(verify).parameters}
    return graph_signature(verify(**kwargs))


@pytest.fixture(scope="module")
def golden(request) -> dict:
    if request.config.getoption("--update-signatures"):
        current = {case_id: _signature(case_id) for case_id in sorted(CASES)}
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    assert GOLDEN.exists(), (
        f"no recorded shape at {GOLDEN} — "
        "run `uv run pytest tests/repo/test_graph_signature.py --update-signatures`"
    )
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


# ── the graphs match what was recorded ─────────────────────────────────


class TestShapeIsUnchanged:
    @pytest.mark.parametrize("case_id", sorted(CASES))
    def test_case_matches_the_recorded_shape(self, case_id, golden):
        assert case_id in golden, f"{case_id} has no recorded shape"
        diffs = diff_signatures(golden[case_id], _signature(case_id))
        assert diffs == [], "\n  " + "\n  ".join(diffs)

    def test_every_recorded_case_still_exists(self, golden):
        """A case dropped from the registry scores nothing, silently."""
        assert set(golden) == set(CASES)


# ── the harness can fail ───────────────────────────────────────────────


@pytest.fixture(scope="module")
def baseline() -> dict:
    return _signature("sentiment_agent")


class TestItCatchesMutations:
    """Each mutation is a way the layer refactor could go wrong.

    Written against a copied signature rather than a real broken graph:
    the point is that the *comparison* sees the difference, and building
    seven broken graphs to prove it would test operonx, not this.
    """

    def test_a_dropped_op_is_caught(self, baseline):
        broken = copy.deepcopy(baseline)
        broken["ops"].pop("scanner")
        diffs = diff_signatures(baseline, broken)
        assert any("op removed: scanner" in d for d in diffs)

    def test_an_extra_op_is_caught(self, baseline):
        """A predicate that stole a name used to *overwrite* its neighbour."""
        broken = copy.deepcopy(baseline)
        broken["ops"]["scanner_2"] = "llm"
        assert any("op added: scanner_2" in d for d in diffs_of(baseline, broken))

    def test_a_changed_op_type_is_caught(self, baseline):
        broken = copy.deepcopy(baseline)
        broken["ops"]["scanner"] = "code"
        assert any("op type changed: scanner" in d for d in diffs_of(baseline, broken))

    def test_a_dropped_edge_is_caught(self, baseline):
        broken = copy.deepcopy(baseline)
        dropped = broken["edges"].pop()
        diffs = diffs_of(baseline, broken)
        assert any(f"edge removed: {dropped[0]} -> {dropped[1]}" in d for d in diffs)

    def test_a_self_edge_is_caught(self, baseline):
        """The 2026-09-24 bug: `check >> check`, and 90 empty output files."""
        broken = copy.deepcopy(baseline)
        broken["edges"] = sorted(broken["edges"] + [["scanner", "scanner"]])
        assert any("edge added: scanner -> scanner" in d for d in diffs_of(baseline, broken))

    def test_a_swapped_branch_arm_is_caught(self, baseline):
        """The failure a structural test exists for: same ops, wrong route."""
        broken = copy.deepcopy(baseline)
        assert broken["branches"], "sentiment_agent must have branches"
        branch = broken["branches"][0]
        branch["default"] = "__somewhere_else__"
        assert diffs_of(baseline, broken), "a re-pointed default must be visible"

    def test_a_changed_condition_is_caught(self, baseline):
        broken = copy.deepcopy(baseline)
        branch = broken["branches"][0]
        if branch["cases"]:
            branch["cases"][0][0] = "totally different condition"
            assert diffs_of(baseline, broken)

    def test_a_changed_exit_is_caught(self, baseline):
        broken = copy.deepcopy(baseline)
        broken["exits"] = sorted(broken["exits"] + ["not_a_real_exit"])
        assert any("exits changed" in d for d in diffs_of(baseline, broken))

    def test_identical_signatures_produce_no_diff(self, baseline):
        """The other half: it must not cry wolf on an unchanged graph."""
        assert diff_signatures(baseline, copy.deepcopy(baseline)) == []


# ── renaming must NOT register as a change ─────────────────────────────


class TestRenamingIsInvisible:
    """The refactor prefixes every op (`scanner` → `l2.scanner`) and will
    rename branches. Neither changes behaviour, so neither may register —
    otherwise the harness fails on the move itself and tells us nothing.
    """

    def test_a_graph_prefix_is_stripped(self, baseline):
        prefixed = copy.deepcopy(baseline)
        prefixed["ops"] = {f"l2.{k}": v for k, v in baseline["ops"].items()}
        # `graph_signature` strips prefixes at build time; this asserts the
        # basename rule the comparison relies on.
        from tests._graph_signature import _base

        assert {_base(k) for k in prefixed["ops"]} == set(baseline["ops"])

    def test_branch_tables_are_keyed_on_conditions_not_names(self, baseline):
        """Two branches swapping names is not a behaviour change."""
        shuffled = copy.deepcopy(baseline)
        shuffled["branches"] = list(reversed(shuffled["branches"]))
        shuffled["branches"].sort(key=lambda b: (str(b["cases"]), str(b["default"])))
        assert diff_signatures(baseline, shuffled) == []


def diffs_of(expected: dict, actual: dict) -> list:
    return diff_signatures(expected, actual)
