# Braindump: Task 144 — Display Consolidation

## Where I Am

Task 144 spec is written. No implementation started. This task was born from the Task 143 review — I did a thorough audit of every display path in the codebase after Task 143 was implemented. The audit results are the foundation of the spec.

Task 143 is fully implemented and staged on branch `feat/unified-diagnostic-system`. It passes 4529 tests, mypy clean, ruff clean. Two additional fixes were applied during the review session (delete `_exception_to_errors()`, eliminate double-parse in library resolver). Those fixes are in the working tree but may or may not be staged yet — the user hasn't committed anything.

## User's Mental Model

This user thinks in terms of "top 10% codebases." They explicitly said during the Task 143 design: "we should prioritize simplicity of the final code, not how easy it is to get there." They see the dict round-trip as the kind of structural debt that accumulates — it works today but invites bugs.

The user initiated Task 144 by asking "what was the next step for unification that will be future work we discussed earlier?" — they remembered from the Task 143 design conversation that display consolidation was planned as a follow-up. They didn't need convincing; they asked if I had enough context to write the spec right now.

The user's decision-making style: they want options with trade-offs, a clear recommendation, and they'll make the call. For Task 143 review they said "lets go ahead and fix 1 and 6 then lets discuss 2" — they're comfortable making scoping decisions quickly. For the `ValidationResult.errors -> list[str]` question, the discussion landed on "leave it for Task 144" because changing it during Task 143 would be premature churn.

Key user quote on Task 143 scope: "the hard part is verifying and testing not the actual implementation." This applies to 144 too — the code changes are mechanical, but verifying no display regression happens is the real work.

## Key Insights

### The round-trip is caused by a shared formatter serving two consumers

`format_execution_success()` returns a dict because JSON consumers need a dict. Text consumers (CLI `_display_execution_summary`, MCP `format_success_as_text`) then extract `dict["warnings"]` (which are display dicts) and have to coerce them back to Diagnostics for `format_diagnostic()`. The root cause is one function serving two different output modalities.

The fix is NOT to stop returning dicts — JSON consumers genuinely need them. The fix is to give text consumers a separate path that passes Diagnostics directly. The spec flags two approaches: (1) add a `warning_diagnostics` parameter alongside the dict, or (2) restructure so text consumers don't go through the formatter dict at all. Option 1 is pragmatic; option 2 is cleaner but bigger.

### `coerce_*_diagnostic()` is solely a symptom, not a root cause

Every `coerce_warning_diagnostic()` call exists because a display function receives a dict when it could receive a Diagnostic. Once the data flow is fixed, all 7 call sites disappear. The implementing agent should NOT try to "improve" the coerce functions — they should eliminate the need for them.

### The validation path is the one with real user-visible improvement

The dict round-trip in the success/failure paths is invisible to users (same text output). But the validation error degradation (`list[str]`) actually loses information — error suggestions don't appear in `format_validation_failure()` output today. Fixing this is the one part of Task 144 that produces a visible improvement, not just code quality.

### `format_success_as_text()` is the tricky function

This function currently takes a success dict (with metrics, execution steps, workflow metadata, warnings, outputs) and renders it all to text. It's 100+ lines. For Task 144, only the warning section needs to change (lines 246-249). But the question is: how do Diagnostics get into this function?

Option A (pragmatic): `format_success_as_text(success_dict, warning_diagnostics=None)` — add an optional parameter. If provided, use it for warning rendering; if not, fall back to dict extraction (backward compat for any external caller).

Option B (clean): Split `format_success_as_text()` into `format_success_as_text(success_dict)` for non-warning sections + separate warning rendering from the caller. More work, less clear benefit.

I'd recommend Option A. The function signature change is minimal and the logic change is 4 lines.

### Similarly for `_display_execution_summary()`

Same pattern: currently takes a formatted dict, extracts warnings from it. Add `warning_diagnostics` parameter. Use it instead of extracting from dict.

## Assumptions & Uncertainties

ASSUMPTION: `to_display_dict()` will remain as the JSON serialization format. It's not a bridge to remove — it's the wire format. I'm ~95% sure this is right but the user hasn't explicitly confirmed the JSON schema should stay as-is.

ASSUMPTION: `format_validation_failure()` can be changed to take `list[Diagnostic]` without breaking external consumers. Currently called from 3 sites: `main.py:426`, `execution_service.py:295`, and tests. All are internal. No external API stability concern.

UNCLEAR: Whether the user wants to keep `format_validation_failure()` at all, or replace it with `format_diagnostic()` calls. The current function renders a bulleted list with a header ("Static validation failed:") and a truncation message for >10 errors. `format_diagnostic()` renders individual diagnostics. The header and truncation logic would need to stay somewhere.

UNCLEAR: Whether `_display_execution_summary()` should still receive the full formatted dict, or whether the caller should destructure it and pass individual pieces. The dict-passing pattern is convenient (one argument) but it obscures what the function actually needs.

NEEDS VERIFICATION: The `format_success_as_text()` function is used by both CLI and MCP. The CLI path calls it via `_handle_text_output() → format_execution_success() → (text path)`. The MCP path calls it directly in `execution_service.py`. Both callers have the Diagnostics available. Need to verify no other caller exists.

## Unexplored Territory

UNEXPLORED: Whether `format_execution_errors()` in `error_formatter.py` should also pass Diagnostics to text consumers instead of calling `to_display_dict()`. Currently it always serializes to dicts (for both JSON and the MCP `_build_error_text()` consumer). The MCP consumer then coerces back. This is a smaller version of the same problem.

