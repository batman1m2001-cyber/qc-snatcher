"""The suite's own rules.

| folder | holds |
|---|---|
| `contract/` | what MLE's deployment relies on: `main.py`, the output file, the `PIPELINE_*` names, the partner DDL |
| `repo/` | static rules over the repository: AST conventions, layout, prompts, graph shape |
| `graphs/` | graphs run with the models replayed or stubbed, the 90-call snapshot among them |
| `unit/` | one function or op at a time |
| `tests/_*.py` | the harness: env pinning, paths, the recording, replay stubs, the engine |

A test file never imports another test file — what two of them share
belongs in the harness. operonx's private graph internals are reached only
through the harness (`tests/_engine.py`, `tests/_replay.py`), so an operonx
upgrade that renames one breaks one file, not ten.
"""
import re

from tests._paths import ROOT

TEST_FILES = sorted((ROOT / "tests").rglob("test_*.py"))
FOLDERS = {"contract", "repo", "graphs", "unit"}
#: Built from parts so this file does not match itself.
PRIVATE = re.compile("|".join(r"\." + name + r"\b" for name in ("_ops", "_edges", "_set_core")))
IMPORTS_A_TEST = re.compile(r"^\s*(from|import) tests\.(\w+\.)?test_", re.M)


def _rel(path) -> str:
    return path.relative_to(ROOT).as_posix()


def test_every_test_file_sits_in_one_of_the_folders():
    assert [_rel(p) for p in TEST_FILES if p.parent.name not in FOLDERS] == []


def test_no_test_file_imports_another():
    hits = [_rel(p) for p in TEST_FILES if IMPORTS_A_TEST.search(p.read_text(encoding="utf-8"))]
    assert hits == [], f"{hits} — move what they share into the harness, tests/_*.py"


def test_the_pinned_env_covers_every_resource_variable():
    """A `${VAR}` in resources.yaml with no default must be pinned in
    tests/_env.py, or the suite needs a `.env` — which CI has not got."""
    from tests._env import PINNED

    needed = set(re.findall(r"\$\{([A-Z0-9_]+)\}", (ROOT / "resources.yaml").read_text(encoding="utf-8")))
    assert needed - set(PINNED) == set()


def test_operonx_internals_only_through_the_harness():
    hits = [_rel(p) for p in TEST_FILES if PRIVATE.search(p.read_text(encoding="utf-8"))]
    assert hits == [], f"{hits} — use tests/_engine.py (children, edges) or tests/_replay.py (answer_ops)"
