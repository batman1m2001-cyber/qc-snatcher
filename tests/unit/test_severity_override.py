"""Corpus severity, not the scanner's category, decides the score.

The scanner picks a category (`C1..C11` / `N1..N5`) and that used to be the
only thing scoring looked at: `C*` -> -10, `N*` -> -25. Corpus severity was
retrieval metadata and reached nothing, so QC's `warning` tier — added
2026-08-19 and covering 253 entries — could not appear in a result at all.

The decider tells us which entries it cited, and corpus.yaml is what QC
maintains, so the cited entry's severity is the better answer. These tests
pin the two places that can go quietly wrong: which severity wins when
several are cited, and what happens when none resolves.

No LLM, no network — the override is a lookup on data already in hand.
"""

import pytest

from src.cases.sentiment_agent import format_sentiment_agent
from src.cases.sentiment_agent.l4_verify.ops import (
    apply_primary_fn,
    format_primary_pools_fn,
    resolve_cited_severity,
)


def unwrap(op):
    """Reach the plain function behind an @op."""
    return getattr(op, "__wrapped__", op)


SEVERITY_BY_ID = {"P1": "warning", "P2": "cao", "P3": "nghiem_trong", "P4": ""}


# ── which severity wins ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "cited, expected",
    [
        (["P1"], "warning"),
        (["P2"], "cao"),
        (["P3"], "nghiem_trong"),
        # Most severe wins regardless of citation order. A serious phrase
        # must not be masked by a mild one cited alongside it.
        (["P1", "P2"], "cao"),
        (["P1", "P3"], "nghiem_trong"),
        (["P3", "P2", "P1"], "nghiem_trong"),
        (["P2", "P3"], "nghiem_trong"),
    ],
)
def test_most_severe_cited_entry_wins(cited, expected):
    assert resolve_cited_severity(cited, SEVERITY_BY_ID) == expected


@pytest.mark.parametrize("cited", [[], None, ["P9"], ["P4"]])
def test_unresolvable_citations_yield_nothing(cited):
    """No citations, an unknown id, or an entry with no severity.

    Returns "" so the scanner's category stays in charge — inventing a
    verdict out of an empty lookup would score calls on nothing.
    """
    assert resolve_cited_severity(cited, SEVERITY_BY_ID) == ""


def test_empty_map_yields_nothing():
    assert resolve_cited_severity(["P1"], {}) == ""
    assert resolve_cited_severity(["P1"], None) == ""


# ── the override reaches the score, both directions ───────────────────


@pytest.mark.parametrize(
    "result, label, score",
    [
        # No override -> category decides, exactly as before.
        ({"category": "C8"}, "Thái độ cao", -10),
        ({"category": "N2"}, "Thái độ nghiêm trọng", -25),
        ({"category": "im_lang"}, "ĐTV im lặng", 0),
        # The tier the scanner has no code for.
        ({"category": "C8", "severity_final": "warning"}, "Thái độ warning", 0),
        # Downwards: a scanner N* whose cited entry QC grades `cao`.
        ({"category": "N2", "severity_final": "cao"}, "Thái độ cao", -10),
        # Upwards: a scanner C* whose cited entry QC grades `nghiem_trong`.
        ({"category": "C8", "severity_final": "nghiem_trong"},
         "Thái độ nghiêm trọng", -25),
        # Blank / unknown severity falls back rather than scoring on junk.
        ({"category": "C8", "severity_final": ""}, "Thái độ cao", -10),
        ({"category": "C8", "severity_final": "bogus"}, "Thái độ cao", -10),
    ],
)
def test_corpus_severity_outranks_category(result, label, score):
    row = format_sentiment_agent({**result, "reason": "x"})
    assert row["Result"] == label
    assert row["Score_offset"] == score


def test_warning_is_a_fourth_result_value():
    """Guards a silent failure mode for consumers.

    An unrecognised Result used to fall through to "Tích cực", so a
    warning-tier call would have been indistinguishable from a clean one.
    """
    row = format_sentiment_agent({"category": "C1", "severity_final": "warning",
                                  "reason": "x"})
    assert row["Result"] == "Thái độ warning"
    assert row["Result"] != "Tích cực"


# ── wiring: the map is built, threaded, and applied ───────────────────


def test_pools_expose_severity_for_positives_only():
    """A carveout is a reason NOT to flag, so it has no severity to give."""
    out = unwrap(format_primary_pools_fn)(
        query="q",
        positives=[{"parent_id": "POS-1", "text": "a", "severity": "warning"}],
        carveouts=[{"parent_id": "CVO-1", "text": "b", "severity": "tich_cuc"}],
    )
    assert out["severity_by_id"] == {"P1": "warning"}


def test_empty_query_yields_empty_map():
    out = unwrap(format_primary_pools_fn)(query="  ", positives=[], carveouts=[])
    assert out["severity_by_id"] == {}


def test_agree_applies_the_override():
    out = unwrap(apply_primary_fn)(
        raw_result={"category": "C8", "violation": "true", "reason": "r"},
        primary_out={"violation": True, "reason": "agree",
                       "cited_positives": ["P1"], "cited_carveouts": []},
        severity_by_id={"P1": "warning"},
    )["result"]
    assert out["severity_final"] == "warning"
    assert out["_trace_meta"]["primary_decider"]["severity_final"] == "warning"
    assert format_sentiment_agent(out)["Score_offset"] == 0


def test_disagree_does_not_apply_the_override():
    """A disagreement drops the violation outright. There is no severity to
    assign to something that is not a violation."""
    out = unwrap(apply_primary_fn)(
        raw_result={"category": "C8", "violation": "true", "reason": "r"},
        primary_out={"violation": False, "reason": "no",
                       "cited_positives": ["P1"], "cited_carveouts": ["C1"]},
        severity_by_id={"P1": "nghiem_trong"},
    )["result"]
    assert "severity_final" not in out
    assert out["category"] == "none"
    assert format_sentiment_agent(out)["Result"] == "Tích cực"


def test_primary_skipped_leaves_category_in_charge():
    """Primary decider switched off in models.yaml — the LLM never fires, so
    there are no citations and nothing to override with."""
    out = unwrap(apply_primary_fn)(
        raw_result={"category": "N1", "violation": "true", "reason": "r"},
        primary_out=None,
        severity_by_id={"P1": "warning"},
    )["result"]
    assert "severity_final" not in out
    assert format_sentiment_agent(out)["Score_offset"] == -25
