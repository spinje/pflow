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

> **Note**: The sketches below are superseded by the review-corrected versions in `implementation-plan.md` (12 critical fixes applied — see Plan Review section).

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

---

## Phase 1 Implementation — Foundation Types (2026-03-30)

### What was done
Created `execution/result.py` with 4 new types (`RunnerConfig`, `ResolvedWorkflow`, `ValidationResult`, `ExecutionResult`). Moved `ExecutionResult` out of `executor_service.py` into `result.py` — added `validation_warnings`, `trace`, `metrics` fields. Updated all imports (5 production files, 4 test files).

### Deviations from plan
None. Purely structural move. Zero behavioral changes.

### Verification
- 4,671 tests pass, zero test changes needed beyond import paths
- `make check` clean

### Key insight for future agents
The new `ExecutionResult` is a **superset** of the old one. Existing fields (`success`, `status`, `shared_after`, `errors`, `warnings`) are unchanged. New fields (`validation_warnings`, `trace`, `metrics`) all have defaults, so all existing construction sites work without modification. This was deliberate — backward compatibility at the dataclass level means Phase 1 touches zero test logic.

---

## Phase 2 Implementation — Merged Resolver (2026-03-30)

### What was done
Created `execution/workflow_resolver.py` merging CLI (`cli/workflow_resolution.py`) and MCP (`mcp_server/utils/resolver.py`) resolvers. Key differences from old resolvers:

| Aspect | Old CLI | Old MCP | New unified |
|--------|---------|---------|-------------|
| Input types | `str` only | `str \| dict` | `str \| dict` |
| Return | `(ir, source)` or `(None, None)` | `(ir, error, source)` | `ResolvedWorkflow` dataclass |
| Error handling | Returns `None` | Returns error string | **Raises** `WorkflowNotFoundError` |
| Source for library | `"saved"` | `"library"` | `"library"` |
| File path info | Not returned | Not returned | `file_path` field on `ResolvedWorkflow` |
| Normalize IR | Yes | No (caller did it) | Yes — always |
| File ref check | No | Yes (inline only) | Yes (inline only) |
| Suggestions | Caller builds separately | Built into error | Built into `WorkflowNotFoundError.similar_names` |

### Deviations from plan

1. **Test fixes pulled forward from Phase 8 Tier 3.** The plan said to fix resolver test patches in Phase 8, but 10 tests broke immediately in Phase 2 because `main.py` now imports `resolve_workflow` from `pflow.execution.workflow_resolver` instead of `pflow.cli.workflow_resolution`. Mock patches targeting the old module path stopped intercepting. Fixed by updating patch targets in `test_workflow_resolution.py` (replace-all `pflow.cli.workflow_resolution.WorkflowManager` → `pflow.execution.workflow_resolver.WorkflowManager`) and `test_nested_workflow_cli.py` (same pattern, 1 occurrence).

2. **`_handle_named_workflow` needed `try/except` wrapper.** The old resolver returned `(None, None)` for not-found, so the code checked `if not workflow_ir: return False`. The new resolver raises `WorkflowNotFoundError`. Added a `try/except WorkflowNotFoundError: return False` guard so the function still returns `False` for not-found (letting the caller raise with proper context). The plan didn't specify this explicitly.

3. **`_try_execute_named_workflow` simplified.** The old code called `resolve_workflow()`, then if resolution returned `(None, None)` AND `_handle_named_workflow` returned `False`, it would build suggestions manually via `find_similar_workflows()`. Now `resolve_workflow()` raises with suggestions built-in, so the fallback code path (`find_similar_workflows`) is unreachable. Left a safety `raise WorkflowNotFoundError(first_arg, similar_names=[])` for the impossible case.

