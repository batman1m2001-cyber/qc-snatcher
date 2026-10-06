"""The sentiment application: seven jobs, and the graph each runs.

    operonx-run --list                         # all seven
    operonx-run <name> [--set k=v] [--show]    # run one; --resume continues it
    python main.py [--ingest]                  # `main`, as the pods run it
    python main.py --selfcheck                 # `selfcheck`, the deploy gate, with MLE's secrets

| name | kind | runs | graph in |
|---|---|---|---|
| `main` | steps | preflight ▶ ingest ▶ score ▶ report | `src/jobs/{preflight,ingest,score,report}` |
| `selfcheck` | steps | preflight ▶ ingest (seed) ▶ selfcheck_score: the 90 fixture calls through the scoring graph, each against its baseline — the deploy gate | `src/jobs/selfcheck` |
| `selfcheck_build` | job | promote the last selfcheck_score run to be the baseline | `src/jobs/selfcheck` |
| `ingest` | job | the corpus store holds corpus.yaml; `seed=true` seeds it | `src/jobs/ingest` |
| `create_schema` | job | create the corpus tables when they are absent — once, by hand | `src/jobs/ingest` |
| `qc_eval` | steps | preflight ▶ qc_eval_score ▶ qc_eval_report: a QC batch (`QC_BATCH`) against QC's labels — F1, and the stage behind each error | `src/jobs/qc_eval` |
| `qc_eval_report` | job | the report again, from the last qc_eval_score run | `src/jobs/qc_eval` |

A run is configured by environment variables, read once into `SETTINGS`
(`app/settings.py` lists them all, with defaults) — the way MLE's pods
configure it; `--set` reaches a graph input. Rough tools —
QC batches, the corpus workbook, the scan report — are plain scripts in
`tools/`, not jobs.

Nothing is served: there is no Service, and `operonx-serve --list` is empty.
Each job traces nothing unless it says so (`trace=[]` below): an
application otherwise gives a job operonx's plain local consumer, which
would write whole transcripts to disk.
"""
from operonx.app import Application, Eval
from operonx.app.jobs import Job
from operonx.core import PARENT

from app._score import build_job
from app.settings import Settings
from src.jobs.ingest import graph as ingest_graphs
from src.jobs.preflight import graph as preflight_graphs
from src.jobs.qc_eval import graph as qc_graphs
from src.jobs.qc_eval.ops import QCBatch, agrees_with_qc
from src.jobs.qc_eval.ops import Show as QCShow
from src.jobs.report import graph as report_graphs
from src.jobs.selfcheck import graph as selfcheck_graphs
from src.jobs.selfcheck.ops import Fixtures, Show, matches_baseline

#: Where every run is recorded: `.runs/<job>/<run>/`.
RUNS = ".runs"

#: The environment, read once — every knob a job below takes comes from here.
SETTINGS = Settings.from_env()


# ── the corpus store ──────────────────────────────────────────────────────

ingest = Job(
    "ingest",
    graph=ingest_graphs.ingest,
    inputs={"seed": False, "reseed": False, "prune": True, "force_prune": False, "dry_run": False,
            "seed_wait_s": SETTINGS.seed_wait_s},
    record_dir=RUNS,
    description="The corpus store holds corpus.yaml — or fail naming the fix; seed=true seeds it under the lock.",
)

create_schema = Job(
    "create_schema",
    graph=ingest_graphs.create_schema,
    inputs={"dsn": "", "dry_run": False},
    record_dir=RUNS,
    description="Create the corpus tables when they are absent.",
)


# ── the main flow ─────────────────────────────────────────────────────────

preflight = Job(
    "preflight",
    graph=preflight_graphs.preflight,
    inputs={"skip_reachability": SETTINGS.skip_reachability},
    record_dir=RUNS,
    description="Print the routing; the backends are remote and reachable.",
)

score = build_job(
    SETTINGS.input_path,
    SETTINGS.output_path,
    files_list=SETTINGS.files_list,
    skip_if_exists=SETTINGS.skip_if_exists,
    tracer_kind=SETTINGS.tracer_kind,
    tracer_local_dir=SETTINGS.tracer_local_dir,
    max_concurrency=SETTINGS.max_concurrency,
    record_dir=RUNS,
)

