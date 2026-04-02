# Task 143: Implementation Reference

Research document for the implementing agent. Contains exact current code, data flows, import analysis, and conversion mappings that are NOT in the task spec.

**State**: After PR #216 (cache opt-out + ValidationWarning slim-down) and PR #217 (duplicate section detection) merged to main. Commit `159b156e`.

---

## 1. Import Graph — Circular Import Analysis

**Verdict: `src/pflow/core/diagnostic.py` creates ZERO circular import risk.**

The import direction is strictly layered:

```
core/ (leaf)
  ↓ consumed by
runtime/, execution/
  ↓ consumed by
cli/, mcp_server/
```

`diagnostic.py` sits at the `core/` layer alongside `exceptions.py`. It must only import from stdlib and leaf `core/` modules. Every file that needs Diagnostic imports downward from it — same pattern as `PflowError`.

**Bonus**: The current `ValidationWarning` lives in `runtime/template_validation/utils.py`, which means `core/workflow/validator.py` imports *across* the `core/` → `runtime/` boundary. Moving the type to `core/diagnostic.py` **fixes** this layering violation.

### Per-file pflow imports (only the modules that will change)

| File | Imports from pflow.* |
|------|---------------------|
| `core/markdown_parser.py` | `core.exceptions`, `core.suggestion_utils` |
| `core/workflow/validator.py` | `core.exceptions`, `registry`, `runtime.template_resolver`, `runtime.template_validation` (ValidationWarning) |
| `runtime/template_validation/utils.py` | Nothing (pure leaf) |
| `runtime/template_validation/path_validation.py` | `registry`, `runtime.template_validation.utils` |
| `execution/runner.py` | `core.exceptions` (6 types), `core.workflow.manager`, `core.workflow.status` |
| `execution/result.py` | `core.workflow.status` |
| `execution/executor_service.py` | Nothing top-level; lazy `runtime.template_validation` |
| `cli/main.py` | Many (see full list in research agents) |
| `cli/error_output.py` | `core.exceptions` (5 types), `core.user_errors` (3 types) |
| `cli/workflow_errors.py` | Nothing top-level; lazy `core.security_utils` |
| `cli/workflow_output.py` | Nothing top-level; lazy `execution.formatters.*`, `core.user_errors` |
| `mcp_server/services/execution_service.py` | `core.exceptions` (3 types), `core.workflow.manager`, `execution.workflow_resolver`, `registry` |
| `execution/formatters/success_formatter.py` | `core.workflow.status` |
| `execution/formatters/error_formatter.py` | `execution.execution_state`, `execution.result` |

---

## 2. Current Code at Each Change Site

### 2.1 ExecutionResult and ValidationResult — `execution/result.py`

```python
@dataclass
class ValidationResult:
    """Result of runner.validate()."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    # warnings shape: {"node_id": str, "message": str, "template": str | None}

@dataclass
class ExecutionResult:
    """Result of workflow execution."""
    success: bool
    status: WorkflowStatus = WorkflowStatus.SUCCESS
    shared_after: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    validation_warnings: list[dict[str, Any]] = field(default_factory=list)
    trace: Optional[Any] = None
    metrics: Optional[Any] = None
```

### 2.2 ValidationWarning — `runtime/template_validation/utils.py:23-33`

```python
@dataclass
class ValidationWarning:
    """Pre-execution warning about a node or template."""
    node_id: str
    message: str
    template: str | None = None
```

Also in this file: `MAX_DISPLAYED_FIELDS = 20`, `MAX_DISPLAYED_SUGGESTIONS = 3`, `MAX_FLATTEN_DEPTH = 5`, plus utility functions (`split_template_path`, `get_node_ids`, `sanitize_for_display`, `flatten_output_structure`, `find_similar_paths`, `build_paths_from_entries`). These utilities stay — only `ValidationWarning` is replaced.

### 2.3 Warning Conversion + Dedup — `execution/runner.py:604-625`

