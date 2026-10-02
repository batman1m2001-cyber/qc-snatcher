"""Configuration: every run knob is read once (`app/settings.py`), every
boolean and number has one grammar (`src/core/env.py`), and the settings
reach the jobs as data. Tests pass a dict — none sets the process env."""
from __future__ import annotations

import pytest

from app.settings import Settings
from src.core import config
from src.core.env import env_bool, env_number, env_str

POD = {  # what MLE's settings.py writes into the pod's .env
    "PIPELINE_INPUT_PATH": "/data/in", "PIPELINE_OUTPUT_PATH": "/data/out",
    "PIPELINE_SKIP_IF_EXISTS": "False", "PIPELINE_TRACER_KIND": "none",
    "PIPELINE_TRACER_LOCAL_DIR": "./traces", "PIPELINE_MAX_CONCURRENCY": "5",
    "PIPELINE_SELFCHECK_MATCH_THRESHOLD": "0.85", "PIPELINE_SELFCHECK_CONCURRENCY": "5",
    "PIPELINE_SELFCHECK_N": "90", "PIPELINE_SELFCHECK_STRICT": "true",  # read by nobody now
}


def test_the_defaults():
    assert Settings.from_env({}) == Settings(
        input_path="samples", files_list="", output_path="outputs/qc", skip_if_exists=False,
        max_concurrency=2, tracer_kind="none", tracer_local_dir="./traces", skip_reachability=False,
        seed_wait_s=900, selfcheck_threshold=0.85, selfcheck_concurrency=5, s3_bucket="", s3_prefix="",
        qc_batch="", qc_concurrency=5)


def test_what_the_pods_set_is_read():
    s = Settings.from_env(POD)
    assert (s.input_path, s.output_path, s.max_concurrency, s.skip_if_exists) == ("/data/in", "/data/out", 5, False)


def test_blank_is_the_default():
    assert Settings.from_env(dict.fromkeys(POD, "")) == Settings()


@pytest.mark.parametrize("raw, expected", [("60", 60), ("0", 1), ("-5", 1), ("", 900)])
def test_the_seed_wait_is_at_least_a_second(raw, expected):
    assert Settings.from_env({"CORPUS_SEED_WAIT_S": raw}).seed_wait_s == expected


@pytest.mark.parametrize("name, raw", [
    ("PIPELINE_SKIP_IF_EXISTS", "sometimes"), ("PIPELINE_MAX_CONCURRENCY", "five"),
    ("CORPUS_SEED_WAIT_S", "soon"), ("PIPELINE_SELFCHECK_MATCH_THRESHOLD", "high"),
])
def test_a_typo_raises_naming_the_variable(name, raw):
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: raw})


# ── the readers ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw, expected", [
    ("1", True), ("true", True), ("TRUE", True), ("Yes", True), (" on ", True),
    ("0", False), ("false", False), ("no", False), ("off", False),
])
def test_env_bool_tokens(raw, expected):
    assert env_bool("X", not expected, {"X": raw}) is expected


def test_env_bool_blank_or_unset_is_the_default():
    assert env_bool("X", True, {}) is True and env_bool("X", True, {"X": "  "}) is True


def test_hush_usage_log_false_is_off():
    """It was `!= "0"`, so `false` turned the log on."""
    assert env_bool("HUSH_USAGE_LOG", False, {"HUSH_USAGE_LOG": "false"}) is False


def test_env_number_keeps_the_defaults_type():
    assert env_number("X", 2, {"X": "7"}) == 7 and isinstance(env_number("X", 2, {"X": "7"}), int)
    assert env_number("X", 0.5, {"X": "1"}) == 1.0 and isinstance(env_number("X", 0.5, {"X": "1"}), float)
    assert env_number("X", 3, {}) == 3


def test_env_str_strips_and_defaults():
    assert env_str("X", "d", {"X": "  v "}) == "v" and env_str("X", "d", {"X": ""}) == "d"


# ── what is scored: src/core/config.py ──────────────────────────────────


def test_every_case_is_on_by_default():
    assert config.enabled_cases({}) == frozenset(config.CASE_IDS)


def test_a_case_switched_off():
    assert config.enabled_cases({"QC_ENABLE_HANGUP": "false"}) == frozenset(c for c in config.CASE_IDS if c != "hangup")


def test_a_bad_case_switch_raises():
    with pytest.raises(ValueError, match="QC_ENABLE_HANGUP"):
        config.enabled_cases({"QC_ENABLE_HANGUP": "flase"})


def test_the_pinned_test_env_names_every_case():
    from tests._env import CASES

    assert set(CASES) == set(config.CASE_IDS)


# ── settings reach the jobs as data ─────────────────────────────────────


def test_the_jobs_take_their_knobs_from_settings():
    from app.main import SETTINGS, ingest, preflight, score, selfcheck_score

    assert preflight.inputs["skip_reachability"] is SETTINGS.skip_reachability
    assert ingest.inputs["seed_wait_s"] == SETTINGS.seed_wait_s
    assert score.concurrency == SETTINGS.max_concurrency
    assert selfcheck_score.threshold == SETTINGS.selfcheck_threshold


def test_nothing_writes_a_config_global_or_the_environment():
    """Settings flow as data. A write at run time leaks into every run
    after it in the process — the old selfcheck turned traces on this way."""
    import ast
    
    from tests._paths import ROOT as root
    hits = []
    for path in [*root.joinpath("src").rglob("*.py"), *root.joinpath("app").rglob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            targets = node.targets if isinstance(node, ast.Assign) else []
            for t in targets:
                text = ast.unparse(t)
                if text.startswith(("config.", "cfg.", "os.environ[")):
                    hits.append(f"{path.relative_to(root)}:{node.lineno} {text}")
    assert hits == [], hits
