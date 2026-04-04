# Task 143 Review: Unified Diagnostic System

## Metadata
- Implementation Date: 2026-04-02 to 2026-04-04
- Commits: `13a49dc9` (feat), `2871bd64` (review fixes), `efa7a2d7` (task review + baseline), `c7304d0d` (PR review fixes)
- PR: #218
- Branch: `feat/unified-diagnostic-system`
- Base: `15eee95e`

## Executive Summary

Replaced 3 incompatible warning types (`list[str]`, `ValidationWarning` dataclass, ad-hoc `dict`) and inconsistent error dict shapes with a single `Diagnostic` dataclass. One type, one list on `ExecutionResult`, one shared render function. Fixes #209 (parser warnings silently lost). 62 files changed, ~5200 lines added, ~960 removed. 4546 tests passing.

## Implementation Overview

### What Was Built

A `Diagnostic` dataclass in `src/pflow/core/diagnostic.py` (684 lines) that carries severity, message, suggestion, node_id, source, and context. All warning producers (parser ×2, validator ×2, cache lint ×1, runtime ×2) now emit `Diagnostic`. All error producers (runner exception boundary, executor_service node failures, CLI pre-runner boundary) use a shared `exception_to_diagnostics()` function. `ExecutionResult` and `ValidationResult` use `diagnostics: list[Diagnostic]` as primary storage with `.errors` and `.warnings` as filtered convenience properties.

### Spec Deviations

| Deviation | Spec says | Implementation does | Why |
|-----------|-----------|-------------------|-----|
| Warning `context` | "always `None`" | Template warnings carry `context={"template": "..."}` | Agent-actionable: the template string identifies what to fix |
| `ValidationResult.errors` | "matching ExecutionResult" | Returns `list[str]` (messages only) | All consumers need strings; `vresult.diagnostics` gives full access. **Task 144 tracks unification.** |
| `_resolve_child_workflow_outputs()` | Listed as threading site | Skipped | Output-shape helper, not a user-visible path. Other 4 sites cover all observable paths. |
| `_exception_to_errors()` | Listed under Deletions | Initially kept as wrapper, deleted during review | The wrapper masked the single-conversion-path architecture |

### Implementation Approach

Dual-write transition: added `diagnostics` field alongside old fields (`errors`, `warnings`, `validation_warnings`), converted all producers and consumers, then removed old fields and made them computed properties. The cutover to properties was atomic — all construction sites and consumers updated in the same commit.

## Files Modified/Created

### Core Changes (what matters for future agents)

- **`src/pflow/core/diagnostic.py`** (NEW, 684 lines) — The type, `exception_to_diagnostics()` (13 exception types), `format_diagnostic()` (multi-path rendering), `coerce_warning_diagnostic()`/`coerce_error_diagnostic()` (dict→Diagnostic bridges), `deduplicate_diagnostics()`.
- **`src/pflow/execution/result.py`** — `ExecutionResult` and `ValidationResult` now have `diagnostics` as only stored field for warnings/errors. Old fields are convenience properties. `ResolvedWorkflow` gained `diagnostics: tuple[Diagnostic, ...]` for parser warnings.
- **`src/pflow/execution/runner.py`** — The central hub. `_prepare_workflow()` accumulates diagnostics into a mutable list. `_compile_and_execute()` merges errors + runtime warnings + validation warnings into one deduplicated list. `_exception_to_result()` preserves parser diagnostics via `_pflow_parser_diagnostics` exception annotation. `run()` and `validate()` accept `ResolvedWorkflow` directly.
- **`src/pflow/execution/workflow_resolver.py`** — `_try_load_from_file()` and `_load_library_workflow()` capture parser warnings in `ResolvedWorkflow.diagnostics`. Library path reparses the file when available, falls back to `load_ir()` for test doubles.
- **`src/pflow/core/workflow/validator.py`** — `_validate_sub_workflows()` now propagates ALL child warnings (not just parser) with provenance prefix. Uses `_add_child_provenance()` helper.
- **`src/pflow/runtime/workflow_executor.py`** — `_propagate_child_parser_warnings()` adds provenance (parent node_id + message prefix) before propagating to `__parser_diagnostics__`. `_load_workflow_by_name()` reparses saved workflows for parser warnings.
- **`src/pflow/execution/executor_service.py`** — `build_error_list()` now returns `list[Diagnostic]` with enrichment in `context`.
- **`src/pflow/cli/error_output.py`** — `display_exception_text()` uses `exception_to_diagnostics()` + `format_diagnostic()`. `_exception_to_errors()` deleted. `_format_from_exception()` inlines the conversion.

### Test Files (which actually matter)

- **`tests/test_core/test_diagnostic.py`** — Comprehensive: identity/hash semantics, serialization, exception conversion for all 13 types, formatting, coerce functions. The exception conversion tests are the most valuable — they catch regressions in the shared conversion boundary.
- **`tests/test_execution/test_runner.py`** — `test_child_parser_warning_survives_prep_failure`, `test_sibling_child_parser_warnings_not_collapsed_by_dedup`, `test_child_cache_lint_warning_propagates_to_parent_validation`. These three guard the child-workflow propagation paths.
- **`tests/test_cli/test_validate_only.py`** — `TestParserWarningsReachCLI` (3 tests) and `TestFailurePathShowsWarnings` (1 test). These are the end-to-end guards for #209 and the "failure shows warnings" spec requirement.

