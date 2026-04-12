# Task 151 Progress Log

## Status

- Current phase: Code review fixes complete
- Overall state: implementation complete, two rounds of code review fixes applied, test backfill pending decision
- Last updated: 2026-04-12

## Verified Context

- Verified: `src/pflow/cli/main_wrapper.py` still performs manual `sys.argv` routing between workflow execution and named command groups.
- Verified: `src/pflow/cli/main.py` still combines entrypoint concerns with workflow execution orchestration.
- Verified: workflow commands are still nested under `src/pflow/cli/commands/workflow.py`.
- Verified: registry commands are still nested under `src/pflow/cli/commands/registry.py`, with single-node execution in `src/pflow/cli/commands/registry_run.py`.
- Verified: MCP server listing still occupies `pflow mcp list` in `src/pflow/cli/commands/mcp.py`.
- Verified: `src/pflow/cli/CLAUDE.md` and `src/pflow/cli/commands/CLAUDE.md` still describe the pre-parser architecture and old command surface, so those docs will need to change later in the task.

## Phase Plan

1. Phase 1: replace wrapper routing with a Click-native default-command group, extract workflow execution to `commands/run.py`, add the `pflow.guide` placeholder package, and update phase-1 tests/imports.
2. Phase 2: flatten workflow commands into top-level `list`, `find`, `describe`, `history`, and `save`.
3. Phase 3: add `guide` and `probe`, then delete legacy `registry` and `instructions` command entrypoints.
4. Phase 4: restructure the `mcp` namespace around tool-first `list/find/describe` and move server listing to `servers`.
5. Phase 5+: rename shared services, consolidate reserved names and settings paths, update stale production strings, then finish docs and verification.

## Decisions

- Decision: use the task-spec placeholder entry content for both `pflow --help` and `pflow guide` in Phase 1. Task 77 owns the real guide content.
- Decision: follow the implementation plan phases in order unless the live code reveals a dependency mismatch that requires reordering.
- Decision: add `src/pflow/cli/__main__.py` so the new entrypoint is runnable as `python -m pflow.cli`. This was not called out explicitly in the plan, but the subprocess test path needs a package-level module after `main_wrapper.py` removal.

## Completed Phases

### Phase 1: Foundation — Click-native Routing + `run.py` Extraction

- Completed: created `src/pflow/guide/__init__.py` and `src/pflow/guide/entry.md` with the shared placeholder entry content for root help.
- Completed: extracted workflow execution orchestration from `src/pflow/cli/main.py` into `src/pflow/cli/commands/run.py`.
- Completed: rewrote `src/pflow/cli/main.py` into a small Click group entrypoint with `PflowCLI` default-command routing and hidden `run` registration.
- Completed: updated `src/pflow/cli/__init__.py` to import `cli_main` from `main.py`.
- Completed: deleted `src/pflow/cli/main_wrapper.py`.
- Completed: added `src/pflow/cli/__main__.py` for direct module execution.
- Completed: updated phase-1 test imports, subprocess module targets, and patch targets to the new entrypoint / `commands.run` module.

### Phase 1 Verification

- Verified: `python3 -m py_compile src/pflow/cli/main.py src/pflow/cli/commands/run.py src/pflow/guide/__init__.py`
- Verified: `UV_CACHE_DIR=/tmp/uv-cache UV_OFFLINE=1 uv run --no-sync pytest tests/test_cli/test_cli.py tests/test_cli/test_main.py tests/test_cli/test_workflow_resolution.py tests/test_cli/test_validate_only.py tests/test_cli/test_validation_before_execution.py tests/test_cli/test_workflow_commands.py tests/test_cli/test_nested_workflow_cli.py tests/test_cli/test_registry_cli.py -q`
- Result: 173 passed

### Phase 2: Flatten Workflow Commands

- Completed: added top-level workflow command modules: `src/pflow/cli/commands/list.py`, `find.py`, `describe.py`, `history.py`, and `save.py`.
- Completed: switched `src/pflow/cli/main.py` registration from the nested `workflow` group to the new top-level commands.
- Completed: deleted `src/pflow/cli/commands/workflow.py`.
- Completed: updated workflow command tests and save-command tests to target the new top-level command modules.
- Completed: updated the workflow list formatter empty-state guidance from `pflow workflow save` to `pflow save`.

