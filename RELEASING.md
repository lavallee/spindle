# Releasing Spindle

This is the canonical release checklist.

## Versioning

Spindle follows semantic versioning. The package version lives in:

- `pyproject.toml` -> `[project].version`

Bump rules:

- Patch: bug fixes, docs, and sample distribution corrections.
- Minor: new backward-compatible CLI, metadata, sink, scout, or composition
  behavior.
- Major: breaking changes to CLI flags, metadata schemas, or generated surface
  contracts.

## Checklist

1. Run the full suite:
   ```bash
   uv run --extra dev pytest -q
   ```
2. Bump `pyproject.toml` and refresh the lockfile:
   ```bash
   uv lock
   ```
3. Update `CHANGELOG.md` with a dated heading and concrete changes.
4. Update `README.md` and `docs/index.html` if the public surface changed.
5. Commit the release changes:
   ```bash
   git commit -m "chore(release): X.Y.Z"
   ```
6. Tag and push:
   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin main
   git push origin vX.Y.Z
   ```
7. Create the GitHub release:
   ```bash
   gh release create vX.Y.Z --title "vX.Y.Z" --notes-file CHANGELOG.md
   ```

## Public Project Conventions

- Keep the default install lightweight and fully public.
- Keep private integrations behind environment variables, callables, or adapter
  packages.
- Keep `examples/spindle-sample` runnable as the reference distribution.
- Keep CI green before tagging.
