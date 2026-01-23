# Braindump: Task 117 - Comprehensive JSON Error Output Investigation

## Where I Am

Task 117 has been **fully researched and documented** but NOT implemented. The task file (`.taskmaster/tasks/task_117/task-117.md`) is comprehensive and verified. This braindump captures the tacit knowledge from the investigation that led to that document.

I also **partially implemented** JSON error support during Task 115 work - specifically `_show_stdin_routing_error()` and `_output_validation_errors()` in main.py. These are working but will need to be migrated to the central infrastructure when Task 117 is implemented.

## User's Mental Model

The user thinks about this as a **contract violation**. When someone passes `--output-format json`, EVERYTHING should be JSON. Their exact framing:

> "1. yes important [rich text formatting]
> 2. this task should do this correctly (high) [refactoring appetite]
> 3. all cli modules"

They care deeply about:
- **Correctness over speed** - They wanted thorough investigation before any implementation
- **Rich text preservation** - Emojis, examples, multi-line formatting must stay for text mode
- **Comprehensive coverage** - All CLI modules, not just main.py
- **Verification** - They explicitly asked me to verify assumptions with subagents before finalizing

Their key insight that shaped the solution: We discussed returning error data vs formatting at call site. They chose the hybrid approach - central function with `text_display` callback to preserve rich formatting.

## Key Insights

### The Real Problem is Architectural

This isn't about fixing individual error calls. It's about **establishing a pattern** that makes it hard to add non-compliant errors in the future. The current codebase has 72+ error paths that each make their own formatting decision.

### ctx.obj Timing is Critical

**DISCOVERED LATE**: Some errors can occur BEFORE `ctx.obj` is populated. The central function MUST handle:
1. `ctx.obj` populated (normal case)
2. `ctx.obj` is None or empty (pre-initialization)
3. `ctx` itself is None (very early errors)

This is why the function signature has `output_format: str | None = None` - it's an override for pre-init scenarios.

### Two Bugs Found During Investigation

1. **registry.py line 426**: `_handle_nonexistent_path()` outputs to stdout, not stderr
2. **workflow.py lines 48-55**: Filter message goes to stdout instead of stderr

These are separate from the JSON issue but should be fixed as part of the work.

### The 11/39 Split

Of 39 error-related functions in main.py:
- **11 already check output_format** (the "routers")
- **28 don't check** (mostly display helpers called by routers)

The 11 that check are the ones that need **structure unification**.
The 28 that don't are the ones that need **format awareness added**.

## Assumptions & Uncertainties

**ASSUMPTION**: The `text_display` callback pattern will work for all error types. I haven't verified that every error message can be cleanly separated into "JSON data" + "text display function".

**ASSUMPTION**: We can add `--json` flags to workflow.py commands without breaking anything. Some commands might have reasons not to support JSON.

**UNCLEAR**: How to handle errors that occur during Click's argument parsing (before any pflow code runs). These might need special handling in Click's error callback.

**NEEDS VERIFICATION**: The line numbers in the task file were verified at time of writing but will drift as code changes. The function names should be stable though.

**UNCLEAR**: Should the unified structure match the existing runtime error structure or the validation error structure? I proposed a hybrid but the user didn't explicitly confirm preference.

## Unexplored Territory

**UNEXPLORED**: MCP server error handling (`src/pflow/mcp_server/`). Does it have the same issues? We only looked at CLI modules.

**UNEXPLORED**: What happens when errors occur in background tasks or async code? The central function uses `ctx.exit(1)` which might not work in all contexts.

**CONSIDER**: Error aggregation. Some workflows produce multiple errors - should they all go in the `errors` array or be separate JSON objects?

**MIGHT MATTER**: The `_serialize_json_result()` function (line 1136) has special handling for binary data and encoding errors. The new central function might need similar safety measures.

**CONSIDER**: Testing strategy. How do you test that ALL error paths produce valid JSON? Might need a meta-test that triggers each error type and validates the output.

**UNEXPLORED**: Performance. Adding a function call layer for every error - does it matter? Probably not, but wasn't discussed.

## What I'd Tell Myself

1. **Start with Phase 1 (infrastructure) and get it reviewed before Phase 2**. The central function design affects everything else.

2. **The text_display callback is the key innovation**. It lets you preserve existing rich text without rewriting it. Just wrap the existing code in a lambda.

3. **Don't try to unify the JSON structure AND add format-awareness simultaneously**. Do one migration at a time per function.

4. **The registry_run.py module is the cleanest to fix** - only 8 error outputs, all straightforward. Good place to prove the pattern.

5. **workflow.py is the messiest** - needs `--json` flags added to multiple commands before errors can be JSON-aware.

## Open Threads

### What I Was About To Do

Nothing - the user asked me to stop after documenting Task 117. The task is ready for implementation.

### Suspicions

The existing `_create_json_error_output()` function (line 1019) is more sophisticated than my proposed central function - it handles metrics, execution state, etc. There might be value in **extending that function** rather than creating a new one. But it's designed for exceptions, not validation errors.

### Patterns I Noticed

The codebase has a "router + helper" pattern:
- Router checks `output_format`
- Router calls JSON helper or text helper
- Helpers don't check format

This works but means you have to remember to add the check in every router. A central function inverts this - call one function and it handles the branching.

## Relevant Files & References

**Task file (source of truth)**:
- `.taskmaster/tasks/task_117/task-117.md` - Comprehensive, verified

**Code that was modified during Task 115** (partial implementation):
- `src/pflow/cli/main.py:3112` - `_show_stdin_routing_error()` - Has JSON support
- `src/pflow/cli/main.py:3152` - `_output_validation_errors()` - Has JSON support

**Existing infrastructure to understand**:
- `src/pflow/cli/main.py:1019` - `_create_json_error_output()` - Existing JSON error builder
- `src/pflow/cli/main.py:1136` - `_serialize_json_result()` - Safe JSON serialization
- `src/pflow/cli/main.py:48` - `safe_output()` - Pipe-safe stdout

**Other CLI modules**:
- `src/pflow/cli/registry.py` - Partial JSON support, bug at line 426
- `src/pflow/cli/registry_run.py` - NO JSON support
- `src/pflow/cli/commands/workflow.py` - NO JSON support, bug at lines 48-55

**Test patterns**:
- `tests/test_cli/test_dual_mode_stdin.py:TestJSONOutputFormat` - Tests I added for stdin JSON errors

## For the Next Agent

**Start by**: Reading `.taskmaster/tasks/task_117/task-117.md` fully. It's comprehensive and verified.

**Don't bother with**: Re-investigating the problem. The research is done. Trust the line numbers and function counts (verified 2026-01-23).

**The user cares most about**:
1. ALL errors respecting `--output-format json`
2. Preserving rich text formatting in text mode
3. Unified JSON structure across all error types
4. Covering all CLI modules

**Implementation order I'd suggest**:
1. Create `src/pflow/cli/error_output.py` with central function and dataclass
2. Write tests for the infrastructure
3. Pick ONE simple error path and migrate it end-to-end
4. Get user review before continuing
5. Then migrate by priority (P1 first)

**Watch out for**:
- Pre-initialization errors need the `output_format` override parameter
- Don't forget the two bugs (registry.py:426, workflow.py:48-55)
- Some workflow.py commands need `--json` flag added before errors can be JSON-aware

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
