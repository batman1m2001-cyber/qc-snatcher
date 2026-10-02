"""Root-level op for sentiment_agent — which layer's verdict goes on to l4.
"""
from __future__ import annotations

from operonx.core import op

from .._shared.ops import has_exit_stamp


@op
def pick_decided(l1: dict = None, l2: dict = None, l3: dict = None) -> dict:
    """The verdict of whichever layer decided, for l4 to verify.

    l1, l2 and l3 each end a call on their own terminals, and l4 needs the
    one that did. Branches route *control* to this op; the three refs supply
    the *data*, and exactly one of them is stamped: a layer that handed on
    returns `result: None`, and a layer that never ran reads as `None`.

    l3 is the fallback rather than a stamped candidate because it always
    decides — if even it produced nothing, l4 receives that `None` and passes
    it through, and the `score` job fails the call on the op error that
    left it empty.

    Choosing explicitly is what keeps the verdict and its trace intact: if
    l4 read `l3["result"]` directly, every call an earlier layer decided
    would reach l4 as `None` and lose `filter`, `scanner` and the exit stamp.
    """
    for result in (l1, l2):
        if has_exit_stamp(result):
            return {"result": result}
    return {"result": l3}
