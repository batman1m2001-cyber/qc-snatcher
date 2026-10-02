"""`preflight` — the stack is there: print the routing, then two checks in
a row; the first that fails names itself.

    routing ──▶ backends ──▶ reachable
"""
from operonx.core import END, START, graph

from .ops import check_backends, check_reachable, show_routing


@graph
def preflight(skip_reachability: bool):
    routing = show_routing()
    backends = check_backends()
    reachable = check_reachable(skip=skip_reachability)
    START >> routing >> backends >> reachable >> END
