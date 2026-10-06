"""What `python main.py --selfcheck` does after its steps, pass or fail:
say the verdict, and send the run record to S3 so each deploy keeps its
own evidence."""
from __future__ import annotations

import json
from pathlib import Path


def verdict(record_dir: str = ".runs") -> str:
    """One line from the last `selfcheck` run (a job of steps): the match
    rate against the threshold, or the step that stopped it before scoring."""
    from operonx.app.jobs import last_run

    run = last_run(record_dir, "selfcheck")
    if run is None:
        return "selfcheck FAIL - no run recorded"
    steps = run.meta.get("steps") or []
    score = next((s for s in steps if s["name"] == "selfcheck_score" and s.get("path")), None)
    if score is None:
        stopped = next((s["name"] for s in steps if s["status"] != "ok"), "?")
        return f"selfcheck FAIL - {stopped} failed, nothing scored"
    ev = json.loads((Path(score["path"]) / "run.json").read_text(encoding="utf-8")).get("eval") or {}
    if not ev.get("cases"):
        return f"selfcheck FAIL - selfcheck_score {score['status']}, no case scored"
    word = "PASS" if score["status"] == "ok" else "FAIL"
    return (f"selfcheck {word} - {ev['passed']}/{ev['cases']} match = {ev['pass_rate']:.1%} "
            f"(threshold {ev['threshold']:.0%}, errored {ev['errored']})  {score['path']}")


def upload_record(bucket: str, prefix: str, record_dir: str = ".runs") -> int:
    """The last selfcheck_score run's record — every call's verdict and
    scored row — to `s3://<bucket>/<prefix>/selfcheck/<run id>/`. Only where
    the deployment set both (`S3_BUCKET`, `SENTIMENT_OUTPUT_S3_KEY`); a
    failed upload is printed, never the verdict. Returns files sent."""
    if not bucket or not prefix:
        print("[selfcheck] skip upload: S3_BUCKET or SENTIMENT_OUTPUT_S3_KEY is unset", flush=True)
        return 0
    from operonx.app.jobs import last_run

    run = last_run(record_dir, "selfcheck_score")
    if run is None:
        return 0
    import boto3

    s3, sent = boto3.client("s3"), 0
    for name in ("run.json", "items.jsonl"):
        key = f"{prefix.rstrip('/')}/selfcheck/{run.run_id}/{name}"
        try:
            s3.upload_file(str(run.path / name), bucket, key)
            sent += 1
        except Exception as exc:  # noqa: BLE001 — evidence, not the verdict
            print(f"[selfcheck] upload failed for {key}: {exc}", flush=True)
    return sent
