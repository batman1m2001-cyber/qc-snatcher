"""Iconic-keyword pre-filter for sentiment_agent.

Loads `knowledge/sentiment_agent/keyword_filter.yaml`, flattens all
grouped phrases, and compiles a single case-insensitive regex. Exposes
`has_hit(agent_text)` — cheap substring check used before the LLM scanner
to drop calls with no violation-adjacent language.

Recall / cost on pilot rounds (measured 2026-07-13):
  recall       ~ 80%    (358 TP / 448 gold VP across 1703 audios)
  filter_rate  ~ 31%    → 69% of calls skip the LLM scanner
Remaining 20% recall gap will be covered by a downstream ML filter
(BGE-M3 similarity / classifier) unioned with this keyword pass.

Loader is a lru_cache singleton so the regex is compiled once per process.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml
from .....core.config import (
    KNOWLEDGE_DIR,
)

_YAML_PATH = KNOWLEDGE_DIR / "sentiment_agent" / "keyword_filter.yaml"


def _load_phrases(path: Path = _YAML_PATH) -> list[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    groups = data.get("groups") or {}
    phrases: list[str] = []
    for grp in groups.values():
        for p in (grp.get("phrases") or []):
            if isinstance(p, str) and p.strip():
                phrases.append(p.strip().lower())
    return sorted(set(phrases))


@lru_cache(maxsize=1)
def _get_pattern() -> re.Pattern[str]:
    phrases = _load_phrases()
    if not phrases:
        # Empty corpus → pattern matches nothing rather than everything.
        return re.compile(r"(?!)")
    return re.compile(
        "(" + "|".join(re.escape(p) for p in phrases) + ")",
        re.IGNORECASE,
    )


def has_hit(agent_text: str) -> bool:
    """True if any keyword substring is present. Empty input → False."""
    if not agent_text:
        return False
    return bool(_get_pattern().search(agent_text))


def concat_agent_text(vads: list[dict]) -> str:
    """Concat all AGENT-role turn contents into one lowercased blob."""
    if not vads:
        return ""
    parts = [
        (v.get("content") or "").lower()
        for v in vads
        if (v.get("role") or "").upper() == "AGENT"
    ]
    return " ".join(parts)
