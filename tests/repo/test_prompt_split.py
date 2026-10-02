"""Static/dynamic split contract for `.prompt` files.

These guard the failure mode that shipped in v3 and v4: the call site
partitioned on an anchor string the prompt did not contain, so the split
silently produced a "static" half containing `{transcript}`. The prompt was
still sent correctly, so nothing broke — but the cached prefix changed on
every call and the prompt cache never hit.

No LLM, no network.
"""
import re

import pytest

from src.core.prompts import PROMPTS, PromptRegistry, PromptSplitError

# Prompts the pipeline actually sends as a cached message pair.
CACHED_PROMPTS = [
    "SCANNER_PROMPT",
    "HALU_CHECK_PROMPT",
    "KID_DETECTOR_PROMPT",
    "DECIDER_PROMPT",
    # Permissive pre-2026-08-18 scanner, kept for A/B against the
    # filter-derived one. Not wired into the graph; eval-only via
]

# Prompts that deliberately opt out of cache_control (see _primary_decider).
NO_CACHE_PROMPTS = [
    "PRIMARY_DECIDER_PROMPT",
    "SOFTEN_REASON_PROMPT",
]

PLACEHOLDER = re.compile(r"(?<!\{)\{(\w+)\}(?!\})")


# ---- backwards compatibility ----------------------------------------------


def test_prompts_is_still_a_dict():
    """~30 call sites read `PROMPTS["KEY"]`; that must keep working."""
    assert isinstance(PROMPTS, dict)
    assert isinstance(PROMPTS["SCANNER_PROMPT"], str)
    assert len(PROMPTS) > 20


# ---- the contract ----------------------------------------------------------


@pytest.mark.parametrize("key", CACHED_PROMPTS + NO_CACHE_PROMPTS)
def test_declared_prompts_split(key):
    parts = PROMPTS.split(key)
    assert parts.static.strip(), f"{key}: empty static half"
    assert parts.dynamic.strip(), f"{key}: empty dynamic half"


@pytest.mark.parametrize("key", CACHED_PROMPTS)
def test_no_placeholder_in_cached_half(key):
    """The bug this suite exists for.

    A `{placeholder}` above the marker means the cached prefix changes every
    call, so the cache never hits. This test fails on the pre-fix
    SCANNER_PROMPT.
    """
    parts = PROMPTS.split(key)
    assert parts.cacheable, f"{key}: expected a cacheable prompt"
    leaked = sorted(set(PLACEHOLDER.findall(parts.static)))
    assert not leaked, f"{key}: {leaked} would be baked into the cached prefix"


@pytest.mark.parametrize("key", CACHED_PROMPTS + NO_CACHE_PROMPTS)
def test_dynamic_half_actually_varies(key):
    parts = PROMPTS.split(key)
    assert PLACEHOLDER.search(parts.dynamic), f"{key}: dynamic half has no placeholder"


@pytest.mark.parametrize("key", NO_CACHE_PROMPTS)
def test_no_cache_prompts_declare_it(key):
    assert PROMPTS.split(key).cacheable is False


def test_every_marked_prompt_is_covered_by_this_test():
    """A new split prompt must be listed above, so it inherits the checks."""
    declared = set(CACHED_PROMPTS) | set(NO_CACHE_PROMPTS)
    assert set(PROMPTS.splittable()) == declared


# ---- message shape ---------------------------------------------------------


def test_cached_pair_shape():
    """The cached half must be the half with no per-request variable in
    it — a `{transcript}` above the marker means the cache key changes
    every call and never hits."""
    pair = PROMPTS.pair("SCANNER_PROMPT")
    assert set(pair) == {"system", "user"}
    block = pair["system"][0]
    assert block["type"] == "text"
    assert block["cache_control"] == {"type": "ephemeral"}
    assert "{transcript}" not in block["text"]
    assert "{transcript}" in pair["user"]


def test_no_cache_pair_shape():
    """`no-cache` prompts send a plain system string — no content parts,
    so nothing for the provider to cache."""
    pair = PROMPTS.pair("SOFTEN_REASON_PROMPT")
    assert set(pair) == {"system", "user"}
    assert isinstance(pair["system"], str)


# ---- failure modes ---------------------------------------------------------


def test_missing_marker_raises():
    reg = PromptRegistry({"X": "no marker here {transcript}"})
    with pytest.raises(PromptSplitError, match="no `── DYNAMIC ──` marker"):
        reg.split("X")


def test_placeholder_above_marker_raises():
    reg = PromptRegistry({"X": "rules {transcript}\n── DYNAMIC ──\n{context}"})
    with pytest.raises(PromptSplitError, match="transcript"):
        reg.split("X")


def test_no_cache_allows_placeholder_above_marker():
    """`_primary_decider` legitimately puts {positives} in the system half."""
    reg = PromptRegistry({"X": "rules {positives}\n── DYNAMIC no-cache ──\n{context}"})
    assert reg.split("X").cacheable is False


def test_static_dynamic_half_with_nothing_varying_raises():
    reg = PromptRegistry({"X": "rules\n── DYNAMIC ──\nnothing varies"})
    with pytest.raises(PromptSplitError, match="nothing below the marker varies"):
        reg.split("X")


def test_escaped_json_braces_are_not_placeholders():
    """Prompts carry `{{...}}` JSON examples; those must not count."""
    reg = PromptRegistry({"X": 'ex: {{"a": 1}}\n── DYNAMIC ──\n{context}'})
    assert reg.split("X").cacheable is True


def test_unknown_key_raises():
    with pytest.raises(PromptSplitError, match="no such prompt"):
        PROMPTS.split("DOES_NOT_EXIST")


def test_duplicate_marker_raises():
    reg = PromptRegistry({"X": "a\n── DYNAMIC ──\n{b}\n── DYNAMIC ──\n{c}"})
    with pytest.raises(PromptSplitError, match="more than one"):
        reg.split("X")
