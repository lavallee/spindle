"""Smoke tests for spindle.packages — discovery via importlib.metadata."""

from __future__ import annotations

import datetime

from spindle import packages
from spindle.models import PackageMetadata


def test_import_succeeds():
    """Acceptance: `from spindle.packages import list_installed_packages` works."""
    from spindle.packages import list_installed_packages  # noqa: F401


def test_list_installed_packages_returns_list():
    """Returns a list; pre-Epic 1.3 with no sample-* packages installed, it's empty."""
    result = packages.list_installed_packages()
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, PackageMetadata)


def test_sample_package_discovered():
    """The sample package (editably installed) is discovered via importlib.metadata."""
    pkgs = packages.list_installed_packages()
    by_name = {p.name: p for p in pkgs}
    assert "sample-planning" in by_name
    # Only assert distribution/skills invariants on the sample-* packages
    # themselves. Other spindle-managed installs (e.g. a scaffolded example or
    # a leftover integration-test fixture) may live in the same venv and
    # legitimately declare a different distribution or be still unwired.
    p = by_name["sample-planning"]
    assert p.distribution == "spindle-sample"
    assert p.skills == ["clarify", "design", "tasks", "review"]


def test_skips_packages_without_tool_spindle_package():
    """Installed packages like pytest / pluggy don't declare [tool.spindle.package] — must be skipped, not raise."""
    # If this doesn't raise, we're good — the environment has plenty of
    # non-spindle packages and discovery must just walk past them.
    packages.list_installed_packages()


def test_parse_package_metadata_full(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "sample-thing"
version = "0.1.0"

[tool.spindle.package]
name = "sample-thing"
version = "0.1.0"
distribution = "spindle-sample"
skills = ["thing"]
capabilities = ["a", "b"]

[[tool.spindle.package.sources]]
peer = "someone/repo"
url = "https://example.com/repo"
transposed_at = "2026-01-15"
notes = "imported"
"""
    )
    meta = packages._parse_package_metadata(pyproject)
    assert meta is not None
    assert meta.name == "sample-thing"
    assert meta.version == "0.1.0"
    assert meta.distribution == "spindle-sample"
    assert meta.skills == ["thing"]
    assert meta.capabilities == ["a", "b"]
    assert len(meta.sources) == 1
    assert meta.sources[0].peer == "someone/repo"
    assert meta.sources[0].transposed_at == datetime.date(2026, 1, 15)


def test_parse_package_metadata_missing_tool_spindle(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "plain-pkg"
version = "0.1.0"
"""
    )
    assert packages._parse_package_metadata(pyproject) is None


def test_parse_package_metadata_malformed_toml(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("this is = not valid : toml [[\n")
    assert packages._parse_package_metadata(pyproject) is None


def test_read_package_metadata_unknown_returns_none():
    assert packages.read_package_metadata("definitely-not-installed-xyz-123") is None


def test_package_skill_dirs_unknown_returns_empty():
    assert packages.package_skill_dirs("definitely-not-installed-xyz-123") == []


def test_package_skill_dirs_resolves_layout(tmp_path, monkeypatch):
    """package_skill_dirs walks the conventional <importable>/skills/<name>/ layout."""
    importable = tmp_path / "sample_demo"
    skill = importable / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\n---\n")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "sample-demo"
version = "0.1.0"

[tool.spindle.package]
name = "sample-demo"
version = "0.1.0"
skills = ["demo"]
"""
    )

    fake_meta = packages._parse_package_metadata(pyproject)
    assert fake_meta is not None

    monkeypatch.setattr(packages, "read_package_metadata", lambda name: fake_meta)
    dirs = packages.package_skill_dirs("sample-demo")
    assert dirs == [skill]


def test_package_skill_dirs_resolves_src_layout(tmp_path, monkeypatch):
    """src-layout packages (src/<importable>/skills/<name>/) resolve too."""
    skill = tmp_path / "src" / "sample_demo" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\n---\n")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "sample-demo"
version = "0.1.0"

[tool.spindle.package]
name = "sample-demo"
version = "0.1.0"
skills = ["demo"]
"""
    )

    fake_meta = packages._parse_package_metadata(pyproject)
    assert fake_meta is not None

    monkeypatch.setattr(packages, "read_package_metadata", lambda name: fake_meta)
    assert packages.package_skill_dirs("sample-demo") == [skill]


def test_read_package_metadata_falls_back_to_spindle_name(tmp_path, monkeypatch):
    """The spindle-package name may differ from the pip distribution name
    (e.g. spindle package `flip` shipped by the `flip-notebook` distribution);
    lookup falls back to scanning installed packages by spindle name."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "sample-demo-dist"
version = "0.2.0"

[tool.spindle.package]
name = "sample-demo"
version = "0.2.0"
skills = []
"""
    )
    fake_meta = packages._parse_package_metadata(pyproject)
    assert fake_meta is not None

    monkeypatch.setattr(packages, "list_installed_packages", lambda: [fake_meta])
    meta = packages.read_package_metadata("sample-demo")
    assert meta is not None and meta.name == "sample-demo"
