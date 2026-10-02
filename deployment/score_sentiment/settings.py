import os
import boto3
import json
from dotenv import set_key
from botocore.exceptions import ClientError

def get_secret(secretId):
    region_name = "ap-southeast-1"

    # Create a Secrets Manager client
    session = boto3.session.Session()
    client = session.client(service_name="secretsmanager", region_name=region_name)
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secretId)
    except ClientError as e:
        raise e

    secret = get_secret_value_response["SecretString"]
    return secret

S3_BUCKET = os.getenv("S3_BUCKET")
S3_METADATA_KEY = os.getenv("S3_METADATA_KEY", None)
S3_SENTIMENT_OUTPUT_KEY = os.getenv("SENTIMENT_OUTPUT_S3_KEY", None)
SECRET_ID = os.getenv("SECRET_ID")
NO_WORKERS = int(os.getenv("NO_WORKERS", 1))
WORKER_ID = int(os.getenv("WORKER_ID", 1))
DATA_DATE = os.getenv("DATA_DATE")

secrets = json.loads(get_secret(SECRET_ID))

# Which model serves each pipeline stage is NOT set here: `models.yaml` in the
# repo is the only source, and no environment variable overrides it. This file
# supplies credentials, endpoints and toggles.

LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING")

# Traces in sentiment_agent output rows: on | off (boolean toggle).
INCLUDE_TRACES = os.getenv("INCLUDE_TRACES", "on")

# =============================================================================
# Databricks (every routed LLM)
# =============================================================================

DATABRICKS_HOST = os.getenv("DATABRICKS_HOST", None)
DATABRICKS_CLIENT_ID = secrets["databricks_client_id"]
DATABRICKS_CLIENT_SECRET = secrets["databricks_client_secret"]

# =============================================================================
# Corpus retrieval — Triton embedding endpoint + Postgres/pgvector
# =============================================================================
#
# Postgres has to be *seeded*, not merely reachable:
#   psql "$PG_DSN" -f scripts/rag/sql/schema.sql
#   uv run python -m scripts.rag --dsn "$PG_DSN"
#
# PG_DSN carries a password, so it comes from Secrets Manager.
TRITON_EMBEDDING_URL = os.getenv("TRITON_EMBEDDING_URL", "aic-ds2-collector-assistant-embedding.aws.coreai.win.dev:443")
TRITON_EMBEDDING_SSL = os.getenv("TRITON_EMBEDDING_SSL", "true")
PG_DSN = secrets.get("pg_dsn")

# Only needed if `llm.prefilter` in models.yaml routes to `e4b-local`.
E4B_LOCAL_BASE_URL = os.getenv("E4B_LOCAL_BASE_URL", None)

# =============================================================================
# Pipeline
# =============================================================================

PIPELINE_INPUT_PATH = os.getenv("PIPELINE_INPUT_PATH", "samples")
PIPELINE_OUTPUT_PATH = os.getenv("PIPELINE_OUTPUT_PATH", "outputs/sentiment")
PIPELINE_SKIP_IF_EXISTS = os.getenv("PIPELINE_SKIP_IF_EXISTS", "False")
PIPELINE_TRACER_KIND = os.getenv("PIPELINE_TRACER_KIND", "none")
PIPELINE_TRACER_LOCAL_DIR = os.getenv("PIPELINE_TRACER_LOCAL_DIR", "./traces")
PIPELINE_MAX_CONCURRENCY = int(os.getenv("PIPELINE_MAX_CONCURRENCY", 5))

# Selfcheck — read by scripts/selfcheck/run.py, which runs before the pods.
PIPELINE_SELFCHECK_N = int(os.getenv("PIPELINE_SELFCHECK_N", 90))
PIPELINE_SELFCHECK_MATCH_THRESHOLD = float(os.getenv("PIPELINE_SELFCHECK_MATCH_THRESHOLD", 0.85))
PIPELINE_SELFCHECK_CONCURRENCY = int(os.getenv("PIPELINE_SELFCHECK_CONCURRENCY", 5))
PIPELINE_SELFCHECK_STRICT = os.getenv("PIPELINE_SELFCHECK_STRICT", "true")