CONSIDER: Whether `_build_error_text()` should just receive `list[Diagnostic]` directly from the caller instead of going through `_format_error_result() → dict → _build_error_text()`. The intermediate error dict in the MCP path serves no purpose other than aggregating formatted errors, execution state, and trace path. If `_build_error_text()` received Diagnostics + trace_path directly, the intermediate dict could be simplified.

CONSIDER: Whether the `"warnings"` key in JSON success output should keep using `to_display_dict()` (flat, context merged) or switch to `to_dict()` (nested context). The spec says keep it, but this is a schema decision that affects AI agent consumers. The `"diagnostics"` key already has the nested form, so `"warnings"` is arguably redundant. But removing it is a breaking JSON change.

MIGHT MATTER: The trace collector's `set_warnings()` currently receives Diagnostics and calls `to_display_dict()` for serialization. If Task 144 establishes "Diagnostics are the text path, dicts are the JSON path" cleanly, the trace collector should probably use `to_dict()` (it writes to a JSON file). Currently it uses `to_display_dict()` which flattens context to top level — less ideal for structured trace data.

MIGHT MATTER: Test coverage for the display paths. Task 143's `test_diagnostic.py` covers the `format_diagnostic()` function well. But there are no integration tests that verify the full path from `ExecutionResult.diagnostics → _display_execution_summary() → stdout`. The round-trip would be caught by such a test because the coercion would fail if the dict shape changed. After Task 144 removes the round-trip, these integration tests become less critical but the gap is worth noting.

UNEXPLORED: Whether `_display_text_error_details()` in `workflow_errors.py` should use `format_diagnostic()` for the full error rendering instead of calling it via `_display_single_error()`. Currently `_display_single_error()` adds a header ("Compilation failed" / "Workflow execution failed") before calling `format_diagnostic()`. That header logic could move into `format_diagnostic()` itself (controlled by the `error_number` parameter which already exists). This would make the failure text path purely `format_diagnostic()`-based with no wrapper.

## What I'd Tell Myself

1. **The spec has two open questions** — decide those before implementing. The user will likely prefer Option A (pragmatic parameter addition) for both `format_success_as_text` and `_display_execution_summary`. Ask, don't assume.

2. **The `format_validation_failure()` change is the highest-value part** — it's the only change that improves user-visible output (suggestions appear in validation errors). Lead with this when explaining the task to the user.

3. **This is a mechanical refactor, not a design task.** The hard design work was Task 143. Task 144 is cleanup. Don't over-design it.

4. **Watch the MCP path carefully.** `_format_error_result()` has the mixed-types issue (Diagnostics for warnings, dicts for errors in the same dict). The fix should make both consistent. The simplest approach: `_build_error_text()` takes `errors: list[Diagnostic], warnings: list[Diagnostic], trace_path: str` directly. Skip the intermediate dict entirely.

5. **The user never commits without being asked.** Don't commit Task 143's changes as part of this work. The user will commit when ready.

## Open Threads

- Task 143 is staged but not committed. The user will likely want to commit it before starting 144, but that's their call.
- The two additional fixes I made during review (delete `_exception_to_errors`, fix double-parse) need to be staged if they aren't already.
- The baselines in `scratchpads/task-143-unified-diagnostics/baselines-current/` should be diffed against `baselines/` to confirm no regressions. The implementing agent's progress log says this was done, but I didn't independently verify.

## Relevant Files & References

**The audit** — the comprehensive display path audit exists only in this conversation's context. The task spec summarizes the findings but the full trace-by-trace analysis (which path does what conversion at which line) is not written anywhere else. The spec's Implementation Notes section has the key call sites.

**Key files for Task 144:**
- `src/pflow/core/diagnostic.py:81-120` — `coerce_warning_diagnostic()` and `coerce_error_diagnostic()` to delete
- `src/pflow/execution/formatters/success_formatter.py:56-60, 246-249` — the round-trip pattern
- `src/pflow/execution/formatters/validation_formatter.py:40-104` — takes `list[str]`, needs `list[Diagnostic]`
- `src/pflow/execution/result.py:45-48` — `ValidationResult.errors` property
- `src/pflow/cli/workflow_output.py:595-600` — `_display_execution_summary` round-trip
- `src/pflow/mcp_server/services/execution_service.py:137-177` — mixed types in error dict

**Task 143 context:**
- Task spec: `.taskmaster/tasks/task_143/task-143.md`
- Implementation plan: `.taskmaster/tasks/task_143/implementation/implementation-plan.md`
- Progress log: `.taskmaster/tasks/task_143/implementation/progress-log.md`

## For the Next Agent

**Start by** reading the Task 144 spec (`.taskmaster/tasks/task_144/task-144.md`). It has the complete problem description, requirements, and implementation notes with exact file:line references.

**Then read** `src/pflow/core/diagnostic.py` to understand the Diagnostic type, the bridge functions you'll delete, and `format_diagnostic()` which is the canonical text renderer.

**Don't bother** re-auditing the display paths — the audit was thorough and the spec captures it. If you want to verify, grep for `coerce_warning_diagnostic` and `coerce_error_diagnostic` — those are the bridge functions and their call sites are the exact places that need changing.

**The user cares most about**: (1) validation errors gaining suggestions in text output, (2) clean code with no unnecessary conversion hops, (3) no display regressions. In that order.

**Ask the user** about the two open questions in the spec before implementing: how `format_success_as_text()` and `_display_execution_summary()` should receive Diagnostics (parameter addition vs restructure).

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
