---
name: sandbox-testing
description: Run focused tests and quality checks safely in the Codex sandbox for pflow or the sibling Django repo. Use before testing either repository, especially when uv caches, home-directory writes, subprocess permissions, databases, Redis, or frontend tooling may behave differently inside the sandbox.
---

# Sandbox Testing

## Detect the repository and platform

- pflow: root `pyproject.toml` and root `.venv/`.
- Sibling Django repo: `backend/pyproject.toml`, `backend/.venv/`, and `frontend/`.
- Detect macOS, Linux, or Windows before choosing paths and shell syntax.

## Operating rules

1. Prefer the existing virtualenv executable over `uv run` for Python, pytest, and Ruff inside the sandbox.
2. Validate in layers: collection, one focused test, related files, directory, then the proportional broader suite.
3. Redirect HOME only when the code under test reads or writes user state; do not change HOME reflexively.
4. Treat permission, cache, service, network, and process-launch failures as environment evidence until reproduced through a focused check.
5. Bound unfamiliar Windows subprocess batches to 30 seconds and stop only the exact process tree created by the run.
6. Report the exact command, platform, exit status, and skipped validation. Never claim a full Make target passed when only its component tools ran.

## pflow profile

Run Python tools from the repository root. Preserve pflow's encoding-warning guard so xdist workers inherit it.

macOS:

```bash
HOME=/private/tmp/pflow-test-home PYTHONWARNDEFAULTENCODING=1 \
  .venv/bin/python -m pytest tests/path/test_file.py -q
.venv/bin/ruff check <paths>
.venv/bin/ruff format --check <paths>
```

Linux uses `HOME="${TMPDIR:-/tmp}/pflow-test-home"`. Windows uses `.venv\Scripts\python.exe`; when home isolation is required, set both `HOME` and `USERPROFILE` to the same writable temp directory.

Prefer `.venv/bin/pflow` (or `.venv\Scripts\pflow.exe`) for CLI checks. Defer authoritative Windows shell, subprocess, and broad e2e behavior to pflow's Windows GitHub Actions jobs after a sandbox process failure appears.

## Sibling Django repo profile

The backend virtualenv lives under `backend/`; the frontend uses pnpm.

```bash
cd backend
.venv/bin/python -m pytest apps/<app>/tests/test_file.py -q
.venv/bin/ruff check <paths>
.venv/bin/ruff format --check <paths>

# Repository-level agent tooling tests from backend's environment
.venv/bin/python -m pytest ../scripts/tests -q
```

For frontend changes:

```bash
cd frontend
pnpm exec vitest run <path>
pnpm exec eslint <paths>
pnpm exec tsc -p tsconfig.app.json --noEmit
```

Backend tests may require PostgreSQL and Redis. Check `make doctor`; if the sandbox cannot reach or start a required service, run service-independent checks locally and leave the service-backed proof to that repo's Ubuntu CI. The sibling repo does not use pflow's encoding-warning, redirected-home, Windows Git Bash, or pflow CLI rules unless the changed code independently introduces those concerns.

## Failure signatures

- uv cache permission failure or Tokio/NULL-object startup failure: invoke the virtualenv tool directly.
- User-home write failure: redirect the relevant home variables to workspace temp storage.
- Network, credential, PostgreSQL, Redis, browser, or remote MCP failure: preserve the test and request permission or defer the exact surface to CI.
- Silent long run: poll with a bounded deadline; do not kill unrelated processes by name.
