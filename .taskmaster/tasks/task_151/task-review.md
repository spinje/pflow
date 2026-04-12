# Task 151 Review: CLI Surface Restructure — Flatten, Rename, Delete

## Metadata

- **Implementation Date**: 2026-04-12
- **Branch**: `refactor/cli-surface-restructure`
- **Commits**: 6 (plan → implementation → audit fixes → code review fixes → test backfill)
- **Scope**: 132 files changed, 5596 insertions, 7558 deletions (net -1962 lines)
- **Final state**: 4719 tests passing, `make check` clean

## Executive Summary

Flattened pflow's nested CLI from `pflow workflow <verb>` / `pflow registry <verb>` into a flat, agent-friendly top-level surface. Replaced the hand-rolled `main_wrapper.py` routing with a Click-native `PflowCLI(click.Group)` subclass using the default-command pattern. Deleted 4 command files, created 10 new ones, updated 132+ references across production code, docs, and architecture files. MCP server boundary strictly respected — only 2 import renames in `discovery_service.py`.

## Implementation Overview

### What Was Built

**CLI routing rewrite**: `main_wrapper.py` (manual `sys.argv` routing) replaced by `PflowCLI(click.Group)` with `ignore_unknown_options=True` for the default-command pattern. `main.py` went from 1058 lines to 136 lines. All workflow execution logic extracted to `commands/run.py` (~780 lines).

**Flattened commands**:
- `pflow workflow list/find/describe/history/save` → `pflow list/find/describe/history/save`
- `pflow registry run` → `pflow probe`
- `pflow instructions` → `pflow guide` (stub, content is Task 77)
- `pflow mcp list` (servers) → `pflow mcp servers`
- New `pflow mcp list` (tools, grouped-by-server), `pflow mcp find`, `pflow mcp describe`

**Supporting changes**:
- `normalize_node_id()` extracted to `registry/node_id.py` as a reusable pure function
- `discover_workflow()` → `find_workflow()`, `discover_components()` → `find_components()`
- Reserved workflow names consolidated to single `frozenset` in `save_service.py`
- `settings registry output-mode` → `settings output-mode`
- `pflow.guide` package created with `render_entry_content()` shared between `--help` and `guide`

### Deviations from Plan

1. **`main.py` is 136 lines, not ~60**: The plan underestimated the size needed for `format_help()` override, `_removed_commands` dict, signal setup, and 14 command registrations. Still clean and focused.

2. **`format_help()` override needed**: Click's `help=render_entry_content()` re-wraps text, destroying the aligned Quick Start table. Solution: override `format_help()` on `PflowCLI` to render entry content directly via `formatter.write()`.

3. **`_removed_commands` pattern added**: Not in the original plan. Without it, `pflow workflow list` silently routed to the default `run` command and produced confusing "Invalid input: workflow list" errors. The pattern produces clear migration messages for `workflow`, `registry`, `instructions` (top-level) and `tools`, `info` (MCP subgroup) and `registry` (settings subgroup). ~30 lines total across 3 classes.

4. **`include_workflows` parameter on `find_components()`**: Added so `mcp find` returns only MCP nodes, not workflows. Existing callers unaffected (default `True`).

5. **`MCPGroup` and `SettingsGroup` subclasses**: Two small `click.Group` subclasses with their own `_removed_commands` for MCP and settings namespaces. Not in original plan.

6. **`__main__.py` added**: `src/pflow/cli/__main__.py` for `python -m pflow.cli` support. Subprocess tests need a package-level module after `main_wrapper.py` removal.

7. **Test files not split as planned**: Plan called for per-command test splits (`test_list.py`, `test_describe.py`, `test_history.py`). Implementation kept `test_workflow_commands.py` for list/describe/history and created new focused files only for genuinely new commands. Pragmatic — the existing test organization was fine.

8. **Node-type-aware error suggestions**: `registry_error_helpers.py` now distinguishes MCP vs core nodes. Suggests `pflow mcp describe` for `mcp-*` nodes, `pflow probe --help` for others. 4 new tests.

## Files Modified/Created

