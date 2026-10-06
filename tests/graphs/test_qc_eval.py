"""The `qc_eval` runbook: a QC batch against QC's labels. Offline — the one
end-to-end run replays the models from a recorded fixture call."""
from __future__ import annotations

import json
import shutil

import pytest
from openpyxl import Workbook
from operonx.app import Eval
from operonx.core import PARENT

from src.jobs.qc_eval import _batch, ops
from src.jobs.qc_eval.graph import score_agent
from src.jobs.selfcheck import _baseline
from tests._replay import build_stubs, install_stubs

#: A fixture call the scanner cleared: the recording covers every model it meets.
CALL = "E_duypd6_D_2026-07-24_H_172616_649_CLID_0900000001_4_83_NO_519418725"


def _sheet(path, rows, header_row=2, label_col="KQ QC hiện tại"):
    """A review sheet the way QC lays one out: a title row, then the header."""
    wb = Workbook()
    ws = wb.active
    if header_row == 2:
        ws.append(["", "", "0.75"])
    ws.append(["Call ID", "File name", "Call code", "Bên ngắt máy", "Tiêu chí", label_col, "Nhận xét của QC cho Ai"])
    for r in rows:
        ws.append(r)
    wb.save(path)


# ── the review sheet ────────────────────────────────────────────────────


def test_the_sheet_is_read_by_column_name_and_filtered_to_the_agent_criterion(tmp_path):
    _sheet(tmp_path / "r.xlsx", [
        [111, "a.wav", "Ngat_may", "AGENT", "Thái độ ĐTV", "thái độ warning", "quá gắt"],
        [111, "a.wav", "Ngat_may", "AGENT", "Thái độ KH", "Tiêu cực", ""],
        [222, "b.wav", "Hua_tra", "", "Thái độ ĐTV", "Tích cực", ""],
        [333, "c.wav", "Hua_tra", "", "Thái độ ĐTV", None, ""],
    ])
    rev = _batch.read_review(tmp_path / "r.xlsx")
    assert rev["111"] == {"call_code": "Ngat_may", "closed_by": "AGENT", "label": "thái độ warning",
                          "violation": True, "comment": "quá gắt"}
    assert rev["222"]["violation"] is False and rev["333"]["violation"] is None


def test_an_earlier_batchs_layout_reads_too(tmp_path):
    """The Aug 11–13 sheet named the label `KQ thủ công`, on the first row."""
    _sheet(tmp_path / "r.xlsx", [[111, "a.wav", "X", "", "Thái độ ĐTV", "Tích cực", ""]],
           header_row=1, label_col="KQ thủ công")
    assert _batch.read_review(tmp_path / "r.xlsx")["111"]["violation"] is False


def test_a_sheet_without_a_label_column_says_so(tmp_path):
    _sheet(tmp_path / "r.xlsx", [], label_col="something else")
    with pytest.raises(ValueError, match="Call ID"):
        _batch.read_review(tmp_path / "r.xlsx")


# ── which stage decided ─────────────────────────────────────────────────


@pytest.mark.parametrize("traces, stage", [
    ({"exit": {"stage": "no_violation"}, "scanner": {"violation": False}}, "scanner"),
    ({"exit": {"stage": "halu"}}, "halu_check"),
    ({"exit": {"stage": "kid"}}, "gate:kid"),
    ({"scanner": {"violation": True}, "decider": {"verdict": False}}, "decider"),
    ({"scanner": {"violation": True}, "decider": {"verdict": True},
      "primary_decider": {"enabled": True, "verdict": False}}, "primary"),
    ({"scanner": {"violation": True}, "decider": {"verdict": True},
      "primary_decider": {"enabled": True, "verdict": True}}, "flagged"),
])
def test_the_deciding_stage(traces, stage):
    assert ops.decided_by(traces) == stage


# ── one call, end to end ────────────────────────────────────────────────


@pytest.fixture
def batch(tmp_path):
    b = tmp_path / "round_x"
    (b / "transcripts").mkdir(parents=True)
    shutil.copy(_baseline.FX_INPUTS / f"{CALL}.json", b / "transcripts" / f"{CALL}.wav")
    _sheet(b / "review.xlsx", [[int(CALL.rsplit("_", 1)[1]), f"{CALL}.wav", "Nham_so", "CUSTOMER",
                                "Thái độ ĐTV", "Thái độ warning", "ĐTV quát khách"]])
    return b


def _run(batch):
    dataset = ops.QCBatch()
    qc_eval = Eval("qc_eval_score", graph=score_agent(item=PARENT, name="score_agent"),
                   dataset=dataset, evaluators=[ops.agrees_with_qc], threshold=0.0, inputs={"batch": str(batch)},
                   item_input="item", on_item=ops.Show(dataset), record_dir=batch.parent / "runs", trace=[])
    block = _baseline.sentiment_row(
        json.loads((_baseline.FX_OUTPUTS / f"{CALL}.json").read_text(encoding="utf-8")))["traces"]
    dataset.inputs = qc_eval.inputs
    install_stubs(qc_eval.engine().graph, build_stubs(block))
    run = qc_eval.run_sync()
    report = ops.write_report.__wrapped__(batch=str(batch), record_dir=str(batch.parent / "runs"))
    return run, report


def test_a_batch_is_scored_against_qc_and_reported(batch, capsys):
    run, report = _run(batch)
    assert run.status == "ok"
    assert f"[1/1] FN  {CALL}  at scanner" in capsys.readouterr().out  # QC flagged it; our scanner cleared it
    out = batch / "runs" / run.run_id
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert (summary["FN"], summary["TP"], summary["f1"]) == (1, 0, 0.0)
    assert set(summary["stamp"]) == {"git", "operonx", "corpus", "prompts", "models"}
    call = json.loads((out / "calls.json").read_text(encoding="utf-8"))[CALL]
    assert call["qc_comment"] == "ĐTV quát khách" and call["row"]["traces"]["scanner"]
    assert "FN by the stage that decided them: scanner 1" in (out / "stages.txt").read_text(encoding="utf-8")
    assert (out / "calls.xlsx").exists() and (out / "corpus.yaml").exists()
    pools = call["row"]["traces"].get("retrieval") or {}
    assert all(isinstance(x, str) for x in pools.get("positives") or [])  # ids; the text is in corpus.yaml
    assert (batch / "inputs" / f"{CALL}.json").exists()


def test_a_second_run_is_diffed_against_the_first(batch):
    _run(batch)
    run, _ = _run(batch)
    diff = (batch / "runs" / run.run_id / "diff.txt").read_text(encoding="utf-8")
    assert diff.startswith("fixed 0") and "broke 0" in diff


def test_set_batch_on_the_steps_reaches_the_dataset():
    """`operonx-run qc_eval --set batch=<folder>` sets every job's inputs
    before the run; the dataset reads the eval's own dict, so it sees it."""
    from argparse import Namespace

    from operonx.cli.run import _apply

    from app import main

    jobs = main.qc_eval.steps
    before = [dict(j.inputs) for j in jobs]
    try:
        _apply(main.qc_eval, Namespace(sets=["batch=data/qc/round_x"], record_dir=None, items=None,
                                       concurrency=None))
        assert main.QC_BATCH.inputs["batch"] == "data/qc/round_x"
        assert main.qc_eval_report.inputs["batch"] == "data/qc/round_x"
    finally:
        for j, was in zip(jobs, before):
            j.inputs.clear()
            j.inputs.update(was)
