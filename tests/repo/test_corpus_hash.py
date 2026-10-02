"""The corpus hash has one definition, and it ignores line endings.

The seed stamps it into Postgres, startup compares against that stamp, and
the selfcheck manifest records it. Seven places used to compute it, two
ways: text mode (CRLF and lone CR become LF) and bytes with only CRLF
replaced. They agreed until a file held a lone CR.
"""
import ast
import json

from src.corpus.loader import CORPUS_YAML, corpus_file_hash

from tests._paths import ROOT


def test_line_endings_do_not_change_the_hash(tmp_path):
    body = "a:\n  positives:\n  - id: x\n    content: y\n"
    hashes = set()
    for name, text in (("lf", body), ("crlf", body.replace("\n", "\r\n")),
                       ("cr", body.replace("\n", "\r"))):
        f = tmp_path / f"{name}.yaml"
        f.write_bytes(text.encode("utf-8"))
        hashes.add(corpus_file_hash(f))
    assert len(hashes) == 1


def test_recorded_baseline_uses_the_same_hash():
    manifest = ROOT / "tests" / "sample" / "fixtures" / "manifest.json"
    recorded = json.loads(manifest.read_text(encoding="utf-8")).get("corpus_hash")
    assert recorded == corpus_file_hash(CORPUS_YAML), (
        "manifest corpus_hash differs from the corpus — either the corpus "
        "changed since the baseline was built, or someone hashes differently")


def test_nothing_else_hashes_the_corpus_by_hand():
    files = [p for p in [*ROOT.glob("src/**/*.py"), *ROOT.glob("app/**/*.py")]
             if "_archive" not in p.parts]
    hits = []
    for p in files:
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and ast.unparse(node.func) == "hashlib.sha1"
                    and "corpus" in ast.unparse(node).lower()):
                hits.append(f"{p.relative_to(ROOT).as_posix()}:{node.lineno}")
    allowed = {"src/corpus/loader.py"}
    hits = [h for h in hits if h.rsplit(":", 1)[0] not in allowed]
    assert hits == [], f"hash the corpus with corpus_file_hash: {hits}"
