# [Sent-HVC] Tech Spec — Sentiment_Agent Pipeline Architecture Update (Go-Live)

| | |
|---|---|
| Owner | Thang Le Quang (EDA - AI.DS) |
| PM | chamttn |
| Status | Ready for Go-Live |
| Go-live date | 2026-08-08 |
| Version | 1.0 |

**Scope.** Ship the new architecture for the `sentiment_agent` case of the QC pipeline — replace the separate verifier step with a **retrieval-fused decider**, add **bot check** + **secondary decider** + **soften**, and enable **multi-model routing** (Gemini 3 Flash primary + Sonnet 4.5 secondary). Output schema unchanged, runs on the existing batch runner pods + Databricks endpoint. Other six QC cases in the pipeline are untouched.

---

## TL;DR

| Aspect | Current live | New architecture |
|---|---|---|
| **LLM cost / month** | **~$30 k** (Sonnet everywhere) | **~$2.0–2.5 k** (~14× cheaper) |
| **Monthly saving** | — | **~$27.5–28 k / month (~$330–336 k / year)** |
| Post-scanner LLM step | Scanner + separate verifier (2 stages) | Scanner + **retrieval-fused decider** (single call, reads evidence + both retrieval pools + taxonomy) |
| Primary LLM tier | Sonnet on every stage | **Gemini 3 Flash** for scanner + decider + soften + side-detectors; Sonnet only on secondary decider |
| IVR / voicemail handling | Scored as if human — false alarm on AGENT's reaction to robot | **Bot check regex** — skip evaluation entirely (~2.4 % of traffic) |
| False-positive guard | None | **Secondary decider (Sonnet 4.5)** — re-checks flagged verdicts, downgrades to `"none"` on disagree |
| Reason tone for C\* / N\* verdicts | Verifier text (accusatory) | **Soften** — rewrites to descriptive tone for QC UX (F1 unaffected) |
| Retrieval schema | 1 corpus entry = 1 embedding | 1 entry = multiple variant embeddings, grouped by `parent_id` to avoid dilution |
| Strong-VP regex bypass | ON (regex short-circuits verifier) | OFF (decider evaluates context); env fallback `QC_ENABLE_STRONG_VP_BYPASS=true` |
| **F1 on 1 700-call pilot round** | Not tracked | **0.836** (target ≥ 0.80) |
| Rollback | — | **Single-line alias flip** in `sentiment_agent/__init__.py` (~5 min) + env-var kill-switch per optional stage (< 30 s, no redeploy) |
| Output schema | Row shape v1 | **Row shape v1 unchanged** — downstream QC dashboard + IT parser untouched |

**Bottom line.** ~14× cost cut (~$28 k / month saving) comes from **primary tier switch** (Sonnet → Gemini 3 Flash on ~100 % of calls) + **scoping Sonnet to secondary FP guard only on ~6 % of flagged calls**. F1 = 0.836 measured on the 1 700-call pilot round holds above target. No new hardware, no schema change.

---

## As-is — limitations of the current pipeline

1. **100 % of calls hit Sonnet for both scanner and verifier.** No tier routing means Sonnet is billed on every call, including obviously-clean ones → cost ~$30 k / month on the sentiment_agent case alone.
2. **IVR / voicemail calls are not gated.** ~2.4 % of live calls hit a `trợ lý ảo` / voicemail pickup — the AGENT's reaction to a robot voice is scored as a negative-sentiment violation → a well-defined FP class.
3. **No FP guard on high-severity verdicts.** The verifier's decision is final — no second-pass strict re-check on flagged high-severity cases.
4. **No reason-tone control.** The reason field is emitted verbatim by the verifier; QC business consumers get accusatory phrasing with no downstream rewrite step.
5. **No retrieval — verifier dumps the entire YAML rulebook.** The current-live verifier receives the full per-category ruleset verbatim; there is no similarity-ranked retrieval. Long carveout lists dilute the LLM's attention on the rules actually relevant to the specific evidence turn.
6. **Regex bypass short-circuits the verifier on strong-VP keywords.** `cố tình / trốn tránh / lật mặt / ...` legitimately appear in echoed customer speech, negation, and self-defence — the regex makes a syntactic decision on a semantic question → FP on those turns.
7. **Prompts are monolithic.** Scanner and verifier each carry multiple concerns (locate + judge + carveout application). When a FN / FP surfaces, it is hard to pin down which sub-concern went wrong.

---

## Solution — modular architecture for `sentiment_agent`

### 1. Core decision path

