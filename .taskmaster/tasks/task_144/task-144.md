# Task 144: Display Consolidation — Diagnostic Rendering Redesign

## Description

Three interconnected problems in the diagnostic layer after Task 143:

1. **Dict round-trip anti-pattern**: Text rendering paths convert Diagnostic → dict → Diagnostic → text, requiring bridge functions (`coerce_*_diagnostic`).
2. **Rendering complexity without clarity**: `format_diagnostic()` has 6 special-case rendering paths (~260 lines) that probe context dict keys to reverse-engineer the original exception type. Context blocks (shell stderr, API response) only render for one of the 6 paths — others silently drop them.
3. **Central conversion dispatch**: `exception_to_diagnostics()` is a 230-line, 13-branch switch that maps typed exception attributes to generic context dicts. Each branch must know the exception's internal structure. Adding a new exception type requires modifying a separate file.

This task redesigns the diagnostic pipeline end-to-end: one rendering format for all errors, self-describing exceptions, and no bridge code. The goal is not "consolidate what exists" but "build the architecture a top 10% codebase would have."

## Status

Phase 1 (research) complete. Implementation not started.

## Priority

medium

## Problem

### Research findings (Phase 1 — complete)

Phase 1 produced 56 baseline outputs across 21 fixtures. Key metrics:
- **76% context key coverage** (96/127 keys rendered, 31 silently dropped)
- **6 inconsistent error formats** — agent can't predict or parse output reliably
- **Same diagnostic, different format** depending on parameters (validation errors render completely differently with/without `error_number`)
- **Simple errors are information-poor** — `FileNotFoundError` renders as `✗ workflow.pflow.md` (nothing actionable)
- **Parallel rendering system** — `registry_run_formatter.py` reimplements error formatting for the same exception types with different output

Research deliverables in `scratchpads/task-144-diagnostic-rendering/`:
- `capture_baselines.py` — automated baseline capture script (56 outputs)
- `baselines-before/rendering-output.txt` — current rendering state
- `baselines-before/context-coverage.txt` — per-fixture context key coverage
- `gap-analysis.md` — per-fixture annotation of what's missing and why
- `target-output-design.md` — concrete before/after for every error type

### Diagnostic type smells

Two design compromises on `Diagnostic` from Task 143 that create complexity in the rendering:

1. **`title` in context dict, not as a field**: Every error needs a title for the unified format. Currently it's a convention (`context["title"]`), not enforced. The renderer probes the context dict to find it, and falls through to different formats when it's missing.

2. **`suggestion` (string) vs `context["suggestions"]` (list)**: Two representations of the same data. The renderer reads the list for numbered display, falls back to the string. The join/split is waste.

## Solution

### Diagnostic type refinement

Add `title` and `suggestions` as first-class fields on `Diagnostic`. Remove the dual `suggestion`/`context["suggestions"]` split:

```python
@dataclass
class Diagnostic:
    severity: Severity
    message: str
    title: str | None = None              # NEW — display title for the error
    suggestions: list[str] | None = None  # REPLACES suggestion: str | None
    node_id: str | None = None
    source: str = ""
    context: dict[str, Any] | None = None
```

`__hash__` and `__eq__` stay on `(severity, source, node_id, message)`. `title` and `suggestions` are display data, not identity.

### Self-describing exceptions

Each PflowError subclass gets a `to_diagnostics()` method that produces its own `Diagnostic` representation. This replaces the 13-branch central converter with polymorphic dispatch:

```python
class CompilationError(PflowError):
    def to_diagnostics(self) -> list[Diagnostic]:
        return [Diagnostic(
            severity=Severity.ERROR,
            title="Compilation Failed",
            message=self.raw_message,
            suggestions=[self.suggestion] if self.suggestion else None,
            node_id=self.node_id,
            source="compilation",
            context={"phase": self.phase, "node_type": self.node_type, ...},
        )]
```

