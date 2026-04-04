# Implementation Plan: Task 144 — Diagnostic Rendering Redesign

## Context

Task 144 redesigns the pflow diagnostic pipeline end-to-end. Three problems being solved simultaneously:

1. **6 inconsistent error text formats** → one titled format for all errors
2. **13-branch central converter** (`exception_to_diagnostics()`) → self-describing exceptions with `to_diagnostics()` methods
3. **Dict round-trip anti-pattern** (7 coerce call sites) + parallel rendering bypass (registry_run_formatter.py) → eliminated

The complete design is documented in:
- **Task spec**: `.taskmaster/tasks/task_144/task-144.md` — requirements, scope, design decisions
- **Progress log**: `.taskmaster/tasks/task_144/implementation/progress-log.md` — WHY behind every decision
- **Target output**: `scratchpads/task-144-diagnostic-rendering/target-output-design.md` — exact before/after for every error type
- **Gap analysis**: `scratchpads/task-144-diagnostic-rendering/gap-analysis.md` — what's missing per fixture
- **Baselines**: `scratchpads/task-144-diagnostic-rendering/baselines-before/` — 56 captured outputs for comparison

**Read all five files before implementing.** The task spec has the WHAT. The progress log has the WHY. The target output has the exact text each error should produce.

## Critical Design Decisions (summary — see progress log for full reasoning)

1. **One rendering format for all errors**: The user-friendly format (title/explanation/suggestions) becomes standard. Template: `Error[  N]: {title}` → message → `At: {location}` → context blocks → suggestions → verbose hint.

2. **`to_diagnostics()` on exception classes**: NOT a reversal of Task 143's removal of `format_for_cli()`. `format_for_cli()` was presentation (coupling to CLI text). `to_diagnostics()` is data conversion (coupling to `Diagnostic` type only). Same pattern as `__str__()`, Pydantic's `model_dump()`.

3. **`Diagnostic` type gains `title` and `suggestions` fields**: `title: str | None = None` (new), `suggestions: list[str] | None = None` (replaces `suggestion: str | None`). `context` dict no longer carries title or suggestions.

4. **Exception classes KEEP their `.suggestion: str` attribute**: Only `Diagnostic.suggestion` is renamed. `CompilationError.suggestion`, `SchemaValidationError.suggestion`, `MarkdownParseError.suggestion` stay as-is. The `to_diagnostics()` methods bridge: `suggestions=[self.suggestion] if self.suggestion else None`.

5. **Import direction flips**: After changes, `exceptions.py` imports `Diagnostic, Severity` from `diagnostic.py`. `diagnostic.py` has zero imports from `exceptions.py` (7 lazy imports deleted). No circular dependency.

6. **JSON key rename is a breaking change**: `to_dict()` emits `"suggestions"` (list) instead of `"suggestion"` (string). No backward compat shim — no external consumers exist. The task spec requirement "JSON output shape unchanged or additive only" is updated to acknowledge this intentional break.

## Implementation Steps

### Step 1: Diagnostic Type Changes

**Files**: `src/pflow/core/diagnostic.py`

This is the foundation — every subsequent step depends on the new field names.

**1a. Change the dataclass definition** (lines 18-30):

```python
# BEFORE:
@dataclass
class Diagnostic:
    """Single type for pflow diagnostics.

    Identity ignores context because context is mutable enrichment data.
    """

    severity: Severity
    message: str
    suggestion: str | None = None
    node_id: str | None = None
    source: str = ""
    context: dict[str, Any] | None = None

# AFTER:
@dataclass
class Diagnostic:
    """Single type for pflow diagnostics.

    Identity ignores context, title, and suggestions — these are display data, not identity.
    """

    severity: Severity
    message: str
    title: str | None = None
    suggestions: list[str] | None = None
    node_id: str | None = None
    source: str = ""
    context: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.suggestions, str):
            raise TypeError(
                f"Diagnostic.suggestions must be list[str] | None, got str: {self.suggestions!r}. "
                f"Wrap in a list: suggestions=[{self.suggestions!r}]"
            )
```