report = Job(
    "report",
    graph=report_graphs.report,
    inputs={
        "input_path": SETTINGS.input_path,
        "files_list": SETTINGS.files_list,
        "output_path": SETTINGS.output_path,
        "record_dir": RUNS,
    },
    record_dir=RUNS,
    description="The end-of-batch summary, read from the score run's record.",
)

main = Job("main", steps=[preflight, ingest, score, report], record_dir=RUNS,
           description="The main flow: preflight, ingest, score, report (PIPELINE_* configure it).")


# ── selfcheck ─────────────────────────────────────────────────────────────

selfcheck_score = Eval(
    "selfcheck_score",
    # Built here so its name is pinned; from a bare factory the root is `params`.
    graph=selfcheck_graphs.score_fixture(item=PARENT, name="score_fixture"),
    dataset=Fixtures(),
    evaluators=[matches_baseline],
    threshold=SETTINGS.selfcheck_threshold,
    input="item",
    concurrency=SETTINGS.selfcheck_concurrency,
    on_item=Show(),
    record_dir=RUNS,
    description="The 90 fixture calls through the scoring graph, each against its baseline row; "
                "fails under PIPELINE_SELFCHECK_MATCH_THRESHOLD (0.85).",
)

selfcheck_build = Job(
    "selfcheck_build",
    graph=selfcheck_graphs.selfcheck_build,
    inputs={"dry_run": False, "record_dir": RUNS},
    record_dir=RUNS,
    description="Promote the last selfcheck_score run to be the baseline (commit tests/sample/fixtures/ after).",
)

# Its own ingest: the same graph `main` runs, but seeding a stale store —
# the gate runs once per deploy, before any pod, and must not judge a
# corpus.yaml the store does not hold yet.
ingest_and_seed = Job(
    "ingest",
    graph=ingest_graphs.ingest,
    inputs={**ingest.inputs, "seed": True},
    record_dir=RUNS,
    description="The corpus store holds corpus.yaml; seed it under the lock when stale.",
)

selfcheck = Job("selfcheck", steps=[preflight, ingest_and_seed, selfcheck_score], record_dir=RUNS,
                description="The deploy gate: preflight, ingest + seed, selfcheck_score (python main.py --selfcheck).")


# ── against QC's labels ───────────────────────────────────────────────────

QC_BATCH = QCBatch()

qc_eval_score = Eval(
    "qc_eval_score",
    graph=qc_graphs.score_agent(item=PARENT, name="score_agent"),
    dataset=QC_BATCH,
    evaluators=[agrees_with_qc],
    threshold=0.0,  # a report, not a gate: disagreeing with QC is what it measures
    inputs={"batch": SETTINGS.qc_batch},
    input="item",
    concurrency=SETTINGS.qc_concurrency,
    on_item=QCShow(QC_BATCH),
    record_dir=RUNS,
    description="Each call QC labelled through sentiment_agent, against QC's verdict (--set batch=<folder>).",
)
QC_BATCH.inputs = qc_eval_score.inputs  # `--set batch=` lands in this dict before the run reads the batch

qc_eval_report = Job(
    "qc_eval_report",
    graph=qc_graphs.qc_eval_report,
    inputs={"batch": SETTINGS.qc_batch, "record_dir": RUNS},
    record_dir=RUNS,
    description="F1, the stage funnel and the diff against the batch's previous run, into <batch>/runs/<run id>/.",
)

qc_eval = Job("qc_eval", steps=[preflight, qc_eval_score, qc_eval_report], record_dir=RUNS,
              description="A QC batch against QC's labels: preflight, qc_eval_score, qc_eval_report (--set batch=<folder>).")


APP = Application(
    "sentiment",
    jobs=[main, selfcheck, selfcheck_build, ingest, create_schema, qc_eval, qc_eval_report],
    # `src.core._bootstrap` installs the hub (env file choice, models.yaml
    # routing, the LLM timeout patch); a second bootstrap would replace it.
    resources=None,
    # Import roots: the repo root only, so `src.core.config` is one module
    # and never also `core.config`.
    src=["."],
    trace=[],
    description="Vietnamese call-centre QC scoring — seven cases per call.",
)
