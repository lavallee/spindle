"""The marketplace plugin remains a thin, executable view of Spindle itself."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from spindle import __version__, operator


ROOT = Path(__file__).parents[1]


def test_dual_harness_manifests_share_identity_and_package_version():
    claude = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    codex = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text())

    assert claude["name"] == codex["name"] == "spindle"
    assert claude["version"] == codex["version"] == __version__ == "0.2.0"
    assert codex["skills"] == "./skills/"


def test_plugin_skill_is_the_editable_and_packaged_operator_source():
    skill = ROOT / "skills" / "spindle"

    assert operator.bundled_skill_path().resolve() == skill.resolve()
    assert (skill / "SKILL.md").is_file()
    assert (skill / "agents" / "openai.yaml").is_file()
    assert (skill / "scripts" / "spindle").is_file()


def test_plugin_launcher_runs_the_checked_out_cli():
    result = subprocess.run(
        [str(ROOT / "skills" / "spindle" / "scripts" / "spindle"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "harness" in result.stdout
