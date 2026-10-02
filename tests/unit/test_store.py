"""The corpus store: what its rows say, and when `ingest` may repair it.

Postgres is shared by every pod, so a stale store is repaired only when the
state is one a re-seed converges on, the run asked for it (`seed`, or a
deliberate `reseed`), and one pod does the work. The lock and the seed need
a database; the decisions around them do not, and those are what this
pins. CI has neither VPN nor Postgres.
"""
import pytest

from src.jobs.ingest import _store

SHA = "abc123def456"
OTHER = "999888777666"
DSN = "postgresql://u:pw@host:5432/db"


@pytest.mark.parametrize("seeded, expected", [
    ([SHA], "ok"),
    ([], "empty"),
    ([OTHER], "mismatch"),
    ([OTHER, SHA], "multi"),
    ([""], "mismatch"),  # a row written before batch_id existed is not this corpus
    (["", SHA], "multi"),
])
def test_classify(seeded, expected):
    assert _store.classify(seeded, SHA) == expected


class _PgError(Exception):
    def __init__(self, sqlstate):
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


@pytest.mark.parametrize("exc, expected", [
    (_PgError("42P01"), "no_schema"),   # undefined_table: the DDL never ran
    (_PgError("28P01"), "unreachable"),
    (OSError("refused"), "unreachable"),
    (TimeoutError(), "unreachable"),
])
def test_classify_error(exc, expected):
    assert _store.classify_error(exc) == expected


@pytest.mark.parametrize("state, seed, reseed, expected", [
    ("ok", False, False, "keep"),
    ("ok", True, False, "keep"),        # seed repairs; it never rewrites a current store
    ("ok", False, True, "seed"),        # reseed: re-embed on purpose
    ("empty", False, False, "refuse"),
    ("empty", True, False, "seed"),
    ("mismatch", False, False, "refuse"),
    ("mismatch", True, False, "seed"),
    ("multi", True, False, "refuse"),   # a seed upserts by id — it would never converge
    ("multi", False, True, "seed"),     # reseed prunes it back to one corpus
    ("not-pgvector", True, True, "keep"),
])
def test_decide(state, seed, reseed, expected):
    assert _store.decide(state, seed=seed, reseed=reseed) == expected


def test_store_dsn_refuses_pgvector_without_a_dsn(monkeypatch):
    class Cfg:
        api_type = type("A", (), {"value": "pgvector"})()
        dsn = ""

    class Hub:
        def get_config(self, key):
            return Cfg()

    from operonx.core.registry import ResourceHub

    monkeypatch.setattr(ResourceHub, "instance", classmethod(lambda cls: Hub()))
    with pytest.raises(RuntimeError, match="no DSN"):
        _store.store_dsn()


@pytest.mark.parametrize("state, seeded, fragment", [
    ("empty", [], "knowledge_policy is empty"),
    ("multi", [OTHER, SHA], "corpus versions at once"),
    ("mismatch", [OTHER], "does not match what is seeded"),
])
def test_state_messages_name_the_job_that_fixes_them(state, seeded, fragment):
    msg = _store.state_message(state, seeded, SHA, "corpus.yaml", "host:5432/db")
    fix = "--set reseed=true" if state == "multi" else "--set seed=true"
    assert fragment in msg and f"operonx-run ingest {fix}" in msg
    assert "rag_seed" not in msg and "scripts.rag" not in msg
