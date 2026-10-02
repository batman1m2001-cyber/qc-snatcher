"""Regression tests for output format bugs discovered in production.

Covers 3 bug classes that broke go-live:

  1. **Sentiment_agent format_row default catching too much** — before the
     01/07 fix, `else` branch mapped `khach_la_tre_em` / `none` / unknown
     categories to "ĐTV im lặng" instead of "Tích cực". Positive calls
     showed as "ĐTV im lặng" in the UI. See spec.py history.

  2. **is_violation case-sensitivity** — XML parser drift ("True", "TRUE",
     " true ") slipped through as False before the R1 fix.

  3. **EvidenceIdxs field lost on restore** — partial re-runs with a
     whitelist that disabled sentiment_agent stripped the clickable
     turn-chip data from the output before EvidenceIdxs was added to
     _RESTORE_KEYS.

Each test locks in the intended behaviour so future refactors can't
silently regress these paths.
"""


import pytest

from src.cases.sentiment_agent import format_sentiment_agent as sentiment_agent_row
from src.cases.sentiment_customer import (
    format_sentiment_customer as sentiment_customer_row,
)
from src.cases._shared.spec import default_sentiment_row, is_violation
from src.qc.ops import NOT_RUN

# ---------------------------------------------------------------------------
# 1. Sentiment agent format_row — category → label mapping
# ---------------------------------------------------------------------------


class TestSentimentAgentCategoryMapping:
    """Locks in the C*/N*/im_lang/other split from spec.py after 01/07 fix."""

    @pytest.mark.parametrize("category", [
        "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11",
    ])
    def test_c_codes_map_to_high(self, category):
        row = sentiment_agent_row({"violation": True, "category": category, "reason": "x"})
        assert row["Result"] == "Thái độ cao"
        assert row["Score_offset"] == -10

    @pytest.mark.parametrize("category", ["N1", "N2", "N3", "N4"])
    def test_n_codes_map_to_severe(self, category):
        row = sentiment_agent_row({"violation": True, "category": category, "reason": "x"})
        assert row["Result"] == "Thái độ nghiêm trọng"
        assert row["Score_offset"] == -25

    def test_im_lang_maps_to_silent(self):
        row = sentiment_agent_row({"violation": False, "category": "im_lang", "reason": ""})
        assert row["Result"] == "ĐTV im lặng"
        assert row["Score_offset"] == 0

    def test_regression_khach_la_tre_em_is_tich_cuc(self):
        """Go-live bug: kid-call was labelled 'ĐTV im lặng'. Must be 'Tích cực'."""
        row = sentiment_agent_row({
            "violation": False,
            "category": "khach_la_tre_em",
            "reason": "Người nghe là trẻ em — bỏ qua đánh giá thái độ ĐTV",
        })
        assert row["Result"] == "Tích cực"
        assert row["Score_offset"] == 0

    def test_regression_none_category_is_tich_cuc(self):
        """No-violation verdict from verifier (category='none') is a positive call."""
        row = sentiment_agent_row({"violation": False, "category": "none", "reason": ""})
        assert row["Result"] == "Tích cực"
        assert row["Score_offset"] == 0

    def test_regression_empty_category_is_tich_cuc(self):
        row = sentiment_agent_row({"violation": False, "category": "", "reason": ""})
        assert row["Result"] == "Tích cực"

    def test_regression_unknown_category_is_tich_cuc(self):
        """Unknown code (typo, model drift) must NOT slip into 'ĐTV im lặng'."""
        row = sentiment_agent_row({"violation": True, "category": "X99", "reason": ""})
        assert row["Result"] == "Tích cực"

    def test_none_result_is_tich_cuc(self):
        row = sentiment_agent_row(None)
        assert row["Result"] == "Tích cực"
        assert row == default_sentiment_row()

    def test_category_none_type_is_tich_cuc(self):
        """result dict with category=None (not string) must not crash."""
        row = sentiment_agent_row({"violation": False, "category": None, "reason": ""})
        assert row["Result"] == "Tích cực"

    def test_category_whitespace_stripped(self):
        row = sentiment_agent_row({"violation": True, "category": " C1 ", "reason": ""})
        assert row["Result"] == "Thái độ cao"


# ---------------------------------------------------------------------------
# 2. Sentiment agent Evidence + EvidenceIdxs fields
# ---------------------------------------------------------------------------


class TestSentimentAgentEvidenceField:
    """Evidence is the `evidence` display text (before a fix it was always
    empty for sentiment_agent)."""

    def test_evidence_is_the_display_text(self):
        row = sentiment_agent_row({
            "violation": True, "category": "C1", "evidence": "[01:00]: agent quote",
        })
        assert row["Evidence"] == "[01:00]: agent quote"

    def test_empty_when_absent(self):
        row = sentiment_agent_row({"violation": True, "category": "C1"})
        assert row["Evidence"] == ""


