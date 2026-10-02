# Refactor plan — operonx layout for `src/`

## Status — 2026-09-25: done

All six steps landed, each verified offline (847 tests, 0 undefined names,
`PROMPTS` byte-identical, zero graph-shape change, corpus hash unchanged).
**Owed:** one selfcheck on VPN, and MLE's review of the one-line
`Dockerfile` change in step 5.

Left for a follow-up, deliberately out of scope:

- four prompts no op reads — `VIOLATION_CASE1_PROMPT`,
  `VIOLATION_CASE2A_PROMPT`, `VIOLATION_CASE2B_PROMPT`,
  `VIOLATION_CASE3_VOICEMAIL_DETECT`
- the `corpus-update` skill runs `scripts/corpus_from_qc_xlsx.py`, which was
  archived to `scripts/_archive/` before this refactor
- dated docs under `docs/` (plans, audits, UAT reports) still name the old
  paths; they describe the code as it was and are left as history

**Goal:** every package reads the same way — one root op in `graph.py`, its
ops beside it, prompts beside the op that sends them. **No logic changes.**

## Target

```
src/
  graph.py                    root op (was orchestrator.py)
  core/                      config · conversation · prompts · _bootstrap
  pipeline/                  batch runner (unchanged)
  corpus/                    corpus seeding code (unchanged)
  cases/
    _shared/                 helpers used by ≥2 cases (was cases/_ops.py)
    hangup/
      graph.py                root op: verify_hangup + format_hangup
      ops.py                 the @ops it wires
      _bot_gates.py          private helpers
      prompts/*.prompt
    sentiment_agent/
      graph.py                l1 → l2 → l3 → l4
      _retrieval.py _pools.py _context.py _trace.py   shared by layers
      l1_gates/   graph.py  ops.py  _*.py  prompts/
      l2_scanner/ graph.py  ops.py  _*.py  prompts/
      l3_decider/ graph.py  ops.py  _*.py  prompts/
      l4_verify/  graph.py  ops.py  _*.py  prompts/

knowledge/                   QC-maintained data + built index (was .prompts/…)
  sentiment_agent/
    corpus.yaml
    keyword_filter.yaml
    index/                   gitignored, rebuilt on freshness mismatch
```

## Rules

| file | holds |
|---|---|
| `graph.py` | the package's root op only — `@graph`, plus `format_<id>` for a case |
| `ops.py` | `@op`s the root wires, plus private helpers only those ops use |
| `_*.py` | non-op helpers shared by more than one file in the package |
| `prompts/` | `.prompt` files sent by this package's ops |

A helper moves up only when a second package needs it, and only to the
lowest common parent. A stage gets its own package only when it must be
a subgraph node — reused (`sentiment_agent/retrieval/`) or needing the
boundary (`l1_gates/prefilter/`, for `.collect()`). Sequential stages stay
flat in their layer's graph (l4's primary decider and soften). A small
private subgraph stays in its parent's `graph.py` (raba's `_detect`).

## Prompt → package

| package | prompts |
|---|---|
| `l1_gates` | `KID_DETECTOR`, `FILTER` |
| `l2_scanner` | `SCANNER`, `HALU_CHECK` |
| `l3_decider` | `DECIDER`, `ASR_CHECK` |
| `l4_verify` | `SECONDARY_DECIDER`, `SOFTEN_REASON` |
| each other case | its own `VIOLATION_CASE*` / `CUSTOMER_SENTIMENT` |

`PROMPTS` keys stay the file stem; the loader `rglob`s `src/` instead of
`.prompts/`, and **raises on a duplicate stem** so moving files cannot
silently shadow one.

## Steps — one commit each, suite green after every one

| # | change | risk |
|---|---|---|
| 1 | `orchestrator.py` → `src/graph.py` — the root at `src/` follows the same rule as every package (`graph.py` kept over `flow.py`: it names the `@graph` inside, and operonx has no per-package convention to align with) | imports only |
| 2 | ops into `ops.py`; subgraphs with their own ops into packages | imports only — **done** |
| 3 | `config` · `conversation` · `prompts` · `_bootstrap` → `src/core/`; `cases/_ops.py` + `cases/spec.py` → `cases/_shared/`; `src/config.py` aliases `src.core.config` | imports; path math — **done** |
| 4 | prompts → `<package>/prompts/`; loader points at `src/`, duplicate-stem guard | test_prompt_split, trace redaction — **done** |
| 5 | corpus · keyword list · index → `knowledge/`; one constant owns the path; **`Dockerfile:95` in the same commit** | selfcheck corpus hash, RAG scripts, `corpus-update` skill, image build — **done** |
| 6 | docs: CLAUDE.md, README, skills, `.kiro/` | none — **done** |

## Verification (offline, no LLM)

- 842 tests + pyflakes pass after every step
- `scripts/snapshot_graphs.py` — **zero** structural diff; only op paths
  may change, never shape
- replay: 80 calls verdict-identical, trace block intact
- `PROMPTS` has the same keys and byte-identical values before and after
- corpus freshness hash unchanged — `knowledge/` holds the same bytes

Then **one selfcheck** on VPN to confirm; expect ~98%.

## MLE-owned files

| file | change | when |
|---|---|---|
| `deployment/score_sentiment/sentiment.py:23` | none — `from src.config import …` keeps working through a re-export shim at `src/config.py` | step 3 |
| `Dockerfile:95` | `COPY ./.prompts /app/.prompts` → `COPY ./knowledge /app/knowledge` | step 5, same commit |

The Dockerfile edit is **that one line and nothing else** — base image, pip,
entrypoint stay theirs. It must land with the move: apart, either the build
fails on a missing `.prompts/` or copies a `knowledge/` that is not there
yet. Prompts need no copy line of their own — they ride in `COPY ./src/`.
The MR goes to MLE for review, not a notice after.

## Not in scope

`main.py`, `deployment/`, `scripts/` layout, `tests/` layout — imports
updated, structure untouched.
