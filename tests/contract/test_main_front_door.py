"""`python main.py` is a contract with the deployment: `--ingest`,
`--selfcheck`, the `PIPELINE_*` variables, the output files and the exit
status. It delegates to the `main` and `selfcheck` jobs (steps); this pins that
the contract survived the move.

| contract | pinned by |
|---|---|
| `--ingest` lets ingest seed; nothing else changes | `test_ingest_*` |
| `--selfcheck` runs the gate, not the batch, and uploads its record pass or fail | `test_selfcheck_*` |
| an old flag fails loudly, naming its variable | `test_an_old_flag_*` |
| exit 1 iff preflight or ingest fails | `test_exit_*` |
| a failed call is recorded, gets its file, and exits 0 | `test_a_failed_call_*` |
| every step runs in one event loop (the Triton client is bound to it) | `test_one_event_loop` |
| the `PIPELINE_*` defaults | `tests/contract/test_settings.py` |
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import app.main as app_main
import main
from app._score import Progress, build_job
from src.jobs.report.ops import summarize

MEMBERS = ("preflight", "ingest", "score", "report")


class FakeRun:
    def __init__(self, status="ok"):
        self.status = status
        self.counts = {"ok": 1}
        self.meta = {"error": None if status == "ok" else f"{status}: 1 failed"}
        self.run_id = "r"
        self.path = "runs/r"


@pytest.fixture
def runbook(monkeypatch, tmp_path):
    """The `main` job with each step's run replaced: records the order,
    the loop, and the inputs each job saw; *fail* names a job that fails."""
    monkeypatch.setattr(app_main.main, "record_dir", tmp_path)
    # operonx-run loads ./.env first; in a test that would leak into every test after it
    monkeypatch.setattr("operonx.cli.run._load_dotenv", lambda: None)
    seen = {"ran": [], "loops": [], "inputs": {}}

    def arrange(fail=None):
        for name in MEMBERS:
            job = getattr(app_main, name)
            monkeypatch.setattr(job, "inputs", dict(job.inputs))

            async def run(resume=False, job=job, **_):
                seen["ran"].append(job.name)
                seen["loops"].append(asyncio.get_running_loop())
                seen["inputs"][job.name] = dict(job.inputs)
                return FakeRun("failed" if job.name == fail else "ok")

            monkeypatch.setattr(job, "run", run)
        return seen
    return arrange


# ── the command ─────────────────────────────────────────────────────────


def test_ingest_lets_ingest_seed(runbook):
    seen = runbook()
    assert main.main(["--ingest"]) == 0
    assert seen["inputs"]["ingest"]["seed"] is True


def test_ingest_off_by_default(runbook):
    seen = runbook()
    assert main.main([]) == 0
    assert seen["inputs"]["ingest"]["seed"] is False
    assert seen["ran"] == list(MEMBERS)


@pytest.mark.parametrize("flag, var", [
    ("--input-path", "PIPELINE_INPUT_PATH"), ("--output-path=x", "PIPELINE_OUTPUT_PATH"),
    ("--files-list", "PIPELINE_FILES_LIST"), ("--max-concurrency", "PIPELINE_MAX_CONCURRENCY"),
])
def test_an_old_flag_fails_naming_its_variable(runbook, capsys, flag, var):
    seen = runbook()
    assert main.main([flag, "x"]) == 2
    assert var in capsys.readouterr().err and seen["ran"] == []


def test_an_unknown_argument_fails(runbook, capsys):
    runbook()
    assert main.main(["--progress-jsonl"]) == 2
    assert "only --ingest or --selfcheck" in capsys.readouterr().err


# ── the deploy gate ─────────────────────────────────────────────────────


@pytest.mark.parametrize("status", [0, 1])
def test_selfcheck_runs_the_gate_not_the_batch_says_the_verdict_and_uploads_either_way(monkeypatch, capsys, status):
    ran, sent = [], []
    monkeypatch.setattr(main, "operonx_run", lambda argv: ran.append(argv[-1]) or status)
    monkeypatch.setattr(main, "load_deploy_secrets", lambda: ran.append("secrets") or False)
    monkeypatch.setattr("src.jobs.selfcheck._gate.verdict", lambda *a: "selfcheck VERDICT")
    monkeypatch.setattr("src.jobs.selfcheck._gate.upload_record", lambda *a: sent.append(a) or 0)
    assert main.main(["--selfcheck"]) == status
    assert ran == ["secrets", "selfcheck"] and len(sent) == 1
    assert capsys.readouterr().out.strip().endswith("selfcheck VERDICT")


def test_selfcheck_with_ingest_is_refused(runbook, capsys):
    seen = runbook()
    assert main.main(["--selfcheck", "--ingest"]) == 2
    assert "drop --ingest" in capsys.readouterr().err and seen["ran"] == []


@pytest.mark.parametrize("fail, ran", [
    ("preflight", ["preflight"]),
    ("ingest", ["preflight", "ingest"]),
])
def test_exit_1_when_the_stack_is_not_fit_and_nothing_is_scored(runbook, fail, ran):
    seen = runbook(fail=fail)
    assert main.main([]) == 1
    assert seen["ran"] == ran


def test_exit_0_when_every_step_ran(runbook):
    runbook()
    assert main.main([]) == 0


def test_one_event_loop(runbook):
    """The Triton client is bound to the loop that made it: an ingest that
    embeds, then scoring in a second loop, would fail every embed with
    'Event loop is closed'."""
    seen = runbook()
    main.main([])
    assert len(seen["loops"]) == 4 and all(loop is seen["loops"][0] for loop in seen["loops"])


# ── a failed call ───────────────────────────────────────────────────────


class OneMissingCall:
    """A call whose transcript is gone: `load_call` fails, before any model."""

    skipped = 0

    def paths(self):
        return ["gone"]

    async def __aiter__(self):
        yield {"path": "does/not/exist.json", "name": "gone", "metadata": {"call_code": "Hua_tra"}}


def test_a_failed_call_is_recorded_gets_its_file_and_does_not_fail_the_run(tmp_path):
    job = build_job(output_path=tmp_path / "out", source=OneMissingCall(), record_dir=tmp_path / "runs",
                    on_item=lambda r: None)
    run = job.run_sync()
    assert run.status == "ok" and run.counts["failed"] == 1
    assert "error" in json.loads((tmp_path / "out" / "gone.json").read_text(encoding="utf-8"))


# ── configuration, progress, report ─────────────────────────────────────


def test_a_files_list_names_the_calls(tmp_path):
    lst = tmp_path / "files.txt"
    lst.write_text("b.json\n# comment\n\na.json\n", encoding="utf-8")
    job = build_job(input_path=tmp_path / "ignored", files_list=lst)
    assert [p.name for p in job.items.paths()] == ["a.json", "b.json"]


def test_progress_lines(capsys):
    progress = Progress(SimpleNamespace(paths=lambda: ["a", "b"]))
    for key, status in (("a", "ok"), ("x", "skipped"), ("b", "failed")):
        progress(SimpleNamespace(key=key, status=status, ms=1500))
    out = capsys.readouterr().out
    assert "[1/2] a.json -> OK (1.5s)" in out and "[2/2] b.json -> FAIL (1.5s)" in out and "x.json" not in out


def test_report_reads_the_score_record(tmp_path, capsys):
    from operonx.app.jobs.record import ItemResult, RunRecord

    inputs = tmp_path / "in"
    inputs.mkdir()
    for stem in ("a", "b", "c"):
        (inputs / f"{stem}.json").write_text("{}", encoding="utf-8")
    record = RunRecord(tmp_path / "runs", "score")
    record.item(ItemResult("a", "ok"))
    record.item(ItemResult("b", "failed", error="boom"))
    record.finish("ok")
    summarize.__wrapped__(input_path=str(inputs), output_path="out", record_dir=str(tmp_path / "runs"))
    out = capsys.readouterr().out
    assert "Total Files       : 3" in out and "Success           : 1" in out
    assert "Failed            : 1" in out and "Skipped           : 1" in out  # c: never reached the record


def test_report_without_a_score_run_says_so_and_never_raises(tmp_path, capsys):
    out = summarize.__wrapped__(record_dir=str(tmp_path / "nothing"))
    assert "nothing to report" in out["summary"]
