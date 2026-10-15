"""The house: one versioned place for rules, the kernel, and project patterns.

A *house directory* is a plain checkout (normally ``house/`` in a distribution repository) holding:

  house.toml     version, the kernel skill list, and named project patterns
  RULES.md       the house rules every harness should load
  patterns/*.md  extra rules for one kind of project
  catalog.toml   pinned third-party sources (see ``spindle.catalog``)

``setup_machine`` projects the rules into each harness's always-loaded
instruction file and links the kernel skills into its skill directory.
``setup_repo`` vendors a pattern's rules and skills into a repository so they
travel with it. Both are idempotent and only touch what a prior run recorded as
theirs, a dangling link, or an older Spindle render.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from . import paths
from .lifecycle import digest_path

HOUSE_SCHEMA = "spindle.house/v1"
INSTALL_SCHEMA = "spindle.house-install/v1"
REPO_LOCK_SCHEMA = "spindle.house-lock/v1"
REPO_LOCK = Path(".spindle") / "house.json"
HARNESSES = ("claude", "codex", "hermes")

_BEGIN = re.compile(
    r"<!-- spindle:house:begin version=(?P<version>\S+) digest=(?P<digest>\S+) -->"
)
_END = "<!-- spindle:house:end -->"
_BLOCK = re.compile(
    r"<!-- spindle:house:begin [^>]*-->\n.*?<!-- spindle:house:end -->\n?",
    re.DOTALL,
)
_SKIP_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "dist", "build", "tests"}
)


class HouseError(RuntimeError):
    """The house is missing, malformed, or names something it cannot resolve."""


@dataclass(frozen=True)
class Pattern:
    name: str
    description: str
    rules: Path | None
    skills: tuple[str, ...]


@dataclass(frozen=True)
class House:
    root: Path
    version: str
    rules_file: Path
    kernel: tuple[str, ...]
    skill_roots: tuple[Path, ...]
    patterns: dict[str, Pattern] = field(default_factory=dict)
    expand_command: Path | None = None

    def rules_text(self) -> str:
        return self.rules_file.read_text(encoding="utf-8").strip() + "\n"

    def pattern(self, name: str) -> Pattern:
        try:
            return self.patterns[name]
        except KeyError:
            known = ", ".join(sorted(self.patterns)) or "none defined"
            raise HouseError(f"unknown pattern {name!r} (known: {known})") from None


def config_file() -> Path:
    return paths.spindle_home() / "house.toml"


def house_dir() -> Path:
    """Resolve the house directory: ``SPINDLE_HOUSE_DIR``, then the config file."""
    raw = os.environ.get("SPINDLE_HOUSE_DIR")
    if not raw:
        config = config_file()
        if config.is_file():
            raw = tomllib.loads(config.read_text(encoding="utf-8")).get("house")
    if not raw:
        raise HouseError(
            "no house is configured; run `spindle house init <path-to-house-dir>`"
        )
    root = Path(raw).expanduser()
    if not (root / "house.toml").is_file():
        raise HouseError(f"{root} has no house.toml")
    return root.resolve()


def init(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    if not (root / "house.toml").is_file():
        raise HouseError(f"{root} has no house.toml")
    load(root)
    config = config_file()
    settings: dict[str, Any] = {}
    if config.is_file():
        settings = tomllib.loads(config.read_text(encoding="utf-8"))
    settings["house"] = str(root)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "".join(f"{key} = {json.dumps(value)}\n" for key, value in settings.items()),
        encoding="utf-8",
    )
    return config


def load(root: Path | None = None) -> House:
    root = root or house_dir()
    try:
        raw = tomllib.loads((root / "house.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise HouseError(f"cannot read {root / 'house.toml'}: {exc}") from exc
    if raw.get("schema") != HOUSE_SCHEMA:
        raise HouseError(f"house.toml must declare schema = {HOUSE_SCHEMA!r}")
    version = str(raw.get("version") or "")
    if not version:
        raise HouseError("house.toml must declare a version")
    rules_file = root / str(raw.get("rules", "RULES.md"))
    if not rules_file.is_file():
        raise HouseError(f"house rules file is missing: {rules_file}")
    patterns: dict[str, Pattern] = {}
    for name, body in (raw.get("patterns") or {}).items():
        rules = root / body["rules"] if body.get("rules") else None
        if rules is not None and not rules.is_file():
            raise HouseError(f"pattern {name!r} rules file is missing: {rules}")
        patterns[name] = Pattern(
            name=name,
            description=str(body.get("description", "")),
            rules=rules,
            skills=tuple(body.get("skills") or ()),
        )
    expand = (raw.get("sourcing") or {}).get("expand")
    return House(
        root=root,
        expand_command=(root / str(expand)).resolve() if expand else None,
        version=version,
        rules_file=rules_file,
        kernel=tuple((raw.get("kernel") or {}).get("skills") or ()),
        skill_roots=tuple(
            (root / item).resolve() for item in raw.get("skill_roots") or ()
        ),
        patterns=patterns,
    )


# --------------------------------------------------------------------- skills


def frontmatter(text: str) -> dict[str, str]:
    """Top-level scalar keys of a SKILL.md frontmatter block.

    Folded and literal block scalars (``description: |``) are joined into one
    line so a description is usable as search text.
    """
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    values: dict[str, str] = {}
    key: str | None = None
    for line in text[3:end].splitlines():
        if key is not None and (line.startswith((" ", "\t")) or not line.strip()):
            values[key] = (values[key] + " " + line.strip()).strip()
            continue
        name, separator, value = line.partition(":")
        if not separator or not name.strip() or name.startswith((" ", "\t", "#")):
            key = None
            continue
        key = name.strip()
        value = value.strip()
        values[key] = "" if value in {"|", ">", "|-", ">-", "|+", ">+"} else _unquote(value)
    return values


def _unquote(value: str) -> str:
    """Undo YAML scalar quoting, so ``"Use for \\"x\\""`` reads ``Use for "x"``."""
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            return json.loads(value)
        except ValueError:
            return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def skill_body(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    return text if end < 0 else text[end + 4 :].lstrip("\n")


def discover_skills(roots: tuple[Path, ...] | list[Path]) -> dict[str, Path]:
    """Map skill name (frontmatter ``name``, else directory name) to its directory."""
    found: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for current, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
            if "SKILL.md" not in files:
                continue
            skill_dir = Path(current)
            try:
                meta = frontmatter(
                    (skill_dir / "SKILL.md").read_text(encoding="utf-8")
                )
            except (OSError, UnicodeDecodeError):
                continue
            found.setdefault(meta.get("name") or skill_dir.name, skill_dir)
            dirs[:] = []
    return found


def resolve_skills(house: House, names: tuple[str, ...]) -> dict[str, Path]:
    index = discover_skills(house.skill_roots)
    missing = [name for name in names if name not in index]
    if missing:
        raise HouseError(
            "house names skills that no skill root provides: " + ", ".join(missing)
        )
    return {name: index[name] for name in names}


# ---------------------------------------------------------------------- rules


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def render_block(version: str, body: str) -> str:
    body = body.strip() + "\n"
    return (
        f"<!-- spindle:house:begin version={version} digest={_digest(body)} -->\n"
        f"{body}{_END}\n"
    )


def read_block(text: str) -> dict[str, Any] | None:
    """Describe the managed block in *text*, or ``None`` when there is none."""
    start = _BEGIN.search(text)
    if start is None:
        return None
    end = text.find(_END, start.end())
    if end < 0:
        return None
    body = text[start.end() : end].lstrip("\n")
    return {
        "version": start["version"],
        "digest": start["digest"],
        "edited": _digest(body) != start["digest"],
    }


def write_block(path: Path, block: str, *, dry_run: bool = False) -> str:
    """Insert or replace the managed block; text outside it is preserved."""
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if _BLOCK.search(existing):
        updated = _BLOCK.sub(lambda _match: block, existing, count=1)
        action = "updated"
    else:
        separator = "" if not existing or existing.endswith("\n\n") else "\n"
        if existing and not existing.endswith("\n"):
            separator = "\n\n"
        updated = existing + separator + block
        action = "added"
    if updated == existing:
        return "current"
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding="utf-8")
    return action


def remove_block(path: Path) -> bool:
    if not path.is_file():
        return False
    existing = path.read_text(encoding="utf-8")
    updated = _BLOCK.sub("", existing, count=1)
    if updated == existing:
        return False
    path.write_text(updated.rstrip("\n") + "\n" if updated.strip() else "", "utf-8")
    return True


# -------------------------------------------------------------------- machine


def rules_target(harness: str) -> Path:
    home = Path.home()
    if harness == "claude":
        return paths.claude_md_path()
    if harness == "codex":
        return Path(os.environ.get("CODEX_HOME", str(home / ".codex"))) / "AGENTS.md"
    if harness == "hermes":
        return Path(os.environ.get("HERMES_HOME", str(home / ".hermes"))) / "SOUL.md"
    raise HouseError(f"unknown harness {harness!r}")


def skills_target(harness: str) -> Path:
    if harness == "claude":
        return paths.claude_skills_dir()
    if harness == "codex":
        return Path(
            os.environ.get(
                "SPINDLE_CODEX_SKILLS_DIR", str(Path.home() / ".agents" / "skills")
            )
        )
    if harness == "hermes":
        return paths.hermes_skills_dir()
    raise HouseError(f"unknown harness {harness!r}")


def detect_harnesses() -> tuple[str, ...]:
    """Harnesses whose home directory exists on this machine."""
    return tuple(h for h in HARNESSES if rules_target(h).parent.is_dir())


def install_record_file() -> Path:
    return paths.spindle_home() / "house" / "installed.json"


def _load_record() -> dict[str, Any]:
    path = install_record_file()
    if not path.is_file():
        return {"schema": INSTALL_SCHEMA, "harnesses": {}}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HouseError(f"cannot read {path}: {exc}") from exc
    record.setdefault("harnesses", {})
    return record


def _save_record(record: dict[str, Any]) -> None:
    path = install_record_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", "utf-8")
    os.replace(temporary, path)


def _replaceable(link: Path, owned: dict[str, str]) -> bool:
    """A link this setup may retarget: still ours, dead, or an older Spindle render.

    "Ours" means the link still points where a prior setup left it. A link
    someone has since retargeted is theirs, whatever the record says.
    """
    target = os.readlink(link)
    if owned.get(str(link)) == target or not link.exists():
        return True
    return target.startswith(str(paths.spindle_home() / "rendered"))


def _plan_link(link: Path, source: Path, owned: dict[str, str]) -> str:
    if link.is_symlink():
        if link.exists() and link.resolve() == source.resolve():
            return "current"
        return "relink" if _replaceable(link, owned) else "conflict"
    if link.exists():
        return "conflict"
    return "link"


def setup_machine(
    house: House,
    harnesses: tuple[str, ...],
    *,
    dry_run: bool = False,
    prune_dangling: bool = False,
) -> list[dict[str, str]]:
    """Install rules and kernel links for each harness. Returns one row per act."""
    sources = resolve_skills(house, house.kernel)
    record = _load_record()
    block = render_block(house.version, house.rules_text())
    rows: list[dict[str, str]] = []

    def row(harness: str, kind: str, name: str, action: str, detail: str = "") -> None:
        rows.append(
            {"harness": harness, "kind": kind, "name": name, "action": action,
             "detail": detail}
        )

    for harness in harnesses:
        state = record["harnesses"].setdefault(harness, {"links": {}})
        owned: dict[str, str] = state.setdefault("links", {})
        target = rules_target(harness)
        row(harness, "rules", str(target), write_block(target, block, dry_run=dry_run))
        state["rules"] = {"path": str(target), "version": house.version}

        skill_dir = skills_target(harness)
        if not dry_run:
            skill_dir.mkdir(parents=True, exist_ok=True)
        wanted = {str(skill_dir / name): source for name, source in sources.items()}
        for link_text in sorted(set(owned) - set(wanted)):
            link = Path(link_text)
            if link.is_symlink() and os.readlink(link) == owned[link_text]:
                if not dry_run:
                    link.unlink()
                row(harness, "skill", link.name, "unlinked", "left the kernel")
            if not dry_run:
                owned.pop(link_text, None)
        for link_text, source in wanted.items():
            link = Path(link_text)
            action = _plan_link(link, source, owned)
            if action == "conflict":
                where = os.readlink(link) if link.is_symlink() else "a real directory"
                row(harness, "skill", link.name, "conflict", f"not ours: {where}")
                continue
            if action != "current" and not dry_run:
                if link.is_symlink():
                    link.unlink()
                link.symlink_to(source)
            if not dry_run:
                owned[link_text] = str(source)
            row(harness, "skill", link.name, action, str(source))
        if skill_dir.is_dir():
            for entry in sorted(skill_dir.iterdir()):
                if not entry.is_symlink() or entry.exists() or str(entry) in wanted:
                    continue
                if prune_dangling and not dry_run:
                    entry.unlink()
                row(
                    harness,
                    "skill",
                    entry.name,
                    "pruned" if prune_dangling else "dangling",
                    os.readlink(entry) if entry.is_symlink() else "dead link removed",
                )
    if not dry_run:
        record["house_version"] = house.version
        record["house_dir"] = str(house.root)
        _save_record(record)
    return rows


def remove_machine(
    harnesses: tuple[str, ...], *, dry_run: bool = False
) -> list[dict[str, str]]:
    """Undo ``setup_machine``: drop the rules block and the links it still owns."""
    record = _load_record()
    rows: list[dict[str, str]] = []
    for harness in harnesses:
        state = record["harnesses"].get(harness)
        if state is None:
            continue
        target = rules_target(harness)
        has_block = target.is_file() and read_block(target.read_text("utf-8"))
        if has_block and (dry_run or remove_block(target)):
            rows.append({"harness": harness, "kind": "rules", "name": str(target),
                         "action": "removed", "detail": ""})
        for link_text, source in sorted(state.get("links", {}).items()):
            link = Path(link_text)
            if link.is_symlink() and os.readlink(link) == source:
                if not dry_run:
                    link.unlink()
                rows.append({"harness": harness, "kind": "skill", "name": link.name,
                             "action": "unlinked", "detail": ""})
        if not dry_run:
            del record["harnesses"][harness]
    if not dry_run:
        _save_record(record)
    return rows


def installed_harnesses() -> tuple[str, ...]:
    """Harnesses an earlier ``setup_machine`` installed on this machine."""
    recorded = _load_record()["harnesses"]
    return tuple(h for h in HARNESSES if h in recorded)


def pull(root: Path) -> dict[str, str]:
    """Fast-forward the Git checkout holding the house, when it is one.

    Only a fast-forward is attempted: a checkout with local commits or edits
    that conflict is reported and left exactly as it was.
    """
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, timeout=120
        )

    try:
        if git("rev-parse", "--is-inside-work-tree").returncode != 0:
            return {"state": "not a git checkout"}
        before = git("rev-parse", "HEAD").stdout.strip()
        pulled = git("pull", "--ff-only", "--quiet")
        after = git("rev-parse", "HEAD").stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return {"state": "failed", "detail": str(exc)}
    if pulled.returncode != 0:
        detail = (pulled.stderr or pulled.stdout).strip().splitlines()
        return {"state": "failed", "detail": detail[-1] if detail else "git pull failed"}
    if before == after:
        return {"state": "current", "commit": after}
    return {"state": "updated", "from": before, "commit": after}


def machine_status(house: House, harnesses: tuple[str, ...]) -> dict[str, Any]:
    sources = resolve_skills(house, house.kernel)
    record = _load_record()
    current = render_block(house.version, house.rules_text())
    report: dict[str, Any] = {
        "house": {"dir": str(house.root), "version": house.version},
        "harnesses": {},
    }
    for harness in harnesses:
        owned = record["harnesses"].get(harness, {}).get("links", {})
        target = rules_target(harness)
        text = target.read_text(encoding="utf-8") if target.is_file() else ""
        block = read_block(text)
        if block is None:
            rules = "missing"
        elif block["edited"]:
            rules = "edited"
        elif current in text:
            rules = "current"
        else:
            rules = "stale"
        skill_dir = skills_target(harness)
        kernel = {
            name: _plan_link(skill_dir / name, source, owned)
            for name, source in sources.items()
        }
        entries = sorted(skill_dir.iterdir()) if skill_dir.is_dir() else []
        dangling = [e.name for e in entries if e.is_symlink() and not e.exists()]
        report["harnesses"][harness] = {
            "rules": {
                "path": str(target),
                "state": rules,
                "installed_version": block["version"] if block else None,
            },
            "skills_dir": str(skill_dir),
            "kernel": kernel,
            "always_on": len([e for e in entries if e.exists()]),
            "dangling": dangling,
        }
    return report


# ----------------------------------------------------------------------- repo


def _repo_rules(house: House, patterns: list[Pattern], with_house_rules: bool) -> str:
    parts: list[str] = []
    if with_house_rules:
        parts.append(house.rules_text().strip())
    else:
        parts.append(
            f"House rules v{house.version} apply here. If they are not already in "
            "your context, run `spindle house rules`."
        )
    for pattern in patterns:
        if pattern.rules is not None:
            parts.append(pattern.rules.read_text(encoding="utf-8").strip())
    return "\n\n".join(parts) + "\n"


def _repo_rule_files(repo: Path) -> list[Path]:
    """Instruction files to carry the block: AGENTS.md, and CLAUDE.md unless it
    already imports AGENTS.md."""
    agents, claude = repo / "AGENTS.md", repo / "CLAUDE.md"
    targets = [agents]
    if claude.is_file() and "@AGENTS.md" not in claude.read_text(encoding="utf-8"):
        targets.append(claude)
    return targets


def read_repo_lock(repo: Path) -> dict[str, Any] | None:
    path = repo / REPO_LOCK
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HouseError(f"cannot read {path}: {exc}") from exc


def setup_repo(
    house: House,
    repo: Path,
    pattern_names: tuple[str, ...] = (),
    *,
    with_house_rules: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> list[dict[str, str]]:
    """Vendor pattern rules and skills into *repo* so they travel with it.

    Skills are copied to ``.agents/skills/<name>`` with a relative link from
    ``.claude/skills/<name>``, so one committed copy serves both harnesses and
    survives worktrees and other hosts.
    """
    repo = repo.resolve()
    if not repo.is_dir():
        raise HouseError(f"not a directory: {repo}")
    lock = read_repo_lock(repo) or {}
    if not pattern_names:
        pattern_names = tuple(lock.get("patterns") or ())
    if lock and not with_house_rules:
        with_house_rules = bool(lock.get("with_house_rules"))
    if not pattern_names and not with_house_rules:
        raise HouseError(
            "name a --pattern (see `spindle house patterns`) or pass "
            "--with-house-rules; this repository has not been set up before"
        )
    patterns = [house.pattern(name) for name in pattern_names]
    wanted: dict[str, Path] = {}
    for pattern in patterns:
        wanted.update(resolve_skills(house, pattern.skills))
    locked: dict[str, str] = dict(lock.get("skills") or {})
    rows: list[dict[str, str]] = []

    def row(kind: str, name: str, action: str, detail: str = "") -> None:
        rows.append({"harness": "repo", "kind": kind, "name": name, "action": action,
                     "detail": detail})

    block = render_block(house.version, _repo_rules(house, patterns, with_house_rules))
    for target in _repo_rule_files(repo):
        row("rules", str(target.relative_to(repo)),
            write_block(target, block, dry_run=dry_run))
    claude_md = repo / "CLAUDE.md"
    if not claude_md.exists():
        if not dry_run:
            claude_md.write_text("@AGENTS.md\n", encoding="utf-8")
        row("rules", "CLAUDE.md", "added", "imports AGENTS.md")

    agents_dir = repo / ".agents" / "skills"
    claude_dir = repo / ".claude" / "skills"
    new_lock: dict[str, str] = {}
    for name in sorted(set(locked) - set(wanted)):
        copy = agents_dir / name
        if copy.is_dir() and digest_path(copy) != locked[name] and not force:
            row("skill", name, "kept", "left the pattern but was edited locally")
            continue
        if not dry_run:
            shutil.rmtree(copy, ignore_errors=True)
            link = claude_dir / name
            if link.is_symlink():
                link.unlink()
        row("skill", name, "removed", "left the pattern")
    for name, source in sorted(wanted.items()):
        copy = agents_dir / name
        source_digest = digest_path(source)
        if copy.exists() or copy.is_symlink():
            present = digest_path(copy)
            if present == source_digest:
                new_lock[name] = source_digest
                row("skill", name, "current")
                _link_claude(claude_dir, name, rows, dry_run)
                continue
            if locked.get(name) != present and not force:
                reason = "edited locally" if name in locked else "not ours"
                if name in locked:
                    new_lock[name] = locked[name]
                row("skill", name, "conflict", f"{reason}; rerun with --force")
                continue
        if not dry_run:
            if copy.is_symlink():
                copy.unlink()
            shutil.rmtree(copy, ignore_errors=True)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                source, copy, symlinks=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        new_lock[name] = source_digest
        row("skill", name, "updated" if name in locked else "vendored")
        _link_claude(claude_dir, name, rows, dry_run)
    for name in sorted(new_lock):
        if _git_ignored(repo, agents_dir / name) or _git_ignored(repo, claude_dir / name):
            row("skill", name, "ignored",
                "git ignores this path, so the skill will not travel with the "
                "repository; un-ignore .agents/skills and .claude/skills")
    if not dry_run:
        path = repo / REPO_LOCK
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": REPO_LOCK_SCHEMA,
                    "house_version": house.version,
                    "patterns": list(pattern_names),
                    "with_house_rules": with_house_rules,
                    "skills": new_lock,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return rows


def _git_ignored(repo: Path, path: Path) -> bool:
    """True when *repo* is a Git checkout whose ignore rules cover *path*."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "-q", str(path)],
            capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _link_claude(
    claude_dir: Path, name: str, rows: list[dict[str, str]], dry_run: bool
) -> None:
    link = claude_dir / name
    target = Path("..") / ".." / ".agents" / "skills" / name
    if link.is_symlink() and os.readlink(link) == str(target):
        return
    if link.exists() and not link.is_symlink():
        rows.append({"harness": "repo", "kind": "skill", "name": name,
                     "action": "conflict",
                     "detail": ".claude/skills entry is a real directory"})
        return
    if not dry_run:
        claude_dir.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            link.unlink()
        link.symlink_to(target)


def repo_status(house: House, repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    lock = read_repo_lock(repo)
    if lock is None:
        return {"repo": str(repo), "state": "not set up"}
    skills: dict[str, str] = {}
    wanted: dict[str, Path] = {}
    for name in lock.get("patterns") or ():
        if name in house.patterns:
            wanted.update(resolve_skills(house, house.patterns[name].skills))
    for name, digest in (lock.get("skills") or {}).items():
        copy = repo / ".agents" / "skills" / name
        if not copy.is_dir():
            skills[name] = "missing"
        elif digest_path(copy) != digest:
            skills[name] = "edited"
        elif name in wanted and digest_path(wanted[name]) != digest:
            skills[name] = "stale"
        else:
            skills[name] = "current"
    for name in wanted:
        skills.setdefault(name, "not vendored")
    return {
        "repo": str(repo),
        "state": "set up",
        "patterns": lock.get("patterns") or [],
        "locked_version": lock.get("house_version"),
        "house_version": house.version,
        "skills": skills,
    }
