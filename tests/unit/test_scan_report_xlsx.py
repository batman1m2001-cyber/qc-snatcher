"""scan_report_xlsx reads production exports, which may still carry the
layer-4 block under its old name `secondary_decider`. Reading only
`primary_decider` showed layer 4 as never run on every call."""

import pytest

from tools import scan_report as scan


@pytest.mark.parametrize("key", ["primary_decider", "secondary_decider"])
def test_layer_4_reads_either_key(key):
    t = {key: {"enabled": True, "verdict": True, "severity_final": "warning",
               "cited_positives": [], "cited_carveouts": []}}
    value, _ = scan.layer_4(t, {})
    assert value == "yes"


def test_new_key_wins_when_both_present():
    t = {"primary_decider": {"verdict": False}, "secondary_decider": {"verdict": True}}
    assert scan.primary_block(t)["verdict"] is False
