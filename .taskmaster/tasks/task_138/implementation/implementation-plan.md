# Task 138 Phase 1: Shared WorkflowRunner — Atomic Implementation Plan

## Context

Task 138 replaces pflow's parallel CLI/MCP orchestration layers with a single `WorkflowRunner`. Currently, CLI (`cli/main.py`, 1,379 lines) and MCP (`mcp_server/services/execution_service.py`, 791 lines) each build their own orchestration from partially-shared components. This causes: every feature must work through 5 paths, MCP skips type coercion/input defaults, validation runs twice per execution, and ~1,500 lines of duplicated glue code.

Phase 0 (dead code cleanup, ~620 lines removed) is complete. Phase 1 creates the shared Runner.

**Authoritative design**: `.taskmaster/tasks/task_138/implementation/progress-log.md` — all design decisions (Q1-Q10, gap resolutions, pre-implementation audit).

**Key constraint**: 4,671 tests must pass after EVERY phase. Run `make test` after each phase before proceeding.

---

## Review Fixes Applied (2026-03-29)

8 review agents identified 12 critical issues in the original plan code snippets. All fixes applied inline below. Key changes:

| # | Finding | Fix |
|---|---------|-----|
| 1 | `'metrics_collector' in dir()` is broken Python (ALL 8 agents) | Init `metrics_collector = None` before try; use `if metrics_collector is not None:` in finally |
| 2 | Validation ordering: defaults not injected before `_validate()` in `run()` | Add `prepare_inputs()` call before `WorkflowValidator.validate()` to enrich params with defaults |
| 3 | `__verbose__` not in shared store — MCP nodes lose verbose mode | Add `shared_store["__verbose__"]` in `_initialize_shared_store()`, pass `verbose` param |
| 4 | `output_error()` wrong signature in Phase 5 | Pass `result=result` and `ctx` as first arg |
| 5 | `display.show_execution_start()` wrong args | Takes `(node_count: int)`, not `(ir_data, workflow_name)` |
| 6 | `WorkflowValidationError` wrong constructor | Use `WorkflowValidationError(validation_errors=errors)` |
| 7 | Source `"saved"` → `"library"` breaks CLI metadata check | Update all `"saved"` checks to `"library"` |
| 8 | LLM interception cleanup missing from Runner finally | Added `trace_collector.cleanup_llm_interception()` |
| 9 | `Registry.get_node_info()` doesn't exist + `format_node_not_found_error` wrong args | Use `nodes = registry.load()` and pass `list(nodes.keys())` |
| 10 | `execution_id=""` breaks `read_fields` MCP pattern | Generate via `ExecutionCache().generate_execution_id()` |
| 11 | Registry run: WorkflowValidator fires on node params as "unknown" | Pass `{}` as Runner params, all user params in node.params only |
| 12 | `_build_error_text` missing `trace_path` in new MCP | Derive from `result.trace` or pass `Path("~/.pflow/debug")` |

**Test migration additions** (from review):
- `test_validate_only.py` (JSON shape) moved from Tier 5 to Tier 1
- `test_api_warning_system.py` added to Tier 1 (3 direct instantiations)
- `test_registry_run_mcp.py` added to Tier 2 (stale mocks after Phase 6)
- `test_nested_workflow_cli.py` added to Tier 3 (patches old resolver)
- `"saved"` → `"library"` assertion updates in `test_workflow_resolution.py`

---

## Phase 1: Foundation Types

**Goal**: Create `execution/result.py` with all new types. Update imports. Zero behavioral changes.

### 1a. Create `src/pflow/execution/result.py`

```python
"""Result types for workflow execution and validation."""

from dataclasses import dataclass, field
from typing import Any, Optional

from pflow.core.workflow.status import WorkflowStatus


@dataclass(frozen=True)
class RunnerConfig:
    """Immutable configuration for WorkflowRunner.run().

    Only execution-affecting parameters. Presentation concerns
    (output_format, logging) belong with the caller.
    """
    trace_enabled: bool = True
    cache_enabled: bool = True
    verbose: bool = False
    only_node: Optional[str] = None


@dataclass(frozen=True)
class ResolvedWorkflow:
    """Result of workflow resolution.

    Returned by resolve_workflow(). The Runner reads file_path
    for _inject_workflow_file_path() — callers never set this.
    """
    ir: dict[str, Any]
    source: str  # "file", "library", "content", "direct"
    file_path: Optional[str] = None  # Absolute path for file/library, None for content/direct


@dataclass
class ValidationResult:
    """Result of runner.validate()."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    # warnings shape: {"node": str, "node_type": str, "template": str, "message": str}


@dataclass
class ExecutionResult:
    """Result of workflow execution."""
    success: bool
    status: WorkflowStatus = WorkflowStatus.SUCCESS
    shared_after: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    validation_warnings: list[dict[str, Any]] = field(default_factory=list)
    trace: Optional[Any] = None  # WorkflowTraceCollector | None
    metrics: Optional[Any] = None  # MetricsCollector | None
```

### 1b. Update `src/pflow/execution/__init__.py`

Change from:
```python
from .executor_service import ExecutionResult, WorkflowExecutorService
```
To:
```python
from .result import ExecutionResult, ResolvedWorkflow, RunnerConfig, ValidationResult
from .executor_service import WorkflowExecutorService
```

Keep `DisplayManager` and `OutputInterface` exports unchanged.

### 1c. Update `src/pflow/execution/executor_service.py`

Remove the `ExecutionResult` dataclass definition (lines 18-26). Replace with import:
```python
from .result import ExecutionResult
```

Keep `WorkflowStatus` import. Keep all `WorkflowExecutorService` code unchanged.

### 1d. Update `src/pflow/execution/workflow_execution.py`

Change line 5 from:
```python
from .executor_service import ExecutionResult, WorkflowExecutorService
```
To:
```python
from .executor_service import WorkflowExecutorService
from .result import ExecutionResult
```

### 1e. Update `src/pflow/execution/formatters/error_formatter.py`

Change line 11 from:
```python
from pflow.execution.executor_service import ExecutionResult
```
To:
```python
from pflow.execution.result import ExecutionResult
```

### 1f. Update all test imports of `ExecutionResult`

| File | Current import | New import |
|------|---------------|------------|
| `tests/test_execution/formatters/test_error_formatter.py:14` | `from pflow.execution.executor_service import ExecutionResult` | `from pflow.execution.result import ExecutionResult` |
| `tests/test_cli/test_agent_ux_fixes.py:15` | `from pflow.execution.executor_service import ExecutionResult, WorkflowExecutorService` | Split: `from pflow.execution.result import ExecutionResult` + keep `from pflow.execution.executor_service import WorkflowExecutorService` |
| `tests/test_cli/test_workflow_output_handling.py:106` (lazy) | `from pflow.execution.executor_service import ExecutionResult` | `from pflow.execution.result import ExecutionResult` |
| `tests/test_runtime/test_checkpoint_tracking.py:254` (lazy) | `from pflow.execution.executor_service import ExecutionResult` | `from pflow.execution.result import ExecutionResult` |

### 1g. Verify

```bash
make test && make check
```

All 4,671 tests must pass. This phase is purely structural (move type + add new types).

---

## Phase 2: Merged Resolver

**Goal**: Create unified `execution/workflow_resolver.py`. Both CLI and MCP call it. Old resolvers remain (temporarily) as thin wrappers.

### 2a. Create `src/pflow/execution/workflow_resolver.py`

This merges:
- `src/pflow/cli/workflow_resolution.py` (CLI resolver: str only, raises on error, returns `(ir, source)`)
- `src/pflow/mcp_server/utils/resolver.py` (MCP resolver: str|dict, returns error tuple `(ir, error, source)`)

