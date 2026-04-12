# Braindump: Task 151 Post-Implementation Audit Context

**Date**: 2026-04-12
**Audience**: The agent responsible for AUDITING the implementation after another agent executes the plan.
**Purpose**: Tell you what to check, what's most likely to be wrong, and what the user actually cares about.

You are not implementing. You are verifying. Read the implementation plan at `.taskmaster/tasks/task_151/implementation/implementation-plan.md` and the task spec at `.taskmaster/tasks/task_151/task-151.md` first. This document tells you where to focus your skepticism.

---

## What Happened Before You

A multi-session planning conversation produced:
1. A task spec (the "what" and "why")
2. An implementation plan (the "how" — 7 phases, ~50 files)
3. A code review by 4 specialized review agents that found 6 critical issues and ~10 warnings

The critical issues were fixed in the plan before approval. **Your job is to verify the implementation got them right** — and to catch anything the reviews missed.

## User's Real Priority

The user said one thing that overrides everything else:

> "We should prioritize simplicity of the final code, not how easy it is to get there."

This means: don't evaluate whether the implementation was efficient. Evaluate whether the **end state** is clean, consistent, and simple. A messy migration path that produces clean final code is a success. A clean migration that leaves architectural debt is a failure.

The user also said "we have NO USERS yet" repeatedly. This means:
- Zero tolerance for backwards-compatibility hacks, aliases, deprecation warnings
- Old commands should produce clear "command not found" errors, not silent fallbacks
- The old `workflow`, `registry`, `instructions` groups should be COMPLETELY gone

## The 6 Critical Issues Found by Review Agents

These were fixed in the plan but are the highest-risk areas for implementation errors:

### 1. `ignore_unknown_options=True` on the PflowCLI group

**Why it matters**: Without this, `pflow --output-format json my-workflow` crashes because the group parser rejects `--output-format` (a `run` option) before routing happens. This is the most subtle architectural issue.

**What to verify**:
```bash
pflow --output-format json <some-workflow>.pflow.md   # Must work
pflow -p my-workflow                                   # Must work (-p is a run option)
pflow --no-trace my-workflow                          # Must work
pflow my-workflow --help                              # Must show workflow interface, NOT run command help
pflow --verbose list                                  # Must work (--verbose is a group option)
```

**The tradeoff**: `ignore_unknown_options=True` means typos like `--output-formt` silently pass through instead of erroring. Verify that `_validate_workflow_flags` catches common misplaced flags. This is an ACCEPTED tradeoff — the user was informed.

**Also verify**: `ignore_unknown_options=True` on the `run` command's `context_settings`, AND `add_help_option=False` on `run`. All three settings are required for correct behavior.

### 2. `configure_logging(verbose)` in the group callback

**Why it matters**: Without it, 7 third-party libraries (httpx, httpcore, mcp SDK, composio, streamable_http, urllib3) flood stderr with their own logs. The original plan only had `setLevel(DEBUG)` — review agents caught this.

**What to verify**: Run `pflow --verbose <some-workflow>` and check that output contains pflow's logs but NOT raw httpx/httpcore request traces. The function is in `src/pflow/cli/logging_config.py`.

### 3. Test file coverage

The original plan missed ~10 test files. The reviews found:
- 5 files importing `cli_main` from the deleted `main_wrapper.py`
- `test_cli.py` and `test_main.py` breaking on help text and empty-arg assertions
- `test_workflow_save_cli.py` importing from deleted `workflow.py`
- `test_workflow_save_security.py` importing from deleted `workflow.py`
- `test_core/test_workflow_discovery.py` not updated for `discover_workflow` → `find_workflow`
- `test_registry/test_component_discovery.py` not updated for `discover_components` → `find_components`

**What to verify**: `make test` passes with ZERO failures. Don't just run it — check the output for skipped tests or xfails that might be masking problems. Also verify no test was deleted rather than updated (the implementing agent might have taken the easy path).

### 4. Stale command references in 12+ production code files

This is the area **most likely to be incomplete**. The plan lists specific files but the implementing agent may have relied on the list instead of doing their own grep.

