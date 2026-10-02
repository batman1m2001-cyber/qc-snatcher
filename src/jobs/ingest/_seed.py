"""Seed `corpus.yaml` into Postgres + pgvector.

What `ingest` writes, under the advisory lock (`_store.seed_under_lock`).

**Rows come from `src.corpus.variants.corpus_rows`, not from a second
flattening** — one `knowledge_policy` row per phrasing (`<uuid>#0`, `#1`,
...), exactly what retrieval serves. A seeder that re-derived the split
could disagree with the store about what a document is.

Every row is stamped `batch_id = corpus sha`; that is what freshness is
read from. Re-running is safe: rows upsert per id, so an edited entry
touches its own rows and nothing else.
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from src.corpus.loader import CORPUS_YAML, corpus_hash
from src.core.config import CORPUS_EMBEDDING
from src.corpus.variants import corpus_rows

_LOG = logging.getLogger(__name__)

#: yaml side → (embedding table, singular sample_type)
SIDES = {
    "positives": ("positive_embedding", "positive"),
    "carveouts": ("carveout_embedding", "carveout"),
}

#: Ours → the partner's CHECK values. One-to-one and order-preserving, and
#: it has to be reversible: `resolve_cited_severity` ranks corpus tiers, so
#: what this writes must read back as the tier it started as, or scoring
#: changes silently. The inverse lives in `src/corpus/loader.py`; the two
#: are pinned together by tests/contract/test_severity_roundtrip.py.
SEVERITY = {
    "tich_cuc":     "SAFE",
    "warning":      "WARNING",
    "cao":          "HIGH",
    "nghiem_trong": "CRITICAL",
}
#: An ungraded entry has no free slot, so it takes HIGH and reads back as
#: `cao` — "at least as serious as cao" is the safe way to be wrong.
#: `metadata.severity_src` keeps the original either way.
SEVERITY_DEFAULT = "HIGH"

#: Progress granularity, not the wire batch: the embedder re-chunks by its
#: own `embed_batch_size` (8, the server's maximum).
BATCH = 16

#: A prune that would remove more than this share of the table is refused
#: without `force_prune`: a corpus loaded from the wrong path makes every
#: row look orphaned, and emptying the store has no undo.
PRUNE_REFUSE_SHARE = 0.5


def map_severity(raw: str) -> tuple[str, str]:
    """(stored value, source value). Blank/unrecognised → HIGH + source."""
    src = (raw or "").strip() or "unknown"
    return SEVERITY.get(src, SEVERITY_DEFAULT), src


def to_pg_vector(vec) -> str:
    """pgvector's text input format."""
    return "[" + ",".join(str(float(v)) for v in vec) + "]"


def groups_of(corpus: dict) -> List[dict]:
    """One `knowledge_info` row per corpus group."""
    out = []
    for group_id, block in corpus.items():
        if not isinstance(block, dict):
            continue
        stored, src = map_severity(block.get("severity"))
        out.append({"id": group_id, "name": block.get("name") or group_id,
                    "severity": stored, "metadata": {"severity_src": src}})
    return out


def plan(corpus_path: "str | Path" = CORPUS_YAML) -> Dict[str, Any]:
    """Everything the seed will write, before it embeds anything.

    `ungraded` lists source severities with no partner tier — they read
    back as `cao`, so they are reported rather than passed quietly.
    """
    corpus_path = Path(corpus_path)
    raw = corpus_path.read_text(encoding="utf-8")
    by_side: Dict[str, List[dict]] = {s: [] for s in SIDES}
    for row in corpus_rows(corpus_path):
        by_side[row["sample_type"]].append(row)
    severities: Dict[str, int] = {}
    for rows in by_side.values():
        for r in rows:
            src = map_severity(r["severity"])[1]
            severities[src] = severities.get(src, 0) + 1
    return {
        "corpus": str(corpus_path),
        "sha": corpus_hash(raw),
        "groups": groups_of(yaml.safe_load(raw) or {}),
        "by_side": by_side,
        "severities": severities,
        "ungraded": sorted(s for s in severities if s not in SEVERITY),
    }


