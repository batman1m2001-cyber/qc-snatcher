# report — how the batch went: calls scored, failed, skipped; LLM tokens and cost.

```
    python main.py                      # the `main` runbook's last step
    operonx-run main                    # the same

Reads the last `score` run's record (`.runs/score/<run>/`) and prints the
summary the pods have always logged: total files, success, failed,
skipped (an output already there, or no call_code), LLM calls, tokens,
cache hits and cost. Never fails the run — the batch is scored by then.

Needs : nothing. Cost: none.
```