The `__post_init__` guard catches the most likely mechanical error during the 28-site rename: `suggestions="text"` instead of `suggestions=["text"]`. Without this, a bare string iterates character-by-character in the renderer, producing garbage output like `1. F`, `2. i`, `3. x` with no error. Mypy also catches it, but this is defense-in-depth.

**`__eq__` and `__hash__`**: Unchanged — identity is (severity, source, node_id, message). `title` and `suggestions` excluded.

**1b. Update `to_dict()`** (lines 45-58):

```python
# BEFORE:
if self.suggestion is not None:
    result["suggestion"] = self.suggestion

# AFTER:
if self.title is not None:
    result["title"] = self.title
if self.suggestions is not None:
    result["suggestions"] = self.suggestions
```

**1c. Update `_KNOWN_FIELDS`** (line 102):

```python
# BEFORE:
_KNOWN_FIELDS = {"severity", "message", "suggestion", "node_id", "source"}

# AFTER:
_KNOWN_FIELDS = {"severity", "message", "title", "suggestions", "node_id", "source"}
```

**1d. Update `_coerce_diagnostic`** (lines 105-119):

Change `suggestion=payload.get("suggestion")` to `suggestions=[payload["suggestion"]] if payload.get("suggestion") else None`. Also extract `title=payload.get("title")`.

**Verification**: Run `make check` — mypy will report every broken constructor and field access across the codebase. Fix them all in subsequent sub-steps.

### Step 1e: Fix ALL Diagnostic constructors (28 sites)

Every `Diagnostic(suggestion="text")` becomes `Diagnostic(suggestions=["text"])`.
Every `Diagnostic(suggestion="; ".join(lst))` becomes `Diagnostic(suggestions=lst)`.
Every `Diagnostic(suggestion=var)` where var is `str | None` becomes `Diagnostic(suggestions=[var] if var else None)`.

**Production files (18 sites):**

| File | Line(s) | Current | New |
|------|---------|---------|-----|
| `diagnostic.py` | 463-476 (CompilationError) | `suggestion=exception.suggestion` | `suggestions=[exception.suggestion] if exception.suggestion else None` |
| `diagnostic.py` | 480-492 (MaxNodeVisitsError) | `suggestion="Set PFLOW_MAX..."` | `suggestions=["Set PFLOW_MAX..."]` |
| `diagnostic.py` | 505 (WorkflowValidationError tuple) | `suggestion=error[2] or None` | `suggestions=[error[2]] if (len(error) >= 3 and error[2]) else None` |
| `diagnostic.py` | 536-543 (SchemaValidationError) | `suggestion=exception.suggestion or None` | `suggestions=[exception.suggestion] if exception.suggestion else None` |
| `diagnostic.py` | 550-558 (MarkdownParseError) | `suggestion=exception.suggestion` | `suggestions=[exception.suggestion] if exception.suggestion else None` |
| `diagnostic.py` | 565-577 (WorkflowNotFoundError) | `suggestion=f"Did you mean: {', '.join(...)}"` | `suggestions=["Use 'pflow workflow list' to see all available workflows."]` |
| `diagnostic.py` | 596-603 (OutputResolutionError) | `suggestion="; ".join(exception.suggestions)` | `suggestions=exception.suggestions or None` |
| `diagnostic.py` | 607-620 (MCPError) | `suggestion="; ".join(exception.suggestions)` | `suggestions=exception.suggestions or None` |
| `diagnostic.py` | 624-637 (UserFriendlyError) | `suggestion="; ".join(exception.suggestions)` | `suggestions=exception.suggestions or None` |
| `executor_service.py` | 48-55 (build_error_list) | no suggestion | Add `title=_CATEGORY_TITLES.get(category, "Execution Failed")` |
| `workflow_executor.py` | 338-346 | `suggestion=d.suggestion` | `suggestions=d.suggestions` |
| `runner.py` | 294-301 | no suggestion | no change needed (stays None) |
| `runner.py` | 477-485 | `suggestion="Inspect..."` | `suggestions=["Inspect..."]` |
| `runner.py` | 489-499 | `suggestion="Fix unresolved..."` | `suggestions=["Fix unresolved..."]` |
| `path_validation.py` | 181-192 | `suggestion="Ensure the value..."` | `suggestions=["Ensure the value..."]` |
| `path_validation.py` | 295-305 | `suggestion="Ensure the value..."` | `suggestions=["Ensure the value..."]` |
| `markdown_parser.py` | 432-441 | `suggestion="Move content..."` | `suggestions=["Move content..."]` |
| `markdown_parser.py` | 580-586 | `suggestion=f"Rename to..."` | `suggestions=[f"Rename to..."]` |
| `validator.py` | 30-38 | `suggestion=w.suggestion` + manual field copy | Use `dataclasses.replace(w, message=..., node_id=...)` — preserves ALL fields including `title` |
| `validator.py` | 865-876 | `suggestion="Add '- cache: false'..."` | `suggestions=["Add '- cache: false'..."]` |
| `workflow_executor.py` | 338-346 | `suggestion=d.suggestion` + manual field copy | Use `dataclasses.replace(d, message=..., node_id=...)` — preserves ALL fields including `title` |