### Phase 2 Verification

- Verified: `UV_CACHE_DIR=/tmp/uv-cache UV_OFFLINE=1 uv run --no-sync pytest tests/test_cli/test_workflow_commands.py tests/test_cli/test_workflow_save_cli.py tests/test_cli/test_workflow_save_security.py -q`
- Result: 53 passed

### Phase 3: New Commands + Deletions

- Completed: added `src/pflow/cli/commands/guide.py` and `src/pflow/cli/commands/probe.py`.
- Completed: moved node-ID normalization into `src/pflow/registry/node_id.py` and exported it from `pflow.registry`.
- Completed: added internal probe execution module `src/pflow/cli/commands/_probe_impl.py`.
- Completed: removed `src/pflow/cli/commands/registry.py`, `registry_run.py`, and `instructions.py`.
- Completed: updated `src/pflow/cli/main.py` registration to expose `guide` and `probe` and drop `registry` / `instructions`.
- Completed: replaced obsolete registry/instructions tests with focused tests for `guide`, `probe`, and node-ID normalization.
- Inconsistency with plan: instead of following the plan's exact registry/instructions test-file split and rename structure, I replaced the removed-surface coverage with smaller new command-focused tests. The behavior coverage remained, but the file layout diverged from the plan.

### Phase 3 Verification

- Verified: `python3 -m py_compile src/pflow/cli/main.py src/pflow/cli/commands/guide.py src/pflow/cli/commands/probe.py src/pflow/cli/commands/_probe_impl.py src/pflow/registry/node_id.py`
- Verified: `UV_CACHE_DIR=/tmp/uv-cache UV_OFFLINE=1 uv run --no-sync pytest tests/test_cli/test_probe.py tests/test_cli/test_guide.py tests/test_cli/test_node_id_normalization.py tests/test_cli/test_main.py tests/test_cli/test_cli.py tests/test_cli/test_workflow_commands.py tests/test_cli/test_workflow_save_cli.py tests/test_cli/test_workflow_save_security.py -q`
- Result: 101 passed

### Phase 4: MCP Namespace Restructure

- Completed: changed `pflow mcp list` (servers) into `pflow mcp servers`.
- Completed: implemented new tool-first `pflow mcp list [keywords...]` with grouped summary and filtered detail modes.
- Completed: implemented `pflow mcp find` using MCP-scoped registry metadata.
- Completed: renamed `pflow mcp info` to `pflow mcp describe` and removed `pflow mcp tools`.
- Completed: added `registry_metadata` scoping support to `src/pflow/registry/discovery.py`.
- Completed: replaced the old mixed discovery test file with focused `test_find.py` and `test_mcp_commands.py`.
- Inconsistency with plan: legacy registry-related tests were removed before the MCP phase was fully complete, then replaced in this phase by new MCP-surface tests rather than migrated in-place.

### Phase 4 Verification

- Verified: `UV_CACHE_DIR=/tmp/uv-cache UV_OFFLINE=1 uv run --no-sync pytest tests/test_cli/test_find.py tests/test_cli/test_mcp_commands.py tests/test_cli/test_guide.py tests/test_cli/test_probe.py tests/test_cli/test_node_id_normalization.py tests/test_cli/test_main.py tests/test_cli/test_cli.py tests/test_cli/test_workflow_commands.py tests/test_cli/test_workflow_save_cli.py tests/test_cli/test_workflow_save_security.py -q`
- Result: 110 passed

### Phase 5 + 5.5: Shared Service Renames + Cleanup

- Completed: renamed workflow discovery function to `find_workflow()` and component discovery function to `find_components()`.
- Completed: updated CLI and MCP service import sites to use the renamed discovery helpers.
- Completed: renamed `src/pflow/cli/discovery_errors.py` to `src/pflow/cli/find_errors.py` and updated callers.
- Completed: consolidated reserved workflow names in `save_service.py` and made `WorkflowManager` delegate to the shared validator.
- Completed: flattened `pflow settings registry output-mode` to `pflow settings output-mode`.
- Completed: updated stale user-facing command references across runtime/compiler, skills, rerun display, diagnostics, exceptions, and MCP-node guidance strings.