```python
"""Unified workflow resolution for CLI and MCP entry points."""

import logging
import os
from pathlib import Path
from typing import Any

from pflow.core.exceptions import WorkflowNotFoundError
from pflow.core.suggestion_utils import find_similar_items
from pflow.core.workflow.manager import WorkflowManager

from .result import ResolvedWorkflow

logger = logging.getLogger(__name__)


def resolve_workflow(
    identifier: str | dict[str, Any],
    wm: WorkflowManager | None = None,
) -> ResolvedWorkflow:
    """Resolve a workflow identifier to IR + metadata.

    Args:
        identifier: File path, saved name, raw markdown string, or IR dict.
        wm: WorkflowManager instance. Created internally if None.

    Returns:
        ResolvedWorkflow with ir, source, and file_path.

    Raises:
        WorkflowNotFoundError: Workflow not found (with similar_names for suggestions).
        MarkdownParseError: Invalid markdown content.
        PermissionError: File access denied.
        ValueError: Inline workflow contains file references.
    """
    # Dict input — passthrough (MCP sends pre-parsed IR)
    if isinstance(identifier, dict):
        _check_inline_file_references(identifier, "direct")
        return ResolvedWorkflow(ir=identifier, source="direct", file_path=None)

    if not isinstance(identifier, str):
        raise WorkflowNotFoundError(
            workflow_name=str(identifier),
            similar_names=[],
            hint="Workflow must be a file path, saved name, markdown string, or IR dict.",
        )

    # Raw markdown content — contains newlines (MCP sends inline workflows)
    if "\n" in identifier:
        ir = _parse_markdown_content(identifier)
        _check_inline_file_references(ir, "content")
        return ResolvedWorkflow(ir=ir, source="content", file_path=None)

    # File path — contains path separator or ends with known extension
    if _is_path_like(identifier):
        result = _try_load_from_file(identifier)
        if result is not None:
            return result
        # Fall through to name-based resolution

    # Name-based resolution — try saved workflow library
    if wm is None:
        wm = WorkflowManager()

    result = _try_load_from_library(identifier, wm)
    if result is not None:
        return result

    # Not found — build suggestions and raise
    similar = _find_suggestions(identifier, wm)
    raise WorkflowNotFoundError(
        workflow_name=identifier,
        similar_names=similar,
    )


def _is_path_like(identifier: str) -> bool:
    """Check if identifier looks like a file path."""
    return (
        os.sep in identifier
        or (os.altsep and os.altsep in identifier)
        or identifier.endswith(".pflow.md")
        or identifier.endswith(".json")
        or identifier.endswith(".md")
    )


def _try_load_from_file(identifier: str) -> ResolvedWorkflow | None:
    """Try to load workflow from file path. Returns None if file doesn't exist."""
    from pflow.core import normalize_ir
    from pflow.core.markdown_parser import parse_markdown

    path = Path(identifier).expanduser().resolve()

    # Reject .json files with migration hint
    if path.suffix == ".json":
        raise WorkflowNotFoundError(
            workflow_name=identifier,
            similar_names=[],
            hint="JSON workflow format is no longer supported. Convert to .pflow.md format.",
        )

    # Reject .md files that aren't .pflow.md with rename suggestion
    if path.suffix == ".md" and not str(path).endswith(".pflow.md"):
        pflow_path = path.with_suffix(".pflow.md")
        if pflow_path.exists():
            raise WorkflowNotFoundError(
                workflow_name=identifier,
                similar_names=[str(pflow_path)],
                hint=f"Did you mean '{pflow_path}'? Workflow files use the .pflow.md extension.",
            )
        raise WorkflowNotFoundError(
            workflow_name=identifier,
            similar_names=[],
            hint="Workflow files use the .pflow.md extension, not .md.",
        )

    if not path.exists():
        return None

    content = path.read_text(encoding="utf-8")
    result = parse_markdown(content)
    normalize_ir(result.ir)
    return ResolvedWorkflow(
        ir=result.ir,
        source="file",
        file_path=str(path),
    )


def _try_load_from_library(
    identifier: str, wm: WorkflowManager
) -> ResolvedWorkflow | None:
    """Try to load workflow from saved library."""
    from pflow.core import normalize_ir

    # Exact name match
    if wm.exists(identifier):
        ir = wm.load_ir(identifier)
        normalize_ir(ir)
        return ResolvedWorkflow(
            ir=ir,
            source="library",
            file_path=wm.get_path(identifier),
        )

    # Strip .pflow.md extension and retry
    if identifier.endswith(".pflow.md"):
        stripped = identifier[:-9]  # len(".pflow.md") == 9
        if wm.exists(stripped):
            ir = wm.load_ir(stripped)
            normalize_ir(ir)
            return ResolvedWorkflow(
                ir=ir,
                source="library",
                file_path=wm.get_path(stripped),
            )

    return None


def _parse_markdown_content(content: str) -> dict[str, Any]:
    """Parse raw markdown string into IR dict."""
    from pflow.core import normalize_ir
    from pflow.core.markdown_parser import parse_markdown

    result = parse_markdown(content)
    normalize_ir(result.ir)
    return result.ir


def _check_inline_file_references(workflow_ir: dict[str, Any], source: str) -> None:
    """Raise ValueError if inline workflow contains file references."""
    if source not in ("content", "direct"):
        return
    from pflow.core.file_resolver import has_file_references

    file_refs = has_file_references(workflow_ir)
    if file_refs:
        examples = ", ".join(file_refs[:3])
        raise ValueError(
            f"Workflow contains file references ({examples}) but was provided as inline content. "
            f"File references require a workflow file path to resolve relative paths from. "
            f"Save the workflow to a file and reference it by path or saved name."
        )


def _find_suggestions(query: str, wm: WorkflowManager) -> list[str]:
    """Find similar workflow names for error suggestions."""
    all_names = wm.list_all()
    if not all_names:
        return []
    return find_similar_items(query, all_names, max_results=5, method="substring", sort_by_length=True)
```

### 2b. Update `src/pflow/execution/__init__.py`

Add to exports:
```python
from .workflow_resolver import resolve_workflow
```

### 2c. Update CLI to use merged resolver

In `src/pflow/cli/main.py`, change the import at line 22-26:
```python
# OLD:
from pflow.cli.workflow_resolution import find_similar_workflows, is_likely_workflow_name, resolve_workflow
# NEW:
from pflow.cli.workflow_resolution import is_likely_workflow_name  # CLI-only routing heuristic
from pflow.execution.workflow_resolver import resolve_workflow
```

Then update all call sites in `main.py` that use the old `resolve_workflow` return type:

**`_try_execute_named_workflow` (line ~1135)**: Change from:
```python
workflow_ir, source = resolve_workflow(first_arg)
```
To:
```python
resolved = resolve_workflow(first_arg)
workflow_ir, source = resolved.ir, resolved.source
```

**`_handle_named_workflow` (line ~1067)**: Same pattern — unpack `resolved.ir, resolved.source`.

Also: `find_similar_workflows()` is now handled by `WorkflowNotFoundError.similar_names` from the resolver's raise. Remove the `find_similar_workflows` call at line ~1143 and let the exception propagate (it already has `similar_names`). The `except WorkflowNotFoundError` handler in `workflow_command` already formats this.

### 2d. Update MCP to use merged resolver

In `src/pflow/mcp_server/services/execution_service.py`, change line 21:
```python
# OLD:
from ..utils.resolver import resolve_workflow
# NEW:
from pflow.execution.workflow_resolver import resolve_workflow
```

Update `_resolve_and_validate_workflow()` (lines 32-82) to use the new return type:
```python
# OLD:
workflow_ir, error, source = resolve_workflow(workflow)
if error or workflow_ir is None:
    return None, {"error": True, "message": error or "Unknown error"}, {}, ""
# NEW:
# resolve_workflow now raises on error, returns ResolvedWorkflow
resolved = resolve_workflow(workflow)
workflow_ir = resolved.ir
source = resolved.source
```

The caller (`execute_workflow` at line 299) must wrap this in try/except:
```python
try:
    resolved = resolve_workflow(workflow)
except (WorkflowNotFoundError, ValueError, MarkdownParseError) as e:
    raise ValueError(str(e)) from e
```

This preserves the existing MCP exception contract (ValueError for not-found).

### 2e. Verify

```bash
make test && make check
```

All tests must pass. The old resolver files still exist but are no longer imported by main.py or execution_service.py (except `is_likely_workflow_name` which stays in `cli/workflow_resolution.py`).

---

## Phase 3: Compiler Changes

**Goal**: Rename `_validate_workflow` to `_prepare_compilation`, strip duplicated validation, add `only_node` parameter to `compile_ir_to_flow()`. Return type changes to tuple.

### 3a. Modify `src/pflow/runtime/compilation/compile_validation.py`

**Rename function** (line 188): `_validate_workflow` → `_prepare_compilation`

**Change return type** to `tuple[dict[str, Any], list[Any]]` (params + validation warnings).

**Strip these checks** (pure validation, covered by WorkflowValidator):
- **Step 2** (lines 213-217): Remove `validate_ir_structure(ir_dict)` call
- **Step 2.1** (line 220): Remove `_validate_data_flow_at_compile_time(ir_dict, CompilationError)` call
- **Step 5** (lines 258-274): Remove `validate_workflow_templates()` call and `display_validation_warnings()` call

**Keep these** (preparation — mutates initial_params):
- **Step 2.5** (lines 223-231): `_get_template_resolution_mode()` → writes `__template_resolution_mode__` to `initial_params`
- **Step 3** (lines 234-248): `prepare_inputs()` → writes defaults + `__env_param_names__` to `initial_params`
- **Step 4** (lines 251-256): `_validate_outputs()` — output name validation

**New return**: Return `(initial_params, template_warnings)` where `template_warnings` is always `[]` for now (warnings from stripped step 5 are gone; future phases may populate this from WorkflowValidator).