```python
@staticmethod
def _warning_to_dict(warning: Any) -> dict[str, Any]:
    """Convert ValidationWarning to agent-facing dict."""
    if isinstance(warning, dict):
        return warning
    return {
        "node_id": getattr(warning, "node_id", None),
        "template": getattr(warning, "template", None),
        "message": getattr(warning, "message", str(warning)),
    }

@staticmethod
def _deduplicate_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate validation warnings by (node_id, template)."""
    seen: set[tuple[str | None, str | None]] = set()
    result: list[dict[str, Any]] = []
    for w in warnings:
        key = (w.get("node_id"), w.get("template"))
        if key not in seen:
            seen.add(key)
            result.append(w)
    return result
```

**Both deleted** — Diagnostic is the type everywhere, dedup uses `__hash__`.

### 2.4 Runtime Warning Extraction — `execution/runner.py:438-450`

```python
def _extract_runtime_warnings(self, shared_store: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract runtime warnings from shared store."""
    warnings: list[dict[str, Any]] = []
    for node_id, message in shared_store.get("__warnings__", {}).items():
        warnings.append({"node_id": node_id, "type": "api_warning", "message": message})
    for node_id, error_data in shared_store.get("__template_errors__", {}).items():
        warnings.append({
            "node_id": node_id,
            "type": "template_resolution",
            "message": error_data.get("message", "Template resolution failed"),
            "unresolved_templates": error_data.get("unresolved", []),
        })
    return warnings
```

**Changes to**: emit `Diagnostic(severity=WARNING, source="runtime", ...)` directly. The `"type"` key maps to a more specific `source` or goes into context. `"unresolved_templates"` goes into context.

**Note**: runtime warnings need `suggestion` fields added for agent actionability. Current warnings have none.

### 2.5 Success Path — ExecutionResult Construction — `execution/runner.py:223-232`

```python
return ExecutionResult(
    success=success,
    status=status,
    shared_after=shared_store,
    errors=errors,
    warnings=runtime_warnings,
    validation_warnings=self._deduplicate_warnings(
        [self._warning_to_dict(w) for w in validation_warnings]
    ),
    trace=trace_collector,
    metrics=metrics_collector,
)
```

**Changes to**: single `diagnostics` list combining errors + runtime warnings + validation warnings.

### 2.6 Exception-to-Result — `execution/runner.py:485-584`

Full type dispatch. Each branch builds an error dict with different keys:

| Exception type | Dict keys produced |
|---------------|-------------------|
| `CompilationError` | `source`, `category`, `message`, `phase`, `node_id`, `node_type`, `suggestion`, `sub_workflow_path` |
| `MaxNodeVisitsError` | `source`, `category`, `node_id`, `visit_count`, `max_visits` |
| `WorkflowValidationError` | `source`, `category`, `message`, `validation_errors`, `path`?, `suggestion`? |
| `SchemaValidationError` | `source`, `category`, `path`?, `suggestion`? |
| `MarkdownParseError` | `category`, `line`?, `suggestion`?, `node_id`? (from annotation) |
| `WorkflowNotFoundError` | `category`, `similar_names` |
| `ValueError` (annotated) | `category`, `node_id` |
| `ValueError` (unannotated) | `category` |
| Everything else | `category`, `exception_type`, `node_id`? (from annotation) |

All branches start with `error_dict = {"source": "runtime", "message": str(exception)}` then `.update()`.

**Key detail**: `_pflow_node_id` annotation. The engine annotates exceptions with the failing node ID at `runner.py:211-214`:
```python
failed_node = shared_store.get("__execution__", {}).get("failed_node")
if failed_node and not hasattr(e, "_pflow_node_id"):
    e._pflow_node_id = failed_node
```

The shared `exception_to_diagnostics()` utility needs to handle this annotation.

### 2.7 Runtime Error Extraction — `execution/executor_service.py:16-48`

```python
def build_error_list(success, action_result, shared_store):
    if success:
        return []
    error_info = _extract_error_info(action_result, shared_store)
    category = determine_error_category(error_info["message"] or "")
    error = {
        "source": "runtime",
        "category": category,
        "message": error_info["message"],
        "action": action_result,
        "node_id": error_info["failed_node"],
    }
    failed_node = error_info.get("failed_node")
    if failed_node:
        node_output = shared_store.get(failed_node, {})
        if isinstance(node_output, dict):
            _enrich_error_from_node_output(error, node_output, category)
    return [error]
```

