"""Make the real `score_cases` graph run with no network.

Two substitutions, both on a *built* graph — no production module is
patched or edited:

* every LLMOp gets a scripted model in place of its Databricks client. The
  op itself is untouched: prompt rendering, the XML/JSON parser, the
  `error` field and the `parsed` guard behind it all run for real. Only the
  text that would have come back over HTTP is canned (`demo/calls.py`).
* inside the two `retrieval` subgraphs, the Triton embedder, the pgvector
  searches and the Postgres fetch answer from memory with three real corpus
  entries; the fan-in, ranking and merge between them run for real.

No client for Databricks, Triton or Postgres is ever built, so the demo
cannot dial out.
"""
from __future__ import annotations

import contextvars
import os
import time
from typing import Any, Iterator

#: Which call is being scored — the scripted model reads it to pick a reply.
CURRENT_CALL: contextvars.ContextVar[str] = contextvars.ContextVar("demo_call", default="")


def pin_environment() -> None:
    """Placeholders for what `resources.yaml` interpolates, all cases on.

    Must run before `src` is imported (its bootstrap reads the environment).
    Values already set by the shell win, except the endpoints: the demo
    never points at a real one.
    """
    for case in ("hangup", "raba", "disclosure", "card_number", "phone_source",
                 "sentiment_agent", "sentiment_customer"):
        os.environ.setdefault(f"QC_ENABLE_{case.upper()}", "true")
    os.environ.setdefault("INCLUDE_TRACES", "off")
    os.environ.update({
        "DATABRICKS_HOST": "https://databricks.offline.invalid",
        "DATABRICKS_CLIENT_ID": "offline",
        "DATABRICKS_CLIENT_SECRET": "offline",
        "E4B_LOCAL_BASE_URL": "http://e4b.offline.invalid/v1",
        "PG_DSN": "postgresql://offline.invalid/none",
        "TRITON_EMBEDDING_URL": "triton.offline.invalid:443",
    })


def walk(graph: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """`(full_name, op)` for every op, into subgraphs."""
    for name, op in (getattr(graph, "_ops", None) or {}).items():
        full = f"{prefix}{name}"
        yield full, op
        if getattr(op, "_ops", None):
            yield from walk(op, full + ".")


class ScriptedLLM:
    """Stands in for one LLMOp's model; answers from `demo/calls.py`."""

    config = None  # LLMOp falls back to its defaults for retry knobs

    def __init__(self, op_name: str, script: dict, default: dict):
        self.op_name, self.script, self.default = op_name, script, default

    def _reply(self) -> str:
        per_call = self.script.get(CURRENT_CALL.get(), {})
        for table in (per_call, self.default):
            for key, text in table.items():
                if self.op_name == key or self.op_name.endswith("." + key):
                    return text
        raise LookupError(f"demo has no scripted reply for `{self.op_name}` on {CURRENT_CALL.get()}")

    async def generate(self, *args, **kwargs):
        from openai.types.chat import ChatCompletion

        return ChatCompletion.model_validate({
            "id": "demo", "object": "chat.completion", "created": int(time.time()),
            "model": "offline-script",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": self._reply()}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })


def _corpus_ops(pool: dict) -> dict:
    """Cores for the three backends inside `retrieve_corpus`: the embedder,
    the vector search (one per side) and the document fetch. Everything
    between them — fan-in, hydrate, rank, merge — is the real code."""
    by_id = {e["id"]: e for side in ("positives", "carveouts") for e in pool[side]}

    async def embed(texts=None, **_):
        return {"embeddings": [[0.0] * 8 for _ in (texts or [""])]}

    def search(side):
        async def core(**_):
            entries = pool[side]
            return {"ids": [e["id"] for e in entries],
                    "scores": [0.9 - 0.1 * i for i in range(len(entries))],
                    "metadata": [{"policy_id": e["id"], "knowledge_id": "demo", "severity": e["severity"]}
                                 for e in entries]}
        return core

    async def fetch(ids=None, **_):
        rows = [{"id": i, "content": by_id[i]["content"], "description": by_id[i]["description"],
                 "group_id": "demo", "group_name": "demo", "severity": by_id[i]["severity"]}
                for i in (ids or []) if i in by_id]
        return {"rows": rows, "missing": [i for i in (ids or []) if i not in by_id]}

    return {"embedding": lambda name: embed,
            "vector-search": lambda name: search("carveouts" if ".carveouts." in name else "positives"),
            "doc-fetch": lambda name: fetch}


def go_offline(graph: Any, script: dict, default: dict, pool: dict) -> dict:
    """Swap models and retrieval backends on *graph* in place. Returns counts."""
    counts = {"llm": 0, "retrieval": 0}
    corpus = _corpus_ops(pool)
    for name, op in walk(graph):
        kind = str(getattr(op, "type", ""))
        if kind == "llm":
            op._llms, op._fallback_llms, op._initialized = [ScriptedLLM(name, script, default)], [], True
            counts["llm"] += 1
        elif kind in corpus:
            op._set_core(corpus[kind](name))
            op._initialized = True  # never build the Triton / Postgres client
            counts["retrieval"] += 1
        elif kind == "reranking":
            raise RuntimeError(f"demo: `{name}` would call a live endpoint")
    return counts
