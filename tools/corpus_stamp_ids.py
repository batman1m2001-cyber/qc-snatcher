"""Re-stamp corpus entry ids as UUIDs, and record what mapped to what.

`POS-006` / `CVO-001` were placeholders, and they encode something that
stopped being true. QC's 2026-08-24 rebuild moved 55 entries between sides
without renaming them, so `POS-316` is a carveout and `CVO-018` is a
positive. An id that asserts anything can be made a liar by an edit; this
one already has been.

A UUID also costs nothing to be safe with. `knowledge_policy.id` is a
flat `VARCHAR(150)` primary key and the seed writes
`ON CONFLICT (id) DO UPDATE`, so any id that ever collides is a silent
overwrite rather than an error. Nothing else writes these tables today, so
this is insurance, not a fix — the reasons above are why the change was
worth making.

What a UUID buys, point by point:

  side move      encodes nothing about the side, so moving an entry is
                 just an UPDATE
  insertion      not positional — the fragility that broke the first
                 Postgres seed, where ids were assigned 1..N in file
                 order and inserting one entry remapped every row below it
  reword         not content-derived, so editing a sample updates the row
                 instead of orphaning it and creating a new one
  collision      no shared namespace to collide in

**Nothing about the schema changes.** The id is a string in the column it
was always a string in, 38 characters against a 150 limit once the `#N`
variant suffix is added. `variant_id()` and `parent_id()` are untouched:
they split on `#`, and a UUID contains none.

Rewrites the `  - id:` lines and nothing else — not a YAML round-trip,
which would reflow 365 KB of QC-maintained text and normalise the line
endings. Every other byte, including CRLF, survives.

    uv run python -m tools.corpus_stamp_ids --dry-run      # what would be stamped
    uv run python -m tools.corpus_stamp_ids --apply        # rewrite corpus.yaml, write the id map

Afterwards the index must be rebuilt and Postgres re-seeded with --prune,
because every id in both is now stale.
"""
from __future__ import annotations

import argparse
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CORPUS = ROOT / "knowledge/sentiment_agent/corpus.yaml"

#: `  - id: <value>` and nothing else. Anchored and indent-aware so a
#: `description:` that happens to contain the text "id:" cannot match.
ID_LINE = re.compile(r"^(?P<pre>\s*-\s+id:\s*)(?P<id>\S+)(?P<post>\s*)$")

#: Top-level mapping key — a group. Zero indent, ends in a colon.
GROUP_LINE = re.compile(r"^(?P<key>\S[^:]*):\s*$")

#: `  positives:` / `  carveouts:`
SIDE_LINE = re.compile(r"^\s+(?P<side>positives|carveouts):\s*$")

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def restamp(text: str) -> tuple[str, list[dict]]:
    """Returns (new text, mapping rows). Already-UUID ids are left alone."""
    out: list[str] = []
    rows: list[dict] = []
    group = side = ""
    seen: set[str] = set()

    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")

        g = GROUP_LINE.match(body)
        if g and not body.startswith(" "):
            group, side = g.group("key"), ""
        s = SIDE_LINE.match(body)
        if s:
            side = s.group("side")

        m = ID_LINE.match(body)
        if not m:
            out.append(line)
            continue

        old = m.group("id")
        if UUID_RE.match(old):
            out.append(line)          # already done; keep it stable
            continue

        new = str(uuid.uuid4())
        while new in seen:            # astronomically unlikely; cheap to rule out
            new = str(uuid.uuid4())
        seen.add(new)

        ending = line[len(body):]     # the exact "\r\n" / "\n" this line had
        out.append(f"{m.group('pre')}{new}{m.group('post')}{ending}")
        rows.append({"old_id": old, "new_id": new, "group_id": group,
                     "side": side})

    return "".join(out), rows


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--map-out", default=None,
                    help="TSV of old -> new. Default: beside the corpus. "
                         "This is how QC's existing review workbook, which "
                         "is keyed by the old ids, still joins.")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if a.apply == a.dry_run:
        raise SystemExit("pass exactly one of --apply / --dry-run")

    path = Path(a.corpus)
    # newline="" so the CRLF this file uses is preserved rather than
    # normalised on the way in and rewritten on the way out.
    with path.open(encoding="utf-8", newline="") as fh:
        text = fh.read()
    new_text, rows = restamp(text)

    total = sum(1 for ln in text.splitlines() if ID_LINE.match(ln))
    print(f"corpus   {path.name}")
    print(f"entries  {total}")
    print(f"restamp  {len(rows)}  ({total - len(rows)} already UUID)")

    if not rows:
        print("\nnothing to do — every id is already a UUID.")
        return

    by_side: dict[str, int] = {}
    for r in rows:
        by_side[r["side"] or "?"] = by_side.get(r["side"] or "?", 0) + 1
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(by_side.items())))
    print("\nfirst few:")
    for r in rows[:4]:
        print(f"  {r['old_id']:9s} -> {r['new_id']}  [{r['side']}] {r['group_id']}")

    if a.dry_run:
        print("\ndry run — nothing written")
        return

    map_path = Path(a.map_out) if a.map_out else path.with_name(
        path.stem + "_id_map.tsv")
    map_path.write_text(
        "old_id\tnew_id\tgroup_id\tside\n" + "".join(
            f"{r['old_id']}\t{r['new_id']}\t{r['group_id']}\t{r['side']}\n"
            for r in rows),
        encoding="utf-8", newline="")
    path.write_text(new_text, encoding="utf-8", newline="")

    print(f"\nwrote {path}")
    print(f"wrote {map_path}  ({len(rows)} rows)")
    print("\nBoth stores now hold stale ids. Next:")
    print("  uv run operonx-run ingest --set seed=true")


if __name__ == "__main__":
    raise SystemExit(main())
