"""Which slot a variant lands in must be decided by the corpus, not the index.

The decider cites slots — `P3`, `C1` — so the mapping from slot to entry is
load-bearing, and the BU FP-report tooling resolves policies through it. Two
backends that retrieve the same entries but label them differently have not
migrated cleanly.

FAISS and pgvector both return tied entries in *some* order, each stable in
itself, and the two disagree. Measured on the real corpus, before this:
13 of 200 pools differed by ordering alone, and one differed by which entry
survived the top-k cutoff.

Two mechanisms fix it, and both are here:

  * `_rank_deterministically` — order by score, break ties by variant id.
  * `_OVERFETCH` — ask the store for more than `top_k` so a tie at the
    cutoff is not decided by whichever index answered, then cut after
    ranking.

The tolerance is the subtle part. Adjacent scores fall into two populations
about three orders of magnitude apart: entries that genuinely differ sit
~1e-03 apart, entries the backends merely round differently sit ~1e-06
apart. The threshold belongs in the empty band between them, and the first
attempt (1e-06) sat inside the noise population instead — the regression at
the bottom of this file is that exact case, with the measured scores.

No database, no network.
"""
import pytest

from src.cases.sentiment_agent.retrieval.graph import assemble_side, widen
from src.cases.sentiment_agent.retrieval.ops import (
    _OVERFETCH,
    _TIE_TOL,
    _rank_deterministically,
)

ASSEMBLE = assemble_side(scores=[], metadata=[], rows=[]).core
WIDEN = widen(top_k=1).core


def scored(*triples) -> list:
    """(score, variant_id) -> the shape `_rank_deterministically` takes."""
    return [(s, vid, {"entry_id": vid.rsplit("#", 1)[0], "score": s})
            for s, vid in triples]


def ids(items) -> list[str]:
    return [it["entry_id"] for it in items]


# ── ordering ──────────────────────────────────────────────────────────────


def test_clear_score_differences_still_decide():
    """The tie-break must not flatten real ranking. `POS-999` sorts last on
    id and first on score; score wins."""
    out = _rank_deterministically(scored((0.9, "POS-999#0"), (0.5, "POS-001#0")))
    assert ids(out) == ["POS-999", "POS-001"]


def test_ties_break_on_variant_id_not_on_arrival_order():
    a = _rank_deterministically(scored((0.5, "POS-300#0"), (0.5, "POS-100#0")))
    b = _rank_deterministically(scored((0.5, "POS-100#0"), (0.5, "POS-300#0")))
    assert ids(a) == ids(b) == ["POS-100", "POS-300"]


def test_a_near_tie_inside_the_tolerance_is_a_tie():
    out = _rank_deterministically(
        scored((0.5 + _TIE_TOL / 2, "POS-300#0"), (0.5, "POS-100#0")))
    assert ids(out) == ["POS-100", "POS-300"], "id should decide, not the crumb"


def test_a_gap_beyond_the_tolerance_is_not_a_tie():
    out = _rank_deterministically(
        scored((0.5 + _TIE_TOL * 10, "POS-300#0"), (0.5, "POS-100#0")))
    assert ids(out) == ["POS-300", "POS-100"]


def test_any_input_permutation_gives_the_same_answer():
    """The property that actually matters: the store's order is not an
    input to the result."""
    import itertools
    rows = [(0.8, "POS-020#0"), (0.8, "POS-010#0"), (0.8, "POS-030#0"),
            (0.4, "POS-005#0")]
    outs = {tuple(ids(_rank_deterministically(scored(*p))))
            for p in itertools.permutations(rows)}
    assert outs == {("POS-010", "POS-020", "POS-030", "POS-005")}


def test_variants_of_one_entry_keep_a_stable_relative_order():
    """`POS-331#0` and `#2` are two phrasings of one entry and group into
    one slot, but the order they are grouped in decides which phrasing
    heads the rendered `a | b` string."""
    out = _rank_deterministically(
        scored((0.7, "POS-331#2"), (0.7, "POS-331#0"), (0.7, "POS-331#1")))
    assert [it["score"] for it in out] == [0.7, 0.7, 0.7]
    assert _rank_deterministically(scored((0.7, "POS-331#2"), (0.7, "POS-331#0"))) \
        == _rank_deterministically(scored((0.7, "POS-331#0"), (0.7, "POS-331#2")))


def test_empty_and_single_are_not_special_cases():
    assert _rank_deterministically([]) == []
    assert ids(_rank_deterministically(scored((0.1, "POS-1#0")))) == ["POS-1"]


# ── over-fetch and truncation ─────────────────────────────────────────────


def test_widen_asks_the_store_for_more_than_the_pool_needs():
    assert WIDEN(top_k=10)["top_k"] == 10 + _OVERFETCH


def test_widen_survives_a_missing_top_k():
    """Graph defaults can arrive as 0 or None; asking a store for 5 rows
    when the pool wants 10 would silently shorten every pool."""
    assert WIDEN(top_k=0)["top_k"] > _OVERFETCH
    assert WIDEN(top_k=None)["top_k"] > _OVERFETCH


