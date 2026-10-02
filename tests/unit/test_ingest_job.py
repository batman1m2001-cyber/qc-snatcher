"""`ingest` and `create_schema` as jobs — offline: the database, the lock
and the embedder are replaced; what is pinned is when the store is seeded,
what a refusal says, the plan, the prune guard and what the run records."""
import asyncio

import pytest
from operonx.app.jobs import RUN_FAILED, RUN_OK

from app.main import create_schema as schema_job
from app.main import ingest as ingest_job
from app.main import ingest_and_seed
from src.corpus.loader import CORPUS_YAML, corpus_file_hash
from src.corpus.variants import corpus_rows
from src.jobs.ingest import _schema, _seed, _store

SHA = corpus_file_hash(CORPUS_YAML)
OTHER = "999888777666"


@pytest.fixture(autouse=True)
def _records(tmp_path, monkeypatch):
    for job in (schema_job, ingest_job, ingest_and_seed):
        monkeypatch.setattr(job, "record_dir", tmp_path)
        monkeypatch.setattr(job, "inputs", dict(job.inputs))


def _result(run):
    """The report the one item produced — read back from the job's record."""
    assert len(run.items) == 1
    return run.items[0]


# ── the plan ─────────────────────────────────────────────────────────────


def test_plan_matches_what_retrieval_serves():
    plan = _seed.plan(CORPUS_YAML)
    rows = list(corpus_rows(CORPUS_YAML))
    assert plan["sha"] == corpus_file_hash(CORPUS_YAML)
    assert sum(len(r) for r in plan["by_side"].values()) == len(rows)
    assert {r["id"] for side in plan["by_side"].values() for r in side} == {r["id"] for r in rows}
    assert plan["ungraded"] == []  # the corpus grades every entry today


def test_map_severity_is_reversible_and_defaults_to_high():
    assert _seed.map_severity("warning") == ("WARNING", "warning")
    assert _seed.map_severity("") == ("HIGH", "unknown")
    assert _seed.map_severity("weird") == ("HIGH", "weird")


# ── ingest, end to end ──────────────────────────────────────────────────


@pytest.fixture
def store(monkeypatch):
    """A store whose rows say *seeded*; records every seed and verify."""
    seen = {"seeds": [], "verified": 0}

    def arrange(seeded, *, counts=None, problems=()):
        monkeypatch.setattr(_store, "store_dsn", lambda: "postgresql://u@h:5432/db")
        monkeypatch.setattr(_store, "seeded_batches", lambda dsn, where: list(seeded))

        async def seed_under_lock(dsn, path, current, where, state, **kw):
            seen["seeds"].append({"state": state, "current": current, **kw})
            return {"knowledge_info": 3} if counts is None else counts

        def check(dsn):
            seen["verified"] += 1
            return list(problems)

        monkeypatch.setattr(_store, "seed_under_lock", seed_under_lock)
        monkeypatch.setattr(_seed, "check_seeded_rows", check)
        return seen
    return arrange


def test_a_current_store_is_left_alone(store):
    seen = store([SHA])
    assert ingest_job.run_sync().status == RUN_OK
    assert seen["seeds"] == [] and seen["verified"] == 0


@pytest.mark.parametrize("seeded", [[], [OTHER]])
def test_a_stale_store_fails_and_names_the_fix(store, seeded):
    seen = store(seeded)
    run = ingest_job.run_sync()
    assert run.status == RUN_FAILED and "operonx-run ingest --set seed=true" in _result(run).error
    assert "python main.py --ingest" in _result(run).error and seen["seeds"] == []


@pytest.mark.parametrize("seeded, state", [([], "empty"), ([OTHER], "mismatch")])
def test_seed_repairs_a_stale_store_under_the_lock_then_verifies(store, seeded, state):
    seen = store(seeded)
    ingest_job.inputs["seed"] = True
    assert ingest_job.run_sync().status == RUN_OK
    assert seen["seeds"] == [{"state": state, "current": SHA, "wait": 900, "force": False, "prune": True,
                              "force_prune": False}]
    assert seen["verified"] == 1


def test_the_deploy_gate_seeds(store):
    seen = store([])
    assert ingest_and_seed.inputs["seed"] is True and ingest_and_seed.name == "ingest"
    assert ingest_and_seed.run_sync().status == RUN_OK and len(seen["seeds"]) == 1


def test_multi_is_refused_even_with_seed(store):
    seen = store([OTHER, SHA])
    ingest_job.inputs["seed"] = True
    run = ingest_job.run_sync()
    assert run.status == RUN_FAILED and "--set reseed=true" in _result(run).error and seen["seeds"] == []


def test_reseed_rewrites_whatever_the_state(store):
    seen = store([SHA])
    ingest_job.inputs.update(reseed=True, prune=False)
    assert ingest_job.run_sync().status == RUN_OK
    assert seen["seeds"][0]["force"] is True and seen["seeds"][0]["prune"] is False


def test_dry_run_takes_no_lock_and_writes_nothing(store):
    seen = store([])
    ingest_job.inputs.update(seed=True, dry_run=True)
    run = ingest_job.run_sync()
    assert run.status == RUN_OK and seen["seeds"] == [] and seen["verified"] == 0


def test_another_pod_seeded_first_so_nothing_to_verify(store):
    seen = store([], counts={})
    ingest_job.inputs["seed"] = True
    assert ingest_job.run_sync().status == RUN_OK
    assert len(seen["seeds"]) == 1 and seen["verified"] == 0


def test_rows_from_another_embedder_fail_the_run(store):
    store([], problems=["model differs"])
    ingest_job.inputs["seed"] = True
    run = ingest_job.run_sync()
    assert run.status == RUN_FAILED and "model differs" in (_result(run).error or "")


