"""The refactor gate, inside the suite: the score job over the 90 fixture
calls, models replayed, every output file byte for byte against
`tests/sample/snapshot.json`. `python -m tests._snapshot` is the same check
with a report; `--write` re-records it when a change is meant to move outputs.
"""
import json

import pytest

from tests._snapshot import BASELINE, compare, take

pytestmark = pytest.mark.snapshot


def test_every_output_is_byte_identical(tmp_path):
    differ, trace_ok = compare(take(tmp_path), json.loads(BASELINE.read_text(encoding="utf-8")))
    assert differ == [], f"{len(differ)} outputs changed, e.g. {differ[:3]} — run `python -m tests._snapshot`"
    assert trace_ok, "the trace layout changed — run `python -m tests._snapshot`"