`exception_to_diagnostics()` becomes a thin dispatcher (~20 lines):
```python
def exception_to_diagnostics(exception: Exception) -> list[Diagnostic]:
    if hasattr(exception, "to_diagnostics"):
        diagnostics = exception.to_diagnostics()
    else:
        diagnostics = [_builtin_exception_diagnostic(exception)]
    # Apply engine node_id annotation
    ...
    return diagnostics
```

This is NOT a reversal of Task 143's removal of `format_for_cli()`:
- `format_for_cli()` → presentation method (coupled to CLI text rendering). **Correctly removed.**
- `to_diagnostics()` → data conversion method (coupled to `Diagnostic` type only). **Different concern.** Same pattern as `__str__()`, Pydantic's `model_dump()`, Django's `clean()`.

### One rendering format

All errors use the same titled format. One rendering function, no dispatch on `source`, `category`, `title`, or `node_id`:

```
Error[  N]: {title}

{message}
  At: {location}

  {context blocks}

To fix this:
  1. {suggestion}

Run with --verbose for technical details.
```

Sections omitted when data is absent. Warnings unchanged (already one clean path).

### Bypass elimination

All error rendering paths that bypass `format_diagnostic()` are folded into the diagnostic pipeline:
- `registry_run_formatter.py` (3 error formatters) — deleted
- `error_output.py:160-165` (UnicodeDecodeError, registry RuntimeError special cases) — routed through diagnostics
- `workflow_output.py:258-259` (OutputResolutionError as raw warning) — routed through diagnostics
- `workflow_errors.py:73-75` (empty errors fallback) — produces a proper diagnostic

## Design Decisions

All resolved during Phase 1 research.

### Architectural

- **One rendering format**: The user-friendly format (title/explanation/suggestions) is the standard for ALL errors. Not "6 paths → 2-3" — one path. Follows rustc/ruff/mypy pattern.
- **`to_diagnostics()` on exception classes**: Each exception is self-describing. The central converter becomes a thin dispatcher. Follows the `__str__()` / `model_dump()` pattern. `context` dict carries only heterogeneous enrichment data (shell/API/MCP details), not title or suggestions.
- **Title derivation in producers, not renderer**: Every `to_diagnostics()` method sets `title=`. The renderer reads the field. No context probing.
- **Built-in exception fallback**: `FileNotFoundError`, `PermissionError`, `ValueError`, generic `Exception` can't have `to_diagnostics()`. A small lookup function handles them (~20 lines).
- **`_pflow_node_id` annotation**: Applied by the thin dispatcher after `to_diagnostics()` returns, using `dataclasses.replace()`. Exception methods don't read the annotation — separation of concerns.

### Data flow

- **`format_execution_success()` keeps its dict return type**: JSON consumers need it. Text consumers receive Diagnostics separately.
- **`ValidationResult.errors` returns `list[Diagnostic]`**: Deferred from Task 143. An `error_messages` property provides the `list[str]` shortcut.
- **`to_display_dict()` and `to_dict()` stay**: JSON serializers, updated for new fields. Not bridges for text rendering.

### Format details

- **`error_number`**: `None` or `0` → `Error: Title`. `N` → `Error N: Title`. Same format in both cases.
- **Location (`At:`)**: `At: node 'X'`, `At: nodes[0].type`, `At: line 42`. Multiple parts comma-separated.
- **Single suggestion**: `→ text`. Multiple suggestions: numbered list under `To fix this:`.
- **Verbose hint**: `Run with --verbose for technical details.` only when `technical_details` exists in context and `verbose=False`.
- **Validation failure list**: Compact numbered format in `format_validation_failure()`. Truncation at 5 errors (each is 2-3 lines). Per-error suggestions from Diagnostic, not auto-generated.
- **`_display_single_error()` header**: Removed. `format_diagnostic()` provides the title. Warning count moves to warnings section header.
- **`_build_error_text()` header**: Uses diagnostic title for single error, generic "Workflow execution failed" for multiple. `format_diagnostic()` produces the titled block.
- **Warning rendering**: Unchanged. `suggestions` field: render first item inline with `→`.

