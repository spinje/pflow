# Braindump: Task 115 - Stdin Routing Research Complete

## Where I Am

Research and specification phase is COMPLETE. The task spec (`task-115-spec.md`) is at version 1.3.0 and has been verified against the codebase. No implementation has started. The next agent should be ready to implement.

## User's Mental Model

The user thinks about this as **Unix-first piping** - making pflow behave like grep, jq, awk. Their exact framing:

- "can workflows know at creation what inputs might and might not come from stdin?" - They wanted to understand if auto-detection was even sensible
- "what is 'correct' here and most agent friendly" - Agent-friendliness is a primary concern
- "is the reasoning for auto detection hedging too much?" - They pushed back on complexity and wanted simplicity
- "i want to take inspiration from 'real unix tools'" - Unix tools don't guess, they're explicit

**Key user priorities (unstated but clear):**
1. Simplicity over cleverness - they rejected type-based auto-routing repeatedly
2. Agent-friendly = predictable, explicit, one rule to learn
3. No backward compatibility concerns - "we don't have any users"
4. Error messages should teach agents how to fix workflows, not expose internals

**How their understanding evolved:**
- Started with task spec that had type-based auto-routing
- I initially defended auto-detection, user pushed back asking "is this hedging?"
- We converged on: explicit `stdin: true` only, no magic
- User then asked about `${stdin}` in shared store - realized it's less flexible than input routing
- Final design: `stdin: true` on inputs is the ONLY mechanism

## Key Insights

### The Critical Injection Point Discovery

The original task spec and research-findings.md were WRONG about where to inject stdin routing. They said line 3261 (after `_validate_and_prepare_workflow_params()`). But validation happens INSIDE that function at line 3121 via `prepare_inputs()`.

**Correct injection point:** INSIDE `_validate_and_prepare_workflow_params()`, between:
- `parse_workflow_params()` at line 3093
- `prepare_inputs()` at line 3121

This was verified via codebase search. If you inject AFTER the function, required inputs that expect stdin will fail validation before stdin is considered.

### Why No `${stdin}` in Shared Store

The user had a key insight: `stdin: true` on an input gives you BOTH:
- Piped input works
- CLI argument works (`pflow workflow.json data="override"`)

While `${stdin}` in shared store only gives you:
- Piped input works
- NO way to provide via CLI

So we're removing `${stdin}` entirely. It's less flexible.

### Error Architecture

pflow has two error patterns:
1. **Return tuples** `(msg, path, suggestion)` - used by `prepare_inputs()`
2. **Raise `UserFriendlyError`** - used for rich formatting

For stdin routing, use **direct `click.echo()` + `ctx.exit(1)`** because:
- Happens before `prepare_inputs()` runs
- Need multi-line output with JSON examples
- Matches existing pattern for invalid parameter names (lines 3096-3100)

### Two Execution Paths

Both need stdin routing, but implementing inside `_validate_and_prepare_workflow_params()` covers both:
1. `_handle_named_workflow()` → direct file/saved workflows
2. `_execute_successful_workflow()` → planner-generated workflows

## Assumptions & Uncertainties

**ASSUMPTION:** Binary stdin (piped binary data) should silently not route. User said "can we defer this?" and I agreed. The downstream "missing required input" error is clear enough.

**ASSUMPTION:** The function signature change to `_validate_and_prepare_workflow_params()` (adding `stdin_data` param) won't cause issues. Only two callers exist, both in same file.

**UNCLEAR:** Should the "no stdin: true input" error fire even if stdin is empty string? Current spec says yes - empty string is valid content. But this might be annoying if user accidentally has stdin attached.

**NEEDS VERIFICATION:** The exact type of `stdin_data` when it reaches `_validate_and_prepare_workflow_params()`. Research says `str | StdinData | None` but this function currently doesn't receive it - needs to be threaded through.

## Unexplored Territory

**UNEXPLORED:** What if a workflow has `stdin: true` on an optional input with a default? Current spec says stdin overrides default. Is this correct? Probably yes, but not explicitly discussed.

**UNEXPLORED:** MCP server execution path (`ExecutionService.execute_workflow()`) doesn't support stdin. Should it? Probably not for this task - MCP is programmatic, not Unix piping.

**CONSIDER:** The `-p` flag for stdout. For full Unix piping (`a | b | c`), you need BOTH stdin routing (this task) AND stdout to actually go to stdout (needs `-p` flag currently). The task mentions this but doesn't solve it. User might expect full piping to "just work" after this task - it won't without `-p`.

