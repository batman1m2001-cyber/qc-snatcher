"""Every prompt the baseline manifest hashes must exist.

`selfcheck_build` would skip a missing path, so a prompt that moved (the l4
flatten moved two) drops out of the manifest and a later edit to it no
longer shows as drift.
"""
from pathlib import Path

import pytest

from src.jobs.selfcheck._baseline import ROOT, TRACKED_PROMPTS


@pytest.mark.parametrize("rel", TRACKED_PROMPTS)
def test_tracked_prompt_exists(rel):
    assert (Path(ROOT) / rel).is_file(), f"{rel} does not exist — update TRACKED_PROMPTS"
