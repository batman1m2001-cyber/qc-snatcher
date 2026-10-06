"""The op `report` runs. See `graph.py`."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from operonx.app.jobs import last_run
from operonx.core import op

from ..score._calls import Calls

#: The job whose record this reads — `score`, the step before it in `main`.
SCORE_JOB = "score"


def summary(run: Any, total: int, output_path: "str | Path") -> str:
    """The end-of-batch summary: counts from the score run's record, LLM
    usage from the process-wide counter `src.core._bootstrap` keeps (the
    `main` job ran score in this process). *total* is every input file; the
    ones the record never saw had no call_code and were skipped at the source."""
    c = run.counts
    unread = max(0, total - len(run.items))
    lines = [
        "-" * 90,
        "SUMMARY:",
        f"Total Files       : {total}",
        f"Success           : {c.get('ok', 0)}",
        f"Failed            : {c.get('failed', 0) + c.get('timeout', 0)}",
        f"Skipped           : {c.get('skipped', 0) + unread}",
    ]
    try:
        from src.core._bootstrap import USAGE_TOTAL

        in_tok = USAGE_TOTAL["prompt_tokens"]
        cache_r = USAGE_TOTAL["cache_read_tokens"]
        cost = USAGE_TOTAL.get("cost_usd", 0.0)
        ok = c.get("ok", 0)
        lines += [
            f"LLM Calls         : {USAGE_TOTAL['calls']:,}",
            f"LLM Tokens in/out : {in_tok:,} / {USAGE_TOTAL['completion_tokens']:,}",
            f"Cache read/write  : {cache_r:,} / {USAGE_TOTAL['cache_creation_tokens']:,}"
            f"  (hit={(cache_r / in_tok * 100) if in_tok else 0.0:.1f}%)",
            f"Total Cost        : ${cost:.4f}  (avg ${cost / ok if ok else 0.0:.5f}/file)",
        ]
    except (ImportError, KeyError):
        pass
    lines += [f"Output Directory  : {output_path}", f"Run record        : {run.path}", "=" * 90]
    return "\n".join(lines)


@op
def summarize(
    input_path: str = "",
    files_list: str = "",
    output_path: str = "",
    record_dir: str = ".runs",
) -> Dict[str, Any]:
    """Print the summary. Never raises: the batch is scored by now, and a
    summary that failed must not turn it into a failed run."""
    try:
        run = last_run(record_dir, SCORE_JOB)
        if run is None:
            text = f"no {SCORE_JOB} run under {record_dir} — nothing to report"
        else:
            total = len(Calls(input_path, files_list=files_list or None).paths())
            text = summary(run, total, output_path)
    except Exception as exc:  # noqa: BLE001 — reported, never raised
        text = f"no summary: {type(exc).__name__}: {exc}"
    print(text, flush=True)
    return {"summary": text}
