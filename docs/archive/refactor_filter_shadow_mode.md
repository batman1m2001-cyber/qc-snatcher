# Refactor Plan — Filter shadow mode + toggle cleanup

| Field | Value |
|---|---|
| **Scope** | v4 sentiment_agent pre-filter (LLM + keyword). No v3 changes. |
| **Goal** | (1) Add shadow mode: filter runs but doesn't gate main flow. (2) Simplify existing toggle wiring. |
| **Author** | thanglq12 |
| **Date** | 2026-08-04 |

---

## 1. Motivation

Two problems with the current pre-filter:

1. **No shadow eval on live traffic.** To measure filter recall/precision today, you have to run the pipeline twice (once with filter on, once off) and diff. Painful for live monitoring.
2. **Toggle wiring is messy.** `check_toggles_fn` + 2-tier nested `if_()` chains inside the subgraph make the decision tree hard to read. 3 terminals (`all_disabled_pass`, `kw_hit_pass`, `kw_only_clean`) with near-identical bodies.

---

## 2. Design

### 2.1 Env vars — 3 orthogonal knobs

| Var | Default | Meaning |
|---|---|---|
| `SENTIMENT_FILTER_LLM_RESOURCE_KEY` | `""` | Non-empty → LLM filter on, bind to key |
| `SENTIMENT_FILTER_KEYWORD_ENABLE` | `false` | Keyword filter on/off |
| `SENTIMENT_FILTER_APPLY` | `true` | `true` = gate main flow (current); `false` = shadow (annotate only, always continue) |

Truth table:

| APPLY | LLM/KW enabled | should_scan | Effect |
|---|---|---|---|
| any | neither | n/a | Filter subgraph short-circuits, no annotation, main flow runs |
| true | ≥1 | true | Main flow runs (current behavior) |
| true | ≥1 | false | `filter_exit` short-circuit (current behavior) |
| false | ≥1 | true | Main flow runs, filter meta on result |
| false | ≥1 | false | **Main flow runs anyway**, filter meta says "would've blocked" |

### 2.2 Config module

Move filter env constants + helpers from [_filter.py](../src/cases/sentiment_agent/v4/_filter.py) into [src/config.py](../src/config.py):

```python
# src/config.py
SENTIMENT_FILTER_RESOURCE_ENV = "SENTIMENT_FILTER_LLM_RESOURCE_KEY"
SENTIMENT_FILTER_KEYWORD_ENABLE_ENV = "SENTIMENT_FILTER_KEYWORD_ENABLE"
SENTIMENT_FILTER_APPLY_ENV = "SENTIMENT_FILTER_APPLY"

SENTIMENT_FILTER_LLM_RESOURCE_KEY = (os.environ.get(SENTIMENT_FILTER_RESOURCE_ENV, "").strip()
                                     or "e4b-local")

def filter_llm_enabled() -> bool: ...
def filter_keyword_enabled() -> bool: ...
def filter_apply_enabled() -> bool: ...        # default True
def any_filter_enabled() -> bool: ...
```

`_filter.py` re-exports for backwards compat (v3 filter still exists and imports the old names).

### 2.3 Subgraph cleanup — one dispatcher

Replace `check_toggles_fn` + nested `if_()` chains with ONE `dispatch_fn`:

```python
@op
def dispatch_fn(conversation: Conversation) -> dict:
    llm_on = filter_llm_enabled()
    kw_on  = filter_keyword_enabled()
    if not (llm_on or kw_on):
        return {"route": "disabled_pass", "kw_hit": False, "llm_needed": False}
    kw_hit = _check_keyword_hit(conversation) if kw_on else False
    if kw_hit:
        return {"route": "kw_hit_pass", "kw_hit": True, "llm_needed": False}
    if llm_on:
        return {"route": "llm_scan", "kw_hit": False, "llm_needed": True}
    return {"route": "kw_clean_pass", "kw_hit": False, "llm_needed": False}
```

Single `if_()` chain on `dispatch["route"]` → 4 terminals.

Subgraph output contract widens to:

```python
{
    "should_scan": bool,
    "reason": str,
    "kw_hit": bool,
    "llm_verdict": bool | None,   # None if LLM not run
}
```

### 2.4 Outer graph — new `apply_filter_gate_fn`

Insert between `filter_node` and `r_filter` in v4/graph.py:

```python
apply_gate = apply_filter_gate_fn(filter_result=filter_node)
# Returns {gate: "block" | "pass", filter_meta: {...}}
r_filter = if_(apply_gate["gate"] == "block", "filter_exit").else_("bot_check")
```