### 2.8 Error Enrichment — `execution/executor_service.py:181-222`

Enrichment fields added to error dict by node type:

| Node type | Fields added |
|-----------|-------------|
| HTTP | `status_code`, `raw_response`, `response_headers`, `response_time` |
| MCP | `mcp_error_details`, `mcp_error` |
| Shell | `shell_command`, `shell_exit_code`, `shell_stdout`, `shell_stderr` |
| Template error | `available_fields`, `available_fields_total`, `available_fields_truncated`, `trace_file_hint` |

All these go into `Diagnostic.context`.

---

## 3. CLI Error Output — Two Parallel Conversion Paths

### Path A: Exception (pre-runner) — `cli/error_output.py`

`_exception_to_errors()` at line 151 — dispatches by type to converter functions:

```
WorkflowValidationError → _workflow_validation_to_errors()
WorkflowNotFoundError   → _workflow_not_found_to_errors()
MCPError                → _mcp_error_to_errors()
OutputResolutionError   → _output_resolution_to_errors()
UserFriendlyError       → _user_friendly_to_errors()
MaxNodeVisitsError      → inline dict
MarkdownParseError      → _markdown_parse_to_errors()
SchemaValidationError   → _schema_validation_to_errors()
FileNotFoundError       → inline dict
PermissionError         → inline dict
fallback                → inline dict
```

Returns `(summary_string, errors_list)`. The `summary_string` is used as the top-level `"error"` field in JSON.

**This whole dispatch is replaced by `exception_to_diagnostics()`.**

### Path B: ExecutionResult (post-runner) — `cli/error_output.py:49-111`

`_format_from_result()` calls `format_execution_errors()` (from `error_formatter.py`) then wraps the result in the JSON output shape. Error dicts already built by the runner.

### Text mode dispatch — `cli/error_output.py:271-294`

`display_exception_text()` checks for `format_for_cli()` method:

```python
if isinstance(exception, UserFriendlyError):
    click.echo(exception.format_for_cli(verbose), err=True)
elif isinstance(exception, (WorkflowNotFoundError, WorkflowValidationError)) or \
     hasattr(exception, "format_for_cli"):
    click.echo(exception.format_for_cli(), err=True)
elif isinstance(exception, PermissionError):
    click.echo(f"✗ {msg}", err=True)
elif isinstance(exception, (FileNotFoundError, MarkdownParseError)):
    click.echo(f"✗ {exception}", err=True)
# ... etc
```

**Replaced by**: convert exception to Diagnostics, render each via `format_diagnostic()`.

---

## 4. format_for_cli() Method Outputs

These produce the text the implementing agent must replicate via Diagnostic → `format_diagnostic()`:

### WorkflowNotFoundError.format_for_cli()

```
❌ Workflow 'my-workflow' not found.

Did you mean one of these?
  - my-wf
  - my-workflow-v2

(or if no similar names:)

❌ Workflow 'my-workflow' not found.

Use 'pflow workflow list' to see available workflows.
```

### WorkflowValidationError.format_for_cli()

```
❌ Unknown node type 'shel'
   At: nodes[0].type
   👉 Did you mean 'shell'?
❌ Missing required input 'api_key'
```

Each validation error is rendered separately. Tuples get `At:` path and `👉` suggestion. Plain strings are passed through.

### UserFriendlyError.format_for_cli(verbose)

```
Error: API key not configured

The LLM node requires an API key to communicate with the model provider.

To fix this:
  1. Run pflow settings set-env ANTHROPIC_API_KEY <your-key>
  2. Or export ANTHROPIC_API_KEY=<your-key>

Run with --verbose for technical details.
```

**Note**: Only `UserFriendlyError.format_for_cli` takes a `verbose` parameter.

### MaxNodeVisitsError.format_for_cli()

```
❌ Node 'loop-step' exceeded maximum visits (101/100). This likely indicates an infinite loop...
```

Just delegates to `__str__()`.

---

## 5. Warning Display Formats (Current)

