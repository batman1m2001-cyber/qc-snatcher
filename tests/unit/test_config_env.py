"""Unit tests for `src.config` env-driven filter helpers.

These are the runtime-per-call functions (`filter_llm_enabled`,
`filter_keyword_enabled`, `filter_apply_enabled`, `any_filter_enabled`,
`filter_llm_resource_key`) that gate the sentiment_agent v4 pre-filter.

Import-time state (`INCLUDE_TRACES`, `ENABLED_CASES`, resource-key
fallback chain) is covered by `test_enabled_cases.py` — this file only
touches the runtime helpers where env is read fresh per call.
"""
from __future__ import annotations


import pytest

from src.core import config as cfg


# ---------------------------------------------------------------------------
# filter_llm_enabled / filter_llm_resource_key
# ---------------------------------------------------------------------------


class TestFilterLlmEnabled:
    """The pre-filter is on iff models.yaml names a resource for it.

    Read from the module constant at call time, so a test points it
    elsewhere with `setattr` — the environment no longer has a say.
    """

    @pytest.mark.parametrize("value", ["", "   "])
    def test_blank_is_off(self, monkeypatch, value):
        monkeypatch.setattr(cfg, "PREFILTER_LLM_RESOURCE_KEY", value)
        assert cfg.filter_llm_enabled() is False
        assert cfg.filter_llm_resource_key() == ""

    def test_named_is_on(self, monkeypatch):
        monkeypatch.setattr(cfg, "PREFILTER_LLM_RESOURCE_KEY", "e4b-local")
        assert cfg.filter_llm_enabled() is True
        assert cfg.filter_llm_resource_key() == "e4b-local"

    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setattr(cfg, "PREFILTER_LLM_RESOURCE_KEY", "  e4b-local  ")
        assert cfg.filter_llm_resource_key() == "e4b-local"


# ---------------------------------------------------------------------------
# filter_keyword_enabled
# ---------------------------------------------------------------------------


class TestFilterKeywordEnabled:
    def test_unset(self, monkeypatch):
        monkeypatch.delenv(cfg.SENTIMENT_FILTER_KEYWORD_ENABLE_ENV, raising=False)
        assert cfg.filter_keyword_enabled() is False

    @pytest.mark.parametrize("token", ["", "false", "no", "off", "0"])
    def test_falsy(self, monkeypatch, token):
        monkeypatch.setenv(cfg.SENTIMENT_FILTER_KEYWORD_ENABLE_ENV, token)
        assert cfg.filter_keyword_enabled() is False

    def test_an_unrecognised_token_raises(self, monkeypatch):
        """One grammar for every boolean (`src/core/env.py`): a typo is an
        error, never quietly false."""
        monkeypatch.setenv(cfg.SENTIMENT_FILTER_KEYWORD_ENABLE_ENV, "banana")
        with pytest.raises(ValueError, match="is not a boolean"):
            cfg.filter_keyword_enabled()

    @pytest.mark.parametrize("token", ["1", "true", "TRUE", "Yes", "on", "  true  "])
    def test_truthy(self, monkeypatch, token):
        monkeypatch.setenv(cfg.SENTIMENT_FILTER_KEYWORD_ENABLE_ENV, token)
        assert cfg.filter_keyword_enabled() is True


# ---------------------------------------------------------------------------
# filter_apply_enabled — default True (gate) vs shadow
# ---------------------------------------------------------------------------


class TestFilterApplyEnabled:
    def test_unset_defaults_true(self, monkeypatch):
        """Default is gate mode. Shadow mode must be an explicit opt-out."""
        monkeypatch.delenv(cfg.SENTIMENT_FILTER_APPLY_ENV, raising=False)
        assert cfg.filter_apply_enabled() is True

    def test_blank_defaults_true(self, monkeypatch):
        monkeypatch.setenv(cfg.SENTIMENT_FILTER_APPLY_ENV, "")
        assert cfg.filter_apply_enabled() is True

    @pytest.mark.parametrize("token", ["false", "False", "off", "no", "0"])
    def test_false_tokens_enable_shadow(self, monkeypatch, token):
        monkeypatch.setenv(cfg.SENTIMENT_FILTER_APPLY_ENV, token)
        assert cfg.filter_apply_enabled() is False

    @pytest.mark.parametrize("token", ["true", "1", "on", "yes"])
    def test_true_tokens(self, monkeypatch, token):
        monkeypatch.setenv(cfg.SENTIMENT_FILTER_APPLY_ENV, token)
        assert cfg.filter_apply_enabled() is True

    def test_typo_raises(self, monkeypatch):
        """Typo must fail loudly — silent default would mask operator error."""
        monkeypatch.setenv(cfg.SENTIMENT_FILTER_APPLY_ENV, "flase")
        with pytest.raises(ValueError):
            cfg.filter_apply_enabled()


