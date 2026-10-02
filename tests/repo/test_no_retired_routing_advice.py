"""No message may tell an operator to set a retired routing variable.

Stage routing is `models.yaml` only. Two error messages kept saying "set
the four CORPUS_* variables" after that move, so an operator following
them would set variables nothing reads. This scans every string literal
the pipeline can print.
"""
import ast
import re
from pathlib import Path

from tests._paths import ROOT
SCANNED = [*ROOT.glob("src/**/*.py"), *ROOT.glob("app/**/*.py"), ROOT / "main.py"]
RETIRED = re.compile(
    r"CORPUS_\*|CORPUS_VECTOR_STORE_(POS|CVO)|CORPUS_DOC_STORE|"
    r"CORPUS_EMBEDDING_RESOURCE|SECONDARY_DECIDER_LLM_RESOURCE_KEY|"
    r"SENTIMENT_FILTER_RESOURCE")


def _string_literals(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            yield node.lineno, node.value


def test_no_message_names_a_retired_routing_variable():
    hits = [f"{p.relative_to(ROOT)}:{line}: {s[:80]!r}"
            for p in SCANNED if p.is_file()
            for line, s in _string_literals(p) if RETIRED.search(s)]
    assert not hits, "retired routing variables in messages:\n" + "\n".join(hits)