### Execution summary warnings (CLI text + MCP text — identical format)

`workflow_output.py:583-597` and `success_formatter.py:235-250`:

```
⚠️ Warnings:
  • get-branch (warning):
    Shell node has no pflow template inputs — cached results will persist across runs
  • fetch (template_resolution):
    Template resolution failed for ${api.response}
```

Format: `• {node_id} ({type}):` then indented message lines. `type` defaults to `"warning"` when absent.

### Validation warnings (CLI text + MCP text — identical format)

`main.py:410-417` and `execution_service.py:271-277`:

```
  ⚠ [fetch] ${fetch.stdout.nested_field}: Nested access on 'str' requires valid JSON
  ⚠ [get-branch] Shell node has no pflow template inputs — cached results will persist
```

Format: `⚠ [{node_id}] {template}: {message}` (with template) or `⚠ [{node_id}] {message}` (without).

### Status line — `workflow_output.py:475-503`

```
✓ Workflow completed in 0.150s (2 cached, 3 executed)
⚠️ Workflow completed with warnings in 0.150s
⚠️ Workflow completed in 0.150s          ← when has_stderr_warnings
❌ Workflow failed after 0.150s
```

---

## 6. MCP Error Path

### _format_error_result() → _build_error_text() → raise RuntimeError

MCP errors are text strings raised as exceptions (FastMCP constraint):

```
❌ Field 'title' required

Error details:
  • fetch-data: Field 'title' required
    Command: curl -X POST...
    Stderr: connection refused...

Trace: /Users/.../.pflow/debug/workflow-trace-20260402-123456.json
```

`_build_error_text()` shows max 3 errors, truncates shell command at 200 chars, stderr at 300 chars. Trace path only shown if file exists.

`_format_error_result()` calls `format_execution_errors(sanitize=True)` then builds an intermediate dict with both `error` (first error promoted) and `errors` (full list). The intermediate dict is never returned to agents — only `_build_error_text()` consumes it.

---

## 7. Error Formatter (Stays, Changes Input Type)

`execution/formatters/error_formatter.py` — `format_execution_errors()`:

1. Deep-copies errors (data integrity)
2. Sanitizes `raw_response`, `response_headers` via `sanitize_parameters()`
3. Builds `checkpoint` from `shared_after`
4. Builds `execution` state (per-node steps with status, timing, cache)
5. Adds metrics

Returns:
```python
{
    "errors": [...],          # sanitized error list
    "checkpoint": {...},       # from shared_after
    "execution": {...},        # steps, timings
    "metrics": {...},          # from metrics_collector
}
```

With Diagnostic: `errors` becomes serialized Diagnostics. Sanitization applies to `diagnostic.context` fields. `checkpoint`, `execution`, `metrics` are execution metadata — they stay as dict fields outside the diagnostics list.

---

## 8. Validation Pipeline

### WorkflowValidator.validate() — `core/workflow/validator.py:27-120`

Returns `(errors: list[str], warnings: list[ValidationWarning])`.

Validation steps that produce warnings:
- Step 6: `_validate_templates()` → calls `validate_workflow_templates()` → returns `(template_errors, template_warnings)` where warnings are `ValidationWarning` objects
- Step 9: Cache lint → appends `ValidationWarning` for shell nodes with no template inputs

### Runner.validate() — `execution/runner.py:234-313`

Builds `ValidationResult`:
```python
ValidationResult(
    valid=len(errors) == 0,
    errors=errors,
    warnings=[self._warning_to_dict(w) for w in warnings],
)
```

Also generates suggestions via `generate_validation_suggestions(errors)` which are currently displayed separately (not part of warnings).

### Runner._validate() — `execution/runner.py:344-363`

Called during execution (not validate-only). Returns `list[ValidationWarning]`. These flow to `_compile_and_execute` as `validation_warnings` parameter.

---

## 9. Parser Warning Sites

### Site 1: Near-miss section names — `markdown_parser.py:311`

Generated by `_resolve_section()` at line 563:
```python
# Inside _resolve_section():
warning = f"Line {line_num}: '## {section_name}' looks like a typo — did you mean '## {canonical}'?"
return _SectionType.UNKNOWN, False, warning
```

