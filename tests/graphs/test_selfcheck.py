"""selfcheck_score (an operonx Eval), selfcheck_build, and the `selfcheck`
runbook around them — the deploy gate. Offline: the one end-to-end run replays the models from the recorded
baseline, the way `tests/_snapshot.py` does."""
from __future__ import annotations

import json
import shutil
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from operonx.app import Eval
from operonx.core import PARENT

from src.core import config
from src.jobs.selfcheck import _baseline, ops
from src.jobs.selfcheck.graph import score_fixture
from tests._replay import build_stubs, install_stubs

#: A fixture call the scanner cleared: the recording covers every model it meets.
CALL = "E_duypd6_D_2026-07-24_H_172616_649_CLID_0900000001_4_83_NO_519418725"


def _row(result="Tích cực", violation=False, cited=None, traces=True):
    row = {"Criteria": _baseline.CRITERIA, "Result": result, "Score_offset": 0, "EvidenceIdxs": []}
    if traces:
        row["traces"] = {"scanner": {"violation": violation, "category_raw": "C1"},
                         "decider": {"verdict": violation, "cited_positives": cited or []}}
    return row


def _scoring(row):
    return {"call_scoring": {"Sentiment": [row], "HVC": [], "qc_score_total_offset": 0}}


# ── the evaluator ───────────────────────────────────────────────────────


def test_an_identical_row_matches_and_carries_what_was_scored():
    v = ops.matches_baseline(output=_scoring(_row()), expected=_row())
    assert v["passed"] and v["hard"] == [] and v["scored"]["Sentiment"][0]["Result"] == "Tích cực"


def test_a_hard_difference_fails_and_says_which():
    v = ops.matches_baseline(output=_scoring(_row(result="Thái độ cao")), expected=_row())
    assert not v["passed"] and v["reason"] == "Result: 'Thái độ cao' != 'Tích cực'"


def test_a_soft_difference_is_listed_but_passes():
    v = ops.matches_baseline(output=_scoring(_row(cited=["P2"])), expected=_row(cited=["P1"]))
    assert v["passed"] and v["soft"] == ["decider.cited_p: ['P2'] != ['P1']"]


@pytest.mark.parametrize("side", ["output", "expected"])
def test_no_stage_block_is_blind_not_a_pass(side):
    """7 of the 10 HARD rules read the stage block; without it they compare
    None to None and agree — a higher rate, with no symptom."""
    rows = {"output": _scoring(_row()), "expected": _row()}
    rows[side] = _scoring(_row(traces=False)) if side == "output" else _row(traces=False)
    v = ops.matches_baseline(**rows)
    assert not v["passed"] and v["reason"].startswith("blind")


def test_no_sentiment_row_fails():
    assert not ops.matches_baseline(output={"call_scoring": {"Sentiment": []}}, expected=_row())["passed"]


# ── the cases ───────────────────────────────────────────────────────────


def test_every_manifest_call_is_a_case_with_its_baseline_row():
    rows = ops.Fixtures().rows()
    assert len(rows) == len(_baseline.manifest()["selected"]) == 90
    assert all(r["input"]["metadata"].get("call_code") for r in rows)
    assert all(r["expected"]["Criteria"] == _baseline.CRITERIA and "traces" in r["expected"] for r in rows)
    assert {r["id"] for r in rows} == {p.stem for p in _baseline.FX_INPUTS.glob("*.json")}


def test_an_empty_manifest_raises_rather_than_passing(tmp_path, monkeypatch):
    (tmp_path / "manifest.json").write_text('{"selected": []}', encoding="utf-8")
    monkeypatch.setattr(_baseline, "MANIFEST", tmp_path / "manifest.json")
    with pytest.raises(RuntimeError, match="no fixture calls"):
        ops.Fixtures().rows()


# ── one call through the eval, end to end ───────────────────────────────


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    """A one-call fixture in a temp tree, pointed at by every selfcheck path."""
    for d in ("inputs", "outputs"):
        (tmp_path / d).mkdir()
        shutil.copy(_baseline.FIXTURE_DIR / d / f"{CALL}.json", tmp_path / d)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"selected": [{"filename": f"{CALL}.json", "class": "neg"}], "corpus_hash": ""}),
        encoding="utf-8")
    monkeypatch.setattr(_baseline, "FX_INPUTS", tmp_path / "inputs")
    monkeypatch.setattr(_baseline, "FX_OUTPUTS", tmp_path / "outputs")
    monkeypatch.setattr(_baseline, "MANIFEST", tmp_path / "manifest.json")
    return tmp_path


def _run(fixture):
    """The eval as `app/main.py` declares it, over the fixture, models replayed."""
    selfcheck = Eval("selfcheck_score", graph=score_fixture(item=PARENT, name="score_fixture"),
                     dataset=ops.Fixtures(), evaluators=[ops.matches_baseline], threshold=0.85,
                     item_input="item", on_item=ops.Show(), record_dir=fixture / "runs", trace=[])
    block = _baseline.sentiment_row(
        json.loads((fixture / "outputs" / f"{CALL}.json").read_text(encoding="utf-8")))["traces"]
    install_stubs(selfcheck.engine().graph, build_stubs(block))
    return selfcheck.run_sync()


