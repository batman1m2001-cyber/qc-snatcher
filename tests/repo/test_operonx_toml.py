"""Every graph `operonx.toml` names must import.

Two of its three entries pointed at modules the restructure removed
(`src.orchestrator`, `sentiment_agent._retrieval`); lint, extract and
studio read this file, and nothing else would notice.
"""
import importlib
import tomllib

import pytest

from tests._paths import ROOT
GRAPHS = tomllib.loads((ROOT / "operonx.toml").read_text(encoding="utf-8"))["graph"]


@pytest.mark.parametrize("entry", [g["entry"] for g in GRAPHS])
def test_graph_entry_imports(entry):
    module, _, attr = entry.partition(":")
    assert hasattr(importlib.import_module(module), attr), entry
