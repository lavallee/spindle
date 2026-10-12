"""CLI coverage for session-local skill realization."""

from __future__ import annotations

import json

from spindle.cli import main


def _skill(tmp_path):
    root = tmp_path / "review"
    overlays = root / "overlays"
    overlays.mkdir(parents=True)
    (root / "SKILL.md").write_text("---\nname: review\n---\n\n# Review\n")
    (overlays / "codex.md").write_text("Focus on correctness.\n")
    (root / "spindle-realization.toml").write_text(
        """schema_version = 1

[[profile]]
id = "codex-review"
overlay = "overlays/codex.md"

[profile.match]
harness = "codex"
model = "gpt-sol"
effort = "high"
role = "reviewer"
"""
    )
    return root


def test_realize_json_reports_matched_profile(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    skill = _skill(tmp_path)

    rc = main(
        [
            "realize",
            str(skill),
            "--session-id",
            "parent",
            "--harness",
            "codex",
            "--model",
            "gpt-sol",
            "--effort",
            "high",
            "--role",
            "reviewer",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["status"] == "matched"
    assert payload["profile_id"] == "codex-review"
    assert payload["tuned"] is True


def test_realize_requires_session_identity(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("SPINDLE_SESSION_ID", raising=False)
    skill = _skill(tmp_path)

    rc = main(["realize", str(skill), "--harness", "codex"])

    assert rc == 1
    assert "routing must be session-local" in capsys.readouterr().err


def test_realize_accepts_session_identity_from_environment(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("SPINDLE_SESSION_ID", "child")
    skill = _skill(tmp_path)

    rc = main(
        [
            "realize",
            str(skill),
            "--harness",
            "codex",
            "--model",
            "gpt-sol",
            "--effort",
            "high",
            "--role",
            "reviewer",
        ]
    )

    assert rc == 0
    assert "session 'child'" in capsys.readouterr().out


def test_realize_accepts_complete_coordinate_from_environment(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("SPINDLE_SESSION_ID", "child-env")
    monkeypatch.setenv("SPINDLE_HARNESS", "codex")
    monkeypatch.setenv("SPINDLE_REQUESTED_MODEL", "gpt-sol")
    monkeypatch.setenv("SPINDLE_SERVED_MODEL", "gpt-sol")
    monkeypatch.setenv("SPINDLE_EFFORT", "high")
    monkeypatch.setenv("SPINDLE_AGENT_ROLE", "reviewer")
    skill = _skill(tmp_path)

    rc = main(["realize", str(skill), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["status"] == "matched"
    assert payload["profile_id"] == "codex-review"


def test_strict_realize_rejects_conservative_fallback(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    skill = _skill(tmp_path)

    rc = main(
        [
            "realize",
            str(skill),
            "--session-id",
            "unknown",
            "--harness",
            "codex",
            "--model",
            "not-evaluated",
            "--strict",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 2
    assert "resolution: unresolved" in captured.out
    assert "requires an evaluated matching profile" in captured.err


def test_realize_blocks_invalid_manifest(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    skill = _skill(tmp_path)
    (skill / "spindle-realization.toml").write_text("schema_version = 9\n")

    rc = main(
        [
            "realize",
            str(skill),
            "--session-id",
            "broken",
            "--harness",
            "codex",
        ]
    )

    assert rc == 1
    assert "schema_version must be 1" in capsys.readouterr().err
