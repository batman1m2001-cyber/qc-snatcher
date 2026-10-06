"""MLE's command: the `selfcheck` and `main` jobs (steps) `app/main.py` declares.

    python main.py --selfcheck  # the deploy gate, once: preflight ▶ ingest + seed ▶ selfcheck_score
    python main.py              # a pod: preflight ▶ ingest ▶ score ▶ report
    python main.py --ingest     # the same, and ingest may seed a stale corpus store

The same as `operonx-run selfcheck` / `operonx-run main [--set seed=true]`,
through `python`, because the deployment starts it with `sys.executable`
and needs no PATH. The scoring run is configured by the `PIPELINE_*`
variables — input and output folders, concurrency, tracing — which is how
the deployment sets it.

`main`: exit 1 when preflight or ingest fails (the stack is not fit to
score); otherwise 0 — a call that fails still gets its output file,
`{"error": ...}`, and does not fail the batch.

`--selfcheck`: exit 1 when a step fails or the fixture's match rate is
under the threshold. It runs before any pod, so it loads the deployment's
secrets itself (a pod gets them from `sentiment.py`), and uploads the run
record to S3 afterwards, pass or fail.
"""
import importlib
import sys
from pathlib import Path

from operonx.cli.run import main as operonx_run

#: Flags main.py took before it delegated, and the variable that replaced each.
MOVED = {
    "--input-path": "PIPELINE_INPUT_PATH",
    "--output-path": "PIPELINE_OUTPUT_PATH",
    "--files-list": "PIPELINE_FILES_LIST",
    "--files": "PIPELINE_FILES_LIST (a file of paths, one per line)",
    "--skip-if-exists": "PIPELINE_SKIP_IF_EXISTS=true",
    "--tracer-kind": "PIPELINE_TRACER_KIND",
    "--tracer-local-dir": "PIPELINE_TRACER_LOCAL_DIR",
    "--max-concurrency": "PIPELINE_MAX_CONCURRENCY",
}

MANIFEST = Path(__file__).resolve().with_name("operonx.toml")


FLAGS = ("--ingest", "--selfcheck")


def load_deploy_secrets() -> bool:
    """Import the deployment's `settings` — in the image it pulls the
    credentials from Secrets Manager and writes them into `.env`, which
    operonx-run then loads. Off the image there is no `settings`: the env
    file is already in place. True when it was found."""
    try:
        importlib.import_module("settings")
    except ModuleNotFoundError as exc:
        if exc.name != "settings":
            raise  # settings is there but needs something missing: a broken image
        return False
    return True


def selfcheck() -> int:
    load_deploy_secrets()
    status = operonx_run(["-f", str(MANIFEST), "selfcheck"])
    from app.main import RUNS, SETTINGS  # after the secrets: src reads the env file at import
    from src.jobs.selfcheck._gate import upload_record, verdict

    print(verdict(RUNS), flush=True)
    upload_record(SETTINGS.s3_bucket, SETTINGS.s3_prefix, RUNS)
    return status


def main(argv: list) -> int:
    for arg in argv:
        if arg in FLAGS:
            continue
        flag = arg.split("=", 1)[0]
        if flag in MOVED:
            print(f"error: {flag} is gone - set {MOVED[flag]} instead", file=sys.stderr)
        else:
            print(f"error: unknown argument {arg!r} - main.py takes only --ingest or --selfcheck", file=sys.stderr)
        return 2
    if "--selfcheck" in argv:
        if "--ingest" in argv:
            print("error: --selfcheck seeds already - drop --ingest", file=sys.stderr)
            return 2
        return selfcheck()
    seed = ["--set", "seed=true"] if "--ingest" in argv else []
    return operonx_run(["-f", str(MANIFEST), "main", *seed])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
