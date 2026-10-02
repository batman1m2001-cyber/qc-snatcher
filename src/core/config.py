"""Pipeline settings — stage routing from `models.yaml`, toggles from env.

**Which resource serves each stage** comes from `models.yaml` at the repo
root and nowhere else — see `_load_routing`. No environment variable
overrides it: an override would make the file the truth locally and a
suggestion wherever something writes the variable, letting production
routing drift from the tested one.

`ENABLED_CASES`            — set of case ids enabled by per-case boolean
                              env vars `QC_ENABLE_<CASE_ID>`. Each defaults
                              to true when unset, so the whole feature is
                              opt-out per case. When every case is on
                              (the default), the value collapses to `None`
                              so the pipeline skips the filter block
                              entirely. `pipeline.run` intersects any
                              per-audio whitelist with this set.

  Example — disable raba + card_number only:
    QC_ENABLE_RABA=false
    QC_ENABLE_CARD_NUMBER=false

No fallback resource: operonx retries empty/error responses inside
`_call_with_retry` (config `max_retries` in `resources.yaml`), which covers
Anthropic's occasional empty-content response.
"""

import logging
from pathlib import Path

from .case_ids import CASE_IDS
from .env import env_bool


_LOG = logging.getLogger(__name__)


#: Stage -> resource. Read once at import; every value names an entry in
#: `resources.yaml`.
ROUTING_FILE = Path(__file__).resolve().parents[2] / "models.yaml"

_ROUTING_SHAPE = {
    "llm": ("default", "filter_decider", "primary_decider", "soften", "prefilter"),
    "retrieval": ("embedding", "positives", "carveouts", "documents"),
}


def _load_routing(path: Path) -> dict:
    """`models.yaml`, checked for shape — a missing stage fails at import.

    Refusing early is the point: a stage that silently falls back to a
    default can drop a whole scoring tier (a primary decider that defaults
    to off whenever its setting is absent) without anything failing.
    """
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [f"{section}.{key}" for section, keys in _ROUTING_SHAPE.items()
               for key in keys if key not in (data.get(section) or {})]
    if missing:
        raise ValueError(f"{path.name} is missing {missing} — every stage must be named "
                         f"explicitly (use null to switch one off)")
    return data


_ROUTING = _load_routing(ROUTING_FILE)
_LLM = _ROUTING["llm"]
_RETRIEVAL = _ROUTING["retrieval"]

#: Every LLM op not given its own stage below.
LLM_RESOURCE_KEY = _LLM["default"]
#: l3's decider, the ASR check and l2's halu check.
DECIDER_LLM_RESOURCE_KEY = _LLM["filter_decider"]
#: l4's strict re-verify; "" when switched off.
PRIMARY_DECIDER_LLM_RESOURCE_KEY = _LLM["primary_decider"] or ""
#: l4's wording pass.
SOFTEN_LLM_RESOURCE_KEY = _LLM["soften"] or LLM_RESOURCE_KEY
#: The cheap LLM pre-filter; "" when switched off.
PREFILTER_LLM_RESOURCE_KEY = _LLM["prefilter"] or ""


# Traces — controls whether sentiment_agent output row includes a `traces`
# key with intermediate pipeline signal (scanner / retrieval / decider /
# primary / soften). Purely additive to the output, does NOT affect any
# pipeline decision. Boolean toggle:
#   on-tokens:  on / true / 1 / yes
#   off-tokens: off / false / 0 / no
INCLUDE_TRACES = env_bool("INCLUDE_TRACES", False)


def enabled_cases(env=None) -> frozenset[str]:
    """The case ids switched on: one `QC_ENABLE_<CASE_ID>` boolean each,
    default on, so a case added upstream never silently drops out.
    *env* is the mapping to read (`os.environ` when omitted)."""
    return frozenset(c for c in CASE_IDS if env_bool(f"QC_ENABLE_{c.upper()}", default=True, env=env))