### Scope boundaries

**In scope (7 bypass paths + existing task scope):**
1. `error_output.py:160-165` — UnicodeDecodeError + registry RuntimeError special cases
2. `workflow_errors.py:73-75` — empty errors fallback
3. `registry_run_formatter.py:44-98` — `format_execution_error()` (parallel renderer)
4. `registry_run_formatter.py:10-41` — `format_node_not_found_error()` (parallel renderer)
5. `registry_run_formatter.py:101-132` — `format_ambiguous_node_error()` (parallel renderer)
6. `validation_formatter.py:40-104` — `format_validation_failure()` takes `list[str]`
7. `workflow_output.py:258-259` — OutputResolutionError rendered as raw warning

**Out of scope:**
- `cli_output.py:49-54` — `CliOutput.show_error()` — OutputInterface abstraction, different layer
- `discovery_errors.py:42-67` — API key configuration guidance, different concern
- `workflow_output.py:386-393` — Batch per-item errors, different display context
- ~41 Tier 2 `Error: {e}` one-liners in CLI command handlers — CLI boundary, not diagnostic rendering
- Pre-existing bug: uncaught `CompilationError` from `inject_special_parameters()` at `registry_run.py:197-201`

## Dependencies

- Task 143: Unified Diagnostic System — merged.

## Requirements

### Diagnostic type

- `Diagnostic` has `title: str | None = None` field
- `Diagnostic` has `suggestions: list[str] | None = None` field (replaces `suggestion: str | None`)
- `to_dict()` and `to_display_dict()` serialize the new fields
- `__hash__` and `__eq__` unchanged (identity = severity/source/node_id/message)
- All Diagnostic constructors updated for new field names

### Self-describing exceptions

- `PflowError` base class has a default `to_diagnostics() -> list[Diagnostic]` method
- 8 PflowError subclasses override `to_diagnostics()` with rich conversion: `CompilationError`, `WorkflowValidationError`, `SchemaValidationError`, `MarkdownParseError`, `WorkflowNotFoundError`, `UserFriendlyError`, `MCPError` (inherits with category override), `OutputResolutionError`
- `MaxNodeVisitsError` (RuntimeError, not PflowError) has `to_diagnostics()`
- `exception_to_diagnostics()` reduced from ~230 lines / 13 branches to ~20 lines / 2 paths (has method + builtin fallback)
- 7 lazy imports in `exception_to_diagnostics()` removed (no longer needed)
- `MarkdownParseError` gets `raw_message` attribute (like `CompilationError`)

### Rendering

- `format_diagnostic()` has ONE error rendering path (the titled format)
- Warning rendering unchanged
- Context blocks rendered for ALL error types (not just runtime default)
- New context block renderers: compilation details (phase), similar-names list, exception-type line
- 6 old rendering functions deleted: `_format_validation_diagnostic`, `_format_not_found_diagnostic`, `_format_user_friendly_diagnostic`, `_format_simple_error_diagnostic`, `_format_runtime_error_diagnostic`, `_format_runtime_error_header_lines`, `_is_simple_error_diagnostic`
- Every populated context key rendered in text or documented as JSON-only with reasoning

### Data flow

- All text rendering paths receive `Diagnostic` objects directly (no dict round-trips)
- `coerce_warning_diagnostic` and `coerce_error_diagnostic` deleted from codebase
- `ValidationResult.errors` returns `list[Diagnostic]`, `error_messages` property for `list[str]`
- `format_validation_failure()` takes `list[Diagnostic]`
- `_build_error_text()` receives `list[Diagnostic]` directly
- `_display_single_error()` simplified (no header, just `format_diagnostic()`)
- JSON output shape unchanged or additive only

### Bypass elimination

