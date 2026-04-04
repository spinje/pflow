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

## [2026-04-04] Addendum: Scope Expansion to Rendering Redesign

**The section above that says "This is a mechanical refactor, not a design task" is now wrong.** The task scope expanded significantly during the post-PR review conversation. What follows captures the knowledge from that conversation that isn't in the task spec.

### How the scope expanded — the user's exact reasoning

After the PR review, we analyzed `diagnostic.py`'s 683 lines. I broke it down: ~70 lines type, ~30 coercion, ~240 exception conversion, ~340 rendering. The user asked: "what does the new file do that was not done before?" I explained that the rendering code produces the same output as the old scattered `format_for_cli()` methods — it's consolidation, not new functionality (aside from parser warning threading and suggestions).

The user then asked the pivotal question: **"how many of the special cases in the if/elif chains really requires special cases, what could be consolidated without losing agent clarity and actionability, or even improve it? And what could potentially be added to all the cases that now ignores this extra information entirely?"**

This shifted the task from "clean up dict round-trips" to "redesign the rendering to be both simpler AND more informative."

I did a surface analysis (6 paths → 2, ~185 lines saved) and the user immediately asked: **"Is it possible you don't have explored this fully?"** I admitted I hadn't — I'd counted branches and estimated savings without thinking through what the ideal output actually looks like.

The user then said the task should **"make sure to explore how this could be done as cleanly as possible, handling all types of errors and warnings with as much information as possible that is available now. Your findings should be a starting point not a final conclusion."**

### Why my "6 paths → 2" analysis is incomplete

I identified that the 6 rendering paths could collapse to 2 (structured block + user-friendly block). But I only looked at the STRUCTURE, not the CONTENT. Specifically:

**What I did**: counted branches, identified duplicates, estimated line savings.

**What I didn't do**:
- Look at what a UserFriendlyError WITH shell stderr would look like if context blocks were universal
- Consider whether the structured block format (`Category: / Message: / Suggestion:`) is even good compared to the user-friendly format (`Error: title / explanation / suggestions`)
- Enumerate every context key that `exception_to_diagnostics()` populates and check which ones `format_diagnostic()` ignores
- Think about what "agent-actionable" means concretely for each error type
- Consider whether warnings should show context in text (currently they don't — validator warnings have `context={"template": "..."}` but it's invisible)
- Check if information is LOST in exception→Diagnostic conversion (OutputResolutionError collapses a `failures` list)

The implementing agent must do this exploration in Phase 1 before assuming my "2 patterns" conclusion is correct.

### The production LOC story — why it matters for Phase 3

The user pushed hard on understanding why `diagnostic.py` isn't net-negative. The answer:

- **~350 lines** are moved/consolidated rendering code that previously lived in `format_for_cli()` methods and display helpers
- **~150 lines** are genuinely new (threading, suggestions, provenance, coercion bridges)
- **~140 lines** are the cost of **explicit routing** — the old code had typed exceptions that knew how to render themselves (`exc.title`, `exc.suggestions`). The new code has a generic `Diagnostic` with `context: dict` and must inspect keys to figure out rendering.

That +140 is the architectural cost of "one render path." The implementing agent should understand this trade-off: centralization eliminates drift between CLI/MCP but costs lines because implicit type-based dispatch became explicit if/elif chains reading dict keys. Phase 3 should find a way to reduce this cost without reintroducing scattered rendering.

CONSIDER: Is there a middle ground? A small number of "render strategies" selected by a key field (like `source` or a new `render_style` field) rather than deep context inspection? This wasn't explored.

### The baseline philosophy shift

Task 143 baselines: "prove nothing was lost" — regression guard.
Task 144 baselines: "prove everything got better" — quality gate.

