"""PART 1 of `schema.sql` must still be MLE's DDL, unedited.

The schema lives in two places: MLE maintain it in
`collection.sentiment_violation.rag/docs/2. ddl_db.md`, and we ship a copy
they can run. Two copies drift, and this one drifts *silently* — a column
they widen or a CHECK they extend does not announce itself here, it shows
up later as an insert that fails in production.

`schema.sql` was briefly two files so that the partner half could be
diffed against their doc. That split cost an extra step at deploy time
whose omission is silent (without PART 2 the seed fails loudly, but
retrieval just returns an empty pool), and both halves need the same DDL
privilege at the same moment, so there was never a case where one ran
without the other. Merging them was right; this test is where the diff
went.

Compares statements, not bytes: their file is prose-formatted markdown and
ours has section banners, so whitespace and comments are normalised away
and the SQL itself is what must match.

Skips if the partner repo is not checked out beside this one — it is a
sibling working copy, not a dependency, and CI should not fail for its
absence.
"""
import re

import pytest

from tests._paths import ROOT
SCHEMA = ROOT / "src/jobs/ingest/schema.sql"
PARTNER_DOC = (ROOT.parent / "collection.sentiment_violation.rag"
               / "docs" / "2. ddl_db.md")

PART2_MARKER = "PART 2 — what this pipeline needs on top"


#: The one place PART 1 deliberately differs from MLE's DDL.
#:
#: Their CHECK allows LOW/MEDIUM/HIGH/CRITICAL. `MEDIUM` was standing in for
#: QC's `warning` tier, and `LOW` for `tich_cuc` — which is a carveout, not a
#: violation at all, so "low severity" said the wrong thing about 498 of the
#: entries. Renamed to SAFE/WARNING/HIGH/CRITICAL on 2026-09-08.
#:
#: Folded onto our spelling here so the rest of the comparison keeps working
#: and still catches drift nobody intended. MLE's copy of the DDL still says
#: LOW/MEDIUM; the tables are created from `schema.sql`, so nothing breaks
#: until their doc is the thing someone runs.
_AGREED_DEVIATIONS = (
    ("'low', 'medium', 'high', 'critical'",
     "'safe', 'warning', 'high', 'critical'"),
)


def norm(sql: str) -> str:
    """Comparable form: no comments, no case, one space between tokens."""
    sql = re.sub(r"--[^\n]*", " ", sql)
    out = re.sub(r"\s+", " ", sql).strip().lower()
    for theirs, ours in _AGREED_DEVIATIONS:
        out = out.replace(theirs, ours)
    return out


def statements(sql: str) -> list[str]:
    """Split on `;`, drop empties. Good enough — this DDL has no function
    bodies in PART 1, which is the only part being compared."""
    return [s for s in (norm(p) for p in sql.split(";")) if s]


@pytest.fixture(scope="module")
def parts() -> tuple[str, str]:
    text = SCHEMA.read_text(encoding="utf-8")
    assert PART2_MARKER in text, "PART 2 banner missing — did the file change shape?"
    head, _, tail = text.partition(PART2_MARKER)
    return head, tail


@pytest.fixture(scope="module")
def partner_sql() -> str:
    if not PARTNER_DOC.exists():
        pytest.skip(f"partner repo not checked out at {PARTNER_DOC}")
    blocks = re.findall(r"```sql\n(.*?)```",
                        PARTNER_DOC.read_text(encoding="utf-8"), re.S)
    assert blocks, "no ```sql blocks found — did their doc change format?"
    return "\n\n".join(blocks)


def test_every_partner_statement_is_present_verbatim(parts, partner_sql):
    """The whole point. A statement of theirs missing from ours means the
    copy has drifted — re-extract rather than patching by hand."""
    head, _ = parts
    ours = set(statements(head))
    missing = [s for s in statements(partner_sql) if s not in ours]
    assert not missing, (
        f"{len(missing)} statement(s) from MLE's DDL are not in PART 1 of "
        f"schema.sql — re-extract it. First: {missing[0][:120]}")


def test_part_1_adds_nothing_of_its_own(parts, partner_sql):
    """Drift runs both ways. Anything we quietly added to *their* half is a
    change they never agreed to and will not reproduce when they apply
    their own file."""
    head, _ = parts
    theirs = set(statements(partner_sql))
    extra = [s for s in statements(head) if s not in theirs]
    assert not extra, (
        f"PART 1 has {len(extra)} statement(s) MLE's DDL does not. They "
        f"belong in PART 2. First: {extra[0][:120]}")


def test_our_additions_stayed_in_part_2(parts):
    """The two things that make their tables usable by this pipeline. If
    either drifted up into PART 1 it would be lost the moment PART 1 is
    re-extracted."""
    _, tail = parts
    low = tail.lower()
    assert "unique (policy_id)" in low, "the seed's ON CONFLICT key is missing"
    assert "create or replace view positives" in low
    assert "create or replace view carveouts" in low


def test_the_partner_half_never_touches_our_views(parts, partner_sql):
    """`positives` / `carveouts` are ours. Finding them in their DDL would
    mean the extraction picked up the wrong blocks."""
    assert "positives" not in norm(partner_sql).replace("positive_embedding", "")
    assert "carveouts" not in norm(partner_sql).replace("carveout_embedding", "")


def test_severity_vocabulary_still_matches_the_seed():
    """`src.jobs.ingest._seed.SEVERITY` writes into a column their CHECK guards. If
    they ever widen or narrow it, the map has to move with it — and this is
    the only place the two are compared."""
    from src.jobs.ingest import _seed as seed

    allowed = set(re.findall(r"'(SAFE|WARNING|HIGH|CRITICAL)'",
                             SCHEMA.read_text(encoding="utf-8")))
    assert set(seed.SEVERITY.values()) <= allowed
    assert seed.SEVERITY_DEFAULT in allowed
