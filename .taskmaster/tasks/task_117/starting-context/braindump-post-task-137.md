# Braindump: Task 117 After Task 137

## Where I Am

Task 117 was originally "Comprehensive JSON Error Output for CLI" — a large task covering ALL error paths across ALL CLI modules. Task 137 (Unified CLI Output Pipeline, completed 2026-03-29) fully handled the main.py scope with a deeper structural fix. Task 117 has been **narrowed to Phase 3 only**: JSON error support for the CLI subcommand modules (`registry.py`, `registry_run.py`, `workflow.py`).

The task spec at `task-117.md` has been updated to reflect this. The original braindumps (`braindump-json-error-investigation.md` and `braindump-unified-errors.md`) are from 2026-01-23 and mostly stale — the infrastructure they discuss was superseded by Task 137's `output_error()`.

## User's Mental Model

The user thinks about this as part of the larger architectural debt cleanup. Their key phrases:

- **"We dont want to be adding a bandaid here"** — this is why Task 117's original approach (add a central function on top of divergent code) was rejected in favor of Task 137's structural fix
- **"this is supposed to be making the codebase simpler and more intuitive for ai agents"** — the user cares about agent-first UX. Error JSON consistency is about agents being able to parse errors reliably
- **"Would it be possible to take an even bigger step back?"** — the user consistently pushed for deeper solutions over quick fixes. They will do the same for this remaining scope

The user's unstated priority: they want the CLI to be **predictable for AI agents**. Every `--output-format json` invocation should produce parseable JSON, never plain text. The remaining subcommand gaps violate this.

However, this is now **medium priority** — the main workflow execution path (what agents use 95% of the time) is fixed. The subcommand gaps are for less-used paths (`registry describe`, `workflow save`, etc.).

## Key Insights

### The infrastructure already exists — this is a wiring task, not a design task

`output_error()` in `src/pflow/cli/error_output.py` handles JSON/text branching. The unified JSON shape is established. The exception-to-error dispatch handles 10+ types. The pattern from Task 137 (convert `click.echo + exit` to exception raises → catch block → `output_error()`) applies directly.

### The subcommand modules have a DIFFERENT architecture than main.py

`main.py` had one giant `workflow_command` with a pipeline of functions. The subcommands are standalone Click commands with their own handlers. The pattern is:

```python
@click.command()
def describe(name, ...):
    try:
        result = do_work(name)
        display(result)
    except SomeError:
        click.echo(f"Error: ...", err=True)
        sys.exit(1)
```

Adding JSON support here is simpler than main.py — each command is self-contained. But there are more of them.

### The flag inconsistency is a real design question

- `registry list` and `registry scan` use `--json` (boolean flag)
- `registry run` uses `--output-format json` (choice parameter)
- `workflow list` uses `--json` (boolean flag)
- `workflow describe`, `workflow history`, `workflow discover`, `workflow save` have **no** format flag

The user hasn't decided how to standardize this. Options:
1. Add `--json` everywhere (simpler, matches existing pattern for list/scan)
2. Add `--output-format` everywhere (more flexible, matches main workflow command)
3. Only add `--json` to commands where JSON makes sense (pragmatic — does `workflow history` need JSON?)

ASSUMPTION: The user will prefer option 1 (add `--json` everywhere) for simplicity. But this should be confirmed.

### registry_run.py's error formatters are plain-string functions

`registry_run_formatter.py` has `format_node_not_found_error()`, `format_ambiguous_node_error()`, `format_execution_error()` — they all return formatted strings with emoji and suggestions. For text mode, these work great. For JSON mode, we need to bypass them and produce structured error dicts instead.

The conversion pattern: instead of calling the formatter and echoing the string, raise a `UserFriendlyError` or `WorkflowNotFoundError` and let `output_error()` handle the dispatch.

### workflow.py has its OWN `_handle_workflow_not_found`

