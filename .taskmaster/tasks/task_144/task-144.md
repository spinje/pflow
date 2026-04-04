# Task 144: Display Consolidation — Diagnostic Rendering Redesign

## Description

Two related problems in the diagnostic display layer left over from Task 143:

1. **Dict round-trip anti-pattern**: Text rendering paths convert Diagnostic → dict → Diagnostic → text, wasting cycles and requiring bridge functions (`coerce_*_diagnostic`).
2. **Rendering complexity without clarity**: `format_diagnostic()` has 6 special-case rendering paths (~260 lines) that produce similar output, while context data populated by `exception_to_diagnostics()` is selectively rendered — some error types show rich context (shell stderr, API response), others silently drop it.

This task eliminates the dict round-trips AND redesigns the rendering to be simpler and more informative. The goal is not "consolidate what exists" but "design what the output should be, given the structured data we now have."

## Status

not started

## Priority

medium

## Problem

### Dict round-trips (from Task 143 transition)

```
Diagnostic → to_display_dict() → dict → coerce_*_diagnostic() → Diagnostic → format_diagnostic() → text
```

This exists because `format_execution_success()` serves both JSON and text consumers but only produces a dict. Text consumers then reconstruct Diagnostics from that dict.

Affected paths:
1. **CLI text success** — `_display_execution_summary()` at `workflow_output.py:600` coerces warnings back from display dicts
2. **MCP text success** — `format_success_as_text()` at `success_formatter.py:249` does the same round-trip
3. **MCP text failure** — `_build_error_text()` at `execution_service.py:163` coerces errors back from display dicts

**Validation error degradation (2 paths):**

`ValidationResult.errors` returns `list[str]` (messages only), losing `suggestion`, `node_id`, `source`, and `context`. Two consumers use this degraded form:
1. `format_validation_failure(vresult.errors)` — renders bullet-point strings, losing fix suggestions
2. `_display_validation_result()` JSON mode — hand-crafts `{"message": e, "category": "validation"}` dicts that have a different shape from `to_display_dict()` output

**Mixed types in MCP error path:**

`_format_error_result()` puts raw `Diagnostic` objects in `error_dict["warnings"]` but display dicts in `error_dict["errors"]` — a footgun for any future consumer that serializes this dict to JSON.

### Rendering complexity

`_format_error_diagnostic()` routes through 6 paths based on `source`, `context.get("category")`, `context.get("title")`, and presence of `node_id`:

| Path | Trigger | Lines | What's truly unique |
|------|---------|-------|-------------------|
| Validation | `source == "validation"` | ~20 | `At: path` line |
| Not-found | `category == "not_found"` | ~20 | "Did you mean" list |
| User-friendly | `context.get("title")` | ~35 | title/explanation/suggestions/verbose |
| Max-visits | `category == "max_visits"` | ~5 | Nothing — just the default with a shortcut |
| Simple | no node_id + certain categories | ~15 | `✗` icon instead of header block |
| Runtime (default) | everything else | ~25 | The general case |

Context blocks (API response, shell stderr, MCP error, template fields) are only rendered for the **runtime default path**. All other paths silently ignore context, even if it's populated.

### Information gaps

Not yet fully explored — this is what the research phase must answer:

- **What context keys does `exception_to_diagnostics()` populate that `format_diagnostic()` never renders?** Initial scan suggests UserFriendlyError's `technical_details` is only shown in verbose mode, and OutputResolutionError's per-failure `failures` list is stored but never individually rendered in text.
- **Should warnings show context in text?** Validator warnings carry `context={"template": "..."}` which is invisible in text output but available in JSON. Is this the right split?
- **Is information lost in the exception→Diagnostic conversion?** OutputResolutionError collapses a `failures` list into one Diagnostic. Is per-failure detail available to agents?
- **Is the user-friendly format (title/explanation/suggestions) better for ALL errors?** The structured block format (`Category: / Message: / Suggestion:`) is mechanical. The user-friendly format is more readable. Could all errors use the user-friendly structure?
- **Is `Diagnostic.suggestion` (joined string) vs `context["suggestions"]` (list) the right design?** The user-friendly renderer reads `context["suggestions"]` for numbered items but falls back to `Diagnostic.suggestion` as a single string.

