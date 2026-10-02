"""Tests for `_finalize` + the flat CASES catalog.

`_finalize` fuses the old `_aggregate`/`_post_process` split — takes each
case's raw result as a kwarg, calls format_<id>, prefixes Criteria, and
returns `{"call_scoring": {...}}`. Called via `.__wrapped__` so we exercise
the real function without spinning up a operonx engine.
"""

import pytest

from src.cases import CASES, CRITERIA_TO_CASE_ID
from src.qc.ops import _finalize


#: What an enabled case that ran and cleared the call hands `_finalize`.
CLEARED = {"violation": False, "reason": ""}


def finalize(**kwargs) -> dict:
    """`_finalize` with every enabled case the test does not name cleared."""
    from src.core import config

    for cid in CASES:
        if cid not in kwargs and cid in config.ENABLED_CASES:
            kwargs[cid] = CLEARED
    return _finalize.__wrapped__(**kwargs)["call_scoring"]


@pytest.fixture(autouse=True)
def _all_cases_on(monkeypatch):
    """These tests are about formatting, not about which cases this
    machine's env switches off."""
    from src.core import config

    monkeypatch.setattr(config, "ENABLED_CASES", frozenset(CASES))


class TestSwitchedOffCase:
    """A case switched off by `QC_ENABLE_<ID>=false` ran nothing. Its row
    must say so — the formatter default would read as a clean verdict."""

    def test_disabled_and_empty_reads_khong_chay(self, monkeypatch):
        from src.core import config

        monkeypatch.setattr(config, "ENABLED_CASES", frozenset({"sentiment_agent"}))
        scoring = finalize()
        rows = {r["Criteria"]: r for r in scoring["HVC"] + scoring["Sentiment"]}
        hangup = rows[CASES["hangup"].criteria]
        assert hangup["Result"] == "Không chạy" and hangup["EvidenceIdxs"] == []
        assert list(hangup)[-1] == "EvidenceIdxs"  # appended, as the old restore did
        agent = rows[CASES["sentiment_agent"].criteria]
        assert agent["Result"] != "Không chạy"
        assert scoring["qc_score_total_offset"] == 0

    def test_a_verdict_is_never_overwritten(self, monkeypatch):
        from src.core import config

        monkeypatch.setattr(config, "ENABLED_CASES", frozenset({"sentiment_agent"}))
        scoring = finalize(hangup={"violation": "true", "reason": "x", "evidence": ""})
        hangup = next(r for r in scoring["HVC"] if r["Criteria"] == CASES["hangup"].criteria)
        assert hangup["Result"] != "Không chạy"


class TestFinalizeDefaults:
    """When every case ran and cleared the call, every row is clean."""

    def test_an_enabled_case_with_no_verdict_raises(self):
        """A lost result must not be written as `Không vi phạm` / `Tích cực`."""
        with pytest.raises(RuntimeError, match="raba produced no verdict"):
            _finalize.__wrapped__(**{cid: CLEARED for cid in CASES if cid != "raba"})

    def test_row_counts(self):
        scoring = finalize()
        assert len(scoring["HVC"]) == 5
        assert len(scoring["Sentiment"]) == 2
        assert scoring["qc_score_total_offset"] == 0

    def test_sentiment_defaults_tich_cuc(self):
        scoring = finalize()
        for row in scoring["Sentiment"]:
            assert row["Result"] == "Tích cực"
            assert row["Score_offset"] == 0

    def test_hvc_defaults_khong_vi_pham(self):
        scoring = finalize()
        for row in scoring["HVC"]:
            assert row["Result"] == "Không vi phạm"
            assert row["Score_offset"] == 0

    def test_hvc_row_keys(self):
        scoring = finalize()
        expected = {"Criteria", "CriteriaCode", "Reasoning", "Result", "Evidence", "Score_offset"}
        for row in scoring["HVC"]:
            assert set(row.keys()) == expected

    def test_sentiment_row_keys_customer(self):
        scoring = finalize()
        # sentiment_customer default row has 5 fields (incl. CriteriaCode)
        expected = {"Criteria", "CriteriaCode", "Reasoning", "Result", "Evidence", "Score_offset"}
        assert set(scoring["Sentiment"][1].keys()) == expected

    def test_hvc_render_order(self):
        scoring = finalize()
        order = [r["Criteria"] for r in scoring["HVC"]]
        assert order == [
            "Treo máy/cố tình ngắt máy",
            "Gian lận Raba",
            "Lỗi trao đổi thông tin của KH cho BT3 không quen biết",
            "Cung cấp 16 số in dập nổi trên thẻ của KH",
            "Cung cấp nguồn truy dấu thông tin của KH/BT3",
        ]

    def test_sentiment_render_order(self):
        scoring = finalize()
        assert [r["Criteria"] for r in scoring["Sentiment"]] == ["Thái độ ĐTV", "Thái độ KH"]


