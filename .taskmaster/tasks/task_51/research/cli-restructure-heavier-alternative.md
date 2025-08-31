## CLI Restructure (Heavier Alternative) — Plan, Rationale, and Steps

This document proposes a clearer CLI module architecture to permanently avoid the Python 3.10 patching ambiguity and improve understandability and maintainability. It replaces the current `main`-centric layout with explicit module names and stable import paths.

### Executive Summary

- Problem: Python 3.10 resolves `pflow.cli.main` to the package attribute exported by `pflow/cli/__init__.py` (a Click `Command`), not the submodule, causing `unittest.mock.patch("pflow.cli.main.X")` to attempt patching attributes on a `Command` object. This produces the observed failures.
- Root cause: Naming collision between a package-level alias (`main`) and a submodule file named `main.py`.
- Heavyweight fix: Rename the workflow command module to a non-ambiguous name (e.g., `workflow.py`) and stop exporting a package-level `main`. Route invocations via an explicit router. Update tests to import from the new explicit path.
- Outcome: Unambiguous import and patch targets across all Python versions; simpler mental model; better separation of concerns.

### Goals

- Eliminate ambiguous references to `main` at the package level.
- Make module boundaries explicit: routing vs workflow command vs subcommands.
- Keep the public CLI entry point unchanged (`pflow` still works the same via `pyproject` script entry).
- Improve test stability (especially for Python 3.10) and readability of imports.

### Non-Goals

- Changing CLI behavior or output text.
- Renaming subcommand modules that are already well-named (`registry.py`, `mcp.py`, `commands/settings.py`) unless necessary.

### Proposed Module Layout

Current key files:
- `pflow/cli/main.py` — defines the workflow Click command, aliases `main = workflow_command`.
- `pflow/cli/main_wrapper.py` — routes between workflow command and subcommands.
- `pflow/cli/__init__.py` — re-exports `workflow_command as main` and `cli_main`.

Proposed layout (after restructure):
- `pflow/cli/router.py` (rename from `main_wrapper.py`) — contains `cli_main()` only. No other exports.
- `pflow/cli/workflow.py` (rename from `main.py`) — contains the workflow Click command `workflow_command`. No `main` alias.
- `pflow/cli/__init__.py` — exports only `cli_main` from `router.py`.
- `pflow/cli/registry.py`, `pflow/cli/mcp.py`, `pflow/cli/commands/settings.py` — unchanged; imported by router.

Resulting import expectations:
- CLI script entry (unchanged): `pflow = "pflow.cli:cli_main"` (via `pyproject.toml`).
- Tests and internal callers should import the workflow command explicitly: `from pflow.cli.workflow import workflow_command`.
- Patching targets use explicit module paths: e.g., `patch("pflow.cli.workflow.Registry")`.

### Why This Works (and Fixes 3.10)

- Removing the package-level `main` export and avoiding a `main.py` module eliminates any ambiguity when referencing `pflow.cli.workflow`.
- `unittest.mock.patch("pflow.cli.workflow.X")` will always point to the module, not to a package attribute, across Python versions.

### Step-by-Step Changes

1) Rename modules and adjust imports
- Rename `pflow/cli/main_wrapper.py` → `pflow/cli/router.py`.
- Rename `pflow/cli/main.py` → `pflow/cli/workflow.py`.
- In `pflow/cli/router.py`, update imports to:
  - `from .workflow import workflow_command`
  - `from .registry import registry`
  - `from .mcp import mcp`
  - `from .commands.settings import settings`
- Remove any import cycles by keeping imports inside `cli_main()` if needed (as they are today) to avoid circulars.

2) Stop exporting `main` at package level
- Update `pflow/cli/__init__.py` to export only `cli_main`:
  - `from .router import cli_main`
  - `__all__ = ["cli_main"]`
- Do NOT alias `workflow_command` as `main` anywhere.

3) Keep the CLI entry point the same
- `pyproject.toml` remains:
  - `[project.scripts] pflow = "pflow.cli:cli_main"`
- No behavioral change for end users.

4) Update all internal references
- Replace any `from pflow.cli.main import ...` with `from pflow.cli.workflow import ...`.
- Replace any `pflow.cli.main` dotted paths in code (if any) with `pflow.cli.workflow`.