The function becomes:
```python
def _prepare_compilation(
    ir_dict: dict[str, Any],
    registry: Registry,
    initial_params: dict[str, Any],
    validate_templates: bool,
) -> tuple[dict[str, Any], list[Any]]:
    """Prepare IR for compilation: resolve inputs, set template mode, validate outputs.

    Returns (mutated initial_params, validation_warnings).
    Validation warnings are currently always empty — pre-execution validation
    warnings come from WorkflowValidator, not the compiler.
    """
    from .compiler import CompilationError

    # Template resolution mode (reads IR or settings, writes to initial_params)
    template_resolution_mode = _get_template_resolution_mode(ir_dict)
    initial_params["__template_resolution_mode__"] = template_resolution_mode

    # Input validation and defaults (5-tier resolution, writes defaults to initial_params)
    try:
        settings_env = _load_settings_env()
        errors, defaults, env_param_names = prepare_inputs(ir_dict, initial_params, settings_env=settings_env)
        if errors:
            _raise_input_validation_errors(errors)
        initial_params.update(defaults)
        if env_param_names:
            initial_params["__env_param_names__"] = list(env_param_names)
    except ValidationError:
        logger.debug("Input validation failed", extra={"phase": "input_validation"}, exc_info=True)
        raise

    # Output validation (validates output names can trace to node outputs)
    try:
        _validate_outputs(ir_dict, registry)
    except ValidationError:
        logger.debug("Output validation failed", extra={"phase": "output_validation"}, exc_info=True)
        raise

    return initial_params, []
```

**Update the import in compiler.py** (line ~27):
```python
# OLD:
from .compile_validation import _validate_workflow
# NEW:
from .compile_validation import _prepare_compilation
```

**Keep** `_validate_data_flow_at_compile_time`, `display_validation_warnings`, `validate_ir_structure` as module functions (they have other consumers or may be needed later). Just remove the calls from the main orchestrator. `_validate_outputs` stays as it's called from the kept code. `_load_settings_env`, `_get_template_resolution_mode`, `_raise_input_validation_errors` all stay (called from the kept code).

### 3b. Update `src/pflow/runtime/compilation/compiler.py`

**Change 1**: Update import (line ~27):
```python
from .compile_validation import _prepare_compilation
```

**Change 2**: Add `only_node` parameter to `compile_ir_to_flow()` signature (line 666):
```python
def compile_ir_to_flow(
    ir_json: Union[str, dict[str, Any]],
    registry: Registry,
    initial_params: Optional[dict[str, Any]] = None,
    validate: bool = True,
    metrics_collector: Optional[Any] = None,
    trace_collector: Optional[Any] = None,
    only_node: Optional[str] = None,  # NEW
) -> Flow:
```

**Change 3**: Update the `_validate_workflow` call at line 731 to unpack tuple:
```python
# OLD:
initial_params = _validate_workflow(ir_dict, registry, initial_params, validate)
# NEW:
initial_params, _comp_warnings = _prepare_compilation(ir_dict, registry, initial_params, validate)
```

**Change 4**: Replace `__only_node__` read from `initial_params` at line 770:
```python
# OLD:
only_node_id = initial_params.get("__only_node__") if initial_params else None
# NEW:
only_node_id = only_node
```

### 3c. Update callers of `compile_ir_to_flow()`

**Production caller 1** — `src/pflow/execution/executor_service.py:110`:
```python
# OLD:
flow = compile_ir_to_flow(
    workflow_ir, registry=registry, initial_params=execution_params,
    validate=validate, metrics_collector=metrics_collector, trace_collector=trace_collector
)
# NEW (add only_node, extracted from execution_params):
only_node_val = execution_params.pop("__only_node__", None) if execution_params else None
flow = compile_ir_to_flow(
    workflow_ir, registry=registry, initial_params=execution_params,
    validate=validate, metrics_collector=metrics_collector, trace_collector=trace_collector,
    only_node=only_node_val,
)
```

Also update `_initialize_shared_store` (line 187) — remove the `__only_node__` filter since we now pop it:
```python
# OLD:
shared_store.update({k: v for k, v in execution_params.items() if k != "__only_node__"})
# NEW:
shared_store.update(execution_params)
```

**Production caller 2** — `src/pflow/runtime/workflow_executor.py:157`:
No change needed — sub-workflows don't use `--only`, and the new `only_node` parameter defaults to `None`.

**Test callers** (~150+ across 20+ files): No change needed — `only_node` defaults to `None`.

### 3d. Update `src/pflow/runtime/compilation/__init__.py`

Add `_prepare_compilation` to exports (alongside existing `_validate_workflow` if needed for transition, or just replace):
```python
# Keep display_validation_warnings for now (cli/main.py:396 still calls it in validate-only path)
```

### 3e. Verify

```bash
make test && make check
```

All tests must pass. The key risk is the `_prepare_compilation` tuple unpacking at `compiler.py:731` — if wrong, `initial_params` becomes a tuple and template resolution crashes with `TypeError`.

---

## Phase 4: Create WorkflowRunner

**Goal**: Create `execution/runner.py` with `WorkflowRunner` class. Both `run()` and `validate()` methods. Does NOT yet replace existing callers — just exists alongside.

### 4a. Create `src/pflow/execution/runner.py`

This absorbs logic from:
- `WorkflowExecutorService.execute_workflow()` — main orchestration
- `WorkflowExecutorService._initialize_shared_store()` — shared store setup
- `WorkflowExecutorService._determine_workflow_status()` — status determination
- `WorkflowExecutorService._build_error_list()` + helpers — error extraction
- `WorkflowExecutorService._extract_warnings()` — warning extraction
- `WorkflowExecutorService._update_workflow_metadata()` — metadata update
- `WorkflowExecutorService._handle_execution_exception()` — exception handling
- `execute_workflow()` wrapper — CompilationError/MaxNodeVisitsError wrapping

Key design constraints from progress log:
1. **Stateless**: No mutable state on instance. `WorkflowRunner()` instantiated fresh per call.
2. **Per-execution resources**: `MCPConnectionPool`, `MemoizationCache`, `MetricsCollector`, `TraceCollector` created inside `run()`, never on init.
3. **Copy params at boundary**: `params = dict(params)` at top of `run()`.
4. **Single exception boundary**: `run()` catches all exceptions, wraps into `ExecutionResult`. Only `KeyboardInterrupt` and `SystemExit` propagate.
5. **`finally` for MCP pool shutdown**: Non-negotiable.

