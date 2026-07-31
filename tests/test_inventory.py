"""Effective cross-scope inventory and safe reconciliation tests."""

from __future__ import annotations

import json
from pathlib import Path

import spindle.inventory as inventory_mod
from spindle.inventory import (
    DisabledRules,
    DiscoveryRoot,
    InventoryDigestCache,
    InventoryState,
    default_discovery_roots,
    load_disabled_rules,
    reconcile_owned,
    scan_effective_inventory,
)
from spindle.lifecycle import (
    ExpectedProjection,
    OwnershipRecord,
    OwnershipStore,
    SurfaceLock,
    digest_path,
    surface_id,
)


def _skill(root: Path, name: str, body: str = "Use the evidence.\n") -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Exercise {name}.\n---\n\n{body}",
        encoding="utf-8",
    )
    return skill


def _store(tmp_path: Path) -> OwnershipStore:
    return OwnershipStore(
        receipt_root=tmp_path / "ownership-receipts",
        index_root=tmp_path / "ownership-index",
    )


def _record(
    store: OwnershipStore,
    *,
    repo: Path,
    projection: Path,
    source: Path,
    name: str,
    harness: str = "codex",
) -> OwnershipRecord:
    digest = digest_path(source)
    record = OwnershipRecord(
        surface_id=surface_id(repo, harness),
        surface_name=repo.name,
        harness=harness,
        skill=name,
        projection_path=str(projection.absolute()),
        source_path=str(source.resolve()),
        source_digest=digest,
        package_digest=digest,
        creation_receipt_id="binding:test",
    )
    store.record(record)
    return record


def _lock(
    repo: Path,
    harness: str,
    expected: list[tuple[str, Path, Path, str | None]],
) -> SurfaceLock:
    projections = []
    for name, projection, source, digest_override in expected:
        digest = digest_override or digest_path(source)
        projections.append(
            ExpectedProjection(
                skill=name,
                projection_path=str(projection.absolute()),
                source_path=str(source.resolve()),
                source_digest=digest,
                package_digest=digest,
            )
        )
    return SurfaceLock(
        surface_id=surface_id(repo, harness),
        surface_name=repo.name,
        repo_path=str(repo.resolve()),
        harness=harness,
        binding_coordinate="binding:test",
        projections=tuple(projections),
    )


