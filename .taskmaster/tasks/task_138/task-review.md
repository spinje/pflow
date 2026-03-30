# Task 138 Review: Shared Execution Pipeline

## Metadata
- **Implementation Date**: 2026-03-29 to 2026-03-30
- **Branch**: `feat/shared-execution-pipeline`
- **Starting test count**: 4,666 → **Final**: 4,678 (+12)
- **Net lines**: ~760 fewer lines of production + test code

## Executive Summary

Replaced pflow's parallel CLI/MCP orchestration layers with a single `WorkflowRunner` that both entry points call. Eliminated ~1,740 lines of duplicated glue code (resolvers, validation, execution wrappers, dead functions) and created ~980 lines of unified pipeline. The Runner owns the full execution lifecycle: resolution → file refs → validation → compilation → execution → resource cleanup → metadata update → exception boundary. CLI and MCP are now thin callers that configure the Runner and format its results.

## Implementation Overview

### What Was Built

Three new files form the execution core:

- **`execution/runner.py`** (~520 lines) — `WorkflowRunner` class with `run()` (always returns `ExecutionResult`, never raises) and `validate()` (returns `ValidationResult`, raises on programming bugs only)
- **`execution/result.py`** (~60 lines) — `RunnerConfig`, `ResolvedWorkflow`, `ValidationResult`, `ExecutionResult` (extended with `validation_warnings`, `trace`, `metrics`)
- **`execution/workflow_resolver.py`** (~200 lines) — Unified resolver merging CLI and MCP resolvers, returns `ResolvedWorkflow(ir, source, file_path)`, raises `WorkflowNotFoundError` on not-found

Additionally: `core/security_utils.py` extracted from `mcp_server/utils/errors.py` to fix an architectural inversion (execution layer was importing from MCP server).

### Key Deviations from Plan

The plan went through 8 review agents and had 12 critical bugs in its code snippets (wrong API signatures, broken Python patterns, missing state injection). All were caught pre-implementation. But the real deviations came during implementation:

1. **`prepare_inputs()` triple-call eliminated.** The plan called `_enrich_params_with_defaults` (which internally called `prepare_inputs`). This ran `prepare_inputs` 3x per CLI execution. Replaced with `_fill_declared_defaults` — a 6-line method that only marks which inputs exist, without resolving values. `prepare_inputs` now runs exactly once, in the compiler's `_prepare_compilation`.

2. **Phase 3 required a redo.** The implementing agent initially kept ALL validation in `_prepare_compilation` for "defense-in-depth" — negating the task's purpose. On correction: structure validation and data-flow validation stayed (compiler prerequisites), template validation was stripped (moved to WorkflowValidator via Runner).

3. **Resource lifecycle forced `run()` decomposition.** Ruff C901 required splitting `run()` into `_prepare_workflow` + `_compile_and_execute` + `_cleanup`. But putting resource creation inside `_compile_and_execute` caused MCP pool leaks — if the method raised after creating the pool, the tuple assignment never completed and the outer `finally` saw `mcp_pool = None`. Resources were moved back to `run()` scope.

4. **`node_id` lost from runtime exceptions.** The old `_handle_execution_exception` read `shared_store["__execution__"]["failed_node"]`. The new `_exception_to_result` doesn't have shared_store access (it's outside `_compile_and_execute`). Fixed with `_pflow_node_id` exception annotation — `_compile_and_execute` catches `flow.run()` exceptions, attaches the failed node, and re-raises.

5. **`validation_warnings` display required two rounds of fixes.** The plan added the field to `ExecutionResult` but no display path read it. First code review caught it. Then a second review found CLI JSON output still only passed `result.warnings` (runtime), not `result.validation_warnings`.

## Architectural Decisions & Tradeoffs

### The Placeholder/Strip Pattern

**Decision**: Use `_fill_declared_defaults` (fills with real defaults or `__pflow_declared_X__` placeholders) + `_strip_placeholders` (removes before compilation) instead of calling `prepare_inputs()` in the Runner.

**Why**: `prepare_inputs()` does 5-tier input resolution (CLI params → shell env → settings.env → workflow defaults → error). Calling it from the Runner meant 2-3 calls per execution, with the Runner's call discarding errors. The validator only needs to know WHICH inputs will exist at runtime, not their resolved values.

**Limitation**: After stripping, env-sourced required inputs are absent from the shared store. The compiler's `prepare_inputs` resolves them into `initial_params`, and template resolution uses the `initial_params` override. So `${api_key}` works in templates, but `shared["api_key"]` in a Python code node would fail with `KeyError`. Same behavior MCP had before. Task 135 (seed store after compilation) properly fixes this.