```python
"""Shared workflow execution runner for CLI and MCP entry points."""

import logging
import time
from typing import Any, Optional

from pflow.core.workflow.manager import WorkflowManager
from pflow.core.workflow.status import WorkflowStatus

from .output_interface import OutputInterface
from .result import ExecutionResult, ResolvedWorkflow, RunnerConfig, ValidationResult
from .workflow_resolver import resolve_workflow

logger = logging.getLogger(__name__)


class WorkflowRunner:
    """Stateless workflow execution pipeline.

    Both CLI and MCP create a fresh instance per call:
        result = WorkflowRunner().run(workflow, params, config, ...)

    The Runner owns:
    - Resolution (via unified resolve_workflow)
    - File reference resolution
    - Validation (WorkflowValidator, once)
    - Compilation (compile_ir_to_flow)
    - Execution (flow.run)
    - Resource lifecycle (MCP pool, cache, trace, metrics)
    - Metadata update (if workflow_manager provided)
    - Exception boundary (always returns ExecutionResult)

    The Runner does NOT own:
    - Display/formatting (caller's OutputInterface)
    - Trace saving to disk (caller reads result.trace)
    - Logging suppression (caller sets before calling)
    - Stdin reading (caller puts value in params)
    """

    def run(
        self,
        workflow: str | dict[str, Any],
        params: dict[str, Any],
        config: RunnerConfig,
        *,
        output: Optional[OutputInterface] = None,
        workflow_manager: Optional[WorkflowManager] = None,
        workflow_name: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute a workflow and return structured results.

        Args:
            workflow: File path, saved name, raw markdown, or IR dict.
            params: User-provided parameters. Copied at boundary.
            config: Immutable execution configuration.
            output: Display interface (CliOutput for CLI, NullOutput/None for MCP).
            workflow_manager: For metadata update on saved workflows. None = skip.
            workflow_name: Saved workflow name for metadata. None = skip.

        Returns:
            ExecutionResult — always. Never raises (except KeyboardInterrupt/SystemExit).
        """
        params = dict(params)  # Copy at boundary — never mutate caller's dict
        mcp_pool = None
        trace_collector = None
        metrics_collector = None  # REVIEW FIX #1: init before try for safe finally
        start_time = time.perf_counter()

        try:
            # Step 1: Resolve workflow
            resolved = self._resolve(workflow)

            # Step 2: Inject workflow file path for sub-workflow relative path resolution
            if resolved.file_path:
                params["_pflow_workflow_file"] = resolved.file_path

            # Step 3: Resolve external file references
            self._resolve_file_references(resolved.ir, params)

            # Step 3.5: Enrich params with input defaults before validation
            # REVIEW FIX #2: Without this, templates referencing default-only inputs
            # produce false validation errors. prepare_inputs() is idempotent —
            # the compiler calls it again inside _prepare_compilation(), harmless.
            self._enrich_params_with_defaults(resolved.ir, params)

            # Step 4: Validate (once, via WorkflowValidator)
            validation_warnings = self._validate(resolved.ir, params)

            # Step 5: Create per-execution resources
            from pflow.core.metrics import MetricsCollector
            from pflow.mcp.pool import MCPConnectionPool
            from pflow.runtime.cache import MemoizationCache
            from pflow.runtime.workflow_trace import WorkflowTraceCollector

            metrics_collector = MetricsCollector()
            metrics_collector.record_workflow_start()

            trace_collector = WorkflowTraceCollector(
                workflow_name=workflow_name or resolved.file_path or "unnamed"
            )

            mcp_pool = MCPConnectionPool()
            cache = MemoizationCache(read_enabled=config.cache_enabled)

            # Step 6: Initialize shared store
            shared_store = self._initialize_shared_store(
                params, config.verbose, output, mcp_pool, cache, trace_collector
            )

            # Step 7: Compile IR to PocketFlow Flow
            from pflow.registry import Registry
            from pflow.runtime import compile_ir_to_flow

            registry = Registry()
            flow = compile_ir_to_flow(
                resolved.ir,
                registry=registry,
                initial_params=params,
                validate=True,
                metrics_collector=metrics_collector,
                trace_collector=trace_collector,
                only_node=config.only_node,
            )

            # Step 8: Execute
            action_result = flow.run(shared_store)

            # Step 9: Determine status and extract results
            success, status = self._determine_status(action_result, shared_store)
            errors = self._build_errors(success, action_result, shared_store) if not success else []
            runtime_warnings = self._extract_runtime_warnings(shared_store)

            # Step 10: Update workflow metadata (fire-and-forget)
            duration = time.perf_counter() - start_time
            self._update_metadata(
                success, workflow_manager, workflow_name, params, duration
            )

            # Re-read trace collector from shared store (may have been replaced)
            trace_collector = shared_store.get("_trace_collector", trace_collector)
            if trace_collector:
                trace_collector.set_warnings(runtime_warnings)

            return ExecutionResult(
                success=success,
                status=status,
                shared_after=shared_store,
                errors=errors,
                warnings=runtime_warnings,
                validation_warnings=[self._warning_to_dict(w) for w in validation_warnings],
                trace=trace_collector,
                metrics=metrics_collector,
            )

        except (KeyboardInterrupt, SystemExit):
            raise

        except Exception as e:
            # Single exception boundary — wrap everything into ExecutionResult
            return self._exception_to_result(e, start_time, trace_collector)

        finally:
            # Non-negotiable: MCP pool shutdown
            if mcp_pool:
                try:
                    mcp_pool.shutdown()
                except Exception:
                    logger.debug("MCP pool shutdown error", exc_info=True)

            # REVIEW FIX #8: LLM interception cleanup (prevents leaked references)
            if trace_collector and hasattr(trace_collector, "cleanup_llm_interception"):
                try:
                    trace_collector.cleanup_llm_interception()
                except Exception:
                    logger.debug("LLM interception cleanup failed", exc_info=True)

            # REVIEW FIX #1: metrics_collector initialized to None before try
            if metrics_collector is not None:
                try:
                    metrics_collector.record_workflow_end()
                except Exception:
                    pass

    def validate(
        self,
        workflow: str | dict[str, Any],
        params: dict[str, Any],
        *,
        source_file_path: Optional[str] = None,
    ) -> ValidationResult:
        """Validate a workflow without executing it.

        Uses dummy parameter values. Does NOT call prepare_inputs().
        This is intentional — validate-only mode checks structure, not runtime values.

        Args:
            workflow: File path, saved name, raw markdown, or IR dict.
            params: User-provided parameters (used for template variable existence checks).
            source_file_path: For file reference resolution. Derived from resolution if None.

        Returns:
            ValidationResult with valid, errors, and warnings.
        """
        try:
            # Resolve
            resolved = self._resolve(workflow)
            file_path = source_file_path or resolved.file_path

            # Inject file path for sub-workflow resolution
            ir = resolved.ir
            if file_path:
                # Don't mutate caller's dict — but we need file path in IR context
                params = dict(params)
                params["_pflow_workflow_file"] = file_path

            # Resolve file references
            self._resolve_file_references(ir, params)

            # Generate dummy params for declared inputs
            from pflow.core.validation_utils import generate_dummy_parameters
            inputs = ir.get("inputs", {})
            dummy_params = generate_dummy_parameters(inputs)
            if file_path:
                dummy_params["_pflow_workflow_file"] = file_path

            # Validate with WorkflowValidator (8-step)
            from pflow.core.workflow.validator import WorkflowValidator
            from pflow.registry import Registry

            registry = Registry()
            errors, warnings = WorkflowValidator.validate(
                workflow_ir=ir,
                extracted_params=dummy_params,
                registry=registry,
                skip_node_types=False,
            )

            return ValidationResult(
                valid=len(errors) == 0,
                errors=errors,
                warnings=[self._warning_to_dict(w) for w in warnings],
            )

        except Exception as e:
            return ValidationResult(
                valid=False,
                errors=[str(e)],
                warnings=[],
            )

    # --- Internal helpers ---

    def _resolve(self, workflow: str | dict[str, Any]) -> ResolvedWorkflow:
        """Resolve workflow identifier to IR."""
        if isinstance(workflow, dict):
            # Caller passed pre-resolved IR dict
            from pflow.core import normalize_ir
            normalize_ir(workflow)
            return ResolvedWorkflow(ir=workflow, source="direct", file_path=None)
        return resolve_workflow(workflow)

    def _resolve_file_references(self, ir: dict[str, Any], params: dict[str, Any]) -> None:
        """Resolve external file references in IR."""
        import yaml
        from pflow.core.file_resolver import get_base_dir, resolve_file_references
        from pflow.runtime import CompilationError

        base_dir = get_base_dir(params)
        try:
            resolve_file_references(ir, base_dir)
        except (FileNotFoundError, yaml.YAMLError) as e:
            raise CompilationError(
                message=str(e), phase="file_resolution",
                details={"error": str(e)},
                suggestion="Check that the file path is correct and relative to the workflow file.",
            ) from e

    def _validate(self, ir: dict[str, Any], params: dict[str, Any]) -> list[Any]:
        """Run WorkflowValidator once. Returns validation warnings."""
        from pflow.core.workflow.validator import WorkflowValidator
        from pflow.registry import Registry

        registry = Registry()
        errors, warnings = WorkflowValidator.validate(
            workflow_ir=ir,
            extracted_params=params,
            registry=registry,
            skip_node_types=False,
        )

        if errors:
            from pflow.core.exceptions import WorkflowValidationError
            # REVIEW FIX #6: first positional is summary (str), not errors (list)
            raise WorkflowValidationError(validation_errors=errors)

        return warnings

    def _initialize_shared_store(
        self,
        params: dict[str, Any],
        verbose: bool,
        output: Optional[OutputInterface],
        mcp_pool: Any,
        cache: Any,
        trace_collector: Any,
    ) -> dict[str, Any]:
        """Prepare shared store with execution params and cross-cutting concerns."""
        shared_store: dict[str, Any] = {}

        # Seed with user params (params already has defaults from _prepare_compilation)
        shared_store.update(params)

        # REVIEW FIX #3: MCP nodes read shared.get("__verbose__", False)
        shared_store["__verbose__"] = verbose

        # Cross-cutting accumulators
        shared_store["__warnings__"] = {}

        # Progress callback from OutputInterface
        if output:
            callback = output.create_node_callback()
            if callback:
                shared_store["__progress_callback__"] = callback

        # Per-execution resources
        shared_store["__mcp_pool__"] = mcp_pool
        shared_store["__memoization_cache__"] = cache
        shared_store["_trace_collector"] = trace_collector

        return shared_store

    def _enrich_params_with_defaults(self, ir: dict[str, Any], params: dict[str, Any]) -> None:
        """REVIEW FIX #2: Enrich params with input defaults before validation.

        Without this, WorkflowValidator.validate() sees params without defaults.
        Templates referencing default-only inputs produce false validation errors.
        This is idempotent — _prepare_compilation() calls prepare_inputs() again
        inside compile_ir_to_flow(), which is harmless (same inputs, same outputs).
        """
        from pflow.runtime.compilation.compile_validation import _load_settings_env
        from pflow.runtime.compilation.ir_preparation import prepare_inputs

        settings_env = _load_settings_env()
        errors, defaults, env_param_names = prepare_inputs(ir, params, settings_env=settings_env)
        # Don't raise on errors here — let WorkflowValidator catch them with better messages
        params.update(defaults)
        if env_param_names:
            params["__env_param_names__"] = list(env_param_names)

    def _determine_status(
        self, action_result: Any, shared_store: dict[str, Any]
    ) -> tuple[bool, WorkflowStatus]:
        """Map action result + store state to (success, status)."""
        if action_result and isinstance(action_result, str) and action_result.startswith("error"):
            return False, WorkflowStatus.FAILED
        warnings = shared_store.get("__warnings__", {})
        template_errors = shared_store.get("__template_errors__", {})
        if warnings or template_errors:
            return True, WorkflowStatus.DEGRADED
        return True, WorkflowStatus.SUCCESS

    def _build_errors(
        self, success: bool, action_result: Any, shared_store: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Build error list from execution result. Delegates to executor_service logic."""
        # Reuse existing error extraction logic
        from .executor_service import WorkflowExecutorService
        svc = WorkflowExecutorService()
        return svc._build_error_list(success, action_result, shared_store)

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

    def _update_metadata(
        self,
        success: bool,
        workflow_manager: Optional[WorkflowManager],
        workflow_name: Optional[str],
        params: dict[str, Any],
        duration: float,
    ) -> None:
        """Update workflow metadata on successful execution."""
        if not (success and workflow_manager and workflow_name):
            return
        try:
            from pflow.mcp_server.utils.errors import sanitize_parameters
            from datetime import datetime

            env_param_names_list = params.get("__env_param_names__", [])
            env_param_names = set(env_param_names_list) if env_param_names_list else set()
            sanitized_params = sanitize_parameters(params, always_redact_keys=env_param_names)

            workflow_manager.update_metadata(
                workflow_name,
                {
                    "last_execution_timestamp": datetime.now().isoformat(),
                    "last_execution_success": True,
                    "last_execution_duration_seconds": round(duration, 2),
                    "last_execution_params": sanitized_params,
                    "execution_count": 1,
                },
            )
        except Exception:
            logger.debug("Metadata update failed", exc_info=True)

    def _exception_to_result(
        self, exception: Exception, start_time: float, trace_collector: Any
    ) -> ExecutionResult:
        """Convert any exception to ExecutionResult."""
        from pflow.core.exceptions import MaxNodeVisitsError, WorkflowValidationError
        from pflow.core.markdown_parser import MarkdownParseError
        from pflow.runtime import CompilationError

        error_dict: dict[str, Any] = {"source": "runtime", "message": str(exception)}

        if isinstance(exception, CompilationError):
            error_dict.update({
                "source": "compilation",
                "category": "compilation",
                "message": getattr(exception, "raw_message", str(exception)),
                "phase": getattr(exception, "phase", None),
                "node_id": getattr(exception, "node_id", None),
                "node_type": getattr(exception, "node_type", None),
                "suggestion": getattr(exception, "suggestion", None),
                "sub_workflow_path": (getattr(exception, "details", None) or {}).get("sub_workflow_path"),
            })
        elif isinstance(exception, MaxNodeVisitsError):
            error_dict.update({
                "source": "runtime",
                "category": "max_visits",
                "node_id": exception.node_id,
                "visit_count": exception.visit_count,
                "max_visits": exception.max_visits,
            })
        elif isinstance(exception, WorkflowValidationError):
            error_dict.update({"source": "validation", "category": "validation"})
        elif isinstance(exception, (MarkdownParseError, ValueError)):
            error_dict.update({"category": "validation"})
        elif isinstance(exception, WorkflowNotFoundError):
            error_dict.update({
                "category": "not_found",
                "similar_names": getattr(exception, "similar_names", []),
            })
        else:
            error_dict.update({"category": "execution_failure", "exception_type": type(exception).__name__})

        return ExecutionResult(
            success=False,
            status=WorkflowStatus.FAILED,
            errors=[error_dict],
            trace=trace_collector,
        )

    @staticmethod
    def _warning_to_dict(warning: Any) -> dict[str, Any]:
        """Convert ValidationWarning to agent-facing dict."""
        if isinstance(warning, dict):
            return warning
        return {
            "node": getattr(warning, "node_id", None),
            "node_type": getattr(warning, "node_type", None),
            "template": getattr(warning, "template", None),
            "message": str(warning) if not hasattr(warning, "reason") else warning.reason,
        }
```

