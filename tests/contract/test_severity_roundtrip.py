"""Corpus severity has to survive a trip through Postgres.

Scoring reads the severity of the entry the primary decider cited:
`warning` scores 0, `cao` -10, `nghiem_trong` -25. The partner's DDL will
not store those words — its CHECK allows only SAFE/WARNING/HIGH/CRITICAL —
so `seed_postgres.py` maps them on the way in.

Nothing mapped them back. On `faiss + yaml` the doc store returns corpus
tiers and scoring works; flip `CORPUS_DOC_STORE=corpus-pg` and it returns
`HIGH`, which `SEVERITY_RANK` does not contain, so every call resolved to
`""`, the corpus-severity override stopped applying, and scoring silently
fell back to the scanner's category.

The forward map made it worse than a lookup miss. It had two entries —
`cao` and `nghiem_trong` — and everything else took the HIGH default, so
`warning` (517 variants, scores **0**) became indistinguishable from `cao`
(scores -10), as did `tich_cuc`, which marks carveouts and is not a
violation at all. 1,421 of 1,611 variants collapsed into one value.

§8.3 cannot catch this. It compares the *rendered pool* — the text the
decider prompt is built from — and `_format_indexed_pool` renders only the
sample and its description. Severity rides alongside in `raw_items`, never
in the text, so the Phase 4 gate passes while scoring is wrong. These
tests are the gate for the part the pool cannot see.

No database, no network: the maps are plain dicts, and this asserts they
are inverses.
"""

import pytest
import yaml

from src.cases.sentiment_agent._format import _SEVERITY_ROW
from src.cases.sentiment_agent.l4_verify.ops import (
    SEVERITY_RANK,
    resolve_cited_severity,
)
from src.corpus.loader import corpus_severity
from src.corpus.loader import _SEVERITY_FROM_PARTNER

from tests._paths import ROOT
CORPUS = ROOT / "knowledge/sentiment_agent/corpus.yaml"

#: The partner's CHECK constraint, from their DDL — mirrored in
#: `src/jobs/ingest/schema.sql`, which is extracted from it
#: verbatim. Writing anything else raises, so the forward map's range is
#: not a matter of taste.
PARTNER_VALUES = {"SAFE", "WARNING", "HIGH", "CRITICAL"}


def _seed():
    """The seeder `ingest` writes with."""
    from src.jobs.ingest import _seed as mod

    return mod


@pytest.fixture(scope="module")
def seed():
    return _seed()


# ── the two maps are inverses ────────────────────────────────────────────


def test_forward_map_is_one_to_one(seed):
    """A shared target value is what made `warning` unrecoverable: two
    tiers writing HIGH means reading HIGH cannot tell you which."""
    stored = list(seed.SEVERITY.values())
    assert len(stored) == len(set(stored)), f"collision in {seed.SEVERITY}"


def test_forward_map_only_writes_values_the_partner_allows(seed):
    assert set(seed.SEVERITY.values()) <= PARTNER_VALUES


def test_the_maps_are_exact_inverses(seed):
    assert {v: k for k, v in seed.SEVERITY.items()} == _SEVERITY_FROM_PARTNER


@pytest.mark.parametrize("tier", ["tich_cuc", "warning", "cao", "nghiem_trong"])
def test_a_tier_round_trips_unchanged(seed, tier):
    assert corpus_severity(seed.map_severity(tier)[0]) == tier


# ── what the corpus actually contains ────────────────────────────────────


def _corpus_tiers() -> set[str]:
    corpus = yaml.safe_load(CORPUS.read_text(encoding="utf-8")) or {}
    tiers = set()
    for block in corpus.values():
        if not isinstance(block, dict):
            continue
        for side in ("positives", "carveouts"):
            for entry in block.get(side) or []:
                if isinstance(entry, dict):
                    tiers.add((entry.get("severity") or "").strip()
                              or (block.get("severity") or "").strip())
    return {t for t in tiers if t}


def test_every_tier_in_the_corpus_is_mapped(seed):
    """The failure mode is silent: an unmapped tier takes the default and
    reads back as `cao`, so a new tier scores -10 the moment it is added
    rather than failing loudly."""
    unmapped = _corpus_tiers() - set(seed.SEVERITY)
    assert not unmapped, (
        f"corpus tiers with no mapping: {sorted(unmapped)} — add them to "
        f"SEVERITY in seed_postgres.py and to _SEVERITY_FROM_PARTNER")


def test_the_corpus_needs_no_more_slots_than_the_partner_has(seed):
    """Four tiers, four allowed values. A fifth tier has nowhere to go and
    is a schema conversation with MLE, not a code change."""
    assert len(_corpus_tiers()) <= len(PARTNER_VALUES)


def test_scoring_knows_every_violation_tier_the_corpus_uses():
    """`tich_cuc` is deliberately absent from both — carveouts suppress a
    finding, they never carry one, and `resolve_cited_severity` reads only
    cited *positives*."""
    scoring_tiers = set(SEVERITY_RANK) | set(_SEVERITY_ROW)
    assert _corpus_tiers() - scoring_tiers == {"tich_cuc"}


# ── the bug this file exists for ─────────────────────────────────────────


@pytest.mark.parametrize("tier, label, offset", [
    ("warning", "Thái độ warning", 0),
    ("cao", "Thái độ cao", -10),
    ("nghiem_trong", "Thái độ nghiêm trọng", -25),
])
def test_a_postgres_pool_scores_the_same_as_a_yaml_pool(seed, tier, label, offset):
    """End to end over the two maps, on the value scoring keys off.

    Before the inverse existed this resolved to `""` for all three, and
    `format_sentiment_agent` fell through to the scanner's category — so a
    `warning` call scored -10 or -25 instead of 0.
    """
    from_yaml = tier
    from_pg = corpus_severity(seed.map_severity(tier)[0])

    assert resolve_cited_severity(["P1"], {"P1": from_pg}) == \
           resolve_cited_severity(["P1"], {"P1": from_yaml}) == tier
    assert _SEVERITY_ROW[tier] == (label, offset)


def test_partner_values_never_reach_scoring():
    """The raw stored values must not survive as themselves: each one
    ranks 0, which reads as 'nothing resolved' rather than as an error."""
    for value in PARTNER_VALUES:
        assert SEVERITY_RANK.get(value, 0) == 0
        assert corpus_severity(value) in set(SEVERITY_RANK) | {"tich_cuc"}


def test_an_unknown_value_passes_through_rather_than_becoming_a_tier():
    """A store speaking neither scale should not be silently promoted into
    a scoring tier. `""` is how 'nothing resolved' is spelled."""
    assert corpus_severity("banana") == "banana"
    assert corpus_severity("") == ""
    assert corpus_severity(None) == ""
    assert resolve_cited_severity(["P1"], {"P1": corpus_severity("banana")}) == ""


def test_the_inverse_is_case_insensitive_but_does_not_touch_corpus_tiers():
    """psycopg returns the column verbatim, but a hand-run backfill or a
    different client may not preserve case. Corpus tiers are lowercase and
    must survive unchanged — `cao` must not be read as a partner value."""
    assert corpus_severity("high") == corpus_severity("HIGH") == "cao"
    assert corpus_severity("cao") == "cao"
    assert corpus_severity("nghiem_trong") == "nghiem_trong"