### Template Validation Left the Compiler

**Decision**: Strip `validate_workflow_templates()` from `_prepare_compilation()` but keep `validate_ir_structure()` and `_validate_data_flow_at_compile_time()`.

**Why**: Structure validation is a compiler prerequisite (without it, `ir_dict["nodes"]` crashes). Data-flow validation prevents cycles that hang at runtime. Template validation is a pre-execution UX check — the compiler produces valid Flows regardless, and bad templates fail at runtime with clear errors from `TemplateAwareNodeWrapper`.

**Impact**: 7 tests that expected compile-time template errors needed updating. 4 were routed through `WorkflowValidator.validate()`, 1 through runtime error assertion, 2 through runtime error assertion. The behavior (catching bad templates before execution) is preserved — it moved from compiler to Runner's validation step.

### `validate()` Narrows Exceptions, `run()` Catches Everything

**Decision**: `run()` catches all exceptions (returns `ExecutionResult`). `validate()` catches specific expected exceptions, lets programming bugs propagate.

**Why**: `run()` wraps `flow.run()` which can fail unpredictably. Always returning `ExecutionResult` is the right contract. `validate()` has bounded failure modes — an `AttributeError` here is a bug, not a user error. Catching it returns misleading `ValidationResult(valid=False, errors=["'NoneType'..."])`.

### Dead `validate`/`validate_templates` Parameters Removed

**Decision**: Removed the `validate` parameter from `compile_ir_to_flow()` and `validate_templates` from `_prepare_compilation()` across ~80 test call sites.

**Why**: After template validation moved to the Runner, these booleans gated nothing meaningful. `validate=False` was used by exactly one test pattern (bypassing validation). Removing them simplifies the compiler interface and eliminates a parameter that misleads future agents into thinking they can selectively disable validation steps.

### Technical Debt Incurred

1. **`WorkflowExecutorService` error helpers extracted but not redesigned.** The 7 alive methods (`build_error_list`, `determine_error_category`, etc.) became standalone functions. The error extraction logic itself (priority ordering, MCP result parsing, template field display) wasn't simplified. Future: collapse into a cleaner error builder.

2. **Child workflow compilation warnings not surfaced.** `compile_ir_to_flow()` returns `Flow`, not `(Flow, warnings)`. Warnings from child workflow compilation are silently dropped. Fixing requires a return type change — scope for wrapper chain refactor.

3. **MCP pre-resolves then passes dict to Runner (double-resolution).** MCP `execute_workflow` calls `_unified_resolve(workflow)` to get source/file_path for metadata, then passes `resolved.ir` to `runner.run()`. The Runner sees a dict, calls `normalize_ir()` (no-op since resolver already normalized). Harmless but architecturally redundant.

## Integration Points & Dependencies

### Incoming Dependencies (What Calls the Runner)

| Caller | Method | How |
|--------|--------|-----|
| `cli/main.py:execute_json_workflow` | `WorkflowRunner().run(ir_dict, params, config, output=CliOutput(...), ...)` | Pre-resolves to dict, injects `_pflow_workflow_file` |
| `cli/main.py:execute_json_workflow` (validate-only) | `WorkflowRunner().validate(ir_dict, params, source_file_path=...)` | Same pre-resolution |
| `mcp_server/services/execution_service.py:execute_workflow` | `WorkflowRunner().run(resolved.ir, params, RunnerConfig(), ...)` | Pre-resolves for metadata |
| `mcp_server/services/execution_service.py:validate_workflow` | `WorkflowRunner().validate(workflow, {})` | Passes raw identifier (string) |
| `mcp_server/services/execution_service.py:run_registry_node` | `WorkflowRunner().run(synthetic_ir, {}, RunnerConfig(cache_enabled=False))` | Builds synthetic single-node IR |

### Outgoing Dependencies (What the Runner Calls)

| Component | Via | Notes |
|-----------|-----|-------|
| `execution/workflow_resolver.py` | `resolve_workflow()` | For string inputs only; dict inputs bypass |
| `core/file_resolver.py` | `resolve_file_references()` | Idempotent — compiler also calls it for sub-workflows |
| `core/workflow/validator.py` | `WorkflowValidator.validate()` | Once per execution (the core promise) |
| `runtime/compilation/compiler.py` | `compile_ir_to_flow()` | With new `only_node` parameter |
| `pocketflow` | `flow.run(shared_store)` | The actual execution |
| `core/security_utils.py` | `sanitize_parameters()` | For metadata update |

### Shared Store Keys (New/Changed)