### 4b. Add import for `WorkflowNotFoundError` at top of runner.py

```python
from pflow.core.exceptions import WorkflowNotFoundError
```

### 4c. Update `src/pflow/execution/__init__.py`

Add:
```python
from .runner import WorkflowRunner
```

### 4d. Verify

```bash
make test && make check
```

All tests must pass. The Runner exists but isn't called by CLI or MCP yet. It's just importable.

---

## Phase 5: Wire CLI to Runner

**Goal**: Replace `execute_json_workflow()`'s orchestration with `WorkflowRunner().run()`. This is the highest-risk phase — many functions in `main.py` get absorbed or simplified.

### 5a. Rewrite `execute_json_workflow()` in `src/pflow/cli/main.py`

The current function (lines 555-684, ~130 lines) becomes ~40 lines. Replace the entire function body.

**Functions absorbed by Runner** (delete their calls from `execute_json_workflow`):
- `_setup_execution_context()` — Runner creates MetricsCollector internally
- `_prepare_execution_environment()` — SPLIT: CLI keeps `CliOutput`/`DisplayManager`, Runner creates `TraceCollector`/`MetricsCollector`/`MemoizationCache`/`MCPConnectionPool`
- `_resolve_file_refs()` — Runner resolves file references internally
- `_validate_before_execution()` — Runner calls WorkflowValidator once internally

**Functions that stay in CLI**:
- `_handle_validate_only_mode()` → replaced by `runner.validate()` call
- `_handle_workflow_success()` — display concern
- `_save_trace_and_report()` — display concern
- `_cleanup_workflow_resources()` → simplified (Runner handles LLM cleanup, CLI handles temp files)

New `execute_json_workflow()`:

```python
def execute_json_workflow(
    ctx: click.Context,
    ir_data: dict[str, Any],
    stdin_data: str | StdinData | None = None,
    output_key: str | None = None,
    execution_params: dict[str, Any] | None = None,
    output_format: str = "text",
    metrics_collector: Any | None = None,  # Unused after Phase 1, kept for signature compat
) -> None:
    """Execute a workflow through the shared Runner."""
    from pflow.execution.runner import WorkflowRunner
    from pflow.execution.result import RunnerConfig

    params = dict(execution_params or {})

    # Route stdin to params (CLI concern — Runner never knows about stdin)
    if stdin_data:
        _route_stdin_to_params(ctx, stdin_data, ir_data, params)

    # Validate-only mode — separate method, separate result type
    if ctx.obj.get("validate_only"):
        from pflow.execution.result import ValidationResult
        runner = WorkflowRunner()
        vresult = runner.validate(ir_data, params,
            source_file_path=ctx.obj.get("source_file_path"))
        _display_validation_result(ctx, vresult, output_format)
        return

    # Build config
    verbose = ctx.obj.get("verbose", False)
    effective_verbose = verbose and output_format != "json"
    config = RunnerConfig(
        trace_enabled=ctx.obj.get("trace", True),
        cache_enabled=ctx.obj.get("cache", True),
        verbose=effective_verbose,
        only_node=ctx.obj.get("only_node"),
    )

    # Suppress PocketFlow "Flow ends" warnings in non-verbose mode
    if not effective_verbose:
        import warnings as _warnings
        _warnings.filterwarnings("ignore", message="Flow ends:*", module="pflow.pocketflow")

    # Suppress logging in JSON mode
    if output_format == "json":
        logging.getLogger().setLevel(logging.CRITICAL)

    # Store total nodes for --report (before Runner resolves)
    ctx.obj["total_nodes"] = len(ir_data.get("nodes", []))

    # Build output interface
    from pflow.cli.cli_output import CliOutput
    output_controller = _get_output_controller(ctx)
    cli_output = CliOutput(output_controller, effective_verbose, output_format)

    # Build display manager for execution start message
    display = DisplayManager(output_controller)
    workflow_name = ctx.obj.get("workflow_name")

    # Execute via Runner
    runner = WorkflowRunner()
    result = None
    try:
        # REVIEW FIX #5: show_execution_start takes (node_count: int), not (ir, name)
        display.show_execution_start(len(ir_data.get("nodes", [])))

        result = runner.run(
            ir_data, params, config,
            output=cli_output,
            # REVIEW FIX #7: merged resolver returns "library" not "saved"
            workflow_manager=WorkflowManager() if ctx.obj.get("workflow_source") == "library" else None,
            workflow_name=workflow_name,
        )

        if result.success:
            _handle_workflow_success(
                ctx, result, result.trace,
                result.shared_after, output_key, ir_data,
                output_format, result.metrics, effective_verbose,
            )
            if result.status == WorkflowStatus.DEGRADED:
                ctx.exit(2)
        else:
            # REVIEW FIX #4: output_error takes (ctx, result=..., output_format=..., ...)
            from pflow.cli.error_output import output_error
            output_error(
                ctx,
                result=result,
                output_format=output_format,
                shared_storage=result.shared_after,
                ir_data=ir_data,
                metrics_collector=result.metrics,
            )
            ctx.exit(1)

    except click.exceptions.Exit:
        raise
    except KeyboardInterrupt:
        click.echo("\n✗ Workflow execution interrupted", err=True)
        ctx.exit(130)
    except Exception as e:
        # REVIEW FIX #4: output_error signature — pass ctx, use result= or exception=
        from pflow.cli.error_output import output_error
        output_error(
            ctx,
            exception=e,
            output_format=output_format,
            shared_storage=result.shared_after if result else {},
            ir_data=ir_data,
        )
        ctx.exit(1)

    finally:
        # Trace saving — caller's job
        trace = result.trace if result else None
        if trace and config.trace_enabled:
            _save_trace_and_report(ctx, trace)

        # Temp file cleanup — caller's job (Runner handles LLM interception)
        _cleanup_temp_files(stdin_data, effective_verbose)

        # Restore logging level
        if output_format == "json":
            logging.getLogger().setLevel(logging.WARNING)
```