- `registry_run_formatter.py` deleted (entire file — only contains error formatters)
- Registry run CLI (`registry_run.py`) error paths route through diagnostics or direct Diagnostic construction
- Registry run MCP (`execution_service.py:run_registry_node`) error paths route through diagnostics (double-formatting eliminated)
- `error_output.py` special cases for UnicodeDecodeError and registry RuntimeError removed
- `workflow_output.py:258-259` OutputResolutionError renders through diagnostics

### Suggestions added to simple exceptions

- `FileNotFoundError` → `suggestions=["Check the file path and ensure the file exists."]`
- `PermissionError` → `suggestions=["Check file permissions and access rights."]`

### Exception-specific conversion notes

- **`WorkflowNotFoundError.to_diagnostics()`**: `suggestions` changes from `["Did you mean: name1, name2"]` (current converter) to generic guidance `["Use 'pflow workflow list' to see all available workflows."]`. The similar names are in `context["similar_names"]` and rendered as a context block — they are no longer the suggestion.
- **`WorkflowValidationError.to_diagnostics()`**: Returns MULTIPLE Diagnostics — one per validation error in `self.validation_errors`. Each gets its own `title`, `suggestions`, and `context["path"]`. The fallback (empty validation_errors) returns a single Diagnostic with `str(self)` as message.
- **`context` dict must NOT contain `title` or `suggestions`**: These are now first-class fields. Putting them in context would create dual storage (the smell we're eliminating). The `to_diagnostics()` methods set `title=` and `suggestions=` on the Diagnostic, not in context.

### Deletions (complete list)

- `Diagnostic.suggestion` field (replaced by `suggestions: list[str] | None`)
- `coerce_warning_diagnostic()`, `coerce_error_diagnostic()`, `_coerce_diagnostic()`, `_KNOWN_FIELDS` constant
- `_format_validation_diagnostic()`, `_format_not_found_diagnostic()`, `_format_user_friendly_diagnostic()`, `_format_simple_error_diagnostic()`, `_format_runtime_error_diagnostic()`, `_format_runtime_error_header_lines()`, `_is_simple_error_diagnostic()`
- `registry_run_formatter.py` (entire file)
- 7 lazy imports in `exception_to_diagnostics()` (from `exceptions.py` and `user_errors.py`)
- `_handle_execution_error()`, `_handle_unknown_node()`, `_handle_ambiguous_node()` in `registry_run.py`

### Title derivation map (for built-in exception fallback)

| Category | Title |
|----------|-------|
| `compilation` | Compilation Failed |
| `max_visits` | Infinite Loop Detected |
| `validation` | Validation Error |
| `parse_error` | Parse Error |
| `not_found` | Workflow Not Found |
| `file_not_found` | File Not Found |
| `permission_denied` | Permission Denied |
| `execution_failure` | Execution Failed |
| `api_validation` | API Validation Error |
| `template_error` | Template Error |

## Files to modify

| File | Change |
|------|--------|
| `src/pflow/core/diagnostic.py` | Add `title`/`suggestions` fields. Delete `suggestion` field. Delete `coerce_*_diagnostic()`. Replace 6 rendering paths with 1. Rewrite `exception_to_diagnostics()` as thin dispatcher. Update `to_dict()`/`to_display_dict()`. |
| `src/pflow/core/exceptions.py` | Add `to_diagnostics()` to `PflowError` (default), `CompilationError`, `MaxNodeVisitsError`, `WorkflowValidationError`, `SchemaValidationError`, `MarkdownParseError`, `WorkflowNotFoundError`. Add `raw_message` to `MarkdownParseError`. Import `Diagnostic`, `Severity`. |
| `src/pflow/core/user_errors.py` | Add `to_diagnostics()` to `UserFriendlyError` (base), `MCPError` (category override), `OutputResolutionError` (adds failures). Import `Diagnostic`, `Severity`. |
| `src/pflow/execution/result.py` | `ValidationResult.errors` returns `list[Diagnostic]`, add `error_messages` property. |
| `src/pflow/execution/formatters/success_formatter.py` | `format_success_as_text()` receives warnings as `list[Diagnostic]`. Update `format_execution_success()` for new field names. |
| `src/pflow/execution/formatters/validation_formatter.py` | `format_validation_failure()` takes `list[Diagnostic]`. Compact numbered format. Truncation at 5. |
| `src/pflow/execution/formatters/registry_run_formatter.py` | **DELETE** (all 3 functions replaced by diagnostic pipeline). |
| `src/pflow/execution/formatters/error_formatter.py` | Update for `suggestions` field name change. |
| `src/pflow/execution/executor_service.py` | `build_error_list()` sets `title=` on Diagnostics. Update `suggestion=` to `suggestions=`. |
| `src/pflow/cli/workflow_output.py` | `_display_execution_summary()` receives warnings as `list[Diagnostic]`. Fix OutputResolutionError raw rendering (line 258). |
| `src/pflow/cli/workflow_errors.py` | Simplify `_display_single_error()` (no header, no coerce). Simplify `_collect_warning_diagnostics()`. |
| `src/pflow/cli/error_output.py` | Remove UnicodeDecodeError/registry RuntimeError special cases. Route through diagnostics. |
| `src/pflow/cli/main.py` | `_display_validation_result()` uses Diagnostics for errors. Update for `suggestions` field. |
| `src/pflow/cli/commands/registry_run.py` | Replace `_handle_execution_error()`, `_handle_unknown_node()`, `_handle_ambiguous_node()` with diagnostic pipeline. |
| `src/pflow/mcp_server/services/execution_service.py` | `_build_error_text()` receives Diagnostics directly. `run_registry_node()` error paths use diagnostics (eliminate double-formatting). `validate_workflow()` passes Diagnostics. |
| `src/pflow/core/workflow/validator.py` | Update warning Diagnostic constructors for `suggestions` field. |
| `src/pflow/core/markdown_parser.py` | Update warning Diagnostic constructors for `suggestions` field. |
| `src/pflow/runtime/engine/engine.py` | Update warning Diagnostic constructors for `suggestions` field. |
| `src/pflow/execution/runner.py` | Update Diagnostic constructors for `suggestions` field. Remove lazy exception imports if no longer needed. |

### What NOT to change

- `format_execution_success()` return type (dict) — JSON consumers depend on it
- `to_display_dict()` / `to_dict()` — JSON serializers (updated for new fields, not deleted)
- `build_error_list()` in `executor_service.py` — stays as direct Diagnostic producer (updated for title/suggestions)
- Warning rendering path — already clean, only field name changes
- Batch per-item error display — different display context
- CLI command-level `except` handlers — CLI boundary, not diagnostic rendering

## Verification

### Baseline comparison — quality gate, not regression guard

Baseline capture script: `scratchpads/task-144-diagnostic-rendering/capture_baselines.py`
Before-baselines: `scratchpads/task-144-diagnostic-rendering/baselines-before/`
Gap analysis: `scratchpads/task-144-diagnostic-rendering/gap-analysis.md`
Target output design: `scratchpads/task-144-diagnostic-rendering/target-output-design.md`

**After implementation:**
1. Run `uv run python scratchpads/task-144-diagnostic-rendering/capture_baselines.py after`
2. Run `uv run python scratchpads/task-144-diagnostic-rendering/capture_baselines.py compare`
3. For every output diff: state what improved. If unchanged, justify.
4. Context coverage must improve from 76% toward ~95%+ (only `action` intentionally dropped).
5. Every test assertion update must be justified — the new format is better than what the test previously asserted.

### Functional

- All text output paths render via `format_diagnostic()` without dict→Diagnostic coercion
- Validation text output shows per-error suggestions and locations (currently lost)
- Every populated context key rendered or documented as JSON-only with reasoning
- `coerce_warning_diagnostic` and `coerce_error_diagnostic` absent from codebase
- `registry_run_formatter.py` absent from codebase
- No bypass paths render errors outside the diagnostic pipeline (for in-scope paths)
- `exception_to_diagnostics()` has no lazy imports and no isinstance chains for PflowError subclasses

### Quality

- `make test` passes
- `make check` passes (mypy + ruff clean)
- JSON output shape unchanged or improved (additive only)
- Every text output more informative, consistent, or actionable than baseline

### Edge cases

- Workflow with no warnings — `warnings` key in JSON is empty list
- Workflow with only parser warnings — text shows warnings, status is SUCCESS
- Validate-only with errors + suggestions — both render in text and JSON
- `WorkflowValidationError` with 15+ errors — truncation at 5 in `format_validation_failure()`
- `FileNotFoundError` and `PermissionError` — now have title and suggestions (were bare messages)
- `MaxNodeVisitsError` without `error_number` — now uses titled format (was bare `❌` one-liner)

## Implementation Notes

### Import structure after changes

```
exceptions.py  →  imports Diagnostic, Severity from diagnostic.py (module-level)
user_errors.py →  imports Diagnostic, Severity from diagnostic.py (module-level)
diagnostic.py  →  zero imports from exceptions.py (lazy imports deleted)
```

The dependency arrow flips. `diagnostic.py` no longer knows about exception types. No circular import — verified.

### UserFriendlyError hierarchy

`MCPError` inherits `UserFriendlyError.to_diagnostics()` with a category override. `OutputResolutionError` overrides `to_diagnostics()` entirely (has unique `failures` data).

### Registry run migration

Not-found and ambiguous-node errors construct Diagnostics directly at the call site (no exception thrown). Pattern:
```python
diagnostic = Diagnostic(severity=Severity.ERROR, title="Node Not Found",
                        message=f"Node '{node_type}' not found in registry.", ...)
click.echo(format_diagnostic(diagnostic), err=True)
sys.exit(1)
```

Generic execution errors route through `exception_to_diagnostics()` + `format_diagnostic()`.

### `_pflow_node_id` annotation flow

The engine sets `exception._pflow_node_id` after raising. The thin dispatcher applies it:
```python
if annotated_node_id:
    from dataclasses import replace
    diagnostics = [replace(d, node_id=annotated_node_id) if not d.node_id else d for d in diagnostics]
```

Exception `to_diagnostics()` methods don't read `_pflow_node_id` — separation of concerns.

### Approximate line count impact

| Area | Lines removed | Lines added | Net |
|------|-------------|-------------|-----|
| Rendering (6 paths → 1) | ~260 | ~60 | -200 |
| Converter (13 branches → thin dispatcher) | ~230 | ~20 | -210 |
| `to_diagnostics()` methods (9 classes) | 0 | ~110 | +110 |
| Coerce functions + call sites | ~70 | 0 | -70 |
| `registry_run_formatter.py` | ~133 | ~20 | -113 |
| Bypass paths | ~20 | 0 | -20 |
| Diagnostic type + serialization updates | ~10 | ~20 | +10 |
| **Total estimate** | **~720** | **~230** | **~-490** |

## References

- Task 143 review: `.taskmaster/tasks/task_143/task-review.md`
- Task 141 review: `.taskmaster/tasks/task_141/task-review.md`
- Task 135 review: `.taskmaster/tasks/task_135/task-review.md`
- Progress log: `.taskmaster/tasks/task_144/implementation/progress-log.md`
- Baseline capture: `scratchpads/task-144-diagnostic-rendering/capture_baselines.py`
- Gap analysis: `scratchpads/task-144-diagnostic-rendering/gap-analysis.md`
- Target output: `scratchpads/task-144-diagnostic-rendering/target-output-design.md`
- Braindump: `.taskmaster/tasks/task_144/starting-context/braindump-display-consolidation.md`
