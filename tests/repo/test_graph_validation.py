"""Every case graph must pass operonx's own structural validation.

This exists because of a bug that reached a live run: `r_route` in the v4
sentiment_agent graph branched to `"matcher_inputs"` after retrieval had
been lifted into its own subgraph, so the first op on that branch was
`retrieval_query` and the target named an op that was no longer a
successor.

A branch target is a **plain string resolved at run time**. The graph
builds fine, imports fine, and 372 unit tests passed — because none of
them takes that branch. It raised only on a call the scanner flagged, and
in the batch runner the exception was caught per-file, so the run reported
`OK`. Every flagged call in production would have been scored wrong, and
quietly.

`GraphOp.validate()` catches it and nothing calls it automatically, so
these tests do. They are cheap: building a graph runs no ops and makes no
network calls.
"""

import pytest
from operonx.core import END, PARENT

GRAPHS = ("sentiment_agent", "l4_verify")

#: Branch targets that name a graph boundary rather than an op, so they are
#: never among the branch's wired successors. Read off operonx's own sentinel
#: rather than hardcoded: `"END"` was the only value skipped here and `END`'s
#: actual `name` is `__END__`, so the first graph to route a branch straight
#: to the exit failed this test for the wrong reason. `"END"` stays in the set
#: because a branch may also be declared with a forward-reference string.
_SENTINELS = frozenset({"END", getattr(END, "name", "__END__")})


def build(name):
    """Instantiate one case graph with placeholder inputs.

    Built inside the test rather than at collection: importing the case
    packages resolves the embedding resource, which loads a 2 GB ONNX
    session, and doing that once per parametrised id is wasteful.
    """

    if name == "sentiment_agent":
        from src.cases.sentiment_agent.graph import verify_sentiment_agent as fn
        return fn(conversation=PARENT, call_code=PARENT)
    if name == "l4_verify":
        from src.cases.sentiment_agent.l4_verify import l4_verify as fn
        return fn(conversation=PARENT, result=PARENT)
    raise AssertionError(f"unknown graph {name!r}")


@pytest.mark.parametrize("name", GRAPHS)
def test_graph_has_no_validation_errors(name):
    """No invalid branch targets, cycles, or dangling refs.

    The failure this guards is silent by construction: a stale branch
    target is only reached when its condition fires.
    """
    graph = build(name)
    result = graph.validate()
    assert not result.has_errors, f"{name} failed validation:\n{result}"


@pytest.mark.parametrize("name", GRAPHS)
def test_every_branch_target_is_a_successor(name):
    """Targets must also be *wired* successors, not merely present.

    `validate()` checks a target names an op that exists somewhere in the
    graph. That is weaker than what the runtime needs: `_activate_successors`
    looks the target up among the branch's own successors, so a target
    naming a real op that was never wired downstream of the branch still
    raises at run time.
    """
    # Recurses into subgraphs. A branch is checked against the edges of the
    # graph that *owns* it, so each level is collected with its own edge set.
    #
    # The flat version went blind the moment `sentiment_agent` nested its
    # gates one level deeper: every branch moved inside `decide`, the
    # top-level scan found none, and only the `assert branches` guard below
    # turned that into a failure instead of a silent pass. That guard is why
    # this was a two-minute fix rather than a hole.
    def _levels(g):
        ops = getattr(g, "_ops", {}) or {}
        # `_edges` is keyed by (from_node, to_node) tuples, not by from_node.
        # Indexing it by branch name returns None, and a successor set built
        # that way is empty — which is how the first version of this test
        # passed with the bug still in place.
        yield ops, (getattr(g, "_edges", {}) or {})
        for op in ops.values():
            if getattr(op, "_ops", None):
                yield from _levels(op)

    branches = [
        (n, op, edges)
        for ops, edges in _levels(build(name))
        for n, op in ops.items()
        if getattr(op, "type", None) == "branch"
    ]
    assert branches, f"{name}: no branch ops found — the test is not looking at anything"

    for op_name, op, edges in branches:
        successors = {to for frm, to in edges if frm == op_name}
        assert successors, f"{name}: branch {op_name!r} has no wired successors"

        for target in getattr(op, "candidates", []):
            if target in _SENTINELS:
                continue
            assert target in successors, (
                f"{name}: branch {op_name!r} targets {target!r}, which is not "
                f"among its wired successors {sorted(successors)}.\n"
                f"The graph builds and validate() passes — {target!r} is a real "
                f"op, just not downstream of this branch — so this only raises "
                f"when the branch is taken."
            )
