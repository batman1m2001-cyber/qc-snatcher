"""The package conventions, checked over all of `src/` by reading the AST.

Written after `retrieval/graph.py` was found building graphs from factories
that returned nested `@graph` closures, and caching an `Operon` engine inside
a library module. Both were designs for a world that no longer existed — two
corpora, a fleet of CLI scripts — and both survived because nothing stated
the rule. These do:

| rule | why |
|---|---|
| `@graph` / `@op` only at module level | a nested one is a factory; a static graph argument does the same job without hiding the graph inside a function |
| `@graph` only in `graph.py`, `@op` only in `ops.py` | the layout rule in CLAUDE.md — a reader finds the root and its ops in the same two places in every package |
| `Operon(...)` only at an entry point | an engine is a process concern. Library code composes graphs; a Job in `app/` runs them |
| a `graph.py` defines only `@graph`s | it wires; logic is an op in `ops.py`, a row formatter is `_format.py` (operonx guide, 05) |
| no `name=` inside a `@graph` body | operonx names an op after the variable it is assigned to; an explicit name duplicates that, drifts from it, and once made `auto_name()` create an op literally called `name` |
| a `@graph` uses its parameters, never `PARENT["param"]` | `@graph` already hands the body `PARENT[param]` for a runtime input (operonx guide, 01); the lookup duplicates the parameter |
| every `@graph` / `@op` parameter is used | an unused one is wiring that carries nothing |
| exits end together: one `[a, b, c] >> END`, not a line each | same edges, one line (operonx guide, 02: a list on either side of `>>` is one wire per element) |
| a fan-out that rejoins is one chain: `x >> [a, b] >> m` | two chains with the same ends are the same wiring written twice |
| every structured model call's `error` is checked (`parsed`) | a reply that fails to parse hands on `None` fields, and `None` reads as "no" — a clean call or a −100 one |
| …unless the call is optional: `on_failure="error"`, and its `error` handed to the op that carries on without it | soften rewords a reason; its failure must not cost the call a verdict |
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests._paths import SRC
APP = SRC.parent / "app"
FILES = sorted(
    p for root in (SRC, APP) for p in root.rglob("*.py") if "__pycache__" not in p.parts
)

def _decorator_names(fn) -> set:
    names = set()
    for d in fn.decorator_list:
        target = d.func if isinstance(d, ast.Call) else d
        names.add(target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None))
    return names


def _functions(tree):
    """(function node, enclosing function or None) for every def in the file."""
    out = []

    def visit(node, parent_fn):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.append((child, parent_fn))
                visit(child, child)
            else:
                visit(child, parent_fn)

    visit(tree, None)
    return out


def _chain(node) -> list:
    """`a >> b >> c` as ["a", "b", "c"]; a list or call element as its source."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.RShift):
        return _chain(node.left) + _chain(node.right)
    return [ast.unparse(node)]


def _rel(p: Path) -> str:
    return str(p.relative_to(SRC.parent)).replace("\\", "/")


