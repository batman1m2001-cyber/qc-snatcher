"""How a corpus entry becomes retrievable rows.

QC maintains `corpus.yaml` as blocks of *entries*, and an entry's
`content` may hold several phrasings of the same idea. Retrieval works on
phrasings, not entries: each one is embedded and searched separately, and
the results are regrouped by the entry they came from.

    POS-001: "anh trả tiền đi | anh thanh toán đi"
        -> POS-001#0  "anh trả tiền đi"
           POS-001#1  "anh thanh toán đi"

A variant is a **document**, not a coordinate inside one — so a hit needs
no second lookup to say which phrasing matched, and `parent_id` is what
puts the siblings back together for display and for a join against QC's
spreadsheet, which is keyed by entry.

None of this is framework behaviour: the variant separator, the id
format, which keys are sides and which are block metadata are all
conventions of *this* corpus, so they live next to the code that
maintains it.

Everything here is a pure function over the file. The Postgres seed
(`src/jobs/ingest/_seed.py`) writes exactly `corpus_rows`, and retrieval
reads those rows back, so the two cannot disagree about what a row is.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

import yaml

__all__ = [
    "VARIANT_SEP",
    "VARIANT_MARK",
    "SIDES",
    "variant_id",
    "parent_id",
    "split_variants",
    "corpus_rows",
]

_LOG = logging.getLogger(__name__)

#: Keys in a block that hold entries. Anything else — `name`, `severity`
#: — is block-level metadata.
SIDES = ("positives", "carveouts")

#: Separator between phrasings inside one entry's ``content``. Spaces on
#: both sides, so it cannot collide with a bare "/" used as inline "or"
#: ("anh/chị", "em/tôi") — which is exactly why it is not "/".
VARIANT_SEP = " | "

#: Joins an entry id to its variant ordinal: ``POS-001`` -> ``POS-001#2``.
VARIANT_MARK = "#"


def variant_id(entry_id: str, index: int) -> str:
    """Document id for one phrasing of an entry."""
    return f"{entry_id}{VARIANT_MARK}{index}"


def parent_id(doc_id: str) -> str:
    """The entry a variant id belongs to. Unsuffixed ids pass through.

    This is how a caller regroups sibling phrasings into a single result,
    and how a lookup against QC's spreadsheet resolves.
    """
    return str(doc_id).rsplit(VARIANT_MARK, 1)[0]


def split_variants(content: str) -> List[str]:
    """Phrasings in one entry's ``content``, blanks dropped."""
    return [p.strip() for p in (content or "").split(VARIANT_SEP) if p.strip()]


def corpus_rows(path: str | Path) -> List[Dict[str, Any]]:
    """Flatten a corpus file into retrievable rows, in file order.

    File order matters beyond tidiness: the seed takes row locks in this
    order, and two pods seeding concurrently therefore block rather than
    deadlock. Anything that reorders this has to re-argue that.

    Entries with no `id` are skipped with a warning rather than given a
    positional one — a positional key shifts whenever anything above it
    is inserted, so a caller holding it would later fetch a different
    entry, silently.

    Returns:
        One dict per phrasing: `id`, `group_id`, `group_name`,
        `sample_type`, `content` (the single phrasing), `description`
        (inherited from the entry, so siblings repeat it), and `severity`
        (per-entry wins; blank inherits the block's).
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows: List[Dict[str, Any]] = []
    unstamped = 0

    for group_id, block in raw.items():
        if not isinstance(block, dict):
            continue
        group_name = block.get("name", "")
        block_severity = block.get("severity", "") or ""
        for side in SIDES:
            for entry in block.get(side) or []:
                if isinstance(entry, str):
                    entry = {"content": entry}
                if not isinstance(entry, dict):
                    continue
                entry_id = entry.get("id")
                if not entry_id:
                    unstamped += 1
                    continue
                content = (entry.get("content") or "").strip()
                if not content:
                    continue
                for i, phrasing in enumerate(split_variants(content)):
                    rows.append({
                        "id": variant_id(entry_id, i),
                        "group_id": group_id,
                        "group_name": group_name,
                        "sample_type": side,
                        "content": phrasing,
                        "description": (entry.get("description") or "").strip(),
                        "severity": entry.get("severity") or block_severity,
                    })

    if unstamped:
        _LOG.warning(
            "%s: %d entries have no `id` and were skipped. Stamp them before "
            "they can be retrieved — positional keys are not used because "
            "they shift on every insert.",
            path.name, unstamped,
        )
    return rows