def test_polluted_fixture_classifies_every_ownership_boundary(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    project_root = repo / ".agents" / "skills"
    user_root = tmp_path / "home" / ".agents" / "skills"
    admin_root = tmp_path / "etc" / "skills"
    project_root.mkdir(parents=True)
    user_root.mkdir(parents=True)
    admin_root.mkdir(parents=True)
    sources = tmp_path / "sources"
    store = _store(tmp_path)

    exact_source = _skill(sources, "exact")
    exact = project_root / "exact"
    exact.symlink_to(exact_source)
    _record(store, repo=repo, projection=exact, source=exact_source, name="exact")

    stale_source = _skill(sources, "stale")
    stale = project_root / "stale"
    stale.symlink_to(stale_source)
    _record(store, repo=repo, projection=stale, source=stale_source, name="stale")

    replaced_source = _skill(sources, "replaced-original")
    replaced = project_root / "ambiguous"
    replaced.symlink_to(replaced_source)
    _record(
        store,
        repo=repo,
        projection=replaced,
        source=replaced_source,
        name="ambiguous",
    )
    replaced.unlink()
    foreign_replacement = _skill(sources, "ambiguous-foreign")
    replaced.symlink_to(foreign_replacement)

    foreign_source = _skill(sources, "foreign-link")
    (user_root / "foreign-link").symlink_to(foreign_source)
    _skill(user_root, "foreign-dir")

    _skill(project_root, "duplicate")
    _skill(user_root, "duplicate")

    (project_root / "broken").symlink_to(sources / "does-not-exist")
    _skill(project_root, "disabled")
    missing_source = _skill(sources, "missing")

    lock = _lock(
        repo,
        "codex",
        [
            ("exact", exact, exact_source, None),
            ("missing", project_root / "missing", missing_source, None),
        ],
    )
    roots = (
        DiscoveryRoot("repo:.", project_root, precedence=100),
        DiscoveryRoot("user", user_root, precedence=50),
        DiscoveryRoot("admin", admin_root, precedence=200),
        DiscoveryRoot("plugins", None, kind="opaque", detail="adapter required"),
    )

    first = scan_effective_inventory(
        repo,
        "codex",
        lock=lock,
        ownership_store=store,
        roots=roots,
        disabled=DisabledRules(names=frozenset({"disabled"})),
    )
    second = scan_effective_inventory(
        repo,
        "codex",
        lock=lock,
        ownership_store=store,
        roots=roots,
        disabled=DisabledRules(names=frozenset({"disabled"})),
    )

    states = {
        (entry.name, entry.scope): entry.state
        for entry in first.entries
        if entry.name != "duplicate"
    }
    assert states[("exact", "repo:.")] is InventoryState.EXPECTED_OWNED
    assert states[("stale", "repo:.")] is InventoryState.STALE_OWNED
    assert states[("ambiguous-foreign", "repo:.")] is (
        InventoryState.AMBIGUOUS_OWNERSHIP
    )
    assert states[("foreign-link", "user")] is InventoryState.FOREIGN
    assert states[("foreign-dir", "user")] is InventoryState.FOREIGN
    assert states[("broken", "repo:.")] is InventoryState.BROKEN
    assert states[("disabled", "repo:.")] is InventoryState.DISABLED
    assert states[("missing", "expected")] is InventoryState.MISSING
    assert states[("__plugins__", "plugins")] is InventoryState.OPAQUE
    assert {entry.state for entry in first.entries if entry.name == "duplicate"} == {
        InventoryState.CONFLICTING
    }
    assert first.inventory_id == second.inventory_id
    assert first.to_dict() == second.to_dict()


def test_reconcile_removes_only_exact_stale_owned_projection(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = repo / ".agents" / "skills"
    root.mkdir(parents=True)
    sources = tmp_path / "sources"
    store = _store(tmp_path)

    stale_source = _skill(sources, "stale")
    stale = root / "stale"
    stale.symlink_to(stale_source)
    stale_record = _record(
        store, repo=repo, projection=stale, source=stale_source, name="stale"
    )

    foreign_source = _skill(sources, "foreign")
    foreign = root / "foreign"
    foreign.symlink_to(foreign_source)
    foreign_dir = _skill(root, "foreign-dir")

    roots = (DiscoveryRoot("repo:.", root),)
    inventory = scan_effective_inventory(
        repo, "codex", ownership_store=store, roots=roots
    )
    dry_actions = reconcile_owned(inventory, ownership_store=store, dry_run=True)
    assert [action.action for action in dry_actions] == ["would-remove"]
    assert stale.is_symlink()

    actions = reconcile_owned(inventory, ownership_store=store)

    assert [action.action for action in actions] == ["removed"]
    assert actions[0].ownership_id == stale_record.ownership_id
    assert not stale.exists()
    assert foreign.is_symlink()
    assert foreign.resolve() == foreign_source.resolve()
    assert foreign_dir.is_dir()
    assert str(stale.absolute()) not in store.records(surface_id(repo, "codex"))


def test_reconcile_preserves_user_retargeted_owned_name(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = repo / ".agents" / "skills"
    root.mkdir(parents=True)
    sources = tmp_path / "sources"
    store = _store(tmp_path)
    original = _skill(sources, "original")
    projection = root / "review"
    projection.symlink_to(original)
    _record(store, repo=repo, projection=projection, source=original, name="review")

    projection.unlink()
    replacement = _skill(sources, "replacement")
    projection.symlink_to(replacement)
    inventory = scan_effective_inventory(
        repo,
        "codex",
        ownership_store=store,
        roots=(DiscoveryRoot("repo:.", root),),
    )

    assert inventory.entries_for("replacement")[0].state is (
        InventoryState.AMBIGUOUS_OWNERSHIP
    )
    assert reconcile_owned(inventory, ownership_store=store) == ()
    assert projection.resolve() == replacement.resolve()


def test_owned_broken_link_can_be_removed_but_foreign_broken_link_is_preserved(
    tmp_path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = repo / ".agents" / "skills"
    root.mkdir(parents=True)
    source = _skill(tmp_path / "sources", "owned-broken")
    owned = root / "owned-broken"
    owned.symlink_to(source)
    store = _store(tmp_path)
    _record(store, repo=repo, projection=owned, source=source, name="owned-broken")
    source.rename(tmp_path / "moved-away")
    foreign = root / "foreign-broken"
    foreign.symlink_to(tmp_path / "never-there")

    inventory = scan_effective_inventory(
        repo,
        "codex",
        ownership_store=store,
        roots=(DiscoveryRoot("repo:.", root),),
    )
    actions = reconcile_owned(inventory, ownership_store=store)

    assert [action.skill for action in actions] == ["owned-broken"]
    assert not owned.is_symlink()
    assert foreign.is_symlink()


def test_editable_content_drift_is_stale_without_version_signal(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = repo / ".agents" / "skills"
    root.mkdir(parents=True)
    source = _skill(tmp_path / "sources", "review", "old\n")
    projection = root / "review"
    projection.symlink_to(source)
    store = _store(tmp_path)
    _record(store, repo=repo, projection=projection, source=source, name="review")
    old_digest = digest_path(source)
    lock = _lock(repo, "codex", [("review", projection, source, old_digest)])

    (source / "SKILL.md").write_text("same version, new content\n", encoding="utf-8")
    inventory = scan_effective_inventory(
        repo,
        "codex",
        lock=lock,
        ownership_store=store,
        roots=(DiscoveryRoot("repo:.", root),),
    )

    assert inventory.entries_for("review")[0].state is InventoryState.STALE_OWNED


def test_loads_codex_and_claude_disabled_rules(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    codex_skill = repo / ".agents" / "skills" / "review"
    codex_skill.mkdir(parents=True)
    codex_config = repo / ".codex" / "config.toml"
    codex_config.parent.mkdir()
    codex_config.write_text(
        f'[[skills.config]]\npath = "{codex_skill / "SKILL.md"}"\nenabled = false\n',
        encoding="utf-8",
    )
    claude_settings = repo / ".claude" / "settings.local.json"
    claude_settings.parent.mkdir()
    claude_settings.write_text(
        json.dumps({"skillOverrides": {"review": "off", "keep": "name-only"}}),
        encoding="utf-8",
    )

    codex = load_disabled_rules(repo, "codex", home=home)
    claude = load_disabled_rules(repo, "claude", home=home)

    assert codex.disables("ignored", codex_skill)
    assert claude.disables("review", Path("anywhere"))
    assert not claude.disables("keep", Path("anywhere"))


def test_default_roots_cover_reference_harness_scopes_and_ancestors(tmp_path):
    repo = tmp_path / "repo"
    child = repo / "packages" / "app"
    child.mkdir(parents=True)
    (repo / ".git").mkdir()
    home = tmp_path / "home"

    codex = default_discovery_roots(
        child, "codex", home=home, admin_root=tmp_path / "etc-codex"
    )
    claude = default_discovery_roots(child, "claude", home=home)

    codex_paths = {root.path for root in codex if root.path is not None}
    claude_paths = {root.path for root in claude if root.path is not None}
    assert child / ".agents" / "skills" in codex_paths
    assert repo / ".agents" / "skills" in codex_paths
    assert home / ".agents" / "skills" in codex_paths
    assert child / ".claude" / "skills" in claude_paths
    assert repo / ".claude" / "skills" in claude_paths
    assert child / ".claude" / "commands" in claude_paths
    assert {root.scope for root in codex if root.kind == "opaque"} == {
        "plugins",
        "system",
    }
    assert {root.scope for root in claude if root.kind == "opaque"} == {
        "plugins",
        "managed",
    }


def test_cache_only_inventory_reuses_proof_and_fails_closed_after_drift(
    tmp_path, monkeypatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    root = repo / ".agents" / "skills"
    root.mkdir(parents=True)
    source = _skill(tmp_path / "sources", "review", "first body\n")
    projection = root / "review"
    projection.symlink_to(source)
    store = _store(tmp_path)
    _record(store, repo=repo, projection=projection, source=source, name="review")
    lock = _lock(repo, "codex", [("review", projection, source, None)])
    cache = InventoryDigestCache(tmp_path / "digest-cache")
    roots = (DiscoveryRoot("repo:.", root),)

    deep = scan_effective_inventory(
        repo,
        "codex",
        lock=lock,
        ownership_store=store,
        roots=roots,
        digest_cache=cache,
    )
    monkeypatch.setattr(
        inventory_mod,
        "digest_path",
        lambda _path: (_ for _ in ()).throw(AssertionError("deep hash was called")),
    )
    cached = scan_effective_inventory(
        repo,
        "codex",
        lock=lock,
        ownership_store=store,
        roots=roots,
        digest_mode="cache-only",
        digest_cache=cache,
    )

    assert cached.inventory_id == deep.inventory_id
    assert cached.entries_for("review")[0].state is InventoryState.EXPECTED_OWNED

    (source / "SKILL.md").write_text("second, changed body\n", encoding="utf-8")
    drifted = scan_effective_inventory(
        repo,
        "codex",
        lock=lock,
        ownership_store=store,
        roots=roots,
        digest_mode="cache-only",
        digest_cache=cache,
    )

    assert drifted.inventory_id != deep.inventory_id
    assert drifted.entries_for("review")[0].content_digest is None
    assert drifted.entries_for("review")[0].state is InventoryState.STALE_OWNED
