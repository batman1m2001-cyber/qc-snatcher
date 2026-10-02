"""Unit tests for v4 matcher pool formatting + citation parsing.

These are the pure string builders that mediate between the retriever and
the decider LLM. They're deterministic, cheap to test, and any drift here
would silently corrupt the pool the decider sees.
"""
from __future__ import annotations

from src.cases.sentiment_agent._pools import (
    _format_indexed_pool,
    _parse_cited,
)

# ---------------------------------------------------------------------------
# _format_indexed_pool — retriever items → indexed prompt string
# ---------------------------------------------------------------------------


class TestFormatIndexedPoolEmpty:
    def test_empty_list(self):
        s, items = _format_indexed_pool([], "P")
        assert s == "(không có mẫu nào được retrieve)"
        assert items == []

    def test_none_list_treated_as_empty(self):
        # Falsy input path — mirrors what happens on retriever error.
        s, items = _format_indexed_pool([], "C")
        assert "không có mẫu" in s
        assert items == []


class TestFormatIndexedPoolSingleGroup:
    def test_single_item_single_variant(self):
        items = [{"parent_id": "pos_1", "text": "cút đi",
                  "description": "chửi thẳng", "category": "C8"}]
        s, out = _format_indexed_pool(items, "P")
        assert "[P1] sample:" in s
        assert '"cút đi"' in s
        assert "description: chửi thẳng" in s
        assert len(out) == 1
        assert out[0]["id"] == "P1"
        assert out[0]["text"] == "cút đi"

    def test_multi_variants_same_parent_joined_with_pipe(self):
        """Same parent_id → variants collapsed into one [P1] with ' | '."""
        items = [
            {"parent_id": "pos_1", "text": "cút đi", "description": "chửi", "category": "C8"},
            {"parent_id": "pos_1", "text": "cút xéo", "description": "chửi", "category": "C8"},
            {"parent_id": "pos_1", "text": "biến đi", "description": "chửi", "category": "C8"},
        ]
        s, out = _format_indexed_pool(items, "P")
        assert "[P1]" in s
        # No [P2] — all 3 variants under one group.
        assert "[P2]" not in s
        assert '"cút đi | cút xéo | biến đi"' in s
        assert len(out) == 1
        assert out[0]["text"] == "cút đi | cút xéo | biến đi"


class TestFormatIndexedPoolMultipleGroups:
    def test_two_parent_groups(self):
        items = [
            {"parent_id": "pos_1", "text": "cút đi", "description": "chửi", "category": "C8"},
            {"parent_id": "pos_2", "text": "im mồm", "description": "áp đặt", "category": "C11"},
        ]
        s, out = _format_indexed_pool(items, "P")
        assert "[P1]" in s
        assert "[P2]" in s
        assert len(out) == 2
        assert out[0]["id"] == "P1"
        assert out[1]["id"] == "P2"

    def test_prefix_switch_for_carveouts(self):
        items = [{"parent_id": "neg_1", "text": "anh giữ máy",
                  "description": "hướng dẫn", "category": "C8"}]
        s, out = _format_indexed_pool(items, "C")
        assert "[C1]" in s
        assert "[P" not in s
        assert out[0]["id"] == "C1"


class TestFormatIndexedPoolEdgeCases:
    def test_missing_parent_id_gets_synthetic_group(self):
        """Items lacking parent_id must still render — one group each."""
        items = [
            {"text": "sample A", "description": "d1", "category": "C1"},
            {"text": "sample B", "description": "d2", "category": "C2"},
        ]
        s, out = _format_indexed_pool(items, "P")
        assert "[P1]" in s
        assert "[P2]" in s
        assert len(out) == 2

    def test_missing_description_shows_placeholder(self):
        items = [{"parent_id": "pos_1", "text": "sample", "description": "",
                  "category": "C1"}]
        s, _ = _format_indexed_pool(items, "P")
        assert "(không có mô tả)" in s

    def test_missing_text_field_stays_empty(self):
        """No text — pool string still forms, empty content."""
        items = [{"parent_id": "pos_1", "description": "d", "category": "C1"}]
        s, out = _format_indexed_pool(items, "P")
        assert "[P1]" in s
        assert out[0]["text"] == ""

    def test_order_preserved(self):
        """Group order = first-seen parent_id order (OrderedDict)."""
        items = [
            {"parent_id": "z", "text": "z1", "description": "", "category": "C1"},
            {"parent_id": "a", "text": "a1", "description": "", "category": "C1"},
            {"parent_id": "m", "text": "m1", "description": "", "category": "C1"},
        ]
        _, out = _format_indexed_pool(items, "P")
        assert [o["id"] for o in out] == ["P1", "P2", "P3"]
        assert out[0]["text"] == "z1"
        assert out[1]["text"] == "a1"
        assert out[2]["text"] == "m1"


# ---------------------------------------------------------------------------
# _parse_cited — LLM emits list or comma-string of PN/CN ids
# ---------------------------------------------------------------------------


class TestParseCited:
    def test_none_returns_empty(self):
        assert _parse_cited(None, "P") == []

    def test_empty_list(self):
        assert _parse_cited([], "P") == []

    def test_empty_string(self):
        assert _parse_cited("", "P") == []

    def test_valid_list(self):
        assert _parse_cited(["P1", "P3", "P10"], "P") == ["P1", "P3", "P10"]

    def test_valid_comma_string(self):
        assert _parse_cited("P1, P2, P3", "P") == ["P1", "P2", "P3"]

    def test_case_normalised_to_upper(self):
        assert _parse_cited(["p1", "P2"], "P") == ["P1", "P2"]

    def test_whitespace_stripped(self):
        assert _parse_cited(["  P1  ", " P2"], "P") == ["P1", "P2"]

    def test_wrong_prefix_dropped(self):
        """P prefix requested — C ids silently dropped, not raised."""
        assert _parse_cited(["P1", "C2", "P3"], "P") == ["P1", "P3"]

    def test_bare_numbers_dropped(self):
        """LLM sometimes returns bare '1' — must not slip through as P1."""
        assert _parse_cited(["1", "P2"], "P") == ["P2"]

    def test_malformed_dropped(self):
        assert _parse_cited(["PP1", "Pabc", "P", "1P"], "P") == []

    def test_prefix_c_only_matches_c(self):
        assert _parse_cited(["P1", "C1", "C2"], "C") == ["C1", "C2"]

    def test_non_list_non_string_returns_empty(self):
        """Defensive: dict or int → empty, not crash."""
        assert _parse_cited({"a": 1}, "P") == []
        assert _parse_cited(42, "P") == []
        assert _parse_cited(True, "P") == []

    def test_comma_string_with_blanks(self):
        assert _parse_cited("P1,,P2, ,P3", "P") == ["P1", "P2", "P3"]

    def test_two_digit_indices(self):
        assert _parse_cited(["P10", "P11", "P100"], "P") == ["P10", "P11", "P100"]
