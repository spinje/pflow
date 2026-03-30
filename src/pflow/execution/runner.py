"""Shared workflow execution runner for CLI and MCP entry points."""

import contextlib
import logging
import time
from typing import Any, Optional

from pflow.core.exceptions import WorkflowNotFoundError
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
            ExecutionResult -- always. Never raises (except KeyboardInterrupt/SystemExit).
        """
        params = dict(params)  # Copy at boundary -- never mutate caller's dict

        # Resources created in run() scope so finally ALWAYS has them for cleanup.
        # If _execute_workflow raises after creating MCPConnectionPool (e.g. flow.run()
        # fails after MCP servers started), the pool must still be shut down.
        mcp_pool = None
        trace_collector = None
        metrics_collector = None
        start_time = time.perf_counter()

        try:
            # Resolve, validate, prepare
            resolved, validation_warnings = self._prepare_workflow(workflow, params)

            # Create per-execution resources (in run scope for safe cleanup)
            from pflow.core.metrics import MetricsCollector
            from pflow.mcp.pool import MCPConnectionPool
            from pflow.runtime.cache import MemoizationCache
            from pflow.runtime.workflow_trace import WorkflowTraceCollector

            metrics_collector = MetricsCollector()
            metrics_collector.record_workflow_start()

            trace_collector = WorkflowTraceCollector(workflow_name=workflow_name or resolved.file_path or "unnamed")

            mcp_pool = MCPConnectionPool()
            cache = MemoizationCache(read_enabled=config.cache_enabled)

            # Compile, execute, build result
            result = self._compile_and_execute(
                resolved,
                params,
                config,
                output,
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
            return self._exception_to_result(e, start_time, trace_collector)

        finally:
            self._cleanup(mcp_pool, trace_collector, metrics_collector)

    def _prepare_workflow(
        self,
        workflow: str | dict[str, Any],
        params: dict[str, Any],
    ) -> tuple[ResolvedWorkflow, list[Any]]:
        """Resolve, inject file path, resolve file refs, enrich defaults, validate.

        Returns (resolved, validation_warnings). Raises on validation error.
        """
        resolved = self._resolve(workflow)

        # For dict inputs (pre-resolved IR), file_path is always None here.
        # Callers who pre-resolve must inject _pflow_workflow_file into params
        # before calling run(). See MCP execute_workflow() and CLI execute_json_workflow().
        if resolved.file_path:
            params["_pflow_workflow_file"] = resolved.file_path

        self._resolve_file_references(resolved.ir, params)

        # Enrich params with input defaults before validation.
        # Without this, templates referencing default-only inputs produce
        # false validation errors. prepare_inputs() is idempotent -- the
        # compiler calls it again inside _prepare_compilation(), harmless.
        self._enrich_params_with_defaults(resolved.ir, params)

        validation_warnings = self._validate(resolved.ir, params)

        return resolved, validation_warnings

    def _compile_and_execute(
        self,
        resolved: ResolvedWorkflow,
        params: dict[str, Any],
        config: RunnerConfig,
        output: Optional[OutputInterface],
        workflow_manager: Optional[WorkflowManager],
        workflow_name: Optional[str],
        validation_warnings: list[Any],
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
        from pflow.runtime import compile_ir_to_flow

        shared_store = self._initialize_shared_store(params, config.verbose, output, mcp_pool, cache, trace_collector)

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

        action_result = flow.run(shared_store)

        success, status = self._determine_status(action_result, shared_store)
        errors = self._build_errors(success, action_result, shared_store) if not success else []
        runtime_warnings = self._extract_runtime_warnings(shared_store)

        duration = time.perf_counter() - start_time
        self._update_metadata(success, workflow_manager, workflow_name, params, duration)

        # Re-read trace collector from shared store (may have been replaced by sub-workflow)
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

    def validate(
        self,
        workflow: str | dict[str, Any],
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
        try:
            resolved = self._resolve(workflow)
            file_path = source_file_path or resolved.file_path

            ir = resolved.ir
            if file_path:
                params = dict(params)
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
                message=str(e),
                phase="file_resolution",
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

            # errors is list[str]; WorkflowValidationError accepts list[str | tuple]
            raise WorkflowValidationError(validation_errors=errors)  # type: ignore[arg-type]

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

        shared_store.update(params)
        shared_store["__verbose__"] = verbose
        shared_store["__warnings__"] = {}

        if output:
            callback = output.create_node_callback()
            if callback:
                shared_store["__progress_callback__"] = callback

        shared_store["__mcp_pool__"] = mcp_pool
        shared_store["__memoization_cache__"] = cache
        shared_store["_trace_collector"] = trace_collector

        return shared_store

    def _enrich_params_with_defaults(self, ir: dict[str, Any], params: dict[str, Any]) -> None:
        """Enrich params with input defaults before validation.

        Without this, WorkflowValidator.validate() sees params without defaults.
        Templates referencing default-only inputs produce false validation errors.
        This is idempotent -- _prepare_compilation() calls prepare_inputs() again
        inside compile_ir_to_flow(), which is harmless (same inputs, same outputs).
        """
        from pflow.runtime.compilation.compile_validation import _load_settings_env
        from pflow.runtime.compilation.ir_preparation import prepare_inputs

        settings_env = _load_settings_env()
        _errors, defaults, env_param_names = prepare_inputs(ir, params, settings_env=settings_env)
        # Don't raise on errors here -- let WorkflowValidator catch them with better messages
        params.update(defaults)
        if env_param_names:
            params["__env_param_names__"] = list(env_param_names)

    def _determine_status(self, action_result: Any, shared_store: dict[str, Any]) -> tuple[bool, WorkflowStatus]:
        """Map action result + store state to (success, status)."""
        if action_result and isinstance(action_result, str) and action_result.startswith("error"):
            return False, WorkflowStatus.FAILED
        warnings = shared_store.get("__warnings__", {})
        template_errors = shared_store.get("__template_errors__", {})
        if warnings or template_errors:
            return True, WorkflowStatus.DEGRADED
        return True, WorkflowStatus.SUCCESS

    def _build_errors(self, success: bool, action_result: Any, shared_store: dict[str, Any]) -> list[dict[str, Any]]:
        """Build error list from execution result. Delegates to executor_service logic."""
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
            from datetime import datetime

            from pflow.mcp_server.utils.errors import sanitize_parameters

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

    def _exception_to_result(self, exception: Exception, start_time: float, trace_collector: Any) -> ExecutionResult:
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
            # Include the actual validation errors, not just the summary
            validation_msgs = []
            for err in exception.validation_errors:
                if isinstance(err, tuple):
                    validation_msgs.append(err[0])  # (msg, path, suggestion) -> msg
                else:
                    validation_msgs.append(str(err))
            message = "\n".join(validation_msgs) if validation_msgs else str(exception)
            error_dict.update({
                "source": "validation",
                "category": "validation",
                "message": message,
                "validation_errors": validation_msgs,
            })
        elif isinstance(exception, (MarkdownParseError, ValueError)):
            error_dict.update({"category": "validation"})
        elif isinstance(exception, WorkflowNotFoundError):
            error_dict.update({
                "category": "not_found",
                "similar_names": getattr(exception, "similar_names", []),
            })
        else:
            error_dict.update({
                "category": "execution_failure",
                "exception_type": type(exception).__name__,
            })

        return ExecutionResult(
            success=False,
            status=WorkflowStatus.FAILED,
            errors=[error_dict],
            trace=trace_collector,
        )

    def _cleanup(self, mcp_pool: Any, trace_collector: Any, metrics_collector: Any) -> None:
        """Clean up per-execution resources."""
        if mcp_pool:
            try:
                mcp_pool.shutdown()
            except Exception:
                logger.debug("MCP pool shutdown error", exc_info=True)

        if trace_collector and hasattr(trace_collector, "cleanup_llm_interception"):
            try:
                trace_collector.cleanup_llm_interception()
            except Exception:
                logger.debug("LLM interception cleanup failed", exc_info=True)

        if metrics_collector is not None:
            with contextlib.suppress(Exception):
                metrics_collector.record_workflow_end()

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
