"""The score job: `build_job` turns a run's settings (`app/settings.py`)
into the job `main` runs, with one progress line per call."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable, List, Optional

from operonx.app.jobs import Job
from operonx.core import PARENT

from src.jobs.score._calls import Calls, Outputs
from src.jobs.score.graph import score_call


def _tracer(kind: str, local_dir: str) -> Optional[Any]:
    """The on-disk trace consumer, or None. Remote tracers are refused: the
    graph passes whole transcripts through a dozen ops (PII)."""
    kind = (kind or "none").lower()
    if kind == "none":
        return None
    if kind == "local":
        from src.jobs.score._tracing import QCLocalConsumer

        return QCLocalConsumer(config={"root": str(local_dir)})
    if kind == "langfuse":
        raise ValueError(
            "tracer_kind='langfuse' is disabled — a remote tracer would leak "
            "customer transcripts (PII). Use 'local' or 'none'."
        )
    raise ValueError(f"Unknown tracer_kind: {kind!r}. Use 'local' or 'none'.")


def build_job(
    input_path: "str | Path" = "samples",
    output_path: "str | Path" = "outputs/qc",
    *,
    files: Optional[List[str]] = None,
    files_list: "str | Path | None" = None,
    skip_if_exists: bool = False,
    tracer_kind: str = "none",
    tracer_local_dir: str = "./traces",
    max_concurrency: int = 2,
    on_item: Optional[Callable[[Any], Any]] = None,
    record_dir: "str | Path" = ".runs",
    source: Optional[Calls] = None,
) -> Job:
    """The scoring job over *input_path* (or *files* / *files_list*) into
    *output_path*.

    A failed call is recorded, not fatal (`on_error="record"`): it still
    gets its file, `{"error": ...}`, so every input has an output a
    downstream reader can check, and the batch — the `main` runbook — does
    not fail over one call. The stage file goes to *tracer_local_dir*
    whether or not op tracing is on — INCLUDE_TRACES alone decides it.

    *source* replaces the files (a test's calls). *on_item* defaults to one
    progress line per call.
    """
    calls = source if source is not None else Calls(input_path, files, files_list)
    tracer = _tracer(tracer_kind, tracer_local_dir)
    return Job(
        "score",
        # Built here so its name is pinned: from a bare factory, operonx
        # names the root after a variable inside its own job.py (`params`),
        # and every op in the trace carries that prefix.
        graph=score_call(item=PARENT, trace_root=PARENT, session_id=PARENT, name="score_call"),
        source=calls,
        sink=Outputs(output_path, skip_existing=skip_if_exists, write_errors=True),
        key="name",
        item_input="item",
        concurrency=max_concurrency,
        on_error="record",
        # `[]`, not None: inside an Application a job with no consumers
        # gets operonx's plain LocalConsumer — every transcript, unredacted.
        trace=[tracer] if tracer else [],
        inputs={"trace_root": str(tracer_local_dir), "session_id": uuid.uuid4().hex},
        on_item=on_item if on_item is not None else Progress(calls),
        record_dir=record_dir,
        description="Score a folder of calls; one JSON out per call.",
    )


class Progress:
    """One line per scored call — `[3/90] X.json -> OK (4.2s)`. A call
    skipped because its output exists is counted by `report`, not printed.
    The total is counted when the first call finishes, not at declaration."""

    def __init__(self, calls: Calls):
        self.calls = calls
        self.total: Optional[int] = None
        self.done = 0

    def __call__(self, result: Any) -> None:
        if result.status == "skipped":
            return
        if self.total is None:
            self.total = len(self.calls.paths())
        self.done += 1
        ok = result.status == "ok"
        elapsed = round((result.ms or 0) / 1000, 2)
        print(f"[{self.done}/{self.total}] {result.key}.json -> {'OK' if ok else 'FAIL'} ({elapsed}s)", flush=True)