### Core Changes (new files)

| File | Purpose |
|------|---------|
| `src/pflow/guide/__init__.py` | `render_entry_content()` — shared between `--help` and `pflow guide` |
| `src/pflow/guide/entry.md` | Placeholder entry content (Task 77 fills this in) |
| `src/pflow/cli/__main__.py` | `python -m pflow.cli` support |
| `src/pflow/cli/commands/run.py` | Workflow execution logic (extracted from old `main.py`) |
| `src/pflow/cli/commands/list.py` | `pflow list [keyword...]` |
| `src/pflow/cli/commands/find.py` | `pflow find "description"` |
| `src/pflow/cli/commands/describe.py` | `pflow describe <workflow>` |
| `src/pflow/cli/commands/history.py` | `pflow history <workflow>` |
| `src/pflow/cli/commands/save.py` | `pflow save <file> --name <name>` |
| `src/pflow/cli/commands/guide.py` | `pflow guide [topics...]` |
| `src/pflow/cli/commands/probe.py` | `pflow probe <node> params...` (thin wrapper) |
| `src/pflow/registry/node_id.py` | `normalize_node_id()` pure function |

### Core Changes (rewritten/significantly modified)

| File | What changed |
|------|-------------|
| `src/pflow/cli/main.py` | Complete rewrite: 1058 lines → 136 lines |
| `src/pflow/cli/__init__.py` | Import source changed from `main_wrapper` to `main` |
| `src/pflow/cli/commands/mcp.py` | Major restructure: `MCPGroup`, new `list`/`find`/`describe`/`servers` |
| `src/pflow/cli/commands/_probe_impl.py` | Renamed from `registry_run.py`, import updates |
| `src/pflow/cli/find_errors.py` | Renamed from `discovery_errors.py` |
| `src/pflow/cli/commands/settings.py` | Removed `registry` subgroup, added `SettingsGroup` |
| `src/pflow/core/workflow/save_service.py` | Reserved names expanded to `frozenset`, consolidated |
| `src/pflow/core/workflow/manager.py` | `_validate_workflow_name()` now delegates to `save_service` |
| `src/pflow/core/workflow/discovery.py` | `discover_workflow()` → `find_workflow()` |
| `src/pflow/registry/discovery.py` | `discover_components()` → `find_components()`, added `include_workflows` param |

### Deleted Files

| File | Why |
|------|-----|
| `src/pflow/cli/main_wrapper.py` | Replaced by Click-native routing |
| `src/pflow/cli/commands/workflow.py` | Commands flattened to top-level |
| `src/pflow/cli/commands/registry.py` | Group eliminated |
| `src/pflow/cli/commands/registry_run.py` | Renamed to `_probe_impl.py` |
| `src/pflow/cli/commands/instructions.py` | Replaced by `guide.py` |
| `docs/reference/cli/workflow.mdx` | Commands flattened |
| `docs/reference/cli/registry.mdx` | Group eliminated |

### Stale Reference Updates (Phase 5.5 + audit + code reviews)

40+ stale command references updated across production code, agent instructions, CLAUDE.md files, docs, and architecture docs. Key files:

- `core/exceptions.py`, `core/workflow/skill_service.py` — error messages and enrichment templates
- `cli/commands/skills.py`, `cli/commands/read_fields.py`, `cli/rerun_display.py`
- `execution/formatters/registry_error_helpers.py` — function renames (`enrich_for_registry_run` → `enrich_for_probe`)
- `runtime/compilation/mcp_resolution.py`, `nodes/mcp/node.py`
- `cli/resources/cli-agent-instructions.md`, `cli/resources/cli-basic-usage.md`
- 13 CLAUDE.md files across the codebase
- 20+ docs files

### Test Files

