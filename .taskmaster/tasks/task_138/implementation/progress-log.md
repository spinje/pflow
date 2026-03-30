# Task 138 Implementation Progress Log

## Phase 0 — Dead Code Cleanup

### 2026-03-29 — Phase 0 Complete

**Baseline captured** before any changes: 10 smoke test outputs saved to `.taskmaster/tasks/task_138/baseline/`.

**Starting state**: 4,666 tests passing, `make check` clean.

#### Removed Items

| Item | Lines | Notes |
|------|-------|-------|
| `executor_service.py:_extract_default_output` + 3 helpers | ~90 | Zero production callers confirmed via grep |
| `planning/` directory | 0 | Already removed by Task 92 |
| `core/workflow/__init__.py` re-exports | ~59 | Zero consumers — all imports from submodules |
| `mcp_server/tools/settings_tools.py` | ~173 | Commented out in `__init__.py` |
| `mcp_server/services/settings_service.py` | ~136 | Only served disabled tools |
| `mcp_server/tools/test_tools.py` | ~146 | Commented out in `__init__.py` |
| `mcp_server/utils/validation.py:validate_file_path()` | ~48 | Never called |
| `core/__init__.py` redundant re-exports | ~20 | Reduced from 16 to 5 exports |
| Commented-out references in `server.py`, `tools/__init__.py` | ~10 | Cleaned up dead comments |
| `services/__init__.py` SettingsService import | ~2 | Would have caused ImportError |

**Total removed**: ~620 lines

#### Verification

- ✅ 4,666 tests pass (zero test changes)
- ✅ `make check` clean (lint, mypy, deptry)
- ✅ Smoke tests diff: only timing/timestamps/cache hits differ — zero behavioral changes

#### Also Updated

- `execution/CLAUDE.md` — removed reference to deleted `_extract_default_output()` output priority section

#### Decisions Made

- **`sanitize_parameters()` is NOT dead** — confirmed by code review. Called by `executor_service.py:546`, `workflow_errors.py:84,91`, `error_formatter.py:67,70`. Left in place.
- **`core/__init__.py` kept 5 exports**: `normalize_ir`, `StdinData`, `validate_ir`, `ValidationError`, `FLOW_IR_SCHEMA` — all have consumers via `from pflow.core import` path (src or tests).
- **`PflowError`, `BATCH_CONFIG_SCHEMA`, `detect_binary_content`** confirmed truly dead (zero imports from any path). Removed from re-exports.
- **`core/workflow/__init__.py`** reduced to docstring-only — convention comment pointing to submodule imports.

---

## Pre-Phase 1 Audit (2026-03-30)

### Smoke Test Baseline Expanded

Added 4 HIGH-risk baselines (paths Phase 1 fundamentally rewrites):
- `11-saved-workflow.txt` — CLI named/saved workflow (`pflow test-manual-check`)
- `12-registry-run.txt` — CLI registry run (`pflow registry run shell command="echo smoke-test-baseline"`)
- `13-mcp-execute.txt` — MCP workflow execution via `ExecutionService.execute_workflow()`
- `14-mcp-registry-run.txt` — MCP registry node run via `ExecutionService.run_registry_node()`

MCP baselines recaptured with logging suppressed (timestamps and log formatting make diffs useless). Baselines now show only the tool return value — what an AI agent would see.

### Dead Code: `__cache_chunks__` Removed

`cache_chunks` parameter and `__cache_chunks__` injection removed from `cli/main.py`. Evidence:
- Single call site at line 1101 never passes it (default `None`)
- Zero consumers in runtime/execution/nodes
- Test references in `test_rerun_display.py` are test data only (test generic `__dunder__` filtering, not `__cache_chunks__` specifically) — left unchanged

3 production lines removed. 4,666 tests pass, `make check` clean.

### MCP Execution Baseline Tests Added

`ExecutionService.execute_workflow()` had **zero test coverage** — the most critical MCP method that Phase 1 rewrites. Added 5 tests in `tests/test_mcp_server/test_execution_workflow.py`:

| Test | Behavior |
|------|----------|
| `test_file_workflow_returns_success_string` | File path → success `str` with `"✓"` |
| `test_library_workflow_returns_success_string` | Saved name → resolves from library, success `str` |
| `test_nonexistent_workflow_raises_value_error` | Unknown name → `ValueError` with "not found" |
| `test_unknown_node_type_raises_validation_error` | Bad node type → `RuntimeError` with type name |
| `test_failing_command_raises_runtime_error` | `exit 1` → `RuntimeError` |

**Exception contract finding**: The docstring claims `ValueError` for "workflow not found or parameters invalid." In practice, validation errors raised inside the `try` block (line 333) are caught by the broad `except Exception` handler (line 368) and re-wrapped as `RuntimeError`. The actual contract is:
- `ValueError` — **only** for "workflow not found" (raised before the `try` block at line 305)
- `RuntimeError` — **everything else**: validation failures, execution failures, unexpected errors

