"""The refactor gate: the score job over the 90 fixture calls, offline.

Every model call is replayed from the recorded baseline (`tests/_replay`),
so nothing touches the network. Each call's output file is hashed, and one
call is re-run with the local tracer on to record where its trace lands.

    uv run python -m tests._snapshot                 # compare with tests/sample/snapshot.json
    uv run python -m tests._snapshot --write         # record it (only when a change is intended)

`tests/graphs/test_snapshot.py` runs the same comparison inside `pytest`.

Exit 1 on any difference. 12 of the 90 calls do not reproduce the recorded
verdict (the primary decider's pool is not in the recording — the same 12
`test_replay_equivalence` xfails); the snapshot pins what they do produce.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from tests._env import pin

pin()  # before anything imports `src`: the same environment as the test suite

BASELINE = Path(__file__).parent / "sample" / "snapshot.json"
_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d{8}T\d{6}-\d+"
                 r"|(?<=_)[0-9a-f]{8}(?=\.json$)")


def _run(name: str, row: dict, out: Path, tracer_kind: str = "none") -> bytes:
    from app._score import build_job
    from tests._replay import build_stubs, install_stubs
    from tests._recorded import INPUTS

    job = build_job(files=[str(INPUTS / name)], output_path=out / "calls", tracer_kind=tracer_kind,
                    tracer_local_dir=str(out / "traces"), record_dir=out / "runs", on_item=lambda r: None)
    install_stubs(job.engine().graph, build_stubs(row["traces"]))
    job.run_sync()
    return (out / "calls" / name).read_bytes()


def take(out: Path) -> dict:
    from tests._recorded import RECORDED_ALL

    calls, t0 = {}, time.perf_counter()
    for p in RECORDED_ALL:
        name, row = p.values
        calls[name] = hashlib.sha256(_run(name, row, out)).hexdigest()
    seconds = round(time.perf_counter() - t0, 1)

    name, row = RECORDED_ALL[0].values
    _run(name, row, out / "traced", tracer_kind="local")
    root = out / "traced" / "traces"
    trace_files = sorted({_ID.sub("<id>", p.relative_to(root).as_posix())
                          for p in root.rglob("*") if p.is_file()})
    return {"calls": calls, "trace_files": trace_files, "seconds": seconds}


def compare(got: dict, want: dict) -> tuple[list, bool]:
    """(calls whose output changed, whether the trace layout is the same)."""
    differ = sorted(k for k in want["calls"] if want["calls"][k] != got["calls"].get(k))
    return differ, want["trace_files"] == got["trace_files"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="record the snapshot instead of comparing")
    args = ap.parse_args()
    out = Path(tempfile.mkdtemp(prefix="snapshot_"))
    try:
        got = take(out)
    finally:
        shutil.rmtree(out, ignore_errors=True)
    if args.write:
        BASELINE.write_text(json.dumps(got, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {BASELINE}: {len(got['calls'])} calls, {got['seconds']}s")
        return 0
    want = json.loads(BASELINE.read_text(encoding="utf-8"))
    differ, trace_ok = compare(got, want)
    same = len(want["calls"]) - len(differ)
    print(f"outputs : {same}/{len(want['calls'])} byte-identical" + (f"; differ: {differ[:5]}" if differ else ""))
    print(f"traces  : {'same layout' if trace_ok else 'DIFFERENT layout'}")
    if not trace_ok:
        print("  was:", want["trace_files"], "\n  now:", got["trace_files"])
    print(f"time    : {got['seconds']}s (baseline {want['seconds']}s)")
    return 0 if not differ and trace_ok else 1


if __name__ == "__main__":
    sys.exit(main())