## Solution

### Phase 1: Research — explore the current state

Before writing any code, the implementing agent must:

1. **Map every context key** populated by `exception_to_diagnostics()` (13 exception types) and check which keys `format_diagnostic()` actually reads. Produce a table: exception type → context keys populated → which are rendered in text → which are JSON-only → which are silently dropped.

2. **Map the rendering paths** end-to-end: for each error type, trace from exception → Diagnostic → format_diagnostic → text output. Capture the actual text output for each type. Identify where information is lost or inconsistently presented.

3. **Compare text vs JSON** for each error type: what does an agent see in JSON that it can't see in text? Is that intentional? Should text show more? Less?

4. **Study what top-tier CLIs do** for diagnostic rendering. rustc, eslint, mypy each have a single diagnostic format with optional context. What's the common structure? (Don't research from scratch — use what's already in the Task 143 braindump about the compiler diagnostic pattern.)

5. **Design the ideal output**: Given all the structured data available, what should a human see in the terminal? What should an agent see in stderr? What should an agent see in JSON? These may be different. Produce concrete before/after examples for each error type.

6. **Propose a rendering architecture**: How many distinct rendering patterns are actually needed? What's the minimal set of helpers? How do context blocks integrate?

### Phase 2: Data flow cleanup (the mechanical part)

This is well-understood and can be specified precisely:

1. **Split text/JSON paths** — text consumers receive `Diagnostic` objects directly, not dicts
2. **Update `ValidationResult.errors`** to return `list[Diagnostic]`
3. **Delete `coerce_warning_diagnostic()` and `coerce_error_diagnostic()`** — all callers updated
4. **Normalize MCP error path** — consistent types throughout

### Phase 3: Rendering redesign (informed by Phase 1)

Implement the rendering architecture designed in Phase 1. This will likely:

- Reduce the number of rendering paths (currently 6, probably 2-3 after redesign)
- Show context blocks for all error types that have them, not just runtime
- Collapse near-identical `exception_to_diagnostics()` branches (UserFriendlyError + MCPError + OutputResolutionError are 3 branches with ~90% identical code)
- Ensure every piece of populated context is either rendered or explicitly excluded with documented reasoning

## Design Decisions

- **`format_execution_success()` keeps its dict return type**: JSON consumers need serialized dicts. Text consumers bypass this function entirely.
- **`ValidationResult.errors` changes to `list[Diagnostic]`**: Deferred from Task 143. An `error_messages` property provides the `list[str]` shortcut if needed.
- **`to_display_dict()` and `to_dict()` stay**: They're JSON serializers, not bridges. What gets removed is deserializing those dicts back into Diagnostics for text rendering.
- **Rendering redesign is informed by research, not prescribed**: The current analysis (6 paths → 2) is a starting point, not a conclusion. The research phase may reveal a different optimal structure.

## Dependencies

- Task 143: Unified Diagnostic System — must be merged first.

## Requirements

### Data Flow (Phase 2 — well-specified)

- All text rendering paths receive `Diagnostic` objects and call `format_diagnostic()` without intermediate dict conversion
- `ValidationResult.errors` returns `list[Diagnostic]`
- `format_validation_failure()` accepts `list[Diagnostic]`
- `coerce_warning_diagnostic` and `coerce_error_diagnostic` deleted from codebase
- MCP error path uses consistent types (not mixed Diagnostics and dicts)
- JSON output shape unchanged

### Rendering (Phase 3 — informed by Phase 1 research)

- Every context key populated by `exception_to_diagnostics()` is either rendered in text or explicitly documented as JSON-only with reasoning
- No silent information loss between exception fields and rendered output
- Rendering paths reduced to the minimum needed (research determines the number)
- `exception_to_diagnostics()` branches with identical structure collapsed
- `diagnostic.py` reduced from ~683 lines (target depends on research findings)