**Use `dataclasses.replace()` for Diagnostic provenance cloning** (validator.py:30-38 and workflow_executor.py:338-346). These sites currently construct new Diagnostics by manually copying fields. They don't copy `title` (it didn't exist before). Using `replace()` preserves all fields automatically — future-proof against any new field additions.

Also add `title=` to the 3 UserFriendlyError/MCPError/OutputResolutionError branches AND remove `"title"` and `"suggestions"` from their context dicts (these move to fields).

**Test files (10 sites):** Same mechanical rename. See search agent results for exact lines.

### Step 1f: Fix ALL `.suggestion` reads

Every `diagnostic.suggestion` → `diagnostic.suggestions`.
Every `if diagnostic.suggestion:` → `if diagnostic.suggestions:`.

**Production reads (10 sites in `diagnostic.py`):**

| Line | Current | New |
|------|---------|-----|
| 53-54 | `if self.suggestion is not None: result["suggestion"] = self.suggestion` | `if self.suggestions is not None: result["suggestions"] = self.suggestions` |
| 102 | `_KNOWN_FIELDS` with `"suggestion"` | `"suggestions"` |
| 144-145 | `if diagnostic.suggestion: line += f"\n    → {diagnostic.suggestion}"` | `if diagnostic.suggestions: line += f"\n    → {diagnostic.suggestions[0]}"` |
| 206-207 | `if diagnostic.suggestion: lines.append(f"   👉 {diagnostic.suggestion}")` | `if diagnostic.suggestions: lines.append(f"   👉 {diagnostic.suggestions[0]}")` |
| 236-237 | `if diagnostic.suggestion: return f"✗ ... → {diagnostic.suggestion}"` | `if diagnostic.suggestions: return f"✗ ... → {diagnostic.suggestions[0]}"` |
| 273-275 | `if diagnostic.suggestion: ... f"  Suggestion: {diagnostic.suggestion}"` | `if diagnostic.suggestions: ... f"  Suggestion: {diagnostic.suggestions[0]}"` |
| 349-350 | `elif diagnostic.suggestion: lines.append(f"\n{diagnostic.suggestion}")` | `elif diagnostic.suggestions: lines.append(f"\n{diagnostic.suggestions[0]}")` |
| 370-371 | `if not suggestions and diagnostic.suggestion: suggestions = [diagnostic.suggestion]` | `if not suggestions and diagnostic.suggestions: suggestions = diagnostic.suggestions` |

**Propagation reads:**
| File | Line | Current | New |
|------|------|---------|-----|
| `validator.py` | 33 | `suggestion=w.suggestion` | `suggestions=w.suggestions` |
| `workflow_executor.py` | 341 | `suggestion=d.suggestion` | `suggestions=d.suggestions` |

**Test reads (~10 sites):** Change `diagnostic.suggestion` → `diagnostic.suggestions` and adjust assertions. E.g., `assert d.suggestion == "Fix it"` → `assert d.suggestions == ["Fix it"]`.