`src/pflow/cli/commands/workflow.py:72` has a DIFFERENT `_handle_workflow_not_found` than the one that was in main.py. This one handles `workflow describe <nonexistent>` and `workflow history <nonexistent>`. It's NOT affected by Task 137's changes. It needs its own JSON support.

### The `workflow` field in the unified JSON shape needs a decision

Task 137's unified shape always includes `"workflow": {"action": "unsaved|reused|created", "name": "..."}`. For `pflow registry describe nonexistent-node --json`, there's no workflow — it's a node operation. Options:
1. Include `"workflow": {"action": "unsaved"}` as a default (consistent shape, slightly misleading)
2. Omit the `workflow` field entirely for non-workflow commands (the spec says optional fields are "omitted when not applicable")
3. Use a different field like `"context": {"command": "registry describe", "node": "nonexistent-node"}`

UNCLEAR: Which approach the user prefers. Option 2 is probably cleanest.

## Assumptions & Uncertainties

ASSUMPTION: The user will want to use `output_error()` from Task 137 rather than creating new per-module formatting. Not explicitly confirmed for subcommands.

ASSUMPTION: The Task 137 exception pattern (raise → catch → output_error) works cleanly for Click subcommands. Each subcommand has its own function, so the catch block would need to be per-command or via a decorator. Not verified.

UNCLEAR: Whether `discovery_errors.py` (shared error handling for LLM discovery commands) needs JSON support too. It's used by both `registry discover` and `workflow discover`.

UNCLEAR: Whether the MCP server's tool execution paths (which also run registry nodes) should produce JSON errors. The task spec says "MCP not in scope" but MCP `run_registry_node` shares code with `registry_run.py`.

NEEDS VERIFICATION: Line numbers in the task spec are from 2026-01-23 (4+ months old, many PRs since). Task 137 modified `registry.py` (stdout fixes) and `workflow.py` (stdout fixes). All line references are stale.

NEEDS VERIFICATION: Whether `workflow save` errors go through `save_service.py` which raises `WorkflowValidationError` — Task 137 enriched this class with `format_for_cli()`. Some save error paths might already work through the exception pipeline without explicit changes.

## Unexplored Territory

UNEXPLORED: **Click error handling for subcommands.** Click has built-in exception handling that can intercept errors before they reach our code. If a subcommand raises an unhandled exception, Click may format and display it before our catch block runs. This needs testing with the actual commands.

UNEXPLORED: **A decorator pattern for JSON error support.** Instead of adding try/catch to every command, a decorator like `@json_error_handler` could wrap Click commands:
```python
@json_error_handler  # catches exceptions, produces unified JSON
@click.command()
def describe(name, output_json, ...):
    ...
```
This would be much cleaner than copy-pasting catch blocks into 15+ commands. Task 137 didn't do this because it only had one command (`workflow_command`).

CONSIDER: **Whether this task should be split.** `registry_run.py` is the cleanest module (8 error paths, self-contained). It could be done as a standalone PR to prove the pattern before tackling `registry.py` and `workflow.py`.

MIGHT MATTER: **The `workflow save` command has interactive prompts** (overwrite confirmation). These interact with `--json` in non-obvious ways — should the prompt be suppressed in JSON mode? Currently `--json` doesn't exist on `save`.

MIGHT MATTER: **`workflow describe` output is rich text** (formatted interface display). Adding `--json` means defining what the JSON shape of a workflow description looks like — this is an output format question, not just an error format question. The task scope is about ERROR JSON, but adding `--json` to a command implies success JSON too.

## What I'd Tell Myself

1. **Start with `registry_run.py`** — it's the cleanest module with the most obvious gap (8 error paths, 0 check format, `--output-format json` flag already exists but only governs success). Prove the pattern here.

2. **The decorator pattern is worth exploring.** Adding try/catch to 15+ commands is repetitive. A shared decorator would be much cleaner and prevent future commands from missing JSON support.

