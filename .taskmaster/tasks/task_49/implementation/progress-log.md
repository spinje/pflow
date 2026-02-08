# Task 49: Prepare and Publish pflow to PyPI — Progress Log

## Status: Ready to publish (blocked on repo going public)

## Date: 2026-02-08

## What was done

### 1. Package name decision

- **`pflow` is taken on PyPI** — registered by David O'Connor (PEP 582 package manager), last updated November 2019, version 0.1.9
- **Chose `pflow-cli`** as the package name. Well-established pattern (aws-cli, vercel-cli). CLI command stays `pflow`.
- PEP 541 name transfer request for `pflow` can be filed later via admin@pypi.org (not urgent)

### 2. pyproject.toml changes

| Field | Before | After |
|-------|--------|-------|
| `name` | `pflow` | `pflow-cli` |
| `version` | `0.0.1` | `0.8.0` |
| `description` | `"cli"` | `"Reusable CLI workflows from shell, LLM, HTTP, and MCP nodes"` |
| `keywords` | `['python']` | `['workflow', 'cli', 'automation', 'llm', 'mcp', 'ai-agent', 'agent-skill']` |
| `classifiers` | generic | Added `Environment :: Console`, `Operating System :: MacOS`, `Operating System :: POSIX :: Linux`, `Topic :: Software Development :: Build Tools` |
| `urls` | old GitHub Pages URLs | `pflow.run` / `docs.pflow.run` |

### 3. Sdist exclusions added

Added `[tool.hatch.build.targets.sdist]` exclude list to drop dev-only files:
- `.claude/`, `.cursor/`, `.github/`, `.taskmaster/`, `architecture/`, `assets/`, `docs/`, `examples/`, `releases/`, `scratchpads/`, `scripts/`, `tests/`
- `.pre-commit-config.yaml`, `CLAUDE.md`, `CONTRIBUTING.md`, `Makefile`, `SECURITY.md`, `tox.ini`, `uv.lock`

**Result:** Sdist went from 18MB / 2,000+ files to 547KB / 196 files.

### 4. Dynamic version in CLI

Replaced hardcoded `click.echo("pflow version 0.0.1")` in `src/pflow/cli/main.py` with:
```python
from importlib.metadata import version as pkg_version
try:
    ver = pkg_version("pflow-cli")
except Exception:
    ver = "0.8.0"
click.echo(f"pflow version {ver}")
```

Updated version test in `tests/test_cli/test_cli.py` to assert `startswith("pflow version ")` instead of exact match.

### 5. Release workflow updated

`.github/workflows/on-release-main.yml`:
- Removed `UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}`
- Added `permissions: id-token: write` to publish job
- Changed publish command to `uv publish --trusted-publishing always`

### 6. README updated

- Install instructions changed from `git+https://github.com/...` to `pip install pflow-cli` / `uv tool install pflow-cli` / `pipx install pflow-cli`
- `uv tool install` listed first as recommended
- Added platform note: "macOS and Linux only for now. Windows is untested."

### 7. Lock file

Ran `uv lock` to update `uv.lock` after package rename.

## PyPI account setup (done by user)

- Created PyPI account with 2FA
- Connected GitHub account
- Configured Trusted Publisher:
  - Owner: `spinje`
  - Repository: `pflow`
  - Workflow: `on-release-main.yml`
  - Environment: (blank)

## Verification

- `make check` passes (ruff, mypy, deptry)
- All 3,741 tests pass
- `uv build` produces `pflow_cli-0.8.0-py3-none-any.whl` (662KB) and `pflow_cli-0.8.0.tar.gz` (547KB)
- Wheel installs successfully and `pflow --version` returns `pflow version 0.8.0`

## What remains to publish

1. Make the repo public (required for Trusted Publishers OIDC)
2. Tag and create a GitHub Release (`gh release create v0.8.0`)
3. CI publishes to PyPI automatically

## Decisions made

- **Package name**: `pflow-cli` (not `pflow` — taken on PyPI)
- **Auth method**: OIDC Trusted Publishers (not API token)
- **Platform scope**: macOS + Linux only for v0.8.0
- **No TestPyPI dry run**: Wheel install test was sufficient for now; can do TestPyPI before real release if desired

## Commit

`7f8caae` — "prepare pflow-cli for PyPI release"

Files changed:
- `.github/workflows/on-release-main.yml`
- `README.md`
- `pyproject.toml`
- `src/pflow/cli/main.py`
- `tests/test_cli/test_cli.py`
- `uv.lock`