# ---------------------------------------------------------------------------
# any_filter_enabled — logical OR of llm + keyword
# ---------------------------------------------------------------------------


class TestAnyFilterEnabled:
    def _clear(self, monkeypatch):
        monkeypatch.setattr(cfg, "PREFILTER_LLM_RESOURCE_KEY", "")
        monkeypatch.delenv(cfg.SENTIMENT_FILTER_KEYWORD_ENABLE_ENV, raising=False)

    def test_both_off(self, monkeypatch):
        self._clear(monkeypatch)
        assert cfg.any_filter_enabled() is False

    def test_llm_only(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setattr(cfg, "PREFILTER_LLM_RESOURCE_KEY", "e4b-local")
        assert cfg.any_filter_enabled() is True

    def test_kw_only(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setenv(cfg.SENTIMENT_FILTER_KEYWORD_ENABLE_ENV, "true")
        assert cfg.any_filter_enabled() is True

    def test_both(self, monkeypatch):
        self._clear(monkeypatch)
        monkeypatch.setattr(cfg, "PREFILTER_LLM_RESOURCE_KEY", "e4b-local")
        monkeypatch.setenv(cfg.SENTIMENT_FILTER_KEYWORD_ENABLE_ENV, "true")
        assert cfg.any_filter_enabled() is True


# ---------------------------------------------------------------------------
# INCLUDE_TRACES import-time validation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Stage routing comes from models.yaml, and only from there
# ---------------------------------------------------------------------------


class TestRoutingComesFromModelsYaml:
    """Which resource serves each stage is models.yaml's decision alone.

    It used to be environment variables with fallbacks — and MLE's
    deployment wrote one of them into every pod's `.env` while computing
    three others it never wrote, so production could run a routing nobody
    had tested, with the primary decider silently off.
    """

    def _file(self):
        import yaml

        return yaml.safe_load(cfg.ROUTING_FILE.read_text(encoding="utf-8"))

    def test_each_stage_is_the_file_value(self):
        llm, ret = self._file()["llm"], self._file()["retrieval"]
        assert cfg.LLM_RESOURCE_KEY == llm["default"]
        assert cfg.DECIDER_LLM_RESOURCE_KEY == llm["filter_decider"]
        assert cfg.PRIMARY_DECIDER_LLM_RESOURCE_KEY == (llm["primary_decider"] or "")
        assert cfg.SOFTEN_LLM_RESOURCE_KEY == (llm["soften"] or llm["default"])
        assert cfg.PREFILTER_LLM_RESOURCE_KEY == (llm["prefilter"] or "")
        assert (cfg.CORPUS_EMBEDDING, cfg.CORPUS_VECTOR_STORE_POS,
                cfg.CORPUS_VECTOR_STORE_CVO, cfg.CORPUS_DOC_STORE) == (
            ret["embedding"], ret["positives"], ret["carveouts"], ret["documents"])

    def test_the_environment_cannot_override_it(self, monkeypatch):
        for name in ("LLM_RESOURCE_KEY", "DECIDER_LLM_RESOURCE_KEY",
                     "SECONDARY_DECIDER_LLM_RESOURCE_KEY", "PRIMARY_DECIDER_LLM_RESOURCE_KEY",
                     "SOFTEN_LLM_RESOURCE_KEY", "SENTIMENT_FILTER_LLM_RESOURCE_KEY",
                     "CORPUS_VECTOR_STORE_POS", "CORPUS_DOC_STORE"):
            monkeypatch.setenv(name, "set-in-the-environment")
        assert "set-in-the-environment" not in repr(cfg._load_routing(cfg.ROUTING_FILE))

    def test_a_missing_stage_refuses_at_import(self, tmp_path):
        f = tmp_path / "models.yaml"
        f.write_text("llm:\n  default: x\nretrieval: {}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="filter_decider"):
            cfg._load_routing(f)

    def test_every_routed_resource_exists(self):
        """A name here that `resources.yaml` does not define fails at the
        first call that resolves it — mid-batch. Catch it offline."""
        import yaml

        defined = set(yaml.safe_load((cfg.ROUTING_FILE.parent / "resources.yaml")
                                     .read_text(encoding="utf-8")))
        data = self._file()
        wanted = {f"llm:{v}" for v in data["llm"].values() if v}
        ret = data["retrieval"]
        wanted |= {f"embedding:{ret['embedding']}", f"vector_store:{ret['positives']}",
                   f"vector_store:{ret['carveouts']}", f"doc_store:{ret['documents']}"}
        assert wanted - defined == set(), f"not in resources.yaml: {sorted(wanted - defined)}"


#: Environment names that used to route stages or change how a call is
#: scored. Reading any of them again would reopen the drift models.yaml
#: exists to close: a pod scoring differently from the reviewed config.
_ROUTING_ENV_NAMES = frozenset({
    "RETRIEVAL_TOP_K", "RETRIEVAL_QUERY_FROM_EVIDENCE",
    "LLM_RESOURCE_KEY", "VERIFIER_LLM_RESOURCE_KEY", "DECIDER_LLM_RESOURCE_KEY",
    "SECONDARY_DECIDER_LLM_RESOURCE_KEY", "PRIMARY_DECIDER_LLM_RESOURCE_KEY",
    "SOFTEN_LLM_RESOURCE_KEY", "SENTIMENT_FILTER_LLM_RESOURCE_KEY",
    "CORPUS_EMBEDDING_RESOURCE", "CORPUS_VECTOR_STORE_POS", "CORPUS_VECTOR_STORE_CVO",
    "CORPUS_DOC_STORE",
})


def _env_reads(path):
    """String literals passed to `os.environ.get/[]`, `os.getenv` in *path*."""
    import ast

    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        arg = None
        if isinstance(node, ast.Call) and node.args:
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            owner = ast.unparse(f.value) if isinstance(f, ast.Attribute) else ""
            if (name == "get" and owner.endswith("environ")) or name == "getenv":
                arg = node.args[0]
        elif isinstance(node, ast.Subscript) and ast.unparse(node.value).endswith("environ"):
            arg = node.slice
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            found.append((arg.value, node.lineno))
    return found


def test_no_code_reads_stage_routing_from_the_environment():
    root = cfg.ROUTING_FILE.parent
    files = [*(root / "src").rglob("*.py"), *(root / "scripts").rglob("*.py"),
             *(root / "deployment").rglob("*.py"), root / "main.py"]
    hits = [
        f"{p.relative_to(root)}:{line} {name}"
        for p in files if "_archive" not in p.parts and "__pycache__" not in p.parts
        for name, line in _env_reads(p) if name in _ROUTING_ENV_NAMES
    ]
    assert hits == [], (
        "stage routing read from the environment — it belongs to models.yaml, "
        f"through src.core.config: {hits}"
    )


def test_deployment_writes_no_routing_name_into_the_pod_env():
    """`settings.py` writes the pod's `.env`. It wrote LLM_RESOURCE_KEY,
    SECONDARY_DECIDER_LLM_RESOURCE_KEY and the CORPUS_* names long after
    nothing read them — they made the pod look routed by env when
    models.yaml decides."""
    import ast

    root = cfg.ROUTING_FILE.parent
    written = []
    for p in (root / "deployment").rglob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "set_key"
                    and len(node.args) > 1 and isinstance(node.args[1], ast.Constant)):
                written.append((p.relative_to(root), node.lineno, node.args[1].value))
    hits = [f"{p}:{line} {name}" for p, line, name in written if name in _ROUTING_ENV_NAMES]
    assert hits == [], f"routing names written into the pod env: {hits}"
