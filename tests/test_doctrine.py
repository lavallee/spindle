"""Tests for spindle.doctrine — load, validate, query, version-coordinate."""

from __future__ import annotations

import spindle.doctrine as doctrine_mod

VALID = """\
version = "0.1.0"

[[preference]]
id = "P1"
scope = "system"
favor = "the spec as the asset"
over = "the code as the asset"
provenance = ["spec-kit", "ralph-loop"]

[[absolute]]
id = "A1"
scope = "system"
mode = "ALWAYS"
statement = "progressive disclosure"
provenance = ["anthropic-skills"]

[[meta_principle]]
id = "M1"
statement = "durable artifacts need a decay obligation"
"""


def _write(tmp_path, text):
    p = tmp_path / "doctrine" / "doctrine.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_load_parses_all_kinds(tmp_path):
    doc = doctrine_mod.load(_write(tmp_path, VALID))
    assert doc.version == "0.1.0"
    assert len(doc.preferences) == 1
    assert len(doc.absolutes) == 1
    assert len(doc.meta_principles) == 1
    assert doc.preferences[0].favor == "the spec as the asset"
    assert doc.preferences[0].provenance == ["spec-kit", "ralph-loop"]
    assert doc.absolutes[0].mode == "ALWAYS"


def test_validate_clean(tmp_path):
    doc = doctrine_mod.load(_write(tmp_path, VALID))
    assert doctrine_mod.validate(doc) == []


def test_validate_catches_duplicate_id(tmp_path):
    text = VALID + """
[[preference]]
id = "P1"
scope = "repo"
favor = "x"
over = "y"
"""
    doc = doctrine_mod.load(_write(tmp_path, text))
    problems = doctrine_mod.validate(doc)
    assert any("duplicate id 'P1'" in p for p in problems)


def test_validate_catches_bad_scope_and_mode(tmp_path):
    text = """\
version = "0.1.0"

[[preference]]
id = "P1"
scope = "galaxy"
favor = "x"
over = "y"

[[absolute]]
id = "A1"
scope = "system"
mode = "MAYBE"
statement = "s"
"""
    doc = doctrine_mod.load(_write(tmp_path, text))
    problems = doctrine_mod.validate(doc)
    assert any("bad scope 'galaxy'" in p for p in problems)
    assert any("bad mode 'MAYBE'" in p for p in problems)


def test_validate_catches_missing_preference_sides(tmp_path):
    text = """\
version = "0.1.0"

[[preference]]
id = "P1"
scope = "system"
favor = "only favor"
"""
    doc = doctrine_mod.load(_write(tmp_path, text))
    assert any("needs both 'favor' and 'over'" in p for p in doctrine_mod.validate(doc))


def test_validate_catches_missing_version(tmp_path):
    text = VALID.replace('version = "0.1.0"\n', "")
    doc = doctrine_mod.load(_write(tmp_path, text))
    assert any("missing version" in p for p in doctrine_mod.validate(doc))


def test_query_get_and_by_scope(tmp_path):
    doc = doctrine_mod.load(_write(tmp_path, VALID))
    assert doc.get("P1").id == "P1"
    assert doc.get("A1").mode == "ALWAYS"
    assert doc.get("nope") is None
    assert [p.id for p in doc.preferences_for_scope("system")] == ["P1"]
    assert doc.preferences_for_scope("repo") == []
    assert [a.id for a in doc.absolutes_for_scope("system")] == ["A1"]


def test_coordinate_is_version_plus_hash(tmp_path):
    doc = doctrine_mod.load(_write(tmp_path, VALID))
    coord = doc.coordinate()
    assert coord.startswith("0.1.0+")
    assert len(doc.source_hash) == 64  # sha256 hex
    # Stable for identical content
    doc2 = doctrine_mod.load(_write(tmp_path, VALID))
    assert doc.coordinate() == doc2.coordinate()


def test_coordinate_changes_with_content(tmp_path):
    doc = doctrine_mod.load(_write(tmp_path, VALID))
    doc2 = doctrine_mod.load(_write(tmp_path, VALID + "\n# a comment changes the hash\n"))
    assert doc.coordinate() != doc2.coordinate()


def test_shipped_doctrine_is_valid():
    """The spindle-sample doctrine.toml in this repo must itself validate."""
    from pathlib import Path
    repo_doctrine = (
        Path(__file__).resolve().parent.parent
        / "examples"
        / "spindle-sample"
        / "doctrine"
        / "doctrine.toml"
    )
    doc = doctrine_mod.load(repo_doctrine)
    assert doctrine_mod.validate(doc) == []
    # Sanity: the seeded set is present
    assert doc.get("P1") is not None
    assert doc.get("A1") is not None
    assert doc.get("M1") is not None