def test_the_eval_scores_the_call_and_matches_the_baseline(fixture, capsys):
    run = _run(fixture)
    assert run.status == "ok" and run.meta["eval"]["pass_rate"] == 1.0
    assert f"PASS  {CALL}" in capsys.readouterr().out
    check = run.items[0].verdict["checks"][ops.EVALUATOR]
    assert _baseline.sentiment_row(check["scored"])["traces"]  # the whole row, stage block inline


def test_the_stage_block_is_there_with_traces_off(fixture, monkeypatch):
    """The eval passes `include_traces=True` as data: a deployment running
    with traces off still compares every HARD rule, and nothing flips the
    process setting (the old sample source set `config.INCLUDE_TRACES`)."""
    monkeypatch.setattr(config, "INCLUDE_TRACES", False)
    run = _run(fixture)
    assert run.meta["eval"]["pass_rate"] == 1.0 and config.INCLUDE_TRACES is False


def test_under_the_threshold_the_run_fails(fixture, capsys):
    path = fixture / "outputs" / f"{CALL}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    _baseline.sentiment_row(data)["Result"] = "Thái độ cao"  # the baseline says otherwise
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    run = _run(fixture)
    assert run.status == "failed" and run.meta["eval"]["pass_rate"] == 0.0
    assert "FAIL" in capsys.readouterr().out


# ── selfcheck_build ─────────────────────────────────────────────────────


def test_build_promotes_the_run_from_its_record(fixture, monkeypatch):
    run = _run(fixture)
    before = (fixture / "outputs" / f"{CALL}.json").read_text(encoding="utf-8")
    scored = ops.read_run.__wrapped__(record_dir=str(fixture / "runs"))["scored"]
    assert list(scored) == [CALL]

    assert ops.promote.__wrapped__(scored=scored, dry_run=True)["report"] == {"differ": 0, "written": False}
    assert (fixture / "outputs" / f"{CALL}.json").read_text(encoding="utf-8") == before
    assert "rebuilt_by" not in _baseline.manifest()

    assert ops.promote.__wrapped__(scored=scored, dry_run=False)["report"]["written"]
    promoted = json.loads((fixture / "outputs" / f"{CALL}.json").read_text(encoding="utf-8"))
    assert promoted == run.items[0].verdict["checks"][ops.EVALUATOR]["scored"]
    m = _baseline.manifest()
    assert m["rebuilt_by"] == "operonx-run selfcheck_build"
    assert set(m["prompt_hashes"]) == {Path(p).name for p in _baseline.TRACKED_PROMPTS}


def test_build_refuses_without_a_run(tmp_path):
    with pytest.raises(RuntimeError, match="no selfcheck_score run"):
        ops.read_run.__wrapped__(record_dir=str(tmp_path))


def test_build_refuses_a_run_missing_a_manifest_call(fixture, monkeypatch):
    _run(fixture)
    m = json.loads(_baseline.MANIFEST.read_text(encoding="utf-8"))
    m["selected"].append({"filename": "E_not_scored.json", "class": "neg"})
    _baseline.MANIFEST.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(RuntimeError, match="1 of 2 calls"):
        ops.read_run.__wrapped__(record_dir=str(fixture / "runs"))


# ── as declared, and the deploy gate ────────────────────────────────────


def test_selfcheck_score_is_the_eval_over_the_scoring_graph():
    from app.main import selfcheck_score

    assert isinstance(selfcheck_score, Eval) and selfcheck_score.graph.name == "score_fixture"
    assert selfcheck_score.evaluators == [ops.matches_baseline] and selfcheck_score.threshold == 0.85
    assert selfcheck_score.dataset.path == _baseline.MANIFEST


def test_the_gate_seeds_before_it_scores():
    """A corpus.yaml change lands with the deploy: scored against a stale
    store, the fixture would judge the old corpus."""
    from app.main import ingest, selfcheck

    assert [j.name for j in selfcheck.steps] == ["preflight", "ingest", "selfcheck_score"]
    assert selfcheck.steps[1].inputs["seed"] is True
    assert ingest.inputs["seed"] is False  # a pod never seeds unless --ingest


def test_the_gate_stops_at_the_first_failed_step(monkeypatch, tmp_path):
    from app.main import selfcheck as deploy

    ran = []
    for job in deploy.steps:
        async def run(resume=False, job=job, **_):
            ran.append(job.name)
            return SimpleNamespace(status="failed" if job.name == "preflight" else "ok",
                                   run_id="x", path=tmp_path, counts={}, meta={},
                                   summary=lambda: job.name)
        monkeypatch.setattr(job, "run", run)
    monkeypatch.setattr(deploy, "record_dir", tmp_path)
    assert deploy.run_sync().status != "ok" and ran == ["preflight"]