### 5b. Add `_display_validation_result()` function to `main.py`

New function replacing `_handle_validate_only_mode` + `_perform_validation` + `_display_validation_results`:

```python
def _display_validation_result(
    ctx: click.Context,
    vresult: Any,  # ValidationResult
    output_format: str,
) -> None:
    """Display validation result and exit with appropriate code."""
    if output_format == "json":
        import json
        output = {
            "success": vresult.valid,
            "validated_only": True,
            "errors": [{"message": e, "category": "validation"} for e in vresult.errors],
            "warnings": vresult.warnings,
        }
        click.echo(json.dumps(output, indent=2, default=str))
    else:
        if vresult.valid:
            from pflow.execution.formatters.validation_formatter import format_validation_success
            click.echo(format_validation_success())
            if vresult.warnings:
                # Convert warning dicts back to display format
                from pflow.runtime.compilation import display_validation_warnings
                # Display warnings using existing function (takes ValidationWarning objects)
                # For now, print simplified text warnings
                for w in vresult.warnings:
                    click.echo(f"  ⚠ {w.get('template', '?')}: {w.get('message', '')}", err=True)
        else:
            from pflow.execution.formatters.validation_formatter import format_validation_failure
            click.echo(format_validation_failure(vresult.errors))

    ctx.exit(0 if vresult.valid else 1)
```

### 5c. Remove absorbed imports from `main.py`

