"""No module may reference a name that does not exist.

Written after the four-layer split shipped six of them. `ea11776` moved the
contents of `_matcher.py` into layer packages and left the context-window
block behind: `l3_decider/_decider_ops.py` kept verbatim copies of
`_window_for` and `_build_verifier_context` without the table they read, and
`l2_scanner/_evidence.py` kept neither.

**All 741 tests passed with all six missing.** They are `NameError`s inside
op bodies, so they fire only when something drives that path, and
`tests/_replay.py` stubs op *cores* — the bodies never run. What surfaced
instead, a day later, was five `[llm timeout]` lines against a healthy
endpoint: the failing op left `l2` with no evidence, the decider was handed
a 4,211-character prompt identical on every call, and the model stalled on
a question with nothing in it.

Import alone would not have caught it either. A missing module-level
constant is legal at import time and fails only when the line executes, so
`import src.cases...` succeeds and the package looks fine.

This is the cheap instrument for that: pyflakes resolves every name against
what the module actually binds, in under a second, without running
anything. It is the standard failure mode of splitting a module and it will
happen again.

Scope is deliberately narrow — **undefined names only** (F821-equivalent).
Unused imports and shadowed names are style, they are numerous here already,
and a test that fails on them would be turned off within a week.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests._paths import ROOT

#: Trees that must resolve. `scripts/_archive/` is excluded on purpose: it
#: holds one-off probes kept for reference, gitignored, and several import
#: from modules that no longer exist. They are history, not code that runs.
_TREES = ("src", "tests")

#: pyflakes prefixes the two undefined-name diagnostics with this. Matching
#: the message rather than a code because pyflakes emits no codes.
_UNDEFINED = "undefined name"


def _pyflakes(tree: str) -> "list[str]":
    """Undefined-name complaints from one tree, one line each."""
    proc = subprocess.run(
        [sys.executable, "-m", "pyflakes", tree],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # pyflakes exits 1 when it reports anything at all, including the unused
    # imports this test ignores, so the exit code says nothing. Only a
    # missing pyflakes (exit 2, empty stdout) is a real failure to run.
    if proc.returncode not in (0, 1) and not proc.stdout:
        pytest.fail(
            f"could not run pyflakes over {tree}/: "
            f"exit {proc.returncode}\n{proc.stderr.strip()}"
        )
    return [ln for ln in proc.stdout.splitlines() if _UNDEFINED in ln]


class TestEveryNameResolves:
    @pytest.mark.parametrize("tree", _TREES)
    def test_no_undefined_names(self, tree: str):
        found = _pyflakes(tree)
        assert found == [], (
            f"{len(found)} undefined name(s) in {tree}/ — each one is a "
            f"NameError waiting for the path that reaches it:\n  "
            + "\n  ".join(found)
        )

    def test_the_check_can_actually_fail(self, tmp_path: Path):
        """A guard that cannot fail is not a guard.

        Without this, a pyflakes that silently stopped reporting — renamed
        message, changed output stream, installed-but-broken — would leave
        the test above green forever, which is the same blindness it exists
        to remove.
        """
        broken = tmp_path / "broken_module.py"
        broken.write_text(
            "def f():\n    return SOME_CONSTANT_THAT_DOES_NOT_EXIST\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, "-m", "pyflakes", str(broken)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        assert _UNDEFINED in proc.stdout, (
            "pyflakes did not report a plainly undefined name — the check "
            f"above is not measuring anything.\nstdout: {proc.stdout!r}\n"
            f"stderr: {proc.stderr!r}"
        )