Each stage owns one narrow responsibility with its own targeted prompt. Bugs trace to a specific stage; prompt tuning is independent per stage.

| Stage | Model tier | Responsibility |
|---|---|---|
| **Scanner** | Gemini 3 Flash | Sweep the transcript, flag candidate violation turns. Emits `violation_bool + category + evidence turn_idx + reason`. Prompt: `SCANNER_PROMPT.prompt` |
| **Attribution** | Deterministic (Python) | Substring anchor check: do the quoted phrases in the scanner's reason match a literal substring of the evidence turn? |
| **Halu check** | Gemini 3 Flash | Fires only when attribution fails. LLM verifies whether the scanner attribution is misattribution / hallucination or real. Prompt: `HALU_CHECK_PROMPT.prompt` |
| **Retrieval — positives pool** | BGE-M3 ONNX (local) | Pull top-K violation samples from the corpus, ranked by similarity to the evidence turn. |
| **Retrieval — carveouts pool** | BGE-M3 ONNX (local) | Pull top-K exclusion samples from the corpus, ranked by similarity to the evidence turn. |
| **Decider** | Gemini 3 Flash | Reads evidence + both retrieval pools + 8-category taxonomy → final verdict in **one LLM call**. Emits `violation bool + reason + cited_positives + cited_carveouts`. Prompt: `DECIDER_PROMPT.prompt` |
| **ASR check** (heavy-kw branch) | Gemini 3 Flash | Fires only when the evidence contains heavy vulgar keywords (`mày / tao / con nợ / thô tục`). Tone-continuity check to distinguish a real slur from ASR misheard `máy` → `mày`. Prompt: `ASR_CHECK_PROMPT.prompt` |

### 2. Optional post-verdict stages

Both are env-gated. When the env var is unset the stage is skipped at graph build time, no code change.

| Stage | Model tier | Env gate | Behaviour |
|---|---|---|---|
| **Secondary decider** | Sonnet 4.5 | `SECONDARY_DECIDER_LLM_RESOURCE_KEY` | Fires only when the primary verdict is `violation=true` and `evidence_idxs` is non-empty. Sonnet re-verifies with tighter criteria plus explicit FP guardrails (E1–E5 patterns). On disagree: downgrade `category` → `"none"`, `violation` → `"false"`, stash the original in `original_category` + `secondary_reason` for audit. Prompt: `SECONDARY_DECIDER_PROMPT.prompt` |
| **Soften** | Gemini 3 Flash | `SOFTEN_LLM_RESOURCE_KEY` | Fires only when `category` starts with `C*` (thái độ cao) or `N*` (nghiêm trọng) and `reason` is non-empty. Rewrites the reason field into descriptive (non-accusatory) language for the QC business audience. **F1 is unaffected** — only the free-text reason changes; verdict / category / evidence stay the same. Prompt: `SOFTEN_REASON_PROMPT.prompt` |

### 3. Auxiliary side-detectors

Each is small, single-purpose, and only fires when its gate condition applies.

| Stage | Type | Position | Behaviour when hit |
|---|---|---|---|
| Silent check | Deterministic (Python) | Before scanner | Exit `im_lang` when the AGENT is silent throughout the call |
| Filter subgraph | KW ∪ cheap LLM (opt-in) | After silent check | **OFF this release** — both env vars unset → passthrough. See `docs/DAB_gemma4_e4b_filter.md` for the follow-up phase |
| **C12 pre-scanner** | Gemini 3 Flash | Before bot check (when active) | **DISABLED this release.** A full-day diagnostic scan showed Gemini 3 Flash over-flagged AGENT identity-verification turns (`em hỏi có phải số của anh X không`) as C12 side-chatter with ~100 % FP rate. Real C12 cases are rare per QC. Re-enable after prompt + corpus rewrite in a follow-up phase |
| Bot check | Regex | Before short check | Skip evaluation entirely (exit `khach_la_bot`) if the regex matches IVR / voicemail / `trợ lý ảo` phrases. Pattern survey on 412 live calls found 10 IVR cases (2.4 %) |
| Kid check | Gemini 3 Flash | After short check (only on short calls, ~20 %) | Exit `khach_la_tre_em` when the customer is detected as a child (avoids FP on `con` xưng-hô with child customers) |

### 4. Retrieval schema — variant grouping

Corpus entries can carry multiple variants separated by ` | ` (pipe with spaces):

```yaml
- content: "cố tình không trả | cố tình trốn tránh | cố ý kéo dài"
  description: "Attributes intentional non-payment to the customer."
```

