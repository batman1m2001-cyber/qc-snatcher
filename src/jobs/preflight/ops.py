"""The ops `preflight` runs. See `graph.py`. Each raises with a message
that names what to fix; an op that raises fails the job, and the ops after
it do not run.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from operonx.core import op

from src.core import config

logger = logging.getLogger(__name__)

#: What each of the four retrieval resources must resolve to. A local
#: backend still answers every query, the pipeline scores every call, and
#: nothing in the output says which backend produced the pool.
_REMOTE_BACKENDS = {"vector_store": "pgvector", "doc_store": "postgres", "embedding": "triton"}

#: Probe timeout. Short on purpose: an endpoint that needs three seconds to
#: accept a socket is worth failing on, and being wrong costs one retry.
_REACH_TIMEOUT = 3.0



def require_remote_retrieval() -> None:
    """Refuse anything but the remote retrieval stack. `models.yaml` names
    the four resources, but a name is a key into `resources.yaml`, and one
    line there can point it anywhere — so the resolved `api_type` is checked."""
    from operonx.core.registry import ResourceHub

    hub = ResourceHub.instance()
    checks = (
        ("vector_store", config.CORPUS_VECTOR_STORE_POS, "retrieval.positives"),
        ("vector_store", config.CORPUS_VECTOR_STORE_CVO, "retrieval.carveouts"),
        ("doc_store", config.CORPUS_DOC_STORE, "retrieval.documents"),
        ("embedding", config.CORPUS_EMBEDDING, "retrieval.embedding"),
    )
    wrong = []
    for kind, name, where in checks:
        try:
            cfg = hub.get_config(f"{kind}:{name}")
        except Exception as e:  # noqa: BLE001 — reported
            wrong.append(f"  {where}={name!r}: cannot resolve {kind}:{name} — {e}")
            continue
        got = getattr(getattr(cfg, "api_type", None), "value", None)
        if got != _REMOTE_BACKENDS[kind]:
            wrong.append(f"  {where}={name!r} is {got!r}, must be {_REMOTE_BACKENDS[kind]!r}")
    if wrong:
        raise RuntimeError(
            "retrieval is not on the remote stack:\n" + "\n".join(wrong)
            + "\n  Fix: point `retrieval.*` in models.yaml at the -pg / -triton resources.")


def resource_keys() -> List[str]:
    """Every resource a scoring run opens a socket to, from `models.yaml`
    (read at call time). A stage switched off (`null`) is not probed."""
    keys = [
        f"vector_store:{config.CORPUS_VECTOR_STORE_POS}",
        f"vector_store:{config.CORPUS_VECTOR_STORE_CVO}",
        f"doc_store:{config.CORPUS_DOC_STORE}",
        f"embedding:{config.CORPUS_EMBEDDING}",
        f"llm:{config.LLM_RESOURCE_KEY}",
        f"llm:{config.DECIDER_LLM_RESOURCE_KEY}",
    ]
    for name in (config.PRIMARY_DECIDER_LLM_RESOURCE_KEY, config.SOFTEN_LLM_RESOURCE_KEY,
                 config.PREFILTER_LLM_RESOURCE_KEY):
        if name.strip():
            keys.append(f"llm:{name.strip()}")
    return sorted(dict.fromkeys(keys))  # several stages on one model probe it once


def require_reachable(skip: bool = False) -> None:
    """Every resource accepts a connection — or raise naming *all* that did
    not. Constructing a client opens no socket, so without this a run off
    the VPN fails one call at a time, each waiting out its own deadline.

    *skip* (`PIPELINE_SKIP_REACHABILITY`) is for a replay or an offline run
    where every network op is stubbed and reaching out would be the bug."""
    if skip:
        logger.warning("PIPELINE_SKIP_REACHABILITY is set — not checking whether any endpoint answers.")
        return
    from operonx.core.registry import ResourceHub

    ResourceHub.instance().require_reachable(*resource_keys(), timeout=_REACH_TIMEOUT)


@op
def show_routing() -> Dict[str, Any]:
    """Print which resource serves each stage, as `models.yaml` routes it —
    the first thing in a pod's log, so a wrong route is read, not guessed."""
    off = "(OFF -- models.yaml says null)"
    print(
        "-" * 78 + "\n"
        f"Stage -> resource  ({config.ROUTING_FILE.name}):\n"
        f"  default: scanner, kid, other cases     ->  {config.LLM_RESOURCE_KEY}\n"
        f"  filter decider: l3, ASR check, halu    ->  {config.DECIDER_LLM_RESOURCE_KEY}\n"
        f"  primary decider: l4 strict re-verify   ->  {config.PRIMARY_DECIDER_LLM_RESOURCE_KEY or off}\n"
        f"  soften: l4 reason rewrite              ->  {config.SOFTEN_LLM_RESOURCE_KEY}\n"
        f"  pre-filter: l1 cheap LLM               ->  {config.PREFILTER_LLM_RESOURCE_KEY or off}\n"
        "\n"
        "Corpus retrieval -> resource:\n"
        f"  vector store (positives)               ->  {config.CORPUS_VECTOR_STORE_POS}\n"
        f"  vector store (carveouts)               ->  {config.CORPUS_VECTOR_STORE_CVO}\n"
        f"  doc store                              ->  {config.CORPUS_DOC_STORE}\n"
        f"  embedding                              ->  {config.CORPUS_EMBEDDING}\n"
        + "-" * 78,
        flush=True,
    )
    return {"routing": config.ROUTING_FILE.name}


@op
def check_backends() -> Dict[str, Any]:
    require_remote_retrieval()
    return {"backends": "ok"}


@op
def check_reachable(skip: bool = False) -> Dict[str, Any]:
    require_reachable(skip)
    return {"reachable": "ok"}
