"""The ops `ingest` and `create_schema` wire. See `graph.py`."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from operonx.core import op

from src.corpus.loader import CORPUS_YAML, corpus_file_hash

from . import _schema, _seed, _store

logger = logging.getLogger(__name__)


# ── create_schema ─────────────────────────────────────────────────────────


@op
def create_tables(dsn: str = "", dry_run: bool = False) -> Dict[str, Any]:
    dsn = dsn or _store.store_dsn()  # the store the pipeline reads: `${PG_DSN}` in resources.yaml
    if not dsn:
        raise RuntimeError("no DSN — retrieval is not on pgvector; --set dsn=...")
    return {"report": _schema.apply_schema(dsn, dry_run=bool(dry_run))}


# ── ingest ────────────────────────────────────────────────────────────────


@op
def read_store() -> Dict[str, Any]:
    """What the configured store holds, against `corpus.yaml` on disk."""
    dsn = _store.store_dsn()
    if dsn is None:
        return {"store": {"state": _store.NOT_PGVECTOR}}
    where = dsn.rsplit("@", 1)[-1]
    current = corpus_file_hash(CORPUS_YAML)
    seeded = _store.seeded_batches(dsn, where)
    return {"store": {"dsn": dsn, "where": where, "current": current, "seeded": seeded,
                      "state": _store.classify(seeded, current)}}


@op
async def seed_store(
    store: dict = None,
    seed: bool = False,
    reseed: bool = False,
    prune: bool = True,
    force_prune: bool = False,
    dry_run: bool = False,
    seed_wait_s: int = 900,
) -> Dict[str, Any]:
    """Keep the store, seed it, or refuse naming the fix (`_store.decide`).

    The lock, the re-check under it and the write are one op: the lock
    lives on a connection, and a connection does not cross ops.
    """
    state = store["state"]
    action = _store.decide(state, seed=bool(seed), reseed=bool(reseed))
    if action == "refuse":
        raise RuntimeError(_store.state_message(
            state, store["seeded"], store["current"], CORPUS_YAML, store["where"]))
    if action == "keep":
        return {"report": {"state": state, "action": action, "written": False}}
    plan = _seed.plan(CORPUS_YAML)
    if plan["ungraded"]:
        logger.warning("ungraded severities %s will read back as `cao`", plan["ungraded"])
    if dry_run:
        return {"report": {"state": state, "action": action, "written": False, "dry_run": True,
                           "sha": plan["sha"], "groups": len(plan["groups"]),
                           "rows": {side: len(rows) for side, rows in plan["by_side"].items()},
                           "severities": plan["severities"]}}
    counts = await _store.seed_under_lock(
        store["dsn"], Path(CORPUS_YAML), store["current"], store["where"], state,
        wait=int(seed_wait_s), force=bool(reseed), prune=bool(prune), force_prune=bool(force_prune))
    # `{}`: another pod held the lock and seeded this corpus first.
    return {"report": {"state": state, "action": action, "written": bool(counts), "counts": counts}}


@op
def verify(report: dict = None, store: dict = None) -> Dict[str, Any]:
    """After a write: the rows were embedded by the embedder configured now.
    Vectors from another model are still unit-norm and 1024-d — the pool
    comes back full, plausible and wrong — so this is read from the rows."""
    if report["written"]:
        problems = _seed.check_seeded_rows(store["dsn"])
        if problems:
            raise RuntimeError("seeded, but the rows do not match the embedder:\n  " + "\n  ".join(problems))
    return {"report": report}