## Implementation Notes

### Current dict round-trip call sites

**`coerce_warning_diagnostic` (5 production sites):**
1. `success_formatter.py:57` — stays for JSON, text path bypasses
2. `success_formatter.py:249` — `format_success_as_text()` receives Diagnostics directly
3. `workflow_output.py:600` — `_display_execution_summary()` receives Diagnostics directly
4. `workflow_errors.py:108` — `_extract_result_warnings()` fallback, no longer needed
5. `execution_service.py:171` — `_build_error_text()` receives Diagnostics directly

**`coerce_error_diagnostic` (2 production sites):**
1. `execution_service.py:163` — `_build_error_text()` receives Diagnostics directly
2. `workflow_errors.py:40` — `_display_single_error()` coerce becomes unnecessary

### Starting observations for rendering research

These are preliminary findings, not conclusions. The research phase must verify and extend them:

- **6 rendering paths exist**, but only 2 patterns appear truly distinct (structured block vs user-friendly block). Max-visits, simple, and validation paths are minor variants of the runtime default.
- **Context blocks** (API response, shell stderr, MCP error, template fields) are only appended by `_format_runtime_error_context_lines()`, which only the runtime default path calls. Other paths silently ignore context.
- **`exception_to_diagnostics()` has 3 near-identical branch groups**: UserFriendlyError/MCPError/OutputResolutionError (~75 lines, differ only in category); FileNotFoundError/PermissionError/generic (~35 lines, differ only in category); SchemaValidationError/MarkdownParseError (~30 lines, similar structure).
- **Warning rendering is a single path** (`_format_warning_or_info_diagnostic`) — clean and probably doesn't need changes. But should warnings with context (e.g., template string) show that context in text?

### How the success text path changes (Phase 2)

Currently:
```
_handle_workflow_success → format_execution_success(warnings=Diagnostics) → dict with warnings as display_dicts
→ _display_execution_summary(dict) → reads dict["warnings"] → coerce back → format_diagnostic
```

After:
```
_handle_workflow_success → format_execution_success(warnings=Diagnostics) → dict (for JSON only)
                         ↘ _display_execution_summary(diagnostics=Diagnostics) → format_diagnostic directly
```

### How `format_validation_failure()` changes (Phase 2)

Currently: `format_validation_failure(errors: list[str], suggestions: list[str] | None)` — renders bullet points from plain strings.

After: `format_validation_failure(errors: list[Diagnostic])` — renders using `format_diagnostic()` for each error. Suggestions come from `Diagnostic.suggestion`. The `suggestions` parameter is removed (suggestions are INFO diagnostics in `vresult.diagnostics`, rendered separately).

### Files to modify

| File | Change |
|------|--------|
| `src/pflow/core/diagnostic.py` | Delete `coerce_*_diagnostic()`, consolidate rendering paths (Phase 3) |
| `src/pflow/execution/result.py` | `ValidationResult.errors` returns `list[Diagnostic]`, add `error_messages -> list[str]` property |
| `src/pflow/execution/formatters/success_formatter.py` | `format_success_as_text()` takes `list[Diagnostic]` for warnings |
| `src/pflow/execution/formatters/validation_formatter.py` | `format_validation_failure()` takes `list[Diagnostic]` |
| `src/pflow/cli/workflow_output.py` | `_display_execution_summary()` takes `list[Diagnostic]` for warnings |
| `src/pflow/cli/workflow_errors.py` | Remove `_extract_result_warnings()` fallback, remove coerce calls |
| `src/pflow/cli/main.py` | `_display_validation_result()` uses Diagnostics for errors and warnings in JSON |
| `src/pflow/mcp_server/services/execution_service.py` | `_format_error_result()` and `_build_error_text()` use Diagnostics consistently |

### What NOT to change

- `format_execution_success()` return type (dict) — JSON consumers depend on it
- `to_display_dict()` / `to_dict()` — JSON serializers, not bridges
- `build_error_list()` in `executor_service.py` — already returns `list[Diagnostic]`
- `exception_to_diagnostics()` type dispatch — may be consolidated in Phase 3, but the exception→Diagnostic boundary stays

