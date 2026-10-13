"""House rules, kernel install, repo patterns, catalog, and sourcing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from spindle import catalog, house, judge, sourcing
from spindle.cli import main


def _skill(root: Path, relative: str, name: str, description: str, body: str = "Do it."):
    directory = root / relative
    directory.mkdir(parents=True)
    directory.joinpath("SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n", "utf-8"
    )
    return directory


@pytest.fixture
def estate(tmp_path, monkeypatch):
    home = tmp_path / "home"
    for harness in (".claude", ".codex", ".hermes"):
        (home / harness).mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SPINDLE_HOME", str(tmp_path / "state"))
    for name in ("CLAUDE_SKILLS_DIR", "CLAUDE_MD_PATH", "CODEX_HOME", "HERMES_HOME",
                 "SPINDLE_CODEX_SKILLS_DIR", "SPINDLE_HERMES_SKILLS_DIR",
                 "TYPESAFE_API_KEY", "SPINDLE_JEV_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    packages = tmp_path / "depot" / "packages"
    _skill(packages, "planning/skills/orient", "orient", "Frame the problem.")
    _skill(packages, "review/skills/review-eng", "review-eng", "Review a plan.")
    _skill(packages, "data/skills/njsd-data", "njsd-data",
           "Work on the school data warehouse and generator pipeline.")
    _skill(packages, "debug/skills/bughunt", "bughunt",
           "Diagnose a failing test or flaky bug by finding the root cause.",
           "Reproduce first. Read ~/.claude/skills/bughunt/bin/trace before guessing.")
    root = tmp_path / "depot" / "house"
    (root / "patterns").mkdir(parents=True)
    root.joinpath("RULES.md").write_text("# House rules\n\n- Keep moving.\n", "utf-8")
    root.joinpath("patterns/data.md").write_text("Check row counts.\n", "utf-8")
    root.joinpath("house.toml").write_text(
        'schema = "spindle.house/v1"\nversion = "1.2.0"\n'
        'skill_roots = ["../packages"]\n'
        '[kernel]\nskills = ["orient", "review-eng"]\n'
        '[patterns.data]\ndescription = "Data publication"\n'
        'rules = "patterns/data.md"\nskills = ["njsd-data"]\n',
        "utf-8",
    )
    root.joinpath("catalog.toml").write_text(
        '[[source]]\nslug = "home"\npath = "../packages"\n', "utf-8"
    )
    monkeypatch.setenv("SPINDLE_HOUSE_DIR", str(root))
    return tmp_path


def test_frontmatter_joins_block_scalars():
    meta = house.frontmatter("---\nname: a\ndescription: |\n  First line\n  second.\n---\nx")
    assert meta == {"name": "a", "description": "First line second."}


def test_machine_setup_installs_rules_and_kernel_for_each_harness(estate, capsys):
    home = estate / "home"
    home.joinpath(".codex/AGENTS.md").write_text("# Mine\n\nKeep this.\n", "utf-8")
    dead = home / ".claude" / "skills" / "old-skill"
    dead.parent.mkdir(parents=True)
    dead.symlink_to(estate / "gone")
    foreign = home / ".claude" / "skills" / "review-eng"
    foreign.mkdir()

    assert main(["house", "setup", "--prune-dangling"]) == 1  # one conflict
    out = capsys.readouterr().out
    assert "conflict" in out and "review-eng" in out

    codex = home.joinpath(".codex/AGENTS.md").read_text("utf-8")
    assert codex.startswith("# Mine\n\nKeep this.\n")
    assert "spindle:house:begin version=1.2.0" in codex and "Keep moving." in codex
    assert "Keep moving." in home.joinpath(".claude/CLAUDE.md").read_text("utf-8")
    assert "Keep moving." in home.joinpath(".hermes/SOUL.md").read_text("utf-8")
    for skills in (".claude/skills", ".agents/skills", ".hermes/skills/spindle"):
        assert (home / skills / "orient" / "SKILL.md").is_file()
    assert foreign.is_dir() and not foreign.is_symlink()
    assert not dead.is_symlink()

    foreign.rmdir()
    assert main(["house", "setup"]) == 0
    capsys.readouterr()
    assert main(["house", "status", "--json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["harnesses"]["claude"]["rules"]["state"] == "current"
    assert set(status["harnesses"]["codex"]["kernel"].values()) == {"current"}


def test_setup_is_idempotent_updates_rules_and_drops_removed_kernel_skills(estate):
    built = house.load()
    house.setup_machine(built, ("claude",))
    again = house.setup_machine(built, ("claude",))
    assert {row["action"] for row in again} == {"current"}

    root = estate / "depot" / "house"
    root.joinpath("RULES.md").write_text("# House rules\n\n- New rule.\n", "utf-8")
    text = root.joinpath("house.toml").read_text("utf-8")
    root.joinpath("house.toml").write_text(
        text.replace('"1.2.0"', '"1.3.0"').replace(', "review-eng"', ""), "utf-8"
    )
    rows = house.setup_machine(house.load(), ("claude",))
    actions = {(row["name"].split("/")[-1], row["action"]) for row in rows}
    assert ("CLAUDE.md", "updated") in actions
    assert ("review-eng", "unlinked") in actions
    claude_md = (estate / "home/.claude/CLAUDE.md").read_text("utf-8")
    assert "New rule." in claude_md and "Keep moving." not in claude_md
    assert claude_md.count("spindle:house:begin") == 1
    assert not (estate / "home/.claude/skills/review-eng").is_symlink()


def test_remove_undoes_setup_but_leaves_a_retargeted_link_and_other_text(estate):
    home = estate / "home"
    home.joinpath(".claude/CLAUDE.md").write_text("# Mine\n", "utf-8")
    built = house.load()
    house.setup_machine(built, ("claude",))
    moved = home / ".claude/skills/orient"
    moved.unlink()
    moved.symlink_to(estate / "depot" / "packages" / "data")  # the user's choice now

    again = house.setup_machine(built, ("claude",))
    assert ("orient", "conflict") in {(r["name"], r["action"]) for r in again}

    assert main(["house", "remove", "--harness", "claude"]) == 0
    assert home.joinpath(".claude/CLAUDE.md").read_text("utf-8") == "# Mine\n"
    assert moved.is_symlink()
    assert not (home / ".claude/skills/review-eng").is_symlink()
    assert house.remove_machine(("claude",)) == []


def test_repo_setup_needs_a_pattern_the_first_time(estate):
    repo = estate / "repo"
    repo.mkdir()
    with pytest.raises(house.HouseError, match="--pattern"):
        house.setup_repo(house.load(), repo)
    assert list(repo.iterdir()) == []


def test_status_reports_a_hand_edited_block(estate):
    built = house.load()
    house.setup_machine(built, ("claude",))
    target = estate / "home/.claude/CLAUDE.md"
    target.write_text(target.read_text("utf-8").replace("Keep moving", "Stop"), "utf-8")
    report = house.machine_status(built, ("claude",))
    assert report["harnesses"]["claude"]["rules"]["state"] == "edited"


def test_repo_setup_vendors_pattern_and_protects_local_edits(estate):
    repo = estate / "repo"
    repo.mkdir()
    built = house.load()
    rows = house.setup_repo(built, repo, ("data",))
    assert ("njsd-data", "vendored") in {(r["name"], r["action"]) for r in rows}
    assert "Check row counts." in repo.joinpath("AGENTS.md").read_text("utf-8")
    assert "House rules v1.2.0 apply" in repo.joinpath("AGENTS.md").read_text("utf-8")
    assert repo.joinpath("CLAUDE.md").read_text("utf-8") == "@AGENTS.md\n"
    link = repo / ".claude/skills/njsd-data"
    assert link.is_symlink() and not Path(link.readlink()).is_absolute()
    assert (link / "SKILL.md").is_file()
    assert house.repo_status(built, repo)["skills"] == {"njsd-data": "current"}

    # No pattern argument: the lock remembers it.
    assert {r["action"] for r in house.setup_repo(built, repo)} == {"current"}

    (repo / ".agents/skills/njsd-data/SKILL.md").write_text("local edit\n", "utf-8")
    assert house.repo_status(built, repo)["skills"]["njsd-data"] == "edited"
    rows = house.setup_repo(built, repo)
    assert ("njsd-data", "conflict") in {(r["name"], r["action"]) for r in rows}
    assert (repo / ".agents/skills/njsd-data/SKILL.md").read_text("utf-8") == "local edit\n"
    rows = house.setup_repo(built, repo, force=True)
    assert ("njsd-data", "updated") in {(r["name"], r["action"]) for r in rows}


def test_unknown_kernel_skill_fails_before_touching_anything(estate):
    root = estate / "depot" / "house"
    text = root.joinpath("house.toml").read_text("utf-8")
    root.joinpath("house.toml").write_text(text.replace("orient", "nope"), "utf-8")
    with pytest.raises(house.HouseError, match="nope"):
        house.setup_machine(house.load(), ("claude",))
    assert not (estate / "home/.claude/CLAUDE.md").exists()


def test_catalog_sync_indexes_local_source_and_flags_kernel_and_install(estate):
    index = catalog.sync(house.load())
    by_ref = {entry["ref"]: entry for entry in index["skills"]}
    assert set(by_ref) == {"home/orient", "home/review-eng",
                           "home/njsd-data", "home/bughunt"}
    assert by_ref["home/orient"]["kernel"] is True
    assert by_ref["home/bughunt"]["requires_install"] is True
    assert by_ref["home/njsd-data"]["requires_install"] is False
    assert catalog.find_entry(index, "bughunt")["ref"] == "home/bughunt"
    with pytest.raises(house.HouseError):
        catalog.find_entry(index, "missing")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_catalog_update_reports_and_applies_a_new_upstream_commit(estate, capsys):
    upstream = estate / "upstream"
    upstream.mkdir()
    _git(upstream, "init", "-b", "main")
    _git(upstream, "config", "user.email", "t@example.test")
    _git(upstream, "config", "user.name", "T")
    _skill(upstream, "skills/alpha", "alpha", "Alpha does a thing.")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-m", "one")
    first = _git(upstream, "rev-parse", "HEAD")
    path = estate / "depot" / "house" / "catalog.toml"
    path.write_text(
        f'[[source]]\nslug = "up"\nref = "git:{upstream}@{first}"\ntrack = "main"\n',
        "utf-8",
    )
    assert main(["catalog", "sync"]) == 0
    assert [e["ref"] for e in catalog.load_index()["skills"]] == ["up/alpha"]

    _skill(upstream, "skills/beta", "beta", "Beta runs curl to fetch.", "curl http://x")
    (upstream / "skills/alpha/SKILL.md").write_text(
        "---\nname: alpha\ndescription: Alpha does more.\n---\n\nMore.\n", "utf-8")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-m", "two")
    second = _git(upstream, "rev-parse", "HEAD")

    report = catalog.check_updates(house.load())[0]
    assert report["state"] == "behind" and report["head"] == second
    assert report["added"] == ["beta"] and report["changed"] == ["alpha"]
    assert "beta" in report["new_risks"]
    assert first in path.read_text("utf-8")  # reporting never moves the pin

    capsys.readouterr()
    assert main(["catalog", "update", "--apply"]) == 0
    assert second in path.read_text("utf-8") and first not in path.read_text("utf-8")
    assert {e["ref"] for e in catalog.load_index()["skills"]} == {"up/alpha", "up/beta"}
    assert catalog.check_updates(house.load())[0]["state"] == "current"


def test_sync_refuses_an_unpinned_git_source(estate):
    path = estate / "depot" / "house" / "catalog.toml"
    path.write_text('[[source]]\nslug = "up"\nref = "github:o/r@main"\n', "utf-8")
    index = catalog.sync(house.load(), offline=True)
    assert "pin a full commit" in index["sources"][0]["error"]


def test_search_excludes_kernel_and_ranks_the_matching_skill_first(estate):
    index = catalog.sync(house.load())
    found = sourcing.search(index, "diagnose a flaky failing test")
    assert found[0]["ref"] == "home/bughunt"
    assert all(not c["ref"].endswith("orient") for c in found)
    assert sourcing.search(index, "the and for") == []


def test_lexical_selection_is_a_labelled_shortlist(estate):
    index = catalog.sync(house.load())
    selection = sourcing.select(index, "diagnose a flaky failing test", use_judge="auto")
    assert selection["confidence"] == "lexical" and selection["judge"] == "none"
    assert "no TypeSafe key" in selection["judge_note"]
    block = sourcing.prompt_block(selection)
    assert "text match only" in block and "home/bughunt" in block
    assert "Needs its own install" in block


def test_judge_selects_only_what_it_expects_to_help_and_may_abstain(estate):
    index = catalog.sync(house.load())
    seen = {}

    def provider(body, key):
        seen.update(body=body, key=key)
        return {"answers": {
            name: {"noul": 0.9 if "bughunt" in q["instructions"] else 0.1}
            for name, q in body["questions"].items()
        }}

    selection = sourcing.select(index, "diagnose a flaky failing test in the pipeline",
                                provider=provider, key="k", job="job1")
    assert seen["key"] == "k" and seen["body"]["model"] == judge.MODEL
    assert selection["confidence"] == "judged"
    assert [c["ref"] for c in selection["candidates"] if c["selected"]] == ["home/bughunt"]
    assert sourcing.load_selection(job="job1")["id"] == selection["id"]

    nothing = sourcing.select(
        index, "diagnose a flaky failing test",
        provider=lambda body, key: {"answers": {n: {"noul": 0.2} for n in body["questions"]}},
        key="k",
    )
    assert not any(c["selected"] for c in nothing["candidates"])
    assert sourcing.prompt_block(nothing) == ""


def test_judge_failure_falls_back_to_lexical(estate):
    index = catalog.sync(house.load())

    def broken(body, key):
        raise TimeoutError("slow")

    selection = sourcing.select(index, "diagnose a flaky failing test",
                                provider=broken, key="k")
    assert selection["confidence"] == "lexical"
    assert "judge unavailable" in selection["judge_note"]


def test_key_file_is_read_without_touching_other_lines(estate, monkeypatch):
    key_file = estate / "jev.env"
    key_file.write_text('OTHER=1\nexport TYPESAFE_API_KEY="abc"\n', "utf-8")
    monkeypatch.setenv("SPINDLE_JEV_KEY_FILE", str(key_file))
    assert judge.resolve_key() == "abc"


def test_use_report_and_usage_close_the_loop(estate, capsys):
    assert main(["catalog", "sync"]) == 0
    capsys.readouterr()
    assert main(["find", "--judge", "none", "--job", "j7", "--json",
                 "diagnose", "a", "flaky", "failing", "test"]) == 0
    selection = json.loads(capsys.readouterr().out)
    assert main(["use", "home/bughunt", "--job", "j7"]) == 0
    assert capsys.readouterr().out.strip().endswith("bughunt/SKILL.md")
    assert main(["report", "--job", "j7", "--outcome", "accepted",
                 "--helped", "home/bughunt"]) == 0
    stats = sourcing.usage_summary()["home/bughunt"]
    assert (stats["offered"], stats["loaded"], stats["accepted"], stats["helped"]) == (1, 1, 1, 1)
    assert sourcing.prior(stats) > 0.5
    assert selection["id"] in (estate / "state" / "usage.jsonl").read_text("utf-8")

    for _ in range(3):
        sourcing.report(outcome="rejected", hurt=["home/njsd-data"])
    low = sourcing.usage_summary()
    assert sourcing.prior(low["home/njsd-data"]) < 0.25
    ranked = sourcing.search(catalog.load_index(), "school data warehouse pipeline test")
    assert next(c for c in ranked if c["ref"] == "home/njsd-data")["prior"] < 0.25
    assert main(["usage"]) == 0
    assert "home/bughunt" in capsys.readouterr().out


def test_brief_inline_embeds_text_and_counts_as_loaded(estate, capsys):
    assert main(["catalog", "sync"]) == 0
    capsys.readouterr()
    assert main(["brief", "--judge", "none", "--inline", "--rules", "--json",
                 "--unjudged", "shortlist",
                 "--job", "j9", "diagnose a flaky failing test"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "### Skill: home/bughunt" in payload["prompt_block"]
    assert "Reproduce first." in payload["prompt_block"]
    assert payload["skills"]["delivery"] == "inline"
    assert payload["skills"]["offered"][0]["ref"] == "home/bughunt"
    assert payload["rules"]["version"] == "1.2.0"
    assert sourcing.usage_summary()["home/bughunt"]["loaded"] == 1


def test_house_init_records_the_pointer(estate, monkeypatch, capsys):
    monkeypatch.delenv("SPINDLE_HOUSE_DIR")
    assert main(["house", "status"]) == 1
    assert "spindle house init" in capsys.readouterr().err
    (estate / "state").mkdir(exist_ok=True)
    (estate / "state" / "house.toml").write_text('jev_key_file = "/k"\n', "utf-8")
    assert main(["house", "init", str(estate / "depot" / "house")]) == 0
    assert 'jev_key_file = "/k"' in (estate / "state" / "house.toml").read_text("utf-8")
    assert main(["house", "rules"]) == 0
    assert "Keep moving." in capsys.readouterr().out


def test_unjudged_brief_points_at_find_instead_of_offering_text_matches(
    estate, capsys, monkeypatch
):
    assert main(["catalog", "sync"]) == 0
    capsys.readouterr()
    assert main(["brief", "--judge", "none", "--json", "diagnose a flaky test"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["prompt_block"].startswith("## Skills on demand")
    assert payload["read_roots"] == [str(estate / "depot" / "packages")]
    assert "spindle find" in payload["prompt_block"]
    assert payload["skills"]["offered"] == [] and payload["skills"]["delivery"] == "pointer"

    assert main(["brief", "--judge", "none", "--unjudged", "none", "--json",
                 "diagnose a flaky test"]) == 0
    assert json.loads(capsys.readouterr().out)["prompt_block"] == ""

    # An agent inside a job inherits the job id, so what it reads is attributed.
    monkeypatch.setenv("SPINDLE_JOB", "job-42")
    assert main(["use", "home/bughunt"]) == 0
    assert main(["report", "--outcome", "accepted", "--selection", payload["selection"],
                 "--job", "job-42"]) == 0
    stats = sourcing.usage_summary()["home/bughunt"]
    assert (stats["loaded"], stats["accepted"]) == (1, 1)


def test_expander_output_is_parsed_and_every_failure_means_no_expansion(tmp_path):
    from spindle import expand

    assert expand.parse("1. systematic debugging\n- Flaky test triage\n\n"
                        '"systematic debugging"\nx\n' + "y" * 90) == [
        "systematic debugging", "Flaky test triage"]
    assert expand.expand("task", None) == ([], "")
    script = tmp_path / "ok"
    script.write_text("#!/bin/sh\ncat >/dev/null\necho root cause analysis\n", "utf-8")
    script.chmod(0o755)
    assert expand.expand("task", script) == (["root cause analysis"], "")
    bad = tmp_path / "bad"
    bad.write_text("#!/bin/sh\nexit 3\n", "utf-8")
    bad.chmod(0o755)
    assert expand.expand("task", bad) == ([], "expander exited 3")
    assert expand.expand("task", tmp_path / "missing")[0] == []


def test_expanded_phrases_recover_a_skill_the_task_text_misses(estate, capsys):
    index = catalog.sync(house.load())
    task = "The nightly job goes red now and then; make it green and keep it green."
    assert "home/bughunt" not in [c["ref"] for c in sourcing.search(index, task)]
    found = sourcing.search(index, task, phrases=["diagnose flaky failing test"])
    assert found[0]["ref"] == "home/bughunt"

    root = estate / "depot" / "house"
    (root / "bin").mkdir()
    script = root / "bin" / "queries"
    script.write_text("#!/bin/sh\ncat >/dev/null\necho diagnose flaky failing test\n",
                      "utf-8")
    script.chmod(0o755)
    with root.joinpath("house.toml").open("a", encoding="utf-8") as handle:
        handle.write('\n[sourcing]\nexpand = "bin/queries"\n')
    capsys.readouterr()
    assert main(["find", "--judge", "none", "--json", task]) == 0
    selection = json.loads(capsys.readouterr().out)
    assert selection["expanded_queries"] == ["diagnose flaky failing test"]
    assert selection["candidates"][0]["ref"] == "home/bughunt"
    assert main(["find", "--judge", "none", "--expand", "none", "--json", task]) == 0
    assert json.loads(capsys.readouterr().out)["expanded_queries"] == []


def test_inline_brief_embeds_at_most_two_skills_and_records_only_those(
    estate, capsys, monkeypatch
):
    packages = estate / "depot" / "packages"
    for name in ("flaky-one", "flaky-two"):
        _skill(packages, f"more/skills/{name}", name,
               "Diagnose a flaky failing test.", "Body of " + name)
    index = catalog.sync(house.load())
    selection = sourcing.select(
        index, "diagnose a flaky failing test", key="k",
        provider=lambda body, key: {"answers": {n: {"noul": 0.9} for n in body["questions"]}},
    )
    assert sum(c["selected"] for c in selection["candidates"]) == 3

    lukewarm = sourcing.select(
        index, "diagnose a flaky failing test", key="k", save=False,
        provider=lambda body, key: {"answers": {n: {"noul": 0.62} for n in body["questions"]}},
    )
    assert any(c["selected"] for c in lukewarm["candidates"])  # fine as a path offer

    import spindle.house_cli as cli
    from types import SimpleNamespace
    monkeypatch.setattr(cli, "_select", lambda args: selection)
    args = SimpleNamespace(inline=True, unjudged="pointer", job=None, rules=False, json=True)
    capsys.readouterr()
    assert cli.cmd_brief(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["prompt_block"].count("### Skill: ") == 2
    assert len(payload["skills"]["offered"]) == 2

    # A skill the judge only narrowly favours is not worth embedding.
    monkeypatch.setattr(cli, "_select", lambda args: lukewarm)
    assert cli.cmd_brief(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["prompt_block"] == "" and payload["skills"]["offered"] == []


def test_house_update_pulls_a_git_house_reinstalls_and_reindexes(estate, capsys):
    depot = estate / "depot"
    upstream = estate / "upstream.git"
    _git(depot, "init", "-b", "main")
    _git(depot, "config", "user.email", "t@example.test")
    _git(depot, "config", "user.name", "T")
    _git(depot, "add", ".")
    _git(depot, "commit", "-m", "house")
    subprocess.run(["git", "clone", "--bare", str(depot), str(upstream)],
                   check=True, capture_output=True)
    _git(depot, "remote", "add", "origin", str(upstream))
    _git(depot, "fetch", "origin")
    _git(depot, "branch", "--set-upstream-to=origin/main", "main")

    assert main(["house", "setup", "--harness", "claude"]) == 0
    capsys.readouterr()
    assert main(["house", "update"]) == 0
    assert "house current" in capsys.readouterr().out

    other = estate / "other"
    subprocess.run(["git", "clone", str(upstream), str(other)],
                   check=True, capture_output=True)
    _git(other, "config", "user.email", "t@example.test")
    _git(other, "config", "user.name", "T")
    (other / "house" / "RULES.md").write_text("# House rules\n\n- Fresh rule.\n", "utf-8")
    _git(other, "commit", "-am", "new rule")
    _git(other, "push", "origin", "main")

    assert main(["house", "update"]) == 0
    out = capsys.readouterr().out
    assert "house updated" in out and "catalog: 4 skills" in out
    assert "Fresh rule." in (estate / "home/.claude/CLAUDE.md").read_text("utf-8")
    # Only harnesses that were set up are touched.
    assert not (estate / "home/.codex/AGENTS.md").exists()


def test_repo_setup_reports_vendored_skills_that_git_ignores(estate, capsys):
    repo = estate / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / ".gitignore").write_text(".agents/\n.claude/\n", "utf-8")
    assert main(["house", "setup", "--repo", str(repo), "--pattern", "data"]) == 1
    assert "ignored" in capsys.readouterr().out

    (repo / ".gitignore").write_text(
        ".agents/*\n!.agents/skills/\n.claude/*\n!.claude/skills/\n", "utf-8")
    assert main(["house", "setup", "--repo", str(repo)]) == 0