### Phase 5 Verification

- Verified: `UV_CACHE_DIR=/tmp/uv-cache UV_OFFLINE=1 uv run --no-sync pytest tests/test_core/test_workflow_discovery.py tests/test_registry/test_component_discovery.py tests/test_cli/test_settings_cli.py tests/test_core/test_skill_service.py tests/test_cli/test_skills.py tests/test_cli/test_rerun_display.py tests/test_execution/formatters/test_validation_formatter.py tests/test_core/test_diagnostic.py tests/test_cli/test_find.py tests/test_cli/test_mcp_commands.py tests/test_cli/test_workflow_resolution.py -q`
- Result: 272 passed

## Core Insights

- Insight: most of the Phase 2 work was not the command code itself; it was removing old `workflow` assumptions embedded in test fixtures and user-facing formatter text.
- Insight: the new `list` semantics need explicit smart-case coverage because the old nested command only exercised case-insensitive filtering.
- Insight: keeping the formatter shared was still the right call, but its embedded guidance strings are part of the CLI surface and must be updated alongside command routing.
- Insight: the cleanest way to remove the `registry` surface was to replace its tests, not keep compatibility shims. A smaller probe-focused test set is easier to keep aligned with the new CLI contract.
- Insight: moving node-ID normalization into the registry package turns it into a reusable pure function, which simplifies both probe behavior and test coverage.
- Insight: the MCP rewrite is easiest to reason about when the registry is treated as the source of truth for tool metadata and the server manager is treated as configuration state. Splitting those concerns made the grouped summary logic straightforward.
- Insight: discovery needed registry scoping before naming cleanup. Adding the optional `registry_metadata` parameter early kept the CLI rewrite unblocked and left the actual function rename for the later cleanup phase.
- Insight: the stale-command cleanup touched more than obvious CLI modules. Saved skill templates, rerun hints, compiler diagnostics, and validation suggestions all embed CLI commands and needed to move in lockstep with the surface rename.
- Insight: renaming the discovery helpers after the MCP rewrite kept the change reversible. The CLI behavior was already stable, so the later rename became a mechanical consistency pass instead of a behavior change.

## Context Changes / Discoveries

- Discovery: `uv run` crashes in this sandbox unless `--no-sync` is used. Verification commands should use `UV_CACHE_DIR=/tmp/uv-cache UV_OFFLINE=1 uv run --no-sync ...` here.
- Discovery: `click.group(no_args_is_help=True)` was insufficient with the custom group subclass. The working behavior required `invoke_without_command=True` plus an explicit `ctx.get_help()` path when no subcommand is invoked.
- Discovery: several CLI tests assumed writable `HOME`. Targeted test updates now set `HOME` to `tmp_path` where needed to keep trace/report and `~` path tests valid under sandbox restrictions.
- Discovery: the original single-node formatter path expected `format_type`, not a `show_structure` argument. The probe implementation needed to map its UX contract onto the existing formatter API instead of forwarding a non-existent keyword.
- Discovery: the broader CLI verification exposed tests that were still asserting old stdin/planner expectations. The correct resolution was to preserve the new root-help fallback and current stdin-routing contract, then update the tests to that clarified behavior rather than reintroduce the old assumptions.

### Phase 6: Docs + Final Verification

- Completed: updated the high-value user/agent-facing docs and guides touched by the new CLI surface, including `README.md`, CLI `CLAUDE.md` files, CLI resource guides, and key non-historical docs/architecture pages.
- Completed: deleted obsolete CLI reference pages `docs/reference/cli/workflow.mdx` and `docs/reference/cli/registry.mdx`.
- Completed: created new top-level CLI reference pages for `list`, `find`, `describe`, `history`, `save`, `guide`, and `probe`.
- Completed: updated `docs/docs.json` navigation and `docs/reference/cli/index.mdx` to point at the new top-level CLI reference pages.
- Completed: verified the code-side stale-command grep for `src/pflow/**/*.py` is clean.
- Verified: `UV_CACHE_DIR=/tmp/uv-cache UV_OFFLINE=1 uv run --no-sync pytest tests/test_cli tests/test_core/test_workflow_discovery.py tests/test_registry/test_component_discovery.py tests/test_execution/formatters/test_validation_formatter.py tests/test_core/test_skill_service.py tests/test_core/test_diagnostic.py -q`
- Result: 630 passed