**Serialized dict reads** (tests that read `result["suggestion"]`): Change to `result["suggestions"]`. See test impact list.

**Verification**: `make check` should pass (all mypy errors resolved). Run `make test` — many tests will fail from assertion changes; fix each to match new field name/type.

### Step 2: `to_diagnostics()` on Exception Classes

**Files**: `src/pflow/core/exceptions.py`, `src/pflow/core/user_errors.py`

**2a. Add imports to `exceptions.py`** (top of file):

```python
from pflow.core.diagnostic import Diagnostic, Severity
```

**2b. Add default `to_diagnostics()` to `PflowError`**:

```python
class PflowError(Exception):
    """Base exception for all pflow errors."""

    def to_diagnostics(self) -> list[Diagnostic]:
        """Convert to diagnostic representation. Override in subclasses for rich output."""
        return [Diagnostic(
            severity=Severity.ERROR,
            message=str(self),
            title="Error",
            source="unknown",
        )]
```

**2c. Add `to_diagnostics()` to each subclass.** The logic is MOVED from `exception_to_diagnostics()` branches. Each method contains the same conversion logic that's currently in the converter.

Implement on: `CompilationError`, `MaxNodeVisitsError`, `WorkflowValidationError`, `SchemaValidationError`, `MarkdownParseError`, `WorkflowNotFoundError`.

**Important for MaxNodeVisitsError**: `str(self)` embeds the suggestion in the message ("...Set PFLOW_MAX_NODE_VISITS..."). The `to_diagnostics()` method must construct the message from `self.node_id`, `self.visit_count`, `self.max_visits` WITHOUT the suggestion tail, or the suggestion appears twice (in message AND as a separate suggestion). Use: `f"Node '{self.node_id}' exceeded maximum visits ({self.visit_count}/{self.max_visits}). This likely indicates an infinite loop in the workflow."`

**2d. Add `raw_message` to `MarkdownParseError.__init__`:**

```python
def __init__(self, message, line=None, suggestion=None):
    self.raw_message = message  # ADD THIS LINE
    self.line = line
    ...
```

**2e. Add imports + `to_diagnostics()` to `user_errors.py`:**

```python
from pflow.core.diagnostic import Diagnostic, Severity
```

Add to `UserFriendlyError` (base implementation), `MCPError` (category override via `_diagnostic_category`), `OutputResolutionError` (full override with failures).

**2f. Rewrite `exception_to_diagnostics()` in `diagnostic.py`** as thin dispatcher (~20 lines). Delete the 13 isinstance branches. Delete the 7 lazy imports.

