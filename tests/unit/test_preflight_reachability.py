"""Ask once whether the network answers, instead of 90 times.

`require_remote_retrieval` checks what a resource *is*; constructing its
client opens no socket. So a run off the VPN cleared every startup check
and then failed one call at a time, each waiting out its own deadline,
with no line saying why. Measured on this machine: the whole set resolves
in about three seconds and names what did not answer.

Nothing here touches the network — the probe itself is operonx's and is
tested there. What is tested here is which keys get checked, that the
list is assembled from the environment rather than frozen at import, and
that the escape hatch is loud.
"""
from __future__ import annotations

import pytest

from src.core import config
from src.jobs.preflight import ops as preflight


class TestResourceKeys:
    def test_it_covers_retrieval_and_the_models(self):
        keys = preflight.resource_keys()
        kinds = {k.split(":", 1)[0] for k in keys}
        assert {"vector_store", "doc_store", "embedding", "llm"} <= kinds

    def test_both_pools_are_checked(self):
        """One store answering does not mean the other does."""
        stores = [k for k in preflight.resource_keys() if k.startswith("vector_store:")]
        assert len(stores) == 2, stores

    def test_duplicates_collapse(self, monkeypatch):
        """Two stages on one model must not report the host twice."""
        monkeypatch.setattr(config, "LLM_RESOURCE_KEY", "same-model")
        monkeypatch.setattr(config, "DECIDER_LLM_RESOURCE_KEY", "same-model")
        keys = preflight.resource_keys()
        assert keys.count("llm:same-model") == 1

    def test_the_optional_models_join_when_configured(self, monkeypatch):
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "strict-judge")
        monkeypatch.setattr(config, "SOFTEN_LLM_RESOURCE_KEY", "rewriter")
        keys = preflight.resource_keys()
        assert "llm:strict-judge" in keys
        assert "llm:rewriter" in keys

    def test_an_unset_optional_model_is_not_invented(self, monkeypatch):
        """`llm:` with no name would fail the check for a stage never run."""
        monkeypatch.setattr(config, "PRIMARY_DECIDER_LLM_RESOURCE_KEY", "")
        monkeypatch.setattr(config, "PREFILTER_LLM_RESOURCE_KEY", "")
        assert not any(k == "llm:" or k.endswith(":") for k in preflight.resource_keys())

    def test_a_blank_optional_model_is_ignored(self, monkeypatch):
        monkeypatch.setattr(config, "PREFILTER_LLM_RESOURCE_KEY", "   ")
        assert not any(k.endswith(":") for k in preflight.resource_keys())

    def test_the_list_is_read_at_call_time(self, monkeypatch):
        """Frozen at import, it would check the wrong things after a
        config change — and the whole point is to reflect this run."""
        before = preflight.resource_keys()
        monkeypatch.setattr(config, "SOFTEN_LLM_RESOURCE_KEY", "late-arrival")
        assert "llm:late-arrival" in preflight.resource_keys()
        assert "llm:late-arrival" not in before


class TestSkipHatch:
    """Skipping must be deliberate and audible.

    A replay run stubs every network op, so reaching out would be the bug
    rather than the check. But a silent skip is how a real run ends up
    unchecked, so it logs a warning naming the variable.
    """

    def test_it_skips_when_set(self, monkeypatch):
        """Asserted by what it does not do — the hub is never consulted.

        Not by the log text: the pipeline configures its own handlers and
        this logger does not propagate, so `caplog` sees nothing. Which is
        the better test regardless — skipping is the behaviour, the
        warning is how it announces itself.
        """
        touched = []

        class _Hub:
            def require_reachable(self, *keys, timeout=None):
                touched.append(keys)

        import operonx.core.registry as reg

        monkeypatch.setattr(reg.ResourceHub, "instance", classmethod(lambda cls: _Hub()))
        preflight.require_reachable(skip=True)
        assert touched == [], "skipping must not probe anything"

    def test_skipping_says_so(self, monkeypatch):
        """A silent skip is how a real run ends up unchecked."""
        said = []
        monkeypatch.setattr(
            preflight.logger, "warning",
            lambda msg, *a, **k: said.append(msg % a if a else msg),
        )
        preflight.require_reachable(skip=True)
        assert said and "PIPELINE_SKIP_REACHABILITY" in said[0]

    def test_it_does_not_skip_by_default(self, monkeypatch):
        """The tokens are `app/settings.py`'s (`tests/contract/test_settings.py`)."""
        calls = {}

        class _Hub:
            def require_reachable(self, *keys, timeout=None):
                calls["keys"] = keys

        import operonx.core.registry as reg

        monkeypatch.setattr(reg.ResourceHub, "instance", classmethod(lambda cls: _Hub()))
        preflight.require_reachable()
        assert calls.get("keys"), "the check must have run"

    def test_it_passes_every_key_to_the_hub(self, monkeypatch):
        seen = {}

        class _Hub:
            def require_reachable(self, *keys, timeout=None):
                seen["keys"] = list(keys)
                seen["timeout"] = timeout

        import operonx.core.registry as reg
        monkeypatch.setattr(reg.ResourceHub, "instance", classmethod(lambda cls: _Hub()))
        preflight.require_reachable()
        assert seen["keys"] == preflight.resource_keys()
        assert seen["timeout"] == preflight._REACH_TIMEOUT

    def test_a_failure_propagates(self, monkeypatch):
        """The point is to stop the run, not to note it and carry on."""
        from operonx.core.registry import ResourceUnreachable

        class _Hub:
            def require_reachable(self, *keys, timeout=None):
                raise ResourceUnreachable({"embedding:x": "no answer"})

        import operonx.core.registry as reg
        monkeypatch.setattr(reg.ResourceHub, "instance", classmethod(lambda cls: _Hub()))
        with pytest.raises(ResourceUnreachable):
            preflight.require_reachable()
