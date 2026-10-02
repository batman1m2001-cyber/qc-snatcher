"""The scanner owns the taxonomy; the primary decider must not have one.

The scanner emits a category code. The primary decider re-judges that
verdict — but only against the retrieved corpus pools, which is the policy
QC actually maintains.

**Until 2026-08-24 the primary decider carried its own copy of the
taxonomy**, and the two prompts had to agree code-for-code. They did not,
and the failures were silent:

  * `N1` meant "mỉa mai / kích động leo thang" to the scanner and
    "xưng mày/tao, chửi tục" to the primary decider — two different
    violations under one code.
  * `C6` meant "cáo buộc KH xúc phạm nhân viên" to the scanner and
    "câu hỏi tu từ chế giễu" (the scanner's C11) to the primary decider.
  * `N2`, `N3`, `N4` were emitted by the scanner and undefined for the
    primary decider, while retired `C12` was still taught to it.

Keeping the two in sync was never the real fix. The taxonomy codes `C1..C11`
collide with the carveout pool ids, which are also `C1, C2, …` — the same
token meaning "a violation group" and "a reason NOT to flag". In the
2026-08-11..13 QC batch, six of 47 penalised calls justified a -10 by
naming taxonomy `C11` while citing no pool id at all, which the prompt's
own rule 4 forbids.

So the taxonomy block and the `{category}` input were removed from the
primary decider, matching `DECIDER_PROMPT`, which has always judged on
pools alone. These tests now pin the absence — re-adding the table would
bring the collision back.

No LLM, no network.
"""
import re

import pytest

from src.core.prompts import PROMPTS

SCANNER = "SCANNER_PROMPT"
PRIMARY = "PRIMARY_DECIDER_PROMPT"
FILTER_DECIDER = "DECIDER_PROMPT"

# `**C1. …` section headers in the scanner's LỚP 1 / LỚP 4 blocks.
_SCANNER_SECTION = re.compile(r"^\*\*(C\d+|N\d+)\.", re.MULTILINE)
# `  C1. AGENT …` entries — the shape the primary decider's taxonomy had.
_TAXONOMY_ENTRY = re.compile(r"^\s{2,}(C\d+|N\d+)\.", re.MULTILINE)
# The `"category": "C1|C2|…|none"` enum in the scanner's output schema.
_CATEGORY_ENUM = re.compile(r'"category":\s*"([^"]+)"')


def _codes(pattern: re.Pattern, key: str) -> list[str]:
    return pattern.findall(PROMPTS[key])


def _sorted_codes(codes) -> list[str]:
    return sorted(set(codes), key=lambda c: (c[0], int(c[1:])))


# ── the deciders judge on pools, not on a taxonomy ────────────────────


@pytest.mark.parametrize("key", [PRIMARY, FILTER_DECIDER])
def test_decider_carries_no_taxonomy(key):
    found = _sorted_codes(_codes(_TAXONOMY_ENTRY, key))
    assert not found, (
        f"{key} defines taxonomy codes {found}. Those collide with the "
        f"carveout pool ids (also C1, C2, …), so the model can cite a "
        f"taxonomy group as if it were a policy. The pools are the only "
        f"source of truth — see this module's docstring."
    )


@pytest.mark.parametrize("key", [PRIMARY, FILTER_DECIDER])
def test_decider_is_not_given_the_scanner_category(key):
    """A code with no table to decode it invites the model to invent a
    meaning — the same failure, with the evidence removed."""
    assert "{category}" not in PROMPTS[key], (
        f"{key} takes `{{category}}` but defines no taxonomy to read it "
        f"against."
    )


@pytest.mark.parametrize("key", [PRIMARY, FILTER_DECIDER])
def test_decider_still_receives_both_pools(key):
    """The counterweight: removing the taxonomy is only safe while the
    pools — the actual policy — are still supplied."""
    for placeholder in ("{positives}", "{carveouts}"):
        assert placeholder in PROMPTS[key], f"{key} is missing {placeholder}"


# ── the scanner is where the taxonomy lives, and must stay coherent ────


def test_scanner_output_enum_matches_its_own_sections():
    """The scanner lists its codes twice: as `**C1.` headers and in the
    `"category"` enum of the output schema. A code in one but not the other
    is either unreachable or unparseable."""
    sections = set(_codes(_SCANNER_SECTION, SCANNER))
    enum_raw = _CATEGORY_ENUM.search(PROMPTS[SCANNER])
    assert enum_raw, f"{SCANNER}: no `category` enum found in the output schema"
    enum = {c for c in enum_raw.group(1).split("|") if c != "none"}

    assert not _sorted_codes(sections - enum), (
        f"{SCANNER}: {_sorted_codes(sections - enum)} documented as sections but "
        f"absent from the `category` enum — the model is told to detect them and "
        f"given no way to report them."
    )
    assert not _sorted_codes(enum - sections), (
        f"{SCANNER}: {_sorted_codes(enum - sections)} in the `category` enum with "
        f"no matching section — emittable but undefined."
    )


def test_no_code_defined_twice():
    codes = _codes(_SCANNER_SECTION, SCANNER)
    dupes = sorted({c for c in codes if codes.count(c) > 1})
    assert not dupes, f"{SCANNER}: {dupes} defined more than once"


def test_retired_c12_is_absent_from_the_scanner():
    """C12 (side-chatter) was retired 2026-07-29 after a 969-call diagnostic
    showed ~100% FP. It must not reappear in a prompt that still runs."""
    assert "C12" not in set(_codes(_SCANNER_SECTION, SCANNER)), (
        f"{SCANNER}: C12 is retired but still defined"
    )
