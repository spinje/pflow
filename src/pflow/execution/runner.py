"""Shared workflow execution runner for CLI and MCP entry points."""

import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pflow.core.diagnostic import (
    LLM_WARNING_CATEGORY,
    Diagnostic,
    Severity,
    deduplicate_diagnostics,
    exception_to_diagnostics,
    normalize_runtime_warning,
    warning_degrades_status,
)
from pflow.core.exceptions import (
    CompilationError,
    GateDenied,
    MarkdownParseError,
    SchemaValidationError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from pflow.core.workflow.manager import WorkflowManager
from pflow.core.workflow.status import WorkflowStatus
from pflow.core.workflow_id import synthesize_inline_workflow_id, workflow_content_hash

from .result import ExecutionResult, Plan, ResolvedWorkflow, RunnerConfig, ValidationResult
from .workflow_resolver import resolve_workflow

if TYPE_CHECKING:
    from pflow.runtime.workflow_trace import ResumeSource

logger = logging.getLogger(__name__)


def _is_degrading_warning(value: Any) -> bool:
    """Return True when a ``__warnings__`` entry should flip workflow status to DEGRADED.

    Parser/validator diagnostics are definition-quality signals, not runtime
    degradation. ``Severity.INFO`` entries are advisories. Legacy string/dict
    shapes without severity/source fail closed as degrading.
    """
    return warning_degrades_status(value)


# Backward-compat alias: the helper moved to ``core/workflow_id.py`` so the
# analyzer can import it without crossing the ``core/`` ← ``execution/`` layer
# boundary. Tests and module-private callers under this prefix continue to
# work unchanged.
_synthesize_inline_workflow_id = synthesize_inline_workflow_id


def _workflow_path_id(resolved: ResolvedWorkflow) -> str:
    """Canonical workflow identifier: the resolved file path, or a synthesized
    ``ir-hash:<md5>`` for inline runs (dict / content-string / MCP-inline).

    The trace collector's ``workflow_path``, the memo-cache scoping key
    (``_pflow_workflow_file``), and the ``--only`` snapshot loader (issue #443)
    MUST all use this exact value — otherwise the snapshot loader won't find the
    workflow's own most-recent full-run trace. Single source so the three sites
    can't drift byte-for-byte.
    """
    return resolved.file_path or _synthesize_inline_workflow_id(resolved.ir)


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
        progress_callback: Callable | None = None,
        gate_resolver: Callable | None = None,
        workflow_manager: WorkflowManager | None = None,
        workflow_name: str | None = None,
        resume_source: "ResumeSource | None" = None,
    ) -> ExecutionResult:
        """Execute a workflow and return structured results.

        Args:
            workflow: File path, saved name, raw markdown, or IR dict.
            params: User-provided parameters. Copied at boundary.
            config: Immutable execution configuration.
            progress_callback: Optional per-node progress callback for CLI streaming.
            gate_resolver: Optional Task 125 gate resolver (see ``core/gate.py`` for
                the contract; built via ``execution.gate_prompt.build_gate_resolver``).
                Installed as ``__gate_resolver__`` exactly like the progress callback.
                None = gates fail loudly with ``GateNotInteractiveError``.
            workflow_manager: For metadata update on saved workflows. None = skip.
            workflow_name: Saved workflow name for metadata. None = skip.
            resume_source: Optional Task 164 resume source (built by
                ``runtime.workflow_trace.load_resume_source``). Rides as a kwarg —
                the Task 125 ``gate_resolver`` precedent; ``RunnerConfig`` stays
                execution-config-only. The caller merges ``resume_source.inputs``
                into ``params`` BEFORE calling; the runner threads the entry node,
                events, and lineage id to the collector and engine, nothing more.
                Its ``entry_node_id`` must already be resolved (never ``None``).

        Returns:
            ExecutionResult -- always. Never raises (except KeyboardInterrupt/SystemExit).
        """
        if resume_source is not None and resume_source.entry_node_id is None:
            # Library-misuse guard (mirrors the engine's resume_from+only_node
            # ValueError): a between-nodes source must have its entry resolved
            # by the CLI before run() — threading None would silently run the
            # whole workflow from the start while claiming a resume.
            raise ValueError("resume_source.entry_node_id must be resolved before run()")
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
            trace_workflow_path = _workflow_path_id(resolved)
            # Task 173 replay version fingerprint: hash the PRISTINE resolved IR (logical only — source-line
            # provenance stripped, see workflow_content_hash) so a replay can detect the file was edited since
            # this run (a node renamed/removed/re-nested), but NOT false-flag a comment/whitespace edit. Must
            # be computed BEFORE any IR-touching compile step — `_fill_declared_defaults` (above, in
            # _prepare_workflow) writes only to `params`, never to `resolved.ir`, so this site stays pristine.
            content_hash = workflow_content_hash(resolved.ir)
            trace_collector = WorkflowTraceCollector(
                workflow_name=workflow_name or resolved.file_path or "unnamed",
                workflow_path=trace_workflow_path,
                # Task 172: THE single run-scoped collector. Sub-workflows record flat into it with
                # emit-time correlation; the per-sub-workflow buffer collectors stay is_run_scoped=False.
                is_run_scoped=True,
                # Stream one JSONL line per node to disk as the run executes (so a live overlay can tail
                # it) — gated by trace_enabled: the CLI persists (True); MCP reads cost from the in-memory
                # collector and passes trace_enabled=False; --no-trace is False.
                stream_to_disk=config.trace_enabled,
                # Stamped into the trace `meta` line; the replay tailer compares it to the current file's
                # digest to flag a stale (different-version) run (Task 173).
                content_hash=content_hash,
                # Task 175: None for every normal run (mint a UUID); a `pflow ui` ▶ launch forces it so
                # the browser can pin the overlay to the exact run it spawned.
                execution_id=config.execution_id,
                # Task 164: attempt-chain lineage. Set at CONSTRUCTION — before
                # start_streaming — because it rides the meta line (_meta_fields).
                resumed_from=resume_source.execution_id if resume_source is not None else None,
            )

            mcp_pool = MCPConnectionPool()
            cache = MemoizationCache(read_enabled=config.cache_enabled)

            # Compile, execute, build result
            result = self._compile_and_execute(
                resolved,
                params,
                config,
                progress_callback,
                gate_resolver,
                workflow_manager,
                workflow_name,
                validation_warnings,
                start_time,
                metrics_collector,
                trace_collector,
                mcp_pool,
                cache,
                resume_source,
            )
            return result

        except (KeyboardInterrupt, SystemExit):
            raise

        except Exception as e:
            return self._exception_to_result(e, start_time, trace_collector, validation_warnings)

        finally:
            # The runner owns finalization of the streamed trace it opened: any caller — CLI, MCP, or a
            # library caller that just inspects the result — ends with a COMPLETE, closed trace rather
            # than an open handle + a trailer-less "incomplete" file. Idempotent + suppressed so it can
            # never mask the run result. The CLI opts out (finalize_trace=False) because it finalizes
            # itself AFTER mutating the trace post-run (set_json_output); MCP's trace never streams, so
            # finalize is a harmless no-op there.
            if config.finalize_trace and trace_collector is not None:
                with contextlib.suppress(Exception):
                    trace_collector.finalize()
            self._cleanup(mcp_pool, trace_collector, metrics_collector)

    def _prepare_workflow(
        self,
        workflow: str | dict[str, Any] | ResolvedWorkflow,
        params: dict[str, Any],
        diagnostics: list[Diagnostic],
    ) -> ResolvedWorkflow:
        """Resolve, inject file path, enrich defaults, validate.

        File reference resolution happens inside ``resolve_workflow()`` at the
        IR-load boundary (see ``execution/workflow_resolver.py``). The Runner
        never re-resolves; ``ResolvedWorkflow.ir`` is the canonical resolved IR.
        """
        resolved = self._resolve(workflow)
        diagnostics.extend(resolved.diagnostics)

        # `_pflow_workflow_file` scopes memo-cache reads to the originating
        # workflow. File/library runs use the resolved absolute path; inline
        # runs (dict, content-string, MCP-inline) use a synthetic IR-content
        # hash so unrelated inline workflows with overlapping node IDs don't
        # pollute each other's cost/duration history. `setdefault` preserves
        # any value a caller pre-injected (back-compat with existing MCP/CLI
        # pre-injection sites).
        params.setdefault("_pflow_workflow_file", _workflow_path_id(resolved))

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
        progress_callback: Callable | None,
        gate_resolver: Callable | None,
        workflow_manager: WorkflowManager | None,
        workflow_name: str | None,
        validation_warnings: list[Diagnostic],
        start_time: float,
        metrics_collector: Any,
        trace_collector: Any,
        mcp_pool: Any,
        cache: Any,
        resume_source: "ResumeSource | None" = None,
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
            gate_resolver,
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

        # Task 175: stamp the run's resolved top-level inputs onto the trace's eager
        # ``meta`` line. ORDERING IS LOAD-BEARING — this MUST run after the defaults
        # merge above (so every input holds its FINAL value) and BEFORE engine.run()
        # below (which calls trace.start_streaming() and flushes the meta line). The
        # snapshot is IR-driven: resolved.ir["inputs"] is keyed by bare input name and
        # shared_store holds each input's resolved value (user arg / env / settings /
        # default), so this is immune to the params-vs-defaults split and never carries
        # ``_``/``__`` internal keys. Do NOT replace with {**params, **resolved_defaults}.
        if trace_collector is not None:
            trace_collector.inputs = {
                name: shared_store[name] for name in resolved.ir.get("inputs", {}) if name in shared_store
            }

        engine = WorkflowEngine(
            metrics_collector=metrics_collector,
            trace_collector=trace_collector,
            only_node=config.only_node,
            # issue #443: byte-identical to the trace collector's workflow_path
            # (resolved file path or synthesized ir-hash:<md5>) so --only's
            # snapshot loader finds this workflow's own most-recent full-run trace.
            workflow_path=_workflow_path_id(resolved),
            # Task 164: resume re-entry — the failed node K, the source trace's
            # events to seed upstream from, and the source run's id for the
            # __execution__ lineage stamp.
            resume_from=resume_source.entry_node_id if resume_source is not None else None,
            resume_events=resume_source.events if resume_source is not None else None,
            resume_source_id=resume_source.execution_id if resume_source is not None else None,
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
            # Include INFO advisories alongside WARNING — INFO diagnostics surface
            # in reports per the severity-aware status contract (see
            # `_is_degrading_warning`). Filtering INFO out here would make
            # advisories like `cache.routed-provider-degraded` invisible on the
            # trace surface even though they're in `result.diagnostics`. Matches
            # the precedent at `cli/commands/run.py:365` and `mermaid.py`.
            trace_collector.set_warnings([
                diagnostic for diagnostic in diagnostics if diagnostic.severity in {Severity.WARNING, Severity.INFO}
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
        source_file_path: str | None = None,
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

            # File resolution happens inside resolve_workflow() at the IR-load
            # boundary. ``ir`` is already fully resolved by the time we get
            # here. See ``execution/workflow_resolver.py`` module docstring.

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
            # ``resolved.diagnostics`` carries parser advisories as well as any future
            # parser errors, so checking the combined list keeps validity tied to
            # severity rather than whichever phase produced the diagnostic.
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

            from pflow.core.prompt_cache_analysis import analyze, summarize_from_analysis

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

    def _validate(self, ir: dict[str, Any], params: dict[str, Any]) -> list[Diagnostic]:
        """Run WorkflowValidator once. Returns non-error validation diagnostics."""
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
        non_error_diagnostics = [
            diagnostic for diagnostic in validator_diagnostics if diagnostic.severity is not Severity.ERROR
        ]

        if errors:
            raise WorkflowValidationError(
                validation_errors=errors,
                validation_warnings=list(non_error_diagnostics),
            )

        return non_error_diagnostics

    def _initialize_shared_store(
        self,
        params: dict[str, Any],
        verbose: bool,
        progress_callback: Callable | None,
        gate_resolver: Callable | None,
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

        if gate_resolver is not None:
            shared_store["__gate_resolver__"] = gate_resolver

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
        """Map action result + store state to (success, status).

        DEGRADED fires when ``__template_errors__`` is non-empty OR
        ``__warnings__`` contains at least one runtime-degrading warning.
        Parser/validator diagnostics and ``Severity.INFO`` advisories surface
        in diagnostics/reports but do not flip workflow status. Legacy
        severity-less warning shapes fail closed as degrading.
        """
        if action_result and isinstance(action_result, str) and action_result.startswith("error"):
            return False, WorkflowStatus.FAILED
        if shared_store.get("__template_errors__"):
            return True, WorkflowStatus.DEGRADED
        warnings = shared_store.get("__warnings__", {})
        if any(_is_degrading_warning(value) for value in warnings.values()):
            return True, WorkflowStatus.DEGRADED
        return True, WorkflowStatus.SUCCESS

    def _build_errors(self, success: bool, action_result: Any, shared_store: dict[str, Any]) -> list[Diagnostic]:
        """Build error list from execution result."""
        from .executor_service import build_error_list

        return build_error_list(success, action_result, shared_store)

    def _extract_runtime_warnings(self, shared_store: dict[str, Any]) -> list[Diagnostic]:
        """Extract runtime warnings from shared store."""
        warnings: list[Diagnostic] = []
        for node_id, raw_message in shared_store.get("__warnings__", {}).items():
            if isinstance(raw_message, Diagnostic):
                # Catalog-emitted Diagnostic. Preserve as-is and bypass the
                # api_warning classifier plus canned suggestions:
                # the Diagnostic already carries id, severity, category,
                # suggestions, and path context end-to-end.
                warnings.append(raw_message if raw_message.node_id else replace(raw_message, node_id=node_id))
                continue

            message, warning_context = normalize_runtime_warning(raw_message)
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
        workflow_manager: WorkflowManager | None,
        workflow_name: str | None,
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
        shared_after = getattr(exception, "_pflow_shared_store", None)
        if not isinstance(shared_after, dict):
            shared_after = {}

        runtime_warnings = self._extract_runtime_warnings(shared_after) if shared_after else []
        diagnostics = deduplicate_diagnostics([
            *exception_to_diagnostics(exception),
            *runtime_warnings,
            *(validation_warnings or []),
            *parser_diagnostics,
            *exception_validation_warnings,
        ])

        if trace_collector:
            # Include INFO advisories alongside WARNING — see parallel site at
            # the success path (around line 290) for rationale.
            trace_collector.set_warnings([
                diagnostic for diagnostic in diagnostics if diagnostic.severity in {Severity.WARNING, Severity.INFO}
            ])

        # A denied gate is a human verdict, not a failure (Task 125 Decision 5):
        # the gated node never ran, nothing broke. Payload diagnostics arrive
        # intact via exception_to_diagnostics → GateDenied.to_diagnostics above;
        # the CLI maps DENIED to its own display + exit code 3.
        status = WorkflowStatus.DENIED if isinstance(exception, GateDenied) else WorkflowStatus.FAILED
        return ExecutionResult(
            success=False,
            status=status,
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
