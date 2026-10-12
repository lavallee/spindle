"""Harness-native Spindle operator lifecycle and context contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spindle import operator
from spindle.lifecycle import (
    ExpectedProjection,
    OwnershipRecord,
    OwnershipStore,
    SurfaceLock,
    digest_path,
    read_surface_lock,
    surface_id,
    write_surface_lock,
)


def _isolate(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(home))
    return home


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


@pytest.mark.parametrize(
    ("harness", "relative_target", "hook_target", "invocation"),
    (
        ("codex", ".agents/skills/spindle", ".codex/hooks.json", "$spindle"),
        ("claude", ".claude/skills/spindle", ".claude/settings.json", "/spindle"),
    ),
)
def test_setup_is_dry_runnable_owned_and_idempotent(
    tmp_path,
    monkeypatch,
    harness,
    relative_target,
    hook_target,
    invocation,
):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)

    dry_run = operator.setup_operator(repo, harness, dry_run=True, home=home)

    assert dry_run["action"] == "would-install"
    assert dry_run["requires_new_session"] is True
    assert dry_run["plan"]["workspace"]["operator_projection"]["vcs"].endswith(
        "do not commit"
    )
    assert not (tmp_path / "state").exists()
    assert not (repo / relative_target).exists()
    assert not (repo / hook_target).exists()

    installed = operator.setup_operator(repo, harness, home=home)
    target = repo / relative_target
    lock = read_surface_lock(surface_id(repo, harness))

    assert installed["action"] == "install"
    assert installed["startup"]["receipt"]["decision"] in {"ok", "warn"}
    assert installed["hooks"]["action"] == "installed"
    assert target.is_symlink()
    assert lock is not None
    projection = next(item for item in lock.projections if item.skill == "spindle")
    assert projection.authority.startswith(operator.OPERATOR_AUTHORITY_PREFIX)
    assert target.resolve() == Path(projection.source_path).resolve()
    assert OwnershipStore().records(lock.surface_id)[
        str(target.absolute())
    ].matches_symlink(target)

    status = operator.operator_status(repo, harness, home=home)
    context = operator.harness_context(
        repo, harness, home=home, environ={}
    )
    second = operator.setup_operator(repo, harness, home=home)

    assert status["state"] == "current"
    assert status["hooks"]["state"] == "configured-unverified"
    assert status["invocation"] == invocation
    assert status["workspace"]["hook_configuration"]["path"].endswith(hook_target)
    assert context["schema"] == operator.HARNESS_CONTEXT_SCHEMA
    assert context["surface"]["harness"] == harness
    assert context["surface"]["harness_detected_by"] == "explicit"
    assert context["operator"]["state"] == "current"
    assert context["authorization"]["default_when_ambiguous"].endswith("never adopt")
    assert any(item["intent"] == "try-once" for item in context["actions"])
    assert second["action"] == "no-change"
    assert second["hooks"]["action"] == "no-change"
    assert second["requires_new_session"] is False


@pytest.mark.parametrize("harness", ("codex", "claude"))
def test_remove_is_dry_runnable_and_removes_only_owned_state(
    tmp_path, monkeypatch, harness
):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    operator.setup_operator(repo, harness, home=home)
    foreign = repo / (".codex/keep.json" if harness == "codex" else ".claude/keep.json")
    foreign.write_text('{"owner":"user"}\n', encoding="utf-8")
    target = repo / (
        ".agents/skills/spindle" if harness == "codex" else ".claude/skills/spindle"
    )

    dry_run = operator.remove_operator(repo, harness, dry_run=True, home=home)

    assert dry_run["action"] == "would-remove"
    assert target.is_symlink()
    assert foreign.exists()

    removed = operator.remove_operator(repo, harness, home=home)
    lock = read_surface_lock(surface_id(repo, harness))

    assert removed["action"] == "removed"
    assert not target.exists() and not target.is_symlink()
    assert foreign.read_text(encoding="utf-8") == '{"owner":"user"}\n'
    assert lock is not None
    assert not any(
        item.authority.startswith(operator.OPERATOR_AUTHORITY_PREFIX)
        for item in lock.projections
    )
    assert operator.operator_status(repo, harness, home=home)["state"] == "missing"


def test_setup_blocks_a_foreign_operator_target_without_mutation(
    tmp_path, monkeypatch
):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    target = repo / ".agents" / "skills" / "spindle"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("# user spindle\n", encoding="utf-8")

    result = operator.setup_operator(repo, "codex", home=home)

    assert result["action"] == "blocked"
    assert "foreign" in " ".join(result["plan"]["blockers"])
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "# user spindle\n"
    assert read_surface_lock(surface_id(repo, "codex")) is None
    assert not (repo / ".codex" / "hooks.json").exists()


def test_operator_status_stays_separate_from_a_modified_owned_hook(
    tmp_path, monkeypatch
):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    operator.setup_operator(repo, "codex", home=home)
    hook_file = repo / ".codex" / "hooks.json"
    payload = json.loads(hook_file.read_text(encoding="utf-8"))
    payload["hooks"]["SessionStart"][0]["hooks"][0]["command"] = "changed"
    hook_file.write_text(json.dumps(payload), encoding="utf-8")

    status = operator.operator_status(repo, "codex", home=home)
    retried = operator.setup_operator(repo, "codex", home=home)

    assert status["state"] == "current"
    assert status["hooks"]["state"] == "blocked"
    assert retried["action"] == "partial"
    assert retried["operator_ready"] is True
    assert retried["hooks"]["action"] == "blocked"


def test_setup_preserves_other_lifecycle_projections(tmp_path, monkeypatch):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    source = tmp_path / "adopted"
    source.mkdir()
    (source / "SKILL.md").write_text("# adopted\n", encoding="utf-8")
    target = repo / ".agents" / "skills" / "adopted"
    target.parent.mkdir(parents=True)
    target.symlink_to(source)
    sid = surface_id(repo, "codex")
    digest = digest_path(source)
    adopted = ExpectedProjection(
        skill="adopted",
        projection_path=str(target.absolute()),
        source_path=str(source.resolve()),
        source_digest=digest,
        package_digest=digest,
        authority="adoption:sha256:" + "a" * 64,
    )
    write_surface_lock(
        SurfaceLock(
            surface_id=sid,
            surface_name="repo",
            repo_path=str(repo.resolve()),
            harness="codex",
            binding_coordinate="adoption-only/v1",
            projections=(adopted,),
            adoption_ids=("sha256:" + "a" * 64,),
        )
    )
    OwnershipStore().record(
        OwnershipRecord(
            surface_id=sid,
            surface_name="repo",
            harness="codex",
            skill="adopted",
            projection_path=str(target.absolute()),
            source_path=str(source.resolve()),
            source_digest=digest,
            package_digest=digest,
            creation_receipt_id="adoption:sha256:" + "a" * 64,
        )
    )

    operator.setup_operator(repo, "codex", home=home)
    lock = read_surface_lock(sid)

    assert lock is not None
    assert lock.adoption_ids == ("sha256:" + "a" * 64,)
    assert {item.skill for item in lock.projections} == {"adopted", "spindle"}
    assert target.resolve() == source.resolve()


def test_unrelated_ambient_conflicts_do_not_block_operator_bootstrap(
    tmp_path, monkeypatch
):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    for folder in ("one", "two"):
        skill = home / ".claude" / "skills" / folder
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: duplicate\ndescription: duplicate fixture\n---\n",
            encoding="utf-8",
        )

    result = operator.setup_operator(repo, "claude", home=home)

    assert result["action"] == "install"
    assert result["operator_ready"] is True
    assert result["surface_ready"] is False
    assert result["startup"]["receipt"]["decision"] == "blocked"
    assert (repo / ".claude" / "skills" / "spindle").is_symlink()
    assert result["hooks"]["action"] == "installed"


def test_detect_harness_uses_explicit_environment_and_surface_lock(
    tmp_path, monkeypatch
):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    monkeypatch.setattr(operator, "_detect_process_harness", lambda: None)

    assert operator.detect_harness("claude", environ={}, repo_path=repo) == (
        "claude",
        "explicit",
    )
    assert operator.detect_harness(
        environ={"CODEX_THREAD_ID": "thread"}, repo_path=repo
    ) == ("codex", "environment")
    assert operator.detect_harness(
        environ={"CLAUDECODE": "1"}, repo_path=repo
    ) == ("claude", "environment")
    with pytest.raises(ValueError, match="both Codex and Claude"):
        operator.detect_harness(
            environ={"CODEX_CI": "1", "CLAUDECODE": "1"}, repo_path=repo
        )
    with pytest.raises(ValueError, match="cannot determine"):
        operator.detect_harness(environ={}, repo_path=repo)

    operator.setup_operator(repo, "codex", home=home)
    assert operator.detect_harness(environ={}, repo_path=repo) == (
        "codex",
        "surface-lock",
    )


def test_detect_harness_prefers_nearest_process_over_inherited_markers(
    tmp_path, monkeypatch
):
    _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    monkeypatch.setattr(operator, "_detect_process_harness", lambda: "claude")

    assert operator.detect_harness(
        environ={"CODEX_THREAD_ID": "parent", "CLAUDECODE": "1"}, repo_path=repo
    ) == ("claude", "process-tree")


def test_bundled_operator_is_intentionally_small_and_has_a_trigger_boundary():
    skill = operator.bundled_skill_path() / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    metadata = text.split("---", 2)[1]

    assert len(text.split()) < 220
    assert "Do not trigger for ordinary work" in metadata
    assert "spindle harness context --here --json" in text
    assert (skill.parent / "agents" / "openai.yaml").is_file()
