"""The corpus as retrieval sees it: one row per phrasing.

`variants.py` is the single definition of how an entry's `content` splits
into variants and how a variant id names its entry — retrieval reads the
store through it, and the `ingest` job writes the store through it. `loader.py` reads `corpus.yaml` itself: hash, flatten,
severity.
Keeping the store current is a job's work (`src/jobs/ingest/`,
`operonx-run ingest`), not the library's.
"""
from .variants import SIDES, VARIANT_MARK, VARIANT_SEP, corpus_rows, parent_id, split_variants, variant_id

__all__ = ["SIDES", "VARIANT_MARK", "VARIANT_SEP", "corpus_rows", "parent_id", "split_variants", "variant_id"]