class TestSentimentAgentEvidenceIdxs:
    """EvidenceIdxs powers clickable turn chips in qc-monitor UI."""

    def test_int_list_passes_through(self):
        row = sentiment_agent_row({
            "violation": True, "category": "C1", "evidence_idxs": [3, 5, 12],
        })
        assert row["EvidenceIdxs"] == [3, 5, 12]

    def test_string_ints_are_coerced(self):
        row = sentiment_agent_row({
            "violation": True, "category": "C1", "evidence_idxs": ["3", "5"],
        })
        assert row["EvidenceIdxs"] == [3, 5]

    def test_invalid_entries_dropped(self):
        row = sentiment_agent_row({
            "violation": True, "category": "C1",
            "evidence_idxs": [3, "abc", None, 7, ""],
        })
        assert row["EvidenceIdxs"] == [3, 7]

    def test_missing_defaults_to_empty(self):
        row = sentiment_agent_row({"violation": True, "category": "C1"})
        assert row["EvidenceIdxs"] == []

    def test_a_string_reads_like_every_other_case(self):
        """`turn_idxs`, shared by every case: "3,5" is two turns."""
        row = sentiment_agent_row({
            "violation": True, "category": "C1", "evidence_idxs": "3,5",
        })
        assert row["EvidenceIdxs"] == [3, 5]

    def test_anything_else_becomes_empty(self):
        row = sentiment_agent_row({
            "violation": True, "category": "C1", "evidence_idxs": 3,
        })
        assert row["EvidenceIdxs"] == []

    def test_high_violation_row_has_evidence_idxs_key(self):
        """Guards against dropping the additive field on any C*/N* branch."""
        row = sentiment_agent_row({"violation": True, "category": "N1"})
        assert "EvidenceIdxs" in row


# ---------------------------------------------------------------------------
# 3. Sentiment_customer format_row (defensive tests to match the fix)
# ---------------------------------------------------------------------------


class TestSentimentCustomerFormat:

    def test_im_lang_kh(self):
        row = sentiment_customer_row({"violation": False, "category": "im_lang"})
        assert row["Result"] == "KH im lặng"

    def test_violation_tieu_cuc(self):
        row = sentiment_customer_row({"violation": True, "reason": "khách bức xúc"})
        assert row["Result"] == "Tiêu cực"

    def test_no_result_tich_cuc(self):
        row = sentiment_customer_row(None)
        assert row["Result"] == "Tích cực"

    def test_non_matching_defaults_to_tich_cuc(self):
        row = sentiment_customer_row({"violation": False, "category": "other"})
        assert row["Result"] == "Tích cực"


# ---------------------------------------------------------------------------
# 4. is_violation robustness (R1 fix — XML parser drift)
# ---------------------------------------------------------------------------


class TestIsViolationRobustness:
    """LLM XML parser output varies: sometimes bool, sometimes string with
    mixed case or padding. `is_violation` must normalise all of these."""

    def test_bool_true(self):
        assert is_violation({"violation": True}) is True

    def test_bool_false(self):
        assert is_violation({"violation": False}) is False

    @pytest.mark.parametrize("raw", ["true", "True", "TRUE", " true ", "  True\n"])
    def test_string_true_variants(self, raw):
        assert is_violation({"violation": raw}) is True

    @pytest.mark.parametrize("raw", ["false", "False", "FALSE", "", "  ", "no"])
    def test_string_false_variants(self, raw):
        assert is_violation({"violation": raw}) is False

    def test_none_value(self):
        assert is_violation({"violation": None}) is False

    def test_none_result(self):
        assert is_violation(None) is False

    def test_empty_result(self):
        assert is_violation({}) is False

    def test_bool_false_string_does_not_leak(self):
        """Python quirk: bool('false') is True. Ensure we do explicit check."""
        assert is_violation({"violation": "false"}) is False


# ---------------------------------------------------------------------------
# 5. A switched-off case's row (the qc-monitor restore that stood here is gone)
# ---------------------------------------------------------------------------


class TestNotRunRow:
    """`Không chạy` must carry every field a row has, EvidenceIdxs included —
    a consumer reading `row["EvidenceIdxs"]` must not KeyError on it."""

    def test_not_run_fields(self):
        assert NOT_RUN == {"Result": "Không chạy", "Reasoning": "", "Evidence": "",
                           "Score_offset": 0, "EvidenceIdxs": []}


# ---------------------------------------------------------------------------
# 6. Traces stage whitelist (regression: `filter` was dropped from the tuple)
# ---------------------------------------------------------------------------




class TestTracesFilterStageIncluded:
    """`_build_traces` has an explicit stage whitelist. `filter` was
    accidentally missing once — filter meta was populated but got stripped
    by the formatter before hitting the output row. Lock the whitelist so
    that regression can't slip back in."""

    _RESULT_WITH_FILTER = {
        "violation": True,
        "category": "C8",
        "reason": "agent nói xấu",
        "evidence": "[00:03]: quote",
        "evidence_idxs": [3],
        "_trace_meta": {
            "filter": {
                "should_scan": True,
                "reason": "filter_llm_flagged",
                "kw_hit": False,
                "llm_verdict": True,
                "applied": True,
            },
            "scanner": {"violation": True, "category_raw": "C8"},
            "decider": {"verdict": True, "reason": "confirmed"},
        },
    }

    def test_on_mode_includes_filter_stage(self):
        row = sentiment_agent_row(self._RESULT_WITH_FILTER, include_traces=True)
        assert "traces" in row
        assert "filter" in row["traces"], (
            "filter stage must be in traces whitelist — regression against "
            "the earlier bug where filter meta was stripped by the formatter"
        )
        # Filter meta must round-trip intact.
        assert row["traces"]["filter"]["llm_verdict"] is True
        assert row["traces"]["filter"]["applied"] is True

    def test_on_mode_keeps_stage_order(self):
        """Stage order must match the whitelist tuple for UI predictability."""
        row = sentiment_agent_row(self._RESULT_WITH_FILTER, include_traces=True)
        keys = list(row["traces"].keys())
        assert keys.index("filter") < keys.index("scanner") < keys.index("decider")

    def test_off_mode_produces_no_traces_key(self):
        row = sentiment_agent_row(self._RESULT_WITH_FILTER, include_traces=False)
        assert "traces" not in row
