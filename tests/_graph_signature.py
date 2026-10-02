"""A structural fingerprint of a case graph, stable under renaming.

Step 0a of `docs/archive/PLAN_sentiment_agent_layers.md`. The layer refactor moves
40 ops into four subgraphs without changing what any of them does, so the
question a test has to answer is "did the shape survive?" — and it has to
answer it without depending on names, because the refactor changes those
on purpose and operonx's auto-naming changes them by accident.

That last part is not hypothetical. `card_number`'s branch is currently
named `role`: `auto_name()` reads the calling line for an assignment, an
inline `if_(...)` has none, and the source parser latched onto a nearby
`role=` instead. A golden file keyed on branch names would encode that
accident and break the day it resolves differently.

So the fingerprint keys on **what an op is and what it connects to**, not
what it is called:

* an op is `(basename, type)` — the graph prefix is stripped, so the same
  op fingerprints the same nested or not
* a branch is `(sorted condition descriptions, default)` — never its name
* an edge is `(from, to)` by basename

Branch *names* are deliberately excluded. Everything that decides
behaviour is included.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict


def _base(name: str) -> str:
    """Last path segment — `qc_flow.l2.scanner` → `scanner`."""
    return str(name).rsplit(".", 1)[-1]


def _condition(ref: Any) -> str:
    """A branch condition, described without its source op's full path.

    `describe()` renders the comparison the branch actually evaluates.
    The source is reduced to a basename so nesting the graph one level
    deeper does not read as a changed condition.
    """
    try:
        text = ref.describe()
    except Exception:
        text = str(ref)
    source = getattr(ref, "raw_source", None)
    if source:
        text = text.replace(str(source), _base(str(source)))
    return text


def branch_signature(op: Any) -> Dict[str, Any]:
    """The routing table of one branch, keyed on conditions not names."""
    cases = []
    for ref, target in getattr(op, "cases", []) or []:
        cases.append([_condition(ref), _base(target) if target else None])
    default = getattr(op, "default", None)
    return {"cases": sorted(cases), "default": _base(default) if default else None}


def graph_signature(graph: Any) -> Dict[str, Any]:
    """Fingerprint a built graph: ops, edges, and every routing table.

    Branches are collected as a *sorted list* of signatures rather than a
    map, so two branches swapping names is invisible and two branches
    swapping arms is not — which is the distinction worth testing.
    """
    ops = {}
    branches = []
    edges = []

    def walk(g):
        """Descend into subgraphs — a layer is a grouping, not a boundary.

        The refactor moves ops *into* subgraphs without changing what they
        do, so a fingerprint that stopped at the top level would go blind
        on exactly the change it exists to check. Basenames are stripped,
        so `scanner` fingerprints the same whether it sits at the top or
        inside `l2`.
        """
        for name, op in (getattr(g, "_ops", None) or {}).items():
            ops[_base(name)] = str(getattr(op, "type", "?"))
            if getattr(op, "type", None) == "branch":
                branches.append(branch_signature(op))
            if getattr(op, "_ops", None):
                walk(op)
        for e in (getattr(g, "_edges", None) or {}).values():
            edges.append([_base(e.from_node), _base(e.to_node)])

    walk(graph)
    edges = sorted(edges)

    return {
        "ops": dict(sorted(ops.items())),
        "edges": edges,
        "branches": sorted(branches, key=lambda b: (str(b["cases"]), str(b["default"]))),
        "entries": sorted(_base(n) for n in (getattr(graph, "entries", None) or [])),
        "exits": sorted(_base(n) for n in (getattr(graph, "exits", None) or [])),
    }


def diff_signatures(expected: Dict[str, Any], actual: Dict[str, Any]) -> list:
    """Human-readable differences, most structural first.

    Returns [] when the two match. Ordered so the first line names the
    thing most likely to explain the rest: an op that vanished explains
    the edges that vanished with it.
    """
    out = []

    exp_ops, act_ops = expected.get("ops", {}), actual.get("ops", {})
    for name in sorted(set(exp_ops) - set(act_ops)):
        out.append(f"op removed: {name} ({exp_ops[name]})")
    for name in sorted(set(act_ops) - set(exp_ops)):
        out.append(f"op added: {name} ({act_ops[name]})")
    for name in sorted(set(exp_ops) & set(act_ops)):
        if exp_ops[name] != act_ops[name]:
            out.append(f"op type changed: {name} {exp_ops[name]} -> {act_ops[name]}")

    # Multiset, not set. Once the walk descends into subgraphs, two layers
    # can hold an edge with the same basenames — `scanner -> mapping` in one
    # and the same pair elsewhere. Comparing sets would let one of a
    # duplicated pair vanish unnoticed, which is precisely a dropped edge.
    exp_e = Counter(tuple(e) for e in expected.get("edges", []))
    act_e = Counter(tuple(e) for e in actual.get("edges", []))
    for (u, v), n in sorted((exp_e - act_e).items()):
        out.append(f"edge removed: {u} -> {v}" + (f" (x{n})" if n > 1 else ""))
    for (u, v), n in sorted((act_e - exp_e).items()):
        out.append(f"edge added: {u} -> {v}" + (f" (x{n})" if n > 1 else ""))

    exp_b = [str(b) for b in expected.get("branches", [])]
    act_b = [str(b) for b in actual.get("branches", [])]
    if exp_b != act_b:
        for b in exp_b:
            if b not in act_b:
                out.append(f"branch table removed: {b}")
        for b in act_b:
            if b not in exp_b:
                out.append(f"branch table added: {b}")

    for key in ("entries", "exits"):
        if expected.get(key) != actual.get(key):
            out.append(f"{key} changed: {expected.get(key)} -> {actual.get(key)}")

    return out