The user said the post-implementation comparison should **"verify that every single item has become BETTER and not worse."** Unchanged output isn't a pass — it's a missed opportunity that needs justification. This is a fundamentally different verification mindset. The implementing agent needs to annotate the BEFORE captures with gaps ("this error has API response data in context but doesn't show it") so the AFTER can be scored against specific improvement targets.

The user also added: make sure "no important information that was present in the previous version was not removed." So it's bidirectional — improve everything, lose nothing.

### What the PR review cycle taught us

We went through a full PR review with both Claude Code (`/code-review` skill, 8 specialized agents) and Gemini (automated PR review). Findings relevant to Task 144:

1. **The shared provenance helper** was the highest-value finding — it turned a documented coupling risk into an eliminated one. Pattern: when two code paths must produce identical output for dedup, extract the shared format into a function. The implementing agent should look for similar patterns in the rendering code.

2. **The coerce functions we just DRY-refactored** (`_coerce_diagnostic` shared helper) will be deleted entirely in Task 144. Don't spend time improving them — eliminate them.

3. **The `to_display_dict()` redundant deepcopy** was fixed by reading from the already-deep-copied `result["context"]` instead of deep-copying `self.context` again. A mutation-safety test caught the initial naive fix. The implementing agent should be aware that `to_display_dict()` has a mutation-safety contract tested at `test_diagnostic.py:49`.

### User's priority ordering (updated)

The braindump above says "(1) validation errors gaining suggestions, (2) clean code, (3) no display regressions." This is now:

1. **Every output becomes more informative and agent-actionable** — not just validation
2. **The rendering is simpler** — fewer paths, less code, but NOT at the cost of information
3. **No information loss** — bidirectional quality gate
4. Clean code (dict round-trips eliminated) is a means, not an end

### Suspicions not yet proven

SUSPICION: The user-friendly format (title / explanation / numbered suggestions / --verbose technical details) might be the right structure for ALL errors, not just UserFriendlyError. It's the most readable pattern we have. Compilation errors, runtime errors, validation errors — they all HAVE a title (the category), explanation (the message), and suggestions. The structured block format (`Category: X / Message: Y`) is just a worse version of the same information.

SUSPICION: `Diagnostic.suggestion` (joined string) and `context["suggestions"]` (list) is a design smell. The user-friendly renderer reads the list from context for numbered display but falls back to the string. This split might be unnecessary — if `suggestion` were always a list, the renderer could always render numbered items (or a single line for length-1 lists).

SUSPICION: OutputResolutionError's conversion to one Diagnostic with `context["failures"]` as an opaque list might be wrong. Per-failure Diagnostics with individual messages might be more agent-actionable. The progress log notes this was a deliberate choice to "avoid duplicate user-facing blocks" but it wasn't explored from the agent-consumer perspective.

## For the Next Agent

**Start by** reading the Task 144 spec (`.taskmaster/tasks/task_144/task-144.md`). It has the complete problem description, requirements, and implementation notes with exact file:line references.

**Then read** `src/pflow/core/diagnostic.py` — the full file. Understand the type, the exception conversion (13 types), and the rendering (6 paths). Your Phase 1 research starts here.

**Critically**: the spec's Phase 1 research requirements are not optional. The user explicitly rejected a "consolidate what exists" approach. You must explore what the output SHOULD be, produce concrete before/after examples, and get approval before implementing Phase 3. Phase 2 (dict round-trip cleanup) is mechanical and well-specified — you can start that while the rendering research is in progress.

**Don't trust my rendering analysis.** I said "6 paths → 2, ~185 lines saved." The user pushed back and I admitted it was surface-level. Your research may find a different optimal structure. Start from the question "what should an agent see when this error occurs?" not "how do I consolidate these branches?"

**The user cares most about**: output quality for AI agents. Every diagnostic should tell an agent what went wrong, where, and what to do about it. Lines of code saved is a side effect, not a goal.

**The baseline is a scorecard.** Annotate before-captures with gaps. Score after-captures against specific improvement targets. Unchanged output needs justification.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