3. **Don't over-scope.** The user said this is medium priority now. The main path is fixed. If the subcommand work gets complex (especially around `--json` for success output, not just errors), it's OK to do just the error paths and leave success JSON for later.

4. **The `discovery_errors.py` module is shared between registry and workflow discover commands.** Fixing it once covers both.

5. **`workflow.py`'s `_handle_workflow_not_found` can probably just raise `WorkflowNotFoundError`** (the enriched one from Task 137) instead of doing its own click.echo. The outer catch would need to call `output_error()`.

## Open Threads

1. **Flag standardization decision** — `--json` vs `--output-format` needs user input before implementation.

2. **Success JSON for subcommands** — adding `--json` to `describe`/`history`/`save` implies defining success JSON shapes, not just error JSON. This could expand scope significantly. Consider: only add `--json` to commands that already have a natural JSON representation (list, scan), and only add JSON error support to the rest.

3. **The `output_error()` function takes `ctx` but never uses it** — this was noted during review. For subcommands, the `ctx` parameter could be useful if we add a decorator pattern that reads `output_format` from `ctx.obj` or Click params.

## Relevant Files & References

### Infrastructure (from Task 137, ready to use)
- `src/pflow/cli/error_output.py` — `output_error()`, `_exception_to_errors()`, `display_exception_text()`
- `src/pflow/core/exceptions.py` — enriched `WorkflowNotFoundError`, `WorkflowValidationError`
- `src/pflow/core/user_errors.py` — `UserFriendlyError` (what/why/how pattern)

### Files to modify (this task)
- `src/pflow/cli/commands/registry.py` — ~7 error paths, `describe`/`discover` need `--json` flag
- `src/pflow/cli/commands/registry_run.py` — 8 error paths, `--output-format json` flag exists but unused for errors
- `src/pflow/cli/commands/workflow.py` — ~14 error paths, need `--json` flags on most commands
- `src/pflow/cli/discovery_errors.py` — shared by registry/workflow discover

### Key references
- `.taskmaster/tasks/task_137/task-review.md` — architectural insights, patterns to follow
- `.taskmaster/tasks/task_137/implementation/progress-log.md` — detailed implementation record
- `tests/test_cli/test_unified_error_output.py` — the JSON shape contract (use `_assert_unified_shape` pattern)
- `src/pflow/execution/formatters/registry_run_formatter.py` — string formatters that need bypassing for JSON

### Research (from this conversation, in my context)
- The registry.py error audit found 13 error outputs, 6 check `output_json`, 7 don't
- The registry_run.py audit found 8 error outputs, 0 check `output_format`, all go to stderr
- The workflow.py audit found 14 error outputs, 0 check format, only `list` has `--json`
- The stdout→stderr bugs in registry.py and workflow.py are ALREADY FIXED (Task 137 Phase 7)

## For the Next Agent

**Start by**: Reading the updated `task-117.md` (narrowed scope) and `.taskmaster/tasks/task_137/task-review.md` (infrastructure + patterns). Then read `src/pflow/cli/error_output.py` — that's the function you'll be wiring into.

**Don't bother with**: The original braindumps (`braindump-json-error-investigation.md`, `braindump-unified-errors.md`) — they're from January and mostly superseded by Task 137. The main.py scope is done. Don't re-research the error handling in main.py.

**The user cares most about**: Agent-parseable JSON errors from `--output-format json` / `--json`. Text mode should be unchanged. The pattern from Task 137 (exception raises → catch → `output_error()`) should be followed.

**Easiest win**: `registry_run.py` — the `--output-format json` flag already exists, the 8 error paths are self-contained, and the conversion pattern is straightforward (raise exceptions instead of `click.echo + sys.exit`).

**Biggest decision needed**: Whether to add `--json` flags to commands like `describe`, `history`, `save` — and if so, what the SUCCESS JSON shape looks like (not just errors). Get user input before committing to a scope.

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