| Key | Set by | Notes |
|-----|--------|-------|
| `__verbose__` | Runner `_initialize_shared_store` | Was `enhanced_params["__verbose__"]` in CLI |
| `__mcp_pool__` | Runner `_initialize_shared_store` | Was `executor_service._initialize_shared_store` |
| `__memoization_cache__` | Runner `_initialize_shared_store` | Same move |
| `_trace_collector` | Runner `_initialize_shared_store` | Same move |
| `__warnings__` | Runner `_initialize_shared_store` | Accumulator for runtime warnings |
| `__execution__` | PocketFlow wrappers | Runner reads `failed_node` from here for exception annotation |

### `ExecutionResult` Field Map

| Field | Source | Consumers |
|-------|--------|-----------|
| `success` | Runner `_determine_status` | CLI exit code, MCP success/error branch |
| `status` | Runner `_determine_status` | CLI exit code 2 for DEGRADED |
| `shared_after` | `flow.run()` result | CLI output detection, MCP output extraction |
| `errors` | Runner `_build_errors` or `_exception_to_result` | CLI `output_error`, MCP `_format_error_result` |
| `warnings` | Runner `_extract_runtime_warnings` | CLI display, MCP `format_execution_success` |
| `validation_warnings` | Runner from `WorkflowValidator.validate()` | CLI stderr + JSON, MCP merged into `warnings=` |
| `trace` | `WorkflowTraceCollector` | CLI `_save_trace_and_report`, MCP derives trace_path |
| `metrics` | `MetricsCollector` | CLI `_handle_workflow_success`, MCP `_format_success_result` |

## Testing Implementation

### Critical Test Cases (catch real bugs)

| Test | What it guards |
|------|----------------|
| `test_validator_called_exactly_once` | Core promise — validation doesn't run twice |
| `test_declared_defaults_applied_without_user_params` | Full `_fill_declared_defaults` → validate → `_strip_placeholders` → `prepare_inputs` pipeline |
| `test_cli_mcp_parity` | CLI and MCP produce equivalent ExecutionResult through same Runner |
| `test_validation_error_prevents_compilation` | Validation failures don't proceed to compilation |
| `test_mcp_warnings_real_workflow` | Validation warnings propagate to ExecutionResult |
| `test_registry_template_resolution` | Templates resolve in synthetic IR (was silently broken before) |
| Pool lifecycle tests (`test_runner_pool_lifecycle`) | MCP pool created and shut down correctly |

### Tests That Document Behavioral Changes

| Test | Old behavior | New behavior |
|------|-------------|--------------|
| `test_typo_in_field_still_errors_despite_optional` | Compile-time `"does not output 'stddout'"` | Runtime `"Unresolved variables...stddout"` |
| `test_validate_only_json_success` | `{"success": true, "status": "valid", "message": "..."}` | `{"success": true, "validated_only": true, "errors": [], "warnings": [...]}` |
| `test_nonexistent_workflow_raises_value_error` | `ValueError` | Still `ValueError` (MCP wraps `WorkflowNotFoundError` with "Did you mean") |

## Patterns Established

### 1. Runner Pattern (Reuse for Any New Execution Path)

```python
runner = WorkflowRunner()
result = runner.run(
    workflow_or_ir,          # str | dict
    params,                  # always copied at boundary
    RunnerConfig(cache_enabled=False),  # frozen dataclass
    output=some_output,      # OutputInterface | None
    workflow_manager=wm,     # for metadata, None to skip
    workflow_name=name,      # for metadata, None to skip
)
# result.success is always set. Never catches exceptions from run().
```

### 2. Resource Lifecycle Rule

Create resources in the scope that has the `finally` block. Never in helper methods.

```python
mcp_pool = None  # Init before try
try:
    mcp_pool = MCPConnectionPool()
    result = self._do_work(mcp_pool)  # pass in, don't create inside
except ...:
    ...
finally:
    if mcp_pool:
        mcp_pool.shutdown()  # Always reachable
```

### 3. Pre-Resolve + Dict Passthrough

When callers need resolution metadata (source, file_path) for their own purposes, they pre-resolve and pass the dict to the Runner:

```python
resolved = resolve_workflow(workflow)       # Caller gets metadata
params["_pflow_workflow_file"] = resolved.file_path  # Inject path
result = runner.run(resolved.ir, params, config)     # Runner sees dict, skips resolution
```

### 4. Exception Annotation for Context Propagation

When an exception crosses a boundary that loses context (like shared_store), annotate it:

```python
try:
    action_result = flow.run(shared_store)
except Exception as e:
    failed_node = shared_store.get("__execution__", {}).get("failed_node")
    if failed_node:
        e._pflow_node_id = failed_node  # Annotation survives the re-raise
    raise
```

### 5. Lazy Import Mock Target Rule

