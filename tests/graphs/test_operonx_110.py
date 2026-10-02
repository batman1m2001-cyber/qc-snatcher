"""What moving to operonx 1.10 had to pin down.

Each of these changed silently between 1.7 and 1.10 — nothing raised, the
run finished, and something landed somewhere else:

| test | the 1.10 change |
|---|---|
| traces stay flat | `LocalConsumer`'s default layout files a job's traces under `jobs/<job>/<run>/`, away from the stage files |
| tracing off stays off | inside an `Application`, a job with `trace=None` is given a plain `LocalConsumer` — whole transcripts, unredacted |
| the root name is pinned | a job's root was named after a variable inside operonx's own `job.py` (`params`) |
| no moved import paths | `operonx.core.jobs` is an alias that already announces its removal |
"""
from __future__ import annotations

import re
from pathlib import Path

from operonx.app.declare import inherit_trace

from src.jobs.score._tracing import QCLocalConsumer, QCLocalConsumerConfig
from app._score import build_job
from tests._paths import ROOT
from tests._recorded import INPUTS, RECORDED_ALL
from tests._replay import build_stubs, install_stubs

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def test_the_qc_consumer_defaults_to_the_flat_layout():
    assert QCLocalConsumer.DEFAULT_CONFIG["layout"] == "flat"
    assert QCLocalConsumerConfig().layout == "flat"


def test_a_traced_call_lands_in_one_folder_under_the_root(tmp_path, monkeypatch):
    import src.core.config as cfg

    monkeypatch.setattr(cfg, "ENABLED_CASES", frozenset({"sentiment_agent"}))
    name, row = RECORDED_ALL[0].values
    job = build_job(files=[str(INPUTS / name)], output_path=tmp_path / "out", tracer_kind="local",
                    tracer_local_dir=str(tmp_path / "tr"), record_dir=tmp_path / "runs")
    install_stubs(job.engine().graph, build_stubs(row["traces"]))
    job.run_sync()
    dirs = [p for p in (tmp_path / "tr").iterdir() if p.is_dir()]
    assert [p.name for p in dirs if not UUID.match(p.name)] == [], "a trace folder that is not <trace_id>/"
    assert len(dirs) == 1 and (dirs[0] / "meta.json").exists()


def test_tracing_off_stays_off_inside_an_application(tmp_path):
    job = build_job(files=[], output_path=tmp_path, tracer_kind="none")
    assert job.trace == []
    inherit_trace(job, None)  # what an Application does to each of its jobs
    assert job.trace == []


def test_the_score_jobs_root_is_named_score_call(tmp_path):
    job = build_job(files=[], output_path=tmp_path)
    assert job.engine().name == "score_call"


def test_nothing_imports_a_moved_operonx_path():
    moved = ("operonx.core.jobs", "operonx.core.manifest", "operonx.core.serve")
    files = [*ROOT.glob("src/**/*.py"), *ROOT.glob("app/**/*.py"), *ROOT.glob("tests/**/*.py"), ROOT / "main.py"]
    hits = [f"{p.relative_to(ROOT)}: {m}" for p in files if p.name != Path(__file__).name
            for m in moved if m in p.read_text(encoding="utf-8")]
    assert hits == []


def test_through_operonx_toml_nothing_traces_unless_it_says_so():
    """`operonx-run` loads the app through operonx.toml. operonx 1.10.0
    dropped the object's empty `trace=[]` there, and every job with no
    consumers of its own recorded whole runs under .operonx/runs; 1.10.1
    keeps it (the pin is >= 1.11.0)."""
    from operonx.app import Application

    assert Application.find(ROOT).manifest.project.get("trace") == []
