"""Execution service for MCP server.

This service handles workflow execution, validation, saving,
and node testing operations.
"""

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pflow.core.diagnostic import Diagnostic, Severity, exception_to_diagnostics
from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.exceptions import (
    CompilationError,
    MarkdownParseError,
    PflowError,
    WorkflowExistsError,
    WorkflowNotFoundError,
    WorkflowValidationError,
)
from pflow.core.workflow.manager import WorkflowManager
from pflow.execution.workflow_resolver import resolve_workflow as _unified_resolve
from pflow.registry import Registry

from ..utils.validation import (
    validate_execution_parameters,
)
from .base_service import BaseService, ensure_stateless

if TYPE_CHECKING:
    from pflow.core.param_coercion import InputSource

logger = logging.getLogger(__name__)


def _from_the_call(parameters: Mapping[str, Any]) -> dict[str, "InputSource"]:
    """Every MCP parameter arrives in the call as typed JSON: labelled ``call``, never inferred."""
    return dict.fromkeys(parameters, "call")


def _workflow_metadata(resolved: Any, workflow_name_display: str) -> dict[str, Any]:
    """The outcome's ``workflow`` block. ``name`` is user-facing (``my-workflow``), never the
    absolute file path — the MCP text leads with ``{name} was executed``."""
    if resolved.source == "library":
        return {"action": "reused", "name": workflow_name_display or str(resolved.file_path)}
    if resolved.source == "file":
        return {"action": "unsaved", "name": workflow_name_display or str(resolved.file_path)}
    return {"action": "unsaved"}