When a function does `from pflow.X import Y` inside its body, mock `pflow.X.Y` (the source module), NOT `pflow.caller_module.Y`. The name never exists on the caller module.

## Anti-Patterns to Avoid

1. **"Defense-in-depth" as a blanket excuse to keep dead code.** Phase 3's initial implementation kept all validation "just in case" — preserving the exact dual-validation bug the task existed to fix.

2. **`'variable_name' in dir()` for local variable checks.** `dir()` lists class/instance attributes, not local variables. Use `variable = None` before `try`, then `if variable is not None:` in `finally`.

3. **Calling `prepare_inputs()` from multiple places.** It does 5-tier resolution with side effects. Every additional call site is a redundancy that discards errors or applies defaults twice. Call it exactly once (in the compiler).

4. **Catching `Exception` in validation paths.** Programming bugs (`AttributeError`, `ImportError`) become misleading validation errors for users/agents. Catch specific expected exceptions only.

## Breaking Changes

| Change | Impact |
|--------|--------|
| Source value `"saved"` → `"library"` | All `ctx.obj["workflow_source"] == "saved"` checks updated |
| Validate-only JSON shape | `{"success", "validated_only", "errors", "warnings"}` replaces `{"success", "status", "message"}` |
| `compile_ir_to_flow()` lost `validate` and `validate_templates` parameters | ~80 test call sites updated |
| Template errors now from WorkflowValidator, not compiler | Error messages slightly different; 4 tests updated |
| `ExecutionResult` gained 3 fields | Backward-compatible (all have defaults) |
| `sanitize_parameters` moved to `core/security_utils` | Old path re-exports for compat |

## Future Considerations

### For Task 135 (Compile-Once)

1. Shared store is seeded BEFORE `prepare_inputs` mutates `initial_params`. Defaults end up in `initial_params` but NOT in shared store. Task 135 must seed store AFTER preparation.
2. `PflowBatchNode` instance state (`self._shared`, `self._errors`, `self._item_timings`) is NOT reset between executions. Safe for Task 138 (recompiles per call). Dangerous for compile-once.
3. `_prepare_compilation` still runs for sub-workflows via `WorkflowExecutor` → `compile_ir_to_flow()`. Mutations must be preserved.

### For Wrapper Chain Refactor

1. Child workflow compilation warnings are silently dropped (requires `compile_ir_to_flow()` return type change).
2. `InstrumentedNodeWrapper` is still 900+ lines with 6+ concerns.
3. Cross-wrapper coupling (`InstrumentedNodeWrapper` reads `TemplateAwareNodeWrapper.last_resolutions`) is action-at-a-distance.

### Extension Points

- **New execution entry point**: Create `RunnerConfig`, call `WorkflowRunner().run()`. That's it.
- **New result field**: Add to `ExecutionResult` with default. Existing consumers unaffected.
- **New error type**: Add branch to `_exception_to_result`. Consider adding to `validate()`'s narrow catch list too.

## AI Agent Guidance

### Quick Start for Related Tasks

1. Read `src/pflow/execution/runner.py` — the 615-line file IS the execution pipeline
2. Read `src/pflow/execution/result.py` — the 4 types define the entire contract
3. Read `src/pflow/execution/CLAUDE.md` — the 137-line doc explains integration
4. For CLI changes: `cli/main.py:execute_json_workflow` (~55 lines) is the thin caller
5. For MCP changes: `mcp_server/services/execution_service.py` has 3 thin methods

### Common Pitfalls

1. **Don't create resources inside helper methods** — create in `run()` scope so `finally` can clean up
2. **Don't add `prepare_inputs()` calls** — it runs once in the compiler, nowhere else
3. **Don't catch `Exception` in `validate()`** — programming bugs should propagate
4. **Don't pass user params as Runner params for registry run** — use empty `{}`, all user params go in `node.params` in synthetic IR (otherwise WorkflowValidator Step 7 flags them as "unknown workflow inputs")
5. **Don't forget `_pflow_workflow_file` injection** — CLI pre-resolves to dict, so the Runner can't derive file_path from resolution. CLI must inject it.

### Mock Points for Testing

| Target | Use case |
|--------|----------|
| `pflow.execution.runner.WorkflowRunner.run` | CLI/MCP integration tests |
| `pflow.execution.runner.WorkflowRunner._compile_and_execute` | Bypass resolution/validation |
| `pflow.runtime.compile_ir_to_flow` | Compilation tests (NOT `pflow.execution.runner.compile_ir_to_flow` — lazy import!) |
| `pflow.core.workflow.validator.WorkflowValidator.validate` | Warning plumbing tests |

---

*Generated from implementation context of Task 138 — Shared Execution Pipeline*