def test_the_upload_is_keyed_by_run_id(fixture, monkeypatch):
    from src.jobs.selfcheck import _gate as door

    run = _run(fixture)
    sent = []
    fake = types.ModuleType("boto3")
    fake.client = lambda name: SimpleNamespace(upload_file=lambda src, bucket, key: sent.append((bucket, key)))
    monkeypatch.setitem(sys.modules, "boto3", fake)
    assert door.upload_record("b", "prefix/", str(fixture / "runs")) == 2
    assert sent == [("b", f"prefix/selfcheck/{run.run_id}/run.json"), ("b", f"prefix/selfcheck/{run.run_id}/items.jsonl")]


def test_no_bucket_no_upload():
    from src.jobs.selfcheck import _gate as door

    assert door.upload_record("", "prefix") == 0 and door.upload_record("b", "") == 0


# ── the deploy gate gets the deployment's credentials ───────────────────


def test_deploy_secrets_import_settings(monkeypatch):
    import main as door

    monkeypatch.setitem(sys.modules, "settings", types.ModuleType("settings"))
    assert door.load_deploy_secrets() is True


def test_no_settings_module_is_not_an_error(monkeypatch):
    import main as door

    monkeypatch.setitem(sys.modules, "settings", None)  # import raises ImportError
    assert door.load_deploy_secrets() is False


def test_settings_that_fail_stop_the_deploy(monkeypatch, tmp_path):
    """B4: Secrets Manager refusing must not be swallowed — the gate would
    run without secrets and fail somewhere far away."""
    import main as door

    (tmp_path / "settings.py").write_text("raise RuntimeError('AccessDenied: secretsmanager')\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "settings", raising=False)
    with pytest.raises(RuntimeError, match="AccessDenied"):
        door.load_deploy_secrets()


def test_the_gate_loads_the_secrets_before_src():
    """`src` reads the env file at import, so the secrets must be in it
    first: nothing at `main.py`'s top level, or in `app/__init__.py`, may
    import `src` or the application."""
    import ast

    for path in ("app/__init__.py", "main.py"):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        mods = [(n.module or "") if isinstance(n, ast.ImportFrom) else n.names[0].name for n in top]
        assert not [m for m in mods if m.startswith(("src", "app"))], (path, mods)
    text = Path("main.py").read_text(encoding="utf-8")
    assert text.index("load_deploy_secrets()\n") < text.index("operonx_run([\"-f\", str(MANIFEST), \"selfcheck\"])")


def test_each_line_says_how_far_the_run_is(capsys):
    """The Eval's line printer lost the old script's `[n/90]` counter."""
    from types import SimpleNamespace

    show = ops.Show()
    show(SimpleNamespace(key="a", verdict={"passed": True}, status="ok"))
    show(SimpleNamespace(key="b", verdict={"passed": False, "checks": {ops.EVALUATOR: {"reason": "x != y"}}}, status="ok"))
    total = len(ops.baseline.manifest()["selected"])
    assert capsys.readouterr().out.splitlines() == [f"[1/{total}] PASS  a", f"[2/{total}] FAIL  b  x != y"]


# ── the verdict line ────────────────────────────────────────────────────


def _gate_record(tmp_path, monkeypatch, steps, ev=None):
    """A `selfcheck` record (a job of steps): *steps* are (name, status, scored?)."""
    import operonx.app.jobs as jobs

    meta = []
    for name, status, scored in steps:
        step = {"name": name, "status": status}
        if scored:
            (tmp_path / name).mkdir()
            (tmp_path / name / "run.json").write_text(json.dumps({"eval": ev}), encoding="utf-8")
            step["path"] = str(tmp_path / name)
        meta.append(step)
    monkeypatch.setattr(jobs, "last_run",
                        lambda root, name: SimpleNamespace(path=tmp_path, meta={"steps": meta}))


EV = {"cases": 90, "passed": 79, "errored": 0, "pass_rate": 0.8778, "threshold": 0.85}


@pytest.mark.parametrize("status, word", [("ok", "PASS"), ("failed", "FAIL")])
def test_the_gate_says_its_match_rate(tmp_path, monkeypatch, status, word):
    """The steps job's own last line counts steps, not calls — a 79/90 run
    once ended on `jobs ok=3` with no rate anywhere on screen."""
    from src.jobs.selfcheck._gate import verdict

    _gate_record(tmp_path, monkeypatch, [("preflight", "ok", False), ("ingest", "ok", False),
                                         ("selfcheck_score", status, True)], EV)
    assert verdict().startswith(f"selfcheck {word} - 79/90 match = 87.8% (threshold 85%")


def test_the_gate_names_the_step_that_stopped_it(tmp_path, monkeypatch):
    from src.jobs.selfcheck._gate import verdict

    _gate_record(tmp_path, monkeypatch, [("preflight", "ok", False), ("ingest", "failed", False)])
    assert verdict() == "selfcheck FAIL - ingest failed, nothing scored"
