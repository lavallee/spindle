"""Scaffold writers for new packages and distributions.

package_new(name, dest, skills, capabilities) — write a pip-installable
package directory with pyproject.toml and one stub SKILL.md per skill.

dist_new(name, dest, source_dir, packages) — write a distribution
pyproject.toml and a stub preempt.md.

Both functions raise ValueError for names that don't match the allowed
pattern: lowercase letters, digits, and hyphens only.
"""

from __future__ import annotations

import re
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _validate_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Invalid name {name!r}: must start with a lowercase letter and "
            "contain only lowercase letters, digits, and hyphens."
        )


# ---------------------------------------------------------------------------
# Package scaffold
# ---------------------------------------------------------------------------

_PACKAGE_PYPROJECT = """\
[project]
name = "{name}"
version = "0.1.0"
description = ""
requires-python = ">=3.11"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{importable}"]

[tool.spindle.package]
name = "{name}"
version = "0.1.0"
distribution = ""
skills = [{skills_list}]
capabilities = [{capabilities_list}]
"""

_SKILL_MD = """\
# {skill}

TODO: describe what this skill does.

## Usage

    /{skill} [args]

## Notes

Add usage examples and notes here.
"""


def package_new(
    name: str,
    dest: str | Path,
    skills: list[str],
    capabilities: list[str],
) -> list[Path]:
    """Write a new package scaffold under *dest*.

    Creates:
      <dest>/pyproject.toml
      <dest>/<importable>/__init__.py
      <dest>/<importable>/<skill>.md   (one per skill)

    Returns the list of paths written.
    """
    _validate_name(name)
    for skill in skills:
        _validate_name(skill)

    dest = Path(dest)
    importable = name.replace("-", "_")

    skills_list = ", ".join(f'"{s}"' for s in skills)
    capabilities_list = ", ".join(f'"{c}"' for c in capabilities)

    pyproject_text = _PACKAGE_PYPROJECT.format(
        name=name,
        importable=importable,
        skills_list=skills_list,
        capabilities_list=capabilities_list,
    )

    written: list[Path] = []

    pyproject_path = dest / "pyproject.toml"
    pyproject_path.parent.mkdir(parents=True, exist_ok=True)
    pyproject_path.write_text(pyproject_text)
    written.append(pyproject_path)

    pkg_dir = dest / importable
    pkg_dir.mkdir(parents=True, exist_ok=True)

    init_path = pkg_dir / "__init__.py"
    init_path.write_text("")
    written.append(init_path)

    for skill in skills:
        skill_path = pkg_dir / f"{skill}.md"
        skill_path.write_text(_SKILL_MD.format(skill=skill))
        written.append(skill_path)

    return written


# ---------------------------------------------------------------------------
# Distribution scaffold
# ---------------------------------------------------------------------------

_DIST_PYPROJECT = """\
[project]
name = "{name}"
version = "0.1.0"
description = ""
requires-python = ">=3.11"
dependencies = [{deps_list}]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{importable}"]

[tool.spindle.distribution]
display_name = "{display_name}"
description = ""
source_dir = "{source_dir}"
preempt_snippet = "preempt.md"
"""

_PREEMPT_MD = """\
# {display_name} — preempt

TODO: describe this distribution's active skills here so the model knows
what is available.
"""


def dist_new(
    name: str,
    dest: str | Path,
    source_dir: str,
    packages: list[str],
) -> list[Path]:
    """Write a new distribution scaffold under *dest*.

    Creates:
      <dest>/pyproject.toml
      <dest>/preempt.md

    *source_dir* is written verbatim into ``[tool.spindle.distribution].source_dir``
    (typically a relative path like ``"../../"``).

    Returns the list of paths written.
    """
    _validate_name(name)

    dest = Path(dest)
    importable = name.replace("-", "_")
    display_name = name.replace("-", " ").title()

    deps_list = ", ".join(f'"{p}"' for p in packages)

    pyproject_text = _DIST_PYPROJECT.format(
        name=name,
        importable=importable,
        display_name=display_name,
        source_dir=source_dir,
        deps_list=deps_list,
    )

    written: list[Path] = []

    dest.mkdir(parents=True, exist_ok=True)

    pyproject_path = dest / "pyproject.toml"
    pyproject_path.write_text(pyproject_text)
    written.append(pyproject_path)

    preempt_path = dest / "preempt.md"
    preempt_path.write_text(_PREEMPT_MD.format(display_name=display_name))
    written.append(preempt_path)

    return written
