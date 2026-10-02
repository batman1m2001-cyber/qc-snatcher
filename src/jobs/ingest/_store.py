"""What the corpus store holds, and making it hold this corpus.

`batch_id` is the corpus sha the seed stamped on every row, so every
question here is answered from the rows themselves.

`classify` and `decide` are pure and `seeded_batches` is one query, so the
interesting logic runs in CI, which has neither VPN nor a database.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from src.core.config import CORPUS_VECTOR_STORE_POS

_LOG = logging.getLogger(__name__)

#: The two states seeding repairs — both converge when the seed re-runs.
#: `multi` does not on its own: rows of entries deleted from corpus.yaml
#: keep their old batch_id until a prune removes them — `reseed` does that.
SEEDABLE = ("empty", "mismatch")

#: Advisory lock keys are a flat namespace per database. The value is
#: arbitrary but must never change: two versions of this code with
#: different keys would not exclude each other.
SEED_LOCK_KEY = 0x5EEDC0BA

#: The store is not pgvector, so there is nothing to check or seed.
NOT_PGVECTOR = "not-pgvector"


class StoreUnusable(RuntimeError):
    """The rows could not be read at all; `state` says which way."""

    def __init__(self, state: str, message: str) -> None:
        super().__init__(message)
        self.state = state


def classify(seeded: List[str], current: str) -> str:
    """ok · empty · mismatch (corpus moved on) · multi (a partial seed, or
    deleted entries never pruned, or two corpora in one database)."""
    if not seeded:
        return "empty"
    if len(seeded) > 1:
        return "multi"
    return "ok" if seeded[0] == current else "mismatch"


def classify_error(exc: Exception) -> str:
    """`42P01` is undefined_table — the DDL never ran, which is a different
    fix from "cannot reach Postgres"."""
    return "no_schema" if getattr(exc, "sqlstate", None) == "42P01" else "unreachable"


def decide(state: str, *, seed: bool, reseed: bool) -> str:
    """keep · seed · refuse — what `ingest` does about a store in *state*.

    `seed` repairs the states a seed converges on; `reseed` writes whatever
    the state — an `ok` store re-embedded, a `multi` store pruned back to
    one corpus — and is never what a pod does on its own. `refuse` means
    raise `state_message`, which names the command that fixes it.
    """
    if state == NOT_PGVECTOR:
        return "keep"
    if reseed:
        return "seed"
    if state == "ok":
        return "keep"
    if state in SEEDABLE and seed:
        return "seed"
    return "refuse"


def seeded_batches(dsn: str, where: str) -> List[str]:
    """The distinct corpus shas the rows carry, sorted.

    Raises:
        StoreUnusable: no schema, or no database.
    """
    import psycopg

    try:
        with psycopg.connect(dsn, connect_timeout=10) as cx, cx.cursor() as cur:
            cur.execute("SELECT DISTINCT batch_id FROM knowledge_policy")
            return sorted(r[0] or "" for r in cur.fetchall())
    except Exception as e:  # noqa: BLE001 — reported
        if classify_error(e) == "no_schema":
            raise StoreUnusable(
                "no_schema",
                f"{where} has no corpus schema — knowledge_policy does not exist.\n"
                "  The tables are created once, and this needs DDL privilege:\n"
                "  uv run operonx-run create_schema") from e
        raise StoreUnusable(
            "unreachable",
            f"cannot reach Postgres at {where}: {type(e).__name__}: {e}\n"
            "  Retrieval is configured for pgvector, so there is nothing to fall back to.") from e


def state_message(state: str, seeded: List[str], current: str, corpus_path: "str | Path", where: str) -> str:
    """The operator-facing text for a state that is not `ok`. Deploy logs
    are grepped for these strings — rewording one changes an interface."""
    name = Path(corpus_path).name
    if state == "multi":
        return (f"{where} holds {len(seeded)} corpus versions at once: {seeded}.\n"
                "  A seed stopped part way, or two corpora were loaded into one database.\n"
                f"  Fix: uv run operonx-run ingest --set reseed=true   (corpus {name})")
    # One line, and the last: a job's record keeps only an error's last line.
    fix = f"  Fix: uv run operonx-run ingest --set seed=true, or python main.py --ingest   (corpus {name})"
    if state == "empty":
        return f"{where} has no corpus seeded — knowledge_policy is empty.\n" + fix
    if state == "mismatch":
        return (f"{name} does not match what is seeded — Postgres holds corpus "
                f"{seeded[0]}, this corpus is {current}.\n"
                "  Retrieval would answer from the corpus that was ingested, not the one on disk.\n"
                + fix)
    return ""


def store_dsn() -> Optional[str]:
    """The DSN of the configured pgvector store — None when the store is
    not pgvector (nothing to check) — or raise when it is and has none."""
    from operonx.core.registry import ResourceHub

    try:
        cfg = ResourceHub.instance().get_config(f"vector_store:{CORPUS_VECTOR_STORE_POS}")
    except Exception:  # noqa: BLE001 — an unresolvable store is preflight's backend check
        return None
    if getattr(getattr(cfg, "api_type", None), "value", None) != "pgvector":
        return None
    dsn = getattr(cfg, "dsn", "")  # resources.yaml fills it from ${PG_DSN}
    if not dsn:
        raise RuntimeError(
            f"retrieval is configured for pgvector but `vector_store:{CORPUS_VECTOR_STORE_POS}` "
            "has no DSN (PG_DSN empty?).")
    return dsn


async def seed_under_lock(dsn: str, corpus_path: Path, current: str, where: str, state: str,
                          *, wait: int = 900, force: bool = False, prune: bool = True,
                          force_prune: bool = False) -> dict:
    """Seed once, however many pods reach the same conclusion together.

    *wait* (`CORPUS_SEED_WAIT_S`) is how long this pod waits for another
    pod's seed: the seed embeds every variant, so it covers a full pass plus
    the writes, with room to grow.

    The lock answers "may I start?"; the rows answer "is it already done?"
    — the re-check after acquiring is the path N-1 of N pods take on a cold
    database (`force`, a deliberate re-seed, skips it). A *transaction*-scoped
    lock, because a pooler in transaction mode pins one connection for a
    transaction's life, where a session lock silently evaporates and every
    pod seeds at once. The lock is an optimisation, not the safety property:
    each seed is one transaction over the same corpus in the same order.

    Returns the seed's counts, or `{}` when another pod had already done it.
    """
    import psycopg

    from . import _seed

    # WARNING, not INFO: these lines are the deploy's evidence of who wrote
    # to the shared database, and they fire once per corpus change.
    _LOG.warning("%s is %s — waiting up to %ds for the seed lock", where, state, wait)
    _seed.embedder_identity()  # refuse before writing anything if it cannot embed
    with psycopg.connect(dsn, connect_timeout=10) as cx:
        with cx.cursor() as cur:
            cur.execute("SELECT set_config('lock_timeout', %s, true)", (f"{wait}s",))
            try:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (SEED_LOCK_KEY,))
            except psycopg.errors.LockNotAvailable as e:
                raise RuntimeError(
                    f"waited {wait}s for the seed lock on {where}. The pod holding it is "
                    "stuck, or died without releasing it.\n  Raise CORPUS_SEED_WAIT_S if a "
                    "seed legitimately takes longer than this.") from e
        if not force and classify(seeded_batches(dsn, where), current) == "ok":
            _LOG.warning("corpus %s was already seeded by another pod — nothing to do", current)
            return {}
        _LOG.warning("holding the seed lock — seeding %s into %s", corpus_path.name, where)
        counts = await _seed.seed(corpus_path, dsn, prune=prune, force_prune=force_prune)
        seeded = seeded_batches(dsn, where)
        after = classify(seeded, current)
        if after != "ok":
            raise RuntimeError(
                f"the seed reported success but {where} still reads as {after}.\n"
                + state_message(after, seeded, current, corpus_path, where))
    _LOG.warning("corpus %s is now seeded in %s", current, where)
    return counts