- **Split at index build.** `_flatten_corpus()` splits by ` | ` into separate items sharing a common `parent_id`.
- **Embed each variant independently.** BGE-M3 encodes each string in isolation → avoids embedding dilution when multiple semantics are merged into one vector.
- **Group at prompt time.** `_format_pool()` groups retrieved items by `parent_id`, printing the description once with all matched variants:
  ```
  - [C1] cố tình không trả / cố tình trốn tránh
    context: Attributes intentional non-payment to the customer.
  ```
- **Fallback.** Legacy plain-string entries (no ` | `) still work — treated as a 1-variant entry.
- **ONNX session serialised.** Cold init is ~2 GB VRAM → parallel workers with a cold cache = OOM. `BgeRetriever` uses a threading lock — first caller pays the init cost, others wait and reuse the singleton.

### 5. Multi-model routing

| Env var | Stages | Recommended resource | When unset |
|---|---|---|---|
| `LLM_RESOURCE_KEY` | Scanner, kid check | `<gemini-3-flash-resource>` | Required — pipeline errors at graph build |
| `DECIDER_LLM_RESOURCE_KEY` | Decider, halu check, ASR check | `<gemini-3-flash-resource>` | Falls back to `LLM_RESOURCE_KEY` |
| `SECONDARY_DECIDER_LLM_RESOURCE_KEY` | Secondary decider | `<sonnet-4-5-resource>` | Secondary decider disabled — flagged verdicts pass through untouched |
| `SOFTEN_LLM_RESOURCE_KEY` | Soften | `<gemini-3-flash-resource>` | Soften disabled — reason field passes through unchanged |
| `SENTIMENT_FILTER_LLM_RESOURCE_KEY` | Pre-filter LLM (out of scope) | — | Filter disabled — passthrough (this release) |
| `SENTIMENT_FILTER_KEYWORD_ENABLE` | Pre-filter KW (out of scope) | — | KW filter disabled (this release) |
| `QC_ENABLE_STRONG_VP_BYPASS` | Fallback to restore regex bypass | `true` on demand | Regex bypass OFF (default). Set to `true` if a FN spike appears on strong-VP evidence |

### 6. Safety — fallbacks, kill-switches, audit

| Mechanism | Behaviour | Trigger |
|---|---|---|
| **Full-pipeline rollback** | Change one import line in `src/cases/sentiment_agent/__init__.py`: `from . import verify_sentiment_agent as verify_sentiment_agent` → `from .v3 import verify_sentiment_agent_v3 as verify_sentiment_agent`. Redeploy the job. **~5 min** | Regression signal (F1 drop, cost spike, downstream complaint) |
| **Secondary decider disable** | Unset `SECONDARY_DECIDER_LLM_RESOURCE_KEY` in the Databricks job config. Graph auto-skips the stage. **< 30 s, no redeploy** | Over-suppression detected (secondary disagree rate too high) |
| **Soften disable** | Unset `SOFTEN_LLM_RESOURCE_KEY`. Reason field passes through unchanged. **< 30 s, no redeploy** | QC business flags meaning-shift in the reason field |
| **Strong-VP regex restore** | `QC_ENABLE_STRONG_VP_BYPASS=true`. Regex short-circuits the verifier on strong-VP keywords, matching prior behaviour. **< 30 s, no redeploy** | FN spike on `cố tình / trốn tránh / lật mặt / ...` |
| **Fail-open on parse error** | LLM returns malformed JSON → validator rejects → hush retries per `max_retries` in `resources.yaml`. If retries exhaust → skip stage, log error, downstream unblocked | Every LLM stage |
| **Trace metadata on every stage** | Every result payload carries `result["_trace_meta"]` with keys `scanner / retrieval / decider / halu_check / asr_check / secondary_decider / soften` — each fired stage records verdict + reason there | Every call — shipped at go-live |
| **Structured logs for pipeline events** | Application log lines for router decisions, stage entry / exit, retries | Every call — shipped at go-live |

---

## Go-Live Deployment

