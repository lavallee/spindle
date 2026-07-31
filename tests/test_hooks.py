"""Ownership, merge, trust, and heartbeat coverage for native hook kits."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from spindle import hooks as hooks_mod
from spindle.hooks import (
    HookOwnershipStore,
    desired_fragments,
    hook_status,
    install_hooks,
    plan_hooks,
    remove_hooks,
)
from spindle.lifecycle import LifecycleError
from spindle.startup import run_startup


def _isolate(monkeypatch, tmp_path):
    state = tmp_path / "state"
    home = tmp_path / "home"
    monkeypatch.setenv("SPINDLE_HOME", str(state))
    monkeypatch.setenv("HOME", str(home))
    home.mkdir()
    return home


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def _store(tmp_path: Path) -> HookOwnershipStore:
    return HookOwnershipStore(
        receipt_root=tmp_path / "receipts",
        index_file=tmp_path / "hook-index.json",
    )


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_claude_install_merges_preserves_mode_and_is_idempotent(tmp_path, monkeypatch):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    target = repo / ".claude" / "settings.json"
    target.parent.mkdir()
    foreign_group = {
        "matcher": "compact",
        "hooks": [{"type": "command", "command": "foreign-hook"}],
    }
    target.write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Read"]},
                "hooks": {"SessionStart": [foreign_group]},
            }
        ),
        encoding="utf-8",
    )
    target.chmod(0o640)
    store = _store(tmp_path)

    result = install_hooks(repo, "claude", home=home, ownership_store=store)
    installed = _read(target)
    second = install_hooks(repo, "claude", home=home, ownership_store=store)

    assert result.action == "installed"
    assert len(result.plan.additions) == 3
    assert result.receipt is not None
    assert installed["permissions"] == {"allow": ["Read"]}
    assert foreign_group in installed["hooks"]["SessionStart"]
    assert target.stat().st_mode & 0o777 == 0o640
    assert second.action == "no-change"
    assert _read(target) == installed
    assert second.receipt == result.receipt


def test_exact_unowned_handlers_are_foreign_and_never_removed(tmp_path, monkeypatch):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    target = repo / ".claude" / "settings.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            {
                "hooks": {
                    fragment.event: [fragment.group]
                    for fragment in desired_fragments("claude")
                }
            }
        ),
        encoding="utf-8",
    )
    store = _store(tmp_path)

    plan = plan_hooks(repo, "claude", home=home, ownership_store=store)
    installed = install_hooks(repo, "claude", home=home, ownership_store=store)
    removed = remove_hooks(repo, "claude", home=home, ownership_store=store)

    assert not plan.additions
    assert len(plan.foreign_present) == 3
    assert installed.action == "no-change"
    assert installed.receipt is None
    assert removed.action == "not-owned"
    assert target.is_file()
    assert len(_read(target)["hooks"]) == 3


def test_remove_deletes_only_owned_fragments_and_preserves_unrelated(
    tmp_path, monkeypatch
):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    store = _store(tmp_path)
    target = repo / ".claude" / "settings.json"
    installed = install_hooks(repo, "claude", home=home, ownership_store=store)
    assert installed.action == "installed"
    payload = _read(target)
    payload["env"] = {"KEEP": "yes"}
    payload["hooks"]["Stop"] = [
        {"hooks": [{"type": "command", "command": "foreign-stop"}]}
    ]
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = remove_hooks(repo, "claude", home=home, ownership_store=store)
    remaining = _read(target)

    assert result.action == "removed"
    assert remaining == {
        "env": {"KEEP": "yes"},
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "foreign-stop"}]}]
        },
    }
    assert store.get(target) is None


def test_modified_owned_fragment_blocks_removal(tmp_path, monkeypatch):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    store = _store(tmp_path)
    target = repo / ".claude" / "settings.json"
    install_hooks(repo, "claude", home=home, ownership_store=store)
    payload = _read(target)
    payload["hooks"]["SessionStart"][0]["matcher"] = "startup"
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = remove_hooks(repo, "claude", home=home, ownership_store=store)

    assert result.action == "blocked:ownership-mismatch"
    assert _read(target) == payload
    assert store.get(target) is not None


def test_codex_shape_and_inline_toml_conflict(tmp_path, monkeypatch):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    store = _store(tmp_path)
    config = repo / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text("[hooks]\n", encoding="utf-8")

    plan = plan_hooks(repo, "codex", home=home, ownership_store=store)
    result = install_hooks(repo, "codex", home=home, ownership_store=store)

    assert plan.blockers
    assert "same layer" in plan.blockers[0]
    assert result.action == "blocked"
    assert not (repo / ".codex" / "hooks.json").exists()
    handler = desired_fragments("codex")[0].group["hooks"][0]
    assert handler["command"].startswith("spindle bootstrap --hook codex")
    assert handler["additionalContextLimit"] == 5000


def test_invalid_json_and_dry_run_do_not_mutate(tmp_path, monkeypatch):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    store = _store(tmp_path)
    target = repo / ".claude" / "settings.json"
    target.parent.mkdir()
    target.write_text("{broken", encoding="utf-8")

    with pytest.raises(LifecycleError, match="invalid JSON"):
        install_hooks(repo, "claude", home=home, ownership_store=store)
    assert target.read_text(encoding="utf-8") == "{broken"

    target.unlink()
    result = install_hooks(
        repo, "claude", dry_run=True, home=home, ownership_store=store
    )
    assert result.action == "would-install"
    assert not target.exists()
    assert not store.index_file.exists()


def test_status_separates_definition_heartbeat_and_disabled_control(
    tmp_path, monkeypatch
):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    store = _store(tmp_path)
    install_hooks(repo, "codex", home=home, ownership_store=store)

    configured = hook_status(repo, "codex", home=home, ownership_store=store)
    run_startup(
        repo,
        "codex",
        event_source="startup",
        adapter_build="codex-test",
        roots=(),
        home=home,
    )
    observed = hook_status(repo, "codex", home=home, ownership_store=store)
    config = repo / ".codex" / "config.toml"
    config.write_text("[features]\nhooks = false\n", encoding="utf-8")
    disabled = hook_status(repo, "codex", home=home, ownership_store=store)

    assert configured["state"] == "configured-unverified"
    assert configured["heartbeat"] is None
    assert observed["state"] == "observed"
    assert observed["heartbeat"]["event_source"] == "startup"
    assert disabled["state"] == "blocked"
    assert any("disabled" in item for item in disabled["blockers"])


def test_hook_fragments_are_stable_and_contain_no_desired_state():
    serialized = json.dumps(
        {
            harness: [fragment.to_dict() for fragment in desired_fragments(harness)]
            for harness in ("claude", "codex")
        },
        sort_keys=True,
    )

    assert "package_digest" not in serialized
    assert "lease" not in serialized
    assert "surface_lock" not in serialized
    assert "bootstrap" in serialized


@pytest.mark.parametrize(
    ("decision", "expected_state"),
    [("blocked", "blocked"), ("restart-required", "restart-required")],
)
def test_status_never_treats_unhealthy_heartbeat_as_observed(
    tmp_path, monkeypatch, decision, expected_state
):
    home = _isolate(monkeypatch, tmp_path)
    repo = _repo(tmp_path)
    store = _store(tmp_path)
    install_hooks(repo, "codex", home=home, ownership_store=store)
    monkeypatch.setattr(
        hooks_mod,
        "_latest_heartbeat",
        lambda *_args, **_kwargs: {
            "decision": decision,
            "event_source": "resume",
            "receipt_id": "sha256:" + "a" * 64,
        },
    )

    status = hook_status(repo, "codex", home=home, ownership_store=store)

    assert status["state"] == expected_state
    assert any(decision in blocker for blocker in status["blockers"])


def test_concurrent_hook_installs_preserve_both_ownership_entries(
    tmp_path, monkeypatch
):
    home = _isolate(monkeypatch, tmp_path)
    first = _repo(tmp_path)
    second = tmp_path / "repo-two"
    second.mkdir()
    (second / ".git").mkdir()
    store = _store(tmp_path)
    errors: list[BaseException] = []

    def install(repo: Path, harness: str) -> None:
        try:
            install_hooks(repo, harness, home=home, ownership_store=store)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [
        threading.Thread(target=install, args=(first, "claude")),
        threading.Thread(target=install, args=(second, "codex")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert not errors
    assert store.get(first / ".claude" / "settings.json") is not None
    assert store.get(second / ".codex" / "hooks.json") is not None