Currently a plain string appended to `warnings: list[str]`.

### Site 2: Orphaned content — `markdown_parser.py:421-424`

```python
if entity_count > 0:
    orphan_lines_str = ", ".join(str(ln) for ln in sorted(lines_in_section))
    warnings.append(
        f"Unparsed content in '{display}' section (lines {orphan_lines_str}). "
        f"Content before the first ### heading is not captured."
    )
```

Currently a plain string. Zero entities → `MarkdownParseError` (not a warning).

### MarkdownParseResult — `markdown_parser.py:45-50`

```python
@dataclass
class MarkdownParseResult:
    ir: dict[str, Any]
    title: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None
    source: str = ""
    warnings: list[str] = field(default_factory=list)
```

`warnings` changes to `list[Diagnostic]`.

### Call sites that need threading (5 of 13)

| # | File:Line | Context | What to thread |
|---|-----------|---------|---------------|
| 1 | `execution/workflow_resolver.py:126` | `_try_load_from_file()` | Parser diagnostics → `ResolvedWorkflow.diagnostics` |
| 2 | `execution/workflow_resolver.py:169` | `_parse_markdown_content()` | Parser diagnostics → `ResolvedWorkflow.diagnostics` |
| 3 | `runtime/workflow_executor.py:441` | `_load_child_workflow()` | Sub-workflow parser diagnostics → parent execution |
| 4 | `core/workflow/validator.py:761` | `_resolve_child_workflow()` | Sub-workflow parser diagnostics → validation warnings |
| 5 | `runtime/template_validation/validator.py:515` | `_resolve_child_workflow_outputs()` | Sub-workflow parser diagnostics → template validation |

### Call sites that DON'T need threading (8 of 13)

| # | File:Line | Why not |
|---|-----------|---------|
| 6 | `core/workflow/save_service.py:185` | Save validation — noise |
| 7 | `core/workflow/save_service.py:282` | Dependency bundling — internal |
| 8 | `core/workflow/save_service.py:330` | File reference check — internal |
| 9 | `core/workflow/manager.py:296` | Library load — noise during list |
| 10 | `core/workflow/manager.py:358` | Library list — noise |
| 11 | `core/workflow/dependency_discovery.py:114` | Dependency discovery — internal |
| 12 | `mcp_server/services/execution_service.py:334` | MCP save — internal |
| 13 | `cli/commands/workflow.py:254` | CLI workflow commands — internal |

---

## 10. Test Files Requiring Updates

### Tier 1 — Structural changes (dict keys/shapes)

| File | Tests | What they assert |
|------|-------|-----------------|
| `tests/test_runtime/test_template_validation/test_warnings.py` | 7 | `warning.node_id`, `warning.message`, `warning.template` on ValidationWarning dataclass |
| `tests/test_mcp_server/test_mcp_warnings.py` | 4 | `warning["node_id"]`, `warning["template"]`, `warning["message"]` on warning dicts |
| `tests/test_execution/formatters/test_error_formatter.py` | 16 | `formatted["errors"][N]["key"]`, `formatted["checkpoint"]`, `formatted["execution"]["steps"]` |
| `tests/test_execution/test_workflow_execution.py` | 1 | `error["source"]`, `["category"]`, `["phase"]`, `["node_id"]`, `["node_type"]`, `["suggestion"]` |
| `tests/test_execution/test_runner.py` | 1 | `error["category"]`, `error["node_id"]` |
| `tests/test_integration/test_template_resolution_hardening.py` | 5 | `error["message"]` content (substrings) |
| `tests/test_cli/test_dual_mode_stdin.py` | 1 | `error["category"]` |

### Tier 2 — Text format (only if display strings change)

| File | Tests | What they assert |
|------|-------|-----------------|
| `tests/test_execution/formatters/test_success_formatter.py` | 30+ | `"✓ fetch (100ms)"`, `"⚠️ Warnings:"`, warning section format |
| `tests/test_execution/formatters/test_validation_formatter.py` | 13 | `"✓ Workflow is valid"`, `"✗ Static validation failed:"` |
| `tests/test_mcp_server/test_validation_service.py` | 8 | `startswith("✓")`, `startswith("✗")`, `"• "` bullets |
| `tests/test_mcp_server/test_registry_run_errors.py` | 8 | `"❌"`, `"not found"` |
| Various CLI tests | ~50 | Status indicators, error prefixes |