### Open questions (to be resolved in Phase 1)

1. How should `format_success_as_text()` receive Diagnostics? Alongside the dict, or via a new interface?
2. How should `_display_execution_summary()` receive warnings? Extra parameter or embedded in the formatted dict?
3. Is the user-friendly format (title/explanation/suggestions) the right model for all errors?
4. Should text output show the same information density as JSON, or is selective display correct?
5. What does "agent-actionable" mean concretely for each error type's text output?

## Verification

### Baseline comparison — quality gate, not regression guard

Task 143 used baselines to prove "no information lost." This task uses baselines to prove "every output improved or justified."

**Before implementation (end of Phase 1):**
1. Capture current text and JSON output for every error type, warning type, and display path — same coverage as Task 143's `capture_baselines.py` (87 outputs across CLI text, CLI JSON, MCP text, validate-only).
2. For each captured output, annotate: what information is available in the Diagnostic that isn't shown? What's inconsistent with other error types? What would an agent need that's missing?
3. Design the target output for each case. Produce concrete "before → after" pairs with commentary on what improved and why.

**After implementation (end of Phase 3):**
1. Recapture all outputs using the same harness.
2. Diff every output against the Phase 1 capture. For each diff:
   - **Changed for the better**: more information, better structure, more actionable → document what improved
   - **Changed for the worse**: less information, less clear, less actionable → this is a bug, fix it
   - **Unchanged**: if the Phase 1 annotation identified missing information or inconsistency, this is a missed opportunity — justify why it wasn't addressed or address it
3. No output should be unchanged without justification. The whole point of this task is that every rendering path gets better.

**The baseline is not a safety net — it's a scorecard.**

### Functional
- All text output paths render via `format_diagnostic()` without dict→Diagnostic coercion
- Validation text output shows suggestions from Diagnostics (currently lost)
- Every populated context key is rendered or documented as JSON-only with reasoning
- `coerce_warning_diagnostic` and `coerce_error_diagnostic` absent from codebase

### Quality
- `make test` passes
- `make check` passes
- JSON output shape unchanged or improved (additive only)
- Every text output is more informative, more consistent, or more actionable than the Task 143 baseline — no exceptions without documented justification

### Edge cases
- Workflow with no warnings — `warnings` key in JSON is empty list, not absent
- Workflow with only parser warnings — text shows warnings, status is SUCCESS (not DEGRADED)
- Validate-only with errors + suggestions — both render in text and JSON

### Research deliverables (Phase 1)
- Context key map: exception type → populated keys → rendered vs. JSON-only vs. dropped
- Annotated baseline captures with gap analysis
- Before/after text examples for each error type with improvement commentary
- Proposed rendering architecture with rationale

## References

- Task 143: Unified Diagnostic System — `src/pflow/core/diagnostic.py`
- Task 143 braindump: `.taskmaster/tasks/task_143/starting-context/braindump-unified-diagnostic-design.md` (compiler diagnostic pattern discussion)
- Task 143 progress log: `.taskmaster/tasks/task_143/implementation/progress-log.md`
- Task 143 task review: `.taskmaster/tasks/task_143/task-review.md` (architectural decisions, tech debt section)
- Display consolidation braindump: `.taskmaster/tasks/task_144/starting-context/braindump-display-consolidation.md`

### Key files
- `src/pflow/core/diagnostic.py` — the type, conversion (13 types), rendering (6 paths), bridge functions
- `src/pflow/execution/result.py` — `ValidationResult.errors` property
- `src/pflow/execution/formatters/success_formatter.py` — dict round-trip
- `src/pflow/execution/formatters/validation_formatter.py` — takes `list[str]`
- `src/pflow/cli/workflow_output.py` — dict round-trip
- `src/pflow/cli/workflow_errors.py` — coerce calls, display helpers
- `src/pflow/mcp_server/services/execution_service.py` — mixed types