Op body:

```python
@op
def apply_filter_gate_fn(filter_result: dict) -> dict:
    apply = filter_apply_enabled()
    should_scan = bool(filter_result.get("should_scan", True))
    gate = "block" if (apply and not should_scan) else "pass"
    return {"gate": gate, "filter_meta": filter_result}
```

### 2.5 Result annotation — thread `filter_meta` to terminals

7 terminals AFTER the filter stage accept a new optional `filter_meta` kwarg and stash it in `result["_trace_meta"]["filter"]`:

| Terminal | Location |
|---|---|
| `filter_exit` (existing exit_fn) | v4/graph.py |
| `exit_bot` (exit_fn) | v4/graph.py |
| `exit_kid` (exit_fn) | v4/graph.py |
| `halu_suppress_fn` | v4/_matcher.py |
| `skip_matcher_fn` | v4/_matcher.py |
| `apply_asr_check_result_fn` | v4/_matcher.py |
| `apply_decider_result_fn` | v4/_matcher.py |

`exit_fn` in [_ops.py](../src/cases/_ops.py) gets a new optional `filter_meta` kwarg (shared across cases; only v4 uses it).

Meta shape:

```python
result["_trace_meta"]["filter"] = {
    "should_scan": bool,
    "reason": str,
    "kw_hit": bool,
    "llm_verdict": bool | None,
    "applied": bool,     # True if gate=block would've fired (i.e., filter_apply_enabled() at gate time)
}
```

---

## 3. Wiring diagram

```
START
  └── r_scope ─┬── exit_code ── END
               └── fmt
                    └── r_silent ─┬── quiet ── END
                                   └── filter_node (subgraph)
                                        └── apply_gate (NEW)
                                             └── r_filter ─┬── filter_exit ── END
                                                            └── bot_check ── ... (main flow)
```

Only ONE new op inserted. `r_filter` predicate changes from `should_scan` to `gate == "block"`.

---

## 4. Backwards compatibility

- Default `SENTIMENT_FILTER_APPLY=true` → identical behavior to today
- Existing env vars unchanged
- v3 filter untouched (still under `sentiment_agent/v3/_filter.py`)
- Existing v3 test suite (`test_sentiment_agent_v3_filter.py`) unaffected

---

## 5. Implementation checklist

- [x] 5.1 Add `SENTIMENT_FILTER_*` constants + helpers to `src/config.py`
- [x] 5.2 Refactor `v4/_filter.py`:
    - [x] Add `dispatch_fn` op
    - [x] Remove `check_toggles_fn`, `all_disabled_pass_fn`, `kw_hit_pass_fn`, `kw_only_clean_fn`
    - [x] Widen subgraph output contract (`kw_hit`, `llm_verdict`)
    - [x] Re-export legacy names for backwards compat
- [x] 5.3 Add `apply_filter_gate_fn` op (kept in `v4/_filter.py`)
- [x] 5.4 Update `v4/graph.py`:
    - [x] Insert `apply_gate` node after `filter_node`
    - [x] Change `r_filter` predicate → `gate == "block"`
    - [x] Thread `filter_meta` kwarg to 7 terminal ops
- [x] 5.5 Update `v4/_matcher.py`:
    - [x] Add `filter_meta` kwarg to 4 apply/suppress/skip ops
    - [x] Stash in `_trace_meta["filter"]`
- [x] 5.6 Update `_ops.py`:
    - [x] Add `filter_meta` kwarg to `exit_fn`
- [x] 5.7 Verify: `uv run pytest tests/…` — 193/193 pass (excluded 1 pre-existing broken test unrelated to this change)
- [x] 5.8 Smoke: v4 graph builds, `dispatch_fn` covers all 4 routes, `apply_filter_gate_fn` covers all 5 truth-table cells

---

## 6. Test additions (deferred)

Not part of this refactor — add later if needed:

- `test_sentiment_agent_v4_filter.py` — mirror v3 tests + shadow mode cases
- Integration test: apply=false + should_scan=false → main flow runs, `_trace_meta.filter.applied=False`

---

## 7. Follow-up considerations

- Prod rollout: flip `SENTIMENT_FILTER_APPLY=false` on a small batch to compare filter verdict vs main flow verdict per call → measure recall/precision on real traffic
- Documentation: after merge, add `SENTIMENT_FILTER_APPLY` to the env var table in `CLAUDE.md`