class TestFinalizeViolations:
    """Score offsets and labels for the common per-case violation shapes."""

    def test_hangup_violation(self):
        scoring = finalize(
            hangup={"violation": True, "reason": "treo máy",
                    "evidence": "[00:15]: em xin phép", "evidence_idxs": [3]},
        )
        row = scoring["HVC"][0]
        assert row["Result"] == "Vi phạm"
        assert row["Score_offset"] == -25
        assert row["Reasoning"] == "treo máy"
        assert row["Evidence"] == "[00:15]: em xin phép"
        assert row["EvidenceIdxs"] == [3]
        assert scoring["qc_score_total_offset"] == -25

    def test_raba_violation_score(self):
        scoring = finalize(raba={"violation": True, "reason": "gian lận"})
        row = scoring["HVC"][1]
        assert row["Result"] == "Vi phạm"
        assert row["Score_offset"] == -100

    def test_disclosure_violation_score(self):
        scoring = finalize(disclosure={"violation": True, "reason": "tiết lộ"})
        assert scoring["HVC"][2]["Score_offset"] == -100

    def test_card_number_violation_score(self):
        scoring = finalize(card_number={"violation": True, "reason": "đọc thẻ"})
        assert scoring["HVC"][3]["Score_offset"] == -100

    def test_phone_source_violation_score(self):
        scoring = finalize(phone_source={"violation": True, "reason": "lộ nguồn"})
        assert scoring["HVC"][4]["Score_offset"] == -100

    def test_agent_sentiment_high(self):
        scoring = finalize(
            sentiment_agent={"violation": True, "category": "C1", "reason": "xấu"},
        )
        row = scoring["Sentiment"][0]
        assert row["Result"] == "Thái độ cao"
        assert row["Score_offset"] == -10

    def test_agent_sentiment_severe(self):
        scoring = finalize(
            sentiment_agent={"violation": True, "category": "N1", "reason": "rất xấu"},
        )
        row = scoring["Sentiment"][0]
        assert row["Result"] == "Thái độ nghiêm trọng"
        assert row["Score_offset"] == -25

    def test_customer_silent(self):
        scoring = finalize(
            sentiment_customer={"violation": False, "category": "im_lang", "reason": ""},
        )
        row = scoring["Sentiment"][1]
        assert row["Result"] == "KH im lặng"
        assert row["Score_offset"] == 0

    def test_customer_negative(self):
        scoring = finalize(sentiment_customer={"violation": True, "reason": "bức xúc"})
        assert scoring["Sentiment"][1]["Result"] == "Tiêu cực"

    def test_multi_violation_total(self):
        scoring = finalize(
            hangup={"violation": True, "reason": "treo máy"},
            raba={"violation": True, "reason": "gian lận"},
            sentiment_agent={"violation": True, "category": "C1", "reason": "xấu"},
        )
        assert scoring["qc_score_total_offset"] == -25 + -100 + -10


class TestCasesCatalog:
    """Sanity checks on the flat CASES dict."""

    def test_all_ids(self):
        assert set(CASES) == {
            "hangup", "raba", "disclosure", "card_number",
            "phone_source", "sentiment_agent", "sentiment_customer",
        }

    def test_sections(self):
        sections = {cid: c.section for cid, c in CASES.items()}
        assert sections["hangup"] == "HVC"
        assert sections["raba"] == "HVC"
        assert sections["disclosure"] == "HVC"
        assert sections["card_number"] == "HVC"
        assert sections["phone_source"] == "HVC"
        assert sections["sentiment_agent"] == "Sentiment"
        assert sections["sentiment_customer"] == "Sentiment"

    def test_criteria_map_inverse(self):
        # every case criteria round-trips through CRITERIA_TO_CASE_ID
        for cid, c in CASES.items():
            assert CRITERIA_TO_CASE_ID[c.criteria] == cid

    @pytest.mark.parametrize("cid", list(CASES.keys()), ids=lambda x: x)
    def test_format_row_default_shape(self, cid):
        """Every case's format function returns a valid row on None input."""
        row = CASES[cid].format(None)
        # sentiment_agent adds "EvidenceIdxs" to the shape — accept both.
        base = {"Reasoning", "Result", "Evidence", "Score_offset"}
        assert base.issubset(row.keys())
        assert row["Score_offset"] == 0

    @pytest.mark.parametrize("cid", list(CASES.keys()), ids=lambda x: x)
    def test_verify_and_format_callables(self, cid):
        c = CASES[cid]
        assert callable(c.verify)
        assert callable(c.format)