| | |
|---|---|
| **Artifact** | Code + config already merged on the `dev` branch of the `analyze` repo: (1) `src/cases/sentiment_agent/v4/*` — v4 code (scanner + decider + matcher + retriever + auxiliary detectors). (2) `src/cases/sentiment_agent/_secondary_decider.py`, `_soften.py` — the two optional stages. (3) `src/cases/sentiment_agent/__init__.py` — alias flip v3 → v4. (4) `src/config.py` — three new env vars (`DECIDER_LLM_RESOURCE_KEY`, `SECONDARY_DECIDER_LLM_RESOURCE_KEY`, `SOFTEN_LLM_RESOURCE_KEY`). (5) `resources.yaml` — resource entries for the Gemini 3 Flash + Sonnet 4.5 Databricks endpoints. (6) `.prompts/sentiment_agent/*.prompt` — v4 prompts. (7) `.prompts/sentiment_agent/{SECONDARY_DECIDER,SOFTEN_REASON}_PROMPT.prompt` — prompts for the optional stages. (8) `.prompts/sentiment_agent/corpus.yaml` — new corpus with variant syntax. **No new container image** — same base image as the prior release. |
| **Interface compatibility** | `CASE_SPEC` unchanged. Pipeline output schema unchanged (`Reasoning / Result / Evidence / Score_offset` + `CriteriaCode=TC_2`). Downstream QC dashboard, IT parser, and orchestrator require no changes. Trace surface `result["_trace_meta"]` gains new keys (`decider / secondary_decider / soften`) — audit consumers can opt in; existing consumers ignore them. |
| **Constraints** | (1) The Gemini 3 Flash resource and the Sonnet 4.5 resource must be registered in `resources.yaml` with names matching the values of the four LLM env vars — a miss crashes the pipeline at graph build. (2) The BGE-M3 ONNX model must be mounted or downloadable from the pod; path via `BGE_M3_EMBEDDING_PATH` env (default `D:\bge-m3-onnx` on local, adjust for the production pod). (3) `.prompts/sentiment_agent/v3/qc_label_flips.yaml` must be deployed alongside — the verifier applies QC label updates from this file. (4) `corpus.yaml` must load through `_flatten_corpus()` at startup — if the variant syntax is wrong (`/` instead of ` | `), the embedding rebuild fails. |
| **Env vars set at go-live** | `LLM_RESOURCE_KEY=<gemini-3-flash-resource>`, `DECIDER_LLM_RESOURCE_KEY=<gemini-3-flash-resource>`, `SECONDARY_DECIDER_LLM_RESOURCE_KEY=<sonnet-4-5-resource>`, `SOFTEN_LLM_RESOURCE_KEY=<gemini-3-flash-resource>`. |
| **Env vars left unset** | `SENTIMENT_FILTER_LLM_RESOURCE_KEY`, `SENTIMENT_FILTER_KEYWORD_ENABLE` (filter code present but OFF this release). |
| **Fallback env available** | `QC_ENABLE_STRONG_VP_BYPASS=true` — restores the legacy regex bypass if a FN spike appears on evident-slur turns. Can be set after go-live if needed. |
| **Deployment owner** | DS2 — Win AI Center |
| **Rollback plan** | (1) **Kill-switch an optional stage** (< 30 s, no redeploy): unset the corresponding env var for secondary decider / soften in the Databricks job config → graph auto-skips the stage. (2) **Alias flip** (~5 min): edit the import in `sentiment_agent/__init__.py` from v4 back to v3, redeploy the job. Downstream requires no intervention because CASE_SPEC and output schema are unchanged. (3) **Deep revert** (~15 min): revert the merge commit `main` → `dev`, redeploy. |

---

## Conclusion

The new architecture replaces the separate verifier with a retrieval-fused decider, adds bot check + secondary decider + soften, and switches to multi-model routing (Gemini 3 Flash primary + Sonnet 4.5 secondary FP guard). LLM cost drops ~14× (**~$28 k / month saving, ~$330 k / year**) with **F1 = 0.836** on the 1 700-call pilot round (target ≥ 0.80). No new hardware, no output schema change — downstream is untouched. Rollback via alias flip (~5 min) plus env-var kill-switch per optional stage (< 30 s, no redeploy).

---

### Appendix — Cost breakdown

**Baseline.** Current live pipeline (Sonnet everywhere, no filter) costs **~$30 k / month** on the sentiment_agent case, implied ~500 k calls / month at ~$0.06 / call.

**Pricing (public list):**
- Gemini 3 Flash: $0.30 / M input, $2.50 / M output
- Sonnet 4.5: $3 / M input, $15 / M output

**Per-call cost derivation** (transcript median ~1 000 tok):

