"""Reading `corpus.yaml` — its path, its content hash, and entry severity.
Rows per phrasing are `variants.corpus_rows`.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..core.config import KNOWLEDGE_DIR

#: What QC maintains.
CORPUS_YAML = KNOWLEDGE_DIR / "sentiment_agent" / "corpus.yaml"


def corpus_hash(text: str) -> str:
    """Short content hash — seed stamps, freshness and baseline drift.

    The one definition: the seed, the startup freshness check and the
    selfcheck manifest all compare hashes, so all of them must hash alike.
    """
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def corpus_file_hash(path) -> str:
    """`corpus_hash` of a file read as text.

    Text mode turns CRLF and lone CR into LF, so a Windows checkout hashes
    the same as a Linux one. Hashing raw bytes would not.
    """
    return corpus_hash(Path(path).read_text(encoding="utf-8"))


#: Postgres stores severity on the partner's scale — their CHECK allows
#: only SAFE/WARNING/HIGH/CRITICAL, and `src/jobs/ingest/_seed.py`
#: maps the corpus tiers onto it on the way in. Without mapping them back,
#: `resolve_cited_severity` gets values its ranking does not contain: every
#: call resolves to "", the corpus-severity override silently stops, and
#: the whole `warning` tier disappears. Values already on the corpus scale
#: pass through untouched.
_SEVERITY_FROM_PARTNER = {
    "SAFE":     "tich_cuc",
    "WARNING":  "warning",
    "HIGH":     "cao",
    "CRITICAL": "nghiem_trong",
}


def corpus_severity(raw: str) -> str:
    """A corpus tier, whichever scale the store speaks."""
    sev = (raw or "").strip()
    return _SEVERITY_FROM_PARTNER.get(sev.upper(), sev)