## Final Notes

- Historical docs under `architecture/historical/` were intentionally left untouched.
- Non-historical docs received targeted CLI-surface updates, but the full guide-content redesign still belongs to Task 77.
- Residual docs note: the docs are directionally correct for Task 151, but some pages were updated via targeted replacements/manual triage rather than full editorial rewrites. `docs/reference/cli/mcp.mdx` is the strongest candidate for a future polish pass because the `mcp list` / `mcp servers` split changed semantics, not just names.
- Post-verification fix: `WorkflowManager._validate_workflow_name()` initially delegated too literally to the shared validator and lost the historical `"Invalid workflow name"` prefix for format errors. Restored that manager-level wrapper text so existing manager/save callers keep their previous error contract while validation logic remains centralized.
- Verified post-fix: `UV_CACHE_DIR=/tmp/uv-cache UV_OFFLINE=1 uv run --no-sync pytest tests/test_core/test_workflow_manager.py tests/test_cli/test_workflow_save_security.py tests/test_core/test_workflow_save_service.py -q`
- Post-fix result: 89 passed
- Post-check fix: replaced the root CLI `SIGPIPE` `try/except/pass` block with `contextlib.suppress(AttributeError)` to satisfy `ruff` SIM105.
- Post-check fix: corrected `_probe_impl.py` to call `ExecutionCache.store()` with the full `(execution_id, node_type, params, outputs)` signature. The extracted probe implementation had accidentally collapsed that call during refactoring, which `mypy` caught.

## Post-Implementation Audit (2026-04-12)

Comprehensive audit by a fresh agent after the "implementation completed" commit. Findings and fixes:

### Baseline: Green
- 4704 tests pass, 0 failures, 0 skips
- `make check` clean (ruff, mypy 176 files, deptry)
- MCP server boundary respected (only 2 import renames in `discovery_service.py`)

### Audit Fixes Applied

**A. Stale references in production code (9 hits → 0):**
- `read_fields.py`: "registry run" → "probe" in docstring/help text (agent-facing)
- `registry_error_helpers.py`: `enrich_for_registry_run` → `enrich_for_probe`, `_registry_run_suggestions` → `_probe_suggestions` (function renames + docstrings)
- `smart_filter.py`, `execution_cache.py`: "registry run" → "probe" in docstrings
- `mcp_server/services/execution_service.py`: import updated for renamed function
- `test_registry_error_helpers.py`, `test_connection_pool.py`: imports/comments updated

**B. Stale references in docs (9 hits → 0):**
- `adding-mcp-servers.mdx`: `mcp tools` → `mcp list`, `mcp info` → `mcp describe`
- `nodes/index.mdx`, `nodes/mcp.mdx`: `mcp tools` → `mcp list`
- `configuration.mdx`: `pflow registry scan` → auto-regeneration description
- `roadmap.mdx`: `pflow workflow save` → `pflow save`
- `probe.mdx`: removed reference to old command name

**C. Stale references in architecture docs (3 hits → 0):**
- `architecture.md`: `registry search` → `mcp list`/`mcp find`
- `ir-schema.md`: `pflow registry --help` → `pflow mcp --help`

**D. CLAUDE.md files rewritten:**
- `src/pflow/cli/CLAUDE.md`: Complete rewrite — new PflowCLI routing architecture, correct file structure (no `main_wrapper.py`/`discovery_errors.py`), correct dependency graph, accurate main.py description (~113 lines entry point), split command flags into group-level vs run-level, updated test mapping with correct mock.patch targets in `commands/run.py`.
- `src/pflow/cli/commands/CLAUDE.md`: Complete rewrite — flat command table (not groups routed by wrapper), updated MCP subcommands (list/find/describe/servers), updated cross-references, complete test mapping with all current mock.patch targets.