## Integration Points & Dependencies

### Critical Data Flows (break any of these and diagnostics silently vanish)

1. **CLI/MCP → Runner**: Both pre-resolve workflows for metadata. They MUST pass `ResolvedWorkflow` (not `.ir` dict) to `WorkflowRunner.run()`/`validate()`, or parser diagnostics from resolution are lost. The runner's `_resolve()` passes through `ResolvedWorkflow` unchanged.

2. **Validation → Runtime dual path**: Child workflow parser warnings propagate through TWO independent paths — validation (`_validate_sub_workflows`) and runtime (`WorkflowExecutor._propagate_child_parser_warnings`). Both must use **identical message format** (`"In step '{id}' sub-workflow: ..."`) or dedup produces duplicates instead of collapsing them.

3. **`WorkflowManager.load_ir()`**: Discards parser warnings. Any path that needs parser diagnostics from saved workflows must reparse via `parse_markdown()`. The `_load_library_workflow()` function in the resolver and `_load_workflow_by_name()` in the executor both do this opportunistically — reparsing when the file exists, falling back to `load_ir()` for test doubles.

### Shared Store Keys

- `__parser_diagnostics__` — `list[Diagnostic]`. Initialized in `_initialize_shared_store()`. In `_PROPAGATED_KEYS` for nested workflow depth > 1. Written by `WorkflowExecutor._propagate_child_parser_warnings()`, read by `_extract_runtime_warnings()`. Parser warnings do NOT drive DEGRADED status — `_determine_status()` only reads `__warnings__` and `__template_errors__`.

## Architectural Decisions & Tradeoffs

### Key Decisions

**`context: dict | None` instead of typed fields** — Enrichment data (HTTP status, shell stderr, MCP details, template strings) is heterogeneous and node-type-specific. Typed fields would bloat the dataclass with 15+ optional fields. `context` is the Sentry pattern — clean message + optional context bag. Display code uses `message` + `suggestion` (always sufficient). JSON output includes `context` (agents get structured data). Sanitization at display time, not construction.

**Custom `__hash__` on `(severity, source, node_id, message)`, context excluded** — Two diagnostics with the same core identity but different enrichment are the same diagnostic for dedup. This is critical for the dual-propagation-path architecture — validation and runtime produce the same warnings with potentially different context, and dedup must collapse them.

**`to_dict()` vs `to_display_dict()`** — Two serialization methods exist for different boundaries. `to_dict()` keeps context nested (for structured JSON consumers). `to_display_dict()` merges context keys to top level via `setdefault` (for backward-compat display code that reads flat dict keys like `error["category"]`). Future: eliminate `to_display_dict()` when all display code reads from Diagnostic attributes directly.

**`ValidationResult.errors` returns `list[str]`** — Pragmatic: `format_validation_failure()` takes `list[str]`. Changing to `list[Diagnostic]` would require updating the formatter and all callers. `vresult.diagnostics` gives full Diagnostic access. Task 144 tracks unification.

### Technical Debt → Task 144

The following items are scoped into **Task 144: Display Consolidation — Diagnostic Rendering Redesign**:

- `diagnostic.py` rendering has 6 special-case paths (~260 lines) where 2-3 patterns would suffice. Context blocks (API response, shell stderr, MCP error) only render for the runtime default path — other error types silently ignore context even when populated.
- `to_display_dict()` is a transition bridge for text consumers that receive dicts instead of Diagnostics. Three text paths still round-trip: Diagnostic → dict → coerce back → format.
- `coerce_warning_diagnostic()`/`coerce_error_diagnostic()` (7 call sites) exist solely because display code receives dicts. Dead code once text paths receive Diagnostics natively.
- `ValidationResult.errors` returns `list[str]` not `list[Diagnostic]` — loses suggestion, node_id, source, context.
- `exception_to_diagnostics()` has 3 near-identical branch groups (UserFriendlyError/MCPError/OutputResolutionError, FileNotFoundError/PermissionError/generic, SchemaValidationError/MarkdownParseError).

**Not scoped into Task 144:**
- Library resolution reparses files instead of extending `load_ir()` to return warnings. The proper fix is to change the `WorkflowManager` API, but that's a larger change.

## Unexpected Discoveries

### The Dual-Propagation-Path Problem

Child parser warnings flow through both validation AND runtime paths. Both parse the same child files and produce the same warnings. Without identical provenance format, dedup fails and users see duplicates. This was not anticipated in planning — it emerged when a regression test produced 4 warnings instead of 2.

### `MarkdownParseError.__str__()` Embeds Suggestions