**What to verify — run these greps yourself**:
```bash
grep -rn "pflow registry" src/pflow/ --include="*.py"
grep -rn "pflow workflow list\|pflow workflow describe\|pflow workflow discover\|pflow workflow history\|pflow workflow save" src/pflow/ --include="*.py"
grep -rn "pflow instructions" src/pflow/ --include="*.py"
grep -rn "pflow mcp tools\|pflow mcp info" src/pflow/ --include="*.py"
grep -rn "registry run\|registry_run" src/pflow/ --include="*.py" | grep -v "_probe_impl\|test_\|CLAUDE\|changelog\|__pycache__"
```

Each should return ZERO hits in production code (excluding comments marked as historical, changelogs, and MCP server tool names which ARE expected to still reference old names).

**The most impactful miss**: `src/pflow/core/workflow/skill_service.py` — stale commands get baked into PERMANENT saved workflow files via enrichment templates. If this file still says `"pflow workflow history"` or `"pflow instructions create"`, every future saved workflow will have wrong commands embedded in it.

### 5. `--version` format

Click's `@click.version_option` outputs `"pflow, version X.Y.Z"` (with comma) by default. The plan specifies `message="pflow version %(version)s"` to preserve the current format. Verify: `pflow --version` outputs `"pflow version X.Y.Z"` (no comma).

### 6. `probe` `--verbose` conflict

The `probe` command must NOT have its own `--verbose` flag. It reads verbose from `ctx.obj.get("verbose", False)`. If probe has a duplicate `--verbose`, the group-level `--verbose` is silently ignored for probe.

**Verify**: `pflow --verbose probe shell command="echo hi"` produces verbose output. If it doesn't, probe has its own `--verbose` shadowing the group's.

## What the Plan Got Right (Don't Re-litigate)

- Naming decisions (`find`, `probe`, `guide`, `describe`) — settled by polls, user accepted
- `src/pflow/guide/` as a top-level package — user explicitly approved
- Click-native routing with `PflowCLI` — user approved after research
- Shared function renames (`discover_*` → `find_*`) — user specifically requested
- `settings registry output-mode` → `settings output-mode` — user's explicit decision
- Clean cutover, no aliases — user's hard requirement
- MCP server is off limits (except import updates for renamed functions)

## Areas Most Likely to Have Residual Issues

### A. The `_handle_workflow_not_found` helper format

The plan says to "duplicate it in both `describe.py` and `history.py`" and preserve the EXACT current format. Check that:
1. The format matches the original in `workflow.py` (emoji prefix, bulleted list — NOT the simplified version the plan showed in an example)
2. Tests that assert on this format still pass

### B. `_validate_discovery_query` shared location

