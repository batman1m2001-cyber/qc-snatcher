"""How a run executes — every variable a job reads, read once, here.

The other homes: which model serves a stage is `models.yaml`; endpoints and
keys are `resources.yaml` (`${VAR}`); what is *scored* — `INCLUDE_TRACES`,
`QC_ENABLE_<CASE_ID>`, the pre-filter switches — is `src/core/config.py`;
how the process loads its env file and calls models is `src/core/_bootstrap.py`
(`QC_LOCAL_STACK`, `LLM_CALL_TIMEOUT_SECS`, `LLM_CALL_RETRIES`, `HUSH_USAGE_LOG`).

| variable | default | read by |
|---|---|---|
| `PIPELINE_INPUT_PATH` | `samples` | main: the folder of calls to score |
| `PIPELINE_FILES_LIST` | — | main: a file of input paths, one per line, instead of the folder |
| `PIPELINE_OUTPUT_PATH` | `outputs/qc` | main: one JSON per call |
| `PIPELINE_SKIP_IF_EXISTS` | `false` | main: skip a call whose output exists (an `{"error"}` file is scored again) |
| `PIPELINE_MAX_CONCURRENCY` | `2` | main: calls scored at once |
| `PIPELINE_TRACER_KIND` | `none` | main: `local` writes redacted op traces |
| `PIPELINE_TRACER_LOCAL_DIR` | `./traces` | main: op traces and stage files |
| `PIPELINE_SKIP_REACHABILITY` | `false` | preflight: skip the endpoint probe (offline replays only) |
| `CORPUS_SEED_WAIT_S` | `900` | ingest: how long a pod waits for another pod's seed |
| `PIPELINE_SELFCHECK_MATCH_THRESHOLD` | `0.85` | selfcheck: the pass rate that passes; `0` = warn only |
| `PIPELINE_SELFCHECK_CONCURRENCY` | `5` | selfcheck: calls scored at once |
| `S3_BUCKET`, `SENTIMENT_OUTPUT_S3_KEY` | — | deploy: where the selfcheck record goes; unset = no upload |
| `QC_BATCH` | — | qc_eval: the default batch folder (`--set batch=` wins) — QC's `.xlsx` and the transcripts (`src/jobs/qc_eval/README.md`) |
| `QC_CONCURRENCY` | `5` | qc_eval: calls scored at once |

Values flow from here as data — Job inputs and arguments; nothing writes
the environment or a module global at run time. Booleans and numbers use
one grammar (`src/core/env.py`): a typo raises, naming the variable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from src.core.env import env_bool, env_number, env_str


@dataclass(frozen=True)
class Settings:
    input_path: str = "samples"
    files_list: str = ""
    output_path: str = "outputs/qc"
    skip_if_exists: bool = False
    max_concurrency: int = 2
    tracer_kind: str = "none"
    tracer_local_dir: str = "./traces"
    skip_reachability: bool = False
    seed_wait_s: int = 900
    selfcheck_threshold: float = 0.85
    selfcheck_concurrency: int = 5
    s3_bucket: str = ""
    s3_prefix: str = ""
    qc_batch: str = ""
    qc_concurrency: int = 5

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        """Read from *env* (`os.environ` when omitted); a test passes a dict."""
        d = cls()
        return cls(
            input_path=env_str("PIPELINE_INPUT_PATH", d.input_path, env),
            files_list=env_str("PIPELINE_FILES_LIST", d.files_list, env),
            output_path=env_str("PIPELINE_OUTPUT_PATH", d.output_path, env),
            skip_if_exists=env_bool("PIPELINE_SKIP_IF_EXISTS", d.skip_if_exists, env),
            max_concurrency=env_number("PIPELINE_MAX_CONCURRENCY", d.max_concurrency, env),
            tracer_kind=env_str("PIPELINE_TRACER_KIND", d.tracer_kind, env),
            tracer_local_dir=env_str("PIPELINE_TRACER_LOCAL_DIR", d.tracer_local_dir, env),
            skip_reachability=env_bool("PIPELINE_SKIP_REACHABILITY", d.skip_reachability, env),
            seed_wait_s=max(1, env_number("CORPUS_SEED_WAIT_S", d.seed_wait_s, env)),
            selfcheck_threshold=env_number("PIPELINE_SELFCHECK_MATCH_THRESHOLD", d.selfcheck_threshold, env),
            selfcheck_concurrency=env_number("PIPELINE_SELFCHECK_CONCURRENCY", d.selfcheck_concurrency, env),
            s3_bucket=env_str("S3_BUCKET", d.s3_bucket, env),
            s3_prefix=env_str("SENTIMENT_OUTPUT_S3_KEY", d.s3_prefix, env),
            qc_batch=env_str("QC_BATCH", d.qc_batch, env),
            qc_concurrency=env_number("QC_CONCURRENCY", d.qc_concurrency, env),
        )