`MarkdownParseError` concatenates its suggestion into `str(exc)` with a `\n\n` separator. Naively using `str(exc)` as `Diagnostic.message` and also setting `Diagnostic.suggestion` prints the suggestion twice. Fix: `str(exception).split("\n\n", 1)[0]` strips the embedded suggestion.

### CLI/MCP Pre-Resolve Boundary

Both CLI and MCP resolve workflows BEFORE calling the runner — for metadata, routing, and parameter validation. They then pass the pre-parsed IR dict to the runner. The runner's `_resolve()` sees a dict and returns `ResolvedWorkflow(diagnostics=())`. Parser diagnostics from the initial resolution silently vanish. Fix: pass `ResolvedWorkflow` objects through, not `.ir` dicts. The runner's `_resolve()` now accepts and passes through `ResolvedWorkflow` directly.

### `WorkflowExecutor` Has No `id` Attribute by Default

`BaseNode` doesn't have an `id` property. The compiler sets `node_instance.node_id = node_id` during compilation. But tests that construct `WorkflowExecutor` directly (without the compiler) don't have `node_id`. Provenance code must use `getattr(self, "node_id", None)` with fallback.

## Patterns Established

### The Diagnostic Pattern (reuse for all future output types)

```python
# Production code creates Diagnostics:
Diagnostic(severity=Severity.WARNING, source="validator", node_id="fetch",
           message="...", suggestion="...", context={"template": "..."})

# Shared conversion at exception boundaries:
diagnostics = exception_to_diagnostics(exception)

# Shared rendering for all display paths:
text = format_diagnostic(diagnostic, verbose=verbose, error_number=n)

# Dedup using custom hash (context excluded):
diagnostics = deduplicate_diagnostics(all_diagnostics)
```

### Provenance Prefixing for Child Diagnostics

When propagating diagnostics from child workflows, always add provenance:
```python
Diagnostic(
    severity=w.severity,
    message=f"In step '{step_id}' sub-workflow: {w.message}",
    node_id=w.node_id or step_id,  # differentiate siblings for dedup
    ...
)
```
The message format MUST match across all propagation paths (validation + runtime).

### Instance Variable + Propagated Shared-Store Key

For data that originates in a child node's `prep()` and must reach the parent runner:
1. Store on the node instance in `prep()`: `self._child_parser_warnings = list(warnings)`
2. Propagate to shared store: `shared["__parser_diagnostics__"].extend(...)`
3. Add the key to `_PROPAGATED_KEYS` for depth > 1
4. Initialize the key in `_initialize_shared_store()` as an empty list

## Breaking Changes

### API Changes
- `ExecutionResult.errors` returns `list[Diagnostic]` (was `list[dict]`)
- `ExecutionResult.warnings` returns `list[Diagnostic]` (was `list[dict]`)
- `ExecutionResult` constructor takes `diagnostics=` (not `errors=`, `warnings=`, `validation_warnings=`)
- `ValidationResult.warnings` returns `list[Diagnostic]` (was `list[dict]`)
- `ValidationResult` constructor takes `diagnostics=` (not `errors=`, `warnings=`)
- `build_error_list()` returns `list[Diagnostic]` (was `list[dict]`)
- `WorkflowRunner.run()` and `validate()` accept `str | dict | ResolvedWorkflow`
- `format_for_cli()` methods deleted from all exception classes
- `ValidationWarning` class deleted
- `_exception_to_errors()` deleted from `error_output.py`

### JSON Output Changes
- Success JSON always includes `"warnings": [...]` and `"diagnostics": [...]` (even when empty)
- Error JSON includes `"diagnostics": [...]` with `to_dict()` format (nested context)
- Error `"errors"` array uses `to_display_dict()` format (flat context) for backward compat
- Validate-only JSON includes `"diagnostics": [...]`

## AI Agent Guidance

### Quick Start for Related Tasks

Read these files first:
1. `src/pflow/core/diagnostic.py` — the type, conversion, formatting
2. `src/pflow/execution/result.py` — result types (48 lines, very readable)
3. `src/pflow/execution/runner.py:128-235` — `_prepare_workflow` and `_compile_and_execute` (the central hub)

### Common Pitfalls

1. **Passing `.ir` instead of `ResolvedWorkflow` to the runner** silently drops parser diagnostics. Always pass the full `ResolvedWorkflow` through.
2. **Changing provenance message format** in `validator.py` OR `workflow_executor.py` without updating the other breaks dedup — you get duplicate warnings.
3. **Adding a shared store key** without adding it to `_PROPAGATED_KEYS` silently kills it for nested workflows at depth > 1.
4. **Changing `Diagnostic.__hash__`** to include `context` breaks dedup for the dual-propagation-path architecture.
5. **Constructing `ExecutionResult(errors=[...])`** — `errors` is a property now. Use `diagnostics=[Diagnostic(...)]`.

### Test-First Recommendations

When modifying diagnostic propagation, run these first:
```bash
pytest tests/test_execution/test_runner.py tests/test_cli/test_validate_only.py::TestParserWarningsReachCLI tests/test_core/test_diagnostic.py -q
```

---

*Generated from implementation context of Task 143*
