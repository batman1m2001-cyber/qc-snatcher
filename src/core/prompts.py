"""Prompts loaded at import time from every `*.prompt` file under `src/`.

Each prompt lives in a `prompts/` folder beside the op that sends it —
`src/cases/sentiment_agent/l2_scanner/prompts/SCANNER_PROMPT.prompt` sits
next to the scanner — so a package carries its own text. PROMPTS stays one
flat namespace keyed by `file.stem`, and **a duplicate stem raises at
import**: with prompts spread across packages, a second file of the same
name would otherwise shadow the first silently, and which one won would
depend on directory walk order.

    from src.core.prompts import PROMPTS
    template = PROMPTS["VIOLATION_CASE1_NORMAL_PROMPT"]

Static / dynamic split
----------------------
A prompt sent as a chat message pair declares its own split point with a
marker line:

    ── DYNAMIC ──              static half is cached
    ── DYNAMIC no-cache ──     static half sent as a plain system message

Everything above the marker is stable across calls and goes in the system
message; everything below carries the per-request `{placeholders}` and goes
in the user message. The marker itself is consumed.

`PROMPTS.pair(key)` returns the ready split, so no call site hand-rolls a
partition:

    template = PROMPTS.pair("SCANNER_PROMPT")

Why the marker lives in the prompt file: the split point and the caching
decision are properties of the prompt, and whoever edits the prompt is the
person who needs to see them. A split kept at the call site can partition
on an anchor the prompt does not contain: the whole prompt, `{transcript}`
included, lands in the cached block and the cache never hits. `split()`
raises instead of degrading.

`no-cache` is not a performance knob. It records a deliberate decision:
the primary decider and soften prompts fire on ~1-2% of traffic, and the
ephemeral cache marker correlated with Result-flip drift on borderline
calls. Placeholder validation is skipped for those, since a plain system
message may legitimately carry per-request text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


#: Scanned for `*.prompt`. The whole package tree, because each prompt sits
#: beside the op that sends it.
_PROMPT_DIR = Path(__file__).resolve().parents[1]

# `── DYNAMIC ──` / `── DYNAMIC no-cache ──`, on its own line.
_MARKER_RX = re.compile(
    r"^[─-]{2,}\s*DYNAMIC(?P<flag>\s+no-cache)?\s*[─-]{2,}\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Single-brace `{name}` placeholders LLMOp fills per request. `{{` / `}}`
# are escaped literals for JSON examples and must not match.
_PLACEHOLDER_RX = re.compile(r"(?<!\{)\{(\w+)\}(?!\})")


class PromptSplitError(ValueError):
    """A prompt could not be split into a cacheable static half and a
    per-request dynamic half."""


@dataclass(frozen=True)
class PromptParts:
    static: str
    dynamic: str
    cacheable: bool


class PromptRegistry(dict):
    """`dict` of prompt-stem -> text, plus static/dynamic splitting.

    Subclasses `dict` so every existing `PROMPTS["KEY"]` read keeps working.
    """

    def split(self, key: str) -> PromptParts:
        """Split a prompt at its `── DYNAMIC ──` marker.

        Raises `PromptSplitError` rather than degrading: a missing marker or
        a per-request placeholder stranded in the cached half is a silent
        cost regression, not a cosmetic issue.
        """
        try:
            text = self[key]
        except KeyError:
            raise PromptSplitError(f"{key}: no such prompt") from None

        m = _MARKER_RX.search(text)
        if m is None:
            raise PromptSplitError(
                f"{key}: no `── DYNAMIC ──` marker — cannot tell which half is "
                f"stable across calls. Add the marker above the per-request values."
            )
        if _MARKER_RX.search(text, m.end()):
            raise PromptSplitError(f"{key}: more than one `── DYNAMIC ──` marker")

        cacheable = m.group("flag") is None
        static = text[: m.start()].rstrip("- \n")
        dynamic = text[m.end():].lstrip("\n")

        if not _PLACEHOLDER_RX.search(dynamic):
            raise PromptSplitError(
                f"{key}: nothing below the marker varies per request — "
                f"the split is pointless as written."
            )
        if cacheable:
            leaked = sorted(set(_PLACEHOLDER_RX.findall(static)))
            if leaked:
                raise PromptSplitError(
                    f"{key}: per-request placeholder(s) {leaked} appear above the "
                    f"marker. They would be baked into the cached prefix and the "
                    f"cache would never hit. Move them below, or mark the prompt "
                    f"`── DYNAMIC no-cache ──`."
                )
        return PromptParts(static=static, dynamic=dynamic, cacheable=cacheable)

    def pair(self, key: str) -> dict:
        """The split, in the shape ``LLMOp`` formats.

        A dict rather than a message list, and that is a statement about
        what these are. `LLMOp` takes exactly one of `prompt=` — a
        *template*, which it formats — or `messages=` — a *finished
        conversation*, which it never formats. Ours are templates: two
        roles carrying `{placeholders}`. Handed to `messages=` every
        placeholder would survive unrendered into the request.

        `_format_value` recurses through dicts and lists, so a cacheable
        system block keeps its content-part structure and its
        `cache_control` while the text inside still gets formatted.
        """
        parts = self.split(key)
        if parts.cacheable:
            system: object = [
                {
                    "type": "text",
                    "text": parts.static,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            system = parts.static
        return {"system": system, "user": parts.dynamic}

    def splittable(self) -> list[str]:
        """Keys carrying a split marker — used by the regression test."""
        return sorted(k for k, v in self.items() if _MARKER_RX.search(v))


def _load(root: Path) -> PromptRegistry:
    """Every `*.prompt` under *root*, keyed by stem; a repeated stem raises."""
    found: dict[str, Path] = {}
    for f in sorted(root.rglob("*.prompt")):
        if f.stem in found:
            raise ValueError(
                f"two prompts named {f.stem!r}: {found[f.stem]} and {f}. "
                "PROMPTS is keyed by file stem, so one would silently shadow "
                "the other — rename one."
            )
        found[f.stem] = f
    return PromptRegistry((k, v.read_text(encoding="utf-8")) for k, v in found.items())


PROMPTS: PromptRegistry = _load(_PROMPT_DIR)
