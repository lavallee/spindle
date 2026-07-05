"""Smoke tests for examples/spindle-sample — validates the public sample distribution."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

SAMPLE_ROOT = Path(__file__).parent.parent / "examples" / "spindle-sample"
PACKAGE_PYPROJECT = SAMPLE_ROOT / "packages" / "sample-planning" / "pyproject.toml"
DIST_PYPROJECT = SAMPLE_ROOT / "distributions" / "spindle-sample" / "pyproject.toml"
PEERS_TOML = SAMPLE_ROOT / "peers" / "peers.toml"
VERDICTS_DIR = SAMPLE_ROOT / "verdicts"
PREEMPT_MD = SAMPLE_ROOT / "distributions" / "spindle-sample" / "preempt.md"
SKILLS_DIR = SAMPLE_ROOT / "packages" / "sample-planning" / "sample_planning" / "skills"


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def test_spindle_sample_root_exists():
    assert SAMPLE_ROOT.is_dir()


def test_package_pyproject_exists():
    assert PACKAGE_PYPROJECT.is_file()


def test_distribution_pyproject_exists():
    assert DIST_PYPROJECT.is_file()


def test_peers_toml_exists():
    assert PEERS_TOML.is_file()


def test_verdicts_dir_has_one_verdict():
    verdicts = [f for f in VERDICTS_DIR.iterdir() if f.suffix == ".md" and not f.name.startswith("_")]
    assert len(verdicts) == 1, f"Expected 1 verdict, got {verdicts}"


def test_preempt_md_exists():
    assert PREEMPT_MD.is_file()


def test_skill_markdown_files_exist():
    for name in ["clarify", "design", "tasks", "review"]:
        assert (SKILLS_DIR / name / "SKILL.md").is_file()


# ---------------------------------------------------------------------------
# Package pyproject: [tool.spindle.package]
# ---------------------------------------------------------------------------

def test_package_metadata_parses():
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    data = tomllib.loads(PACKAGE_PYPROJECT.read_text())
    pkg = data["tool"]["spindle"]["package"]
    assert pkg["name"] == "sample-planning"
    assert pkg["distribution"] == "spindle-sample"
    assert pkg["skills"] == ["clarify", "design", "tasks", "review"]
    assert len(pkg.get("capabilities", [])) > 0
    assert len(pkg.get("sources", [])) > 0


def test_package_source_has_required_fields():
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    data = tomllib.loads(PACKAGE_PYPROJECT.read_text())
    source = data["tool"]["spindle"]["package"]["sources"][0]
    assert "peer" in source
    assert "url" in source
    assert "transposed_at" in source
    # transposed_at must be a valid date string
    datetime.date.fromisoformat(str(source["transposed_at"]))


# ---------------------------------------------------------------------------
# Distribution pyproject: [tool.spindle.distribution]
# ---------------------------------------------------------------------------

def test_distribution_metadata_parses():
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    data = tomllib.loads(DIST_PYPROJECT.read_text())
    dist = data["tool"]["spindle"]["distribution"]
    assert dist["display_name"] == "Spindle Sample"
    assert "source_dir" in dist
    assert "preempt_snippet" in dist


def test_distribution_depends_on_sample_planning():
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    data = tomllib.loads(DIST_PYPROJECT.read_text())
    deps = data["project"].get("dependencies", [])
    assert any("sample-planning" in d for d in deps)


# ---------------------------------------------------------------------------
# Peers
# ---------------------------------------------------------------------------

def test_peers_toml_has_one_peer():
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    data = tomllib.loads(PEERS_TOML.read_text())
    peers = data.get("peer", [])
    assert len(peers) == 1
    assert "slug" in peers[0]
    assert "url" in peers[0]


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def test_verdict_has_frontmatter():
    verdict_files = [f for f in VERDICTS_DIR.iterdir() if f.suffix == ".md" and not f.name.startswith("_")]
    content = verdict_files[0].read_text()
    assert content.startswith("---"), "Verdict must start with YAML frontmatter"
    assert "verdict:" in content


# ---------------------------------------------------------------------------
# spindle distributions parser: round-trip
# ---------------------------------------------------------------------------

def test_spindle_can_parse_distribution_pyproject():
    from spindle.distributions import _parse_distribution_metadata
    meta = _parse_distribution_metadata(DIST_PYPROJECT)
    assert meta is not None
    assert meta.name == "spindle-sample"
    assert meta.display_name == "Spindle Sample"
    assert meta.packages == ["sample-planning"]


def test_spindle_can_parse_package_pyproject():
    from spindle.packages import _parse_package_metadata
    meta = _parse_package_metadata(PACKAGE_PYPROJECT)
    assert meta is not None
    assert meta.name == "sample-planning"
    assert meta.distribution == "spindle-sample"
    assert meta.skills == ["clarify", "design", "tasks", "review"]
