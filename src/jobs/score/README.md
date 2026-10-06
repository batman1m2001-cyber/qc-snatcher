# score — run the scoring graph over a folder of calls, one JSON out per call.

```
    python main.py                     # the `main` job (steps): preflight ▶ ingest ▶ this ▶ report
    operonx-run main --resume          # only the calls the last score run did not finish

Configured by PIPELINE_INPUT_PATH (or PIPELINE_FILES_LIST, a file of paths,
one per line), PIPELINE_OUTPUT_PATH, PIPELINE_MAX_CONCURRENCY,
PIPELINE_SKIP_IF_EXISTS, PIPELINE_TRACER_KIND / _LOCAL_DIR (`app/_score.py`).
A failed call is recorded, not fatal: it gets its file and the batch goes on.

Input : a folder of ASR ``*.json`` files, each with ``metadata.call_code``
        (files without one are skipped with a warning).
Output: ``<output>/<stem>.json`` per call — the ``call_scoring`` row, or
        ``{"error": ...}`` when the call failed; the stage block goes to
        ``<trace dir>/<stem>_<id>.json`` when INCLUDE_TRACES is on.
Needs : VPN — Databricks LLMs, the Triton embedder, Postgres.
Cost  : one set of LLM calls per call scored.
```
