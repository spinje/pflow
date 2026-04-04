# Task 144 Review: Display Consolidation — Diagnostic Rendering Redesign

## Metadata
- Implementation Date: 2026-04-04
- Branch: `feat/diagnostic-rendering-redesign`
- Related Issue: spinje/pflow#219 (filed during implementation — pre-existing validator gap)
- Depends on: Task 143 (Unified Diagnostic System)

## Executive Summary

Redesigned the diagnostic pipeline end-to-end: 6 inconsistent error text formats → 1 unified titled format, 13-branch central converter → polymorphic `to_diagnostics()` dispatch, dict round-trip bridge code → direct Diagnostic passing. One file deleted (`registry_run_formatter.py`), ~270 net lines removed from `diagnostic.py`. Every error output is now more informative or unchanged. The baseline comparison caught 3 regressions that were fixed before completion.

## Implementation Overview

### What Was Built

1. **Diagnostic type gains `title` and `suggestions`** — `suggestion: str | None` replaced with `title: str | None` + `suggestions: list[str] | None`. `__post_init__` guard catches accidental `suggestions="string"` at runtime.

2. **Self-describing exceptions** — 9 exception classes now have `to_diagnostics() -> list[Diagnostic]`. `exception_to_diagnostics()` went from 230-line/13-branch switch to 30-line thin dispatcher. Import direction flipped: `exceptions.py` → `diagnostic.py` (was reversed via lazy imports).

3. **One rendering format** — All errors render as `Error[  N]: {title}\n\n{message}\n  At: {location}\n  {context blocks}\n  → {suggestions}`. Six old rendering functions deleted. Context blocks (shell, API, MCP, template, compilation, similar-names, exception-type) now render for ALL error types, not just specific ones.

4. **Dict round-trip eliminated** — `coerce_warning_diagnostic` and `coerce_error_diagnostic` deleted. Warning Diagnostics passed directly to text renderers. `ValidationResult.errors` returns `list[Diagnostic]` (was `list[str]`).

5. **Bypass paths eliminated** — `registry_run_formatter.py` deleted. CLI and MCP registry-run error paths now go through the diagnostic pipeline with call-site enrichment for node-type context.

### Deviations from Spec