def _rows(n: int) -> tuple[list, list, list]:
    scores = [1.0 - i / 1000 for i in range(n)]
    meta = [{"policy_id": f"POS-{i:03d}#0"} for i in range(n)]
    rows = [{"id": f"POS-{i:03d}#0", "content": f"t{i}"} for i in range(n)]
    return scores, meta, rows


def test_the_pool_is_cut_to_top_k_after_ranking_not_before():
    scores, meta, rows = _rows(15)
    out = ASSEMBLE(scores=scores, metadata=meta, rows=rows, top_k=10)["items"]
    assert len(out) == 10
    assert out[0]["entry_id"] == "POS-000"


def test_the_extra_candidates_can_win_a_place():
    """The point of over-fetching. An entry the store returned 11th, tied
    with the 10th, must be able to take the slot — on both backends, by id."""
    scores = [0.9] * 2
    meta = [{"policy_id": "POS-500#0"}, {"policy_id": "POS-100#0"}]
    rows = [{"id": "POS-500#0", "content": "a"}, {"id": "POS-100#0", "content": "b"}]
    out = ASSEMBLE(scores=scores, metadata=meta, rows=rows, top_k=1)["items"]
    assert [it["entry_id"] for it in out] == ["POS-100"]


def test_top_k_zero_means_no_truncation():
    """Callers outside the graph (`corpus_api`, the optimizer) assemble
    without a pool size and must get everything back."""
    scores, meta, rows = _rows(12)
    assert len(ASSEMBLE(scores=scores, metadata=meta, rows=rows, top_k=0)["items"]) == 12


# ── the regression, with the scores that caused it ────────────────────────


@pytest.mark.parametrize("backend, s164, s131", [
    # faiss put them 1.013e-06 apart, pgvector 8.36e-07 — one side called it
    # a tie and the other did not, and the entries swapped slots.
    ("faiss+yaml", 0.6541470885276794, 0.6541460752487183),
    ("pgvector",   0.654147049537478,  0.6541462139530845),
])
def test_the_two_backends_now_agree_on_this_pair(backend, s164, s131):
    out = _rank_deterministically(
        scored((s164, "POS-164#0"), (s131, "POS-131#0")))
    assert ids(out) == ["POS-131", "POS-164"], (
        f"{backend}: gap {abs(s164 - s131):.3e} must read as a tie")


@pytest.mark.parametrize("backend, s555, s367", [
    # `xàm xí` — these straddled the top-10 cutoff, each backend keeping a
    # different one. With over-fetch both are in hand and id decides.
    ("faiss+yaml", 0.6012721061706543, 0.6012720344934422),
    ("pgvector",   0.6012720344934422, 0.6012721061706543),
])
def test_the_cutoff_tie_resolves_the_same_way_on_both(backend, s555, s367):
    scores = [s555, s367]
    meta = [{"policy_id": "POS-555#0"}, {"policy_id": "POS-367#0"}]
    rows = [{"id": "POS-555#0", "content": "a"}, {"id": "POS-367#0", "content": "b"}]
    out = ASSEMBLE(scores=scores, metadata=meta, rows=rows, top_k=1)["items"]
    assert [it["entry_id"] for it in out] == ["POS-367"], backend


def test_the_tolerance_sits_between_the_two_populations():
    """Guards the constant itself. Real gaps ~1e-03, backend-noise gaps
    ~1e-06; 1e-06 was too tight and 1e-03 would flatten real ranking."""
    assert 1e-6 < _TIE_TOL < 1e-3


# ── the id format the corpus actually uses ────────────────────────────────
#
# The fixtures above use `POS-nnn` because a reader can see at a glance
# which of two sorts first, and the mechanism does not care what the string
# is. The corpus itself no longer uses that format — entry ids are UUIDs —
# so these pin the tie-break against the real shape rather than only the
# legible stand-in.


def test_ties_break_on_uuid_ids_too():
    lo = "1f543284-1652-4274-9df1-85b8c48c73bd"
    hi = "ae2238f2-6370-4309-8b0a-09b41c650c6a"
    a = _rank_deterministically(scored((0.5, f"{hi}#0"), (0.5, f"{lo}#0")))
    b = _rank_deterministically(scored((0.5, f"{lo}#0"), (0.5, f"{hi}#0")))
    assert ids(a) == ids(b) == [lo, hi]


def test_a_uuid_entry_id_still_yields_its_parent():
    """`parent_id` splits on `#`, and a UUID contains none — which is why
    switching id schemes needed no change to the retrieval code."""
    from src.corpus.variants import parent_id, variant_id

    entry = "ef375b7d-3375-41fe-96f0-c55ab08ad540"
    assert parent_id(variant_id(entry, 2)) == entry
    assert variant_id(entry, 2) == f"{entry}#2"
