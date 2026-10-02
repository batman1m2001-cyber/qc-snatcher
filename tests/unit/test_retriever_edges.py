"""Unit tests for the corpus-shape surface of retrieval.

Skips anything needing the 2GB ONNX session or an on-disk index, and
focuses on the pure-python helpers that could silently corrupt the pool
downstream: variant split and hash stability. These are the layers most
likely to drift when someone edits corpus.yaml or refactors the schema.
"""
from __future__ import annotations

import hashlib

from src.corpus import loader as corpus_mod
from src.corpus.variants import split_variants
from src.cases.sentiment_agent.retrieval import graph as ret
from tests._engine import children

# ---------------------------------------------------------------------------
# split_variants — pipe-delimited multi-variant strings
# ---------------------------------------------------------------------------


class TestSplitVariants:
    def test_single_variant(self):
        assert split_variants("cút đi") == ["cút đi"]

    def test_two_variants(self):
        assert split_variants("cút đi | biến đi") == ["cút đi", "biến đi"]

    def test_three_variants(self):
        assert split_variants("a | b | c") == ["a", "b", "c"]

    def test_extra_whitespace_stripped(self):
        assert split_variants("  a  |  b  ") == ["a", "b"]

    def test_empty_variant_dropped(self):
        """`' | '` between two pipes → empty middle chunk must be dropped."""
        assert split_variants("a |  | b") == ["a", "b"]

    def test_empty_string(self):
        assert split_variants("") == []

    def test_slash_not_a_delimiter(self):
        """Slash means 'or' inside a variant (`anh/chị`), NOT a separator.
        Regression: earlier schema used ` / ` — switched to ` | ` so
        inline `anh/chị` slashes stop clashing with variant boundaries."""
        assert split_variants("anh/chị ơi") == ["anh/chị ơi"]

    def test_pipe_without_spaces_stays_intact(self):
        """`|` without surrounding spaces is NOT a delimiter — must stay
        inside the variant text."""
        assert split_variants("a|b") == ["a|b"]


# ---------------------------------------------------------------------------
# _corpus_hash — deterministic + short
# ---------------------------------------------------------------------------


class TestCorpusHash:
    def test_deterministic(self):
        text = "some yaml content"
        assert corpus_mod.corpus_hash(text) == corpus_mod.corpus_hash(text)

    def test_different_content_different_hash(self):
        assert corpus_mod.corpus_hash("a") != corpus_mod.corpus_hash("b")

    def test_length_12(self):
        """Cache filename uses first 12 chars — schema must not drift."""
        assert len(corpus_mod.corpus_hash("anything")) == 12

    def test_matches_sha1_prefix(self):
        text = "predictable"
        expected = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        assert corpus_mod.corpus_hash(text) == expected


# ---------------------------------------------------------------------------
# the graph binds each pool's store at build time
# ---------------------------------------------------------------------------


class TestEachSideBindsItsOwnStore:
    """`store` is a static argument, so it binds when the graph is built.

    The two sides used to come from a factory that closed over their keys —
    a design for two corpora that no longer exist. A plain `@graph` taking
    `store` as a literal does the same, provided operonx really passes a
    static value through to the body. If it ever started turning it into a
    runtime ref, both sides would search the same store — or none — and
    nothing would fail at build time. This catches that.
    """

    def test_each_side_searches_its_own_store(self):
        from operonx.core import PARENT

        from src.core import config as C

        g = ret.retrieve_corpus(query=PARENT, top_k=PARENT)
        stores = {name: getattr(children(op).get("hits"), "resource", None)
                  for name, op in children(g).items() if name in ("positives", "carveouts")}
        assert stores == {"positives": C.CORPUS_VECTOR_STORE_POS,
                          "carveouts": C.CORPUS_VECTOR_STORE_CVO}
