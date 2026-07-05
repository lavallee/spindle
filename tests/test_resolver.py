"""Tests for spindle.resolver — input validation and ResolverError behaviour."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spindle.resolver import ResolverError, _classify_source, uv_install, uv_lock, uv_uninstall


class TestClassifySource:
    def test_absolute_path_is_local(self):
        assert _classify_source("/abs/path/to/pkg") == "local"

    def test_relative_dotslash_is_local(self):
        assert _classify_source("./some/dir") == "local"

    def test_relative_dotdotslash_is_local(self):
        assert _classify_source("../sibling/dir") == "local"

    def test_git_https_url(self):
        assert _classify_source("git+https://github.com/org/repo") == "git"

    def test_git_ssh_url(self):
        assert _classify_source("git+ssh://git@github.com/org/repo") == "git"

    def test_plain_pypi_name(self):
        assert _classify_source("sample-grill") == "pypi"

    def test_pypi_name_with_version_pin(self):
        assert _classify_source("sample-grill==0.2.0") == "pypi"

    def test_pypi_name_with_gte_constraint(self):
        assert _classify_source("requests>=2.0") == "pypi"

    def test_invalid_source_raises_resolver_error(self):
        with pytest.raises(ResolverError, match="Cannot determine source type"):
            _classify_source("???not-valid???")

    def test_empty_string_raises_resolver_error(self):
        with pytest.raises(ResolverError):
            _classify_source("")


class TestResolverError:
    def test_is_exception(self):
        err = ResolverError("boom")
        assert isinstance(err, Exception)

    def test_message_accessible_via_str(self):
        err = ResolverError("something went wrong")
        assert "something went wrong" in str(err)

    def test_stderr_attribute(self):
        err = ResolverError("failure", stderr="uv: command not found")
        assert err.stderr == "uv: command not found"

    def test_stderr_defaults_to_empty_string(self):
        err = ResolverError("failure")
        assert err.stderr == ""


def _make_completed(returncode=0, stdout="", stderr=""):
    cp = MagicMock(spec=subprocess.CompletedProcess)
    cp.returncode = returncode
    cp.stdout = stdout
    cp.stderr = stderr
    return cp


class TestUvInstall:
    def test_local_path_uses_editable_flag(self):
        with patch("subprocess.run", return_value=_make_completed()) as mock_run:
            uv_install("./my-dist")
        argv = mock_run.call_args[0][0]
        assert "-e" in argv
        assert "./my-dist" in argv

    def test_pypi_name_no_editable_flag(self):
        with patch("subprocess.run", return_value=_make_completed()) as mock_run:
            uv_install("sample-grill==0.2.0")
        argv = mock_run.call_args[0][0]
        assert "-e" not in argv
        assert "sample-grill==0.2.0" in argv

    def test_git_url_no_editable_flag(self):
        with patch("subprocess.run", return_value=_make_completed()) as mock_run:
            uv_install("git+https://github.com/org/repo")
        argv = mock_run.call_args[0][0]
        assert "-e" not in argv

    def test_returns_stdout_stderr_tuple(self):
        with patch("subprocess.run", return_value=_make_completed(stdout="ok", stderr="warn")):
            out, err = uv_install("sample-grill")
        assert out == "ok"
        assert err == "warn"

    def test_nonzero_exit_raises_resolver_error(self):
        with patch("subprocess.run", return_value=_make_completed(returncode=1, stderr="err")):
            with pytest.raises(ResolverError) as exc_info:
                uv_install("sample-grill")
        assert exc_info.value.stderr == "err"

    def test_invalid_source_raises_resolver_error_before_subprocess(self):
        with patch("subprocess.run") as mock_run:
            with pytest.raises(ResolverError, match="Cannot determine source type"):
                uv_install("???bad???")
        mock_run.assert_not_called()


class TestUvUninstall:
    def test_valid_name_calls_uv(self):
        with patch("subprocess.run", return_value=_make_completed()) as mock_run:
            uv_uninstall("sample-grill")
        argv = mock_run.call_args[0][0]
        assert "uninstall" in argv
        assert "sample-grill" in argv

    def test_returns_stdout_stderr_tuple(self):
        with patch("subprocess.run", return_value=_make_completed(stdout="done", stderr="")):
            out, err = uv_uninstall("sample-grill")
        assert out == "done"
        assert err == ""

    def test_nonzero_exit_raises_resolver_error(self):
        with patch("subprocess.run", return_value=_make_completed(returncode=1, stderr="not found")):
            with pytest.raises(ResolverError) as exc_info:
                uv_uninstall("sample-grill")
        assert "not found" in exc_info.value.stderr

    def test_invalid_name_raises_before_subprocess(self):
        with patch("subprocess.run") as mock_run:
            with pytest.raises(ResolverError, match="Invalid package name"):
                uv_uninstall("???bad name???")
        mock_run.assert_not_called()


class TestUvLock:
    def test_calls_uv_lock_with_cwd(self, tmp_path):
        with patch("subprocess.run", return_value=_make_completed()) as mock_run:
            uv_lock(tmp_path)
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] == tmp_path

    def test_argv_contains_lock_subcommand(self, tmp_path):
        with patch("subprocess.run", return_value=_make_completed()) as mock_run:
            uv_lock(tmp_path)
        argv = mock_run.call_args[0][0]
        assert argv == ["uv", "lock"]

    def test_returns_stdout_stderr_tuple(self, tmp_path):
        with patch("subprocess.run", return_value=_make_completed(stdout="locked", stderr="")):
            out, err = uv_lock(tmp_path)
        assert out == "locked"

    def test_nonzero_exit_raises_resolver_error(self, tmp_path):
        with patch("subprocess.run", return_value=_make_completed(returncode=2, stderr="lock fail")):
            with pytest.raises(ResolverError) as exc_info:
                uv_lock(tmp_path)
        assert "lock fail" in exc_info.value.stderr
