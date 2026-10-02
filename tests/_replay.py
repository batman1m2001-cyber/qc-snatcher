"""Replay a recorded call through the real graph with no network.

Step 0a, T4 of `docs/archive/PLAN_sentiment_agent_layers.md`. The layer refactor's
claim is that it changes no verdict, and selfcheck cannot check that: on a
~27% Result-flip floor it can say *close enough*, never *identical*.

So instead of calling the models again, replay what they said last time.
`tests/sample/fixtures/outputs/` carries, for all 90 calls, a block that
records every decision the pipeline made — and the recording is complete
enough to drive the graph, which is not obvious and was checked field by
field:

| op | reads | recorded as |
|---|---|---|
| `filter` | `should_scan` `reason` `kw_hit` `llm_verdict` | the same four |
| `scanner` | `violation` `category` `reason` `evidence` `evidence_idxs` | `scanner.*`, `category_raw`, `evidence_idxs_raw` |
| `retrieval` | `positives` `carveouts` | in full — id, content, severity |
| `decider` | `violation` `reason` `cited_positives` `cited_carveouts` | `decider.*`, `violation` as `verdict` |
| `asr_check` | `keep` `reason` | `asr_check.verdict`, `.reason` |
| primary | `violation` `reason` `cited_*` | `primary_decider.*` |
| soften | `reason` | `soften.after` |

Two are *not* recorded — `kid_check` and `halu_check` on the paths where
they ran and cleared. They are derived instead, and derivable because the
gates in front of them are pure Python: `attr_check_fn` recomputes from
the scanner block, and `short_gate` is a comparison on `n_turns`. Where a
call's recorded block shows it reached a later stage, the earlier gate
must have cleared it.
"""
from __future__ import annotations

from typing import Any, Dict

#: Suffixes of ops replaced during replay, longest first so
#: `primary_sa.retrieval` is matched before a bare `retrieval`.
_STUBBED = (
    "filter",
    "kid_check",
    "scanner",
    "halu_check",
    "asr_check",
    "retrieval",
    "decider",
    "primary_llm",
    "soften_llm",
)


def _pool_from_map(pool_map: Dict[str, Any], recorded: Dict[str, Any]):
    """Rebuild a stage's pools in its own slot order, or None if we cannot.

    `pool_map` is `{"P1": <id>, "C1": <id>, ...}` for the stage that owns
    it. The entries are looked up in another stage's recorded pools, which
    works because both retrieve from one corpus. An id that appears in no
    recorded pool means the entry cannot be rebuilt — better to say so by
    returning None than to hand back a pool with a hole where a severity
    should be.
    """
    if not pool_map:
        return None
    by_id = {
        entry.get("id"): entry
        for side in ("positives", "carveouts")
        for entry in (recorded.get(side) or [])
        if isinstance(entry, dict) and entry.get("id")
    }

    def _side(prefix: str) -> list:
        slots = sorted(
            (k for k in pool_map if isinstance(k, str) and k.startswith(prefix)),
            key=lambda k: int(k[len(prefix):] or 0),
        )
        return [by_id[pool_map[k]] for k in slots if pool_map.get(k) in by_id]

    positives, carveouts = _side("P"), _side("C")
    wanted = sum(1 for k in pool_map if isinstance(k, str) and k[:1] in ("P", "C"))
    if len(positives) + len(carveouts) < wanted:
        return None
    return {"positives": positives, "carveouts": carveouts}


def _unremap(cited, pool_map, prefix: str) -> list:
    """Recorded ids back to the slot labels the pipeline parses.

    A trace records `cited_positives` *after* `remap_cited` has turned the
    model's `P1` / `P2` into corpus uuids — that is the useful form for a
    reviewer. Replaying those uuids straight back in feeds
    `_parse_cited(..., "P")` something it cannot read, so nothing resolves,
    the cited severity is lost, and a `Thái độ warning` call silently
    replays as `Tích cực`.

    `pool_map` is the slot to id mapping that was applied, so inverting it
    restores what the model actually said. An id with no slot is passed
    through rather than dropped — losing a citation would be the same
    failure in a quieter form.
    """
    if not cited:
        return []
    by_id = {v: k for k, v in (pool_map or {}).items() if isinstance(k, str)}
    return [by_id.get(c, c) for c in cited]


