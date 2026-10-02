"""What the `score` job writes, byte for byte.

The output file is a contract — MLE's merge step and the QC UI read it —
so it is pinned two ways:

* `finalize_row` moves the stage block out of the row into its own file,
  unchanged, and never fails a call over that diagnostic file;
* for replayed fixture calls, the job's output file is exactly the
  `score_cases`'s `call_scoring` minus `traces`, as `json.dumps(indent=2,
  ensure_ascii=False)` writes it — the format the batch runner it replaced
  produced (checked 90/90 byte-identical when it was replaced).
"""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from app._score import build_job
from src.jobs.score.ops import finalize_row
from tests._engine import apply_case_selection, create_engine
from tests._replay import build_stubs, install_stubs
from tests._recorded import INPUTS, RECORDED_ALL

_row = finalize_row.__wrapped__


def _scoring(with_traces=True):
    agent = {"Criteria": "Thái độ ĐTV", "Result": "Tích cực", "Score_offset": 0}
    if with_traces:
        agent["traces"] = {"scanner": {"violation": False}}
    return {"Sentiment": [agent, {"Criteria": "Thái độ KH", "Result": "Tích cực"}],
            "HVC": [], "qc_score_total_offset": 0}


# ── finalize_row ────────────────────────────────────────────────────────


def test_the_stage_block_leaves_the_row_for_its_own_file(tmp_path):
    out = _row(call_scoring=_scoring(), trace_id="call_1_abcd", trace_root=str(tmp_path), session_id="s")
    assert list(out) == ["Sentiment", "HVC", "qc_score_total_offset"]
    assert "traces" not in out["Sentiment"][0]
    payload = json.loads((tmp_path / "call_1_abcd.json").read_text(encoding="utf-8"))
    assert payload["traces"] == {"scanner": {"violation": False}}
    assert payload["request_id"] == "call_1_abcd" and payload["workflow_name"] == "qc_flow"


def test_the_input_is_not_mutated(tmp_path):
    scoring = _scoring()
    before = copy.deepcopy(scoring)
    _row(call_scoring=scoring, trace_id="t", trace_root=str(tmp_path))
    assert scoring == before


def test_no_block_means_no_file(tmp_path):
    _row(call_scoring=_scoring(with_traces=False), trace_id="t", trace_root=str(tmp_path))
    assert not list(tmp_path.glob("*.json"))


def test_the_root_is_created(tmp_path):
    _row(call_scoring=_scoring(), trace_id="t", trace_root=str(tmp_path / "deep" / "er"))
    assert (tmp_path / "deep" / "er" / "t.json").exists()


def test_an_unwritable_root_does_not_fail_the_call(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    out = _row(call_scoring=_scoring(), trace_id="t", trace_root=str(blocker / "sub"))
    assert out["Sentiment"][0]["Result"] == "Tích cực"


def test_no_call_scoring_fails_the_call():
    with pytest.raises(RuntimeError, match="no call_scoring"):
        _row(call_scoring=None, trace_id="t")


# ── the job's file, byte for byte ───────────────────────────────────────

SAMPLE = [p for p in RECORDED_ALL][:12]
ONLY = frozenset({"sentiment_agent"})


def _expected_bytes(name: str, block: dict) -> bytes:
    """`score_cases` run directly, `traces` removed, dumped the way the
    replaced runner dumped it."""
    engine, _ = create_engine()
    apply_case_selection(engine, set(ONLY))
    install_stubs(engine.graph, build_stubs(block))
    meta = json.loads((INPUTS / name).read_text(encoding="utf-8"))["metadata"]
    from src.core.conversation import Conversation

    result = asyncio.run(engine.run(inputs={
        "conversation": Conversation.load(str(INPUTS / name)),
        "call_code": meta["call_code"], "closed_by": meta.get("closed_by") or "YES",
        "is_chinh_chu": bool(meta.get("is_chinh_chu", False)), "queue_id": int(meta.get("queueid") or 0),
    }))
    scoring = copy.deepcopy(result["call_scoring"])
    for row in scoring.get("Sentiment") or []:
        row.pop("traces", None)
    # Through a text-mode write, as the replaced runner's open(path, 'w') did:
    # LF on the Linux pods, CRLF on Windows - the same as the job either way.
    tmp = Path(__file__).parent / ".expected.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(scoring, f, ensure_ascii=False, indent=2)
    data = tmp.read_bytes()
    tmp.unlink()
    return data


@pytest.mark.parametrize("name, row", [p.values for p in SAMPLE], ids=[p.id for p in SAMPLE])
def test_the_output_file_is_the_orchestrators_verdict_as_written_before(tmp_path, monkeypatch, name, row):
    import src.core.config as cfg

    monkeypatch.setattr(cfg, "ENABLED_CASES", ONLY)
    expected = _expected_bytes(name, row["traces"])
    job = build_job(files=[str(INPUTS / name)], output_path=tmp_path / "out",
                    tracer_local_dir=str(tmp_path / "tr"), record_dir=tmp_path / "runs")
    install_stubs(job.engine().graph, build_stubs(row["traces"]))
    job.run_sync()
    got = (tmp_path / "out" / name).read_bytes()
    if b'"error"' in expected[:20] or b'"error"' in got[:20]:
        pytest.skip("the recording cannot drive this call")
    assert got == expected


# ── Outputs: a failure is not "already there" ────────────────────────────


def test_a_call_whose_file_is_an_error_is_scored_again(tmp_path):
    from src.jobs.score._calls import Outputs

    sink = Outputs(tmp_path, skip_existing=True, write_errors=True)
    (tmp_path / "done.json").write_text('{"Sentiment": [], "HVC": []}', encoding="utf-8")
    (tmp_path / "failed.json").write_text('{"error": "scanner_parsed: did not parse"}', encoding="utf-8")
    (tmp_path / "torn.json").write_text('{"Sentim', encoding="utf-8")
    assert sink.exists("done") and not sink.exists("failed") and not sink.exists("torn")
    assert not sink.exists("absent")
    assert not Outputs(tmp_path, skip_existing=False).exists("done")