Add `_builtin_exception_diagnostic()` for FileNotFoundError, PermissionError, ValueError, generic Exception (the 4 types that can't have `to_diagnostics()`).

Define `_CATEGORY_TITLES` as a module-level constant in `diagnostic.py` (the single definition point — also imported by `executor_service.py` for `build_error_list()`):
```python
_CATEGORY_TITLES: dict[str, str] = {
    "compilation": "Compilation Failed",
    "max_visits": "Infinite Loop Detected",
    "validation": "Validation Error",
    "parse_error": "Parse Error",
    "not_found": "Workflow Not Found",
    "file_not_found": "File Not Found",
    "permission_denied": "Permission Denied",
    "execution_failure": "Execution Failed",
    "api_validation": "API Validation Error",
    "template_error": "Template Error",
}
```

**Important for ValueError**: The current converter gives different categories based on `_pflow_node_id` annotation: annotated → `"execution_failure"`, unannotated → `"validation"`. The `_builtin_exception_diagnostic()` function MUST preserve this conditional logic. The annotated node_id is passed as a parameter.

Apply `_pflow_node_id` annotation via `dataclasses.replace()` after dispatch.

**Verification**: Run the existing `test_diagnostic.py::TestExceptionToDiagnostics` tests — they should produce identical output. These tests call `exception_to_diagnostics()` which now dispatches to `to_diagnostics()` internally.

### Step 3: One Rendering Format

**Files**: `src/pflow/core/diagnostic.py`

**3a. Replace `_format_error_diagnostic()`** with a single implementation:

```python
def _format_error_diagnostic(diagnostic, verbose, error_number=None):
    lines = []
    context = diagnostic.context or {}

    # 1. Title line
    title = diagnostic.title or "Error"
    prefix = f"Error {error_number}" if error_number else "Error"
    lines.append(f"{prefix}: {title}")
    lines.append("")

    # 2. Message
    lines.append(diagnostic.message)

    # 3. Location (At:)
    location = _format_location(diagnostic, context)
    if location:
        lines.append(f"  At: {location}")

    # 4. Context blocks (universal — called for ALL error types)
    context_lines = _format_all_context_blocks(diagnostic, context)
    if context_lines:
        lines.extend(context_lines)

    # 5. Suggestions
    suggestions = diagnostic.suggestions or []
    if suggestions:
        lines.append("")
        if len(suggestions) == 1:
            lines.append(f"  → {suggestions[0]}")
        else:
            lines.append("To fix this:")
            for i, s in enumerate(suggestions, 1):
                lines.append(f"  {i}. {s}")

    # 6. Verbose hint
    technical_details = context.get("technical_details")
    if verbose and technical_details:
        lines.append("")
        lines.append("Technical details:")
        lines.append(str(technical_details))
    elif technical_details:
        lines.append("")
        lines.append("Run with --verbose for technical details.")

    return "\n".join(lines)
```

**3b. Add `_format_location()`:**

```python
def _format_location(diagnostic, context):
    parts = []
    if diagnostic.node_id:
        parts.append(f"node '{diagnostic.node_id}'")
    if (path := context.get("path")) and path != "root":
        parts.append(path)
    if (line := context.get("line")) is not None:
        parts.append(f"line {line}")
    return ", ".join(parts) if parts else None
```

**3c. Add `_format_all_context_blocks()`** that calls ALL block renderers (existing + new):

Calls: `_format_compilation_context_lines` (existing — **update to also render `phase`**), `_format_shell_error_lines` (existing), `_format_api_response_lines` (existing), `_format_mcp_error_lines` (existing), `_format_template_error_lines` (existing), `_format_similar_names_block` (NEW), `_format_exception_type_line` (NEW).

**Update `_format_compilation_context_lines`**: Currently only renders `node_type` and `sub_workflow_path`. Add `phase` rendering:
```python
if phase := context.get("phase"):
    lines.append(f"  Phase: {phase}")
```
This was identified as one of the 8 silently dropped context keys in the gap analysis.

**3d. Add new block renderers:**

```python
def _format_similar_names_block(context):
    similar = context.get("similar_names")
    if not similar:
        return []
    lines = ["", "Did you mean one of these?"]
    for name in similar:
        lines.append(f"  - {name}")
    return lines

def _format_exception_type_line(context):
    if exc_type := context.get("exception_type"):
        return [f"  Type: {exc_type}"]
    return []
```

**3e. Delete old rendering functions:**
- `_format_validation_diagnostic`
- `_format_not_found_diagnostic`
- `_format_user_friendly_diagnostic`
- `_format_simple_error_diagnostic`
- `_format_runtime_error_diagnostic`
- `_format_runtime_error_header_lines`
- `_is_simple_error_diagnostic`

**3f. Update warning renderer** for `suggestions` field:

```python
# In _format_warning_or_info_diagnostic:
if diagnostic.suggestions:
    line += f"\n    → {diagnostic.suggestions[0]}"
```

**Verification**: Run `scratchpads/task-144-diagnostic-rendering/capture_baselines.py after` (update the script first for new field names). Compare outputs against `target-output-design.md`.

### Step 4: Data Flow Cleanup

**⚠️ Steps 4h-4k are tightly coupled** — `ValidationResult.errors` type change and its 3 consumers MUST be updated atomically. If the property returns `list[Diagnostic]` before consumers are updated, the CLI JSON output, text output, and MCP output all produce corrupt data silently (Diagnostic repr strings instead of messages). Implement 4h through 4k together before running `make test`.

**4a. Delete coerce functions** from `diagnostic.py`:
- `coerce_warning_diagnostic()` (line 92-94)
- `coerce_error_diagnostic()` (line 97-99)
- `_coerce_diagnostic()` (lines 105-119)
- `_KNOWN_FIELDS` constant (line 102)

**4b. Update `format_execution_success()`** in `success_formatter.py` (line 56-60):
Remove the coerce comprehension. Warnings are already `Diagnostic` objects (callers pass them directly). Replace `coerce_warning_diagnostic` import with nothing.

**4c. Update `format_success_as_text()`** in `success_formatter.py`:
Add `warning_diagnostics: list[Diagnostic] | None = None` parameter. Use it instead of extracting from `success_dict["warnings"]` and coercing. Update the warnings rendering section (lines 244-249).

**4d. Update `_display_execution_summary()`** in `workflow_output.py`:
Add `warning_diagnostics: list[Diagnostic] | None = None` parameter. Use it for warning rendering instead of `formatted_result.get("warnings", [])` + coerce. Update call site in `_handle_text_output()` (line 135) to pass warnings separately.

**4e. Update `_display_single_error()`** in `workflow_errors.py`:
Remove `coerce_error_diagnostic(error)` call (line 40). Accept `Diagnostic` directly (remove `dict[str, Any]` from type union). Remove the header lines (43-49) — title now comes from `format_diagnostic()`.

**4f. Simplify `_collect_warning_diagnostics()`** in `workflow_errors.py`:
Remove the legacy `getattr(result, "warnings", [])` fallback path (lines 106-109). Only read from `result.diagnostics`.

**4g. Update `_build_error_text()`** in `execution_service.py`:
Change to receive `errors: list[Diagnostic], warnings: list[Diagnostic], trace_path: str` directly instead of `error_dict: dict[str, Any]`. Update caller (`execute_workflow` at line 258) to pass Diagnostics directly. Header uses `errors[0].title` for single error.

**4h. `ValidationResult.errors` → `list[Diagnostic]`** in `result.py`:
```python
@property
def errors(self) -> list[Diagnostic]:
    """Validation errors as diagnostics."""
    return [d for d in self.diagnostics if d.severity == Severity.ERROR]
```

Do NOT add an `error_messages` property — no caller needs it. YAGNI. If someone needs string messages later, `[d.message for d in vresult.errors]` is trivial.

**4i. Update `_display_validation_result()`** in `main.py` (lines 394-437):
- JSON mode: use `d.to_display_dict()` for errors (not `to_dict()`) — `to_display_dict()` flattens context to top level, keeping `"category"` as a top-level key for consistency with the `"warnings"` array which already uses `to_display_dict()`.
- Text mode: pass `vresult.errors` (now `list[Diagnostic]`) to `format_validation_failure()`

**4j. Redesign `format_validation_failure()`** in `validation_formatter.py`:
Change signature to `format_validation_failure(errors: list[Diagnostic]) -> str`. Compact numbered format with per-error path and suggestion. Truncation at 5.

**4k. Update MCP `validate_workflow()`** in `execution_service.py` (line 297):
Pass `vresult.errors` (now `list[Diagnostic]`) to `format_validation_failure()`.

**Verification**: `make test` — fix broken assertions. Every updated assertion should produce better output than before.

### Step 5: Bypass Elimination

**5a. Delete `registry_run_formatter.py`** entirely.

**5b. Update `registry_run.py`** error handlers:
- `_handle_unknown_node()`: Construct `Diagnostic(title="Node Not Found", ...)` directly, call `format_diagnostic()`, `click.echo`, `sys.exit(1)`.
- `_handle_ambiguous_node()`: Construct `Diagnostic(title="Ambiguous Node Name", ...)` directly.
- `_handle_execution_error()`: Call `exception_to_diagnostics(exc)` + `format_diagnostic()` for each.
- `_execute_and_display_results()` MCPError branch (line 283-288): Unchanged (already uses diagnostic pipeline).
- Generic except branch (line 289-292): Use `exception_to_diagnostics()` + `format_diagnostic()`.

**5c. Update MCP `run_registry_node()`** in `execution_service.py`:
- Not-found (line 478-481): Construct Diagnostic directly, return `format_diagnostic()` text.
- Runner failure (line 562-567): Use `exception_to_diagnostics()` + `format_diagnostic()` directly. Remove double-formatting.
- Exception (line 569-573): Same.
- Remove all `format_execution_error`, `format_node_not_found_error` imports.

**5d. Remove `error_output.py` special cases** (lines 160-165):
Delete the `UnicodeDecodeError` and `RuntimeError` special cases. Let them fall through to `exception_to_diagnostics()` + `format_diagnostic()`.

**5e. Fix `workflow_output.py:258-259`**:
Replace raw `click.echo(f"Warning: {e.title}\n{e.explanation}", err=True)` with `exception_to_diagnostics(e)` + `format_diagnostic()`.

**Verification**: `make test` — registry run tests and MCP tests should pass with updated assertions.

### Step 6: Update Baseline Capture Script + Final Verification

**6a. Update `capture_baselines.py`:**
- Change all `suggestion=` to `suggestions=[]` in fixtures
- Add `title=` to fixtures where applicable
- Update wrapper function calls for new signatures

**6b. Capture after-baselines:**
```bash
uv run python scratchpads/task-144-diagnostic-rendering/capture_baselines.py after
uv run python scratchpads/task-144-diagnostic-rendering/capture_baselines.py compare
```

**6c. Score outputs** against `target-output-design.md`. Every output should match the target or be justified.

**6d. Final checks:**
```bash
make test
make check
```

All tests pass. All mypy/ruff clean. Context coverage improved from 76% toward ~95%+.

## Files Modified (complete list)

| # | File | Nature of change |
|---|------|-----------------|
| 1 | `src/pflow/core/diagnostic.py` | Type changes, delete coerce/rendering functions, thin dispatcher, new renderers |
| 2 | `src/pflow/core/exceptions.py` | Add `to_diagnostics()` to 7 classes, `raw_message` to MarkdownParseError, import Diagnostic |
| 3 | `src/pflow/core/user_errors.py` | Add `to_diagnostics()` to 3 classes, import Diagnostic |
| 4 | `src/pflow/execution/result.py` | `ValidationResult.errors` returns `list[Diagnostic]` (no `error_messages` property — YAGNI) |
| 5 | `src/pflow/execution/formatters/success_formatter.py` | Warning parameter change, field rename |
| 6 | `src/pflow/execution/formatters/validation_formatter.py` | Complete rewrite of `format_validation_failure()` |
| 7 | `src/pflow/execution/formatters/registry_run_formatter.py` | **DELETE** |
| 8 | `src/pflow/execution/formatters/error_formatter.py` | Field rename |
| 9 | `src/pflow/execution/executor_service.py` | Add `title=` to `build_error_list()`, field rename |
| 10 | `src/pflow/cli/workflow_output.py` | Warning parameter, fix OutputResolutionError bug |
| 11 | `src/pflow/cli/workflow_errors.py` | Simplify `_display_single_error`, remove coerce |
| 12 | `src/pflow/cli/error_output.py` | Remove special cases |
| 13 | `src/pflow/cli/main.py` | Update `_display_validation_result` |
| 14 | `src/pflow/cli/commands/registry_run.py` | Replace error handlers with diagnostic pipeline |
| 15 | `src/pflow/mcp_server/services/execution_service.py` | `_build_error_text` signature, `run_registry_node` bypass elimination |
| 16 | `src/pflow/core/workflow/validator.py` | Field rename in Diagnostic constructors |
| 17 | `src/pflow/core/markdown_parser.py` | Field rename in Diagnostic constructors |
| 18 | `src/pflow/runtime/engine/engine.py` | Field rename (if any Diagnostic constructors exist) |
| 19 | `src/pflow/runtime/workflow_executor.py` | Field rename in propagation |
| 20 | `src/pflow/runtime/template_validation/path_validation.py` | Field rename |
| 21 | `src/pflow/execution/runner.py` | Field rename, remove lazy imports if unused |
| 22 | `scratchpads/task-144-diagnostic-rendering/capture_baselines.py` | Update for new fields |

**Test files that need updates** (~60-80 assertions across ~20 files):

Field rename (`.suggestion` → `.suggestions`, `["suggestion"]` → `["suggestions"]`):
- `tests/test_core/test_diagnostic.py` — HEAVY: field rename + coerce test deletion (11 tests) + rendering assertion updates
- `tests/test_execution/test_runner.py` — `.suggestion` → `.suggestions` assertions (3 tests)
- `tests/test_execution/formatters/test_success_formatter.py` — field rename + `["suggestion"]` dict key
- `tests/test_execution/test_workflow_execution.py` — `.suggestion` assertion
- `tests/test_runtime/test_template_validation/test_warnings.py` — field rename
- `tests/test_runtime/test_workflow_trace.py` — field rename
- `tests/test_mcp_server/test_mcp_warnings.py` — field rename
- `tests/test_cli/test_unified_error_output.py` — `["suggestion"]` → `["suggestions"]` dict keys (2 tests)
- `tests/test_cli/test_validate_only.py` — `["suggestion"]` → `["suggestions"]` dict key

Rendering format changes (error text assertions):
- `tests/test_cli/test_agent_ux_fixes.py` — `"Error at node 'X':"` format + needs data construction rewrites (dict → Diagnostic)
- `tests/test_mcp_server/test_registry_run_mcp.py` — rendering format assertions
- `tests/test_mcp_server/test_validation_service.py` — `"✗"` prefix assertions (6 tests)
- `tests/test_cli/test_shell_stderr_display.py` — rendering format assertions
- `tests/test_execution/formatters/test_validation_formatter.py` — complete rewrite (new signature, 12 tests)

Rendering format changes (discovered by review agents — `"❌"` and header assertions):
- `tests/test_mcp_server/test_registry_run_errors.py` — `"❌"` assertions after formatter deletion (2 tests)
- `tests/test_integration/test_e2e_workflow.py` — `"Workflow execution failed"` header assertions (3 sites)
- `tests/test_nodes/test_shell_smart_handling.py` — `"Workflow failed"` header assertions (4 sites)
- `tests/test_cli/test_dual_mode_stdin.py` — `"❌"` assertion (1 site)
- `tests/test_cli/test_workflow_resolution.py` — `"❌"` assertion (1 site)
- `tests/test_cli/test_workflow_commands.py` — exact-match not-found assertions (2 sites)
- `tests/test_cli/test_registry_run.py` — `"not found in registry"` assertions (2 sites)

**Exception `.suggestion` attribute on exception classes is NOT renamed.** Tests that assert `exc.suggestion` on exception objects (test_exception_hierarchy.py, test_ir_schema.py, test_markdown_parser.py, test_compiler_basic.py, etc.) are NOT affected.

## Verification Strategy

1. After Step 1: `make check` passes (all mypy errors resolved). The `__post_init__` guard catches any `suggestions="string"` mistakes.
2. After Step 2: Existing `test_diagnostic.py::TestExceptionToDiagnostics` tests pass (same output through new dispatcher). **Run `/code-review` here** — this is the highest-risk step (changes foundation type + adds methods to exception hierarchy).
3. After Step 3: Baseline capture matches target output design.
4. After Step 4: `make test` passes (with assertion updates). Steps 4h-4k implemented atomically.
5. After Step 5: `make test` passes (registry run + MCP tests updated).
6. **Manual testing** (after Step 5):
   - Run a workflow with a real shell error → verify shell context blocks render in new format
   - Run `pflow --validate-only` on an invalid workflow → verify new validation failure format
   - Run `pflow registry run nonexistent-node` → verify registry bypass elimination works
   - Run a nonexistent saved workflow name → verify not-found format with similar names
7. **Update CLAUDE.md files**: `src/pflow/core/CLAUDE.md`, `src/pflow/execution/CLAUDE.md`, `src/pflow/execution/formatters/CLAUDE.md`, `src/pflow/cli/CLAUDE.md` — stale references to coerce functions, registry_run_formatter.py, 6 rendering paths, ValidationResult.errors type.
8. Final: `make test && make check` clean. Baseline comparison shows improvement. Context coverage ≥ 95%.
