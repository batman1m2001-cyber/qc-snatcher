"""The application declares seven jobs, each is documented, and the product
never depends on the tooling.

| rule | why |
|---|---|
| `APP` lists exactly the seven | `operonx-run --list` is how anyone finds them; a rough tool is a script in `tools/` |
| every job's graph inputs are named in its `inputs` | `--set key=value` can only reach an input the job declares |
| every job is documented in its feature's README | `operonx-run <name> --help` prints flags, not what the job does |
| nothing outside `src/jobs/` imports it | the scoring product must not depend on the jobs that operate on it |
| `src/` never imports `app/` | imports go one way: app → graph → ops → helpers |
| nothing in `src/` or `app/` imports `tools/` | the rough tools are an archive, not a dependency |
"""
import ast
import inspect

import pytest

from app.main import APP

from tests._paths import ROOT
JOBS = ROOT / "src" / "jobs"
FEATURES = sorted(p for p in JOBS.iterdir() if p.is_dir() and not p.name.startswith("_") and (p / "__init__.py").exists())
ALL = {j.name: j for j in APP.jobs}
PLAIN = [j for j in APP.jobs if j.steps is None]


def test_the_application_declares_every_job():
    assert list(ALL) == ["main", "selfcheck", "selfcheck_build", "ingest", "create_schema", "qc_eval", "qc_eval_report"]


def test_the_steps_jobs_run_their_jobs_in_order():
    assert [j.name for j in ALL["main"].steps] == ["preflight", "ingest", "score", "report"]
    assert [j.name for j in ALL["selfcheck"].steps] == ["preflight", "ingest", "selfcheck_score"]


def test_main_scores_the_env_and_the_deploy_gate_seeds():
    main_ingest = ALL["main"].steps[1]
    deploy_ingest = ALL["selfcheck"].steps[1]
    assert main_ingest is ALL["ingest"] and main_ingest.inputs["seed"] is False
    assert deploy_ingest.inputs["seed"] is True
    assert ALL["main"].steps[2].items_fail_run is False  # a failed call must not stop the steps


@pytest.mark.parametrize("job", PLAIN, ids=lambda j: j.name)
def test_every_graph_input_is_declared(job):
    from operonx.core.ops.graph import GraphOp

    if isinstance(job.graph, GraphOp):
        return  # built already (score, selfcheck): it binds its own inputs
    params = set(inspect.signature(job.graph).parameters)  # what Job itself reads
    assert params <= set(job.inputs), f"{job.name}: {params - set(job.inputs)} cannot be --set"


@pytest.mark.parametrize("job", PLAIN, ids=lambda j: j.name)
def test_every_job_is_documented(job):
    readmes = "\n".join(p.read_text(encoding="utf-8") for p in JOBS.glob("*/README.md"))
    assert f"operonx-run {job.name}" in readmes, f"no README says how to run {job.name}"


@pytest.mark.parametrize("feature", FEATURES, ids=lambda p: p.name)
def test_a_feature_folder_has_its_parts(feature):
    for f in ("__init__.py", "graph.py", "ops.py", "README.md"):
        assert (feature / f).is_file(), f"src/jobs/{feature.name}/{f} is missing"


def _imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield node.lineno, [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, [node.module]


def test_the_product_never_imports_the_tooling():
    hits = [f"{p.relative_to(ROOT)}:{line}"
            for p in (ROOT / "src").rglob("*.py") if JOBS not in p.parents
            for line, names in _imports(p) if any(n.startswith("src.jobs") for n in names)]
    assert hits == [], f"the product imports src/jobs: {hits}"


def test_nothing_imports_the_tools():
    hits = [f"{p.relative_to(ROOT)}:{line}"
            for d in ("src", "app") for p in (ROOT / d).rglob("*.py")
            for line, names in _imports(p) if any(n == "tools" or n.startswith("tools.") for n in names)]
    assert hits == [], f"imports tools/: {hits}"


def test_src_never_imports_app():
    hits = [f"{p.relative_to(ROOT)}:{line}"
            for p in (ROOT / "src").rglob("*.py")
            for line, names in _imports(p) if any(n == "app" or n.startswith("app.") for n in names)]
    assert hits == [], f"src imports app: {hits}"
