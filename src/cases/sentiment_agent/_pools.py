"""Pool formatting and citation parsing — shared by both deciders.

The filter decider and the primary decider each retrieve their own pools, hand
them to a model as indexed slots (`P1`, `C3`), and map the slots the model
cites back to corpus ids. Same four helpers, two callers, so they live
between the layers rather than inside either.

Moved verbatim out of `_matcher.py`; `git log --follow` on this file shows
the history they came with.
"""
from __future__ import annotations

import re
from collections import OrderedDict


_ID_RX_TEMPLATE = r"^{prefix}\d+$"


def _format_indexed_pool(items: list[dict], prefix: str) -> tuple[str, list[dict]]:
    """Emit indexed labeled pool + return raw item list for tie-judge lookup.

    Groups by ``parent_id``: the variants of one corpus entry share a slot.
    Output shape (per item):

        [P1] sample: "variant1 | variant2"
             description: "..."

    Returns ``(formatted_string, list_of_dicts)`` where each dict is
    ``{id, text, description, category}``. The list preserves the same
    order as the formatted string so ``id → dict`` lookup is trivial.
    """
    if not items:
        return "(không có mẫu nào được retrieve)", []

    grouped: OrderedDict[str, dict] = OrderedDict()
    for i, it in enumerate(items):
        pid = it.get("parent_id") or f"__nogroup_{i}"
        if pid not in grouped:
            grouped[pid] = {
                "category": it.get("category", "?"),
                "description": (it.get("description") or "").strip(),
                # Corpus severity of the entry, carried so a caller can map a
                # cited pool id back to the tier QC assigned it. Not rendered
                # into the prompt — the model is not told severities and its
                # behaviour is unchanged by this.
                "severity": (it.get("severity") or "").strip(),
                "entry_id": pid,
                "variants": [],
            }
        grouped[pid]["variants"].append(it.get("text", ""))

    lines: list[str] = []
    raw_items: list[dict] = []
    for idx, g in enumerate(grouped.values(), 1):
        pool_id = f"{prefix}{idx}"
        content = " | ".join(g["variants"]) if len(g["variants"]) > 1 else g["variants"][0]
        lines.append(f'[{pool_id}] sample: "{content}"')
        desc = g["description"] or "(không có mô tả)"
        lines.append(f"      description: {desc}")
        lines.append("")
        raw_items.append(
            {"id": pool_id, "text": content, "description": g["description"],
             "category": g["category"], "severity": g["severity"],
             "entry_id": g["entry_id"]}
        )
    return "\n".join(lines).rstrip(), raw_items


def pool_id_map(*item_lists) -> dict[str, str]:
    """`{"P1": "<entry uuid>", "C2": "<entry uuid>", ...}`.

    Built from the `raw_items` `_format_indexed_pool` already returns, so
    this is bookkeeping over data the caller has in hand — no second lookup
    that could disagree with what the model was shown.
    """
    out: dict[str, str] = {}
    for items in item_lists:
        for it in items or []:
            if not isinstance(it, dict):
                continue
            pool_id = str(it.get("id") or "").strip()
            entry_id = str(it.get("entry_id") or "").strip()
            if pool_id and entry_id:
                out[pool_id] = entry_id
    return out


def remap_cited(cited: list, pool_map: dict) -> list[str]:
    """Slot labels -> corpus entry ids.

    A slot the map does not know passes through unchanged rather than being
    dropped: an unresolved `P3` is a fact worth seeing, and silently losing
    a citation would read as "the model cited nothing".
    """
    m = pool_map or {}
    return [m.get(c, c) for c in (cited or [])]


def _parse_cited(cited_raw, prefix: str) -> list[str]:
    """Extract + validate cited sample ids (``PN`` / ``CN`` format).

    Accepts list or comma-string. Silently drops invalid ids (wrong
    prefix, no digit suffix) rather than failing — LLM sometimes cites
    bare numbers or wrong-prefix ids.
    """
    if cited_raw is None:
        return []
    if isinstance(cited_raw, str):
        cited_raw = [x.strip() for x in cited_raw.split(",") if x.strip()]
    if not isinstance(cited_raw, list):
        return []
    id_rx = re.compile(_ID_RX_TEMPLATE.format(prefix=prefix), re.IGNORECASE)
    return [str(x).strip().upper() for x in cited_raw
            if id_rx.fullmatch(str(x).strip().upper())]
