"""Graphs of the corpus store — `ingest` and `create_schema`. Each runs as
the Job of the same name in `app/main.py`; usage in `README.md`."""
from operonx.core import END, START, graph

from .ops import create_tables, read_store, seed_store, verify


# ── ingest ── read the store ──▶ keep / seed under the lock / refuse ──▶ verify


@graph
def ingest(seed: bool, reseed: bool, prune: bool, force_prune: bool, dry_run: bool, seed_wait_s: int):
    store = read_store()
    seeded = seed_store(
        store=store["store"],
        seed=seed,
        reseed=reseed,
        prune=prune,
        force_prune=force_prune,
        dry_run=dry_run,
        seed_wait_s=seed_wait_s,
    )
    checked = verify(report=seeded["report"], store=store["store"])
    START >> store >> seeded >> checked >> END


# ── create_schema ── one step: apply the DDL when the tables are absent


@graph
def create_schema(dsn: str, dry_run: bool):
    created = create_tables(dsn=dsn, dry_run=dry_run)
    START >> created >> END