@pytest.mark.parametrize("path", FILES, ids=_rel)
class TestConventions:
    def test_no_graph_or_op_is_defined_inside_a_function(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        nested = [f"{fn.name} (inside {parent.name}, line {fn.lineno})"
                  for fn, parent in _functions(tree)
                  if parent is not None and _decorator_names(fn) & {"graph", "op"}]
        assert nested == [], (
            f"{_rel(path)}: a @graph/@op defined inside a function is a graph "
            f"factory. Define it at module level and pass what varies as a "
            f"static argument: {nested}"
        )

    def test_graphs_live_in_graph_py_and_ops_in_ops_py(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        misplaced = []
        for fn, parent in _functions(tree):
            if parent is not None:
                continue
            kinds = _decorator_names(fn)
            if "graph" in kinds and path.name != "graph.py":
                misplaced.append(f"@graph {fn.name}")
            if "op" in kinds and path.name != "ops.py":
                misplaced.append(f"@op {fn.name}")
        assert misplaced == [], (
            f"{_rel(path)}: {misplaced} — @graph belongs in graph.py and @op in "
            f"ops.py (CLAUDE.md, *Layout rule*)."
        )

    def test_an_engine_is_built_only_at_an_entry_point(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # `main()` is a module's smoke entry, reached only from its
        # `if __name__ == "__main__"` block — an entry point in its own right.
        entry_fns = {fn for fn, _ in _functions(tree) if fn.name == "main"}
        inside_entry = set()
        for fn in entry_fns:
            inside_entry |= {id(n) for n in ast.walk(fn)}
        built = [
            f"line {n.lineno}"
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", getattr(n.func, "attr", None)) == "Operon"
            and id(n) not in inside_entry
        ]
        assert built == [], (
            f"{_rel(path)}: builds an Operon engine at {built}. Library code "
            f"composes graphs; only an entry point runs one."
        )


    def test_no_op_is_given_an_explicit_name(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        named = []
        for fn, parent in _functions(tree):
            if parent is not None or "graph" not in _decorator_names(fn):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and any(k.arg == "name" for k in node.keywords):
                    named.append(f"line {node.lineno} in {fn.name}")
        assert named == [], (
            f"{_rel(path)}: `name=` at {named}. operonx names an op after the "
            f"variable it is assigned to — name the variable instead."
        )


    def test_a_graph_py_defines_only_graphs(self, path):
        if path.name != "graph.py":
            return
        tree = ast.parse(path.read_text(encoding="utf-8"))
        extra = [f"{n.name} (line {n.lineno})" for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                 and "graph" not in _decorator_names(n)]
        assert extra == [], (
            f"{_rel(path)}: {extra} — a graph.py wires ops and nothing else. "
            f"Logic goes in ops.py, a row formatter in _format.py."
        )

    def test_a_graph_reads_its_parameters_directly_and_uses_every_one(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = []
        for fn, parent in _functions(tree):
            kinds = _decorator_names(fn)
            if parent is not None or not kinds & {"graph", "op"}:
                continue
            params = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
            read = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
            looked_up = {n.slice.value for n in ast.walk(fn)
                         if isinstance(n, ast.Subscript) and getattr(n.value, "id", None) == "PARENT"
                         and isinstance(n.slice, ast.Constant)}
            found += [f"{fn.name}: PARENT[{p!r}]" for p in params if p in looked_up]
            if fn.args.kwarg is None:
                found += [f"{fn.name}: {p} unused" for p in params if p not in read | looked_up]
        assert found == [], (
            f"{_rel(path)}: {found} — use a @graph parameter by name (it already is "
            f"PARENT[name] at run time), and drop a parameter nothing reads."
        )


    def test_wiring_is_written_once(self, path):
        if path.name != "graph.py":
            return
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = []
        for fn, parent in _functions(tree):
            if parent is not None or "graph" not in _decorator_names(fn):
                continue
            chains = [_chain(st.value) for st in fn.body
                      if isinstance(st, ast.Expr) and isinstance(st.value, ast.BinOp)
                      and isinstance(st.value.op, ast.RShift)]
            exits = [c for c in chains if len(c) == 2 and c[1] == "END" and not c[0].startswith("if_")]
            if len(exits) > 1:
                found.append(f"{fn.name}: {len(exits)} lines end at END — write [{', '.join(c[0].strip('[]') for c in exits)}] >> END")
            ends = {}
            for c in chains:
                if len(c) >= 3 and c[0].isidentifier() and c[-1].isidentifier():
                    ends.setdefault((c[0], c[-1]), []).append(c)
            found += [f"{fn.name}: {len(v)} chains from {k[0]} to {k[1]} — write {k[0]} >> [...] >> {k[1]}"
                      for k, v in ends.items() if len(v) > 1]
        assert found == [], f"{_rel(path)}: {found}"


    def test_every_model_reply_is_checked(self, path):
        if path.name != "graph.py":
            return
        tree = ast.parse(path.read_text(encoding="utf-8"))
        unchecked = []
        for fn, parent in _functions(tree):
            if parent is not None or "graph" not in _decorator_names(fn):
                continue
            body = ast.unparse(fn)
            for st in fn.body:
                if (isinstance(st, ast.Assign) and isinstance(st.value, ast.Call)
                        and "LLMOp" in ast.unparse(st.value.func)
                        and any(k.arg == "fields" for k in st.value.keywords)):
                    name = st.targets[0].id
                    optional = any(k.arg == "on_failure" and ast.unparse(k.value) == "'error'"
                                   for k in st.value.keywords)
                    handled = f"parsed(error={name}['error'])" in body or (
                        optional and f"={name}['error']" in body)
                    if not handled:
                        unchecked.append(f"{fn.name}.{name}")
        assert unchecked == [], (
            f"{_rel(path)}: {unchecked} — follow each with `x_parsed = parsed(error=x[\"error\"])` "
            f"and wire `x >> x_parsed >> ...`, or a reply that fails to parse becomes a verdict."
        )


def test_the_check_sees_a_nested_graph(tmp_path):
    """A guard that cannot fail is not a guard."""
    tree = ast.parse(
        "from operonx.core import graph\n"
        "def make():\n"
        "    @graph\n"
        "    def inner(x): ...\n"
        "    return inner\n"
    )
    assert [fn.name for fn, parent in _functions(tree)
            if parent is not None and _decorator_names(fn) & {"graph"}] == ["inner"]


def test_reading_the_corpus_or_the_config_builds_no_case_graph():
    """`src.corpus` and `src.core.config` are what the jobs read. Neither may
    load a case package: `config` once imported `src.cases` for its id list,
    and so did every job that only wanted the corpus hash."""
    import subprocess
    import sys

    code = ("import sys, src.corpus.loader, src.core.config; "
            "print(sorted(m for m in sys.modules if m.startswith('src.cases')))")
    out = subprocess.run([sys.executable, "-c", code], cwd=SRC.parent,
                         capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    assert out == "[]", out