def _mcp_surfaced_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Diagnostics worth surfacing on MCP text/structured responses.

    MCP suppresses runtime INFO notes that duplicate structured data agents can
    inspect directly (for example empty-batch metadata), but parser/validator
    INFO diagnostics are definition-quality advisories with no other surface.
    """
    return [
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.severity is Severity.WARNING
        or (diagnostic.severity is Severity.INFO and diagnostic.source in {"parser", "validator"})
    ]


def _format_mcp_diagnostic_sections(diagnostics: list[Diagnostic]) -> str:
    warning_diagnostics = [diagnostic for diagnostic in diagnostics if diagnostic.severity is Severity.WARNING]
    advisory_diagnostics = [diagnostic for diagnostic in diagnostics if diagnostic.severity is Severity.INFO]
    sections: list[str] = []
    if warning_diagnostics:
        sections.append("Warnings:\n" + "\n".join(format_diagnostic(warning) for warning in warning_diagnostics))
    if advisory_diagnostics:
        sections.append("Advisories:\n" + "\n".join(format_diagnostic(advisory) for advisory in advisory_diagnostics))
    return "\n\n".join(sections)


class ExecutionService(BaseService):
    """Service for workflow execution and related operations.

    Handles workflow execution, validation, saving, and node testing
    while maintaining stateless pattern.
    """

    @classmethod
    @ensure_stateless
    def execute_workflow(
        cls,
        workflow: Any,
        parameters: dict[str, Any] | None = None,
        auto_approve: list[str] | None = None,
    ) -> str:
        """Execute a workflow with agent-optimized defaults.

        Args:
            workflow: Workflow name, path, or IR dict
            parameters: Execution parameters
            auto_approve: Step names whose approval gates are pre-approved. An
                unlisted gate pauses durably when its checkpoint is persisted;
                otherwise the response contains remediation guidance. Escalation
                gates also pause and cannot be pre-approved.

        Returns:
            Formatted text output matching CLI (success or error)

        Raises:
            ValueError: If workflow not found (with suggestions) or parameters fail security validation
            RuntimeError: All other failures (validation, compilation, execution)
        """
        from pflow.execution.gate_prompt import build_gate_resolver
        from pflow.execution.result import RunnerConfig
        from pflow.execution.runner import WorkflowRunner

        # Validate parameters at system boundary (security check stays in MCP)
        validated_params: dict[str, Any] = {}
        if parameters:
            is_valid, error = validate_execution_parameters(parameters)
            if not is_valid:
                raise ValueError(f"Invalid parameters: {error}")
            validated_params = dict(parameters)

        # Pre-resolve to get source/file_path for metadata
        try:
            resolved = _unified_resolve(workflow)
        except WorkflowNotFoundError as e:
            hint = str(e)
            if e.similar_names:
                hint += f"\nDid you mean: {', '.join(e.similar_names[:5])}"
            raise ValueError(hint) from e
        except Exception as e:
            raise ValueError(str(e)) from e

        workflow_name = str(workflow) if resolved.source == "library" else None
        wm = WorkflowManager()

        # Pass the full ResolvedWorkflow so the Runner's `_resolve` short-circuits
        # (no double-resolution). `_prepare_workflow` then injects
        # `_pflow_workflow_file` into params via `setdefault` against
        # `resolved.file_path` — no need to pre-inject here.
        runner = WorkflowRunner()
        result = runner.run(
            resolved,
            validated_params,
            # Task 171: MCP streams traces like the CLI — a durable gate pause
            # needs the trace ON DISK (the trace IS the checkpoint; the token
            # resolves against it). The runner opens the stream and finalizes it
            # (finalize_trace=True default) — MCP does no post-run trace
            # mutation, so each call gets a complete closed file. Concurrency is
            # safe: per-call collector + microsecond filename. The registry
            # single-node probe below stays traceless.
            RunnerConfig(),
            # MCP is the production non-TTY surface: output_controller=None means the
            # resolver honors auto_approve pre-approvals and otherwise raises the
            # payload-carrying GateNotInteractiveError (never hangs, never silently
            # approves). Same builder as the CLI — one resolver, every surface.
            gate_resolver=build_gate_resolver(frozenset(auto_approve or ()), None),
            workflow_manager=wm,
            workflow_name=workflow_name,
            input_sources=_from_the_call(validated_params),
        )

        try:
            from pflow.core.workflow.status import WorkflowStatus
            from pflow.execution.formatters.run_outcome import build_run_outcome, render_mcp_text

            outcome = build_run_outcome(
                result, resolved.ir, workflow_metadata=_workflow_metadata(resolved, str(workflow))
            )
            text = render_mcp_text(outcome)
            # A durable pause is not an error: it returns the token + gate (the builder already
            # turned a pause whose trailer never reached disk into a failure). Failure stays a
            # raise — the server boundary renders it.
            if outcome.status in (WorkflowStatus.SUCCESS, WorkflowStatus.DEGRADED, WorkflowStatus.PAUSED):
                return text
            raise RuntimeError(text)
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}", exc_info=True)
            raise RuntimeError(f"❌ Workflow execution failed: {e}") from e

    @classmethod
    @ensure_stateless
    def validate_workflow(cls, workflow: Any) -> str:
        """Validate workflow structure without execution.

        Args:
            workflow: Workflow name, path, or IR dict

        Returns:
            Formatted text with validation results (same as CLI output)
        """
        from pflow.execution.runner import WorkflowRunner

        runner = WorkflowRunner()
        vresult = runner.validate(workflow, {})

        if vresult.valid:
            from pflow.execution.formatters.validation_formatter import format_validation_success

            msg = format_validation_success()
            surfaced_diagnostics = _mcp_surfaced_diagnostics(vresult.diagnostics)
            if surfaced_diagnostics:
                msg += "\n\n" + _format_mcp_diagnostic_sections(surfaced_diagnostics)
            return msg
        else:
            from pflow.execution.formatters.validation_formatter import format_validation_failure

            msg = format_validation_failure(vresult.errors)
            surfaced_diagnostics = _mcp_surfaced_diagnostics(vresult.diagnostics)
            if surfaced_diagnostics:
                msg += "\n\n" + _format_mcp_diagnostic_sections(surfaced_diagnostics)
            return msg

    @classmethod
    @ensure_stateless
    def plan_workflow(
        cls,
        workflow: Any,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build workflow execution plan without invoking side effects."""
        from pflow.execution.formatters.plan_formatter import format_plan_json
        from pflow.execution.result import RunnerConfig
        from pflow.execution.runner import WorkflowRunner

        validated_params: dict[str, Any] = {}
        if parameters:
            is_valid, error = validate_execution_parameters(parameters)
            if not is_valid:
                raise ValueError(f"Invalid parameters: {error}")
            validated_params = dict(parameters)

        try:
            resolved = _unified_resolve(workflow)
        except WorkflowNotFoundError as e:
            hint = str(e)
            if e.similar_names:
                hint += f"\nDid you mean: {', '.join(e.similar_names[:5])}"
            raise ValueError(hint) from e
        except Exception as e:
            raise ValueError(str(e)) from e

        # Runner's `_prepare_workflow` injects `_pflow_workflow_file` via
        # `setdefault` against `resolved.file_path` — no pre-injection needed.
        runner = WorkflowRunner()
        try:
            plan = runner.plan(
                resolved, validated_params, RunnerConfig(), input_sources=_from_the_call(validated_params)
            )
        except WorkflowValidationError as e:
            # Preserve structured validation diagnostics (titles, paths,
            # suggestions, similar_names) so the agent sees the rich error
            # instead of a flattened `str(e)`. Matches save_workflow's pattern.
            from pflow.execution.formatters.validation_formatter import format_validation_failure

            rendered = (
                format_validation_failure(e.validation_errors) if e.validation_errors else f"Invalid workflow: {e}"
            )
            raise ValueError(rendered) from e
        except (CompilationError, MarkdownParseError) as e:
            # PflowError subclasses with `to_diagnostics()` — render via the
            # shared pipeline so per-error `suggestion`/`path` survive.
            from pflow.core.diagnostic import exception_to_diagnostics

            rendered = "\n\n".join(format_diagnostic(d) for d in exception_to_diagnostics(e))
            raise ValueError(f"Workflow planning failed:\n\n{rendered}") from e
        except Exception as e:
            logger.error("Workflow planning failed: %s", e, exc_info=True)
            raise RuntimeError(f"❌ Workflow planning failed: {e}") from e

        return format_plan_json(plan)

    @classmethod
    @ensure_stateless
    def analyze_cache(
        cls,
        workflow: Any,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Analyze a workflow's prompt cache plan; return the JSON shape that mirrors
        ``pflow analyze-cache --format=json`` byte-for-byte.

        Per Task 152 MCP-parity invariant: every shared formatter has two call
        sites (CLI + MCP); ``render_json(analyze(...))`` is that single
        formatter and is reused by both surfaces.

        Per DD#36, cache-analysis findings are advisory: ERROR-severity
        diagnostics surface in the result's ``warnings[]`` array but do NOT
        raise exceptions from this method. Exceptions are reserved for parse /
        validation failures that prevent IR construction (the same shape the
        runner would surface), and for trace-load failures.

        Args:
            workflow: Workflow file path / saved name / raw IR dict.
            parameters: Optional input parameters (per DD#35 — analysis falls
                back gracefully when input substitution can't fully resolve a
                prompt).

        Returns:
            JSON dict with the same schema as ``pflow analyze-cache
            --format=json``.

        Raises:
            ValueError: workflow path unparseable, validation prevents IR
                construction, or ``--from-trace`` analog (a trace path
                provided via parameters) cannot be loaded. Pre-rendered
                rich text matching the CLI surface.
        """
        from pflow.core.prompt_cache_analysis import analyze, render_json

        validated_params: dict[str, Any] = {}
        if parameters:
            is_valid, error = validate_execution_parameters(parameters)
            if not is_valid:
                raise ValueError(f"Invalid parameters: {error}")
            validated_params = dict(parameters)

        try:
            resolved = _unified_resolve(workflow)
        except WorkflowNotFoundError as e:
            hint = str(e)
            if e.similar_names:
                hint += f"\nDid you mean: {', '.join(e.similar_names[:5])}"
            raise ValueError(hint) from e
        except (CompilationError, MarkdownParseError) as e:
            from pflow.core.diagnostic import exception_to_diagnostics

            rendered = "\n\n".join(format_diagnostic(d) for d in exception_to_diagnostics(e))
            raise ValueError(f"Workflow analysis failed:\n\n{rendered}") from e
        except Exception as e:
            raise ValueError(str(e)) from e

        base_path = Path(resolved.file_path).parent if resolved.file_path else None
        # Inline (dict) workflows pass ``None``; ``analyze()`` derives the
        # canonical ``ir-hash:<md5>`` identifier internally so autoload + memo
        # + cross-workflow lookups correlate with what the trace writer / memo
        # cache used at run time. The displayed ``"<inline>"`` label is
        # produced separately inside ``analyze()`` for the rendered output.
        workflow_path_str = resolved.file_path

        try:
            analysis = analyze(
                resolved.ir,
                parameters=validated_params,
                input_sources=_from_the_call(validated_params),
                workflow_path=workflow_path_str,
                base_path=base_path,
            )
        except (FileNotFoundError, ValueError) as e:
            raise ValueError(str(e)) from e
        except PflowError:
            raise  # a supplied value that fails its declaration: the server renders its diagnostics
        except Exception as e:
            logger.error("Cache analysis failed: %s", e, exc_info=True)
            raise RuntimeError(f"❌ Cache analysis failed: {e}") from e

        return render_json(analysis)

    @classmethod
    @ensure_stateless
    def save_workflow(cls, workflow: str, name: str, force: bool = False) -> str:
        """Save workflow to global library.

        Accepts raw .pflow.md content or a file path. Does NOT use
        resolve_workflow() — save needs to preserve the original markdown
        content for storage (not just the parsed IR).

        Args:
            workflow: Raw markdown content (string with newlines) or path to .pflow.md file
            name: Workflow name (lowercase-with-hyphens)
            force: If True, overwrite existing workflow

        Returns:
            Formatted success message (text) matching CLI output

        Raises:
            ValueError: If workflow name is invalid, content is invalid, or validation fails
            FileExistsError: If workflow exists and force=False
        """
        from pflow.core.workflow.save_service import (
            validate_workflow_name,
        )

        # Validate workflow name
        is_valid, error = validate_workflow_name(name)
        if not is_valid:
            raise ValueError(f"Invalid workflow name: {error}")

        # Determine markdown content from input
        source_path: Path | None = None
        if "\n" in workflow:
            # Raw markdown content
            markdown_content = workflow
        elif workflow.lower().endswith(".pflow.md") or Path(workflow).expanduser().exists():
            # File path — read content
            file_path = Path(workflow).expanduser()
            if not file_path.exists():
                raise ValueError(f"Workflow file not found: {workflow}")
            markdown_content = file_path.read_text(encoding="utf-8")
            source_path = file_path
        else:
            raise ValueError(f"Cannot save '{workflow}'. Pass raw .pflow.md content or a file path.")

        try:
            return cls._save_and_format_result(name, markdown_content, force, source_path)
        except FileExistsError:
            raise
        except WorkflowValidationError as e:
            from pflow.execution.formatters.validation_formatter import format_validation_failure

            rendered = (
                format_validation_failure(e.validation_errors) if e.validation_errors else f"Invalid workflow: {e}"
            )
            raise ValueError(rendered) from e
        except MarkdownParseError as e:
            raise ValueError(f"Invalid workflow: {e}") from e

    @classmethod
    def _save_and_format_result(
        cls,
        name: str,
        markdown_content: str,
        force: bool,
        source_path: Path | None = None,
    ) -> str:
        """Save workflow and format success message.

        Args:
            name: Workflow name
            markdown_content: Original markdown content (preserved for save)
            force: Whether to overwrite existing workflow
            source_path: Optional source file path for dependency discovery

        Returns:
            Formatted success message

        Raises:
            FileExistsError: If workflow exists and force=False
            ValueError: If save fails
        """
        from pflow.core.workflow.save_service import save_workflow_with_options
        from pflow.execution.formatters.workflow_save_formatter import format_save_success

        try:
            saved_path, bundled_files, workflow_ir = save_workflow_with_options(
                name=name,
                markdown_content=markdown_content,
                force=force,
                source_path=source_path,
            )

            success_message = format_save_success(
                name=name,
                saved_path=str(saved_path),
                workflow_ir=workflow_ir,
                metadata=None,
                bundled_files=bundled_files,
            )

            return success_message

        except WorkflowExistsError as e:
            # A pre-formatted FileExistsError passes through the MCP error boundary verbatim.
            raise FileExistsError(f"{e} Pass force: true to overwrite, or choose a different name.") from e
        except (WorkflowValidationError, MarkdownParseError):
            raise
        except Exception as e:
            logger.error(f"Failed to save workflow: {e}", exc_info=True)
            raise ValueError(f"Failed to save workflow: {e}") from e

    @classmethod
    @ensure_stateless
    def run_registry_node(cls, node_type: str, parameters: dict[str, Any] | None = None) -> str:
        """Probe one node (``execution/probe.py::probe_node``, shared with ``pflow probe``).

        Returns:
            The node's output structure, or its failure text
        """
        from pflow.execution.probe import probe_node

        if parameters:
            # MCP's boundary check: JSON-serialisable and under the size limit.
            is_valid, error = validate_execution_parameters(parameters)
            if not is_valid:
                return f"❌ Invalid parameters: {error}"

        try:
            probe = probe_node(node_type, dict(parameters or {}))
            if not probe.success:
                from pflow.execution.formatters.run_outcome import format_error_text

                return format_error_text(probe.errors, _mcp_surfaced_diagnostics(probe.warnings))

            from pflow.core.settings import SettingsManager
            from pflow.execution.formatters.node_output_formatter import format_structure_output

            return format_structure_output(
                probe.node_type,
                probe.outputs,
                probe.outputs,
                Registry(),
                probe.execution_time_ms,
                verbose=True,
                execution_id=probe.execution_id,
                output_mode=SettingsManager().load().registry.output_mode,
            )
        except Exception as e:
            logger.error(f"Failed to run node {node_type}: {e}", exc_info=True)
            return "\n".join(format_diagnostic(d) for d in exception_to_diagnostics(e))