**Impact on Phase 1**: After Phase 1, the Runner always returns `ExecutionResult`. MCP converts all failures to `RuntimeError`. The only visible change: "not found" goes from `ValueError` to `RuntimeError`. AI agents consuming MCP don't care — the MCP protocol returns error text, not Python exception types. The error message still says "not found" with suggestions. `test_nonexistent_workflow_raises_value_error` will flag this change; we update it consciously.

4,671 tests pass (4,666 + 5 new), `make check` clean.

### Assumption Audit Results

8 review agents verified 10 design assumptions against current code:

**Confirmed (8/10):**
- `WorkflowNotFoundError` with `similar_names` — exists at `core/exceptions.py:18`
- `display_validation_warnings()` — exactly 2 call sites confirmed
- `_load_settings_env()` — 2 definitions, 2 call sites (duplicated code)
- `_handle_execution_exception()` re-raises `CompilationError` and `RuntimeError` — confirmed
- `WorkflowExecutorService` single public method — confirmed
- `OutputInterface`, `NullOutput`, `CliOutput` — all exist as designed

**Corrected (2/10):**
1. **`RecursionError` does NOT escape both layers** — caught by `executor_service.py`'s `except Exception` catch-all, wrapped into error dict. NOT re-raised. The Runner still catches it but the original claim "unhandled today" was wrong — it's handled (with a generic error category).
2. **`_prepare_compilation()` doesn't exist yet** — it's the rename target of `_validate_workflow()`. Pipeline ordering constraint is correct for the *current* function name.

**New findings:**
- `ValidationResult` type doesn't exist — must be created
- `_suppress_logging_in_json_mode()` referenced in "CLI after" sketch doesn't exist — it's inline code at 2 different severity levels
- `__cache_chunks__` was dead code — removed (see above)
- `__env_param_names__` is a pipeline artifact (produced by `prepare_inputs()`, consumed by metadata redaction), not a config value
- `resolve_file_references()` runs redundantly in CLI (before validation AND inside compiler)
- `@ensure_stateless` is a no-op — logs only, prevents nothing

### Ambiguity Resolution (2026-03-30)

4 remaining items resolved through code tracing and discussion.

**1. Logging suppression → CLI keeps it**