| File | Status | What it tests |
|------|--------|---------------|
| `test_cli/test_probe.py` | Renamed from `test_registry_run.py` | probe command + ambiguous node IDs + shell special chars rejection |
| `test_cli/test_node_id_normalization.py` | Updated imports | `normalize_node_id()` — invalid inputs, MCP multi-hyphen, case sensitivity |
| `test_cli/test_guide.py` | New | guide stub returns content, topic placeholder |
| `test_cli/test_mcp_commands.py` | New | mcp list/find/describe/servers + migration errors |
| `test_cli/test_find.py` | New | LLM-powered find + no-match guidance |
| `test_cli/test_workflow_commands.py` | Updated patches | list/describe/history with new import paths |
| `test_cli/test_workflow_save_cli.py` | Updated imports | save command with new module path |
| `test_cli/test_workflow_save_security.py` | Updated imports | `_validate_discovery_query` from `find.py` |
| `test_cli/test_settings_cli.py` | Updated + new test | `settings output-mode` + `settings registry` migration error |
| `test_core/test_workflow_discovery.py` | Updated | `discover_workflow` → `find_workflow` |
| `test_registry/test_component_discovery.py` | Updated | `discover_components` → `find_components` |

**Critical tests** (catch real bugs, not coverage padding):
- `test_probe_rejects_shell_special_chars_in_param_names` — security boundary wiring
- `test_probe_ambiguous_node_shows_candidates` — agent UX for ambiguous node IDs
- `test_mcp_describe_unknown_tool_shows_suggestions` — error path with fuzzy matching
- `test_normalize_node_id_case_sensitive` — documents intentional case sensitivity, prevents accidental `.lower()`
- `test_normalize_node_id_filesystem_mcp_tools` — multi-hyphen server names (real MCP pattern)

## Integration Points & Dependencies

### Incoming Dependencies (what depends on this)

| Consumer | Interface | Notes |
|----------|-----------|-------|
| Task 77 (guide content) | `pflow.guide.render_entry_content()`, `entry.md` | Task 77 fills `entry.md`; both `--help` and `guide` auto-pick it up |
| Task 77 (guide content) | `guide_cmd` argument signature `(topics: tuple[str, ...])` | Task 77 replaces the topic placeholder |
| Task 77 (reserved names) | `save_service.RESERVED_WORKFLOW_NAMES` | Task 77 will add topic names to this set |
| Task 152 (MCP parity) | `find_workflow()`, `find_components()` | Task 152 spec currently uses old names — **needs updating** |
| MCP server | `find_workflow()`, `find_components()` in `discovery_service.py` | Import paths already updated |
| All CLI tests | `pflow.cli.commands.run.WorkflowManager` patch target | Will break if `run.py` moves |

### Outgoing Dependencies (what this depends on)

| This Task | Depends On | Interface |
|-----------|-----------|-----------|
| `PflowCLI.format_help()` | `pflow.guide.render_entry_content()` | Called at help-render time |
| `commands/run.py` | All existing CLI modules, `pflow.execution.*` | Unchanged from pre-restructure |
| `commands/mcp.py` list | `MCPRegistrar.registry.load()`, `mcp_metadata.server` | Groups by server field |
| `commands/mcp.py` describe | `registry/node_id.py:normalize_node_id()` | Node ID resolution |
| `commands/probe.py` | `_probe_impl.py:execute_single_node()` | Thin delegation |
| Reserved names validation | `save_service.RESERVED_WORKFLOW_NAMES` frozenset | Single source of truth |

## Architectural Decisions & Tradeoffs

### Key Decisions

1. **Click-native routing instead of maintaining `main_wrapper.py`**
   - *Reasoning*: Click auto-generates `Commands:` section, supports standard `CliRunner` testing, eliminates manual `sys.argv` manipulation. The `click-default-group` pattern is well-established (565K weekly PyPI downloads) and only needs ~20 lines vendored inline.
   - *Alternative*: Keep `main_wrapper.py` with updated routes. Rejected because it's hand-rolled, fragile, and doesn't benefit from Click's help/completion infrastructure.

