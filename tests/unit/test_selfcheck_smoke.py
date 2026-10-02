"""Smoke tests for the selfcheck compare + fixture layout.

The full selfcheck (invoking the pipeline against live LLM) belongs on
UAT — see src/jobs/selfcheck/. These tests only exercise the pure-python
compare logic + fixture manifest consistency so a fixture rebuild that
breaks the file layout would fail loudly in CI without any LLM cost.
"""
from __future__ import annotations

import copy
import json

from src.jobs.selfcheck._baseline import FX_INPUTS, FX_OUTPUTS, MANIFEST
from src.jobs.selfcheck._baseline import HARD_RULES as _HARD_RULES
from src.jobs.selfcheck._baseline import SOFT_RULES as _SOFT_RULES
from src.jobs.selfcheck._baseline import compare as _compare
from src.jobs.selfcheck._baseline import pick as _pick
from src.jobs.selfcheck._baseline import sentiment_row as _sentiment_row

# ---------------------------------------------------------------------------
# Fixture layout — files exist and match the manifest
# ---------------------------------------------------------------------------


class TestFixtureLayout:
    def test_manifest_exists(self):
        assert MANIFEST.exists(), (
            "fixture manifest missing — the fixture is committed, so this means a "
            "partial checkout, not a missing build step"
        )

    def test_inputs_and_outputs_dirs_populated(self):
        assert FX_INPUTS.exists() and any(FX_INPUTS.iterdir())
        assert FX_OUTPUTS.exists() and any(FX_OUTPUTS.iterdir())

    def test_each_input_has_matching_output(self):
        inputs = {p.name for p in FX_INPUTS.glob("*.json")}
        outputs = {p.name for p in FX_OUTPUTS.glob("*.json")}
        missing = inputs - outputs
        extra = outputs - inputs
        assert not missing, f"inputs without baseline output: {sorted(missing)}"
        assert not extra, f"orphan baseline outputs: {sorted(extra)}"

    def test_manifest_selection_matches_disk(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        expected = {entry["filename"] for entry in manifest["selected"]}
        on_disk = {p.name for p in FX_INPUTS.glob("*.json")}
        assert expected == on_disk

    def test_every_baseline_has_sentiment_agent_row(self):
        """Baseline outputs must have the row selfcheck compares — else the
        compare would trivially fail with 'row missing'."""
        for out_path in FX_OUTPUTS.glob("*.json"):
            data = json.loads(out_path.read_text(encoding="utf-8"))
            row = _sentiment_row(data)
            assert row is not None, f"baseline {out_path.name} missing sentiment_agent row"
            assert "traces" in row, f"baseline {out_path.name} missing traces (rebuild with INCLUDE_TRACES=on)"

    def test_class_coverage(self):
        """Manifest must contain both positive and negative class samples so
        selfcheck exercises both violation-catch and non-violation code paths."""
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        classes_seen = {e.get("class") or e.get("bucket") for e in manifest["selected"]}
        # Class field replaces the earlier bucket taxonomy — accept either.
        has_pos = "pos" in classes_seen or any("tp_" in c or "fn_" in c
                                                for c in classes_seen if c)
        has_neg = "neg" in classes_seen or any("tn_" in c or "fp_" in c
                                                for c in classes_seen if c)
        assert has_pos and has_neg


# ---------------------------------------------------------------------------
# _pick — nested dict lookup
# ---------------------------------------------------------------------------


class TestPick:
    def test_shallow(self):
        assert _pick({"a": 1}, ["a"]) == 1

    def test_nested(self):
        assert _pick({"a": {"b": {"c": 42}}}, ["a", "b", "c"]) == 42

    def test_missing_returns_none(self):
        assert _pick({"a": 1}, ["missing"]) is None

    def test_missing_intermediate_returns_none(self):
        assert _pick({"a": 1}, ["a", "b", "c"]) is None

    def test_none_root(self):
        # Defensive: chained lookup on non-dict must not crash.
        assert _pick({}, ["a", "b"]) is None


# ---------------------------------------------------------------------------
# _compare — the heart of the selfcheck
# ---------------------------------------------------------------------------


def _mk_row(**overrides) -> dict:
    base = {
        "Result": "Tích cực",
        "Score_offset": 0,
        "EvidenceIdxs": [],
        "traces": {
            "filter": {"should_scan": True, "reason": "filter_disabled",
                       "kw_hit": False, "llm_verdict": None, "applied": True},
            "scanner": {"violation": True, "category_raw": "C8",
                        "reason": "…", "evidence": "[00:03]: quote",
                        "evidence_idxs_raw": [3]},
            "decider": {"verdict": True, "reason": "…",
                        "cited_positives": ["P1"], "cited_carveouts": []},
            "primary_decider": {"verdict": False, "reason": "…",
                                  "cited_positives": [], "cited_carveouts": ["C2"]},
        },
    }
    base.update(overrides)
    return base


class TestCompare:
    def test_identical_no_diffs(self):
        row = _mk_row()
        hard, soft = _compare(row, row)
        assert hard == [] and soft == []

    def test_deep_copy_identical_no_diffs(self):
        """Same content but distinct object refs — compare must be value-based."""
        row_a = _mk_row()
        row_b = copy.deepcopy(row_a)
        hard, soft = _compare(row_a, row_b)
        assert hard == [] and soft == []

    def test_result_mismatch_is_HARD(self):
        actual = _mk_row(Result="Thái độ cao")
        baseline = _mk_row(Result="Tích cực")
        hard, soft = _compare(actual, baseline)
        assert any(d.startswith("Result:") for d in hard), \
            "Result flip must be HARD — user-visible drift"
        assert not any("Result" in d for d in soft)

    def test_score_offset_mismatch_is_HARD(self):
        actual = _mk_row(Score_offset=-10)
        baseline = _mk_row(Score_offset=0)
        hard, soft = _compare(actual, baseline)
        assert any("Score_offset" in d for d in hard)

    def test_evidence_idxs_order_matters(self):
        """`[3,5]` != `[5,3]` — order of turn refs is semantic."""
        actual = _mk_row(EvidenceIdxs=[3, 5])
        baseline = _mk_row(EvidenceIdxs=[5, 3])
        hard, _ = _compare(actual, baseline)
        assert any("EvidenceIdxs" in d for d in hard)

    def test_primary_verdict_change_is_HARD(self):
        """Regression: Claude verdict flip flags in HARD (may cascade to Result)."""
        actual = _mk_row()
        baseline = copy.deepcopy(actual)
        baseline["traces"]["primary_decider"]["verdict"] = True
        hard, _ = _compare(actual, baseline)
        assert any("primary.verdict" in d for d in hard)

    def test_cited_positives_change_is_SOFT(self):
        """LLM picks P1 vs P2 = same semantic pool, different label.
        Documented ~10-20% noise from Gemini reasoning — SOFT, not HARD."""
        actual = _mk_row()
        baseline = copy.deepcopy(actual)
        baseline["traces"]["decider"]["cited_positives"] = ["P1", "P2"]
        hard, soft = _compare(actual, baseline)
        assert not any("decider.cited_p" in d for d in hard), \
            "cited_positives is LLM noise, must NOT block"
        assert any("decider.cited_p" in d for d in soft)

    def test_scanner_category_change_is_SOFT(self):
        """C1 vs C4 = LLM's semantic swap. Downstream Result rule catches
        any real impact."""
        actual = _mk_row()
        baseline = copy.deepcopy(actual)
        baseline["traces"]["scanner"]["category_raw"] = "C4"
        hard, soft = _compare(actual, baseline)
        assert not any("scanner.category" in d for d in hard)
        assert any("scanner.category" in d for d in soft)

    def test_filter_meta_regression_is_HARD(self):
        """If `filter_meta` threading breaks (kw_hit / llm_verdict lost),
        the diff must land in HARD — historical bug, pure-python drift."""
        actual = _mk_row()
        actual["traces"]["filter"]["kw_hit"] = True
        actual["traces"]["filter"]["llm_verdict"] = True
        baseline = _mk_row()  # kw_hit=False, llm_verdict=None
        hard, _ = _compare(actual, baseline)
        assert any("filter.kw_hit" in d for d in hard)
        assert any("filter.llm_verdict" in d for d in hard)

    def test_reasoning_field_not_compared_anywhere(self):
        """`Reasoning` is fully LLM-generated — MUST not be in either tier
        (would fail every run, no diagnostic value)."""
        all_labels = {label for label, _ in _HARD_RULES + _SOFT_RULES}
        assert "Reasoning" not in all_labels

    def test_soft_rules_include_llm_noisy_fields(self):
        """Diagnostics (scripts/diag_pipeline_variance.py) confirmed these
        are Gemini/Claude non-det. Locking their placement in SOFT."""
        soft_labels = {label for label, _ in _SOFT_RULES}
        assert "decider.cited_p" in soft_labels
        assert "decider.cited_c" in soft_labels
        assert "primary.cited_p" in soft_labels
        assert "primary.cited_c" in soft_labels
        assert "scanner.category" in soft_labels

    def test_hard_rules_include_user_visible_and_pure_python(self):
        hard_labels = {label for label, _ in _HARD_RULES}
        # User-visible
        assert "Result" in hard_labels
        assert "Score_offset" in hard_labels
        assert "EvidenceIdxs" in hard_labels
        # Pure-python gates
        assert "filter.should_scan" in hard_labels
        assert "filter.applied" in hard_labels
        # LLM verdict booleans (stable across runs per diagnostic)
        assert "scanner.violation" in hard_labels
        assert "decider.verdict" in hard_labels
        assert "primary.verdict" in hard_labels

    def test_hard_and_soft_rules_are_disjoint(self):
        """Same field must not be in both — semantic conflict."""
        hard_labels = {label for label, _ in _HARD_RULES}
        soft_labels = {label for label, _ in _SOFT_RULES}
        assert hard_labels.isdisjoint(soft_labels)

    def test_missing_traces_stage_surfaces_as_diff(self):
        """If a baseline has primary_decider but actual doesn't, verdict
        None != True/False shows as HARD."""
        actual = _mk_row()
        del actual["traces"]["primary_decider"]
        baseline = _mk_row()
        hard, _ = _compare(actual, baseline)
        assert any("primary.verdict" in d for d in hard)
