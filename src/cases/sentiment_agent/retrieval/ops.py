"""Retrieval ops — embed, widen, fan variants back into entries, rank, merge.

`_rank_deterministically` breaks score ties by corpus id, so the same query
returns the same pool order on every run.
"""
from __future__ import annotations

import logging as _logging
from typing import Any

from operonx.core import op

from ....core.config import RETRIEVAL_TOP_K
from ....corpus.variants import parent_id
from ....corpus.loader import (
    corpus_severity,
)

_LOG = _logging.getLogger(__name__)


@op
def to_batch(query: str = None) -> dict[str, Any]:
    """Wrap the query into a batch of one.

    `EmbeddingOp` takes a list, but a list *literal* in the graph body
    (`texts=[query]`) hides the reference inside a container the wiring
    cannot see into — the op then receives an unresolved placeholder and
    its output arrives as None. Building the list inside an op keeps the
    reference visible to the graph.
    """
    return {"texts": [query]}


@op
def first_vector(embeddings: list = None) -> dict[str, Any]:
    """`EmbeddingOp` embeds a batch; the query is a batch of one."""
    if not embeddings:
        raise ValueError("embedder returned no vectors for the query")
    return {"vector": list(embeddings[0])}


@op
def fan_in_variants(ids: list = None, metadata: list = None) -> dict[str, Any]:
    """Vector row ids -> document ids, first-seen order.

    A vector row id addresses a row; documents are keyed by `policy_id`,
    which rides on the hit's metadata. Each variant is its own document,
    so this is a straight translation — the dedupe only guards against a
    sidecar mapping two rows onto one document.
    """
    doc_ids: list[str] = []
    seen: set[str] = set()
    for i, m in zip(ids or [], metadata or []):
        pid = (m or {}).get("policy_id")
        if not pid:
            raise ValueError(
                f"hit {i} carries no policy_id — the metadata sidecar is "
                "stale relative to the index; rebuild both together."
            )
        if pid not in seen:
            seen.add(pid)
            doc_ids.append(pid)
    return {"entry_ids": doc_ids}


#: Scores closer together than this are the same score, and their relative
#: order carries no information.
#:
#: Set from the gap distribution: adjacent scores that differ meaningfully
#: sit ~1e-03 apart, while float rounding differences between backends sit
#: ~1e-06 apart. 1e-05 is the empty band between them. A tolerance inside
#: the noise band (e.g. 1e-06) lets two runs disagree on whether a pair is
#: tied, and the entries swap slots.
_TIE_TOL = 1e-5


#: Extra candidates fetched beyond `top_k` before ranking and truncating.
#:
#: Otherwise the store decides the cutoff, and at a near-tie it decides
#: arbitrarily (two entries 1e-07 apart at rank 10 can each be the one kept),
#: and the loser is never fetched. Over-fetching puts both candidates in hand
#: and `_rank_deterministically` makes the same choice every time. The pool
#: handed on is still exactly `top_k`.
_OVERFETCH = 5


def _rank_deterministically(scored: list[tuple[float, str, dict]]) -> list[dict]:
    """Order by score, breaking ties by variant id rather than by luck.

    Without this the slot labels are decided by index layout: a store
    returns tied entries in *some* order, and another backend or index
    build may return another — so `P4` and `P5` swap while the retrieved
    set is the same. The decider cites slots, so a swap means a citation
    resolves to a different entry. Ordering must be deterministic across
    backends.

    Ties are found by walking runs, **not** by rounding scores onto a grid:
    two scores 1e-07 apart land in different buckets whenever they straddle
    a boundary.

    Run membership is measured against the run's head. Two entries within
    rounding noise fall in the same run on any backend, and the variant id —
    corpus data, not arithmetic — then decides.

    This cannot fix a tie that straddles the fetch cutoff — the loser was
    never fetched. `_OVERFETCH` handles that.
    """
    scored = sorted(scored, key=lambda t: (-t[0], t[1]))
    out: list[dict] = []
    i = 0
    while i < len(scored):
        j = i + 1
        while j < len(scored) and abs(scored[i][0] - scored[j][0]) <= _TIE_TOL:
            j += 1
        out.extend(item for _, _, item in sorted(scored[i:j], key=lambda t: t[1]))
        i = j
    return out