2. **`ignore_unknown_options=True` on both group AND `run` command**
   - *Reasoning*: Group needs it so `pflow --output-format json workflow.pflow.md` works (group parser doesn't reject `--output-format`). `run` command needs it so `pflow my-workflow --help` passes through to `_show_workflow_help()`.
   - *Tradeoff*: Typos like `--output-formt` silently pass through. `_validate_workflow_flags` in `commands/run.py` mitigates for common misplaced flags. Accepted tradeoff — user was informed.

3. **`format_help()` override instead of `help=render_entry_content()`**
   - *Reasoning*: Click's `help=` parameter re-wraps text, destroying the aligned Quick Start table in `entry.md`. The override renders content directly via `formatter.write()`, bypassing Click's paragraph wrapper.
   - *Discovery*: Found during real CLI verification, not during planning. The plan originally specified `help=render_entry_content()`.

4. **`_removed_commands` dict pattern for migration errors**
   - *Reasoning*: Without it, `pflow workflow list` silently routes to `run` and produces "Invalid input: workflow list" (confusing). With it, agents get "Error: 'workflow' command was removed. Workflow commands are now top-level: pflow list, pflow find, ..." — actionable.
   - *Scope*: ~30 lines across `PflowCLI`, `MCPGroup`, `SettingsGroup`. Not an alias or fallback — just better error messages.

5. **`pflow.guide` as a top-level package, not a CLI implementation detail**
   - *Reasoning*: Both CLI (`pflow guide`) and MCP (Task 152) need to import `render_entry_content()`. A top-level package makes the dependency direction clean.

6. **Shared function renames (`discover_*` → `find_*`)**
   - *Reasoning*: User explicitly requested — "we have the context for optimal naming when implementing." The CLI verb is `find`, so the service function should match.
   - *Risk*: Touches test files outside CLI scope (`test_core/`, `test_registry/`), creates Task 152 spec conflict. Was the highest-risk decision for marginal value.

### Technical Debt Incurred

1. **`_handle_workflow_not_found` duplicated in `describe.py` and `history.py`** — 7 lines each. Too small for a shared module per user's principle ("three similar lines of code is better than a premature abstraction").

2. **`mcp.py` uses inline formatting, not shared formatters** — Unlike other commands that use `pflow.execution.formatters/`, the MCP list/find commands format inline. Acceptable for now; could be extracted if the MCP server needs the same formats (Task 152).

3. **Task 152 spec references old function names** — `discover_workflow`/`discover_components` in Task 152's spec need updating to `find_workflow`/`find_components`.

4. **`docs/reference/cli/mcp.mdx` needs a polish pass** — The `mcp list` / `mcp servers` semantic split changed more than names. The docs were updated via targeted replacements, not a full editorial rewrite.

## Testing Implementation

### Test Strategy Applied

- **154 old tests deleted, 22 replacements created** — focus on tests that catch real bugs at behavioral boundaries, not coverage padding
- **35+ real subprocess tests** run against the live CLI during verification (no mocks, no CliRunner)
- **Test backfill** after implementation: 8 high-value tests across 4 files, each targeting a specific bug surface
- **Two rounds of code review** by specialized agents (silent-failures, feature-interactions, validation-consistency, impact-completeness)

### Critical Test Cases

| Test | What it validates | Why it matters |
|------|-------------------|---------------|
| `test_probe_rejects_shell_special_chars_in_param_names` | probe calls `is_valid_parameter_name` before execution | Security boundary wiring |
| `test_probe_ambiguous_node_shows_candidates` | Ambiguous node ID shows candidate list, not traceback | Agent UX |
| `test_normalize_node_id_case_sensitive` | Case sensitivity is intentional | Prevents accidental `.lower()` "fix" |
| `test_normalize_node_id_filesystem_mcp_tools` | Multi-hyphen server names resolve correctly | Real MCP pattern |
| `test_mcp_describe_unknown_tool_shows_suggestions` | Unknown tool shows fuzzy suggestions | Error path |
| `test_mcp_list_keyword_no_match_shows_guidance` | No-match shows guidance, not empty output | Silent failure prevention |
| `test_find_no_match_shows_guidance` | Empty result shows guidance | Most common `find` outcome |

## Unexpected Discoveries

### Gotchas Encountered

1. **`click.group(no_args_is_help=True)` doesn't work with the custom group subclass**. Required `invoke_without_command=True` plus explicit `ctx.get_help()` path when no subcommand is invoked.

2. **Click's `help=` parameter re-wraps text**. Destroyed the aligned Quick Start table. Required `format_help()` override — found during real CLI testing, not planning.

3. **`ExecutionCache.store()` has a 4-argument signature** (`execution_id, node_type, params, outputs`). The extracted `_probe_impl.py` accidentally collapsed this during refactoring. Caught by mypy.

4. **Several CLI tests assumed writable `HOME`**. Needed `HOME=tmp_path` for trace/report and `~` path tests under sandbox restrictions.

5. **`mcp describe` was missing `normalize_node_id`** — regression from old `registry describe`. Found in code review round 2, not by tests.

6. **`mcp find` was not actually MCP-scoped** — `find_components()` unconditionally included workflow context. Required adding `include_workflows: bool = True` parameter.

7. **`guide` stub referenced a repo-relative path** (`cat src/pflow/cli/resources/cli-agent-instructions.md`). Replaced with `pflow --help` reference.

8. **Stale command references extended far beyond obvious CLI modules** — skill templates, compiler diagnostics, error suggestions, MCP node guidance, rerun hints all embed CLI commands and needed updating in lockstep.

## Patterns Established

### Reusable Patterns

**1. `_removed_commands` for clean migration errors**
```python
class PflowCLI(click.Group):
    _removed_commands: ClassVar[dict[str, str]] = {
        "old-cmd": "Replaced by: pflow new-cmd",
    }
    def resolve_command(self, ctx, args):
        if args and args[0] in self._removed_commands:
            click.echo(f"Error: '{args[0]}' ...", err=True)
            ctx.exit(1)
        ...
```
Use whenever deleting a command that agents may have memorized.

**2. `format_help()` override for custom help content**
Don't use `help=` for content that needs precise formatting. Override `format_help()` and write directly to the formatter.

**3. One-file-per-command in `commands/`**
Each command file is self-contained, importable independently. Shared logic goes in `_`-prefixed implementation modules (e.g., `_probe_impl.py`) or `cli/find_errors.py`.

**4. `normalize_node_id()` as a reusable pure function**
3-tier matching (exact → hyphen/underscore → suffix) in `registry/node_id.py`. Use whenever resolving user-provided node IDs.

### Anti-Patterns to Avoid

1. **Don't add `--verbose` to individual commands** — Read from `ctx.obj.get("verbose", False)`. A duplicate flag shadows the group-level one silently.

2. **Don't use `help=` for multi-line formatted content** — Click re-wraps it. Use `format_help()` override or `\b` markers for examples blocks.

3. **Don't split `run.py` further** — It's ~780 lines but it's the orchestration layer. The functions are interdependent. Extracting pieces creates circular imports.

4. **Don't patch `pflow.cli.main.WorkflowManager`** — Workflow logic moved to `commands/run.py`. Correct patch target: `pflow.cli.commands.run.WorkflowManager`.

## Breaking Changes

### CLI Surface (all intentional, clean cutover)

| Old | New | Type |
|-----|-----|------|
| `pflow workflow list/find/describe/history/save` | `pflow list/find/describe/history/save` | Flattened |
| `pflow registry run` | `pflow probe` | Renamed |
| `pflow registry list/describe/discover/scan` | Removed (absorbed by `mcp list/describe/find` and `guide`) | Deleted |
| `pflow instructions` | `pflow guide` | Renamed |
| `pflow mcp list` (servers) | `pflow mcp servers` | Semantic change |
| `pflow mcp tools` | `pflow mcp list` | Renamed |
| `pflow mcp info` | `pflow mcp describe` | Renamed |
| `pflow settings registry output-mode` | `pflow settings output-mode` | Flattened |

### Internal API Changes

| Old | New |
|-----|-----|
| `discover_workflow()` | `find_workflow()` |
| `discover_components()` | `find_components(task, ..., include_workflows=True)` |
| `enrich_for_registry_run()` | `enrich_for_probe()` |
| `_registry_run_suggestions()` | `_probe_suggestions()` |
| `from pflow.cli.main_wrapper import cli_main` | `from pflow.cli.main import cli_main` |

## Future Considerations

### Extension Points

1. **Adding a new top-level command**: Create `commands/new_cmd.py`, import in `main.py`, call `cli.add_command(new_cmd)`. Add the name to `RESERVED_WORKFLOW_NAMES` in `save_service.py`.

2. **Task 77 hooks**: `pflow.guide.render_entry_content()` reads `entry.md` — just populate that file. `guide_cmd` accepts `topics: tuple[str, ...]` — replace the placeholder logic with `compose_guide(topics)`.

3. **Task 152 hooks**: MCP server imports `find_workflow()` and `find_components()` from their current locations. Tool renames are independent of CLI routing.

4. **`RESERVED_WORKFLOW_NAMES`**: Task 77 will add topic names. The `frozenset` in `save_service.py` is the single source of truth.

### Fragility Warnings

1. **`PflowCLI.resolve_command()` is the routing backbone** — ALL CLI routing depends on this 15-line method. Test any routing changes with both named commands AND workflow catch-all.

2. **`ignore_unknown_options=True` + `add_help_option=False` + `allow_interspersed_args=True`** — This triple on the `run` command is load-bearing. Removing any one breaks a different use case.

3. **`format_help()` override** — Click version upgrades could change the formatter API. Verify `pflow --help` output after Click upgrades.

4. **`_removed_commands` must be manually maintained** — When adding/removing commands, update these dicts. They're in `PflowCLI`, `MCPGroup`, and `SettingsGroup`.

5. **`mock.patch` targets** — Tests patch at the import site (`pflow.cli.commands.run.WorkflowManager`), not the definition site. Moving imports breaks tests silently (mock attaches to nonexistent attribute, test passes but tests nothing).

## AI Agent Guidance

### Quick Start for Related Tasks

**Task 77 (guide content)**:
1. Read `src/pflow/guide/__init__.py` — understand `render_entry_content()`
2. Populate `src/pflow/guide/entry.md` with real content
3. Replace the topic placeholder in `src/pflow/cli/commands/guide.py`
4. Add topic names to `RESERVED_WORKFLOW_NAMES` in `src/pflow/core/workflow/save_service.py`

**Task 152 (MCP parity)**:
1. Update spec: `discover_workflow` → `find_workflow`, `discover_components` → `find_components`
2. MCP server code in `mcp_server/` is untouched except 2 import renames in `discovery_service.py`
3. CLI routing (`PflowCLI`) is independent of MCP tool names

**Adding a new command**:
1. Create `src/pflow/cli/commands/new_cmd.py`
2. Import and register in `src/pflow/cli/main.py` via `cli.add_command()`
3. Add command name to `RESERVED_WORKFLOW_NAMES`
4. Read verbose from `ctx.obj.get("verbose", False)` — do NOT add a `--verbose` flag

### Common Pitfalls

1. **Don't use `from pflow.cli.main import main` and invoke with workflow args directly** — `main` is now the Click group. CliRunner invocations route through `resolve_command`. Tests that did `result = runner.invoke(main, ["my-workflow.pflow.md"])` still work because the group routes to `run`.

2. **Don't grep for stale references in `architecture/historical/`** — Intentionally untouched. Only check `src/pflow/`, `docs/` (excluding `changelog.mdx`), and non-historical `architecture/` files.

3. **The `entry.md` file is currently a placeholder with minimal content** — This is intentional. Task 77 owns the real content. Don't expand it prematurely.

4. **`mcp list` no-args and `mcp list <keyword>` have different output formats** — No-args shows grouped-by-server summary; with keywords shows filtered detail view. These are two code paths in the same command.

### Test-First Recommendations

When modifying CLI routing or commands, run in this order:
1. `pytest tests/test_cli/test_cli.py tests/test_cli/test_main.py -q` — help text, version, routing
2. `pytest tests/test_cli/test_workflow_resolution.py -q` — catch-all routing
3. `pytest tests/test_cli/ -q` — full CLI suite
4. `make test && make check` — everything

---

*Generated from implementation context of Task 151*
