"""preflight — is the stack this deployment needs there?

    operonx-run preflight                               # check, and exit 0 / 1

Prints which resource serves each stage (models.yaml), then checks, in
order — each only means anything once the one before holds:

  1. backends   the four retrieval resources resolve to the remote kinds
                (pgvector, postgres, triton) — a local one answers every
                query and reports nothing
  2. reachable  every resource `models.yaml` routes to accepts a
                connection — constructing a client opens no socket

Whether the corpus store is current is `ingest`'s question, the next step
of the `main` runbook. Needs VPN. Costs nothing.
"""
