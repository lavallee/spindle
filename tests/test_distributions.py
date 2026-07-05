"""Smoke tests for spindle.distributions."""

from __future__ import annotations

from pathlib import Path

from spindle import distributions
from spindle.models import DistributionMetadata


def test_import_succeeds():
    from spindle.distributions import list_installed_distributions  # noqa: F401


def test_list_installed_distributions_returns_list():
    result = distributions.list_installed_distributions()
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, DistributionMetadata)


def test_list_installed_distributions_includes_spindle_sample():
    """Spindle Sample distribution is installed in editable mode."""
    result = distributions.list_installed_distributions()
    names = {d.name for d in result}
    assert "spindle-sample" in names


def test_read_distribution_metadata_unknown_returns_none():
    assert distributions.read_distribution_metadata("definitely-not-installed-xyz-123") is None


def test_distribution_source_dir_unknown_returns_none():
    assert distributions.distribution_source_dir("definitely-not-installed-xyz-123") is None


def test_parse_distribution_metadata_full(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "my-dist"
version = "1.2.3"
dependencies = [
  "sample-grill==0.2.0",
  "sample-plan>=0.1",
]

[tool.spindle.distribution]
display_name = "My Distribution"
description = "A test distribution."
source_dir = "../../"
preempt_snippet = "preempt.md"
home_url = "https://example.com"
"""
    )
    meta = distributions._parse_distribution_metadata(pyproject)
    assert meta is not None
    assert meta.name == "my-dist"
    assert meta.version == "1.2.3"
    assert meta.display_name == "My Distribution"
    assert meta.description == "A test distribution."
    assert meta.home_url == "https://example.com"
    assert meta.packages == ["sample-grill", "sample-plan"]


def test_parse_distribution_metadata_missing_section(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "plain-pkg"
version = "0.1.0"
"""
    )
    assert distributions._parse_distribution_metadata(pyproject) is None


def test_parse_distribution_metadata_malformed_toml(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("this is = not valid : toml [[\n")
    assert distributions._parse_distribution_metadata(pyproject) is None


def test_distribution_source_dir_resolves_relative(tmp_path):
    """source_dir = '../../' is resolved to an absolute path relative to the pyproject."""
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    pyproject = nested / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "test-dist"
version = "0.1.0"

[tool.spindle.distribution]
display_name = "Test"
description = ""
source_dir = "../../"
"""
    )
    meta = distributions._parse_distribution_metadata(pyproject)
    assert meta is not None
    assert meta.source_dir == tmp_path.resolve()
    assert meta.source_dir.is_absolute()


def test_distribution_source_dir_dot_resolves_to_pyproject_parent(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "test-dist"
version = "0.1.0"

[tool.spindle.distribution]
display_name = "Test"
description = ""
source_dir = "."
"""
    )
    meta = distributions._parse_distribution_metadata(pyproject)
    assert meta is not None
    assert meta.source_dir == tmp_path.resolve()


def test_preempt_snippet_is_none_when_absent(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "test-dist"
version = "0.1.0"

[tool.spindle.distribution]
display_name = "Test"
description = ""
source_dir = "."
"""
    )
    meta = distributions._parse_distribution_metadata(pyproject)
    assert meta is not None
    assert meta.preempt_snippet is None


def test_preempt_snippet_resolved_under_source_dir(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "test-dist"
version = "0.1.0"

[tool.spindle.distribution]
display_name = "Test"
description = ""
source_dir = "."
preempt_snippet = "preempt.md"
"""
    )
    meta = distributions._parse_distribution_metadata(pyproject)
    assert meta is not None
    assert meta.preempt_snippet == tmp_path.resolve() / "preempt.md"
