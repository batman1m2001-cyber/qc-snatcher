"""Corpus retrieval — embed, search both pools, hydrate. See `graph.py`.

| module | holds |
|---|---|
| `graph.py` | `retrieve_corpus` and its per-pool `corpus_side` — graphs only, no engine |
| `ops.py` | the ops those graphs wire, and the deterministic ranking |

Reading `corpus.yaml` itself (hash, flatten, severity) is `src/corpus/loader.py`,
so a job can read the corpus without building this graph. Graphs import
`retrieve_corpus` from `.graph`.
"""
from .ops import merge_sides

__all__ = ["merge_sides"]
