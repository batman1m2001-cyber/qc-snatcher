"""Every resource the graph names must exist in `resources.yaml`.

operonx resolves provider ops **eagerly**: `Operon.__init__` calls
`_warmup_ops()`, which asks the hub for every op's resource before the
first call is scored. hush was lazy — an op resolved only when it ran.

That is the safer order, and it moves a failure. Under hush a typo in a
resource key surfaced the first time that op executed; for a branch that
production never takes, it never surfaced at all. Now it stops the pod at
startup.

Which creates one specific hazard worth a test rather than a comment: a
resource can be **named by the graph and never executed**. The filter's
scan is exactly that — `SENTIMENT_FILTER_LLM_RESOURCE_KEY` is unset in
deployment, so the branch is dead, but the op is still built and
`llm:e4b-local` must still resolve. Someone tidying `resources.yaml` and
removing "the unused local filter model" would take the whole pipeline
down on next deploy, with nothing in this repo having changed.

So the check runs here, where it costs a second, instead of there.

No LLM, no network: `has()` reads config, it does not construct a client.
"""

import os

import pytest
from operonx.core.ops import GraphOp
from operonx.core.registry import ResourceHub

import src.core._bootstrap  # noqa: F401 — loads the env file + installs the hub
from tests._engine import children


def _iter_ops(graph):
    """Every op in the graph, recursively."""
    for op in children(graph).values():
        yield op
        if isinstance(op, GraphOp):
            yield from _iter_ops(op)


def _named_resources(graph):
    """`{(op_name, category, key)}` for every op that names a resource.

    Each provider op prepends its own category when it asks the hub
    (`LLMOp` -> `llm:`, `EmbeddingOp` -> `embedding:`, ...), so the
    category is derived from the op type rather than read off the op.
    """
    categories = {
        "LLMOp": "llm",
        "EmbeddingOp": "embedding",
        "VectorSearchOp": "vector_store",
        "DocFetchOp": "doc_store",
        "RerankOp": "reranking",
    }
    found = set()
    for op in _iter_ops(graph):
        category = categories.get(type(op).__name__)
        if category is None:
            continue
        resource = getattr(op, "resource", None)
        if not resource:
            continue
        # `resource=` may be a list for load-balanced ops.
        for key in (resource if isinstance(resource, list) else [resource]):
            if isinstance(key, str) and key:
                found.add((op.name, category, key))
    return found


@pytest.fixture(scope="module")
def graph():
    from operonx.core import PARENT

    from src.qc.graph import score_cases

    return score_cases(
        conversation=PARENT, call_code=PARENT, closed_by=PARENT,
        is_chinh_chu=PARENT, queue_id=PARENT,
    )


def test_the_graph_names_some_resources(graph):
    """Guards the guard: a walk that silently found nothing would make
    every assertion below vacuous."""
    found = _named_resources(graph)
    assert len(found) >= 5, f"expected several provider ops, found {found}"


def test_every_named_resource_resolves(graph):
    hub = ResourceHub.instance()
    missing = [
        f"{op_name}: {category}:{key}"
        for op_name, category, key in sorted(_named_resources(graph))
        if not hub.has(f"{category}:{key}")
    ]
    assert not missing, (
        "resources.yaml is missing keys the graph names. operonx resolves "
        "these at engine construction, so this would stop the pod at "
        "startup:\n  " + "\n  ".join(missing)
    )


def test_prefilter_off_binds_the_default_model():
    """With `llm.prefilter: null` the pre-filter's op binds the default model.

    It used to bind `e4b-local`, and operonx resolves every op's resource at
    engine start whether or not it can fire — so every pod needed
    `E4B_LOCAL_BASE_URL` for a model it never called.
    """
    from src.core import config

    if config.PREFILTER_LLM_RESOURCE_KEY:
        pytest.skip("pre-filter is routed in models.yaml")
    assert config.SENTIMENT_FILTER_LLM_RESOURCE_KEY == config.LLM_RESOURCE_KEY


def test_engine_starts_without_the_e4b_env_var():
    """Build the real engine in a fresh process with `E4B_LOCAL_BASE_URL`
    removed. Offline: the probe pins the test environment first, so token
    providers hand out a fixed token instead of fetching one."""
    import subprocess
    import sys

    from tests._paths import ROOT as root
    probe = (
        "import os, sys; sys.path.insert(0, os.getcwd());"
        "from tests._env import pin; pin();"
        "import src.core._bootstrap;"
        "os.environ.pop('E4B_LOCAL_BASE_URL', None);"
        "from app._score import build_job; build_job().engine()"
    )
    env = {k: v for k, v in os.environ.items() if k != "E4B_LOCAL_BASE_URL"}
    r = subprocess.run([sys.executable, "-c", probe], cwd=root, env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    assert r.returncode == 0, r.stderr[-1500:]