Logging suppression is caller-specific display policy, not execution logic. Evidence:
- All logging goes to **stderr** (both CLI and MCP). JSON stdout contamination is not a real risk.
- `OutputInterface` / `NullOutput` / `CliOutput` have **zero relationship** to Python logging — they're separate systems.
- MCP intentionally leaves INFO logging on stderr (diagnostic channel for stdio transport, doesn't contaminate tool responses).
- CLI has two overlapping inline suppression sites (`workflow_command` sets ERROR with restore, `execute_json_workflow` escalates to CRITICAL without restore). These collapse to one site in the CLI, outside the Runner.
- Runner never touches logging. Caller configures before calling Runner — same as how `CliOutput` is configured by the caller.

**2. `ValidationResult` → Minimal internal type, rich agent-facing JSON**

Internal type wraps `WorkflowValidator.validate()` return directly:
```python
@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]
    warnings: list[ValidationWarning]
```

Agent-facing JSON output (converted by CLI/MCP display layer):
```json
{
  "success": true,
  "validated_only": true,
  "errors": [],
  "warnings": [
    {
      "node": "process-data",
      "node_type": "mcp-github-search",
      "template": "${fetch.response.items}",
      "message": "Output 'response' from 'fetch' has type 'Any' — nested access '.items' cannot be validated before execution"
    }
  ]
}
```

Failure:
```json
{
  "success": false,
  "validated_only": true,
  "errors": [
    {"message": "Workflow requires input 'github_token': ...", "category": "validation"}
  ],
  "warnings": []
}
```

Design rationale:
- Consuming AI agents get: `success` (can I run this?), `errors` (what's wrong, how to fix), `warnings` (what might fail at runtime, with node + template + reason).
- Consuming AI agents do NOT get: `output_type`, `nested_path`, `output_key` (pflow internals from `ValidationWarning` — implementation details).
- Internal type carries everything; display layer selects what to expose. Conversion is a one-place function per entry point.
- Fixes existing bugs: warnings lost in all JSON paths today, MCP discards warnings entirely.

**3. `resolve_file_references()` → Defense-in-depth, keep compiler's internal call**

Evidence from code tracing:
- **Sub-workflow child IR is ONLY resolved by the compiler's internal call** (`compiler.py:721`). Child IR is loaded fresh from `.pflow.md` at runtime inside `WorkflowExecutor`, long after the parent's pre-compilation resolution. Removing the compiler's call would break child file references.
- `resolve_file_references()` is **idempotent** — proven by test at `test_file_resolver.py:270`. After first resolution, content no longer matches `is_file_reference()` heuristic (contains newlines/spaces/parsed to non-string). Second call is a no-op.
- MCP's `_check_inline_file_references()` is a **guard** (detects unresolvable refs in inline workflows), NOT a resolver. Completely different function.
- Runner calls pre-compilation (for the validate path where compilation doesn't happen). Compiler keeps internal call (for sub-workflows). Double-call on parent IR is idempotent and harmless.

**4. `__env_param_names__` → Metadata update stays inside Runner**

Evidence from code tracing:
- `_update_workflow_metadata()` is **already inside** the execution pipeline at `executor_service.py:126` — called between `flow.run()` and exception handling. It's not a post-execution caller concern today.
- Both CLI and MCP already control it through constructor args: CLI passes `workflow_manager=None` for non-saved workflows, MCP passes `workflow_name=None` for non-library. The "policy decision" is expressed through what the caller passes, not by the caller doing the update.
- `env_param_names` is produced by `prepare_inputs()` and consumed by `sanitize_parameters()` — both will live inside the Runner. Keeping metadata update inside means `env_param_names` is a local variable that never surfaces to callers.
- Moving metadata update out would force every caller to: extract `env_param_names`, call `sanitize_parameters` correctly, call `update_metadata`. That's security plumbing that should be invisible — getting it wrong silently leaks secrets to disk.
- `sanitize_parameters` currently lives in `mcp_server/utils/errors.py` — an architectural inversion (execution layer imports from MCP server). Runner absorbing this fixes the dependency direction.

Trace saving is fundamentally different: it involves user-facing file paths, optional report generation, and CLI-specific display ("Trace saved to: ..."). Metadata update is a fire-and-forget side effect gated by a kwarg.

---

## Phase 1 — Shared WorkflowRunner

### Design Decisions (locked 2026-03-29, updated 2026-03-30)

8 review agents analyzed all 10 questions. Full synthesis in `design-review-synthesis.md`. Original decisions below, with updates marked.

**Q1 — Runner config: Frozen dataclass, kwargs for collaborators**
- `@dataclass(frozen=True)` for immutable scalars: `trace_enabled`, `cache_enabled`, `verbose`, `only_node`, `output_format`, `source_file_path`
- Per-call kwargs: `output: OutputInterface | None`, `workflow_manager: WorkflowManager | None`, `workflow_name: str | None` *(updated: was single kwarg, now includes metadata update collaborators)*
- Runner creates `MetricsCollector` and `TraceCollector` internally — per-execution, no one customizes these, results exposed via `ExecutionResult`
- `__no_cache__` becomes config-only — no more popping from params dict

**Q2 — Validate-only: Separate method `runner.validate()` → `ValidationResult`**
- `runner.validate(ir, params) → ValidationResult(valid, errors, warnings)`
- `runner.run(ir, params, config, **kwargs) → ExecutionResult`
- Validate-only intentionally skips `prepare_inputs()` — separate method makes this enforced, not conditional
- `ValidationResult` is minimal: `valid: bool`, `errors: list[str]`, `warnings: list[ValidationWarning]`
- CLI/MCP convert to agent-facing JSON with `"validated_only": true`, actionable error messages, and structured warnings (node, node_type, template, message)
- No more `sys.exit()` bypass — CLI handles exit codes from structured result
- Fixes existing bugs: warnings lost in all JSON paths, MCP discards warnings entirely

**Q3 — CLI boundary: CLI reads stdin, hands clean params to Runner (Option A)**
- CLI reads stdin via `read_stdin_content()`, finds `stdin: true` input, puts value in params dict
- Runner receives complete params — never knows about stdin
- Ordering preserved: stdin value in params before `runner.run()` calls validation
- Simpler, no stdin concept in Runner API. MCP can add `stdin_data` param later if needed

**Q4 — Merged resolver: Raise on error, return `(ir, source)` — ANSWER FIRST**
- `resolve_workflow(identifier: str | dict) → tuple[dict, str]`
- Raises `WorkflowNotFoundError`, `MarkdownParseError`, `PermissionError` on failure
- MCP gains "Did you mean" suggestions it currently lacks (via `WorkflowNotFoundError.similar_names`)
- Must `normalize_ir()` in ALL resolution paths (file, library, dict, raw markdown)
- Always returns fresh dict (never cached reference) — concurrency safety

**Q5 — Registry run: Full — synthetic IR through Runner**
- Build single-node IR, call `runner.run()` — less code than Medium, zero special-casing
- Gets template resolution, tracing, metrics, error handling for free
- Output handling (structure mode, execution caching, `node_output_formatter`) stays in `registry_run.py` — output is a display concern, not execution
- `action` return from `node.run()` replaced by `result.success` check
- Eliminates registry run as a separate execution path — same argument as the whole task

**Q6 — MCP service classes: Shrink, don't flatten**
- Keep `@classmethod` + `@ensure_stateless` as defense-in-depth guardrail
- Each service method becomes 10-20 lines: construct config, call Runner, format result
- Remove `BaseService` if it provides no shared behavior
- Fresh `Registry()` per call prevents stale node metadata — concurrency safety

**Q7 — Validation warnings: Return from `_prepare_compilation()`, never print**
- Change return type: `_prepare_compilation() → tuple[dict, list[str]]` (params + warnings)
- Remove `display_validation_warnings()` call from inside compiler
- Runner collects warnings from both `WorkflowValidator.validate()` and `_prepare_compilation()`
- Routes through `OutputInterface` — fixes: MCP silently losing warnings, double-emission in verbose, stderr pollution in JSON mode
- Note: TWO call sites exist today — compiler (`compile_validation.py:265`) AND validate-only path (`cli/main.py:399`)

**Q8 — Settings env: Runner loads once, passes as parameter**
- `_load_settings_env()` moves to Runner, called once per `run()` invocation
- Result passed to `_prepare_compilation(settings_env=...)` as explicit parameter
- Sub-workflows: `_prepare_compilation()` still calls its own load for child workflows (Runner isn't in sub-workflow path)
- MCP gains settings_env loading it currently skips — new behavior, needs test
- Never cache at module level — load fresh per call

**Q9 — Exceptions: Single layer, always return `ExecutionResult`**
- Runner catches all exceptions at its boundary, wraps into `ExecutionResult.errors`
- Callers (CLI, MCP) always receive `ExecutionResult`, never raw exceptions from `runner.run()`
- Wrapped types: `CompilationError`, `MaxNodeVisitsError`, `ValueError`, `RuntimeError`, `WorkflowValidationError`, `RecursionError`, `MarkdownParseError`, `WorkflowNotFoundError`
- Propagated through: `KeyboardInterrupt`, `SystemExit`
- `finally` for MCP pool shutdown: **non-negotiable** — must survive any restructuring
- Use `_exception_to_errors()` dispatch table from `error_output.py` as canonical error conversion
- Correction: `RecursionError` is already caught by `executor_service.py`'s `except Exception` catch-all (not "unhandled" as originally claimed). Runner still catches it but with proper error category.

**Q10 — Resolver location: `execution/workflow_resolver.py`**
- Sibling to `executor_service.py` and `workflow_execution.py`
- Zero new dependency edges — both CLI and MCP already import from `execution/`
- Preserves `source` return value distinction (`"file"` vs `"library"`) for `_inject_workflow_file_path()`
- `.json` extension validation with migration hint preserved (currently CLI-only, benefits MCP too)

### Runner Boundary Principle (locked 2026-03-29, revised 2026-03-30)

**The Runner is an execution pipeline** — it transforms inputs into results. It owns the execution resource lifecycle (create + cleanup MCP pools, caches, LLM interceptions, metrics, traces) and fire-and-forget side effects controlled by caller-provided collaborators. It does NOT own presentation or user-facing persistence.

| Concern | Owner | Why |
|---------|-------|-----|
| MetricsCollector creation | **Runner** | Per-execution, no one customizes, results in `ExecutionResult.metrics` |
| TraceCollector creation | **Runner** | Per-execution, Runner knows workflow_name from resolution |
| Trace **saving** to disk | **Caller** | User-facing (path display, report generation). Runner returns trace data. |
| Metadata update | **Runner** | Security (env param sanitization co-located with data). Caller controls via `workflow_manager` kwarg — pass `None` for no-op. |
| MCP pool + LLM interception cleanup | **Runner** (finally) | Runner creates these, Runner cleans them up |
| Temp file cleanup (stdin) | **CLI** | CLI creates temp files, CLI cleans them up |
| OutputInterface | **Caller** (kwarg) | Display policy differs per entry point |
| Logging suppression | **Caller** | Caller-specific display policy (CLI JSON mode vs MCP stderr) |
| Report generation | **Caller** | Presentation concern — CLI-only feature |

**Why trace saving is a caller concern but metadata update is not**: Trace saving involves user-facing file paths, optional report generation, and CLI-specific display ("Trace saved to: ..."). Metadata update is a fire-and-forget side effect that requires security-critical `sanitize_parameters()` with `env_param_names` — data that's produced and consumed entirely within the Runner. Moving it out would force callers to replicate security plumbing, with silent secret leaks on failure.

**Runner API**:
```python
class WorkflowRunner:
    def run(
        self,
        workflow: str | dict,          # file path, saved name, raw markdown, or IR dict
        params: dict[str, Any],
        config: RunnerConfig,
        *,
        output: OutputInterface | None = None,
        workflow_manager: WorkflowManager | None = None,
        workflow_name: str | None = None,
    ) -> ExecutionResult:
        ...

    def validate(
        self,
        workflow: str | dict,
        params: dict[str, Any],
        source_file_path: Optional[str] = None,
    ) -> ValidationResult:
        ...
```

**CLI after** (~25 lines):
```python
def execute_json_workflow(ctx, ir_data, stdin_data=None, output_key=None,
                          execution_params=None, output_format="text"):
    params = execution_params or {}
    if stdin_data:
        _route_stdin_to_params(ir_data, params, stdin_data)

    if ctx.obj.get("validate_only"):
        vresult = WorkflowRunner().validate(ir_data, params,
            source_file_path=ctx.obj.get("source_file_path"))
        _display_validation_result(ctx, vresult, output_format)
        return

    config = RunnerConfig(
        trace_enabled=not ctx.obj.get("no_trace"),
        cache_enabled=ctx.obj.get("cache", True),
        verbose=ctx.obj.get("verbose") and output_format != "json",
        only_node=ctx.obj.get("only_node"),
        output_format=output_format,
        source_file_path=ctx.obj.get("source_file_path"),
    )

    result = WorkflowRunner().run(ir_data, params, config,
        output=CliOutput(ctx.obj["output_controller"], config.verbose, output_format),
        workflow_manager=WorkflowManager() if ctx.obj.get("workflow_source") == "saved" else None,
        workflow_name=ctx.obj.get("workflow_name"))

    # Trace saving — caller's job (user-facing path display + optional report)
    if result.trace and config.trace_enabled:
        trace_path = result.trace.save_to_file()
        _echo_trace(ctx, trace_path)

    # Display
    _display_execution_result(ctx, result, output_key, ir_data, output_format)
```

**MCP after** (~12 lines):
```python
@classmethod
@ensure_stateless
def execute_workflow(cls, workflow, parameters=None):
    workflow_name = str(workflow) if source == "library" else None
    result = WorkflowRunner().run(workflow, parameters or {}, RunnerConfig(),
        workflow_manager=WorkflowManager(), workflow_name=workflow_name)
    if result.success:
        return format_success_as_text(_format_success_result(result))
    else:
        raise RuntimeError(_build_error_text(_format_error_result(result)))
```

### Key Findings from Review (new, not in original spec)

1. **MCP passes `{}` not `None` to `WorkflowValidator.validate()`** — template validation runs against empty params, fails on workflows with required inputs. Runner must populate dummy params for declared inputs.
2. **`display_validation_warnings()` has TWO call sites** — compiler + validate-only path. Both must be addressed.
3. **Test migration scope larger than spec**: `test_workflow_resolution.py` (8+14 patches), `test_template_resolution_hardening.py` (13 imports), `test_connection_pool.py` (3 instantiations) not in spec's migration list.
4. **`RecursionError` is already caught** by `executor_service.py`'s `except Exception` catch-all (originally claimed "unhandled" — corrected during audit). Handled with generic error category. Runner catches it with proper categorization.
5. **`execute_json_workflow()` is the real consumer** — the spec doesn't name it but Runner config must absorb everything it constructs.
6. **Batch child workflow template validation gap widens slightly** — stripping compiler's `validate_workflow_templates()` means child `${item.field}` only validated against dummy params. Pre-existing gap, flag in implementation.
7. **`PflowBatchNode` instance state not reset between executions** — safe for Task 138 (recompiles per call), dangerous for Task 135 (compile-once). Document explicitly.
8. **Runner should copy params at boundary** — `_params = dict(params)` makes every call mutation-safe from caller's perspective.
9. **`__cache_chunks__` was dead code** — removed during pre-Phase 1 audit. Zero consumers, never passed at the only call site.
10. **`sanitize_parameters` lives in `mcp_server/utils/errors.py`** — architectural inversion (execution layer imports from MCP server). Runner absorbing metadata update fixes the dependency direction. Consider moving `sanitize_parameters` to `core/security_utils.py` alongside `SENSITIVE_KEYS`.

### Implementation Steps

1. ~~Design `WorkflowRunner.run()` signature and config object~~ → decisions locked
2. ~~Resolve open design questions with user~~ → 10 questions locked
3. ~~Show concrete before/after for CLI and MCP~~ → approved
4. ~~Define Runner boundary principle~~ → metadata update inside Runner, trace saving with caller
5. Merge two `resolve_workflow()` functions into one (`execution/workflow_resolver.py`)
6. Strip duplicated validation from `_validate_workflow()` → rename to `_prepare_compilation()`
7. Implement `WorkflowRunner` — absorb `WorkflowExecutorService` + `execute_workflow()`
8. Thin down `cli/main.py` to Click handler + Runner call
9. Thin down MCP `execution_service.py` to async wrapper + Runner call
10. Route registry run through Runner with synthetic IR
11. Migrate affected tests (10-13 test files — expanded list from review)
12. Add new tests: CLI/MCP parity, validator-called-once guard, registry template resolution
13. Verify: `make test && make check`, smoke test diffs, manual spot checks

### Pre-Implementation Audit (2026-03-29)

9 parallel agents (4 codebase searchers, 5 review agents) verified assumptions and analyzed design gaps.

#### Verification Results (Items 4–7)

**Item 4 — ExecutionResult shape verified.** Current fields: `success`, `status`, `shared_after`, `errors`, `warnings` (all `list[dict]`). Located at `executor_service.py:18-26`. Missing for Runner: `trace` (currently in `shared_after["_trace_collector"]`), `metrics` (currently passed as separate arg). `ValidationResult` doesn't exist yet. 3 construction sites, ~15 consumer access points identified.

**Item 5 — `only_node` threading traced.** Full chain: CLI `ctx.obj["only_node"]` → `enhanced_params["__only_node__"]` → filtered from shared store but kept in `initial_params` → compiler reads at `compiler.py:770` → `_apply_only_node_stop()` monkey-patches `flow.get_next_node`. Validation layers don't touch it. **Decision: Option A** — add `only_node: Optional[str] = None` parameter to `compile_ir_to_flow()`. One line in signature, default `None` means sub-workflows and tests need zero changes. Eliminates the filter hack in `_initialize_shared_store()`.

**Item 6 — MCP type coercion confirmed safe.** MCP already gets `prepare_inputs()` via compiler's `_validate_workflow()`. The `context.update(initial_params)` override means template resolution end results are identical today. Moving `prepare_inputs()` earlier only changes: shared store has correct types from the start, earlier error detection. JSON params from AI agents are natively typed — coercion is a no-op for well-typed inputs. No breakage risk.

**Item 7 — Sub-workflow validation gap: none.** `WorkflowValidator` Step 8 runs the full 8-step pipeline recursively on children, including `validate_data_flow(check_inputs=True)` — stricter than the compiler's `check_inputs=False`. Only cosmetic gap: template validation uses dummy params instead of actual child values (structural check, not value check). All `_prepare_compilation()` mutations continue for children. No previously-caught error would go undetected.

#### Design Gap Resolutions (from 5 review agents)

**Gap 1 — Warnings: Two separate fields on `ExecutionResult`** *(updates Q7, Q9)*

Three problems found by all 5 agents:
- Type collision: `ExecutionResult.warnings` is `list[dict]`, `ValidationWarning` is a dataclass. `success_formatter.py:240` calls `warning.get("node_id")` — crashes on dataclass objects.
- OutputInterface-only routing contradicts Q9 ("always return ExecutionResult"). JSON/MCP consumers never see warnings through display channel alone.
- Child workflow compilation warnings silently dropped: `compile_ir_to_flow()` returns `Flow`, not `(Flow, warnings)`. After `_prepare_compilation()` returns warnings instead of printing, the compiler discards them.

**Resolution:**
- Keep existing `warnings: list[dict[str, Any]]` for runtime warnings (API degradation, template errors) — no change.
- Add `validation_warnings: list[dict[str, Any]]` for pre-execution warnings — new field, converted from `ValidationWarning` objects at Runner boundary. Dict shape: `{"node": ..., "node_type": ..., "template": ..., "message": ...}` — same as `ValidationResult.warnings` JSON shape, so validate-only and execution are consistent.
- Warnings go into `ExecutionResult` (authoritative) AND through `OutputInterface` (real-time display).
- Runner deduplicates validation warnings by `(node_id, template)` before storing — prevents N identical warnings from batch compilations.
- **Child workflow warnings: known limitation for Phase 1.** Fixing requires `compile_ir_to_flow()` return type change or shared-store accumulator — scope creep. Current behavior (print to stderr) is also lossy for JSON/MCP. Document explicitly; address in wrapper chain refactor.

**Gap 2 — Resolver return type: `ResolvedWorkflow` dataclass** *(updates Q4, Q1)*

Problem: `_inject_workflow_file_path()` needs the actual file path. Current resolvers return semantic labels ("file"/"library"), not paths. Runner resolves internally for string inputs but gets no path back.

**Resolution:**
- Merged resolver returns `ResolvedWorkflow(ir: dict, source: str, file_path: Optional[str])` frozen dataclass.
  - `source`: `"file"`, `"library"`, `"content"`, `"direct"`
  - `file_path`: absolute path for file/library sources, `None` for content/direct
- **Remove `source_file_path` from `RunnerConfig`** — redundant when Runner resolves internally. Dual source of truth is a bug magnet. Runner reads `file_path` from `ResolvedWorkflow`.
- Keep `source_file_path` as explicit param on `runner.validate()` — caller may have pre-resolved.
- Fixes MCP sub-workflow relative path bug as side effect.

Updated `RunnerConfig`:
```python
@dataclass(frozen=True)
class RunnerConfig:
    trace_enabled: bool = True
    cache_enabled: bool = True
    verbose: bool = False
    only_node: Optional[str] = None
```

**Gap 3 — `output_format` removed from `RunnerConfig`** *(updates Q1)*

Unanimous across all 5 agents. Zero reads of `output_format` in `runtime/` or `execution/`. `verbose` already encodes JSON-mode suppression (`verbose and output_format != "json"` computed by caller). `OutputInterface` (`CliOutput`) already carries format awareness. Keeping it invites the exact coupling this task eliminates.

**Resolution:** Removed. `RunnerConfig` has 4 fields: `trace_enabled`, `cache_enabled`, `verbose`, `only_node`.

**Gap 8 — CLI function inventory: 7 concrete items** *(refines implementation steps)*

| Item | Issue | Resolution |
|------|-------|------------|
| `_prepare_execution_environment()` | Straddles Runner boundary — creates both `CliOutput` (CLI concern) and `TraceCollector` (Runner concern) | **Split**: CLI keeps `CliOutput`/`DisplayManager` creation. Runner creates `TraceCollector`, `MetricsCollector`, `MemoizationCache`, `MCPConnectionPool`. |
| `compiler.py:731` unpacking | When `_validate_workflow()` return type changes to tuple, `initial_params = _validate_workflow(...)` silently assigns tuple to `initial_params`. `initial_params["__template_resolution_mode__"]` then fails with `TypeError`. | Add to implementation checklist. Must unpack: `initial_params, comp_warnings = _prepare_compilation(...)`. |
| `total_nodes` for `--report` | CLI reads `len(ir_data.get("nodes", []))` before execution. After Runner resolves internally, CLI may not have IR. | CLI computes from IR before calling Runner (IR available in "after" sketch as it's passed to `runner.run()`). Not a problem when CLI pre-resolves for stdin routing. |
| `warnings.filterwarnings("ignore")` | PocketFlow "Flow ends" noise suppression at `main.py:604`. Not in "after" sketch. | Keep in CLI wrapper before `runner.run()` call. |
| Registry run + cache | After Phase 1, registry run gains memoization via Runner. Defeats discovery purpose — cached results instead of fresh execution. | `RunnerConfig(cache_enabled=False)` for registry run. |
| `validate_execution_parameters()` | MCP security check for registry run params (code injection detection). Unclear placement after Runner. | MCP caller validates before building synthetic IR and calling Runner. Security check stays at system boundary. |
| `KeyboardInterrupt` before result | "CLI after" sketch accesses `result.trace` in finally — `result` may not exist if `KeyboardInterrupt` fires before Runner returns. | Guard with `trace = result.trace if 'result' in locals() else None`. |

#### Updated Runner API

```python
@dataclass(frozen=True)
class RunnerConfig:
    trace_enabled: bool = True
    cache_enabled: bool = True
    verbose: bool = False
    only_node: Optional[str] = None

@dataclass(frozen=True)
class ResolvedWorkflow:
    ir: dict[str, Any]
    source: str                         # "file", "library", "content", "direct"
    file_path: Optional[str] = None     # Absolute path for file/library, None for content/direct

@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]
    warnings: list[dict[str, Any]]      # Same shape as ExecutionResult.validation_warnings

class WorkflowRunner:
    def run(
        self,
        workflow: str | dict,          # file path, saved name, raw markdown, or IR dict
        params: dict[str, Any],
        config: RunnerConfig,
        *,
        output: OutputInterface | None = None,
        workflow_manager: WorkflowManager | None = None,
        workflow_name: str | None = None,
    ) -> ExecutionResult:
        ...

    def validate(
        self,
        workflow: str | dict,
        params: dict[str, Any],
        *,
        source_file_path: Optional[str] = None,
    ) -> ValidationResult:
        ...
```

Updated `ExecutionResult`:
```python
@dataclass
class ExecutionResult:
    success: bool
    status: WorkflowStatus = WorkflowStatus.SUCCESS
    shared_after: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)              # runtime: API degradation, template errors
    validation_warnings: list[dict[str, Any]] = field(default_factory=list)   # pre-execution: type-unknown templates
    trace: Optional[Any] = None                                               # WorkflowTraceCollector, if trace_enabled
    metrics: Optional[Any] = None                                             # MetricsCollector
```

#### Updated CLI "after" sketch (~30 lines)

```python
def execute_json_workflow(ctx, ir_data, stdin_data=None, output_key=None,
                          execution_params=None, output_format="text"):
    params = dict(execution_params or {})  # copy at boundary
    if stdin_data:
        _route_stdin_to_params(ir_data, params, stdin_data)

    if ctx.obj.get("validate_only"):
        vresult = WorkflowRunner().validate(ir_data, params,
            source_file_path=ctx.obj.get("source_file_path"))
        _display_validation_result(ctx, vresult, output_format)
        return

    config = RunnerConfig(
        trace_enabled=not ctx.obj.get("no_trace"),
        cache_enabled=ctx.obj.get("cache", True),
        verbose=ctx.obj.get("verbose") and output_format != "json",
        only_node=ctx.obj.get("only_node"),
    )

    # Suppress PocketFlow "Flow ends" warnings in non-verbose mode
    if not config.verbose:
        warnings.filterwarnings("ignore", message="Flow ends:*", module="pflow.pocketflow")

    result = WorkflowRunner().run(ir_data, params, config,
        output=CliOutput(ctx.obj["output_controller"], config.verbose, output_format),
        workflow_manager=WorkflowManager() if ctx.obj.get("workflow_source") == "saved" else None,
        workflow_name=ctx.obj.get("workflow_name"))

    # Trace saving — caller's job (user-facing path display + optional report)
    trace = result.trace if 'result' in locals() else None
    if trace and config.trace_enabled:
        trace_path = trace.save_to_file()
        _echo_trace(ctx, trace_path)

    # Display
    _display_execution_result(ctx, result, output_key, ir_data, output_format)
```

#### Updated MCP "after" sketch (~12 lines)

```python
@classmethod
@ensure_stateless
def execute_workflow(cls, workflow, parameters=None):
    resolved = resolve_workflow(workflow)  # raises on error
    workflow_name = str(workflow) if resolved.source == "library" else None
    result = WorkflowRunner().run(workflow, parameters or {}, RunnerConfig(),
        workflow_manager=WorkflowManager(), workflow_name=workflow_name)
    if result.success:
        return format_success_as_text(_format_success_result(result))
    else:
        raise RuntimeError(_build_error_text(_format_error_result(result)))
```

#### Updated Implementation Checklist

1. ~~Design `WorkflowRunner.run()` signature and config object~~ → decisions locked
2. ~~Resolve open design questions with user~~ → 10 questions + 4 gaps locked
3. ~~Show concrete before/after for CLI and MCP~~ → approved (updated above)
4. ~~Define Runner boundary principle~~ → metadata update inside Runner, trace saving with caller
5. Create `ResolvedWorkflow`, `ValidationResult`, `RunnerConfig` types in `execution/result.py`
6. Move `ExecutionResult` to `execution/result.py` (stable home), add `validation_warnings`, `trace`, `metrics` fields
7. Merge two `resolve_workflow()` functions into `execution/workflow_resolver.py` — returns `ResolvedWorkflow`
8. Strip duplicated validation from `_validate_workflow()` → rename to `_prepare_compilation()` → returns `tuple[dict, list[ValidationWarning]]`
9. **Update `compiler.py:731`** — unpack tuple: `initial_params, comp_warnings = _prepare_compilation(...)`
10. Add `only_node: Optional[str] = None` parameter to `compile_ir_to_flow()`
11. Implement `WorkflowRunner` — absorb `WorkflowExecutorService` + `execute_workflow()`, single exception boundary, `finally` for MCP pool + LLM interception cleanup
12. **Split `_prepare_execution_environment()`** — CLI keeps `CliOutput`/`DisplayManager`, Runner creates `TraceCollector`/`MetricsCollector`/`MemoizationCache`/`MCPConnectionPool`
13. Thin down `cli/main.py` to Click handler + Runner call (keep `warnings.filterwarnings`, stdin routing, logging suppression, trace saving, display)
14. Thin down MCP `execution_service.py` to async wrapper + Runner call (`validate_execution_parameters()` stays in MCP caller)
15. Route registry run through Runner with synthetic IR — `RunnerConfig(cache_enabled=False)`
16. Migrate affected tests (~13 test files — expanded list from review)
17. Add new tests: CLI/MCP parity, validator-called-once guard, registry template resolution, MCP gains warnings
18. Verify: `make test && make check`, smoke test diffs, manual spot checks

**Known limitations (Phase 1, documented):**
- Child workflow compilation warnings not surfaced in `ExecutionResult.validation_warnings` — requires `compile_ir_to_flow()` return type change. Address in wrapper chain refactor.
- Batch child template validation uses dummy params at pre-execution time (pre-existing, slightly wider gap).

### Plan Review (2026-03-30)

8 review agents reviewed the implementation plan. 12 critical issues found in plan code snippets — all fixed in the plan before handoff.

**Critical fixes applied to plan** (code snippet bugs that would crash at runtime):
1. `'metrics_collector' in dir()` → broken Python. Fixed: init `None` before try, use `is not None` in finally.
2. Validation ordering regression: `_validate()` ran before `prepare_inputs()` → false errors for workflows with defaults. Fixed: added `_enrich_params_with_defaults()` call before validation in `run()`.
3. `__verbose__` missing from shared store → MCP nodes lose verbose mode. Fixed: inject in `_initialize_shared_store()`.
4. `output_error()` called with nonexistent `errors=` kwarg. Fixed: pass `result=result` and `ctx`.
5. `display.show_execution_start()` wrong args (takes int, not ir+name). Fixed.
6. `WorkflowValidationError(errors)` passes list as `summary` string. Fixed: use `validation_errors=` kwarg.
7. Source `"saved"` → `"library"` breaks `ctx.obj["workflow_source"]` check. Fixed throughout CLI.
8. LLM interception cleanup missing from Runner `finally`. Fixed: added `trace_collector.cleanup_llm_interception()`.
9. `Registry.get_node_info()` doesn't exist + `format_node_not_found_error` takes `list[str]` not `Registry`. Fixed.
10. `execution_id=""` breaks `read_fields` MCP caching. Fixed: generate via `ExecutionCache`.
11. Registry run synthetic IR: all params flagged as "unknown workflow inputs". Fixed: pass `{}` as Runner params.
12. `_build_error_text` missing `trace_path` param in new MCP code. Fixed.

**Test migration additions** (from review):
- `test_validate_only.py` JSON shape tests moved to Tier 1 (will break, not just "verify")
- `test_api_warning_system.py` added to Tier 1 (3 direct instantiations, was missing)
- `test_registry_run_mcp.py` added to Tier 4 (stale mocks after registry run rewrite)
- `test_nested_workflow_cli.py` added to Tier 3 (patches old resolver path)
- `"saved"` → `"library"` assertion updates noted for `test_workflow_resolution.py`

**New test improvements** (from review):
- Parity test: assert output values, not just key presence
- Validator guard: test behavior (compilation blocked on error), not call count
- Registry template: correct namespace (workflow params, not duplicated in node params)

### Implementation Plan

Full atomic plan at `.taskmaster/tasks/task_138/implementation/implementation-plan.md` — 10 phases, all code snippets review-corrected, ready for implementing agent.

### Status: Implementation in progress (handed off to implementing agent)
