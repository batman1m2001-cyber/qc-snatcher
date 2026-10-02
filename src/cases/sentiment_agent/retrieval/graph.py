"""Corpus retrieval — embed once, search both pools, hydrate, assemble.

```mermaid
flowchart LR
    E[EmbeddingOp] --> Q[first_vector]
    Q --> SP[corpus_side positives] --> M[merge_sides]
    Q --> SC[corpus_side carveouts] --> M
```

Each side is its own subgraph: `VectorSearchOp` → fan variant hits into
entry ids → `DocFetchOp` → `assemble_side`. Every hop is a node, so each gets
a trace span — which matters most for the hydrate step, often slower than
the search itself.

Backends are resource config, not code: `models.yaml` `retrieval.*` sets
the constants `CORPUS_EMBEDDING`, `CORPUS_VECTOR_STORE_POS` / `_CVO` and
`CORPUS_DOC_STORE`, each naming an entry in `resources.yaml` (a remote
Triton embedder, pgvector stores, a Postgres doc store). A resource binds
when the op is built, so the two sides take their store as a **static**
graph argument — operonx passes a non-Ref value straight through to the
body at build time.

`retrieve_corpus` is composed as a node by the graphs that need it (l3's
filter decider, l4's primary decider). It builds no engine of its own: a
caller with no graph to hang it on — a script, a preflight — wraps it in
an `Operon` at its own entry point, the same way `main.py` wraps the whole
pipeline.

Items come back **variant-level**, per side, in score order, each carrying
`parent_id` so `_format_indexed_pool` groups them into `P1..Pn` slots. The
pool renders only the phrasings that matched, because the corpus
descriptions are written against those.
"""
from __future__ import annotations

from operonx.core import END, START, GraphOp, graph
from operonx.providers import DocFetchOp, EmbeddingOp, VectorSearchOp

from ....core.config import (
    CORPUS_DOC_STORE,
    CORPUS_EMBEDDING,
    CORPUS_VECTOR_STORE_CVO,
    CORPUS_VECTOR_STORE_POS,
    RETRIEVAL_TOP_K,
)
from .ops import assemble_side, fan_in_variants, first_vector, merge_sides, to_batch, widen

__all__ = ["corpus_side", "retrieve_corpus"]


@graph
def corpus_side(query_vector: list, top_k: int, store: str, collection: str) -> GraphOp:
    """One pool: search → fan-in → hydrate → assemble.

    `store` and `collection` are passed as literals and bind at build time;
    `query_vector` and `top_k` are runtime inputs.
    """
    # Over-fetch, then let `assemble_side` rank and cut. The store must not be
    # the thing that decides a tie at the cutoff — see `_OVERFETCH`.
    wide = widen(top_k=top_k)
    hits = VectorSearchOp.of(resource=store, query_vector=query_vector, top_k=wide["top_k"])
    fan = fan_in_variants(ids=hits["ids"], metadata=hits["metadata"])
    docs = DocFetchOp.of(resource=CORPUS_DOC_STORE, ids=fan["entry_ids"], collection=collection)
    built = assemble_side(
        scores=hits["scores"], metadata=hits["metadata"],
        rows=docs["rows"], missing=docs["missing"], top_k=top_k)

    START >> wide >> hits >> fan >> docs >> built >> END


@graph
def retrieve_corpus(query: str, top_k: int = RETRIEVAL_TOP_K) -> GraphOp:
    """Embed once, search both pools in parallel, merge."""
    batch = to_batch(query=query)
    emb = EmbeddingOp.of(resource=CORPUS_EMBEDDING, texts=batch["texts"])
    qvec = first_vector(embeddings=emb["embeddings"])

    positives = corpus_side(query_vector=qvec["vector"], top_k=top_k,
                            store=CORPUS_VECTOR_STORE_POS, collection="positives")
    carveouts = corpus_side(query_vector=qvec["vector"], top_k=top_k,
                            store=CORPUS_VECTOR_STORE_CVO, collection="carveouts")
    merge = merge_sides(positives=positives["items"], carveouts=carveouts["items"])

    START >> batch >> emb >> qvec >> [positives, carveouts] >> merge >> END