def test_a_store_that_is_not_pgvector_is_not_checked(monkeypatch):
    monkeypatch.setattr(_store, "store_dsn", lambda: None)
    monkeypatch.setattr(_store, "seeded_batches", lambda *a: pytest.fail("queried"))
    assert ingest_job.run_sync().status == RUN_OK


# ── the seed itself: plan ──▶ embed ──▶ write ───────────────────────────


class FakeEmbedder:
    def __init__(self):
        self.texts = []

    async def run(self, texts):
        self.texts.extend(texts)
        return {"embeddings": [[0.1, 0.2] for _ in texts]}


def test_seed_embeds_every_variant_and_writes_them(monkeypatch):
    emb, seen = FakeEmbedder(), {}
    monkeypatch.setattr(_seed, "embedder_identity", lambda: {"embedder": emb, "model": "m", "tokenizer_sha": ""})

    async def fake_write(plan, vectors, dsn, **kw):
        seen.update(plan=plan, vectors=vectors, dsn=dsn, **kw)
        return {"knowledge_info": len(plan["groups"]), "orphans": 0, "pruned": 0}

    monkeypatch.setattr(_seed, "write", fake_write)
    out = asyncio.run(_seed.seed(CORPUS_YAML, "postgresql://x@h/db"))
    plan = seen["plan"]
    for side, rows in plan["by_side"].items():
        assert len(seen["vectors"][side]) == len(rows)
    assert len(emb.texts) == sum(len(r) for r in plan["by_side"].values())
    assert seen["prune"] is True and seen["force_prune"] is False and out["sha"] == SHA


def test_an_embedder_that_cannot_embed_stops_before_writing(monkeypatch):
    def broken():
        raise RuntimeError("tokeniser not found")

    monkeypatch.setattr(_seed, "embedder_identity", broken)
    monkeypatch.setattr(_seed, "write", lambda *a, **k: pytest.fail("wrote"))
    with pytest.raises(RuntimeError, match="tokeniser"):
        asyncio.run(_seed.seed(CORPUS_YAML, "postgresql://x@h/db"))


# ── the prune guard ─────────────────────────────────────────────────────


class FakeCursor:
    def __init__(self, orphans, total):
        self.orphans, self.total, self.sql = orphans, total, []
        self._next = None

    async def execute(self, sql, params=None):
        self.sql.append(sql.split()[0])
        if sql.startswith("SELECT id"):
            self._next = [(o,) for o in self.orphans]
        elif sql.startswith("SELECT count"):
            self._next = (self.total,)
        elif sql.startswith("DELETE") and "RETURNING" in sql:
            self._next = []

    async def fetchall(self):
        return self._next

    async def fetchone(self):
        return self._next


def _prune(orphans, total, prune=True, force=False):
    cur = FakeCursor(orphans, total)
    out = asyncio.run(_seed.prune_orphans(cur, ["keep"], prune, force))
    return out, cur


def test_no_orphans_touches_nothing():
    out, cur = _prune([], 10)
    assert out == {"orphans": 0, "pruned": 0} and "DELETE" not in cur.sql


def test_a_small_prune_deletes():
    out, cur = _prune(["a", "b"], 10)
    assert out == {"orphans": 2, "pruned": 2} and "DELETE" in cur.sql


def test_without_prune_orphans_are_only_reported():
    out, cur = _prune(["a"], 10, prune=False)
    assert out == {"orphans": 1, "pruned": 0} and "DELETE" not in cur.sql


def test_a_prune_of_most_of_the_table_is_refused():
    with pytest.raises(RuntimeError, match="refusing to prune 6 of 10"):
        _prune(list("abcdef"), 10)


def test_force_allows_a_large_prune():
    out, _ = _prune(list("abcdef"), 10, force=True)
    assert out["pruned"] == 6


def test_an_entry_that_moved_sides_loses_its_old_vector():
    cur = FakeCursor([], 0)
    asyncio.run(_seed.clear_other_side(cur, {"positives": ["p"], "carveouts": ["c"]}))
    assert cur.sql.count("DELETE") == 2


# ── create_schema ──────────────────────────────────────────────────────────


def test_schema_is_a_no_op_when_the_tables_exist(monkeypatch):
    monkeypatch.setattr(_schema, "tables_present", lambda dsn: True)
    assert _schema.apply_schema("dsn") == {"applied": False, "reason": "all 4 tables already exist"}


def test_schema_refuses_an_unreachable_database(monkeypatch):
    monkeypatch.setattr(_schema, "tables_present", lambda dsn: None)
    with pytest.raises(RuntimeError, match="cannot reach"):
        _schema.apply_schema("dsn")


def test_schema_dry_run_applies_nothing(monkeypatch):
    monkeypatch.setattr(_schema, "tables_present", lambda dsn: False)
    monkeypatch.setattr("psycopg.connect", lambda *a, **k: pytest.fail("connected"))
    assert _schema.apply_schema("dsn", dry_run=True)["applied"] is False


def test_schema_job_without_a_dsn_fails(monkeypatch):
    """No `dsn` input and retrieval not on pgvector: nothing to create tables in."""
    monkeypatch.setattr(_store, "store_dsn", lambda: None)
    run = schema_job.run_sync()
    assert run.status == RUN_FAILED and "no DSN" in (_result(run).error or "")


def test_schema_file_is_where_the_job_reads_it():
    assert _schema.SCHEMA.is_file() and "CREATE TABLE" in _schema.SCHEMA.read_text(encoding="utf-8")