- **`error_messages` property not added** to `ValidationResult` — spec said to add it, but no caller needs it. YAGNI.
- **`_diagnostic_category` class variable** instead of per-class `to_diagnostics()` overrides for UserFriendlyError → MCPError hierarchy. Simpler.
- **`UnicodeDecodeError` specific branch added** — not in spec, but removing the `error_output.py` special case created a regression (rendered as generic "Validation Error" since it's a ValueError subclass).
- **Call-site enrichment pattern** for registry-run errors — spec said to use `exception_to_diagnostics()` directly, but that loses the node_type context the call site has. Enrichment via `dataclasses.replace()` fills the gap.
- **`error_number=0` truthiness** cleaned up — was not in spec but the review uncovered it as fragile. Changed to explicit `None` vs `int` semantics.

## Files Modified/Created

### Core Changes (16 production files)

- `src/pflow/core/diagnostic.py` — Foundation: type changes, unified renderer, thin dispatcher, `_CATEGORY_TITLES`, `_builtin_exception_diagnostic`. Went from 684 → 420 lines.
- `src/pflow/core/exceptions.py` — `to_diagnostics()` on `PflowError` (base), `CompilationError`, `WorkflowValidationError`, `SchemaValidationError`, `MarkdownParseError`, `WorkflowNotFoundError`, `MaxNodeVisitsError`. Added `raw_message` to `MarkdownParseError`.
- `src/pflow/core/user_errors.py` — `to_diagnostics()` on `UserFriendlyError` (via `_diagnostic_category`), override on `OutputResolutionError`. `MCPError` inherits with `_diagnostic_category = "mcp"`.
- `src/pflow/execution/result.py` — `ValidationResult.errors` → `list[Diagnostic]`
- `src/pflow/execution/formatters/validation_formatter.py` — Rewritten: accepts `list[Diagnostic] | list[str]`, numbered format, truncation at 5
- `src/pflow/execution/formatters/success_formatter.py` — `warning_diagnostics` parameter on `format_success_as_text`
- `src/pflow/execution/formatters/registry_run_formatter.py` — **DELETED**
- `src/pflow/execution/executor_service.py` — `build_error_list` adds `title` via `_CATEGORY_TITLES`
- `src/pflow/execution/runner.py` — `suggestions=` rename, `title=` on validate-only Diagnostics
- `src/pflow/cli/commands/registry_run.py` — `_handle_*` functions rewritten with diagnostic pipeline + call-site enrichment (`_registry_run_suggestions`)
- `src/pflow/cli/workflow_errors.py` — `_display_single_error` accepts `Diagnostic` directly, `error_number` uses `None` not `0`
- `src/pflow/cli/workflow_output.py` — `warning_diagnostics` threaded through, OutputResolutionError bypass fixed
- `src/pflow/cli/error_output.py` — UnicodeDecodeError/registry RuntimeError special cases removed
- `src/pflow/cli/main.py` — `_display_validation_result` uses `to_display_dict()` for JSON errors
- `src/pflow/mcp_server/services/execution_service.py` — `_build_error_text` takes Diagnostics directly, `_format_registry_run_exception` and `_format_node_not_found` extracted
- `src/pflow/core/markdown_parser.py`, `src/pflow/core/workflow/validator.py`, `src/pflow/runtime/template_validation/path_validation.py`, `src/pflow/runtime/workflow_executor.py` — Field rename only (`suggestion=` → `suggestions=`, `dataclasses.replace` for provenance)

### Test Files (15 files, 42 failures fixed, 4 tests added)

Critical tests (catch real bugs, not just coverage):
- `test_diagnostic.py::test_to_dict_does_not_leak_suggestions_reference` — catches mutation via reference leak
- `test_diagnostic.py::test_suggestions_rejects_bare_string` — catches `suggestions="text"` mistake
- `test_validate_only.py::test_json_errors_are_diagnostic_dicts_not_strings` — guards JSON shape at the type-change boundary
- `test_validate_only.py::test_text_validation_failure_renders_diagnostic_fields` — catches Diagnostic repr leaking into text output

## Design Reasoning — Why These Decisions

### Why one rendering format, not 2-3

The task spec originally said "6 paths, probably 2-3 after redesign." Research found the answer is 1. rustc, ESLint, mypy, ruff all converge on one diagnostic format — the differences are in which fields are populated, not in which rendering path executes.

With 6 formats, an AI agent parsing error output has to pattern-match against 6 visual styles (`❌ msg`, `✗ msg`, `Error at node 'X':`, `Error: Title`, `Category: / Message:`, etc.). With 1 format, the agent always knows: line 1 is `Error: {title}`, the `At:` line has the location, `→` has the fix. Predictable, parseable, no dispatch.

The user-friendly format (path 3 of 6) was already the best output in the codebase. Making it the standard means UserFriendlyError/MCPError/OutputResolutionError get ZERO changes. Everything else gets BETTER. One rendering function (~50 lines) replaces six (~260 lines).

### Why `to_diagnostics()` is NOT a reversal of Task 143

Task 143 explicitly removed `format_for_cli()` methods from exception classes. Task 144 adds `to_diagnostics()` methods to exception classes. An agent reading both reviews might see a contradiction.

The distinction is between PRESENTATION and DATA CONVERSION:
- `format_for_cli()` → returned `str` (rendered text). Coupled exceptions to CLI display format. If you changed the text format, you'd change every exception class. **Correctly removed in Task 143.**
- `to_diagnostics()` → returns `list[Diagnostic]` (structured data). Coupled exceptions to the `Diagnostic` type only. If you change the text format, you change ONE function (`format_diagnostic`), not 9 exception classes. **Different concern, same pattern as `__str__()` or Pydantic's `model_dump()`.**

The alternative — keeping the central 13-branch converter and enriching it with titles — would have made the converter MORE complex, investing deeper into the pattern we were trying to eliminate. If we're already rewriting every converter branch to add titles, moving the logic to where it belongs (the exception class) is the same work with a better result.

### Why typed exceptions stay (three layers)

If every exception produces the same `Diagnostic` type, why keep `CompilationError`, `WorkflowNotFoundError`, etc. as separate classes?

Three layers serve three purposes:

| Layer | Purpose | Type |
|---|---|---|
| **Exception** | Catch-site dispatch (`except CompilationError` vs `except WorkflowNotFoundError`) | Typed classes — stays typed |
| **Data** | Canonical output value for all display paths | `Diagnostic` — one type |
| **Rendering** | Text display for humans and agents | One format — unified |

If we collapsed exceptions to one type, catch sites would inspect string fields to decide what to do — replacing type-safe dispatch with context-key probing. That's the exact anti-pattern we eliminated from the renderer.

`to_diagnostics()` bridges layer 1 → layer 2. `format_diagnostic()` bridges layer 2 → layer 3. Multiple exception types → one data type → one text format.

### Why `title` and `suggestions` are Diagnostic fields, not context dict keys

Before this task, `title` lived in `context["title"]` and suggestions lived in both `Diagnostic.suggestion` (joined string) and `context["suggestions"]` (list). Two problems:

1. **`title` as a convention**: Every error needs a title in the unified format. Using `context["title"]` is a convention the type system can't enforce. The renderer had to probe the context dict to find it and fell through to different rendering paths when it was missing — the root cause of the 6-path dispatch. Making it a field means `diagnostic.title` is always there (or explicitly None), no probing.

2. **`suggestion`/`suggestions` dual representation**: The renderer read the list from context for numbered display, fell back to the string field for single-line display. Two representations of the same data. The join/split was waste. A single `suggestions: list[str] | None` eliminates the duplication.

Together, these changes make `context` carry ONLY heterogeneous enrichment data (shell stderr, API response, MCP errors, similar names, phase, line) — things that genuinely vary between error types and don't have a fixed schema.

### Why registry_run_formatter was in scope

A task named "Display Consolidation" should consolidate ALL parallel display systems, not just the ones in the original spec. `registry_run_formatter.py` had 3 functions that formatted the SAME exception types (FileNotFoundError, PermissionError, not-found) in a DIFFERENT way from `format_diagnostic()`. Two renderers for the same errors is drift.

The irony that sealed the decision: the bypass path provided BETTER guidance than the diagnostic path for simple errors. `format_execution_error(FileNotFoundError)` said "Verify the file path exists." The diagnostic path said `✗ workflow.pflow.md`. The system we were eliminating was more helpful than the unified system. The fix: bring the guidance INTO the diagnostic system (add suggestions to simple exception conversions) and delete the bypass.

### Why compact numbered format for validation failure lists

When displaying multiple validation errors as a group, each error getting the full titled block (`Error: Validation Error / message / At: path / → suggestion`) means "Validation Error" repeated N times when the header already says "Validation failed." Redundant.

The compact numbered format (`1. message / At: path / → suggestion`) shows all the structured data (location, suggestion) without the redundant title per-error. Each error is 2-3 lines instead of 1, so truncation changed from 10 to 5 to keep output under ~15 lines.

### The 141 → 143 → 144 evolution arc

This task is the completion of a three-task arc, each narrowing the problem space:

- **Task 141**: Consolidated the exception **hierarchy** (all under `PflowError`). Didn't change interfaces.
- **Task 143**: Consolidated the output **type** (3 incompatible warning types → `Diagnostic`). Created the 13-branch converter and 6-path renderer.
- **Task 144**: Consolidates the **rendering** (6 paths → 1) and the **conversion bridge** (13-branch converter → polymorphic dispatch).

The phased approach was the right process for understanding the problem — each task revealed what the next task needed to fix. But the intermediate states (13-branch converter, 6-path renderer, coerce bridges) were over-built. Task 144 targets the final design directly, informed by what Tasks 141 and 143 revealed.

## Architectural Decisions & Tradeoffs

### The call site owns the context

The most important pattern from this task. When `registry_run_formatter.py` was deleted, registry-run errors lost node_type context because the generic `exception_to_diagnostics()` doesn't know it's a registry run. The fix is NOT to add registry-awareness to the renderer — it's to enrich diagnostics at the call site via `dataclasses.replace()`:

```python
# In registry_run.py — the call site has node_type
diagnostics = exception_to_diagnostics(exc)
for d in diagnostics:
    enriched = replace(d, node_id=d.node_id or node_type, suggestions=_registry_run_suggestions(d, node_type, exc))
    click.echo(format_diagnostic(enriched), err=True)
```

This principle applies to any future code that routes errors through the generic diagnostic pipeline but has additional context.

### `_diagnostic_category` class variable

`UserFriendlyError.to_diagnostics()` reads `self._diagnostic_category` for the context dict. `MCPError` overrides with `_diagnostic_category = "mcp"`. This avoids duplicating the entire `to_diagnostics()` method for a one-field difference.

### `__post_init__` as a rename safety net

The `suggestion → suggestions` rename touches 28 constructor sites. A bare string `suggestions="text"` would iterate character-by-character in the renderer. The `__post_init__` guard catches this at construction time. Mypy also catches it, but this is defense-in-depth for dynamic code paths.

### Technical Debt

- `format_validation_failure()` accepts `list[Any]` — no type safety at the function boundary. It uses `isinstance(error, Diagnostic)` internally. Should be `list[Diagnostic]` once `WorkflowValidator.validate()` returns Diagnostics (spinje/pflow#219).
- `_display_execution_summary` reads warning count from the serialized dict (`formatted_result["warnings"]`) but renders from the directly-passed `warning_diagnostics`. The counts are consistent in practice but the dual source is a latent divergence risk.

## Unexpected Discoveries

### Baseline comparison catches what tests don't

The automated baseline script (`capture_baselines.py`) compares rendered text for 21 fixtures across multiple rendering paths. It caught 3 real regressions in registry bypass paths that all 4500+ tests missed — because the tests check for substrings like `"not found"` while the baselines compare full output quality.

**Run the baseline comparison after ANY rendering change:**
```bash
uv run python .taskmaster/tasks/task_144/research/capture_baselines.py after
uv run python .taskmaster/tasks/task_144/research/capture_baselines.py compare
```

### Context coverage metric is misleading

The coverage script checks if context dict values appear as substrings in rendered text. The new format expresses `category="compilation"` through `title="Compilation Failed"` — semantically better but not detected by substring matching. The metric dropped from 76% to 54% despite the output being objectively better. Evaluate fixture-by-fixture, not by aggregate metric.

### `UnicodeDecodeError` is a `ValueError` subclass

Removing the `error_output.py` special case for `UnicodeDecodeError` caused it to hit the generic `ValueError` branch in `_builtin_exception_diagnostic`, rendering as "Validation Error" with the raw codec error. Required a specific branch BEFORE the `ValueError` check, ordered by MRO specificity.

### `to_dict()` must copy mutable fields

The old `suggestion: str` was immutable — no aliasing risk. The new `suggestions: list[str]` is mutable — `to_dict()` must return `list(self.suggestions)` to prevent callers from corrupting the source Diagnostic. Caught by code review, not by tests.

## Patterns Established

### Adding a new PflowError subclass

1. Add `to_diagnostics() -> list[Diagnostic]` that sets `title=`, `suggestions=`, `source=`, `context=`
2. If the subclass is in a hierarchy (like UserFriendlyError), consider `_diagnostic_category` class variable instead of method override
3. If the error can't have `to_diagnostics()` (built-in exception), add a branch to `_builtin_exception_diagnostic()` in `diagnostic.py`
4. Run `capture_baselines.py` to verify the rendered output

### Adding a new context block renderer

1. Add the renderer function to `diagnostic.py` (e.g., `_format_my_block(context)`)
2. Call it from `_format_all_context_blocks()` — this is the ONLY place context blocks are dispatched
3. Add a fixture to `capture_baselines.py` to verify rendering

### Enriching diagnostics at a call site

When a call site has context that the generic pipeline doesn't (e.g., node_type in registry run):

```python
from dataclasses import replace
diagnostics = exception_to_diagnostics(exc)
enriched = [replace(d, node_id=d.node_id or my_context, suggestions=[...]) for d in diagnostics]
```

Do NOT add the context to the renderer or dispatcher. The call site owns the context.

## Breaking Changes

### JSON Output

- `Diagnostic.to_dict()` emits `"title"` (string) and `"suggestions"` (list of strings) instead of `"suggestion"` (string). All JSON consumers (MCP tools, CLI `--output-format json`) see the new shape.
- Validate-only JSON `"errors"` array entries changed from `{"message": str, "category": "validation"}` to full `Diagnostic.to_display_dict()` shape with `severity`, `source`, `title`, `suggestions`, `context`, etc.

### Text Output

Every error type now renders in the titled format. Agents or scripts parsing specific prefixes (`❌`, `✗`, `Error at node`) need to update to parse `Error: {title}` or `Error N: {title}`.

## AI Agent Guidance

### Quick Start for Related Tasks

Read in this order:
1. `src/pflow/core/diagnostic.py` — the type, the renderer, the dispatcher
2. `src/pflow/core/exceptions.py` — `to_diagnostics()` methods, `_diagnostic_category` pattern
3. `.taskmaster/tasks/task_144/research/target-output-design.md` — exact before/after for every error type

### Common Pitfalls

- **Don't put `title` or `suggestions` in the `context` dict** — they are first-class Diagnostic fields now. Putting them in context creates dual storage.
- **Don't add rendering logic to `_format_error_diagnostic()`** — add a context block renderer and call it from `_format_all_context_blocks()`.
- **Don't call `exception_to_diagnostics()` when you have context** the generic pipeline doesn't — enrich at the call site instead.
- **Don't use `suggestions="text"`** — the `__post_init__` guard will catch it, but use `suggestions=["text"]` from the start.

### Test-First Recommendations

When modifying diagnostic rendering:
1. Run `capture_baselines.py before` FIRST
2. Make changes
3. Run `capture_baselines.py after` then `compare`
4. Verify every fixture is same-or-better

When adding a new exception type:
1. Write the `to_diagnostics()` method
2. Add a fixture to `capture_baselines.py`
3. Verify `exception_to_diagnostics(your_exception)` produces the expected Diagnostic
4. Verify `format_diagnostic()` renders it correctly

---

*Generated from implementation context of Task 144*
