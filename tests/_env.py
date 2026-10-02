"""The environment every offline test runs in — pinned before `src` is imported.

`src` loads `local.env` / `.env` when it is imported (`_bootstrap`), and a
variable already set wins. Pinning every switch here first means no test
reads a developer's settings: the scoring switches are the ones the recorded
fixtures were scored with (only sentiment_agent on, traces on), and every
run knob is blank — its default in `app/settings.py`.

The variables `resources.yaml` references are pinned too, to placeholders.
Building a graph resolves them, so without a value the suite needs a `.env`
— which CI has not got; and no test should see a real secret or endpoint.
Resolving `api_key: oauth2:databricks` also *fetches a token* on the spot,
so every token provider hands out a fixed one instead: without that, each
run of the "offline" suite called Databricks. A test that dials out anyway
fails fast on `.invalid`.

Nothing here may import `src`: that would load the env file first.
"""
import os

#: The case ids, spelled out — `tests/contract/test_settings.py` checks they match `CASE_IDS`.
CASES = ("hangup", "raba", "disclosure", "card_number", "phone_source", "sentiment_agent", "sentiment_customer")

PINNED = {
    "INCLUDE_TRACES": "on",
    **{f"QC_ENABLE_{c.upper()}": "true" if c == "sentiment_agent" else "false" for c in CASES},
    **dict.fromkeys((
        "SENTIMENT_FILTER_KEYWORD_ENABLE", "SENTIMENT_FILTER_APPLY",
        "PIPELINE_INPUT_PATH", "PIPELINE_FILES_LIST", "PIPELINE_OUTPUT_PATH", "PIPELINE_SKIP_IF_EXISTS",
        "PIPELINE_MAX_CONCURRENCY", "PIPELINE_TRACER_KIND", "PIPELINE_TRACER_LOCAL_DIR",
        "PIPELINE_SKIP_REACHABILITY", "CORPUS_SEED_WAIT_S",
        "PIPELINE_SELFCHECK_MATCH_THRESHOLD", "PIPELINE_SELFCHECK_CONCURRENCY",
        "S3_BUCKET", "SENTIMENT_OUTPUT_S3_KEY", "QC_BATCH", "QC_CONCURRENCY",
        "HUSH_USAGE_LOG", "LLM_CALL_TIMEOUT_SECS", "LLM_CALL_RETRIES",
    ), ""),
    # resources.yaml — see above; tests/repo/test_tests_layout.py checks the list
    "DATABRICKS_HOST": "https://databricks.offline.invalid",
    "DATABRICKS_CLIENT_ID": "offline",
    "DATABRICKS_CLIENT_SECRET": "offline",
    "E4B_LOCAL_BASE_URL": "http://e4b.offline.invalid/v1",
    "PG_DSN": "postgresql://offline.invalid/none",
    "TRITON_EMBEDDING_URL": "triton.offline.invalid:443",
}


def pin() -> None:
    os.environ.update(PINNED)
    from operonx.providers.auth.keycloak import KeycloakTokenProvider
    from operonx.providers.auth.oauth2 import OAuth2TokenProvider

    for provider in (OAuth2TokenProvider, KeycloakTokenProvider):
        provider.get_token = lambda self: "offline-token"
