---
name: corpus-update
description: Change the sentiment_agent retrieval corpus — import QC's xlsx into corpus.yaml, write entry descriptions to QC's conventions, rebuild the index, and know what the change forces downstream. Use when editing knowledge/sentiment_agent/corpus.yaml or acting on QC feedback about violation wording.
---

# Updating the corpus

`knowledge/sentiment_agent/corpus.yaml` is what QC maintains and what the
decider cites. The scanner supplies recall; the corpus supplies precision.

**Coverage expectation: the corpus should cover ~99% of cases.** When a false
positive survives, the cause is a corpus policy or a prompt bug — never
"the corpus can't express this". Find the entry that should have matched.

## Importing QC's xlsx

```powershell
uv run python -m tools.corpus_import --dry-run     # what would change
uv run python -m tools.corpus_import               # write corpus.yaml
```

Defaults: xlsx at the repo parent, corpus at `knowledge/sentiment_agent/`,
backup to `corpus.pre-qc-import.yaml`, unresolved rows to
`qc_import_review.tsv`.

The xlsx is **source of truth**. If QC removed an entry it is gone — do not
reinstate it because it looked useful.

Traps:

- **Check the backup target is not already occupied.** A stale
  `corpus.yaml.bak` from before id-stamping exists and is gitignored; a
  `not BACKUP.exists()` guard silently skips the copy, and using a
  pre-stamping file as the id reference re-stamps every entry.
- **Id recovery must be conservative.** Matching short strings lets a
  fragment like `"ừ"` claim many entries; `MIN_RECOVERY_CHARS` guards this.
  Two QC rows claiming one id means one gets dropped.
- **Resolve `qc_import_review.tsv` before shipping**, then re-run the import.

## Writing `description`

These are the conventions that get violated most often:

| rule | why |
|---|---|
| Paraphrase QC's comment **only** | never invent a discriminator QC did not state |
| One sample per entry | never lump patterns as `(a)(b)(c)` in one description |
| Short — roughly ≤ 2 sentences, enough meaning without padding | |
| Separate variants with ` \| `, never `/` | `/` collides with inline `anh/chị` |
| No external references | `C1..C12`, N-codes, "step19 carveout" mean nothing to the model |

If two QC comments conflict, **ask** — do not reconcile them yourself.

Each entry carries `severity` (`warning` / `cao` / `nghiem_trong`) alongside
`content` and `description`. Severity now decides the score: the primary
decider resolves the cited entry's severity and it outranks the scanner's
category. `warning` reports a distinct `Result` at offset 0. Changing an
entry's severity therefore changes scoring, not just retrieval.

## After editing — re-seed the store

The corpus and its vectors are separate artefacts. Edit the yaml and the
store still answers from the old text: entries added since the seed are
unreachable, and entries whose text moved return a vector for one phrasing
while the pool displays another.

```powershell
uv run python -m tools.corpus_stamp_ids --apply        # new entries get ids
uv run operonx-run ingest --set seed=true              # embed and write, then verify
uv run operonx-run ingest                              # the store now matches the corpus
```

`ingest --set seed=true` repairs an empty or stale store; a store holding
two corpora at once (`multi`) needs `--set reseed=true`, which also prunes.
(`operonx-run create_schema` creates the tables, once per database.) It
embeds every variant through Triton, so it needs the VPN — hand the command
over rather than running it.

`main.py` and `main.py --selfcheck` both run the `ingest` job before
scoring, which checks the store's corpus hash. Where seeding is allowed
(`python main.py --selfcheck`, `python main.py --ingest`) it takes an advisory
lock so exactly one pod seeds and the rest find the work done
(`src/jobs/ingest/_store.py`). Without `seed`, a stale store fails the run
naming the fix rather than being repaired underneath a running pod.

A FAISS index step used to sit here, and `CORPUS_AUTO_REINDEX` with it.
Both are gone — there is one store, it is shared, and a pod must not
rebuild a shared store on startup.

The freshness hash is over `read_text().encode()`, not `read_bytes()` — hashing
raw bytes makes every CRLF checkout look modified.

## What the change forces

1. Re-seed the store (above).
2. **Rebuild the selfcheck baseline** — see the `selfcheck` skill. A corpus
   change moves `Result` and `Score_offset`, which are HARD fields.
3. If severities changed, say so explicitly: `Thái độ warning` is a **fourth**
   `Result` value, and consumers that don't know it fall through to
   `Tích cực` — a flagged call reads as clean downstream.

## Tuning against ground truth

Tune against QC labels, never against a prior run — the ~27% Databricks flip
rate means a prior run is not a stable reference. Verify F1 has not dropped
before committing a simplification.