# ── embedder ─────────────────────────────────────────────────────────────


def tokenizer_path_for(conf: Any, api: str) -> Optional[Path]:
    """Where the embedder reads its tokeniser from — None when it does not
    tokenise on this side (the deployed Triton endpoint, `input_name` set).
    Hashing a file that had no part in producing the vectors would stamp
    every row with a provenance that looks checked and is not."""
    if api == "triton":
        if getattr(conf, "input_name", None):
            return None
        raw = getattr(conf, "tokenizer_path", None)
        return Path(str(raw)) if raw else None
    if api == "onnx":
        model = getattr(conf, "model", None)
        return Path(str(model)) / "tokenizer.json" if model else None
    return None


def sha_of(path: "Path | str | None") -> str:
    """First 16 hex of sha256, or "" when there is nothing to hash."""
    if not path:
        return ""
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else ""


def embedder_identity() -> Dict[str, Any]:
    """The embedder the seed will use, and what identifies its vectors."""
    from operonx.core.registry import ResourceHub

    embedder = ResourceHub.instance().get(f"embedding:{CORPUS_EMBEDDING}")
    conf = getattr(embedder, "config", None)
    api = getattr(getattr(conf, "api_type", None), "value", "") or str(getattr(conf, "api_type", ""))
    tok = tokenizer_path_for(conf, api)
    if tok is not None and not tok.exists():
        raise RuntimeError(
            f"tokeniser not found at {tok}: the embedder tokenises on this side "
            "and would fail on the first call. The deployed endpoint tokenises "
            "server-side — keep `input_name: TEXT` set on the resource.")
    return {"embedder": embedder, "model": getattr(conf, "model", "") or "unknown",
            "tokenizer_sha": sha_of(tok)}


async def embed_all(embedder: Any, texts: List[str], label: str) -> List[List[float]]:
    """Every text's vector, with a progress line — a few hundred round trips
    to a remote endpoint, and without it a run in progress and a hung one
    look the same."""
    out: List[List[float]] = []
    total, t0 = len(texts), time.perf_counter()
    for i in range(0, total, BATCH):
        res = await embedder.run(texts[i:i + BATCH])
        out.extend(res["embeddings"])
        done = min(i + BATCH, total)
        rate = done / max(time.perf_counter() - t0, 1e-9)
        print(f"\r  {label}: {done}/{total}  {rate:4.0f}/s", end="", flush=True)
    print(f"\r  {label}: {total}/{total} in {time.perf_counter() - t0:.0f}s" + " " * 12, flush=True)
    return out


# ── SQL ──────────────────────────────────────────────────────────────────

INFO_SQL = """
INSERT INTO knowledge_info (id, name, severity, metadata)
VALUES (%(id)s, %(name)s, %(severity)s, %(metadata)s)
ON CONFLICT (id) DO UPDATE SET
    name       = EXCLUDED.name,
    severity   = EXCLUDED.severity,
    metadata   = knowledge_info.metadata || EXCLUDED.metadata,
    updated_at = NOW()
"""

#: `status` is computed, so it means something: NEW, UPDATE or UNCHANGED.
POLICY_SQL = """
INSERT INTO knowledge_policy
    (id, knowledge_id, batch_id, sample_type, content, severity, description, status)
VALUES
    (%(id)s, %(knowledge_id)s, %(batch_id)s, %(sample_type)s,
     %(content)s, %(severity)s, %(description)s, 'NEW')
ON CONFLICT (id) DO UPDATE SET
    knowledge_id = EXCLUDED.knowledge_id,
    batch_id     = EXCLUDED.batch_id,
    sample_type  = EXCLUDED.sample_type,
    content      = EXCLUDED.content,
    severity     = EXCLUDED.severity,
    description  = EXCLUDED.description,
    status       = CASE
        WHEN knowledge_policy.content     IS DISTINCT FROM EXCLUDED.content
          OR knowledge_policy.description IS DISTINCT FROM EXCLUDED.description
          OR knowledge_policy.severity    IS DISTINCT FROM EXCLUDED.severity
        THEN 'UPDATE' ELSE 'UNCHANGED' END,
    updated_at   = NOW()
"""


