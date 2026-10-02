"""The preflight job prints the routing, then runs its two checks in order
and stops at the first that fails — a later check against a broken earlier
one is noise. Whether the corpus is current is `ingest`'s question."""
import pytest

import src.jobs.preflight.ops as ops
from app.main import preflight as preflight_job
from operonx.app.jobs import RUN_FAILED, RUN_OK


@pytest.fixture
def calls(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(preflight_job, "record_dir", tmp_path)

    def stub(name, fail=False):
        def f(*a, **k):
            seen.append(name)
            if fail:
                raise RuntimeError(f"{name} is broken")
        return f

    def install(fail_at=None):
        monkeypatch.setattr(ops, "require_remote_retrieval", stub("backends", fail_at == "backends"))
        monkeypatch.setattr(ops, "require_reachable", stub("reachable", fail_at == "reachable"))
    return seen, install


def test_both_run_in_order_when_healthy(calls, capsys):
    seen, install = calls
    install()
    assert preflight_job.run_sync().status == RUN_OK
    assert seen == ["backends", "reachable"]
    assert "Stage -> resource" in capsys.readouterr().out  # the routing is printed first


@pytest.mark.parametrize("fail_at,ran", [
    ("backends", ["backends"]),
    ("reachable", ["backends", "reachable"]),
])
def test_stops_at_the_first_failure(calls, fail_at, ran):
    seen, install = calls
    install(fail_at)
    run = preflight_job.run_sync()
    assert run.status == RUN_FAILED
    assert seen == ran
    assert f"{fail_at} is broken" in (run.items[0].error or "")


def test_preflight_never_touches_the_corpus_store():
    import inspect

    assert not hasattr(ops, "_store") and "seed" not in inspect.signature(preflight_job.graph).parameters
