# Contributing to Spindle

Spindle is a small public base for composing skill packages into
surface-specific blends. Contributions should keep that base generic: private
tools, proprietary distributions, and organization-specific runners belong in
adapter packages that depend on Spindle.

## Setup

```bash
git clone https://github.com/lavallee/spindle
cd spindle
uv sync --extra dev
uv run --extra dev pytest -q
```

## Making a Change

1. Keep changes scoped to the public platform, sample distribution, or docs.
2. Add or update tests for behavior changes.
3. Run the full suite before opening a PR:
   ```bash
   uv run --extra dev pytest -q
   ```
4. Add a `CHANGELOG.md` entry for user-visible changes.

## Public Surface Guard

`tests/test_public_surface.py` scans the repository for legacy private project
names and private integration strings. If it fails, remove or generalize the
string rather than adding an exemption.

## Private Integrations

If a downstream install needs a private task service, gate sink, scout runner,
registry, or skill alias migration, add a plug point or use the existing
environment/callable hook. Do not import private packages from Spindle core.