def embedding_sql(table: str) -> str:
    """Replace a policy's vector. Keyed on `policy_id`, not the BIGSERIAL
    primary key — a row's identity must not depend on insertion order."""
    return f"""
INSERT INTO {table}
    (policy_id, knowledge_id, sample_type, severity,
     embedding_model, embedding_version, metadata, embedding)
VALUES
    (%(policy_id)s, %(knowledge_id)s, %(sample_type)s, %(severity)s,
     %(embedding_model)s, %(embedding_version)s, %(metadata)s, %(embedding)s::vector)
ON CONFLICT (policy_id) DO UPDATE SET
    knowledge_id      = EXCLUDED.knowledge_id,
    severity          = EXCLUDED.severity,
    embedding_model   = EXCLUDED.embedding_model,
    embedding_version = EXCLUDED.embedding_version,
    metadata          = EXCLUDED.metadata,
    embedding         = EXCLUDED.embedding
"""


async def clear_other_side(cur: Any, ids_by_side: Dict[str, List[str]]) -> int:
    """Drop the vector an entry left behind when it changed sides.

    An entry id is stable; which side it sits on is not. The upsert keys on
    `policy_id` within one table, so a move writes the new side and leaves
    the old row — a stale vector a positive query can still hit, whose doc
    lookup then comes back empty and the pool a slot short.
    """
    moved = 0
    for side, (_, _) in SIDES.items():
        other = next(SIDES[s][0] for s in SIDES if s != side)
        await cur.execute(
            f"DELETE FROM {other} WHERE policy_id = ANY(%(ids)s) RETURNING policy_id",
            {"ids": ids_by_side[side]},
        )
        moved += len(await cur.fetchall())
    return moved


async def prune_orphans(cur: Any, all_ids: List[str], prune: bool, force: bool) -> Dict[str, int]:
    """Policy rows the corpus no longer has — reported always, deleted with
    `prune` (their vectors follow via ON DELETE CASCADE). Groups are never
    deleted: a group is a QC-facing object, and with no policies under it
    retrieval cannot reach it anyway.

    Raises:
        RuntimeError: a prune would remove more than half the table without
            `force` — usually the wrong corpus file, not an edit.
    """
    await cur.execute("SELECT id FROM knowledge_policy WHERE NOT (id = ANY(%(ids)s))", {"ids": all_ids})
    orphans = [r[0] for r in await cur.fetchall()]
    if not orphans:
        return {"orphans": 0, "pruned": 0}
    await cur.execute("SELECT count(*) FROM knowledge_policy")
    total = (await cur.fetchone())[0]
    if prune and not force and total and len(orphans) / total > PRUNE_REFUSE_SHARE:
        raise RuntimeError(
            f"refusing to prune {len(orphans)} of {total} rows ({len(orphans) / total:.0%}). "
            "A corpus this different is usually the wrong file, not an edit — check the "
            "corpus path, or set force_prune if it really is intended.")
    if prune:
        await cur.execute("DELETE FROM knowledge_policy WHERE NOT (id = ANY(%(ids)s))", {"ids": all_ids})
    return {"orphans": len(orphans), "pruned": len(orphans) if prune else 0}