@op
def assemble_side(
    scores: list = None,
    metadata: list = None,
    rows: list = None,
    missing: list = None,
    top_k: int = 0,
) -> dict[str, Any]:
    """Rebuild the variant-level items `_format_indexed_pool` consumes.

    The document's `content` **is** the matched phrasing — a variant is a
    document, so there is nothing to split and nothing to index into.

    `parent_id` is the entry the phrasing belongs to, recovered from the
    id (`ef375b7d-3375-41fe-96f0-c55ab08ad540#2` -> the entry). That regroups sibling phrasings
    into one pool card, and it is the id QC's spreadsheet is keyed by.
    """
    if missing:
        # Index drift: the index references documents the store of record
        # no longer has. Loud, because the alternative is a quietly short
        # pool.
        _LOG.warning("retrieval: %d indexed ids have no corpus entry: %s",
                     len(missing), list(missing)[:5])

    by_id = {r["id"]: r for r in (rows or [])}
    scored: list[tuple[float, str, dict]] = []
    for score, meta in zip(scores or [], metadata or []):
        row = by_id.get((meta or {}).get("policy_id"))
        if row is None:
            continue
        entry = parent_id(row["id"])
        scored.append((float(score), str(row["id"]), {
            "text": row.get("content", ""),
            "description": row.get("description", ""),
            "category": row.get("group_id", ""),
            "category_name": row.get("group_name", ""),
            "severity": corpus_severity(
                meta.get("severity") or row.get("severity", "")),
            "parent_id": entry,
            "entry_id": entry,
            "score": float(score),
        }))

    # The store returned these in *its* order, over-fetched. Re-rank so the
    # slot a variant lands in is decided by the corpus rather than by which
    # index answered, then cut to the pool size the caller asked for.
    items = _rank_deterministically(scored)
    if top_k and top_k > 0:
        items = items[:top_k]
    return {"items": items}


@op
def widen(top_k: int = RETRIEVAL_TOP_K) -> dict[str, Any]:
    """`top_k + _OVERFETCH`, as an op rather than an expression.

    Arithmetic on a graph ref has to happen inside an op: writing
    `top_k=top_k + 5` in a graph body computes on the *placeholder*, and the
    failure surfaces several ops later as something unrelated.
    """
    return {"top_k": int(top_k or RETRIEVAL_TOP_K) + _OVERFETCH}


@op
def merge_sides(positives: list = None, carveouts: list = None) -> dict[str, Any]:
    """Single terminal so the graph has one END. Refuses an empty pool.

    Both sides empty is not a retrieval that found nothing — a vector
    search returns the k nearest whatever the query is, and the store is
    checked for the right corpus at startup. It means a hop upstream
    failed and returned None: the embedder timed out, the channel
    dropped, a search errored. operonx records that error on the op and
    lets the graph carry on, so without this the None arrives here as
    `[]` and leaves as a well-formed empty pool.

    That is worth refusing loudly, because of what the empty pool then
    does. The filter decider and the primary decider are asked whether the
    evidence matches a corpus entry; handed nothing to match against, both
    answer "no matching pattern" — correctly — and the call scores
    `Tích cực`. A transport failure becomes a verdict, with no error in the
    output and no failed file in the batch. This has happened: a degraded
    Triton connection turned real violations into clean calls while the
    batch reported every call scored.
    """
    pos, cvo = positives or [], carveouts or []
    if not pos and not cvo:
        raise RuntimeError(
            "retrieval returned an empty pool for both sides. The store is "
            "seeded and a vector search always returns its k nearest, so "
            "this is an upstream hop that failed and returned None — "
            "embedder timeout, dropped channel, or a search error. Failing "
            "the call: judged against an empty pool, the decider answers "
            "'no matching pattern' and a violation scores as clean."
        )
    return {"positives": pos, "carveouts": cvo}
