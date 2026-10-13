"""Find the right catalog skills for a task, hand them over, and learn from it.

The loop a runtime drives, with one command per step:

  find / brief   rank catalog skills for a task and record the selection
  use            hand one skill to the agent (a path, or its text)
  report         record how the work turned out and which skills helped

Ranking is lexical recall (BM25 over name, description, and body), adjusted by
how each skill has fared before, then optionally judged by ``spindle.judge``.
Every step appends to one usage ledger, so a selection, what was actually read,
and the graded outcome can be joined later by selection id or job id.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import judge as judge_mod
from . import paths
from .house import HouseError, read_repo_lock, skill_body

SELECTION_SCHEMA = "spindle.selection/v1"
RECALL_LIMIT = 12
RRF_K = 10
JUDGE_THRESHOLD = 0.6
LEXICAL_FLOOR = 0.5
INLINE_MAX_SKILLS = 2
INLINE_THRESHOLD = 0.7
OUTCOMES = ("accepted", "rejected", "mixed", "unknown")
_WORD = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")
_STOP = frozenset(
    "the and for with that this from into your you are was were have has had not "
    "but can will should would could its it's their there then than them they our "
    "use using used make made need needs want add new get set run all any each "
    "when what which who how why where also just more most some such only over "
    "under about after before must may please task work job file files code".split()
)
_MARKERS = {
    "pyproject.toml": "python", "package.json": "node", "Cargo.toml": "rust",
    "go.mod": "go", "Gemfile": "ruby", "DESCRIPTION": "r", "Package.swift": "swift",
    "wrangler.toml": "cloudflare-workers", "Dockerfile": "docker",
}


def usage_file() -> Path:
    return paths.spindle_home() / "usage.jsonl"


def selections_dir() -> Path:
    return paths.spindle_home() / "selections"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tokens(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for word in _WORD.findall(text.lower()):
        if word not in _STOP:
            seen.setdefault(word, None)
    return list(seen)[:32]


# ---------------------------------------------------------------------- usage


def record(event: dict[str, Any]) -> None:
    path = usage_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": _now(), **event}, sort_keys=True) + "\n")


def read_events() -> list[dict[str, Any]]:
    path = usage_file()
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def usage_summary(events: list[dict[str, Any]] | None = None) -> dict[str, dict[str, int]]:
    """Per-skill counters folded from the usage ledger."""
    events = read_events() if events is None else events
    stats: dict[str, dict[str, int]] = {}
    loaded_by: dict[str, set[str]] = {}

    def bump(ref: str, field: str) -> None:
        row = stats.setdefault(
            ref, dict.fromkeys(
                ("offered", "selected", "loaded", "accepted", "rejected",
                 "helped", "hurt"), 0)
        )
        row[field] += 1

    for event in events:
        keys = [k for k in (event.get("selection"), event.get("job")) if k]
        kind = event.get("kind")
        if kind == "selection":
            for ref in event.get("offered", []):
                bump(ref, "offered")
            for ref in event.get("selected", []):
                bump(ref, "selected")
        elif kind == "loaded":
            bump(event["ref"], "loaded")
            for key in keys:
                loaded_by.setdefault(key, set()).add(event["ref"])
        elif kind == "outcome":
            loaded = set(event.get("loaded", []))
            for key in keys:
                loaded |= loaded_by.get(key, set())
            loaded |= set(event.get("helped", [])) | set(event.get("hurt", []))
            for ref in sorted(loaded):
                if event.get("outcome") in ("accepted", "rejected"):
                    bump(ref, event["outcome"])
            for ref in event.get("helped", []):
                bump(ref, "helped")
            for ref in event.get("hurt", []):
                bump(ref, "hurt")
    return stats


def prior(row: dict[str, int] | None) -> float:
    """Shrunk estimate in (0, 1) that a skill helps; 0.5 with no evidence.

    An explicit helped/hurt verdict counts fully; a graded outcome on a run that
    merely had the skill loaded is weak evidence and counts 0.3.
    """
    if not row:
        return 0.5
    good = row["helped"] + 0.3 * row["accepted"]
    bad = row["hurt"] + 0.3 * row["rejected"]
    return (good + 1) / (good + bad + 2)


# --------------------------------------------------------------------- search


def search(
    index: dict[str, Any],
    task: str,
    *,
    limit: int = RECALL_LIMIT,
    include_kernel: bool = False,
    stats: dict[str, dict[str, int]] | None = None,
    phrases: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Lexical recall over the catalog index, best first.

    ``phrases`` are extra queries (see ``spindle.expand``). Each query ranks the
    catalog on its own and the rankings are fused by reciprocal rank, so a skill
    that one focused phrase puts first is not buried by a long task text.
    """
    queries = [words for words in map(tokens, [task, *(phrases or [])]) if words]
    entries = [
        entry for entry in index.get("skills", [])
        if include_kernel or not entry.get("kernel")
    ]
    if not queries or not entries:
        return []
    stats = usage_summary() if stats is None else stats
    db = sqlite3.connect(":memory:")
    try:
        db.execute(
            "CREATE VIRTUAL TABLE skills USING fts5("
            "ref UNINDEXED, name, description, body, tokenize='porter unicode61')"
        )
        db.executemany(
            "INSERT INTO skills VALUES (?, ?, ?, ?)",
            [
                (e["ref"], e["name"].replace("-", " "), e["description"],
                 e.get("excerpt", ""))
                for e in entries
            ],
        )
        fused: dict[str, float] = {}
        for words in queries:
            query = " OR ".join('"' + word.replace('"', "") + '"' for word in words)
            ranked_refs = db.execute(
                "SELECT ref FROM skills WHERE skills MATCH ? "
                "ORDER BY bm25(skills, 0.0, 8.0, 4.0, 0.3) LIMIT ?",
                (query, limit * 3),
            ).fetchall()
            for rank, (ref,) in enumerate(ranked_refs):
                fused[ref] = fused.get(ref, 0.0) + 1.0 / (RRF_K + rank)
        rows = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
    finally:
        db.close()
    if not rows:
        return []
    by_ref = {entry["ref"]: entry for entry in entries}
    top = max(score for _ref, score in rows) or 1.0
    ranked = []
    for ref, score in rows:
        entry = by_ref[ref]
        skill_prior = prior(stats.get(ref))
        ranked.append(
            {
                **{k: entry[k] for k in ("ref", "source", "name", "description", "path",
                                         "digest", "commit", "words",
                                         "requires_install", "risks")},
                "lexical": round(score / top, 4),
                "prior": round(skill_prior, 4),
                "score": round((score / top) * (0.75 + 0.5 * skill_prior), 4),
            }
        )
    ranked.sort(key=lambda item: (-item["score"], item["ref"]))
    return ranked[:limit]