| Stage | Model | Fires on | Prompt tok | Output tok | Per-fire $ | Weighted per-call $ |
|---|---|---|---|---|---|---|
| Scanner | Flash | ~87 % | ~5 000 | 400 | $0.00280 | $0.00244 |
| Kid check | Flash | ~18 % | ~2 300 | 200 | $0.00149 | $0.00027 |
| Halu check | Flash | ~4 % | ~900 | 200 | $0.00086 | $0.00003 |
| Decider | Flash | ~10 % | ~2 500 | 300 | $0.00180 | $0.00018 |
| ASR check | Flash | ~1 % | ~2 400 | 200 | $0.00131 | $0.00002 |
| **Secondary decider** | **Sonnet** | **~6 %** | ~5 000 | 300 | $0.01950 | $0.00117 |
| Soften | Flash | ~3 % | ~500 | 200 | $0.00065 | $0.00002 |
| **Total per call** | | | | | | **~$0.0041** |

**Projection at $30 k baseline traffic (~500 k calls / month):**

| Configuration | Est. monthly cost | vs current |
|---|---|---|
| Current live (Sonnet everywhere) | ~$30 k | 1.00× |
| **Proposed (multi-model routing)** | **~$2.0–2.5 k** | **~0.07–0.08×** |
| **Estimated monthly saving** | — | **~$27.5–28 k / month, ~$330–336 k / year** |

**Fire rate assumptions:** silent ~5 %, bot ~2.4 %, short ~20 %, kid-of-short ~30 %, scanner detection ~15 % (anchor: `project_live_20260629_baseline.md` — 848 / 5 054 = 16.78 %), halu suppress ~50 %, ASR route ~10 %.

**Load-bearing driver.** The primary tier switch (Sonnet → Gemini 3 Flash on ~100 % of calls) is the bulk of the saving. Sonnet on the secondary decider fires on only ~6 % of input calls → the secondary line ~$0.001 / input call is the single biggest line item in the proposed pipeline.

Full derivation + estimator disclaimer: see DAB `docs/DAB_sentiment_agent_pipeline_golive.md` §4.4.

---

### Appendix — Behaviour deltas

| Call class | Prior | Proposed |
|---|---|---|
| Bot / IVR picks up | AGENT reaction to robot voice may score as violation | Skipped entirely at the bot check regex gate |
| Evidence contains strong-VP keyword (`cố tình / trốn tránh / ...`) | Regex bypass — verifier skipped, syntactic decision | Decider evaluates full context (semantic) |
| Ambiguous case (negation / echo / self-defence) | Sometimes over-flagged due to incorrect regex bypass | Decider disambiguates using both retrieval pools + context |
| High-severity verdict (C\* / N\*) reason field | Verifier text (accusatory tone) | Softened to descriptive tone (F1 unaffected) — when the soften env is set |
| Flagged verdict on cheap-tier decider | Final | Optionally re-verified by Sonnet secondary decider — can downgrade to `"none"` on disagree |

---

### Appendix — Code & config references

| Component | Path |
|---|---|
| Pipeline entrypoint (alias) | `src/cases/sentiment_agent/__init__.py` |
| v4 graph | `src/cases/sentiment_agent/v4/graph.py` |
| v4 matcher / decider ops | `src/cases/sentiment_agent/v4/_matcher.py` |
| v4 retriever (BGE-M3) | `src/cases/sentiment_agent/v4/_retriever.py` |
| v4 filter subgraph (OFF this release) | `src/cases/sentiment_agent/v4/_filter.py` |
| v4 side-detectors | `src/cases/sentiment_agent/v4/{_kid_detector,_bot_check,_c12_detector,_asr_check,_keyword_filter}.py` |
| Secondary decider | `src/cases/sentiment_agent/_secondary_decider.py` |
| Soften | `src/cases/sentiment_agent/_soften.py` |
| Env vars + config constants | `src/config.py` |
| Resource registry | `resources.yaml` |
| v4 prompts | `.prompts/sentiment_agent/{SCANNER,DECIDER,HALU_CHECK,ASR_CHECK,FILTER,C12_DETECTOR,KID_DETECTOR}_PROMPT_V4.prompt` |
| Secondary decider + soften prompts | `.prompts/sentiment_agent/{SECONDARY_DECIDER,SOFTEN_REASON}_PROMPT.prompt` |
| v4 corpus + keyword filter | `.prompts/sentiment_agent/{corpus,keyword_filter}.yaml` |
| QC label overrides | `.prompts/sentiment_agent/v3/qc_label_flips.yaml` |
| BGE-M3 ONNX model | Path via `BGE_M3_EMBEDDING_PATH` env |
| DAB (design justification) | `docs/DAB_sentiment_agent_pipeline_golive.md` |
| Integration branch | `dev` of the `analyze` repo |
