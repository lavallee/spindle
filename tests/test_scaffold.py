"""Tests for spindle.scaffold — package_new and dist_new template writers."""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from spindle.scaffold import package_new, dist_new


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "Bad", "-start", "under_score", "has space", "1start"])
def test_package_new_rejects_bad_names(tmp_path, bad):
    with pytest.raises(ValueError, match="Invalid name"):
        package_new(bad, tmp_path / "out", skills=[], capabilities=[])


@pytest.mark.parametrize("bad", ["", "Bad", "under_score"])
def test_dist_new_rejects_bad_names(tmp_path, bad):
    with pytest.raises(ValueError, match="Invalid name"):
        dist_new(bad, tmp_path / "out", source_dir="../../", packages=[])


@pytest.mark.parametrize("good", ["mypackage", "my-package", "abc123", "a1-b2"])
def test_package_new_accepts_valid_names(tmp_path, good):
    written = package_new(good, tmp_path / good, skills=[], capabilities=[])
    assert len(written) >= 2  # pyproject.toml + __init__.py


# ---------------------------------------------------------------------------
# package_new: file structure
# ---------------------------------------------------------------------------

def test_package_new_creates_pyproject(tmp_path):
    package_new("my-pkg", tmp_path, skills=["hello"], capabilities=["greeting"])
    assert (tmp_path / "pyproject.toml").is_file()


def test_package_new_creates_init(tmp_path):
    package_new("my-pkg", tmp_path, skills=[], capabilities=[])
    assert (tmp_path / "my_pkg" / "__init__.py").is_file()


def test_package_new_creates_skill_md(tmp_path):
    package_new("my-pkg", tmp_path, skills=["hello", "bye"], capabilities=[])
    assert (tmp_path / "my_pkg" / "hello.md").is_file()
    assert (tmp_path / "my_pkg" / "bye.md").is_file()


def test_package_new_returns_all_paths(tmp_path):
    written = package_new("x", tmp_path, skills=["a", "b"], capabilities=["c"])
    names = {p.name for p in written}
    assert "pyproject.toml" in names
    assert "__init__.py" in names
    assert "a.md" in names
    assert "b.md" in names


# ---------------------------------------------------------------------------
# package_new: pyproject content
# ---------------------------------------------------------------------------

def test_package_pyproject_parses(tmp_path):
    package_new("my-pkg", tmp_path, skills=["hello"], capabilities=["greeting"])
    data = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert data["project"]["name"] == "my-pkg"
    pkg = data["tool"]["spindle"]["package"]
    assert "hello" in pkg["skills"]
    assert "greeting" in pkg["capabilities"]


def test_package_pyproject_importable_name(tmp_path):
    package_new("my-pkg", tmp_path, skills=[], capabilities=[])
    data = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    packages = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert "my_pkg" in packages


def test_package_pyproject_empty_skills_and_caps(tmp_path):
    package_new("solo", tmp_path, skills=[], capabilities=[])
    data = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    pkg = data["tool"]["spindle"]["package"]
    assert pkg["skills"] == []
    assert pkg["capabilities"] == []


# ---------------------------------------------------------------------------
# dist_new: file structure
# ---------------------------------------------------------------------------

def test_dist_new_creates_pyproject(tmp_path):
    dist_new("my-dist", tmp_path, source_dir="../../", packages=["pkg-a"])
    assert (tmp_path / "pyproject.toml").is_file()


def test_dist_new_creates_preempt_md(tmp_path):
    dist_new("my-dist", tmp_path, source_dir="../../", packages=[])
    assert (tmp_path / "preempt.md").is_file()


def test_dist_new_returns_two_paths(tmp_path):
    written = dist_new("my-dist", tmp_path, source_dir="../../", packages=["x"])
    assert len(written) == 2
    names = {p.name for p in written}
    assert "pyproject.toml" in names
    assert "preempt.md" in names


# ---------------------------------------------------------------------------
# dist_new: pyproject content
# ---------------------------------------------------------------------------

def test_dist_pyproject_parses(tmp_path):
    dist_new("my-dist", tmp_path, source_dir="../../", packages=["pkg-a", "pkg-b"])
    data = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert data["project"]["name"] == "my-dist"
    dist = data["tool"]["spindle"]["distribution"]
    assert dist["source_dir"] == "../../"
    assert dist["preempt_snippet"] == "preempt.md"


def test_dist_pyproject_deps(tmp_path):
    dist_new("my-dist", tmp_path, source_dir="../../", packages=["pkg-a", "pkg-b"])
    data = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    deps = data["project"]["dependencies"]
    assert "pkg-a" in deps
    assert "pkg-b" in deps