### Tier 3 — Substring only (low risk)

| File | Tests | What they assert |
|------|-------|-----------------|
| `tests/test_integration/test_e2e_workflow.py` | 4 | `"Workflow completed"` |
| `tests/test_integration/test_sigpipe_regression.py` | 5 | `"Workflow completed"` |
| `tests/test_core/test_markdown_parser.py` | 4 | `result.warnings` content (parser-level) |

---

## 11. Helper Functions in error_output.py (to be replaced)

The file has individual converter functions for each exception type. These are NOT documented in the task spec but the implementing agent needs to know they exist:

```
_workflow_validation_to_errors(exc) → (summary, errors_list)
_workflow_not_found_to_errors(exc) → (summary, errors_list)
_mcp_error_to_errors(exc) → (summary, errors_list)
_output_resolution_to_errors(exc) → (summary, errors_list)
_user_friendly_to_errors(exc) → (summary, errors_list)
_markdown_parse_to_errors(exc) → (summary, errors_list)
_schema_validation_to_errors(exc) → (summary, errors_list)
```

These all live between lines 190-270 of `error_output.py`. Each extracts structured fields from the specific exception type and builds error dicts. **All replaced by `exception_to_diagnostics()`.**

Read the full implementations at implementation time — some have nuanced field extraction (e.g., `OutputResolutionError` iterates `exc.failures` list, `MCPError` has default suggestions).

---

## 12. Gotchas and Edge Cases

### _pflow_node_id annotation
The engine annotates exceptions with the failing node's ID as a dynamic attribute (`e._pflow_node_id = failed_node`). The `exception_to_diagnostics()` utility must check `getattr(exc, "_pflow_node_id", None)` and use it as `node_id` for exceptions that don't carry their own (e.g., bare `ValueError`, unknown exceptions).

### Failure path omits some fields
The success path returns `ExecutionResult` with all 8 fields. The failure path (`_exception_to_result`) returns only `success`, `status`, `errors`, `validation_warnings`, `trace` — omitting `shared_after`, `warnings` (runtime), and `metrics`. With unified `diagnostics`, the failure path would include validation warnings as diagnostics but not runtime warnings (since execution didn't complete).

### ValidationResult.suggestions
`generate_validation_suggestions()` in `core/validation_utils.py` produces suggestions as `list[str]`. These are currently displayed separately from errors and warnings. With unified diagnostics, they become `Diagnostic(severity=INFO)`. The generator needs to be updated to produce Diagnostics or a wrapper function converts the strings.

### Trace collector set_warnings
At `runner.py:228`:
```python
trace_collector = shared_store.get("_trace_collector", trace_collector)
if trace_collector:
    trace_collector.set_warnings(runtime_warnings)
```
The trace collector receives runtime warnings. This interface needs to accept `list[Diagnostic]` or the warnings need to be converted for the trace.

### MCP _format_error_result promotes first error
At `execution_service.py:107-115`, the first error's fields are spread into the top-level `error` dict. With Diagnostic, this becomes `diagnostic.context` fields being spread. Same pattern, different access.

### Error category determines display header
In `workflow_errors.py:68-69`:
```python
header = "❌ Compilation failed" if category == "compilation" else "❌ Workflow execution failed"
```
With Diagnostic, `category` is in `context`. The display code needs `diagnostic.context.get("category") == "compilation"`.

### Sanitization happens in format_execution_errors
`error_formatter.py` deep-copies errors then sanitizes `raw_response` and `response_headers`. With Diagnostic, it deep-copies `diagnostic.context` and sanitizes the sensitive fields within it. The Diagnostic object itself is not mutated (context is copied).

### _exception_to_errors returns (summary, errors_list)
The summary string is used as the top-level `"error"` field in JSON output. With Diagnostic, the summary needs to be derived differently — either from the first diagnostic's message or computed from the count.