**MIGHT MATTER:** `planning/nodes.py` lines 840-847 check for `shared["stdin"]`. This is in ParameterDiscoveryNode. Removing it is safe (prompt handles `stdin_info=None`), but the planner might behave slightly differently for stdin-heavy requests. Not tested.

**CONSIDER:** Test coverage for the removed `populate_shared_store()` function. There are 5 tests in `test_shell_integration.py` that directly test it. These need to be removed, not updated.

## What I'd Tell Myself

1. **Read the spec file first** - It's at v1.3.0 and accurate. Don't re-research what's already verified.

2. **The injection point is INSIDE the function** - Not after it. This was the biggest correction.

3. **Don't overcomplicate errors** - Use `click.echo()` directly, don't try to fit into the tuple pattern.

4. **The user values simplicity** - Every time I suggested a "smart" feature, they pushed back. One rule, explicit, predictable.

5. **`research-findings.md` is outdated** - It still has type-detection code examples. The spec is the source of truth.

## Open Threads

### What I Was About To Do Next

Implementation order I had in mind:
1. Add `stdin` field to IR schema (`ir_schema.py`)
2. Add validation in `prepare_inputs()` for multiple `stdin: true`
3. Modify `_validate_and_prepare_workflow_params()` to accept and route stdin
4. Remove `populate_shared_store()` and related code
5. Update/remove tests
6. Update docs

### Hunches

- The `_inject_stdin_object()` function at `main.py:259-272` exists but is NEVER CALLED. It properly handles StdinData. Might be useful reference code, or might just be dead code to delete.

- The type flow `str | StdinData | None` loses type safety at execution layer (becomes `Optional[Any]`). Not a problem for this task, but worth knowing.

### Unresolved Question

Should error messages include the workflow name/path for context? Current spec doesn't. Might help agents debugging: "Workflow 'transform.json' has no input marked with stdin: true" vs just "Workflow has no input...". Not discussed with user.

## Relevant Files & References

**Spec (source of truth):**
- `.taskmaster/tasks/task_115/starting-context/task-115-spec.md` - v1.3.0, fully verified

**Task description:**
- `.taskmaster/tasks/task_115/task-115.md` - Updated with new design, examples

**Research (historical, some outdated):**
- `.taskmaster/tasks/task_115/starting-context/research-findings.md` - Has correct file locations but outdated code examples

**Key implementation files:**
- `src/pflow/cli/main.py` - Lines 3076-3140 for `_validate_and_prepare_workflow_params()`
- `src/pflow/core/ir_schema.py` - Lines 252-270 for input schema
- `src/pflow/runtime/workflow_validator.py` - Lines 72-195 for `prepare_inputs()`
- `src/pflow/execution/executor_service.py` - Line 176 for `populate_shared_store()` call to remove
- `src/pflow/core/shell_integration.py` - Lines 200-210 for function to remove
- `src/pflow/planning/nodes.py` - Lines 840-847 for stdin checking to remove

**Tests to update/remove:**
- `tests/test_shell_integration.py` - Lines 126-185, remove tests for `populate_shared_store()`
- `tests/test_integration/test_user_nodes.py` - Lines 79-81, 207
- `tests/test_planning/` - Multiple files using `shared["stdin"]`

**Docs to update:**
- `docs/reference/cli/index.mdx` - Line 125 mentions `${stdin}`

## For the Next Agent

**Start by:** Reading `task-115-spec.md` in full. It's comprehensive and verified.

**Don't bother with:** Re-researching the codebase. The spec has exact line numbers. Trust them.

**The user cares most about:**
1. Simplicity - one rule, explicit `stdin: true`
2. Agent-friendly errors - show JSON examples, no internals
3. Clean removal of `${stdin}` pattern - no half measures

**Implementation order suggestion:**
1. Schema change (ir_schema.py) - smallest, enables everything else
2. Multi-stdin validation (workflow_validator.py) - simple addition
3. Routing logic (main.py) - the core feature
4. Remove old pattern (executor_service, shell_integration, planning/nodes)
5. Fix tests
6. Update docs

**Watch out for:**
- The function signature change to `_validate_and_prepare_workflow_params()` - need to update both callers
- Threading `stdin_data` through to where routing happens - it's currently passed to `execute_json_workflow()`, not the validation function

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
