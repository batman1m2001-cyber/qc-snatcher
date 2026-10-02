"""Create the corpus tables — once, when they are absent.

What `create_schema` runs.

PART 1 of `schema.sql` is MLE's DDL verbatim, with plain
`CREATE TABLE`: run twice, it fails on the first statement. That is right
for a file meant to run once and useless as an error, so the existence
check comes first and a second run is a no-op.

Applied through psycopg, not `psql -f`: psycopg is already a dependency,
and it opens a transaction, so a failure half-way leaves *no* tables
rather than four tables and no views — the state a later run would misread
as "already applied".
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

SCHEMA = Path(__file__).resolve().parent / "schema.sql"
TABLES = ("knowledge_info", "knowledge_policy", "positive_embedding", "carveout_embedding")


def tables_present(dsn: str) -> Optional[bool]:
    """True / False, or None when the database cannot be reached."""
    import psycopg

    try:
        with psycopg.connect(dsn, connect_timeout=10) as cx, cx.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname='public' "
                "AND tablename = ANY(%s)", (list(TABLES),))
            return cur.fetchone()[0] == len(TABLES)
    except Exception:  # noqa: BLE001 — the caller says what it means
        return None


def apply_schema(dsn: str, dry_run: bool = False) -> Dict[str, object]:
    """Apply the DDL when the tables are absent; report what happened.

    Raises:
        RuntimeError: the database cannot be reached, or the DDL ran and the
            tables are still missing.
    """
    present = tables_present(dsn)
    if present is None:
        raise RuntimeError("cannot reach the database — no schema step without one")
    if present:
        return {"applied": False, "reason": f"all {len(TABLES)} tables already exist"}
    if dry_run:
        return {"applied": False, "reason": "tables absent — dry run, nothing applied"}

    import psycopg

    sql = SCHEMA.read_text(encoding="utf-8")
    with psycopg.connect(dsn, connect_timeout=15) as cx:
        with cx.cursor() as cur:
            # No parameters, so psycopg uses the simple query protocol and
            # runs every statement in the file.
            cur.execute(sql)
        cx.commit()
    if not tables_present(dsn):
        raise RuntimeError("schema applied but the tables are still missing")
    return {"applied": True, "reason": f"created {len(TABLES)} tables"}