The plan evolved on this. Initially it said "inline in find.py", but a review finding (Gotcha #16) says "put it in `find_errors.py`" so both `find.py` and `mcp.py`'s `find_tools` can use it. Check which approach was taken and whether it's consistent.

### C. The `mcp list` grouped-by-server implementation

This is the most genuinely NEW code (not a port). The plan says to use `mcp_metadata.server` from registry entries (NOT naive `split("-", 2)` name parsing). Verify:
1. Grouping uses `entry["interface"]["mcp_metadata"]["server"]`
2. NOT `tool_name.split("-", 2)[1]` (which breaks for multi-hyphen server names)
3. Cross-references with `MCPServerManager.list_servers()` to show unsynced servers

### D. `discover_components()` `registry_metadata` parameter

Phase 4 adds an optional `registry_metadata` parameter to `discover_components()` (before the Phase 5 rename to `find_components`). This parameter lets `mcp find` scope to MCP-only nodes. Verify:
1. The parameter exists with default `None`
2. When `None`, function loads all nodes (backward compatible)
3. `mcp find` passes pre-filtered MCP-only metadata
4. The MCP server's `discovery_service.py` still works without passing the parameter

### E. Reserved names consolidation

The plan consolidates from TWO duplicated sets (in `save_service.py` AND `manager.py`) to a single source of truth. Verify:
1. `save_service.py` has the expanded `frozenset`
2. `manager.py._validate_workflow_name()` DELEGATES to `save_service.validate_workflow_name()` instead of maintaining its own set
3. The expanded set includes ALL new CLI commands: `list`, `find`, `describe`, `history`, `save`, `guide`, `probe`, `run`, `read-fields`, `trace`, `visualize` (plus the originals: `null`, `undefined`, `none`, `test`, `settings`, `registry`, `workflow`, `mcp`, `skill`, `instructions`)

### F. Phase ordering — guide package before main.py

Gotcha #1 in the plan: `src/pflow/guide/` MUST be created before `main.py` is rewritten, because `help=render_entry_content()` is evaluated at import time. If the implementing agent got this wrong, `import pflow.cli.main` would crash. This would be caught by any test run, but verify the guide package exists and `render_entry_content()` works standalone.

## Silent Failure Patterns to Check

These are things that break WITHOUT causing test failures:

1. **`pflow workflow list` after restructure**: Does this silently try to execute a workflow named "workflow" (via the catch-all)? Or does `is_likely_workflow_name("workflow", ("list",))` return False and produce a clear error? Verify the error message is helpful, not confusing.

2. **`pflow registry list` same question**: "registry" is a reserved name but reserved names only block SAVING, not EXECUTING. The routing should try to treat "registry" as a workflow name, fail the heuristic, and show a clear error.

3. **Empty keywords in `pflow list`**: `keywords=()` (empty tuple) should show ALL workflows, not filter everything out. Verify `if keywords:` evaluates to `False` for empty tuple.

4. **`pflow --verbose` with no subcommand**: Should show group help. With the old code, this showed workflow help. Verify the behavior is reasonable (group help with Commands list).

5. **Mock.patch targets on wrong paths**: If a test patches `pflow.cli.main.WorkflowManager` but the function moved to `pflow.cli.commands.run`, the patch silently does nothing (attaches a Mock to a nonexistent attribute on the module). The test passes but isn't testing what it thinks. Grep for any remaining `pflow.cli.main.WorkflowManager` or `pflow.cli.main.execute_json_workflow` patches — there should be ZERO.

## Docs Verification

132+ references across 20+ files in `docs/`. The plan lists them all. Run:

```bash
grep -r "pflow registry" docs/ --include="*.mdx" | grep -v changelog.mdx
grep -r "pflow workflow discover\|pflow workflow list\|pflow workflow describe\|pflow workflow history\|pflow workflow save" docs/ --include="*.mdx" | grep -v changelog.mdx
grep -r "pflow instructions" docs/ --include="*.mdx" | grep -v changelog.mdx
grep -r "pflow mcp tools\|pflow mcp info" docs/ --include="*.mdx" | grep -v changelog.mdx
```

All should return ZERO hits (excluding `changelog.mdx` which keeps historical references).

Also verify `docs/docs.json` navigation:
- `reference/cli/workflow` and `reference/cli/registry` REMOVED from nav
- New pages added: `list`, `find`, `describe`, `history`, `save`, `guide`, `probe`
- 7 broken cross-reference links (pointing to deleted `workflow.mdx` and `registry.mdx`) fixed

## Architecture Docs

The plan's Phase 6 was extended to include `architecture/` docs, but this was a late addition. Check:
```bash
grep -rn "pflow registry\|pflow workflow list\|pflow workflow describe\|pflow instructions" architecture/ --include="*.md"
```

## MCP Server Boundary Check

The plan is explicit: MCP server code is off limits EXCEPT for import path updates when shared functions are renamed. Verify:

1. `src/pflow/mcp_server/services/discovery_service.py` — ONLY the import names changed (`discover_workflow` → `find_workflow`, `discover_components` → `find_components`). No logic changes.
2. `src/pflow/mcp_server/tools/*.py` — ZERO changes
3. `src/pflow/mcp_server/resources/instructions/*.md` — ZERO changes
4. `src/pflow/mcp_server/server.py` — ZERO changes
5. MCP tests in `tests/test_mcp_server/` — ZERO changes (they test old tool names which still work)

If anything beyond import renames was changed in `mcp_server/`, flag it as out of scope.

## The Final Code Quality Check

The user's overriding principle: "prioritize simplicity of the final code." After verifying correctness, evaluate:

1. **Is `main.py` actually small?** (~60 lines target). If it grew beyond ~100 lines, something leaked from `run.py`.
2. **Is each command file self-contained?** `list.py`, `find.py`, etc. should each be readable independently.
3. **Are there any re-export hacks?** The user explicitly said no backwards-compat hacks. The only acceptable re-export is `main = cli` in `main.py`.
4. **Is the `PflowCLI` class clean?** Should be ~20 lines: `ignore_unknown_options`, `resolve_command`, `format_usage`.
5. **Did `commands/` get cleaner?** Old: 9 files including 3 groups. New: 14 files, all flat commands. Is each file focused?

## What I'd Do Differently If Starting Over

1. **Run the reviews BEFORE writing the plan, not after.** We wrote a comprehensive plan, then 4 review agents found 6 critical issues. Better: research → rough plan → review → fix → finalize.

2. **The shared function renames (`discover_*` → `find_*`) add scope for marginal value.** They touch test files outside the CLI scope (`test_core/`, `test_registry/`) and create a Task 152 spec conflict. If I were starting over, I'd ask the user to reconsider — the CLI verb is `find` but the underlying operation is still "discovery" at the service layer. The user specifically wanted the renames ("we have the context for optimal naming when implementing"), so they stay. But verify extra carefully that ALL import sites were caught.

3. **The `_handle_workflow_not_found` duplication is mildly annoying.** Two copies of 7 lines in `describe.py` and `history.py`. A shared `cli/command_helpers.py` would be cleaner. But the user's principle says "Three similar lines of code is better than a premature abstraction." Accept it.

## Relevant Files

**Read these first (in this order):**
1. `.taskmaster/tasks/task_151/task-151.md` — the spec (what and why)
2. `.taskmaster/tasks/task_151/implementation/implementation-plan.md` — the plan (how)
3. This file — what to focus on during audit

**Key source files to inspect:**
- `src/pflow/cli/main.py` — should be ~60 lines, PflowCLI group
- `src/pflow/cli/commands/run.py` — the big file, all workflow execution logic
- `src/pflow/cli/commands/mcp.py` — most complex changes (mcp list/find/describe)
- `src/pflow/guide/__init__.py` — render_entry_content()
- `src/pflow/core/workflow/save_service.py` — consolidated reserved names
- `src/pflow/core/workflow/manager.py` — should delegate to save_service now

**Key test files to inspect:**
- `tests/test_cli/test_cli.py` — help text and version assertions
- `tests/test_cli/test_main.py` — same
- `tests/test_cli/test_probe.py` — renamed from test_registry_run.py, 39 mock.patch targets
- `tests/test_cli/test_mcp_commands.py` — new file, tests for mcp list/find/describe
- `tests/test_cli/test_reserved_names.py` — new file, tests expanded reserved set

## For the Next Agent

**Start by:**
1. Reading the task spec and implementation plan
2. Running `make test && make check` — this is the baseline
3. Running the grep commands in this document for stale references
4. Testing the 6 critical edge cases listed above
5. Spot-checking the "most likely to have residual issues" areas (A-F)

**Don't bother with:**
- Re-evaluating naming decisions (settled by polls)
- Checking MCP server logic (off limits, only imports changed)
- Reviewing the old code (it's deleted)
- Suggesting improvements beyond scope (the user explicitly said "don't add features beyond what was asked")

**The user cares most about:**
- Clean, simple final code (evaluate the end state, not the migration)
- Agent-first UX (help text, error messages, command discoverability)
- NO stale command references anywhere in production code
- NO silent failures (deleted commands should error clearly, not route to garbage)
- MCP server completely unaffected (except import renames)

**Red flags to escalate to the user:**
- Any file in `mcp_server/` changed beyond import renames
- `main.py` bigger than ~100 lines
- Re-export hacks or backwards-compat shims
- Tests deleted instead of updated
- Stale command references surviving in production code

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
