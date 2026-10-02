# Checklist — bring the three branches back to one line

**Goal:** `thanglq2_dev` is the only place code is written. `dev` is the MR
target and nothing else. `feat/corpus-autoseed` disappears into it.

```
c18f3d9  08/09  ← where dev and thanglq2_dev parted
  ├─ dev            8ef1e48 merge · 9746623 + 4eb0a2a settings.py · 5a66cd4 Dockerfile
  │    └─ feat/corpus-autoseed   14cbb0f + 9c46590
  └─ thanglq2_dev   9 commits
```

Nothing here is pushed yet, so every step is undoable until §5.

---

## 1. Safety net

- [ ] `git branch backup/thanglq2_dev-$(date +%Y%m%d) thanglq2_dev`
- [ ] `git branch backup/feat-autoseed-$(date +%Y%m%d) feat/corpus-autoseed`
- [ ] working tree clean — `git status --short` shows only the usual untracked
      (`runs/`, `docs/REPORT_*`, `.env.bak.*`)

## 2. Pull dev's deployment commits into thanglq2_dev

MLE's env work. Left behind, the next MR silently reverts it.

- [ ] `git checkout thanglq2_dev`
- [ ] `git cherry-pick 9746623 4eb0a2a`   *(both touch only `deployment/score_sentiment/settings.py`)*
- [ ] **skip `5a66cd4`** — 125 insertions / 125 deletions on `Dockerfile` is
      pure CRLF churn, no content change
- [ ] `git diff dev thanglq2_dev -- deployment/` is empty

## 3. Rebase the autoseed work onto thanglq2_dev

- [ ] `git rebase --onto thanglq2_dev dev feat/corpus-autoseed`
- [ ] resolve the four files below
- [ ] `git checkout thanglq2_dev && git merge --ff-only feat/corpus-autoseed`

### The four files, and what to keep

| file | resolution |
|---|---|
| `src/config.py` | **drop my hunk entirely.** `thanglq2_dev` already defaults the four resources to remote, and `require_remote_retrieval()` goes further by resolving the real `api_type` — a name like `corpus-pos-pg` can still point at a faiss block |
| `src/cases/sentiment_agent/_retrieval.py` | keep `require_remote_retrieval` from `thanglq2_dev`; replace the body of `_check_seeded_corpus` with the version that resolves the DSN and calls `src.corpus.ensure_seeded` |
| `main.py` | keep both calls, **in this order**: `require_remote_retrieval()` then `check_corpus_freshness()`. Plus the `--ingest` flag. Order matters — on the local stack the freshness check answers from a faiss manifest it will happily rebuild, so it cannot tell a deployment it is on the wrong backend |
| `.gitignore` | union of both |

The two mechanisms compose rather than compete: `require_remote_retrieval`
answers *am I on the right backend*, `src/corpus` answers *does that backend
hold the right corpus, and make it so*.

## 4. Verify before pushing

- [ ] `uv run pytest tests/ -q` → 528 pass
- [ ] `uv run python scripts/sim_multipod.py empty` → `seeded=1 skipped=3` PASS
- [ ] `uv run python scripts/sim_multipod.py ok` → `seeded=0 untouched=4` PASS
- [ ] `uv run python scripts/check_triton.py` → OK *(needs VPN)*
- [ ] default is still off: `main.py` without `--ingest` on a mismatched store
      raises, writes nothing
- [ ] `git grep -c "def require_remote_retrieval" src/` → 1
- [ ] `git grep -c -- "--ingest" main.py` → 2

## 5. Push and MR

- [ ] `git push origin thanglq2_dev` *(needs VPN)*
- [ ] `cd ../../../platform.hush-ai && git push` — hush-providers 0.4.0,
      commit `60af37d`. **Push this first**: `pyproject.toml` now requires
      `>=0.4.0` and the build fails without it
- [ ] MR `thanglq2_dev` → `dev`, same route as `8ef1e48`
- [ ] `git branch -d feat/corpus-autoseed`

## 6. Tell MLE

- [ ] one env var on the pod: `CORPUS_AUTO_SEED=true`
- [ ] prod does not run selfcheck, so the pods do the seeding — the advisory
      lock is what keeps that to one
- [ ] first batch after deploy: exactly one pod logs `holding the seed lock`,
      the rest log `already seeded by another pod`. More than one seeding is
      harmless but means the lock is not holding

## Rollback

Anything before §5 is local only: `git reset --hard backup/thanglq2_dev-<date>`.
After the push, revert the merge commit on `thanglq2_dev` — the auto-seed is
opt-in, so simply unsetting `CORPUS_AUTO_SEED` already restores the old
refuse-and-stop behaviour without touching code.