### Verification After Fixes
- 4704 tests pass, 0 failures
- `make check` clean
- All stale-reference greps return zero hits (excluding `architecture/historical/` which is intentionally untouched)

### Outstanding: Test Coverage Gap (not yet addressed)

154 tests were deleted with 22 replacements created. The new tests cover happy paths but drop significant edge case coverage. Key gaps:

| Area | Was | Now | Gap |
|---|---|---|---|
| Registry list/describe/search CLI | 51 tests | 6 (mcp_commands) | Grouped display, MCP name resolution depth, error cases |
| Registry describe | 28 tests | 1 | Format consistency, snippet generation, multi-node, special chars |
| Node ID normalization | 17 tests | 4 | Invalid IDs, backward compat, mixed case |
| Probe (was registry run) | 28 tests | 6 | Param type inference, structure mode, verbose, timing, error JSON |
| Discovery commands | 9 tests | 3 | Empty query, no-workflows edge case |
| Instructions (now guide) | 21 tests | 3 | Content validation (deferred to Task 77) |
| Registry scan | 8 tests | 0 | Command deleted, but scan logic still exists |
| Routing | 3 tests | 0 | New PflowCLI routing tests |

Decision on backfill approach pending user input.

### Real CLI Verification (2026-04-12)

Three parallel verification agents ran 35+ real subprocess tests (`uv run pflow ...`) against the live CLI. No mocks, no CliRunner — real process execution.

**All execution paths verified correct:**
- Workflow execution: file, saved name, `run` prefix, two-step template chaining
- Critical routing: `--output-format json` before workflow name passes through `ignore_unknown_options=True` correctly
- All flags: `-p`, `--verbose`, `--validate-only`, `--no-trace`, `--output-format json`, `--cache/--no-cache`
- Flags work before and after workflow name (`allow_interspersed_args=True`)
- Required input validation, empty param rejection, stdin piping error messages
- `probe`, `list`, `describe`, `history`, `save` + run-by-name lifecycle
- Reserved names rejected on save
- `settings output-mode`, `mcp list`, `mcp servers`
- Exit codes correct throughout (0 success, 1 errors, 2 Click usage errors)
- stdout/stderr separation clean

**Issues found and fixed:**

**P1 — Root help formatting broken (FIXED):**
Click's `help=` parameter re-wrapped the Quick Start table. Fix: overrode `format_help()` on `PflowCLI` to render entry content directly via `formatter.write()`, bypassing Click's paragraph wrapper. `help=render_entry_content()` removed from group decorator. The `pflow guide` path already used `click.echo()` directly. Result: `entry.md` (Task 77) is plain text — no Click-specific markers needed.

**P2 — Deleted commands gave no migration guidance (FIXED):**
`pflow workflow list` produced misleading "Invalid input: workflow list" (suggesting a malformed workflow invocation). Fix: added `_removed_commands` dict to `PflowCLI.resolve_command()` for top-level (`workflow`, `registry`, `instructions`) and `MCPGroup.resolve_command()` for MCP subgroup (`tools`, `info`). Each produces a clear error naming the replacement: `"Error: 'workflow' command was removed. Workflow commands are now top-level: pflow list, pflow find, ..."`. Not aliases, not fallbacks — just better errors. ~20 lines total.

**P3 — `mcp list --help` too terse (FIXED):**
Added description explaining grouped-by-server summary vs keyword-filtered detail modes, with examples.

**P4 — `probe --help` missing examples (FIXED):**
Added examples block.

**Per-command `\b` markers for examples blocks:**
Added `\b` before Examples sections in `list`, `find`, `describe`, `history`, `save`, `probe`, `mcp list` help text. Standard Click pattern to preserve indented formatting.

**Test updates:** 2 tests updated to match new error messages (`test_mcp_commands.py` for mcp migration messages, `test_dual_mode_stdin.py` for a test that used "workflow" as a proxy for multi-word args — changed to "something").