# QC criteria toggles — flip to false to skip a case for this run.
QC_ENABLE_HANGUP = os.getenv("QC_ENABLE_HANGUP", "false").lower() == "true"
QC_ENABLE_RABA = os.getenv("QC_ENABLE_RABA", "false").lower() == "true"
QC_ENABLE_DISCLOSURE = os.getenv("QC_ENABLE_DISCLOSURE", "false").lower() == "true"
QC_ENABLE_CARD_NUMBER = os.getenv("QC_ENABLE_CARD_NUMBER", "false").lower() == "true"
QC_ENABLE_PHONE_SOURCE = os.getenv("QC_ENABLE_PHONE_SOURCE", "false").lower() == "true"
QC_ENABLE_SENTIMENT_AGENT = os.getenv("QC_ENABLE_SENTIMENT_AGENT", "true").lower() == "true"
QC_ENABLE_SENTIMENT_CUSTOMER = os.getenv("QC_ENABLE_SENTIMENT_CUSTOMER", "false").lower() == "true"

set_key(".env", "LOG_LEVEL", LOG_LEVEL)
set_key(".env", "INCLUDE_TRACES", INCLUDE_TRACES)

if DATABRICKS_HOST:
    set_key(".env", "DATABRICKS_HOST", DATABRICKS_HOST)
set_key(".env", "DATABRICKS_CLIENT_ID", DATABRICKS_CLIENT_ID)
set_key(".env", "DATABRICKS_CLIENT_SECRET", DATABRICKS_CLIENT_SECRET)

if TRITON_EMBEDDING_URL:
    set_key(".env", "TRITON_EMBEDDING_URL", TRITON_EMBEDDING_URL)
set_key(".env", "TRITON_EMBEDDING_SSL", TRITON_EMBEDDING_SSL)
if PG_DSN:
    set_key(".env", "PG_DSN", PG_DSN)
if E4B_LOCAL_BASE_URL:
    set_key(".env", "E4B_LOCAL_BASE_URL", E4B_LOCAL_BASE_URL)

set_key(".env", "QC_ENABLE_HANGUP", str(QC_ENABLE_HANGUP))
set_key(".env", "QC_ENABLE_RABA", str(QC_ENABLE_RABA))
set_key(".env", "QC_ENABLE_DISCLOSURE", str(QC_ENABLE_DISCLOSURE))
set_key(".env", "QC_ENABLE_CARD_NUMBER", str(QC_ENABLE_CARD_NUMBER))
set_key(".env", "QC_ENABLE_PHONE_SOURCE", str(QC_ENABLE_PHONE_SOURCE))
set_key(".env", "QC_ENABLE_SENTIMENT_AGENT", str(QC_ENABLE_SENTIMENT_AGENT))
set_key(".env", "QC_ENABLE_SENTIMENT_CUSTOMER", str(QC_ENABLE_SENTIMENT_CUSTOMER))

# --- pipeline knobs read by main.py ---
set_key(".env", "PIPELINE_INPUT_PATH", PIPELINE_INPUT_PATH)
set_key(".env", "PIPELINE_OUTPUT_PATH", PIPELINE_OUTPUT_PATH)
set_key(".env", "PIPELINE_SKIP_IF_EXISTS", str(PIPELINE_SKIP_IF_EXISTS))
set_key(".env", "PIPELINE_TRACER_KIND", PIPELINE_TRACER_KIND)
set_key(".env", "PIPELINE_TRACER_LOCAL_DIR", PIPELINE_TRACER_LOCAL_DIR)
set_key(".env", "PIPELINE_MAX_CONCURRENCY", str(PIPELINE_MAX_CONCURRENCY))

# --- selfcheck knobs read by scripts/selfcheck/run.py ---
set_key(".env", "PIPELINE_SELFCHECK_N", str(PIPELINE_SELFCHECK_N))
set_key(".env", "PIPELINE_SELFCHECK_MATCH_THRESHOLD", str(PIPELINE_SELFCHECK_MATCH_THRESHOLD))
set_key(".env", "PIPELINE_SELFCHECK_CONCURRENCY", str(PIPELINE_SELFCHECK_CONCURRENCY))
set_key(".env", "PIPELINE_SELFCHECK_STRICT", PIPELINE_SELFCHECK_STRICT)