def test_dist_pyproject_display_name_derived(tmp_path):
    dist_new("my-dist", tmp_path, source_dir=".", packages=[])
    data = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    assert data["tool"]["spindle"]["distribution"]["display_name"] == "My Dist"


# ---------------------------------------------------------------------------
# CLI wiring: spindle package new
# ---------------------------------------------------------------------------

from spindle.cli import main as cli_main


def test_cli_package_new_exits_zero(tmp_path):
    rc = cli_main(["package", "new", "my-tools", "--dest", str(tmp_path / "my-tools")])
    assert rc == 0


def test_cli_package_new_prints_written_paths(tmp_path, capsys):
    cli_main(["package", "new", "my-tools", "--dest", str(tmp_path / "my-tools")])
    out = capsys.readouterr().out
    assert "pyproject.toml" in out
    assert "__init__.py" in out


def test_cli_package_new_with_skills_creates_md(tmp_path):
    dest = tmp_path / "my-tools"
    cli_main(["package", "new", "my-tools", "--dest", str(dest), "--skill", "search", "--skill", "summarise"])
    assert (dest / "my_tools" / "search.md").is_file()
    assert (dest / "my_tools" / "summarise.md").is_file()


def test_cli_package_new_bad_name_exits_nonzero(tmp_path, capsys):
    rc = cli_main(["package", "new", "Bad_Name", "--dest", str(tmp_path / "out")])
    assert rc != 0
    assert "error" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# CLI wiring: spindle dist new
# ---------------------------------------------------------------------------


def test_cli_dist_new_exits_zero(tmp_path):
    rc = cli_main(["dist", "new", "my-dist", "--dest", str(tmp_path / "my-dist")])
    assert rc == 0


def test_cli_dist_new_prints_written_paths(tmp_path, capsys):
    cli_main(["dist", "new", "my-dist", "--dest", str(tmp_path / "my-dist")])
    out = capsys.readouterr().out
    assert "pyproject.toml" in out
    assert "preempt.md" in out


def test_cli_dist_new_with_packages_in_deps(tmp_path):
    dest = tmp_path / "my-dist"
    cli_main([
        "dist", "new", "my-dist",
        "--dest", str(dest),
        "--package", "sample-grill==0.2.0",
        "--source-dir", "../../",
    ])
    data = tomllib.loads((dest / "pyproject.toml").read_text())
    assert any("sample-grill" in d for d in data["project"]["dependencies"])


def test_cli_dist_new_bad_name_exits_nonzero(tmp_path, capsys):
    rc = cli_main(["dist", "new", "Bad_Name", "--dest", str(tmp_path / "out")])
    assert rc != 0
    assert "error" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# CLI integration: scaffold → uv install -e → spindle package list → uninstall
# ---------------------------------------------------------------------------

import subprocess
import sys


def test_scaffold_install_list_uninstall(tmp_path):
    """Full lifecycle: scaffold a package, install it editably, confirm spindle package list
    finds it, then uninstall."""
    pkg_name = "spindle-inttest-smoke"
    dest = tmp_path / pkg_name

    # 1. Scaffold via CLI
    rc = cli_main(["package", "new", pkg_name, "--dest", str(dest), "--skill", "demo"])
    assert rc == 0
    assert (dest / "pyproject.toml").is_file()

    try:
        # 2. Install editable into the active venv
        install = subprocess.run(
            ["uv", "pip", "install", "-e", str(dest)],
            capture_output=True,
            text=True,
        )
        assert install.returncode == 0, f"uv pip install failed:\n{install.stderr}"

        # 3. spindle package list must show the package — run in a fresh subprocess so
        #    importlib.metadata picks up the newly installed .dist-info
        listed = subprocess.run(
            [sys.executable, "-c",
             "from spindle.cli import main; import sys; sys.exit(main(['package', 'list']))"],
            capture_output=True,
            text=True,
        )
        assert listed.returncode == 0, f"spindle package list failed:\n{listed.stderr}"
        assert pkg_name in listed.stdout, (
            f"{pkg_name!r} not in `spindle package list` output:\n{listed.stdout}"
        )
    finally:
        # 4. Always uninstall to keep the test environment clean.
        # `uv pip uninstall` doesn't prompt and has no --yes flag (the
        # earlier version of this test passed --yes and silently no-op'd,
        # leaving an editable install behind that broke test_packages).
        subprocess.run(
            ["uv", "pip", "uninstall", pkg_name],
            capture_output=True,
        )
