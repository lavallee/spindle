"""Regression checks for the public repository surface."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".git",
    ".gstack",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".sqlite", ".db"}

PRIVATE_PATTERNS = [
    ("legacy package name", re.compile(r"\b" + "iv" + "y" + r"\b", re.IGNORECASE)),
    ("legacy env prefix", re.compile("I" + "VY_")),
    ("legacy metadata table", re.compile(r"tool\." + "iv" + "y")),
    ("legacy import", re.compile(r"(from|import)\s+" + "iv" + "y" + r"\b")),
    ("private distribution family", re.compile(r"\b" + "fo" + "rge" + r"\b", re.IGNORECASE)),
    ("private org name", re.compile("ly" + "ra", re.IGNORECASE)),
    ("old example name", re.compile("spr" + "uce", re.IGNORECASE)),
    ("private task service", re.compile("geo" + "rge", re.IGNORECASE)),
    ("private runner", re.compile(r"\b" + "fa" + "b" + r"\b")),
]


def _iter_text_files():
    for path in ROOT.rglob("*"):
        if path.is_dir():
            continue
        rel_parts = set(path.relative_to(ROOT).parts)
        if rel_parts & SKIP_DIRS:
            continue
        if path.suffix in SKIP_SUFFIXES:
            continue
        yield path


def test_public_tree_has_no_private_surface_strings():
    hits: list[str] = []
    for path in _iter_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(ROOT)
        for label, pattern in PRIVATE_PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                hits.append(f"{rel}:{line}: {label}: {match.group(0)!r}")

    assert hits == []