# ---------------------------------------------------------------------------
# sentiment_agent pre-filter — LLM + keyword toggles + apply/shadow mode
# ---------------------------------------------------------------------------
#
# Three orthogonal knobs:
#   models.yaml `llm.prefilter`        — a resource → LLM filter on
#   SENTIMENT_FILTER_KEYWORD_ENABLE    — true/false → KW filter on
#   SENTIMENT_FILTER_APPLY             — true (default) = gate main flow;
#                                        false = shadow mode (filter runs but
#                                        never blocks; verdict rides on
#                                        `result["_trace_meta"]["filter"]`)
#
# The two toggles are read fresh per call so tests can flip them.

SENTIMENT_FILTER_KEYWORD_ENABLE_ENV = "SENTIMENT_FILTER_KEYWORD_ENABLE"
SENTIMENT_FILTER_APPLY_ENV = "SENTIMENT_FILTER_APPLY"

# The resource the pre-filter's LLMOp binds at graph-build time. operonx
# resolves it at engine start whether or not the op can fire, so when the
# pre-filter is off it binds the default model — already required, never
# called here (only `ROUTE_LLM_SCAN` reaches it, and only when
# `filter_llm_enabled()`). Binding a dedicated model instead made every pod
# need that model's env vars to start.
SENTIMENT_FILTER_LLM_RESOURCE_KEY = PREFILTER_LLM_RESOURCE_KEY or LLM_RESOURCE_KEY


def filter_llm_resource_key() -> str:
    """The pre-filter's resource from models.yaml; "" when switched off."""
    return PREFILTER_LLM_RESOURCE_KEY.strip()


def filter_llm_enabled() -> bool:
    """True iff models.yaml names a resource for the pre-filter."""
    return bool(filter_llm_resource_key())


def filter_keyword_enabled(env=None) -> bool:
    """True iff SENTIMENT_FILTER_KEYWORD_ENABLE is set to a truthy token."""
    return env_bool(SENTIMENT_FILTER_KEYWORD_ENABLE_ENV, env=env)


def filter_apply_enabled(env=None) -> bool:
    """True iff filter verdict gates the main flow. Default True.

    Shadow mode = set env to a false token; filter still runs but never
    short-circuits. Verdict rides on `result["_trace_meta"]["filter"]` for
    downstream eval.
    """
    return env_bool(SENTIMENT_FILTER_APPLY_ENV, default=True, env=env)


def any_filter_enabled() -> bool:
    """True iff either the LLM or keyword filter is enabled."""
    return filter_llm_enabled() or filter_keyword_enabled()


# ---------------------------------------------------------------------------
# Knowledge — QC-maintained data, and the index built from it
# ---------------------------------------------------------------------------
#
# `knowledge/<case>/` holds what QC edits (`corpus.yaml`, `keyword_filter.yaml`)
# plus artefacts derived from it (the gitignored `index/`). Kept out of `src/`
# on purpose: a QC edit to the corpus is a data change with its own index and
# freshness hash, and should not read as a code change in review. Every reader
# builds its path from this one constant.
KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"


# ---------------------------------------------------------------------------
# Corpus retrieval — resource keys
# ---------------------------------------------------------------------------
#
# Retrieval is four resources, named in `models.yaml` under `retrieval`.
#
# Remote only (pgvector + the Triton embedding endpoint). A local fallback
# would let a pod that never received its settings score every call
# without contacting Postgres or Triton, and nothing would fail.
# `require_remote_retrieval()` checks at startup what the four resources
# actually are, because a name can be pointed anywhere.

CORPUS_EMBEDDING = _RETRIEVAL["embedding"]
CORPUS_VECTOR_STORE_POS = _RETRIEVAL["positives"]
CORPUS_VECTOR_STORE_CVO = _RETRIEVAL["carveouts"]
CORPUS_DOC_STORE = _RETRIEVAL["documents"]

# Counts *variants*, not entries — several phrasings of one entry can occupy
# several slots, which is the behaviour the decider and the BU report were
# tuned against. A constant, not an env var: it changes which entries the deciders see,
# so it moves scores, and the selfcheck baseline was recorded at 10.
RETRIEVAL_TOP_K = 10



ENABLED_CASES: frozenset[str] = enabled_cases()