def _wrap(result: Dict[str, Any]) -> Dict[str, Any]:
    """An LLMOp's output shape: the parsed `result` plus a clean `error`.

    `error` matters. `LLMOp` sets it on a parse failure and leaves `result`
    None, and several ops check it — a stub that omits it would replay a
    call as though the parser had never been consulted.
    """
    return {"result": result, "error": None}


def build_stubs(block: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Map op-name suffix → the dict that op's core should return.

    `block` is one call's recorded `traces`. Absent stages are absent from
    the map, and `install_stubs` leaves those ops alone — which is correct:
    a stage with no record is a stage the call never reached.
    """
    out: Dict[str, Dict[str, Any]] = {}

    flt = block.get("filter")
    if isinstance(flt, dict):
        out["prefilter"] = {
            "should_scan": flt.get("should_scan"),
            "reason": flt.get("reason") or "",
            "kw_hit": flt.get("kw_hit"),
            "llm_verdict": flt.get("llm_verdict"),
        }

    scan = block.get("scanner")
    if isinstance(scan, dict):
        out["scanner"] = _wrap({
            "violation": scan.get("violation"),
            "category": scan.get("category_raw") or "",
            "reason": scan.get("reason") or "",
            "evidence": scan.get("evidence") or "",
            "evidence_idxs": list(scan.get("evidence_idxs_raw") or []),
        })

    retr = block.get("retrieval")
    if isinstance(retr, dict):
        pools = {
            "positives": list(retr.get("positives") or []),
            "carveouts": list(retr.get("carveouts") or []),
        }
        out["retrieval"] = pools

    dec = block.get("decider")
    if isinstance(dec, dict):
        pm = dec.get("pool_map") or {}
        out["decider"] = _wrap({
            "violation": dec.get("verdict"),
            "reason": dec.get("reason") or "",
            "cited_positives": _unremap(dec.get("cited_positives"), pm, "P"),
            "cited_carveouts": _unremap(dec.get("cited_carveouts"), pm, "C"),
        })

    asr = block.get("asr_check")
    if isinstance(asr, dict):
        out["asr_check"] = _wrap({
            "keep": asr.get("verdict"),
            "reason": asr.get("reason") or "",
        })

    sec = block.get("primary_decider")
    if isinstance(sec, dict) and sec.get("enabled"):
        pm = sec.get("pool_map") or {}
        # The primary retrieves for itself, with a different query, so its
        # pool is not the filter decider's — `P1` means a different entry in each.
        # Feeding it the filter decider's pool aligns the slots wrongly, the cited
        # entry resolves to the wrong severity, and a `Thái độ warning` call
        # replays as `Tích cực`.
        #
        # Its own pool is not recorded, but `pool_map` gives the slot order
        # and the entries themselves appear in the filter decider's recording, so
        # the pool can be rebuilt in the right order.
        rebuilt = _pool_from_map(pm, retr if isinstance(retr, dict) else {})
        if rebuilt is not None:
            out["primary_sa.retrieval"] = rebuilt
        out["primary_llm"] = _wrap({
            "violation": sec.get("verdict"),
            "reason": sec.get("reason") or "",
            "cited_positives": _unremap(sec.get("cited_positives"), pm, "P"),
            "cited_carveouts": _unremap(sec.get("cited_carveouts"), pm, "C"),
        })

    sof = block.get("soften")
    if isinstance(sof, dict) and sof.get("enabled"):
        out["soften_llm"] = _wrap({"reason": sof.get("after") or ""})

    # ── derived, because the recording does not carry them ──────────────
    # A call whose block shows a scanner verdict got past the kid gate, and
    # one that shows a decider verdict got past halu. Both gates are the
    # "cleared" side, which is the side that writes nothing.
    if "scanner" in out:
        out["kid_check"] = _wrap({"is_kid": False})
    halu = block.get("halu_check")
    if isinstance(halu, dict):
        out["halu_check"] = _wrap({
            "hallucinated": halu.get("verdict"),
            "reason": halu.get("reason") or "",
        })
    elif "decider" in out or "asr_check" in out:
        out["halu_check"] = _wrap({"hallucinated": False, "reason": ""})

    return out


def _match(full_name: str, stubs: Dict[str, Dict[str, Any]]) -> "str | None":
    """Longest suffix of *full_name* present in *stubs*."""
    parts = full_name.split(".")
    for i in range(len(parts)):
        candidate = ".".join(parts[i:])
        if candidate in stubs:
            return candidate
    return None


class WouldHaveCalledOut(RuntimeError):
    """A replayed run reached an op the recording does not cover."""


def install_stubs(graph: Any, stubs: Dict[str, Dict[str, Any]]) -> int:
    """Poison every network op, then overwrite the ones we can replay.

    **Poison first.** Stubs are built from a recording, so an op the
    recording does not cover would otherwise be left live — and a replay
    harness whose whole purpose is "no network" would quietly call a model.
    That nearly happened: a first version stubbed only what the block
    carried, leaving `asr_check` and `soften_llm` live on any call that
    routed through them.

    So every LLM op and every retrieval subgraph gets a core that raises,
    and the recorded ones are then replaced. A path the recording cannot
    drive fails the test loudly instead of dialling out. Same shape as the
    empty-pool guard: absent must not quietly become a value — here, a
    live call.

    Returns the number of ops replayed from the recording.
    """
    _poison_network_ops(graph)

    installed = 0
    for name, op in _walk(graph):
        base = str(name).rsplit(".", 1)[-1]
        if base not in _STUBBED:
            continue
        key = _match(str(name), stubs) or (base if base in stubs else None)
        if key is not None:
            op._set_core(_make_core(stubs[key]))
            installed += 1
    return installed


def answer_ops(graph: Any, answers: Dict[str, Dict[str, Any]]) -> Dict[str, dict]:
    """Poison every network op, then answer each op named in *answers* (by the
    last segment of its name) with that canned output. Returns the inputs
    each answered op was called with, filled in as the graph runs."""
    _poison_network_ops(graph)
    seen: Dict[str, dict] = {}
    for full, op in _walk(graph):
        base = str(full).rsplit(".", 1)[-1]
        if base in answers:
            async def core(_base=base, **kw):  # async: see `_make_core`
                seen[_base] = kw
                return dict(answers[_base])

            op._set_core(core)
    return seen


def fail_model(graph: Any, op_name: str, exc: Exception) -> Dict[str, int]:
    """Give the LLMOp named *op_name* a model that raises *exc* — its real
    core stays, so what the op does with a hard failure (`on_failure`) is
    what runs. Returns a counter of the calls the model received."""
    calls = {"n": 0}

    class _Failing:
        config = None

        async def generate(self, *args, **kwargs):
            calls["n"] += 1
            raise exc

    for full, op in _walk(graph):
        if str(full).rsplit(".", 1)[-1] == op_name:
            op._llms, op._fallback_llms, op._initialized = [_Failing()], [], True
    return calls


def _walk(graph: Any, prefix: str = ""):
    """Yield `(full_name, op)` for every op, into subgraphs."""
    for name, op in (getattr(graph, "_ops", None) or {}).items():
        full = f"{prefix}{name}"
        yield full, op
        if getattr(op, "_ops", None):
            yield from _walk(op, full + ".")


#: Op types that open a socket. Matched on type rather than name because
#: `retrieval` is a *subgraph*: poisoning its core leaves its children to run,
#: and they are the ones holding the embedder and the two stores. A poisoned
#: run reached the real Triton endpoint that way — three connection attempts
#: from what is meant to be an offline test.
_NETWORK_TYPES = frozenset({
    "llm", "embedding", "vector-search", "doc-fetch", "reranking",
})


def _poison_network_ops(graph: Any) -> int:
    """Give every op that could reach the network a core that raises."""
    n = 0
    for full, op in _walk(graph):
        base = str(full).rsplit(".", 1)[-1]
        # The subgraph stays in by name as well: a stub replaces it wholesale,
        # and poisoning it too means an *unstubbed* one fails at the boundary
        # with a name a reader recognises rather than four levels down.
        reaches_out = str(getattr(op, "type", "")) in _NETWORK_TYPES or base == "retrieval"
        if reaches_out:
            op._set_core(_make_poison(full))
            n += 1
    return n


def _make_poison(name: str):
    async def core(**_inputs):
        raise WouldHaveCalledOut(
            f"replay reached `{name}`, which the recording does not cover. "
            f"This op would have called a live endpoint. Either the fixture "
            f"takes a path the trace block never recorded, or a stub key "
            f"stopped matching after a rename."
        )

    return core


def _make_core(payload: Dict[str, Any]):
    """An async core, because the op being replaced already has one.

    `_set_core` only resolves `bound` when it is still None, and an LLMOp
    resolved to `"io"` at construction. Handing it a sync function leaves
    the dispatcher awaiting a dict.
    """

    async def core(**_inputs):
        return dict(payload)

    return core