5) Update tests to use explicit module path
- Change imports in tests that reference package-level `main` to module-level workflow command:
  - `from pflow.cli import main` → `from pflow.cli.workflow import workflow_command as main`
  - `from pflow.cli.main import main` → `from pflow.cli.workflow import workflow_command as main`
- Update patch targets so they refer to the module, not the package attribute:
  - `patch("pflow.cli.main.Registry")` → `patch("pflow.cli.workflow.Registry")`
  - `patch("pflow.cli.main.WorkflowManager")` → `patch("pflow.cli.workflow.WorkflowManager")`
  - `patch("pflow.cli.main.workflow_command")` → `patch("pflow.cli.workflow.workflow_command")`

6) Optional naming polish (low risk)
- If desired, rename `router.py` to `entrypoint.py` or keep `router.py` to emphasize routing responsibility.
- Keep `workflow.py` concise and focused on the workflow command; avoid re-exporting or helper aliasing.

### File/Import Mapping (Before → After)

- `pflow/cli/main.py` → `pflow/cli/workflow.py`
  - `main = workflow_command` (removed)
- `pflow/cli/main_wrapper.py` → `pflow/cli/router.py`
- `pflow/cli/__init__.py`:
  - Before: exports `main` and `cli_main`.
  - After: exports only `cli_main`.
- Test imports:
  - `from pflow.cli import main` → `from pflow.cli.workflow import workflow_command as main`
  - `from pflow.cli.main import main` → `from pflow.cli.workflow import workflow_command as main`
- Patch targets:
  - `pflow.cli.main.*` → `pflow.cli.workflow.*`

### Risks and Mitigations

- Risk: Missed import references to `pflow.cli.main`.
  - Mitigation: repo-wide search and update; CI will catch any stragglers.
- Risk: Circular imports after renaming.
  - Mitigation: keep imports inside functions in `router.py` (as today); avoid top-level cross-imports.
- Risk: Test brittleness if any tests assume `pflow.cli:main` exists.
  - Mitigation: update tests to import from `pflow.cli.workflow` explicitly; do not reintroduce a package-level alias.

### Verification Plan

- Static checks:
  - Run `make check` (ruff, mypy) and ensure no broken imports or style issues.
- Tests:
  - Run the full suite under Python 3.10, 3.11, 3.12, 3.13.
  - Specifically confirm previously failing tests now pass:
    - `tests/test_cli/test_registry_cli.py::test_main_wrapper_routes_unknown_to_workflow_command` (patch target updated)
    - All tests in `tests/test_cli/test_workflow_save_integration.py` (patch targets updated)
    - All tests in `tests/test_cli/test_workflow_output_handling.py` (patch targets updated)
- Manual spot checks:
  - `uv run pflow --help` renders correctly.
  - `uv run pflow registry list` routes via router and works.
  - `uv run pflow mcp --help` works.
  - `uv run pflow "echo something"` still enters the workflow command.

### Rollback Plan

- The change is fully reversible:
  - Move files back to original names (`workflow.py` → `main.py`, `router.py` → `main_wrapper.py`).
  - Restore package-level alias in `__init__.py`.
  - Revert test import paths.
- No persistent data or external interfaces are impacted.

### Rationale Recap

- The ambiguity stems from `main` being both a module and a package attribute. This restructure removes the collision entirely rather than patching around it, yielding:
  - Clear ownership: `router.py` routes; `workflow.py` implements the workflow command.
  - Stable, explicit import/patch targets.
  - Lower cognitive load and fewer future surprises (especially during refactors or upgrades).

### Estimated Effort

- Rename + imports update: ~30–45 minutes.
- Test import and patch target updates: ~30–45 minutes.
- CI run and fixes: ~15–30 minutes.
- Total: ~1.5–2.0 hours.

### Acceptance Criteria

- No references to package-level `main` remain.
- All tests green on Python 3.10–3.13.
- `pflow` CLI continues to operate identically for end-to-end behavior.

---

If we want to go further, we can formalize the CLI package with a small ADR-style note to document the design intent: no package-level aliases that shadow submodule names; routing responsibility is isolated; commands are in single-purpose modules.
