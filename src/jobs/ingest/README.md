# ingest

The corpus store in Postgres + pgvector: create its tables once, then keep
it holding the `corpus.yaml` on disk.

## ingest — the store holds this corpus, or the run fails naming the fix.

```
    operonx-run ingest                               # check: exit 1 when the store is stale
    operonx-run ingest --set seed=true               # seed an empty or stale store (python main.py --ingest)
    operonx-run ingest --set reseed=true             # re-embed whatever the state; repairs `multi`
    operonx-run ingest --set seed=true --set dry_run=true   # what it would write, and nothing else
    operonx-run ingest --set reseed=true --set prune=false  # keep rows the corpus no longer has

    read_store ──▶ seed_store ──▶ verify

read_store   the distinct `batch_id`s the rows carry against the corpus sha:
             ok · empty · mismatch · multi
seed_store   ok → nothing. empty / mismatch → seed when `seed`, else fail.
             multi → only `reseed`. A seed takes the advisory lock (waits up
             to CORPUS_SEED_WAIT_S, default 900), re-checks — N-1 of N pods
             find it done — then writes in one transaction: prune refused
             above 50% of the table unless `force_prune`; the partner's
             knowledge_info rows are never deleted
verify       after a write, the rows were embedded by the embedder configured now

Runs as the `main` job (steps)'s second step (seed=false unless --ingest) and
in `selfcheck`, the deploy gate (seed=true). Writes to the store the pipeline reads
(`retrieval.positives` in models.yaml, DSN from PG_DSN).

Needs : VPN — the Triton embedder and Postgres.
Cost  : nothing unless it seeds; a seed is one embedding call per 8 variants, no LLM.
```


## create_schema — create the corpus tables in Postgres, once.

```
    operonx-run create_schema                              # apply schema.sql when the tables are absent
    operonx-run create_schema --set dry_run=true           # say what it would do
    operonx-run create_schema --set dsn=postgresql://...   # another database than PG_DSN

Applies `schema.sql` — MLE's DDL (PART 1) plus our constraints and views
(PART 2) — in one transaction, and only when the four tables are absent; a
second run is a no-op. It creates, it does not migrate.

Needs : Postgres with DDL privilege (the DSN from PG_DSN unless `dsn` is set).
Cost  : none.
```
