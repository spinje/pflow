# Task 143: Unified Diagnostic System

## Description

Replace all ad-hoc warning types (ValidationWarning, runtime warning dicts, parser warning strings) and error output dicts with a single `Diagnostic` dataclass used from generation through display. Fixes #209 (parser warnings silently lost) and the reviewer finding from PR #216 (duplicate warning formatting logic).

## Status

not started

## Priority

high

## Problem

pflow generates diagnostics at multiple stages (parse, validate, execute) and surfaces them through multiple channels (CLI text, CLI JSON, MCP). Today this is fragmented:

**Warnings (3 incompatible types):**
- Parser: `list[str]` on `MarkdownParseResult.warnings` — silently dropped at all 13 call sites (#209)
- Validation: `ValidationWarning` dataclass (3 fields) — converted to dicts via `_warning_to_dict()`
- Runtime: ad-hoc dicts with `{"node_id", "type", "message"}` — extracted from shared store

**Errors (ad-hoc dicts with inconsistent shapes):**
- `_exception_to_result()` in `runner.py` has type-specific branches producing different dict shapes per exception type
- `build_error_list()` in `executor_service.py` produces enriched dicts with node-type-specific fields (HTTP status, shell stderr, MCP details)
- CLI JSON and MCP intermediate dict have different shapes for the same `"error"` key (string vs dict)

**Consequences:**
- `ExecutionResult` has two warning fields (`warnings` + `validation_warnings`) that every consumer merges
- Two merge sites (`main.py:148`, `execution_service.py:70`)
- Duplicate display code (4 warning render sites, 2 error render paths)
- PR #216 reviewer flagged duplicate warning formatting in `main.py:408-414` and `execution_service.py:269-276`
- Parser warnings (#209) are generated but never reach users — `## Input` (singular) silently produces zero inputs with no feedback
- `"node"` vs `"node_id"` key mismatch was fixed in PR #216 but the structural cause (ad-hoc dicts) remains

## Solution

One diagnostic type, one list, one render function. Following the pattern of top-tier CLI tools (rustc, eslint, mypy) that use a single diagnostic type with a severity field.

```python
class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

@dataclass
class Diagnostic:
    severity: Severity
    message: str                              # what happened
    suggestion: str | None = None             # what to do (agent-actionable)
    node_id: str | None = None                # which node (None = workflow-level)
    source: str = ""                          # "parser" | "validator" | "runtime" | "compilation"
    context: dict[str, Any] | None = None     # enrichment data (HTTP status, shell stderr, etc.)
```

- **Internal mechanism unchanged**: `PflowError` exceptions still control flow (retries, abort). `Diagnostic` is the output/reporting type.
- **Conversion boundary**: Exceptions become `Diagnostic(severity=ERROR)` at the runner boundary. Warnings become `Diagnostic(severity=WARNING)` at their creation sites.
- **One field on ExecutionResult**: `diagnostics: list[Diagnostic]` replaces `warnings`, `validation_warnings`, and `errors` (the ad-hoc dict lists).
- **One render function**: `format_diagnostic(d: Diagnostic) -> str` shared by CLI and MCP.
- **Parser warnings threaded**: Through the execution path (2 resolver sites + 1 nested workflow executor) into the diagnostics list.

## Design Decisions

- **Warnings AND errors in one type**: Doing both in one task because the verification matrix (baseline capture, output comparison across all paths) is the same work either way. Doing it twice would be the real waste.
- **`context: dict[str, Any] | None` for enrichment data**: HTTP status codes, shell stderr, MCP error details, available template fields are heterogeneous and node-type-specific. Typed fields would bloat the dataclass with 15+ optional fields each relevant to one node type. `context` is the Sentry pattern — clean structured message + optional context bag. Display code uses `message` + `suggestion` (always sufficient for action). JSON output includes `context` when present (agents get structured data for deeper parsing). For warnings, `context` is always `None`.
- **`PflowError` hierarchy stays**: Exceptions control flow (retries, abort, error-only successors). Diagnostic is the output representation. Conversion happens once at the runner boundary, not throughout the codebase.
- **Parser warnings only threaded through execution path**: 5 of 13 `parse_markdown()` call sites need warnings: 2 resolver sites (running workflows), 1 nested workflow executor (sub-workflows at runtime), 2 validator sites (sub-workflow validation). The remaining 8 (save, list, describe, dependency discovery, template analysis) are internal operations where parser syntax warnings would be noise.
- **Status line indicator**: Success with warnings shows `⚠ Workflow completed with 2 warnings` instead of the current `✓`. Failure with warnings shows `❌ Workflow failed (2 warnings)`. Warnings listed in the execution summary, not shown early.
- **No early warning display**: PR #216 already deleted the early display loop. Warnings appear once in the execution summary (success or failure path). The ⚠ status indicator signals "look down."
- **Custom `__eq__`/`__hash__` instead of `frozen=True`**: `context: dict` is unhashable, so `frozen=True` auto-hash won't work. Custom hash on `(severity, source, node_id, message)` — context excluded because two diagnostics with the same message but different enrichment data are the same diagnostic.
- **Shared `exception_to_diagnostics()` utility**: Both the runner and CLI error handler need exception→Diagnostic conversion. One function, no drift between paths. Lives alongside the Diagnostic type.
- **`format_for_cli()` methods replaced, not kept**: Exception→Diagnostic conversion must produce Diagnostics whose rendering via `format_diagnostic()` is equivalent to what `format_for_cli()` produced. One render path everywhere.
- **Convenience properties on ExecutionResult**: `result.errors` and `result.warnings` as filtered views of `result.diagnostics`. Reduces consumer blast radius without undermining the unified storage.
- **`ValidationResult` fully unified**: `errors`, `warnings`, and `suggestions` all become Diagnostics with appropriate severity levels. Same principle as ExecutionResult.
- **`category` in `context`**: Error categories like "compilation", "api_validation" are error-specific metadata. Display code reads from `diagnostic.context`, not a dedicated field.
- **Sanitization at display time**: Context holds raw enrichment data. Sanitize when serializing for JSON output or rendering for text, same timing as today.

## Dependencies

None. PR #216 (ValidationWarning slim-down, cache opt-out) and PR #217 (#212 duplicate section detection) are already merged.

## Requirements

### Diagnostic Type
- `Diagnostic` dataclass with fields: `severity`, `message`, `suggestion`, `node_id`, `source`, `context`
- `Severity` enum: `ERROR`, `WARNING`, `INFO`
- Custom `__eq__` and `__hash__` based on `(severity, source, node_id, message)` only — `context` is a mutable dict and excluded from identity. Two diagnostics with the same core fields but different context are the same diagnostic for dedup purposes.
- Lives in a shared location (e.g., `src/pflow/core/diagnostic.py`) importable by parser, validator, runtime, and display code — no circular import risk

### Warning Producers
- Parser (`markdown_parser.py`): 2 warning sites emit `Diagnostic(severity=WARNING, source="parser")` instead of appending strings
- Validator (`path_validation.py`): 2 creation sites emit `Diagnostic(severity=WARNING, source="validator")` instead of `ValidationWarning`
- Validator cache lint (`validator.py`): emits `Diagnostic(severity=WARNING, source="validator")` instead of `ValidationWarning`
- Runtime (`runner.py`): `_extract_runtime_warnings()` emits `Diagnostic(severity=WARNING, source="runtime")` instead of ad-hoc dicts
- Every warning MUST have a `suggestion` field (the agent-actionable requirement)

### Error Producers
- `_exception_to_result()` in `runner.py`: each exception type branch produces `Diagnostic(severity=ERROR)` instead of ad-hoc dicts
- `build_error_list()` in `executor_service.py`: runtime node failures produce `Diagnostic(severity=ERROR, context={...enrichment...})`
- Enrichment data (HTTP status, shell command/stderr, MCP error, available fields, trace hint) goes in `context`
- `category` (e.g., "compilation", "api_validation", "execution_failure") goes in `context` — it's error-specific metadata that warnings don't have. Display code reads `diagnostic.context.get("category")` for header decisions.
- `WorkflowValidationError` carries `validation_errors: list[str | tuple]` — the conversion MUST produce one Diagnostic per validation error, not one Diagnostic for the whole exception
- Sanitization of sensitive data (`raw_response`, `response_headers`) happens at display/serialization time, not at Diagnostic construction. Context holds raw data.

### Shared Exception-to-Diagnostic Conversion
- Create a shared `exception_to_diagnostics(exc: Exception) -> list[Diagnostic]` utility alongside the Diagnostic type
- Used by BOTH the runner (`_exception_to_result`) AND the CLI error handler (`error_output.py`)
- The CLI layer catches some exceptions before the runner runs (e.g., `WorkflowNotFoundError` from resolution, `MarkdownParseError` from file loading) — these go through `error_output.py` and need the same conversion logic
- `format_for_cli()` methods on exceptions (`WorkflowNotFoundError`, `WorkflowValidationError`, `UserFriendlyError`, `MaxNodeVisitsError`) become redundant — the conversion must produce Diagnostics whose `message` + `suggestion` render equivalently via `format_diagnostic()`. One render path, no drift.

### ExecutionResult
- Replace `warnings: list[dict]` and `validation_warnings: list[dict]` and `errors: list[dict]` with single `diagnostics: list[Diagnostic]`
- Runner merges all diagnostics at the source — no downstream merging
- Delete the two merge sites (`main.py:148`, `execution_service.py:70`)
- Add convenience properties to reduce consumer blast radius:
  ```python
  @property
  def errors(self) -> list[Diagnostic]:
      return [d for d in self.diagnostics if d.severity == Severity.ERROR]
  @property
  def warnings(self) -> list[Diagnostic]:
      return [d for d in self.diagnostics if d.severity == Severity.WARNING]
  ```
- `success` and `status` fields stay — they represent execution outcome, not diagnostic content

### Parser Warning Threading (#209)
- `MarkdownParseResult.warnings` changes from `list[str]` to `list[Diagnostic]`
- `ResolvedWorkflow` gains a `diagnostics: list[Diagnostic]` field (or warnings field)
- `workflow_resolver.py` (2 sites): preserves parser diagnostics when building `ResolvedWorkflow`
- `workflow_executor.py` (1 site): propagates sub-workflow parser diagnostics to parent execution
- `validator.py` (2 sites): propagates sub-workflow parser diagnostics through validation
- Parser diagnostics with `node_id=None` (workflow-level) — display code handles this

### Display — CLI Text
- One shared `format_diagnostic()` function for the diagnostic-to-string conversion
- Warning display: `⚠ [{node_id}] {message}` with optional `→ {suggestion}` on next line. If `node_id` is None (parser warnings), display `⚠ {message}`
- Error display: preserve all current enrichment rendering (API response, shell details, MCP errors, available fields, trace hint) — read from `diagnostic.context`
- Status line: `⚠ Workflow completed with N warnings` when diagnostics contain warnings but no errors. `❌ Workflow failed (N warnings)` when both.
- Failure path must show warnings (currently shows zero) — list warnings after errors in the error display
- Delete duplicate display code: `workflow_output.py:583-597` and `success_formatter.py:235-250` replaced by shared function

### Display — CLI JSON
- `diagnostics` key in JSON output, each diagnostic serialized as dict
- `context` included when present (gives agents structured enrichment data)
- Backwards-incompatible change to JSON shape is acceptable (no users yet)

### Display — MCP
- Same `format_diagnostic()` function for text rendering
- Delete duplicate formatting in `execution_service.py:269-276`
- MCP error path: format diagnostics into the RuntimeError text (same enrichment display as CLI)

### Display — Validate-Only
- `ValidationResult` unified: replace `errors: list[str]`, `warnings: list[dict]`, and `suggestions: list[str]` with single `diagnostics: list[Diagnostic]`
- Validation errors become `Diagnostic(severity=ERROR)`, warnings become `Diagnostic(severity=WARNING)`
- Suggestions (from `generate_validation_suggestions()`) become `Diagnostic(severity=INFO)` — they're derived from errors but agent-actionable in their own right
- `ValidationResult.valid` stays as the primary success indicator
- Add convenience properties matching ExecutionResult (`errors`, `warnings`)
- Validate-only text output uses same `format_diagnostic()` function
- Validate-only JSON includes `diagnostics` array

### Error Formatter Scope
- `format_execution_errors()` in `error_formatter.py` does more than format errors: it handles sanitization, adds `checkpoint` (from shared_after), and adds `execution` state (per-node steps/timings)
- These are execution metadata, not diagnostics — the formatter stays but changes to serialize Diagnostics instead of copying dicts
- Sanitization applies to `diagnostic.context` fields at serialization time (same timing as today)

### Deletions
- `ValidationWarning` dataclass
- `_warning_to_dict()` static method on WorkflowRunner
- `_extract_runtime_warnings()` (replaced by direct Diagnostic construction)
- `_deduplicate_warnings()` (replaced by set-based dedup using custom `__hash__`)
- `validation_warnings` field on `ExecutionResult` (replaced by `diagnostics`)
- `warnings` field on `ExecutionResult` (replaced by `diagnostics`)
- `errors` field on `ExecutionResult` (replaced by `diagnostics`)
- Merge code at `main.py:148` and `execution_service.py:70`
- Duplicate warning display at `workflow_output.py:583-597`
- `_exception_to_errors()` in `error_output.py` (replaced by shared `exception_to_diagnostics()`)
- `format_for_cli()` methods on exception classes become dead code once all display goes through `format_diagnostic()` — delete them

### Baseline Capture (pre-implementation)
- Before any code changes, capture current output for every output path as reference files
- Paths to capture (each in text and JSON where applicable):
  - CLI: success, success with warnings, failure, failure with warnings, degraded, validate-only valid, validate-only invalid with suggestions
  - MCP: success, success with warnings, failure, validate-only
  - Error types: compilation error, runtime node failure (HTTP, shell, MCP), template error with available fields, WorkflowNotFoundError with similar names, MarkdownParseError with line number, WorkflowValidationError with multiple errors, UserFriendlyError with suggestions
- Store baselines in `scratchpads/task-143-baselines/` for comparison during and after implementation
- Every output path must produce equivalent or improved output — no silent regressions in information content or agent actionability

## Implementation Notes

### Conversion Boundaries (three, not two)

The key architectural insight: `PflowError` exceptions stay as the flow-control mechanism. `Diagnostic` is the reporting type. The shared `exception_to_diagnostics()` utility handles all three boundaries:

1. **`_exception_to_result()`** in `runner.py` — catches exceptions during execution pipeline, converts via shared utility. Each exception type maps to one or more Diagnostics.

2. **`build_error_list()`** in `executor_service.py` + `_enrich_error_from_node_output()` — runtime node failures with enrichment. The enrichment fields (HTTP status, shell stderr, etc.) go into `context`.

3. **`error_output.py`** — catches exceptions that occur before the runner (e.g., `WorkflowNotFoundError` from resolution, `MarkdownParseError` from file loading). Currently has its own `_exception_to_errors()` — replaced by the same shared utility. This eliminates a source of drift between runner and CLI error handling.

### Error Display Preservation

The error display functions in `workflow_errors.py` (`_display_single_error`, `_display_api_error_response`, `_display_mcp_error_details`, `_display_shell_error_details`) currently read from top-level error dict keys. With Diagnostic, they read from `diagnostic.context.get("key")` instead. The helper functions themselves stay — they receive a dict and format it. No loss of any current display detail.

### PflowError Hierarchy (13 types)

Each needs a conversion path to Diagnostic. The key ones:

| Exception | Diagnostic fields | Context |
|-----------|-------------------|---------|
| `CompilationError` | `source="compilation"`, `node_id`, `suggestion` | `phase`, `node_type`, `details` |
| `UserFriendlyError` (+ MCPError, OutputResolutionError) | `source="runtime"`, `suggestion` from suggestions list | `title`, `explanation`, `technical_details` |
| `MarkdownParseError` | `source="parser"`, `suggestion` | `line` |
| `SchemaValidationError` | `source="validation"`, `suggestion` | `path` |
| `WorkflowValidationError` | `source="validation"` — **produces multiple Diagnostics**, one per validation_errors entry | `path` (from tuple entries) |
| `WorkflowNotFoundError` | `source="runtime"`, `suggestion` from similar_names | `similar_names` |
| `MaxNodeVisitsError` | `source="runtime"` | `visit_count`, `max_visits` |
| Runtime node failures | `source="runtime"`, enrichment in context | HTTP/shell/MCP/template fields |

### MCP Error Path

MCP currently raises `RuntimeError(text)` — FastMCP constraint, can't change. The text is built by `_build_error_text()` from an intermediate dict. With Diagnostic, `_build_error_text()` receives `list[Diagnostic]` and formats them using `format_diagnostic()`. Simpler intermediate representation.

### Test Impact

Research identified the affected tests:

**Tier 1 — Structural (dict key/shape changes, ~35 tests):**
- `tests/test_execution/formatters/test_error_formatter.py` (16 tests)
- `tests/test_execution/test_workflow_execution.py` (1 test)
- `tests/test_execution/test_runner.py` (1 test)
- `tests/test_mcp_server/test_mcp_warnings.py` (4 tests)
- `tests/test_runtime/test_template_validation/test_warnings.py` (7 tests)
- `tests/test_integration/test_template_resolution_hardening.py` (5 tests)
- `tests/test_cli/test_dual_mode_stdin.py` (1 test)

**Tier 2 — Text format (only if display strings change, ~130+ tests):**
- `tests/test_execution/formatters/test_success_formatter.py` (30+ tests)
- `tests/test_execution/formatters/test_validation_formatter.py` (13 tests)
- `tests/test_mcp_server/test_validation_service.py` (8 tests)
- Various CLI tests

**Tier 3 — Substring (low risk, ~10 tests):**
- Integration tests checking `"Workflow completed"` substrings

## Verification

### Functional
- Parser warnings (`## Input` typo, orphaned content) reach the user through CLI text, CLI JSON, and MCP output
- All 13 exception types convert to Diagnostic correctly (message, suggestion, context preserved)
- Runtime enrichment data (HTTP, shell, MCP, template fields) displays identically to current output
- Validate-only mode shows diagnostics in both text and JSON
- Failure path shows warnings (currently doesn't)
- Success with warnings shows ⚠ status indicator
- Deduplication works (frozen Diagnostic hashability)
- No enrichment display is lost — API response, shell details, MCP errors, available fields, trace hints all render

### Integration
- `make test` passes (4500+ tests)
- `make check` passes (lint, type check)
- Tier 1 tests updated to use Diagnostic assertions
- End-to-end: run a workflow that produces warnings + succeeds, verify output
- End-to-end: run a workflow that produces warnings + fails, verify both shown

### Agent Actionability
- Every warning has a `suggestion` field
- JSON output includes structured `diagnostics` array with `context` when present
- An AI agent can parse the JSON, identify the issue, and know what to fix without reading prose

## References

### Issues
- #209: Parser warnings silently lost during workflow resolution (OPEN — fixed by this task)
- #204: Misleading error when inputs uses wrong syntax (CLOSED — parser detection works, warnings don't reach users)
- #212: Duplicate known section headings silently merge (CLOSED — fixed in PR #217)

### PRs
- PR #216: ValidationWarning slim-down (7→3 fields), cache opt-out, duplicate display fix — establishes current state
- PR #217: Duplicate section detection (#212)
- PR #216 review finding: duplicate warning formatting logic acknowledged, deferred to this task

### Key Files (current state after PR #216 + #217)
- `src/pflow/runtime/template_validation/utils.py:22-37` — `ValidationWarning` (to be replaced)
- `src/pflow/runtime/template_validation/path_validation.py:182-194, 297-308` — 2 ValidationWarning creation sites
- `src/pflow/core/workflow/validator.py` — cache lint warning creation
- `src/pflow/core/markdown_parser.py:311, 421-424` — 2 parser warning sites
- `src/pflow/execution/runner.py:438-450` — `_extract_runtime_warnings()`
- `src/pflow/execution/runner.py:485-584` — `_exception_to_result()` (error dict construction)
- `src/pflow/execution/runner.py:604-613` — `_warning_to_dict()` (to be deleted)
- `src/pflow/execution/runner.py:615-625` — `_deduplicate_warnings()` (to be deleted)
- `src/pflow/execution/result.py` — `ExecutionResult`, `ValidationResult`
- `src/pflow/execution/executor_service.py:16-48, 181-222` — runtime error extraction + enrichment
- `src/pflow/cli/main.py:148` — warning merge site
- `src/pflow/cli/main.py:390-423` — `_display_validation_result()`
- `src/pflow/cli/workflow_output.py:475-503` — `_display_workflow_completion_status()` (status line)
- `src/pflow/cli/workflow_output.py:583-597` — warning display (duplicate of success_formatter)
- `src/pflow/cli/workflow_errors.py` — error text display with enrichment rendering
- `src/pflow/cli/error_output.py` — unified error output (JSON + text)
- `src/pflow/execution/formatters/success_formatter.py:235-250` — warning display in MCP text
- `src/pflow/execution/formatters/error_formatter.py` — error sanitization + execution steps
- `src/pflow/mcp_server/services/execution_service.py:70, 269-276` — MCP merge + formatting
- `src/pflow/execution/workflow_resolver.py:126-132, 169-171` — resolver (thread parser warnings)
- `src/pflow/runtime/workflow_executor.py:441` — nested workflow loading (thread parser warnings)
- `src/pflow/core/workflow/validator.py:761` — sub-workflow validation (thread parser warnings)
- `src/pflow/core/exceptions.py` — PflowError hierarchy
- `src/pflow/core/user_errors.py` — UserFriendlyError hierarchy