Remove these lazy imports (they're no longer called):
- `from pflow.execution.workflow_execution import execute_workflow` (line ~570)
- `from pflow.runtime.workflow_trace import WorkflowTraceCollector` (inside `_prepare_execution_environment`)

Add new import near top:
```python
from pflow.core.workflow.status import WorkflowStatus
```

### 5d. Simplify `_cleanup_workflow_resources`

Remove LLM interception cleanup (Runner handles it in finally). Keep only temp file cleanup:
```python
def _cleanup_workflow_resources(
    workflow_trace: Any | None,
    stdin_data: str | StdinData | None,
    verbose: bool,
) -> None:
    """Clean up temp files."""
    _cleanup_temp_files(stdin_data, verbose)
```

Actually — the Runner handles LLM interception cleanup internally (in its finally block). But the current code also does `workflow_trace.cleanup_llm_interception()` in the CLI. After Phase 5, the Runner does this, so the CLI just calls `_cleanup_temp_files` directly in its finally block. `_cleanup_workflow_resources` can be inlined or simplified.

### 5e. Functions that can be deleted from `main.py`

After this phase, these functions are dead code (no longer called):
- `_prepare_execution_environment` — split into RunnerConfig + CliOutput construction
- `_setup_execution_context` — Runner creates MetricsCollector
- `_resolve_file_refs` — Runner resolves file references
- `_validate_before_execution` — Runner validates
- `_handle_validate_only_mode` — replaced by `_display_validation_result`
- `_perform_validation` — replaced by `runner.validate()`
- `_display_validation_results` — replaced by `_display_validation_result`
- `_load_settings_env` — Runner loads settings env (via `_prepare_compilation`)

Keep these for now; delete after all tests pass. Mark with `# TODO: Remove after Phase 1 complete` if desired.

### 5f. Update `_prepare_execution_environment` references

The function `_prepare_execution_environment` previously set `ctx.obj["workflow_trace"]`. After Phase 5, `workflow_trace` comes from `result.trace`. Update `_save_trace_and_report` to accept the trace as a parameter (it already does — line 497).

### 5g. Verify

```bash
make test && make check
```

This is the highest-risk phase. Some tests mock `execute_workflow` or `WorkflowExecutorService` at specific paths — those tests will break here. Fix them in Phase 8, or temporarily skip if needed. The key verification is: run a real workflow from CLI and confirm identical output to baseline.

Also run smoke test baselines:
```bash
# Compare against baselines in .taskmaster/tasks/task_138/baseline/
uv run pflow examples/hello-world.pflow.md 2>/dev/null | diff - .taskmaster/tasks/task_138/baseline/01-hello-world.txt
```

---

## Phase 6: Wire MCP to Runner

**Goal**: Replace `ExecutionService.execute_workflow()`, `validate_workflow()`, and `run_registry_node()` with Runner calls.

### 6a. Rewrite `ExecutionService.execute_workflow()` in `src/pflow/mcp_server/services/execution_service.py`

Current: 98 lines (276-373). New: ~20 lines.

```python
@classmethod
@ensure_stateless
def execute_workflow(cls, workflow: Any, parameters: dict[str, Any] | None = None) -> str:
    """Execute a workflow and return formatted result string."""
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner
    from pflow.execution.workflow_resolver import resolve_workflow as _resolve

    # Validate parameters at system boundary (security check stays in MCP)
    validated_params = {}
    if parameters:
        validated_params = validate_execution_parameters(parameters)

    # Pre-resolve to get workflow_name for metadata and avoid double-resolution
    try:
        resolved = _resolve(workflow)
    except Exception as e:
        raise ValueError(str(e)) from e

    workflow_name_str = str(workflow) if resolved.source == "library" else None

    # Execute via Runner — pass resolved.ir (dict) to avoid double-resolution
    # The Runner's _resolve() detects isinstance(dict) and returns early
    runner = WorkflowRunner()
    result = runner.run(
        resolved.ir, validated_params, RunnerConfig(),
        workflow_manager=WorkflowManager(),
        workflow_name=workflow_name_str,
    )

    if result.success:
        formatted = _format_success_result(result, resolved)
        from pflow.execution.formatters.success_formatter import format_success_as_text
        return format_success_as_text(formatted)
    else:
        formatted = _format_error_result(result)
        # REVIEW FIX #12: _build_error_text takes (error_dict, trace_path).
        # Derive trace_path from result.trace or use a default.
        trace_path = getattr(result.trace, "trace_path", None) or Path.home() / ".pflow" / "debug" / "unknown-trace.json"
        raise RuntimeError(_build_error_text(formatted, trace_path))
```

Simplify `_format_success_result` and `_format_error_result` to take `ExecutionResult` directly (they currently take ~8 params). These formatting helpers stay in the MCP layer.

**Note**: The MCP `_inject_workflow_file_path` logic is now handled inside the Runner — when the Runner calls `_resolve()` on the dict (from `resolved.ir`), it gets `source="direct"` and `file_path=None`. The Runner must handle this: for pre-resolved IR from MCP, the file path information is lost. To preserve it, the MCP caller should set `resolved.ir["_pflow_workflow_file_hint"] = resolved.file_path` or pass it via params: `validated_params["_pflow_workflow_file"] = resolved.file_path` before calling `runner.run()`. The simplest fix: inject it into params before the Runner call:
```python
if resolved.file_path:
    validated_params["_pflow_workflow_file"] = resolved.file_path
```

### 6b. Rewrite `ExecutionService.validate_workflow()`

Current: 79 lines (375-453). New: ~12 lines.

```python
@classmethod
@ensure_stateless
def validate_workflow(cls, workflow: Any) -> str:
    """Validate a workflow and return formatted result string."""
    from pflow.execution.runner import WorkflowRunner

    runner = WorkflowRunner()
    vresult = runner.validate(workflow, {})

    if vresult.valid:
        from pflow.execution.formatters.validation_formatter import format_validation_success
        msg = format_validation_success()
        if vresult.warnings:
            warning_text = "\n".join(f"  ⚠ {w.get('template', '?')}: {w.get('message', '')}" for w in vresult.warnings)
            msg += f"\n\nWarnings:\n{warning_text}"
        return msg
    else:
        from pflow.execution.formatters.validation_formatter import format_validation_failure
        return format_validation_failure(vresult.errors)
```

### 6c. Rewrite `ExecutionService.run_registry_node()`

Current: 91 lines (701-791), bypasses compiler entirely. New: ~25 lines, uses synthetic IR through Runner.

```python
@classmethod
@ensure_stateless
def run_registry_node(cls, node_type: str, parameters: dict[str, Any] | None = None) -> str:
    """Run a single registry node via synthetic IR through the Runner."""
    from pflow.execution.result import RunnerConfig
    from pflow.execution.runner import WorkflowRunner

    # REVIEW FIX #9: Registry.get_node_info() doesn't exist. Use load().
    registry = Registry()
    nodes = registry.load()
    if node_type not in nodes:
        from pflow.execution.formatters.registry_run_formatter import format_node_not_found_error
        # REVIEW FIX #9: takes list[str], not Registry
        return format_node_not_found_error(node_type, list(nodes.keys()))

    # Validate parameters at system boundary
    if parameters:
        parameters = validate_execution_parameters(parameters)

    # Build synthetic single-node IR
    node_params = parameters or {}
    synthetic_ir = {
        "nodes": [{"id": node_type, "type": node_type, "params": node_params}],
        "edges": [],
    }

    # REVIEW FIX #10: Generate execution_id for read_fields pattern
    from pflow.core.execution_cache import ExecutionCache
    cache = ExecutionCache()
    execution_id = cache.generate_execution_id()

    # Execute with cache disabled (registry run is for discovery)
    # REVIEW FIX #11: Pass {} as Runner params, not node_params.
    # All user params are in synthetic_ir["nodes"][0]["params"] only.
    # Passing them as Runner params causes WorkflowValidator Step 7
    # to flag all node params as "unknown workflow inputs".
    config = RunnerConfig(cache_enabled=False)
    runner = WorkflowRunner()
    result = runner.run(synthetic_ir, {}, config)

    if result.success:
        # Extract and format node output
        from pflow.execution.formatters.node_output_formatter import format_node_output
        from pflow.core.settings import SettingsManager
        settings = SettingsManager().load()
        output_mode = getattr(settings.runtime, "registry_output_mode", "structure")

        outputs = result.shared_after.get(node_type, {})
        if isinstance(outputs, dict):
            formatted = format_node_output(
                outputs, node_type, format_type=output_mode, verbose=True,
                execution_id=execution_id,
            )
        else:
            formatted = str(outputs)

        # Cache for read_fields pattern
        cls._cache_execution_result(
            execution_id=execution_id,
            node_type=node_type,
            parameters=parameters,
            outputs=outputs if isinstance(outputs, dict) else {"result": outputs},
            action=None,
        )
        return formatted
    else:
        from pflow.execution.formatters.registry_run_formatter import format_execution_error
        error_msg = result.errors[0].get("message", "Unknown error") if result.errors else "Unknown error"
        return format_execution_error(node_type, error_msg)
```

### 6d. Remove absorbed helper functions

These are no longer needed after Runner replaces the logic:
- `_resolve_and_validate_workflow()` (lines 32-82)
- `_build_workflow_metadata()` (lines 85-109)
- `_inject_workflow_file_path()` (lines 240-246)
- `_check_inline_file_references()` (lines 249-266)
- `_configure_node_parameters()` (lines 581-641)
- `_extract_node_outputs()` (lines 643-670)

Keep: `_format_success_result`, `_format_error_result`, `_build_error_text`, `_cache_execution_result`, `save_workflow`, `_save_and_format_result`.

### 6e. Update MCP imports

Remove unused imports:
```python
# Remove:
from pflow.execution.workflow_execution import execute_workflow
from pflow.runtime import import_node_class
from ..utils.resolver import resolve_workflow  # Now using execution.workflow_resolver
```

### 6f. Verify

```bash
make test && make check
```

Run MCP smoke test baselines:
```bash
# Compare against .taskmaster/tasks/task_138/baseline/13-mcp-execute.txt and 14-mcp-registry-run.txt
```

---

## Phase 7: Delete Old Code

**Goal**: Remove files and functions that are no longer needed.

### 7a. Delete `src/pflow/execution/workflow_execution.py`

This thin wrapper is fully absorbed by the Runner. Its only function `execute_workflow()` is no longer called.

### 7b. Clean up `src/pflow/execution/executor_service.py`

The `WorkflowExecutorService` class is no longer called by production code. However, some tests still reference it directly (for testing helper methods like `_build_error_list`, `_determine_error_category`).

**Option A** (recommended): Keep the file but mark the class as deprecated. The Runner delegates `_build_errors()` to `svc._build_error_list()` for now. The class becomes an internal utility, not a public API.

**Option B**: Extract the helper methods (`_build_error_list`, `_extract_error_info`, `_determine_error_category`, etc.) into standalone functions in the same file. Remove the class. This requires updating test fixtures. Do this in a follow-up task.

For Phase 1, go with Option A — keep `WorkflowExecutorService` as internal utility. The Runner calls `svc._build_error_list()` in its `_build_errors()` method (already written in Phase 4).

### 7c. Remove `from .executor_service import WorkflowExecutorService` from `execution/__init__.py`

Keep `ExecutionResult` re-export from `result.py`. Remove `WorkflowExecutorService` from public API.

### 7d. Delete dead functions from `cli/main.py`

Remove these functions (confirmed dead after Phase 5):
- `_prepare_execution_environment` (lines 128-184)
- `_setup_execution_context` (lines 287-315)
- `_handle_validate_only_mode` (lines 416-445)
- `_perform_validation` (lines 318-360)
- `_display_validation_results` (lines 363-413)
- `_validate_before_execution` (lines 464-494)
- `_resolve_file_refs` (lines 448-461)
- `_load_settings_env` (lines 862-877)

Keep: `_validate_and_prepare_workflow_params` (still called from `_handle_named_workflow`), all stdin functions, all display functions, all Click handlers.

### 7e. Verify

```bash
make test && make check
```

---

## Phase 8: Test Migration

**Goal**: Fix all broken tests, file by file, priority order.

### Tier 1 — Direct import/mock of removed symbols

**8a. `tests/test_execution/test_workflow_execution.py`**
- Entire file tests `execute_workflow()` wrapper — which is deleted
- **Rewrite** to test `WorkflowRunner().run()` instead
- 4 mock patches of `WorkflowExecutorService` → mock `compile_ir_to_flow` or use real compilation
- Keep same behavioral assertions (CompilationError wrapping, MaxNodeVisitsError wrapping, NullOutput default)
- **Preserve** `TestCompilationErrorIntegration` as unmocked integration test (highest value)

**8b. `tests/test_execution/test_executor_service.py`**
- 13+ tests call `_update_workflow_metadata` directly
- The method still exists on `WorkflowExecutorService` (Option A from Phase 7)
- **Minimal change**: update import if `ExecutionResult` moved. Keep testing via `WorkflowExecutorService` instance for now.
- If the class is fully removed later, these tests move to test `WorkflowRunner._update_metadata` or standalone function.

**8b2. `tests/test_execution/test_api_warning_system.py`** *(REVIEW FIX: was missing from plan)*
- 3 direct `WorkflowExecutorService()` instantiations (lines 165, 191, 221)
- Tests call `svc._build_error_list()` and `svc._determine_error_category()` directly
- **Minimal change**: update `ExecutionResult` import. Keep `WorkflowExecutorService` usage (Option A).

**8c. `tests/test_cli/test_agent_ux_fixes.py`**
- Lines 200, 225: mock `pflow.execution.workflow_execution.WorkflowExecutorService.execute_workflow`
  → Change to mock `pflow.execution.runner.WorkflowRunner.run`
- Lines 290-334: instantiate `WorkflowExecutorService` for helper tests
  → Keep (Option A — class still exists as internal utility)
- Line 15: split import (`ExecutionResult` from `result`, `WorkflowExecutorService` from `executor_service`)
- **Note**: Tests constructing `ExecutionResult(...)` may need new fields (`trace=None`, `metrics=None`) if the constructor signature changes. The new fields have defaults so existing constructions should work without change.

**8d. `tests/test_runtime/test_checkpoint_tracking.py`**
- Line 256: `from pflow.execution.workflow_execution import execute_workflow` → `from pflow.execution.runner import WorkflowRunner`
- Line 277: `patch("pflow.execution.executor_service.WorkflowExecutorService.execute_workflow")` → `patch("pflow.execution.runner.WorkflowRunner.run")`
- Line 281: `execute_workflow(...)` → `WorkflowRunner().run(...)`

**8e. `tests/test_mcp/test_connection_pool.py`**
- Lines 526-599: 3 test methods instantiating `WorkflowExecutorService`
- Change to use `WorkflowRunner` or keep using the internal utility class
- Mock target `pflow.runtime.compile_ir_to_flow` → unchanged (still the same path)

**8f. `tests/test_cli/test_workflow_output_handling.py`**
- Line 86: `patch("pflow.execution.workflow_execution.execute_workflow")` → `patch("pflow.execution.runner.WorkflowRunner.run")`
- Line 106: `ExecutionResult` import path change

**8f2. `tests/test_cli/test_validate_only.py`** *(REVIEW FIX: moved from Tier 5 to Tier 1)*
- Tests 268-311 (JSON output shape) WILL break — new JSON has `{"success": true, "validated_only": true, "errors": [], "warnings": []}` instead of `{"success": true, "status": "valid", "message": "..."}`
- Update assertions: `output_data.get("message")` → `output_data.get("validated_only")`, add `"warnings"` key check
- Exit codes (0 for valid, 1 for invalid) must be preserved — `ctx.exit()` in `_display_validation_result`

### Tier 2 — Import path for ExecutionResult (already done in Phase 1)

Already handled in Phase 1f.

### Tier 3 — Resolver merge

**8g. `tests/test_cli/test_workflow_resolution.py`**
- Line 17: import from `pflow.cli.workflow_resolution` → `pflow.execution.workflow_resolver`
- Lines 30-116: `resolve_workflow(name, mock_wm)` returns `ResolvedWorkflow` not `(ir, source)` tuple
  → Unpack: `resolved = resolve_workflow(name, mock_wm); assert resolved.ir == ...; assert resolved.source == ...`
- **REVIEW FIX #7**: Source values change — `"saved"` → `"library"`. Update all `assert source == "saved"` to `assert resolved.source == "library"`.
- Lines 173-607: patches on `pflow.cli.workflow_resolution.WorkflowManager` → `pflow.execution.workflow_resolver.WorkflowManager`

**8g2. `tests/test_cli/test_nested_workflow_cli.py`** *(REVIEW FIX: was missing)*
- Line 182: patches `pflow.cli.workflow_resolution.WorkflowManager` → update to `pflow.execution.workflow_resolver.WorkflowManager`

### Tier 4 — Function absorbed

**8h. `tests/test_integration/test_template_resolution_hardening.py`**
- Line 32: `from pflow.execution.workflow_execution import execute_workflow` → `from pflow.execution.runner import WorkflowRunner`
- 12 call sites: `execute_workflow(workflow_ir=..., execution_params={})` → `WorkflowRunner().run(ir, {}, RunnerConfig())`
- Import `RunnerConfig` from `pflow.execution.result`
- **Note**: Argument names differ — `workflow_ir=` becomes first positional, `execution_params=` becomes second positional. Don't just rename — verify the positional ordering.

**8h2. `tests/test_mcp_server/test_registry_run_mcp.py`** *(REVIEW FIX: was missing)*
- After Phase 6 rewrites `run_registry_node()` to use Runner + synthetic IR, tests that mock `import_node_class` become stale (Runner doesn't call it).
- Update mocks to target the Runner's compilation path, or rewrite as behavioral tests against real registry.

### Tier 5 — Verify behavioral tests

**8i.** Run and verify these test files pass without changes:
- `tests/test_cli/test_validation_before_execution.py`
- `tests/test_mcp_server/test_execution_workflow.py` — **Note**: `test_nonexistent_workflow_raises_value_error` should still pass (Phase 6a preserves `ValueError` via `raise ValueError(str(e))`). Verify explicitly.
- `tests/test_mcp_server/test_registry_run_errors.py`
- `tests/test_mcp_server/test_validation_service.py`

### 8j. Verify after all migrations

```bash
make test && make check
```

All 4,671+ tests must pass.

---

## Phase 9: New Tests

**Goal**: Add regression guards and parity tests.

### 9a. CLI/MCP parity test

`tests/test_integration/test_cli_mcp_parity.py`:
- Execute the same simple workflow through `WorkflowRunner().run()` with `CliOutput` vs `NullOutput`
- Assert `ExecutionResult` fields match: `success`, `status`, `errors`, AND actual output values in `shared_after` (not just key presence — REVIEW FIX: checking keys only is a weak assertion)
- This catches future divergence

### 9b. Validator-called-once guard

`tests/test_execution/test_runner.py`:
- ~~Mock `WorkflowValidator.validate`, assert `call_count == 1`~~ *(REVIEW FIX: this tests mechanism, not behavior)*
- Instead: provide a workflow with a known validation error (e.g., cycle in data flow). Assert `WorkflowRunner().run()` returns `ExecutionResult(success=False)` with `"data_flow"` in the error category. Then verify `compile_ir_to_flow` was NOT called (compilation should not proceed past validation failure). This tests the behavioral outcome, not the call count.

### 9c. Registry run template resolution

`tests/test_mcp_server/test_registry_template.py`:
- Build synthetic IR with a shell node: `{"nodes": [{"id": "shell", "type": "shell", "params": {"command": "echo ${greeting}"}}]}`
- ~~Pass `{"greeting": "hello"}` as both node params and Runner params~~ *(REVIEW FIX: greeting must be a workflow-level concern, not duplicated in node.params)*
- Call `WorkflowRunner().run(synthetic_ir, {"greeting": "hello"}, RunnerConfig(cache_enabled=False))` — `greeting` is in Runner params (template resolution context), `command` is in node params (the template)
- Assert output contains "hello" not "${greeting}"
- **Note**: This tests template resolution path for registry-style single-node execution

### 9d. MCP gains warnings test

`tests/test_mcp_server/test_mcp_warnings.py`:
- Create a workflow with a node whose output type is `Any` and another node accessing `${node.output.nested_field}`
- Execute via `WorkflowRunner().run()`
- Assert `result.validation_warnings` is non-empty
- Assert warning dict has `node`, `node_type`, `template`, `message` keys with actual values (not just `len > 0`)

### 9e. Verify

```bash
make test && make check
```

---

## Phase 10: Final Verification

### 10a. Full test suite
```bash
make test && make check
```

### 10b. Smoke test baselines

Diff all 14 baselines in `.taskmaster/tasks/task_138/baseline/`:
```bash
for f in .taskmaster/tasks/task_138/baseline/*.txt; do echo "=== $f ==="; done
```

Run each smoke test command and compare. Only timing/timestamps/cache hits should differ.

### 10c. Manual spot checks

1. `uv run pflow examples/hello-world.pflow.md` — basic execution
2. `uv run pflow examples/hello-world.pflow.md --validate-only` — validate mode
3. `uv run pflow examples/hello-world.pflow.md --validate-only --output-format json` — JSON validate
4. `uv run pflow examples/hello-world.pflow.md --output-format json` — JSON execution
5. `uv run pflow registry run shell command="echo hello"` — registry run
6. Test a workflow with external file references (e.g., `file: ./script.py` in code blocks) — verifies `resolve_file_references` path through Runner

### 10d. Update CLAUDE.md files

Update these docs to reflect new structure:
- `src/pflow/execution/CLAUDE.md` — add Runner, remove WorkflowExecutorService as primary
- `src/pflow/cli/CLAUDE.md` — note thinned main.py
- `src/pflow/mcp_server/CLAUDE.md` — note thinned execution_service.py

---

## Critical Files Summary

| File | Action | Phase |
|------|--------|-------|
| `src/pflow/execution/result.py` | **CREATE** | 1 |
| `src/pflow/execution/workflow_resolver.py` | **CREATE** | 2 |
| `src/pflow/execution/runner.py` | **CREATE** | 4 |
| `src/pflow/execution/__init__.py` | Modify exports | 1,2,4,7 |
| `src/pflow/execution/executor_service.py` | Move `ExecutionResult` out, keep as utility | 1,7 |
| `src/pflow/execution/workflow_execution.py` | **DELETE** | 7 |
| `src/pflow/runtime/compilation/compile_validation.py` | Rename function, strip checks, tuple return | 3 |
| `src/pflow/runtime/compilation/compiler.py` | Add `only_node` param, unpack tuple | 3 |
| `src/pflow/cli/main.py` | Rewrite `execute_json_workflow`, delete 8 functions | 5,7 |
| `src/pflow/mcp_server/services/execution_service.py` | Rewrite 3 methods, delete 6 helpers | 6 |
| `src/pflow/execution/formatters/error_formatter.py` | Update import | 1 |
| 10 test files | Migration | 8 |
| 3 test files | **CREATE** | 9 |

## Known Limitations (Document, Don't Fix)

1. **Child workflow compilation warnings not in `ExecutionResult.validation_warnings`** — requires `compile_ir_to_flow()` return type change. Address in wrapper chain refactor.
2. **Batch child template validation uses dummy params** at pre-execution time (pre-existing, slightly wider gap).
3. **`WorkflowExecutorService` kept as internal utility** — helper methods (`_build_error_list`, etc.) not yet extracted to standalone functions. Follow-up cleanup.
4. **`sanitize_parameters` still imported from `mcp_server/utils/errors.py`** — architectural inversion. Move to `core/security_utils.py` in follow-up.