### Verification After All Fixes
- 4704 tests pass, 0 failures
- `make check` clean
- All stale-reference greps return zero hits
- Real CLI execution verified across 35+ subprocess tests

## Code Review Round 1 (2026-04-12)

4 specialized review agents deployed: review-silent-failures, review-feature-interactions, review-validation-consistency, review-impact-completeness.

### Findings: 5 confirmed, 4 disputed

**Confirmed and fixed:**

1. **Agent instruction files had stale `registry run` references** (all 4 agents flagged)
   - `cli-basic-usage.md`: 5 `registry run` → `probe`, 1 `guide --part 1/2/3` → `guide`
   - `cli-agent-instructions.md`: 3 `registry run` → `pflow probe`

2. **Root `CLAUDE.md` referenced removed `pflow instructions`**
   - Lines 172, 372: `pflow instructions usage` → `pflow guide`

3. **Error suggestions referenced `pflow mcp describe` for ALL node types**
   - `registry_error_helpers.py`: Added `_node_discovery_suggestions()` and `_describe_suggestion()` — suggests MCP commands for `mcp-*` nodes, core node list + `probe --help` for others
   - 4 new tests added in `test_registry_error_helpers.py`

4. **`settings registry output-mode` had no migration error**
   - Added `SettingsGroup(click.Group)` with `_removed_commands` for `registry`
   - 1 new test in `test_settings_cli.py`

5. **CLAUDE.md files across codebase had stale references** (~25 stale references across 13 files)
   - `discover_workflow` → `find_workflow`, `discover_components` → `find_components`
   - `registry_run.py` → `_probe_impl.py`, `commands/registry.py` → updated consumers
   - `main_wrapper.py` references removed from `mcp.py` docstring, `logging_config.py`
   - `docs/CLAUDE.md`, `examples/README.md`, `tests/shared/README.md` updated

**Disputed:**
- `mcp describe` not using `normalize_node_id` — flagged as pre-existing, but later confirmed as a real regression in Review Round 2
- `_get_version()` broad exception catch — low risk, reasonable for dev environments
- `ignore_unknown_options=True` swallows typos — known documented tradeoff
- `logging_config.py` line 21 stale comment — reviewer misread the file

### Verification After Round 1
- 4709 tests pass (5 new), 0 failures
- `make check` clean
- All stale-reference greps return zero hits

## Code Review Round 2 (2026-04-12)

External review document evaluated: `scratchpads/code-review-task151-pr-20260412-142728.md`

### Findings: 4 confirmed, 1 disputed

**Confirmed and fixed:**

1. **`mcp describe` missing `normalize_node_id`** — regression from old `registry describe`
   - Added `normalize_node_id()` call before `registrar.get_tool_info()` in `mcp.py`
   - Loads registry via `registrar.registry.load()` to get available node set
   - 2 new tests: hyphen/underscore normalization, short-form suffix matching

2. **`mcp find` not actually MCP-scoped** — `find_components()` unconditionally injected workflow context
   - Added `include_workflows: bool = True` parameter to `find_components()` in `registry/discovery.py`
   - `mcp find` now passes `include_workflows=False`
   - Existing callers unaffected (default `True`)

3. **`guide` stub pointed to repo-relative path** — `cat src/pflow/cli/resources/cli-agent-instructions.md`
   - Replaced with `pflow --help` reference
   - Updated `test_guide.py` assertion to match

4. **`mcp servers` empty-state hint had wrong `add` format** — suggested `<name> <command>`
   - Changed to `./server-config.json` matching actual `config_sources` argument

**Disputed:**
- Test coverage is thin — true but already a known tracked gap, not a new finding

**Already fixed (in Round 1):**
- `mcp.py` module docstring referencing `main_wrapper.py`

### Verification After Round 2
- 4711 tests pass (7 new total from both rounds), 0 failures
- `make check` clean

## Risks / Notes

- Note: the task spec requires the progress log to stay live. Update it after every completed phase and when implementation diverges from the written plan.
- Note: one stale reference remains in `architecture/implementation-details/metadata-extraction.md` (`pflow registry install`) — this command never existed and the doc is a design-time artifact, so it was intentionally left untouched.
