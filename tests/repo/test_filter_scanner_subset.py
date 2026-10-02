"""The filter prompt may be a subset of the scanner, never a superset.

`FILTER_PROMPT` is a hand-fork of `SCANNER_PROMPT`. A cheap pre-filter
being *shorter* is by design. What is not by design is the filter holding
knowledge the scanner lacks — the filter only decides whether to run the
scanner at all, so anything it knows and the scanner does not is knowledge
that never reaches a verdict.

That is how six QC rulings went dark: they were written into the filter
during the 2026-07-10/11 review rounds, the scanner never got them, and the
filter was later disabled in `.env`. Nothing failed; the rulings simply
stopped applying.

These tests pin the direction of that relationship. No LLM, no network.
"""
import re

import pytest

from src.core.prompts import PROMPTS

SCANNER = "SCANNER_PROMPT"
FILTER = "FILTER_PROMPT"

# Phrases QC ruled must NOT be flagged. Written as `KHÔNG bắt ...` in the
# scanner and `... KHÔNG bắt vi phạm` in the filter, so match on the quoted
# term rather than the sentence shape.
_QUOTED = re.compile(r'"([^"]+)"')


def _negative_rule_terms(key: str) -> set[str]:
    """Quoted terms appearing on a line that says KHÔNG bắt."""
    terms: set[str] = set()
    for line in PROMPTS[key].splitlines():
        if "KHÔNG bắt" not in line:
            continue
        for q in _QUOTED.findall(line):
            terms.update(p.strip().lower() for p in q.split("|") if p.strip())
    return terms


def _codes(key: str) -> set[str]:
    return set(re.findall(r"^\*\*(C\d+|N\d+)\.", PROMPTS[key], re.MULTILINE))


def test_filter_declares_no_code_the_scanner_lacks():
    """A code the filter knows and the scanner does not can never produce a
    verdict — the filter only gates whether the scanner runs."""
    extra = sorted(_codes(FILTER) - _codes(SCANNER),
                   key=lambda c: (c[0], int(c[1:])))
    assert not extra, (
        f"{FILTER} declares {extra} which {SCANNER} does not — either add them "
        f"to the scanner or drop them from the filter."
    )


def test_filter_holds_no_negative_rule_the_scanner_lacks():
    """The regression that cost six QC rulings.

    Every `KHÔNG bắt` term in the filter must also appear in the scanner.
    The reverse is fine: the scanner may know more.
    """
    filter_terms = _negative_rule_terms(FILTER)
    scanner_text = PROMPTS[SCANNER].lower()

    missing = sorted(t for t in filter_terms if t not in scanner_text)
    assert not missing, (
        f"{FILTER} rules out {missing} but {SCANNER} has never heard of them. "
        f"A QC ruling that lives only in the filter does not apply to any "
        f"verdict — and stops applying entirely when the filter is disabled."
    )


@pytest.mark.parametrize("term,where", [
    ("trì hoãn", "C1"),
    ("thả trôi", "C1"),
    ("không thiện chí", "C1"),
    ("sai sự thật", "C1"),
    ("mô tả khách quan", "LỚP 0"),
])
def test_recovered_qc_rulings_are_present(term, where):
    """The five rulings merged back into the scanner on 2026-08-14.

    `con nợ` is deliberately NOT here: it is handled at the precision tier by
    the ASR-check route (`_HEAVY_KW_PATTERNS` in v4/_asr_check.py), which
    inspects surrounding tone instead of suppressing it outright. A blanket
    scanner rule would make that routing dead code.
    """
    assert term in PROMPTS[SCANNER].lower(), f"{term} ({where}) missing from {SCANNER}"


def test_con_no_is_left_to_the_asr_route():
    """Guard the decision above: if someone later adds a blanket `KHÔNG bắt
    "con nợ"` to the scanner, the ASR-check branch silently stops mattering."""
    assert "con nợ" not in _negative_rule_terms(SCANNER), (
        'scanner now rules out "con nợ" outright, which bypasses the ASR-check '
        "route that exists to judge it in context. Remove the rule, or remove "
        "the route in v4/_asr_check.py — but not both."
    )