async def write(the_plan: Dict[str, Any], vectors: Dict[str, List[List[float]]], dsn: str, *,
                model: str, tokenizer_sha: str, prune: bool = True, force_prune: bool = False,
                embedding_version: str = "1.0") -> Dict[str, Any]:
    """Upsert groups, policies and vectors in one transaction, then clear
    side moves and orphans. A failure leaves the store as it was."""
    from operonx.providers.vector_stores._pg import get_pool
    from psycopg.types.json import Jsonb

    sha = the_plan["sha"]
    counts: Dict[str, Any] = {}
    pool = get_pool(dsn)
    await pool.open()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.executemany(INFO_SQL, [{**g, "metadata": Jsonb(g["metadata"])} for g in the_plan["groups"]])
            counts["knowledge_info"] = len(the_plan["groups"])
            for side, rows in the_plan["by_side"].items():
                table, sample_type = SIDES[side]
                await cur.executemany(POLICY_SQL, [{
                    "id": r["id"], "knowledge_id": r["group_id"], "batch_id": sha,
                    "sample_type": sample_type, "content": r["content"],
                    "severity": map_severity(r["severity"])[0],
                    "description": r["description"] or None,
                } for r in rows])
                payload = []
                for r, vec in zip(rows, vectors[side]):
                    stored, src = map_severity(r["severity"])
                    payload.append({
                        "policy_id": r["id"], "knowledge_id": r["group_id"],
                        "sample_type": sample_type, "severity": stored,
                        "embedding_model": model, "embedding_version": embedding_version,
                        "metadata": Jsonb({"severity_src": src, "corpus_sha": sha,
                                           "tokenizer_sha": tokenizer_sha}),
                        "embedding": to_pg_vector(vec),
                    })
                await cur.executemany(embedding_sql(table), payload)
                counts[side] = len(rows)
            counts["moved_sides"] = await clear_other_side(
                cur, {s: [r["id"] for r in rows] for s, rows in the_plan["by_side"].items()})
            counts.update(await prune_orphans(
                cur, [r["id"] for rows in the_plan["by_side"].values() for r in rows], prune, force_prune))
    return counts


async def seed(corpus_path: "str | Path", dsn: str, *, prune: bool = True,
               force_prune: bool = False) -> Dict[str, Any]:
    """plan → embed → write, in one call — what `ingest` runs under the lock."""
    the_plan = plan(corpus_path)
    ident = embedder_identity()
    vectors = {side: await embed_all(ident["embedder"], [r["content"] for r in rows], side)
               for side, rows in the_plan["by_side"].items()}
    counts = await write(the_plan, vectors, dsn, model=ident["model"],
                         tokenizer_sha=ident["tokenizer_sha"], prune=prune, force_prune=force_prune)
    return {"sha": the_plan["sha"], **counts}


def check_seeded_rows(dsn: str) -> List[str]:
    """Did the vectors in Postgres come from the embedder configured now?

    Vectors from a different model or tokeniser are still unit-norm and
    1024-d; the pool comes back full, plausible and wrong. The rows record
    what made them — this compares. Returns the problems, empty when none.
    """
    import psycopg

    ident = embedder_identity()
    try:
        with psycopg.connect(dsn, connect_timeout=10) as cx, cx.cursor() as cur:
            cur.execute("SELECT DISTINCT embedding_model, metadata->>'tokenizer_sha' FROM positive_embedding")
            rows = cur.fetchall()
    except Exception as e:  # noqa: BLE001 — reported
        return [f"could not read the embedding rows: {type(e).__name__}: {e}"]
    if not rows:
        return ["positive_embedding is empty — run operonx-run ingest --set reseed=true"]
    out = []
    if len(rows) > 1:
        out.append(f"rows were seeded by {len(rows)} embedder/tokeniser combinations: {rows} — re-seed")
    model, tok = rows[0]
    if model and ident["model"] and model != ident["model"]:
        out.append(f"rows were embedded with model={model!r}; the embedder now is {ident['model']!r}")
    if tok and ident["tokenizer_sha"] and tok != ident["tokenizer_sha"]:
        out.append(f"rows were embedded with tokeniser {tok}; this config tokenises with {ident['tokenizer_sha']}")
    return out
