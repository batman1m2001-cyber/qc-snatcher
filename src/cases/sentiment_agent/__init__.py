"""Agent sentiment case — re-exports the public surface + row formatter.

`verify_sentiment_agent` (see `graph.py`) runs four layers: cheap gates,
scanner, filter decider, primary decider.

There is no version suffix here on purpose: `main` runs the older
implementation and is the rollback target, so rolling back means deploying
`main`, not flipping a switch in this tree.

`format_sentiment_agent` lives in `_format.py`, not `graph.py`, so the
row shape is not tied to the graph's internals.
"""

from ._format import format_sentiment_agent
from .graph import (
    KID_DETECTOR_TURN_CAP,
    _verify_result_ok,
    verify_sentiment_agent,
)


__all__ = [
    "verify_sentiment_agent",
    "format_sentiment_agent",
    "KID_DETECTOR_TURN_CAP",
    "_verify_result_ok",
]
