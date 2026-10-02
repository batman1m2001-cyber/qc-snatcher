"""Prompts live beside their ops, and two may not share a name.

`PROMPTS` is keyed by file stem across the whole `src/` tree. With prompts
spread over a dozen `prompts/` folders, a second file with an existing name
would shadow the first — and which one won would depend on directory walk
order. The loader refuses instead; these pin that it does.
"""
from __future__ import annotations


import pytest

from src.core.prompts import _PROMPT_DIR, PROMPTS, _load

from tests._paths import SRC


def test_the_loader_scans_the_package_tree():
    assert _PROMPT_DIR == SRC


def test_every_prompt_sits_in_a_prompts_folder():
    stray = [p for p in SRC.rglob("*.prompt") if p.parent.name != "prompts"]
    assert stray == [], f"prompt files outside a prompts/ folder: {stray}"


def test_every_prompt_file_is_loaded():
    assert set(PROMPTS) == {p.stem for p in SRC.rglob("*.prompt")}


def test_a_duplicate_name_raises(tmp_path):
    for pkg in ("a", "b"):
        d = tmp_path / pkg / "prompts"
        d.mkdir(parents=True)
        (d / "SAME_PROMPT.prompt").write_text(f"from {pkg}", encoding="utf-8")
    with pytest.raises(ValueError, match="SAME_PROMPT"):
        _load(tmp_path)


def test_distinct_names_load(tmp_path):
    for pkg, name in (("a", "ONE"), ("b", "TWO")):
        d = tmp_path / pkg / "prompts"
        d.mkdir(parents=True)
        (d / f"{name}.prompt").write_text(name, encoding="utf-8")
    assert set(_load(tmp_path)) == {"ONE", "TWO"}