def project_facts(repo: Path | None) -> dict[str, Any]:
    """Small, code-derived description of the repository a task runs in."""
    if repo is None or not repo.is_dir():
        return {}
    facts: dict[str, Any] = {"name": repo.resolve().name}
    stacks = sorted({kind for name, kind in _MARKERS.items() if (repo / name).exists()})
    if stacks:
        facts["stack"] = stacks
    try:
        lock = read_repo_lock(repo)
    except HouseError:
        lock = None
    if lock and lock.get("patterns"):
        facts["patterns"] = lock["patterns"]
    return facts


def select(
    index: dict[str, Any],
    task: str,
    *,
    k: int = 3,
    repo: Path | None = None,
    job: str | None = None,
    use_judge: str = "auto",
    phrases: list[str] | None = None,
    expand_note: str = "",
    provider: judge_mod.Provider | None = None,
    key: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Rank, optionally judge, and record one selection for a task.

    ``use_judge`` is ``auto`` or ``jev`` (judge when a key is configured) or
    ``none``. With a judgment, only candidates the judge expects to help are
    selected, and an empty selection is a valid answer. Without one the
    selection is a shortlist of the best text matches, marked ``lexical``: text
    match finds the right neighbourhood but cannot tell "relevant" from "shares
    words", so whoever receives the shortlist has to do the judging.
    """
    candidates = search(index, task, phrases=phrases)
    facts = project_facts(repo)
    scores: dict[str, float] | None = None
    judged_by = "none"
    note = ""
    if use_judge != "none" and candidates:
        scores, reason = judge_mod.judge(
            task, candidates, facts, provider=provider, key=key
        )
        if scores is None:
            note = reason
        else:
            judged_by = "jev"
    for candidate in candidates:
        if scores is not None:
            candidate["judged"] = round(scores[candidate["ref"]], 4)
            candidate["selected"] = scores[candidate["ref"]] >= JUDGE_THRESHOLD
        else:
            candidate["judged"] = None
            candidate["selected"] = candidate["lexical"] >= LEXICAL_FLOOR
    if scores is not None:
        candidates.sort(key=lambda c: (-c["judged"], -c["score"], c["ref"]))
    chosen = 0
    for candidate in candidates:
        if candidate["selected"]:
            chosen += 1
            candidate["selected"] = chosen <= k
    task_sha = hashlib.sha256(task.encode("utf-8")).hexdigest()
    selection = {
        "schema": SELECTION_SCHEMA,
        "id": "sel_" + hashlib.sha256(
            f"{task_sha}:{job}:{_now()}:{os.getpid()}".encode()
        ).hexdigest()[:12],
        "created_at": _now(),
        "job": job,
        "task_sha256": task_sha,
        "task_excerpt": task[:400],
        "project": facts,
        "judge": judged_by,
        "judge_policy": judge_mod.JUDGE_POLICY if judged_by == "jev" else None,
        "judge_note": note,
        "expanded_queries": list(phrases or []),
        "expand_note": expand_note,
        "confidence": "judged" if judged_by == "jev" else "lexical",
        "house_version": index.get("house_version"),
        "candidates": candidates,
    }
    if save:
        save_selection(selection)
    return selection


def save_selection(selection: dict[str, Any]) -> Path:
    directory = selections_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{selection['id']}.json"
    path.write_text(json.dumps(selection, indent=1, sort_keys=True) + "\n", "utf-8")
    record(
        {
            "kind": "selection",
            "selection": selection["id"],
            "job": selection.get("job"),
            "judge": selection["judge"],
            "offered": [c["ref"] for c in selection["candidates"]],
            "selected": [c["ref"] for c in selection["candidates"] if c["selected"]],
        }
    )
    return path


def load_selection(
    selection_id: str | None = None, job: str | None = None
) -> dict[str, Any] | None:
    """Fetch a selection by id, or the latest one recorded for a job."""
    if selection_id is None and job is not None:
        for event in reversed(read_events()):
            if event.get("kind") == "selection" and event.get("job") == job:
                selection_id = event["selection"]
                break
    if selection_id is None or not re.fullmatch(r"sel_[0-9a-f]{12}", selection_id):
        return None
    path = selections_dir() / f"{selection_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------- delivery


def read_skill(entry: dict[str, Any]) -> str:
    path = Path(entry["path"]) / "SKILL.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        raise HouseError(
            f"{entry['ref']} is indexed but missing on disk; run `spindle catalog sync`"
        ) from None


def note_loaded(
    entry: dict[str, Any], *, selection: str | None = None, job: str | None = None
) -> None:
    record({"kind": "loaded", "ref": entry["ref"], "digest": entry["digest"],
            "selection": selection, "job": job})


def prompt_block(
    selection: dict[str, Any], *, inline: bool = False, inline_chars: int = 8000
) -> str:
    """A prompt section offering the selected skills to an agent.

    Path delivery lists each skill with where to read it, so the agent pays for
    a skill only if it decides to use it. Inline delivery embeds the text, for
    runtimes that cannot read outside their sandbox.
    """
    chosen = [c for c in selection["candidates"] if c["selected"]]
    if not chosen:
        return ""
    how = (
        "a judge model that expects each to help"
        if selection["confidence"] == "judged"
        else "text match only, so check each description before relying on it"
    )
    lines = [
        "## Skills available for this job",
        "",
        f"Spindle picked these from the house catalog by {how} "
        f"(selection {selection['id']}). They are optional guidance, not "
        "requirements, and never override the task or its acceptance criteria.",
        "",
    ]
    if inline:
        for candidate in chosen:
            body = skill_body(read_skill(candidate)).strip()
            if len(body) > inline_chars:
                body = body[:inline_chars].rstrip() + "\n\n[skill text truncated]"
            lines += [f"### Skill: {candidate['ref']}", "", body, ""]
    else:
        lines += [
            "Read a skill's SKILL.md before the part of the work it covers; files "
            "it references sit beside it.",
            "",
        ]
        for candidate in chosen:
            description = " ".join(candidate["description"].split())[:320]
            note = " Needs its own install; treat as reference." if candidate[
                "requires_install"] else ""
            lines += [
                f"- **{candidate['ref']}**: {description}{note}",
                f"  Read: {Path(candidate['path']) / 'SKILL.md'}",
            ]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def pointer_block(selection: dict[str, Any]) -> str:
    """A prompt section for when nothing was pre-selected: how to ask instead.

    An unjudged shortlist built from a whole commission is mostly noise, and
    noise in a prompt costs attention. The agent, once it knows what it is about
    to do, can write a far better query than the commission text is.
    """
    return (
        "## Skills on demand\n\n"
        "No skill was pre-selected for this job. A catalog of vetted skills is "
        "available if you reach work you are unsure how to do well: "
        '`spindle find "<a few words for what you are about to do>"` lists '
        "candidates, and `spindle use <source>/<skill>` prints the path of one "
        "to read. Skip this for routine work. Skills are optional guidance and "
        "never override the task or its acceptance criteria "
        f"(selection {selection['id']}).\n"
    )


def skills_record(selection: dict[str, Any], delivery: str) -> dict[str, Any]:
    """The compact record a runtime keeps beside its own receipt."""
    return {
        "selection": selection["id"],
        "confidence": selection["confidence"],
        "house_version": selection.get("house_version"),
        "delivery": delivery,
        "offered": [
            {
                "ref": c["ref"],
                "digest": c["digest"],
                "judged": c["judged"],
                **(
                    {"path": str(Path(c["path"]) / "SKILL.md")}
                    if delivery == "path"
                    else {}
                ),
            }
            for c in selection["candidates"]
            if c["selected"]
        ],
    }


def report(
    *,
    outcome: str,
    selection_id: str | None = None,
    job: str | None = None,
    loaded: list[str] | None = None,
    helped: list[str] | None = None,
    hurt: list[str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    if outcome not in OUTCOMES:
        raise HouseError(f"outcome must be one of: {', '.join(OUTCOMES)}")
    selection = load_selection(selection_id, job)
    if selection is None and not (loaded or helped or hurt):
        raise HouseError("nothing to report on: no selection found and no skill named")
    selection_key = selection["id"] if selection else selection_id
    job = job or (selection or {}).get("job")
    already = {
        event["ref"]
        for event in read_events()
        if event.get("kind") == "loaded"
        and selection_key is not None
        and event.get("selection") == selection_key
    }
    digests = {c["ref"]: c["digest"] for c in (selection or {}).get("candidates", [])}
    for ref in sorted(set(loaded or []) - already):
        record({"kind": "loaded", "ref": ref, "digest": digests.get(ref),
                "selection": selection_key, "job": job, "observed_by": "runtime"})
    event = {
        "kind": "outcome",
        "selection": selection_key,
        "job": job,
        "outcome": outcome,
        "loaded": sorted(set(loaded or [])),
        "helped": sorted(set(helped or [])),
        "hurt": sorted(set(hurt or [])),
        "note": note[:500],
    }
    record(event)
    return event
