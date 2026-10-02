"""Tests for the `QC_ENABLE_<CASE_ID>` per-case boolean toggles.

Two layers under test:

  1. `env_bool` + `enabled_cases` — env → the frozenset of case ids on.
     Each case defaults ON when unset. Any typo raises at import time.
  2. `src.qc.graph.score_cases` switches each case node off at build time
     when ENABLED_CASES leaves it out.
"""


import pytest

from src.core import config
from src.core.env import env_bool
from src.cases import CASES
from tests._engine import children


class TestParseBoolEnv:

    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("QC_ENABLE_TEST", raising=False)
        assert env_bool("QC_ENABLE_TEST", default=True) is True
        assert env_bool("QC_ENABLE_TEST", default=False) is False

    def test_default_when_blank(self, monkeypatch):
        monkeypatch.setenv("QC_ENABLE_TEST", "   ")
        assert env_bool("QC_ENABLE_TEST", default=True) is True

    @pytest.mark.parametrize("token", ["1", "true", "TRUE", "Yes", "on"])
    def test_true_tokens(self, monkeypatch, token):
        monkeypatch.setenv("QC_ENABLE_TEST", token)
        assert env_bool("QC_ENABLE_TEST", default=False) is True

    @pytest.mark.parametrize("token", ["0", "false", "FALSE", "No", "off"])
    def test_false_tokens(self, monkeypatch, token):
        monkeypatch.setenv("QC_ENABLE_TEST", token)
        assert env_bool("QC_ENABLE_TEST", default=True) is False

    def test_typo_raises(self, monkeypatch):
        monkeypatch.setenv("QC_ENABLE_TEST", "flase")
        with pytest.raises(ValueError, match="not a boolean"):
            env_bool("QC_ENABLE_TEST", default=True)


class TestParseEnableFlags:

    def _clear(self, monkeypatch):
        for cid in CASES:
            monkeypatch.delenv(f"QC_ENABLE_{cid.upper()}", raising=False)

    def test_all_defaults_is_every_case(self, monkeypatch):
        self._clear(monkeypatch)
        assert config.enabled_cases() == frozenset(CASES)

    def test_all_explicit_true_is_every_case(self, monkeypatch):
        self._clear(monkeypatch)
        for cid in CASES:
            monkeypatch.setenv(f"QC_ENABLE_{cid.upper()}", "true")
        assert config.enabled_cases() == frozenset(CASES)

    def test_single_off_leaves_it_out(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv("QC_ENABLE_RABA", "false")
        got = config.enabled_cases()
        assert got == frozenset(cid for cid in CASES if cid != "raba")

    def test_all_off_yields_empty_set(self, monkeypatch):
        """Disabling every case is legal — the filter block hands an empty
        set down; `apply_case_selection` will simply disable every op."""
        self._clear(monkeypatch)
        for cid in CASES:
            monkeypatch.setenv(f"QC_ENABLE_{cid.upper()}", "false")
        assert config.enabled_cases() == frozenset()


class TestGraphBuildEnablesCases:
    """`score_cases` reads ENABLED_CASES when it is built."""

    def _enabled(self, monkeypatch, enabled):
        from operonx.core import PARENT

        from src.qc.graph import score_cases

        monkeypatch.setattr(config, "ENABLED_CASES", enabled)
        graph = score_cases(conversation=PARENT, call_code=PARENT, closed_by=PARENT,
                             is_chinh_chu=PARENT, queue_id=PARENT)
        return {cid for cid in CASES if children(graph)[cid].enabled}

    def test_every_id_enables_every_case(self, monkeypatch):
        assert self._enabled(monkeypatch, frozenset(CASES)) == set(CASES)

    def test_only_the_listed_cases_are_on(self, monkeypatch):
        assert self._enabled(monkeypatch, frozenset({"hangup", "raba"})) == {"hangup", "raba"}

    def test_empty_set_switches_every_case_off(self, monkeypatch):
        assert self._enabled(monkeypatch, frozenset()) == set()



def test_the_test_engine_names_its_root_qc_flow():
    """Regression: the helper built `score_cases` into a variable named
    `graph`, so every state key read `graph.sentiment_agent` and 96 replay
    tests found no verdict under `qc_flow.sentiment_agent`."""
    from tests._engine import create_engine

    engine, _ = create_engine()
    assert engine.graph.name == "qc_flow"