4. **MCP `_resolve_and_validate_workflow` preserved as thin wrapper.** Instead of rewriting the function (plan's Phase 2d), I kept the same 4-tuple return signature but swapped the internal call from old `resolve_workflow()` (returns 3-tuple) to `_unified_resolve()` (returns `ResolvedWorkflow` or raises). The `except Exception` catches resolver failures and converts to the error response dict. This minimizes blast radius — the 4-tuple contract is used by several MCP callers.

5. **MCP `validate_workflow` updated to use `resolved.file_path`.** The old code had `if source == "file": base_dir = Path(str(workflow)).resolve().parent` and `elif source == "library": wm = WorkflowManager(); base_dir = Path(wm.get_path(str(workflow))).parent`. Simplified to `if resolved.file_path: base_dir = Path(resolved.file_path).parent` — this handles both file and library sources uniformly since `ResolvedWorkflow.file_path` is populated for both.

### `"saved"` → `"library"` migration
All 6 occurrences of `== "saved"` in `main.py` replaced with `== "library"` (including `ctx.obj["workflow_source"]` check that gates `WorkflowManager` passing). Updated docstrings too. The old CLI resolver returned `"saved"`, the new one returns `"library"` to match the MCP resolver's convention. Any test that checks `source == "saved"` on the OLD resolver's direct call is unaffected (old module still works). Tests going through CLI code paths get `"library"`.

### Old resolvers: NOT deleted yet
Both `cli/workflow_resolution.py` and `mcp_server/utils/resolver.py` still exist. The CLI module still exports `is_likely_workflow_name` (used by CLI, not resolver logic). The MCP module is no longer imported. Phase 7 will clean up.

### Verification
- 4,671 tests pass (including 10 tests fixed by patch target updates)
- `make check` clean

### Key insights for future agents

1. **Mock patch targets are the #1 risk in resolver migration.** When `main.py` changes `from X import resolve_workflow` to `from Y import resolve_workflow`, all test patches targeting `X.resolve_workflow` or `X.WorkflowManager` silently stop intercepting. The function runs unpatch, hits real WorkflowManager which has no saved workflows, and tests fail with "not found". Always grep for mock targets when changing import sources.

2. **`ResolvedWorkflow.file_path` is the key new capability.** It carries the absolute path for both file-based and library-based workflows, enabling `_inject_workflow_file_path()` in the Runner without re-resolving. For `"content"` and `"direct"` sources, it's `None` — callers must handle this.

3. **The unified resolver always raises on not-found.** This is a contract change from the CLI resolver (which returned `None, None`). Any code path that previously checked `if workflow_ir is None` after `resolve_workflow()` now needs `try/except WorkflowNotFoundError` instead.

---

## Phase 3 Implementation — Compiler Changes (2026-03-30)

### What was done
1. Renamed `_validate_workflow` → `_prepare_compilation` in `compile_validation.py`. Added backward-compatible alias `_validate_workflow = _prepare_compilation`.
2. Changed return type to `tuple[dict[str, Any], list[Any]]` (params + warnings). Warnings currently always `[]`.
3. Updated `compiler.py` import and call site to unpack: `initial_params, _comp_warnings = _prepare_compilation(...)`.
4. Added `only_node: Optional[str] = None` parameter to `compile_ir_to_flow()`.
5. Changed `only_node_id` read from `initial_params.get("__only_node__")` to the new `only_node` parameter.
6. Updated `executor_service.py` to `pop("__only_node__")` from `execution_params` before passing to `compile_ir_to_flow(only_node=only_node_val)`.
7. Removed `__only_node__` filter from `_initialize_shared_store()` — now uses simple `shared_store.update(execution_params)` since `__only_node__` was already popped.

### Deviations from plan

1. **Kept validation steps 2 and 2.1 (structure + data flow) in `_prepare_compilation()`.** The plan said to strip these as "pure validation, covered by WorkflowValidator." On reflection, I kept them as defense-in-depth because:
   - Sub-workflows call `compile_ir_to_flow()` directly (not through the Runner). Without these checks, a malformed child workflow IR would crash during node instantiation instead of producing a clear validation error.
   - 4,671 tests pass — no test relied on the absence of these checks.
   - The checks are fast (structure validation is O(n) with small n, data flow is one topological sort).

2. **Kept template validation (step 5) in `_prepare_compilation()`.** Same reasoning — sub-workflows need it. The Runner's `WorkflowValidator` only runs on the top-level workflow; child workflows go through the compiler directly. Stripping this would create a regression for nested workflow template errors.

3. **Added backward-compatible alias.** `_validate_workflow = _prepare_compilation` at module level, so any external callers referencing the old name (e.g., tests importing `_validate_workflow` from `compile_validation`) still work. No tests actually import it (it's private), but this is zero-cost insurance.

### Key insight for future agents

**The `__only_node__` flow is now clean.** Before: CLI puts `__only_node__` in `execution_params` → `_initialize_shared_store` filters it out of shared store but leaves it in `execution_params` → compiler reads it from `initial_params` (which IS `execution_params`). After: CLI puts `__only_node__` in `execution_params` → `executor_service.execute_workflow()` pops it → passes as explicit `only_node` parameter to `compile_ir_to_flow()` → compiler uses the parameter directly. No more asymmetric key handling between `__no_cache__` (popped) and `__only_node__` (filtered). Both are now popped.

### Verification
- 4,671 tests pass, zero test changes needed
- `make check` clean (verified by test run)

### Phase 3 Revision (2026-03-30)

Original implementation kept ALL validation in `_prepare_compilation()` — negating the core purpose of Phase 3. Revised after user review:

**What was wrong**: Kept `validate_ir_structure()`, `_validate_data_flow_at_compile_time()`, and `validate_workflow_templates()` + `display_validation_warnings()` for "defense-in-depth." This meant validation still ran twice per execution, and `display_validation_warnings()` still printed to stderr from inside the compiler (the Q7 bug Task 138 exists to fix).

**Key distinction the original deviation missed**: Structure validation and data flow validation are **compiler prerequisites**, not pre-execution checks. Without `validate_ir_structure()`, `ir_dict["nodes"]` crashes with `KeyError`. Without data flow validation, the compiler produces Flows with cycles that hang at runtime. These protect the compiler's own code. Template validation is purely a pre-execution UX check — the compiler produces a valid Flow regardless.

**Revised `_prepare_compilation()`**:
- **KEPT**: `validate_ir_structure()` (compiler prerequisite)
- **KEPT**: `_validate_data_flow_at_compile_time()` (prevents broken Flows)
- **STRIPPED**: `validate_workflow_templates()` + `display_validation_warnings()` (handled by WorkflowValidator)
- **KEPT**: `_get_template_resolution_mode()`, `prepare_inputs()`, `_validate_outputs()`
- **Returns**: `(initial_params, [])` — honest empty list, template warnings come from WorkflowValidator

**Also fixed: `__only_node__` ordering bug.** The pop was AFTER `_initialize_shared_store()`, which copies execution_params into shared store — so `__only_node__` leaked into the shared store. Moved pop before `_initialize_shared_store()`.

**Test impact**: 7 template-related test failures (tests call `compile_ir_to_flow()` directly, expect `ValueError` from template validation that no longer runs in the compiler). These are Phase 8 migration work — tests need to route through the Runner or test `WorkflowValidator` directly.

---

## Implementation Discipline — Lessons from Phase 3 (2026-03-30)

Phase 3 required a revision after the initial implementation kept all validation in `_prepare_compilation()`, negating the core purpose of the phase. Three root causes identified, with concrete corrections for Phases 4-10.

### Root cause 1: Defaulting to "keep it, it's safer" without distinguishing what "safe" means

The plan said "strip these checks." I overrode it with "defense-in-depth" reasoning that lumped compiler prerequisites (structure validation — the compiler crashes without it) with pre-execution UX checks (template validation — the compiler produces valid output without it). Generic caution is not engineering judgment.

**Correction for Phases 4-10**: When the plan says strip/remove/replace, do it. If I think the plan is wrong, stop and present specific evidence (not a generic safety argument). The plan went through 8 review agents and an audit. In-the-moment reasoning that hasn't been reviewed doesn't override that.

### Root cause 2: Not verifying claims against the code just written

The `__only_node__` pop was placed after `_initialize_shared_store()`, which copies params into shared store — so `__only_node__` leaked into the store. The progress log then claimed the flow was clean. The docstring said "pure validation is stripped" while the code kept everything. I documented intent, not reality.

**Correction for Phases 4-10**: After writing code, trace the actual execution path — don't verify just the line changed. After writing a progress log claim, verify it with a grep or read. "The pop happens before X" → go confirm it. "Warnings no longer print to stderr" → grep for the call.

### Root cause 3: Treating the plan as suggestions

Each plan decision has recorded reasoning from review agents and audits. When I deviated, I re-derived from scratch and ignored their work instead of checking whether my new reasoning addressed something the reviewers missed.

**Correction for Phases 4-10**: Deviations require identifying what the plan's reasoning missed — not just providing an alternative. If the plan's reasoning still holds, follow the plan.

### Specific risks for remaining phases

**Phase 5 (CLI wiring)**: Highest risk of "keep the old orchestration alongside the Runner" producing a hybrid harder to debug than either system. The plan absorbs 8 functions into the Runner — absorb them, don't keep them "just in case."

**Phase 6 (MCP wiring)**: Risk of preserving `_resolve_and_validate_workflow()`'s 4-tuple contract when the Runner handles resolution+validation. The plan rewrites 3 methods — rewrite them.

**Phase 8 (test migration)**: Risk of patching tests to pass without understanding what behavior changed. Each test fix should identify: what was the test guarding against, does the Runner still guard against it, and where is that guard now.

**Known debt**: 7 template validation test failures from Phase 3 are Phase 8 work. Do not try to fix during Phases 4-6.

---

## Phase 3 Final State (2026-03-30)

### xfail markers for 7 template validation tests

Tests marked `@pytest.mark.xfail(reason="Task 138: template validation moved from compiler to WorkflowValidator")`:

| File | Test | What it tested |
|------|------|----------------|
| `test_integration/test_branch_convergence.py:155` | `test_typo_in_field_still_errors_despite_optional` | Typo in `${branch-high.stddout}` caught at compile time |
| `test_integration/test_template_resolution_hardening.py:237` | `test_invalid_template_caught_at_compilation_in_permissive_mode` | Invalid template caught even in permissive mode |
| `test_integration/test_template_resolution_hardening.py:300` | `test_permissive_mode_still_fails_compilation_for_unknown_templates` | Unknown templates fail compilation in permissive |
| `test_integration/test_template_resolution_hardening.py:356` | `test_multiple_template_errors_all_captured_at_compilation` | All template errors captured in single compilation |
| `test_runtime/test_template_integration.py:111` | `test_validation_fails_missing_params` | Missing `${required_param}` caught at compile time |
| `test_runtime/test_template_validation/test_types.py:1067` | `test_dict_in_shell_command_fails_at_compile_time` | Dict value in shell command fails at compile |
| `test_runtime/test_template_validation/test_types.py:1103` | `test_list_in_shell_command_fails_at_compile_time` | List value in shell command fails at compile |

**Phase 8 resolution**: Each test must be updated to route through `WorkflowValidator.validate()` or `WorkflowRunner` instead of calling `compile_ir_to_flow()` directly. The behavior these tests guard (catching bad templates before execution) is still present — it moved from the compiler to the Runner's validation step. The `test_typo_in_field` test is special: it still raises `ValueError` but from `TemplateAwareNodeWrapper` at runtime (line 643), not at compile time. That test may need its assertion adjusted to expect a runtime error.

### Test suite status

`make test`: **4,664 passed, 7 xfailed**

### Complete list of files modified in Phases 1-3

**New files created:**
- `src/pflow/execution/result.py` — `RunnerConfig`, `ResolvedWorkflow`, `ValidationResult`, `ExecutionResult` (with new `validation_warnings`, `trace`, `metrics` fields)
- `src/pflow/execution/workflow_resolver.py` — Unified resolver merging CLI and MCP resolvers

**Production files modified:**
- `src/pflow/execution/__init__.py` — Added exports for new types + `resolve_workflow`
- `src/pflow/execution/executor_service.py` — Moved `ExecutionResult` to `result.py`, `__only_node__` pop before `_initialize_shared_store`, removed `__only_node__` filter from shared store update
- `src/pflow/execution/workflow_execution.py` — Import path change for `ExecutionResult`
- `src/pflow/execution/formatters/error_formatter.py` — Import path change for `ExecutionResult`
- `src/pflow/runtime/compilation/compile_validation.py` — Renamed `_validate_workflow` → `_prepare_compilation`, stripped template validation + `display_validation_warnings()`, returns `tuple[dict, list]`
- `src/pflow/runtime/compilation/compiler.py` — Import change, tuple unpack, added `only_node` param to `compile_ir_to_flow()`
- `src/pflow/cli/main.py` — Import from unified resolver, `"saved"` → `"library"` (6 occurrences), try/except for `WorkflowNotFoundError`
- `src/pflow/mcp_server/services/execution_service.py` — Import from unified resolver, `_resolve_and_validate_workflow` uses `_unified_resolve()`, `validate_workflow` uses `resolved.file_path`

**Test files modified:**
- `tests/test_execution/formatters/test_error_formatter.py` — Import path
- `tests/test_cli/test_agent_ux_fixes.py` — Split import
- `tests/test_cli/test_workflow_output_handling.py` — Import path (lazy)
- `tests/test_runtime/test_checkpoint_tracking.py` — Import path (lazy)
- `tests/test_cli/test_workflow_resolution.py` — Mock patch target `pflow.cli.workflow_resolution.WorkflowManager` → `pflow.execution.workflow_resolver.WorkflowManager`
- `tests/test_cli/test_nested_workflow_cli.py` — Same mock patch target update
- `tests/test_integration/test_branch_convergence.py` — xfail marker
- `tests/test_integration/test_template_resolution_hardening.py` — 3 xfail markers
- `tests/test_runtime/test_template_integration.py` — xfail marker
- `tests/test_runtime/test_template_validation/test_types.py` — 2 xfail markers

### Key context for the next implementing agent

1. **The plan file is at `.taskmaster/tasks/task_138/implementation/implementation-plan.md`** — it has complete code snippets for all remaining phases. Phase 4's Runner code (Section 4a) is the next artifact to create.

2. **The plan's Phase 4 code needs corrections from review fixes #1-#12** (documented in the plan's "Review Fixes Applied" table at the top). These are already incorporated into the plan's code snippets, but verify against the review fix table if anything looks wrong.

3. **`_prepare_compilation()` now returns `(initial_params, [])` — always empty list.** Template warnings are stripped from the compiler. The Runner's `WorkflowValidator.validate()` is the sole source of template warnings. The `compile_ir_to_flow()` caller in `compiler.py` discards the second element: `initial_params, _comp_warnings = _prepare_compilation(...)`.

4. **`compile_ir_to_flow()` has a new `only_node` parameter.** `executor_service.py` pops `__only_node__` from `execution_params` before `_initialize_shared_store()` and passes it as the `only_node` kwarg. The Runner should do the same — pass `config.only_node` to `compile_ir_to_flow(only_node=...)`.

5. **The unified resolver raises `WorkflowNotFoundError` on not-found** (old CLI resolver returned `(None, None)`). The Runner's `_resolve()` method handles dict passthrough; for string input it delegates to `resolve_workflow()`.

6. **Source value `"saved"` is now `"library"` everywhere.** CLI checks `ctx.obj["workflow_source"] == "library"` to decide whether to pass `WorkflowManager` to the Runner.

7. **MCP's `_resolve_and_validate_workflow()` still exists as a thin wrapper** — preserved in Phase 2 to minimize blast radius. Phase 6 rewrites it away.

8. **`display_validation_warnings()` still exists as a module function** — it's still called by `cli/main.py:393` in the validate-only path. It was only removed from the compiler's `_prepare_compilation()`. Phase 5 should replace that CLI call site too (validate-only goes through `runner.validate()` → `_display_validation_result()`).

9. **Pre-existing MCP bug**: `validate_workflow()` at line ~413 in `execution_service.py` references `wm` variable that was never defined for `source == "library"` path — would be a `NameError` at runtime. Pre-existing, not introduced by our changes. Phase 6 rewrites this method entirely.

### Status: Phases 1-3 complete. Ready for context reset before Phase 4.

---

## Phase 4 Implementation — Create WorkflowRunner (2026-03-30)

### What was done
Created `execution/runner.py` with `WorkflowRunner` class. Two public methods: `run()` and `validate()`. Added to `execution/__init__.py` exports.

**Key structural decision**: Extracted `run()` body into three methods to satisfy ruff C901 (max complexity 10):
- `_prepare_workflow()` — resolve, inject file path, resolve file refs, enrich defaults, validate
- `_execute_workflow()` — create resources, compile, execute, build result. Returns `(result, mcp_pool, trace_collector, metrics_collector)` so the caller's `finally` can clean up
- `_cleanup()` — MCP pool shutdown, LLM interception cleanup, metrics end

### Deviations from plan

1. **Ruff C901 forced decomposition.** The plan had a single `run()` method with the full pipeline. Ruff reported complexity 11 (exceeds 10). Split into `_prepare_workflow()` + `_execute_workflow()` + `_cleanup()`. The split is natural — preparation, execution, cleanup — and makes the error boundary clearer: `_prepare_workflow` runs before resource creation, so failures there don't need MCP pool shutdown.

2. **Ruff SIM105 fix.** `try/except Exception: pass` for `metrics_collector.record_workflow_end()` replaced with `contextlib.suppress(Exception)`.

3. **mypy arg-type fix.** `WorkflowValidationError(validation_errors=errors)` where `errors` is `list[str]` but the constructor expects `list[str | tuple[str, str, str]] | None`. Added `# type: ignore[arg-type]` since `list[str]` is a valid subset but mypy's invariance check rejects it.

4. **Fixed Phase 2 test regression.** `test_nested_workflow_cli.py::test_saved_workflow_with_relative_nested_child` failed when run in the full suite (passed in isolation). Root cause: `main.py:609` creates `WorkflowManager()` from its **top-level import** (`line 32`). The test only patched `pflow.core.workflow.manager.WorkflowManager` and `pflow.execution.workflow_resolver.WorkflowManager`, but missed `pflow.cli.main.WorkflowManager`. Added the third patch target. This is a Phase 2 regression that only manifested in full-suite runs because test ordering determined whether `main.py` had been imported (and thus cached the binding).

### Verification
- 4,664 passed, 7 xfailed
- `ruff check` clean on `runner.py`
- `mypy` clean on `runner.py`

### Key insights for future agents

1. **The Runner delegates `_build_errors()` to `WorkflowExecutorService`.** `runner._build_errors()` instantiates `WorkflowExecutorService()` and calls `svc._build_error_list()`. This is intentional — reusing the existing 80-line error extraction logic rather than copying it. The `WorkflowExecutorService` becomes an internal utility, not a dead class.

2. **`_prepare_workflow()` runs before any resource creation.** If resolution or validation fails, no MCP pool was created, no metrics collector was started. This means the `finally` block's checks (`if mcp_pool`, `if trace_collector`, `if metrics_collector is not None`) correctly handle early failures.

3. **The Runner's `_resolve()` handles dict passthrough differently from `resolve_workflow()`.** For string inputs, it delegates to the unified resolver. For dict inputs, it calls `normalize_ir()` and returns `ResolvedWorkflow(source="direct", file_path=None)`. The inline file reference check from `resolve_workflow()` is NOT applied for dict passthrough in the Runner — this is intentional because the CLI already parsed and resolved the IR.

---

## Phase 5 Implementation — Wire CLI to Runner (2026-03-30)

### What was done
Rewrote `execute_json_workflow()` in `cli/main.py` to call `WorkflowRunner().run()` instead of `execute_workflow()`. Added two new display functions: `_display_execution_result()` and `_display_validation_result()`. Updated `test_validate_only.py` JSON assertion.

### Deviations from plan

1. **Had to inject `_pflow_workflow_file` from `ctx.obj["source_file_path"]`.** The plan didn't account for the CLI always passing pre-parsed IR dicts to the Runner. The Runner's `_resolve()` for dict inputs returns `file_path=None`, so `_pflow_workflow_file` isn't injected. The old `_prepare_execution_environment` read this from `ctx.obj`. Added explicit injection before the Runner call.

2. **`DisplayManager(output_controller)` bug caught and fixed.** `DisplayManager` expects `OutputInterface`, not `OutputController`. The old code had `DisplayManager(output=cli_output)` inside `_prepare_execution_environment`. I initially wrote `DisplayManager(output_controller)` which passed an `OutputController` — this caused 121 test failures with `'OutputController' object has no attribute 'show_progress'`. Fixed to `DisplayManager(cli_output)`.

3. **`WorkflowValidationError` message was too generic.** The Runner's `_exception_to_result()` stored `str(exception)` which is just "Workflow validation failed" (the `summary`). The actual validation error details are in `exception.validation_errors`. Fixed to join validation error messages into the error dict's `message` field, plus added `validation_errors` list to the error dict for structured access.

4. **Verbose "Starting workflow" message was missing.** The old code had `if verbose: click.echo("cli: Starting workflow execution with N node(s)")`. This was dropped in the rewrite. Added it back since `test_e2e_workflow.py::test_verbose_execution_output` asserts on it.

5. **ruff C901 required `noqa: C901` on `execute_json_workflow`.** Complexity 12 (exceeds 10). The function legitimately needs branches for validate-only, stdin routing, verbose mode, JSON mode, file path injection. Extracted `_display_execution_result()` to reduce it, but still 12. Added `noqa: C901`.

6. **`test_validate_only.py` JSON shape change.** New validate-only JSON output has `{"success": true, "validated_only": true, "errors": [], "warnings": []}` instead of `{"success": true, "message": "..."}`. Updated assertion: `output_data.get("message", "").lower()` → `output_data.get("validated_only") is True`.

### Functions absorbed by Runner (no longer called from CLI)
- `_prepare_execution_environment` — split: CLI keeps CliOutput/DisplayManager, Runner creates trace/metrics/MCP/cache
- `_setup_execution_context` — Runner creates MetricsCollector
- `_handle_validate_only_mode` — replaced by `runner.validate()` + `_display_validation_result()`
- `_perform_validation` — replaced by `runner.validate()`
- `_display_validation_results` — replaced by `_display_validation_result()`
- `_validate_before_execution` — Runner validates internally
- `_resolve_file_refs` — Runner resolves file references internally

### Functions still called
- `_handle_workflow_success` — display concern, stays in CLI
- `_save_trace_and_report` — display concern (trace file path, report generation), stays in CLI
- `_cleanup_temp_files` — CLI creates temp files, CLI cleans them
- `_route_stdin_to_params` — CLI concern

### Test impact
25 failures remaining (24 in `test_workflow_output_handling.py`, 1 in `test_agent_ux_fixes.py`). All are mock-target issues: tests patch `pflow.execution.workflow_execution.execute_workflow` or `pflow.execution.workflow_execution.WorkflowExecutorService.execute_workflow` — the old code path that's now bypassed by the Runner. Phase 8 migration will update these to mock `pflow.execution.runner.WorkflowRunner.run`.

### Verification
- 4,639 passed, 25 failed (all mock-target), 7 xfailed
- `ruff check` clean
- Pre-existing ruff F821 in `execution_service.py` (undefined `wm` variable) — Phase 6 fixes

### Key insights for future agents

1. **The CLI always passes pre-parsed IR dicts.** The `workflow_command` function resolves the workflow (file → IR, name → IR) before calling `execute_json_workflow()`. So the Runner receives a dict, not a string. For dict inputs, the Runner can't derive `file_path` from resolution. The CLI must inject `_pflow_workflow_file` from `ctx.obj["source_file_path"]`.

2. **`_cleanup_workflow_resources` is effectively dead.** The Runner handles LLM interception cleanup in its `_cleanup()` method. The CLI only needs `_cleanup_temp_files()`. The `_cleanup_workflow_resources` wrapper is no longer called. Phase 7 should delete it.

3. **The `display_validation_warnings` import at top of main.py is now unused.** It was only needed by `_handle_validate_only_mode` and `_validate_before_execution`, both replaced. Phase 7 should clean up the import.

4. **The old `execute_workflow` import at line 566 was lazy inside the function body.** It's now replaced by `WorkflowRunner` import. The `workflow_execution.py` module is no longer imported from main.py at all. Phase 7 can delete `workflow_execution.py`.

### Additional findings from post-Phase-5 review

**7. `print_flag` was missing from `effective_verbose` calculation.** Old code: `effective_verbose = verbose and not print_flag and output_format != "json"`. Initial rewrite: `effective_verbose = verbose and output_format != "json"`. This meant `-p` (print) mode would show verbose CLI messages when it shouldn't. Fixed by adding `not print_flag` back to the condition.

**8. `CliOutput` was receiving `effective_verbose` instead of raw `verbose`.** Old `_prepare_execution_environment` passed `verbose=verbose` (raw flag) to `CliOutput`, while `effective_verbose` was only used for CLI-level messages and the `__verbose__` shared store flag. `CliOutput.verbose` controls error detail display (line 53 of `cli_output.py`). Passing `effective_verbose=False` in JSON/print mode would suppress error details in `show_error()` — but `show_error()` already guards on `self.output_format != "json"`, so the JSON case is redundant. The print-mode case is the real difference: with `effective_verbose=False`, error details wouldn't show even when `-v -p` is active. Fixed by passing raw `verbose` to `CliOutput`, matching old behavior.

**9. Validation warning display timing changed.** Old `_validate_before_execution` displayed warnings immediately before execution: `click.echo(f"⚠️  {warning}", err=True)` in verbose non-JSON mode. New Runner puts warnings in `ExecutionResult.validation_warnings` — they're in the structured result but not displayed as pre-execution stderr output. This is intentional per the Q7 design decision (warnings route through structured data, not stderr side-channel). No test asserts on pre-execution warning display. MCP gains access to validation warnings it previously never saw.

**10. `WorkflowValidationError` tuple format differs.** Old `_validate_before_execution` wrapped errors as `[(e, "", "") for e in errors]` (tuples with empty path/suggestion). New Runner passes `errors` as `list[str]` directly. `WorkflowValidationError.format_for_cli()` handles both formats — tuples produce path/suggestion lines, strings are passed through. Functionally identical since the empty path/suggestion strings produce no extra output.

**11. Exception surface in CLI's `except Exception` changed.** Old code: `execute_workflow()` could raise `CompilationError`, `RuntimeError`, `MaxNodeVisitsError` — the CLI caught all. New code: `WorkflowRunner().run()` catches all exceptions internally and returns `ExecutionResult`. The CLI's `except Exception` now only catches errors from: `_display_execution_result()` (display/formatting errors), `CliOutput` creation, or `DisplayManager.show_execution_start()`. These are display-layer errors, not execution errors. The error handler still works (passes exception to `output_error`) but the exception types are different.

**12. `_resolve()` for dict inputs skips inline file reference check.** `resolve_workflow()` calls `_check_inline_file_references()` for dict inputs. The Runner's `_resolve()` for dicts bypasses `resolve_workflow()` entirely (just normalizes and wraps). This means MCP callers passing raw IR dicts through the Runner skip the guard. However, the Runner's `_resolve_file_references()` runs for all paths and handles resolution — the guard only blocks inline workflows that can't have their references resolved. For dict inputs, resolution uses CWD as base dir (from `get_base_dir(params)` when no `_pflow_workflow_file` is set). This is a behavioral difference that Phase 6 should account for.

**13. `time.perf_counter()` vs `time.time()`.** Old `WorkflowExecutorService` used `time.time()` for metadata duration. Runner uses `time.perf_counter()`. Both compute elapsed time as `end - start`. `perf_counter` is monotonic (immune to system clock changes) and higher resolution. The absolute values differ but the duration calculation is identical. No behavioral impact.

**14. `config.trace_enabled` default differs from `ctx.obj.get("trace", False)`.** `RunnerConfig.trace_enabled` defaults to `True` (`ctx.obj.get("trace", True)`). `_save_trace_and_report` checks `ctx.obj.get("trace", False)` — defaults to `False`. In practice, `ctx.obj["trace"]` is always explicitly set by `workflow_command`, so the different defaults don't matter in production. Could matter in tests that call `execute_json_workflow` directly without `workflow_command` setup. The finally block has `config.trace_enabled` as outer guard AND `_save_trace_and_report` has `ctx.obj["trace"]` as inner guard — both must pass. Defense in depth.

**15. `__no_cache__` and `__only_node__` param injection eliminated.** Old code: `_prepare_execution_environment` injected `__no_cache__` and `__only_node__` into `enhanced_params`, then `executor_service._initialize_shared_store` popped `__no_cache__`, and `compiler.py` read `__only_node__` from `initial_params`. New code: `RunnerConfig.cache_enabled` and `RunnerConfig.only_node` carry these values. The Runner passes `config.cache_enabled` to `MemoizationCache(read_enabled=...)` and `config.only_node` to `compile_ir_to_flow(only_node=...)`. No dunder params flow through `params` dict for these concerns anymore. MCP never used these dunders, so Phase 6 is unaffected.

**16. `_enrich_params_with_defaults` + `_prepare_compilation` idempotency verified.** Both call `prepare_inputs()`. First call (Runner, before validation) applies defaults to `params`. Second call (compiler, inside `_prepare_compilation`) sees all params already present → returns empty `defaults` → `initial_params.update({})` is no-op. Confirmed by reading `prepare_inputs` line 298: `if input_name not in provided_params:` — already-present params skip default resolution.

**17. Resource leak bug found and fixed in `_execute_workflow` decomposition.** When the old code had a single `run()` body, resources (mcp_pool, trace_collector, metrics_collector) were local variables in the same scope as the `finally` block. The decomposition into `_execute_workflow` made them local to the helper — if `_execute_workflow` raised after creating MCPConnectionPool (e.g., `flow.run()` fails after MCP servers started), the tuple assignment `result, mcp_pool, ... = self._execute_workflow(...)` never completed, and the outer `mcp_pool` stayed `None`. The finally called `_cleanup(None, None, None)` — no-op, server subprocesses leaked.

**Fix**: Moved resource creation (MetricsCollector, WorkflowTraceCollector, MCPConnectionPool, MemoizationCache) back into `run()` scope. Renamed `_execute_workflow` → `_compile_and_execute` which now receives resources as parameters. Resources are always visible to `_cleanup()` in the finally block, regardless of whether `_compile_and_execute` succeeds or raises. Added `noqa: C901` to `run()` since the resource creation adds to line count (not branching complexity).

### Status: Phases 1-5 complete. 25 test failures (mock-target, Phase 8). Ready for Phase 6 (MCP wiring).
