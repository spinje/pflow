"""Shared workflow execution runner for CLI and MCP entry points."""

import contextlib
import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Optional

from pflow.core.diagnostic import (
    LLM_WARNING_CATEGORY,
    Diagnostic,
    Severity,
    deduplicate_diagnostics,
    exception_to_diagnostics,
    normalize_runtime_warning,
)
from pflow.core.exceptions import (
    CompilationError,
    MarkdownParseError,
    SchemaValidationError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from pflow.core.workflow.manager import WorkflowManager
from pflow.core.workflow.status import WorkflowStatus
from pflow.core.workflow_id import synthesize_inline_workflow_id

from .result import ExecutionResult, Plan, ResolvedWorkflow, RunnerConfig, ValidationResult
from .workflow_resolver import resolve_workflow

logger = logging.getLogger(__name__)


# Backward-compat alias: the helper moved to ``core/workflow_id.py`` so the
# analyzer can import it without crossing the ``core/`` ← ``execution/`` layer
# boundary. Tests and module-private callers under this prefix continue to
# work unchanged.
_synthesize_inline_workflow_id = synthesize_inline_workflow_id


class WorkflowRunner:
    """Stateless workflow execution pipeline.

    Both CLI and MCP create a fresh instance per call:
        result = WorkflowRunner().run(workflow, params, config, ...)

    The Runner owns:
    - Resolution (via unified resolve_workflow)
    - File reference resolution
    - Validation (WorkflowValidator, once)
    - Compilation (compile_workflow)
    - Execution (WorkflowEngine.run)
    - Resource lifecycle (MCP pool, cache, trace, metrics)
    - Metadata update (if workflow_manager provided)
    - Exception boundary (always returns ExecutionResult)

    The Runner does NOT own:
    - Display/formatting (caller renders results/progress)
    - Trace saving to disk (caller reads result.trace)
    - Logging suppression (caller sets before calling)
    - Stdin reading (caller puts value in params)
    """

    def run(
        self,
        workflow: str | dict[str, Any] | ResolvedWorkflow,
        params: dict[str, Any],
        config: RunnerConfig,
        *,
        progress_callback: Optional[Callable] = None,
        workflow_manager: Optional[WorkflowManager] = None,
        workflow_name: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute a workflow and return structured results.

        Args:
            workflow: File path, saved name, raw markdown, or IR dict.
            params: User-provided parameters. Copied at boundary.
            config: Immutable execution configuration.
            progress_callback: Optional per-node progress callback for CLI streaming.
            workflow_manager: For metadata update on saved workflows. None = skip.
            workflow_name: Saved workflow name for metadata. None = skip.

        Returns:
            ExecutionResult -- always. Never raises (except KeyboardInterrupt/SystemExit).
        """
        params = dict(params)  # Copy at boundary -- never mutate caller's dict

        # Resources created in run() scope so finally ALWAYS has them for cleanup.
        # If _execute_workflow raises after creating MCPConnectionPool (e.g. flow.run()
        # fails after MCP servers started), the pool must still be shut down.
        mcp_pool = None
        trace_collector = None
        metrics_collector = None
        validation_warnings: list[Diagnostic] = []
        start_time = time.perf_counter()

        try:
            # Resolve, validate, prepare
            resolved = self._prepare_workflow(workflow, params, validation_warnings)

            # Create per-execution resources (in run scope for safe cleanup)
            from pflow.core.metrics import MetricsCollector
            from pflow.mcp.pool import MCPConnectionPool
            from pflow.runtime.cache import MemoizationCache
            from pflow.runtime.workflow_trace import WorkflowTraceCollector

            metrics_collector = MetricsCollector()
            metrics_collector.record_workflow_start()

            # Task 159 E.1 trace 2.1.0: ``workflow_path`` is the canonical
            # identifier. File-based runs use the resolved path; inline runs
            # synthesize a stable ``ir-hash:<md5>`` (symmetric with
            # ``MemoizationCache.workflow_path`` scoping for inline rows).
            trace_workflow_path = resolved.file_path or _synthesize_inline_workflow_id(resolved.ir)
            trace_collector = WorkflowTraceCollector(
                workflow_name=workflow_name or resolved.file_path or "unnamed",
                workflow_path=trace_workflow_path,
            )

            mcp_pool = MCPConnectionPool()
            cache = MemoizationCache(read_enabled=config.cache_enabled)

            # Compile, execute, build result
            result = self._compile_and_execute(
                resolved,
                params,
                config,
                progress_callback,
                workflow_manager,
                workflow_name,
                validation_warnings,
                start_time,
                metrics_collector,
                trace_collector,
                mcp_pool,
                cache,
            )
            return result

        except (KeyboardInterrupt, SystemExit):
            raise

        except Exception as e:
            return self._exception_to_result(e, start_time, trace_collector, validation_warnings)

        finally:
            self._cleanup(mcp_pool, trace_collector, metrics_collector)

    def _prepare_workflow(
        self,
        workflow: str | dict[str, Any] | ResolvedWorkflow,
        params: dict[str, Any],
        diagnostics: list[Diagnostic],
    ) -> ResolvedWorkflow:
        """Resolve, inject file path, resolve file refs, enrich defaults, validate."""
        resolved = self._resolve(workflow)
        diagnostics.extend(resolved.diagnostics)

        # `_pflow_workflow_file` scopes memo-cache reads to the originating
        # workflow. File/library runs use the resolved absolute path; inline
        # runs (dict, content-string, MCP-inline) use a synthetic IR-content
        # hash so unrelated inline workflows with overlapping node IDs don't
        # pollute each other's cost/duration history. `setdefault` preserves
        # any value a caller pre-injected (back-compat with existing MCP/CLI
        # pre-injection sites).
        if resolved.file_path:
            params.setdefault("_pflow_workflow_file", resolved.file_path)
        else:
            params.setdefault("_pflow_workflow_file", _synthesize_inline_workflow_id(resolved.ir))

        self._resolve_file_references(resolved.ir, params)

        # Fill declared input names so validation doesn't flag them as missing.
        # Only needs to know WHICH inputs will be available, not their final values.
        # The real prepare_inputs() (type coercion, env resolution) runs once
        # in the compiler's _prepare_compilation().
        self._fill_declared_defaults(resolved.ir, params)

        validation_warnings = self._validate(resolved.ir, params)
        diagnostics.extend(validation_warnings)

        return resolved

    def _compile_and_execute(
        self,
        resolved: ResolvedWorkflow,
        params: dict[str, Any],
        config: RunnerConfig,
        progress_callback: Optional[Callable],
        workflow_manager: Optional[WorkflowManager],
        workflow_name: Optional[str],
        validation_warnings: list[Diagnostic],
        start_time: float,
        metrics_collector: Any,
        trace_collector: Any,
        mcp_pool: Any,
        cache: Any,
    ) -> ExecutionResult:
        """Compile IR, execute flow, build result.

        Resources (metrics, trace, mcp_pool, cache) are created by the caller
        and passed in so the caller's finally block can clean them up even if
        this method raises.
        """
        from pflow.registry import Registry
        from pflow.runtime import WorkflowEngine, compile_workflow

        # Strip validation placeholders BEFORE seeding shared store — a KeyError
        # on direct shared["input"] access is more honest than a placeholder string.
        self._strip_placeholders(params)

        shared_store = self._initialize_shared_store(
            params,
            config.verbose,
            progress_callback,
            mcp_pool,
            cache,
            trace_collector,
        )

        registry = Registry()
        workflow = compile_workflow(resolved.ir, registry=registry, initial_params=params)

        # Seed shared store with resolved defaults (from prepare_inputs).
        # User-provided params are already in shared_store via _initialize_shared_store.
        # resolved_defaults contains ONLY defaults for inputs not provided by the user,
        # so this doesn't overwrite user values.
        shared_store.update(workflow.resolved_defaults)

        engine = WorkflowEngine(
            metrics_collector=metrics_collector,
            trace_collector=trace_collector,
            only_node=config.only_node,
        )

        try:
            action_result = engine.run(workflow, shared_store)
        except Exception as e:
            # Annotate with failed_node from shared store before propagating —
            # _exception_to_result doesn't have shared_store access.
            # SKIP for OutputResolutionError: it runs in populate_declared_outputs
            # AFTER node execution finished, so the stale failed_node pointer
            # (from an already-recovered failure) would lie about the location.
            from pflow.core.user_errors import OutputResolutionError

            failed_node = shared_store.get("__execution__", {}).get("failed_node")
            if failed_node and not hasattr(e, "_pflow_node_id") and not isinstance(e, OutputResolutionError):
                e._pflow_node_id = failed_node  # type: ignore[attr-defined]
            parser_diagnostics = shared_store.get("__parser_diagnostics__", [])
            if parser_diagnostics and not hasattr(e, "_pflow_parser_diagnostics"):
                e._pflow_parser_diagnostics = list(parser_diagnostics)  # type: ignore[attr-defined]
            # Attach shared_store so _exception_to_result can populate
            # ExecutionResult.shared_after — without this, the rich __failures__
            # record and partial execution state are invisible to consumers
            # (CLI formatters, MCP consumers, build_execution_steps).
            if not hasattr(e, "_pflow_shared_store"):
                e._pflow_shared_store = shared_store  # type: ignore[attr-defined]
            raise

        success, status = self._determine_status(action_result, shared_store)
        errors = self._build_errors(success, action_result, shared_store) if not success else []
        runtime_warnings = self._extract_runtime_warnings(shared_store)
        diagnostics = deduplicate_diagnostics([*errors, *runtime_warnings, *validation_warnings])

        duration = time.perf_counter() - start_time
        self._update_metadata(success, workflow_manager, workflow_name, params, duration)

        trace_collector = shared_store.get("__trace_collector__", trace_collector)
        if trace_collector:
            trace_collector.set_warnings([
                diagnostic for diagnostic in diagnostics if diagnostic.severity == Severity.WARNING
            ])

        return ExecutionResult(
            success=success,
            status=status,
            shared_after=shared_store,
            trace=trace_collector,
            metrics=metrics_collector,
            diagnostics=diagnostics,
        )

    def validate(
        self,
        workflow: str | dict[str, Any] | ResolvedWorkflow,
        params: dict[str, Any],
        *,
        source_file_path: Optional[str] = None,
    ) -> ValidationResult:
        """Validate a workflow without executing it.

        Uses dummy parameter values for declared inputs. Does NOT call
        prepare_inputs(). This is intentional -- validate-only mode checks
        structure, not runtime values.

        Args:
            workflow: File path, saved name, raw markdown, or IR dict.
            params: User-provided parameters (used for template variable existence checks).
            source_file_path: For file reference resolution. Derived from resolution if None.

        Returns:
            ValidationResult with valid, errors, and warnings.
        """
        parser_diagnostics: list[Diagnostic] = []
        try:
            resolved = self._resolve(workflow)
            parser_diagnostics = list(resolved.diagnostics)
            file_path = source_file_path or resolved.file_path

            params = dict(params)  # Copy at boundary (consistent with run())
            ir = resolved.ir
            if file_path:
                params["_pflow_workflow_file"] = file_path

            self._resolve_file_references(ir, params)

            from pflow.core.validation_utils import generate_dummy_parameters

            inputs = ir.get("inputs", {})
            dummy_params = generate_dummy_parameters(inputs)
            if file_path:
                dummy_params["_pflow_workflow_file"] = file_path

            from pflow.core.workflow.validator import WorkflowValidator
            from pflow.registry import Registry

            registry = Registry()
            validator_diagnostics = WorkflowValidator.validate(
                workflow_ir=ir,
                extracted_params=dummy_params,
                registry=registry,
                skip_node_types=False,
                workflow_file=Path(file_path) if file_path else None,
            )
            diagnostics = [*resolved.diagnostics, *validator_diagnostics]
            # Compute ``valid`` from the combined list, not only ``validator_diagnostics``.
            # ``resolved.diagnostics`` only carries parser WARNINGs today, but the type
            # system permits ERROR severity there, so checking the combined list makes
            # the invariant explicit and hardens against future parser changes that add
            # error-severity diagnostics at resolution time.
            errors = [diagnostic for diagnostic in diagnostics if diagnostic.severity == Severity.ERROR]

            return ValidationResult(
                valid=len(errors) == 0,
                diagnostics=deduplicate_diagnostics(diagnostics),
            )

        except (
            WorkflowNotFoundError,
            SchemaValidationError,
            MarkdownParseError,
            ValueError,
            PermissionError,
            FileNotFoundError,
        ) as e:
            # Expected validation-phase errors → structured result
            return ValidationResult(
                valid=False,
                diagnostics=deduplicate_diagnostics([*parser_diagnostics, *exception_to_diagnostics(e)]),
            )
        except Exception as e:
            if isinstance(e, (WorkflowValidationError, CompilationError)):
                return ValidationResult(
                    valid=False,
                    diagnostics=deduplicate_diagnostics([*parser_diagnostics, *exception_to_diagnostics(e)]),
                )
            # Unexpected errors (programming bugs) — let them propagate.
            raise

    def plan(
        self,
        workflow: str | dict[str, Any] | ResolvedWorkflow,
        params: dict[str, Any],
        config: RunnerConfig,
    ) -> Plan:
        """Build an execution plan without invoking any node."""
        from pflow.execution.plan import build_plan
        from pflow.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.cache import MemoizationCache

        params = dict(params)

        validation_diags: list[Diagnostic] = []
        resolved = self._prepare_workflow(workflow, params, validation_diags)

        cache = MemoizationCache(read_enabled=config.cache_enabled)
        registry = Registry()

        self._strip_placeholders(params)
        compiled = compile_workflow(resolved.ir, registry=registry, initial_params=params)

        workflow_name = (
            resolved.file_path if resolved.file_path else (str(workflow) if isinstance(workflow, str) else "<workflow>")
        )
        plan = build_plan(
            compiled,
            params,
            cache,
            registry,
            workflow_name=workflow_name,
            only_node=config.only_node,
            _parent_workflow_file=resolved.file_path,
        )

        if validation_diags:
            plan = replace(plan, diagnostics=[*plan.diagnostics, *validation_diags])

        # Task 159 F3.3: append the dry-run cache nudge when actionable
        # opportunities exist (silent on optimal plans). Per DD#36, --dry-run
        # runs the FULL analytical pass — same analysis as `pflow analyze-cache`.
        cache_nudge = self._build_cache_nudge(resolved, params, workflow_name)
        if cache_nudge is not None:
            plan = replace(plan, diagnostics=[*plan.diagnostics, cache_nudge])

        return plan

    def _build_cache_nudge(
        self,
        resolved: ResolvedWorkflow,
        params: dict[str, Any],
        workflow_name: str,
    ) -> Diagnostic | None:
        """Run analyze() + summarize() to produce the dry-run cache nudge.

        Returns ``None`` when the cache plan is optimal (no actionable
        opportunities). On any analyzer-internal failure, log + return None
        — the nudge is advisory and must NEVER fail the dry-run.
        """
        try:
            from pathlib import Path

            from pflow.core.cache_analysis import analyze, summarize_from_analysis

            base_path = Path(resolved.file_path).parent if resolved.file_path else None
            analysis = analyze(
                resolved.ir,
                parameters=params,
                workflow_path=resolved.file_path or workflow_name,
                base_path=base_path,
                # Don't auto-load traces in --dry-run path — keeps latency
                # bounded; agents who want trace-correlated nudges run
                # `pflow analyze-cache --from-trace` directly.
                auto_load_trace=False,
            )
            return summarize_from_analysis(analysis)
        except Exception:
            logger.debug("Cache nudge generation failed; skipping", exc_info=True)
            return None

    # --- Internal helpers ---

    def _resolve(self, workflow: str | dict[str, Any] | ResolvedWorkflow) -> ResolvedWorkflow:
        """Resolve workflow identifier to IR."""
        if isinstance(workflow, ResolvedWorkflow):
            return workflow
        if isinstance(workflow, dict):
            from pflow.core import normalize_ir

            ir = dict(workflow)  # Copy — never mutate caller's dict
            normalize_ir(ir)
            return ResolvedWorkflow(ir=ir, source="direct", file_path=None)
        return resolve_workflow(workflow)

    def _resolve_file_references(self, ir: dict[str, Any], params: dict[str, Any]) -> None:
        """Resolve external file references in IR."""
        import yaml

        from pflow.core.file_resolver import get_base_dir, resolve_file_references

        base_dir = get_base_dir(params)
        try:
            resolve_file_references(ir, base_dir)
        except (FileNotFoundError, yaml.YAMLError) as e:
            raise CompilationError(
                message=str(e),
                phase="file_resolution",
                details={"error": str(e)},
                suggestion="Check that the file path is correct and relative to the workflow file.",
            ) from e

    def _validate(self, ir: dict[str, Any], params: dict[str, Any]) -> list[Diagnostic]:
        """Run WorkflowValidator once. Returns validation warnings."""
        from pflow.core.workflow.validator import WorkflowValidator
        from pflow.registry import Registry

        wf_path = params.get("_pflow_workflow_file")
        registry = Registry()
        validator_diagnostics = WorkflowValidator.validate(
            workflow_ir=ir,
            extracted_params=params,
            registry=registry,
            skip_node_types=False,
            workflow_file=Path(wf_path) if wf_path else None,
        )
        errors = [diagnostic for diagnostic in validator_diagnostics if diagnostic.severity == Severity.ERROR]
        warnings = [diagnostic for diagnostic in validator_diagnostics if diagnostic.severity == Severity.WARNING]

        if errors:
            raise WorkflowValidationError(
                validation_errors=errors,
                validation_warnings=list(warnings),
            )

        return warnings

    def _initialize_shared_store(
        self,
        params: dict[str, Any],
        verbose: bool,
        progress_callback: Optional[Callable],
        mcp_pool: Any,
        cache: Any,
        trace_collector: Any,
    ) -> dict[str, Any]:
        """Prepare shared store with execution params and cross-cutting concerns."""
        shared_store: dict[str, Any] = {}

        shared_store.update(params)
        shared_store["__verbose__"] = verbose
        shared_store["__warnings__"] = {}
        shared_store["__parser_diagnostics__"] = []

        if progress_callback is not None:
            shared_store["__progress_callback__"] = progress_callback

        shared_store["__mcp_pool__"] = mcp_pool
        shared_store["__memoization_cache__"] = cache
        shared_store["__trace_collector__"] = trace_collector

        return shared_store

    _PLACEHOLDER_PREFIX = "__pflow_declared_"

    def _fill_declared_defaults(self, ir: dict[str, Any], params: dict[str, Any]) -> None:
        """Fill declared input names so validation doesn't flag them as missing.

        The validator checks template variables against params. Without inputs
        filled in, ${name} produces a false "unresolved template" error.

        Adds real defaults for optional inputs, and placeholders for required/env
        inputs. Placeholders are stripped before compilation so prepare_inputs()
        correctly catches truly missing required inputs with (msg, path, suggestion).
        """
        for name, decl in ir.get("inputs", {}).items():
            if name not in params:
                if "default" in decl:
                    params[name] = decl["default"]
                else:
                    params[name] = f"{self._PLACEHOLDER_PREFIX}{name}__"

    def _strip_placeholders(self, params: dict[str, Any]) -> None:
        """Remove declared-input placeholders before compilation.

        Placeholders were added by _fill_declared_defaults to satisfy the validator.
        The compiler's prepare_inputs() needs them absent to detect truly missing
        required inputs with full (msg, path, suggestion) error tuples.
        """
        to_remove = [k for k, v in params.items() if isinstance(v, str) and v.startswith(self._PLACEHOLDER_PREFIX)]
        for k in to_remove:
            del params[k]

    def _determine_status(self, action_result: Any, shared_store: dict[str, Any]) -> tuple[bool, WorkflowStatus]:
        """Map action result + store state to (success, status)."""
        if action_result and isinstance(action_result, str) and action_result.startswith("error"):
            return False, WorkflowStatus.FAILED
        warnings = shared_store.get("__warnings__", {})
        template_errors = shared_store.get("__template_errors__", {})
        if warnings or template_errors:
            return True, WorkflowStatus.DEGRADED
        return True, WorkflowStatus.SUCCESS

    def _build_errors(self, success: bool, action_result: Any, shared_store: dict[str, Any]) -> list[Diagnostic]:
        """Build error list from execution result."""
        from .executor_service import build_error_list

        return build_error_list(success, action_result, shared_store)

    def _extract_runtime_warnings(self, shared_store: dict[str, Any]) -> list[Diagnostic]:
        """Extract runtime warnings from shared store."""
        warnings: list[Diagnostic] = []
        failures = shared_store.get("__failures__", {})
        for node_id, raw_message in shared_store.get("__warnings__", {}).items():
            message, warning_context = normalize_runtime_warning(raw_message)
            failure = failures.get(node_id)
            is_recovery = (
                failure is not None
                and failure.get("warning") is not None
                and failure.get("category") not in ("api_warning", "routing_error")
            ) or (
                # Sub-workflow recovery: __warnings__ propagates to parent
                # but __failures__ stays in child scope. Fall back to the
                # message pattern written by engine step 17.5.
                failure is None and "\u2014 on-error \u2192" in message
            )
            if is_recovery:
                category = failure.get("category") if failure else None
                warnings.append(
                    Diagnostic(
                        severity=Severity.WARNING,
                        message=message,
                        node_id=node_id,
                        source="runtime",
                        context={"type": "on_error_recovery", "category": category},
                    )
                )
            else:
                context = {"type": "api_warning"}
                context.update(warning_context)
                if "kind" in warning_context:
                    context.setdefault("category", LLM_WARNING_CATEGORY)
                warnings.append(
                    Diagnostic(
                        severity=Severity.WARNING,
                        message=message,
                        suggestions=[
                            f"Inspect '{node_id}' upstream inputs and output to verify the warning is expected.",
                            "If unintended, fix the upstream data or add error handling to this node.",
                        ],
                        node_id=node_id,
                        source="runtime",
                        context=context,
                    )
                )
        for node_id, error_data in shared_store.get("__template_errors__", {}).items():
            # Every entry in __template_errors__ carries a structured
            # Diagnostic built at the source site (see
            # runtime/engine/template_resolution.py — both the unresolved
            # template path and the type_validation path attach one).
            # The Diagnostic carries per-reference status, failure category,
            # peer suggestions, and typo hints — none of which a canned
            # one-line hint could express.
            attached = error_data.get("diagnostic") if isinstance(error_data, dict) else None
            if not isinstance(attached, Diagnostic):
                # Contract violation: a producer wrote to __template_errors__
                # without attaching a Diagnostic. Log and skip rather than
                # silently rendering a lossy one-liner.
                logger.warning(
                    "Skipping __template_errors__ entry for node %r: missing 'diagnostic' key. "
                    "All producers must attach a structured Diagnostic.",
                    node_id,
                )
                continue

            from dataclasses import replace

            warning = replace(attached, severity=Severity.WARNING)
            if not warning.node_id:
                warning = replace(warning, node_id=node_id)
            warnings.append(warning)
        for diagnostic in shared_store.get("__parser_diagnostics__", []):
            if isinstance(diagnostic, Diagnostic):
                warnings.append(diagnostic)
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
            from datetime import datetime

            from pflow.core.security_utils import sanitize_parameters

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
        self,
        exception: Exception,
        start_time: float,
        trace_collector: Any,
        validation_warnings: list[Diagnostic] | None = None,
    ) -> ExecutionResult:
        """Convert any exception to ExecutionResult.

        If the exception was annotated with ``_pflow_shared_store`` (by the
        engine's exception handler in ``_compile_and_execute``), the rich
        shared store — including ``__failures__``, per-node outputs, and
        batch metadata — is surfaced via ``ExecutionResult.shared_after``.
        Without this, CLI/MCP formatters lose all failure detail on
        exception-path crashes.
        """
        parser_diagnostics = [
            diagnostic
            for diagnostic in getattr(exception, "_pflow_parser_diagnostics", [])
            if isinstance(diagnostic, Diagnostic)
        ]
        # validation_warnings is a first-class attribute on WorkflowValidationError
        # (promoted from the previous ``_pflow_validation_warnings`` dynamic attr
        # pattern). Kept as getattr here because ``exception`` is loosely typed
        # at this layer — any exception can propagate through run(), and only
        # WorkflowValidationError carries this attribute.
        exception_validation_warnings = [
            diagnostic
            for diagnostic in getattr(exception, "validation_warnings", [])
            if isinstance(diagnostic, Diagnostic)
        ]
        diagnostics = deduplicate_diagnostics([
            *exception_to_diagnostics(exception),
            *(validation_warnings or []),
            *parser_diagnostics,
            *exception_validation_warnings,
        ])

        if trace_collector:
            trace_collector.set_warnings([
                diagnostic for diagnostic in diagnostics if diagnostic.severity == Severity.WARNING
            ])

        shared_after = getattr(exception, "_pflow_shared_store", None)
        if not isinstance(shared_after, dict):
            shared_after = {}

        return ExecutionResult(
            success=False,
            status=WorkflowStatus.FAILED,
            shared_after=shared_after,
            trace=trace_collector,
            diagnostics=diagnostics,
        )

    def _cleanup(self, mcp_pool: Any, trace_collector: Any, metrics_collector: Any) -> None:
        """Clean up per-execution resources."""
        if mcp_pool:
            try:
                mcp_pool.shutdown()
            except Exception:
                logger.debug("MCP pool shutdown error", exc_info=True)

        if metrics_collector is not None:
            with contextlib.suppress(Exception):
                metrics_collector.record_workflow_end()
