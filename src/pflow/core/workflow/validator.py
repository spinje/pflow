"""Unified workflow validation system.

This module provides the single source of truth for all workflow validation,
ensuring consistency between production, tests, and any other consumers.
"""

import logging
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional

from pflow.core.diagnostic import Diagnostic, Severity, deduplicate_diagnostics, format_child_provenance
from pflow.core.exceptions import SchemaValidationError, WorkflowValidationError
from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver

logger = logging.getLogger(__name__)


def _stamp_affected_workflow(
    diagnostics: list[Diagnostic],
    workflow_path: str | None,
) -> list[Diagnostic]:
    """Stamp ``context['affected_workflow']`` when a child path is known.

    The cache analyzer uses this field to scope child-workflow diagnostics.
    Existing values win so recursive validation keeps the deepest workflow
    path, matching ``_add_child_provenance``'s first-write-wins contract.
    """
    if not workflow_path:
        return diagnostics
    enriched: list[Diagnostic] = []
    for diagnostic in diagnostics:
        context = dict(diagnostic.context or {})
        current = context.get("affected_workflow")
        if not current or current == "<unknown>":
            context["affected_workflow"] = workflow_path
        enriched.append(replace(diagnostic, context=context))
    return enriched


def _add_child_provenance(
    child_diagnostics: list[Diagnostic] | tuple[Diagnostic, ...],
    step_id: str,
    ref_label: str | None = None,
) -> list[Diagnostic]:
    """Add sub-workflow provenance to child diagnostics.

    Prefixes the message with the parent step ID so that:
    - Siblings with identical diagnostics don't collapse during dedup (different node_id)
    - Display shows which step produced the diagnostic

    Uses ``format_child_provenance`` so the validation and runtime propagation
    paths produce identical diagnostics that dedup naturally.

    For nested sub-workflows (parent → child → grandchild), ``sub_workflow_step``
    and ``sub_workflow_path`` are first-write-wins: the innermost wrapping (closest
    to the error) is preserved as recursion unwinds. This keeps the structured
    provenance fields aligned with ``node_id`` and ``context['path']``, which both
    point at the deepest level.
    """
    result: list[Diagnostic] = []
    for diagnostic in child_diagnostics:
        existing_context = diagnostic.context or {}
        new_context = dict(existing_context)
        new_context.setdefault("sub_workflow_step", step_id)
        if ref_label:
            new_context.setdefault("sub_workflow_path", ref_label)
        result.append(
            replace(
                diagnostic,
                message=format_child_provenance(step_id, diagnostic.message),
                node_id=diagnostic.node_id or step_id,
                context=new_context,
            )
        )
    return result


def _mcp_sync_hint_for_unknown_node_type(node_type: str) -> tuple[str, str] | None:
    """Return (server_name, suggestion_text) when an unknown mcp-* node type
    matches a configured MCP server with zero synced tools. Returns None
    when the node type isn't MCP-shaped, doesn't parse, isn't a registered
    server, or has at least one synced tool (in which case the missing tool
    is the user's real problem — fuzzy-match suggestion is more useful).

    Wraps MCP infrastructure calls in a broad ``except Exception`` so that
    a corrupted MCP config or settings load never crashes the validator.
    """
    if not node_type.startswith("mcp-"):
        return None

    # Lazy import keeps the core/validator → runtime/ boundary clean.
    from pflow.core.exceptions import CompilationError
    from pflow.runtime.compilation.mcp_resolution import _parse_mcp_node_type

    try:
        server, _tool = _parse_mcp_node_type(node_type)
    except CompilationError:
        # Unparseable as an MCP node — not confidently MCP-shaped enough
        # to suggest a sync. Let the generic fuzzy-match path run.
        return None

    try:
        # Lazy imports — MCP infrastructure is optional.
        from pflow.mcp.manager import MCPServerManager
        from pflow.mcp.registrar import MCPRegistrar

        if server not in MCPServerManager().list_servers():
            return None
        # At least one synced tool means the user has the wrong tool name,
        # not a missing sync. Fuzzy-match suggestion is more useful.
        if MCPRegistrar().list_registered_tools(server) != []:
            return None
    except Exception:
        # MCP config corruption, settings load failure, or any other
        # infrastructure issue must NEVER crash the validator. Fall
        # back to the generic fuzzy-match path.
        return None

    return (
        server,
        f"Run 'pflow mcp sync {server}' to discover tools for the '{server}' MCP server.",
    )


class WorkflowValidator:
    """Orchestrates all workflow validation checks.

    This class provides a unified interface for all workflow validation,
    consolidating structural, template, node type, and data flow validation
    into a single source of truth.
    """

    @staticmethod
    def validate(
        workflow_ir: dict[str, Any],
        extracted_params: Optional[dict[str, Any]] = None,
        registry: Optional[Registry] = None,
        skip_node_types: bool = False,
        workflow_file: Optional[Path] = None,
        _seen: Optional[set[str]] = None,
        _ir_cache: Optional[dict[str, tuple[dict[str, Any], Optional[Path]]]] = None,
    ) -> list[Diagnostic]:
        """Run complete workflow validation.

        Performs multiple validation checks:
        1. Structural validation - IR schema compliance
           (once structural validation passes, a reserved-literal-name guard
           runs before the steps below: inputs/node IDs named true/false/null
           are rejected — they become unreachable in templates after
           literal-operand support, e.g. ${true} resolves to the boolean
           literal, not an input named "true".)
        2. Stdin input validation - Only one stdin: true allowed
        3. Stdout output validation - Only one stdout: true allowed
        4. Data flow validation - Execution order and dependencies
        5. Template validation - Variable resolution
        6. Node type validation - Registry verification
        7. Output source validation - Output node references
        8. Unknown param errors - Rejects params not in node interface
        9. Node-specific static parameter semantics - Per-node-type param checks
           (e.g. claude-code structured-output schema preflight)
        10. Sub-workflow validation - Recursive validation of child workflows

        Args:
            workflow_ir: Workflow to validate
            extracted_params: Parameters extracted from user input
            registry: Node registry (uses default if None)
            skip_node_types: Skip node type validation (for mock nodes in tests)
            workflow_file: Path to the workflow file being validated. Used to
                resolve relative sub-workflow file references in step 10. When
                None and a relative path is encountered, a validation error
                is produced (relative paths are also unresolvable at runtime).

        Returns:
            Validation diagnostics. Severity distinguishes errors from warnings.
        """
        diagnostics: list[Diagnostic] = []

        # 1. Structural validation (ALWAYS run)
        diagnostics.extend(WorkflowValidator._validate_structure(workflow_ir))

        # Short-circuit: semantic validators (steps 2-10) assume a structurally-valid IR.
        # Running them on a malformed IR would produce misleading cascades (closes #237).
        if any(d.severity == Severity.ERROR for d in diagnostics):
            return diagnostics

        # Reserved-literal-keyword guard: inputs/node IDs named true/false/null
        # become unreachable in templates after Optional A (${true} resolves to
        # the boolean literal). Reject loudly rather than fail silently.
        diagnostics.extend(WorkflowValidator._reject_reserved_literal_names(workflow_ir))

        # 2. Stdin input validation (ALWAYS run - only one stdin: true allowed)
        diagnostics.extend(WorkflowValidator._validate_stdin_inputs(workflow_ir))

        # 3. Stdout output validation (ALWAYS run - only one stdout: true allowed)
        diagnostics.extend(WorkflowValidator._validate_stdout_outputs(workflow_ir))

        # 4. Data flow validation (ALWAYS run)
        diagnostics.extend(WorkflowValidator._validate_data_flow(workflow_ir, workflow_file=workflow_file))

        # 5. Template validation (if params provided)
        if extracted_params is not None:
            if registry is None:
                registry = Registry()
            diagnostics.extend(WorkflowValidator._validate_templates(workflow_ir, extracted_params, registry))

        # 6. Node type validation (if not skipped)
        if not skip_node_types:
            if registry is None:
                registry = Registry()
            diagnostics.extend(WorkflowValidator._validate_node_types(workflow_ir, registry))

        # 7. Output source validation (ALWAYS run - validate output references)
        diagnostics.extend(WorkflowValidator._validate_output_sources(workflow_ir, registry))

        # 8. Unknown param errors
        # Only run if registry available (need interface metadata for param keys)
        if registry is not None:
            diagnostics.extend(WorkflowValidator._validate_unknown_params(workflow_ir, registry))

        # 9. Node-specific static parameter semantics
        diagnostics.extend(WorkflowValidator._validate_node_param_semantics(workflow_ir))

        # 10. Sub-workflow validation (recursive)
        diagnostics.extend(
            WorkflowValidator._validate_sub_workflows(
                workflow_ir, extracted_params, registry, _seen, _ir_cache, skip_node_types, workflow_file
            )
        )

        errors = [d for d in diagnostics if d.severity == Severity.ERROR]
        warnings = [d for d in diagnostics if d.severity == Severity.WARNING]

        if errors:
            logger.debug(f"Validation found {len(errors)} errors")
        elif warnings:
            logger.debug(f"Validation passed with {len(warnings)} runtime-validated template(s)")
        else:
            logger.debug("Validation passed")

        return diagnostics

    @staticmethod
    def _validate_structure(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
        """Validate IR structure and schema compliance.

        Args:
            workflow_ir: Workflow to validate

        Returns:
            Structural validation diagnostics
        """
        from pflow.core.ir_schema import validate_ir

        try:
            validate_ir(workflow_ir)
            return []
        except SchemaValidationError as e:
            return list(e.to_diagnostics())
        except Exception as e:
            return [
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    message=f"Unexpected error during structural validation: {e}",
                    context={"category": "validation"},
                )
            ]

    # Names that template resolution treats as JSON literals after Optional A.
    # An input or node ID with one of these names is unreachable via ${name}.
    _RESERVED_LITERAL_NAMES = ("true", "false", "null")

    @staticmethod
    def _reject_reserved_literal_names(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
        """Reject inputs/node IDs named after reserved literal keywords.

        After Optional A, ``${true}`` / ``${false}`` / ``${null}`` resolve to the
        boolean/null literal, so an input or node with one of those names can
        never be referenced. This converts a silent footgun into a loud error.
        """
        diagnostics: list[Diagnostic] = []

        def _diag(name: str, kind: str, path: str) -> Diagnostic:
            return Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="Validation Error",
                node_id=name if kind == "Node" else None,
                message=(
                    f"{kind} '{name}' uses a reserved literal keyword. Templates like "
                    f"${{{name}}} resolve to the boolean/null literal, not this {kind.lower()}."
                ),
                suggestions=[
                    f"Rename to something like '{name}_value', 'is_{name}', or '{name}_flag'.",
                ],
                context={"category": "validation", "path": path},
            )

        inputs = workflow_ir.get("inputs", {})
        if isinstance(inputs, dict):
            for input_name in inputs:
                if input_name in WorkflowValidator._RESERVED_LITERAL_NAMES:
                    diagnostics.append(_diag(input_name, "Input", f"inputs.{input_name}"))

        for node in workflow_ir.get("nodes", []):
            node_id = node.get("id")
            if node_id in WorkflowValidator._RESERVED_LITERAL_NAMES:
                diagnostics.append(_diag(node_id, "Node", f"nodes[id={node_id}]"))

        return diagnostics

    @staticmethod
    def _validate_stdin_inputs(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
        """Validate that at most one input has stdin: true.

        Args:
            workflow_ir: Workflow to validate

        Returns:
            Stdin validation diagnostics
        """
        inputs = workflow_ir.get("inputs", {})
        if not inputs:
            return []

        stdin_inputs = [name for name, spec in inputs.items() if spec.get("stdin") is True]

        if len(stdin_inputs) > 1:
            return [
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    message=(
                        f'Multiple inputs marked with "stdin": true: {", ".join(stdin_inputs)}. '
                        "Only one input can receive piped stdin."
                    ),
                    suggestions=["Mark only one workflow input with stdin: true."],
                    context={"category": "validation", "path": "inputs"},
                )
            ]

        return []

    @staticmethod
    def _validate_stdout_outputs(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
        """Validate that at most one output has stdout: true.

        Args:
            workflow_ir: Workflow to validate

        Returns:
            Stdout validation diagnostics
        """
        outputs = workflow_ir.get("outputs", {})
        if not outputs:
            return []

        stdout_outputs = [
            name for name, spec in outputs.items() if isinstance(spec, dict) and spec.get("stdout") is True
        ]

        if len(stdout_outputs) > 1:
            return [
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    message=(
                        f'Multiple outputs marked with "stdout": true: {", ".join(stdout_outputs)}. '
                        "Only one output can stream to stdout."
                    ),
                    suggestions=["Mark only one workflow output with stdout: true."],
                    context={"category": "validation", "path": "outputs"},
                )
            ]

        return []

    @staticmethod
    def _validate_data_flow(workflow_ir: dict[str, Any], workflow_file: Optional[Path] = None) -> list[Diagnostic]:
        """Validate execution order and data dependencies.

        Assumes ``workflow_ir`` has passed structural validation (step 1 short-circuits
        on schema errors). Producer bugs surface as raw exceptions to the outer
        exception boundary — CLI (``cli/commands/run.py``) and MCP (``PflowMCP``)
        both convert them to structured Diagnostics via ``exception_to_diagnostics``.

        Threads ``workflow_file`` through as a string so cache.* diagnostics that
        route through ``make_diagnostic`` carry ``affected_workflow`` for
        workflow-scope correctness when the same node id appears in parent and
        child workflows.
        """
        from pflow.core.workflow.data_flow import validate_data_flow

        return validate_data_flow(workflow_ir, workflow_path=str(workflow_file) if workflow_file else None)

    @staticmethod
    def _validate_templates(
        workflow_ir: dict[str, Any], extracted_params: dict[str, Any], registry: Registry
    ) -> list[Diagnostic]:
        """Validate template variables and parameters.

        Assumes ``workflow_ir`` has passed structural validation. See
        ``_validate_data_flow`` docstring for the producer-bug contract.
        """
        from pflow.runtime.template_validation import validate_workflow_templates

        return validate_workflow_templates(workflow_ir, extracted_params, registry)

    @staticmethod
    def _validate_node_types(workflow_ir: dict[str, Any], registry: Registry) -> list[Diagnostic]:
        """Validate all node types exist in registry.

        Assumes ``workflow_ir`` has passed structural validation. See
        ``_validate_data_flow`` docstring for the producer-bug contract.
        """
        from pflow.core.suggestion_utils import find_similar_items

        diagnostics: list[Diagnostic] = []

        # Types handled specially by the compiler, not registered in the node registry
        compiler_special_types = {"workflow", "pflow.runtime.workflow_executor"}

        node_types = {node.get("type") for node in workflow_ir.get("nodes", []) if node.get("type")}
        registry_types = node_types - compiler_special_types

        if not registry_types:
            return diagnostics

        metadata = registry.get_nodes_metadata(registry_types)
        unknown_types = registry_types - set(metadata.keys())
        known_types = sorted(metadata.keys())

        for index, node in enumerate(workflow_ir.get("nodes", [])):
            node_type = node.get("type")
            if node_type in unknown_types:
                similar = (
                    find_similar_items(node_type, known_types, max_results=3, method="fuzzy") if known_types else []
                )

                mcp_sync_hint = _mcp_sync_hint_for_unknown_node_type(node_type)

                suggestions: list[str] | None
                extra_context: dict[str, Any] = {}
                if mcp_sync_hint is not None:
                    server_name, suggestion_text = mcp_sync_hint
                    suggestions = [suggestion_text]
                    extra_context["mcp_server"] = server_name
                    extra_context["mcp_sync_required"] = True
                elif similar:
                    suggestions = [f"Did you mean '{similar[0]}'?"]
                else:
                    suggestions = None

                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        source="validator",
                        title="Validation Error",
                        node_id=node.get("id", "unknown"),
                        message=f"Unknown node type: '{node_type}'",
                        suggestions=suggestions,
                        context={
                            "category": "validation",
                            "path": f"nodes[{index}].type",
                            "node_type": node_type,
                            "similar_names": similar or None,
                            **extra_context,
                        },
                    )
                )

        return diagnostics

    @staticmethod
    def _validate_output_sources(workflow_ir: dict[str, Any], registry: Optional[Registry] = None) -> list[Diagnostic]:
        """Validate that workflow output sources reference valid roots.

        Ensures output source fields reference existing node IDs or declared
        workflow input names. Supports plain references (node.key), template
        references (${node.key}), and bracket access (${data[0]}).

        Args:
            workflow_ir: Workflow to validate
            registry: Optional registry for enhanced validation (not used in v1)

        Returns:
            Output source validation diagnostics
        """
        diagnostics: list[Diagnostic] = []

        # Early return if no outputs defined
        outputs = workflow_ir.get("outputs", {})
        if not outputs:
            return diagnostics

        # Build valid source roots: node IDs + declared input names
        node_ids = {node["id"] for node in workflow_ir.get("nodes", [])}
        valid_sources = node_ids | set((workflow_ir.get("inputs") or {}).keys())

        # Validate each output's source field
        for output_name, output_def in outputs.items():
            # Skip if output_def is not a dict (schema validation should catch this)
            if not isinstance(output_def, dict):
                continue

            source = output_def.get("source")

            # Skip if no source specified (outputs without source are valid)
            if source is None:
                continue

            # Validate source is non-empty string
            if not isinstance(source, str) or not source.strip():
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        source="validator",
                        title="Validation Error",
                        message=(
                            f"Output '{output_name}' has empty source field. Use 'node_id' or "
                            "'node_id.output_key' format."
                        ),
                        context={"category": "validation", "path": f"outputs.{output_name}.source"},
                    )
                )
                continue

            # Validate templates instead of skipping
            if "${" in source:
                diagnostics.extend(WorkflowValidator._validate_template_in_source(output_name, source, valid_sources))
                continue

            # Extract root identifier (handles both dot and bracket syntax)
            node_id = TemplateResolver.extract_root_node_id(source)

            # Validate source root exists (node or declared input)
            if node_id not in valid_sources:
                diagnostics.append(
                    WorkflowValidator._build_node_not_found_diagnostic(output_name, node_id, valid_sources)
                )
                continue

            # Note: Output key validation skipped in v1
            # We don't have reliable node output metadata at validation time
            # This could be added in future versions when registry has full interface specs

        return diagnostics

    @staticmethod
    def _validate_template_in_source(output_name: str, source: str, valid_sources: set[str]) -> list[Diagnostic]:
        """Validate template variable references in output source.

        Validates that ${root.key} templates reference valid source roots
        (node IDs or declared workflow input names).
        Provides "Did you mean?" suggestions for typos.

        Args:
            output_name: Name of output being validated
            source: Source value with template (e.g., "${node.key}")
            valid_sources: Set of valid root identifiers (node IDs + input names)

        Returns:
            Validation diagnostics (empty if valid)
        """
        diagnostics: list[Diagnostic] = []

        # Extract template variables: ${...}
        matches = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall(source)

        if not matches:
            # Has ${ but malformed
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Template Error",
                    message=f"Output '{output_name}' has malformed template: '{source}'.",
                    suggestions=["Use format: ${variable} or ${node.output_key}."],
                    context={
                        "category": "template_error",
                        "path": f"outputs.{output_name}.source",
                        "template": source,
                    },
                )
            )
            return diagnostics

        # Validate each template
        for template_var in matches:
            # Split coalesce operands and validate each one
            operands = TemplateResolver.split_coalesce_operands(template_var)
            for operand in operands:
                # Literal operands (Optional A) are values, not node/input refs.
                if TemplateResolver.is_literal_operand(operand):
                    continue
                # Parse root identifier via the canonical extractor so operands
                # like `${data[0].x}` yield node_id="data" (not "data[0]").
                # Strip a leading dot only so bracket forms like `[0].x` are
                # preserved in the rendered output_key for error messages.
                node_id = TemplateResolver.extract_root_node_id(operand)
                output_key = operand[len(node_id) :].lstrip(".")

                # Validate source root exists (node ID or declared input)
                if node_id not in valid_sources:
                    diagnostics.append(
                        WorkflowValidator._build_template_node_diagnostic(
                            output_name, source, node_id, output_key, valid_sources
                        )
                    )

        return diagnostics

    @staticmethod
    def _build_node_not_found_diagnostic(
        output_name: str,
        missing_node_id: str,
        valid_sources: set[str],
    ) -> Diagnostic:
        """Build diagnostic for plain reference to non-existent source."""
        from pflow.core.suggestion_utils import find_similar_items

        available = sorted(valid_sources)
        similar = find_similar_items(missing_node_id, available, max_results=3, method="fuzzy") if available else []

        return Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Validation Error",
            message=f"Output '{output_name}' references non-existent source '{missing_node_id}'.",
            suggestions=[f"Did you mean '{similar[0]}'?"] if similar else None,
            context={
                "category": "validation",
                "path": f"outputs.{output_name}.source",
                "available_fields": available,
                "available_fields_total": len(available),
                "available_fields_label": "sources",
                "similar_names": similar or None,
            },
        )

    @staticmethod
    def _build_template_node_diagnostic(
        output_name: str,
        source: str,
        missing_node_id: str,
        output_key: str | None,
        valid_sources: set[str],
    ) -> Diagnostic:
        """Build structured diagnostic for template reference to missing source."""
        from pflow.core.suggestion_utils import find_similar_items

        available = sorted(valid_sources)
        similar = find_similar_items(missing_node_id, available, max_results=3, method="fuzzy") if available else []

        suggestions: list[str] = []
        if similar:
            best = similar[0]
            sep = "" if output_key and output_key.startswith("[") else "."
            corrected = f"${{{best}{sep}{output_key}}}" if output_key else f"${{{best}}}"
            suggestions.append(f'Change "{source}" to "{corrected}"')
            for suggestion in similar[1:]:
                alternative = f"${{{suggestion}{sep}{output_key}}}" if output_key else f"${{{suggestion}}}"
                suggestions.append(f"Or use {alternative}")

        return Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Template Error",
            message=f"Output '{output_name}' source references non-existent source '{missing_node_id}'.",
            suggestions=suggestions or None,
            context={
                "category": "template_error",
                "path": f"outputs.{output_name}.source",
                "template": source,
                "available_fields": available,
                "available_fields_total": len(available),
                "available_fields_label": "sources",
                "similar_names": similar or None,
            },
        )

    # =========================================================================
    # Unknown Param Errors (Step 7)
    # =========================================================================

    @staticmethod
    def _extract_known_keys(interface: dict[str, Any]) -> set[str]:
        """Extract known parameter keys from a node's interface metadata."""
        known_keys: set[str] = set()
        for param in interface.get("params", []):
            if isinstance(param, dict) and param.get("key"):
                known_keys.add(param["key"])
        for inp in interface.get("inputs", []):
            if isinstance(inp, dict) and inp.get("key"):
                known_keys.add(inp["key"])
        return known_keys

    @staticmethod
    def _validate_unknown_params(
        workflow_ir: dict[str, Any],
        registry: Registry,
    ) -> list[Diagnostic]:
        """Validate that node parameters are recognized by the node's interface.

        Compares each node's params keys against the known params from registry
        interface metadata. Unknown params produce errors since they indicate
        typos or documentation bullets accidentally parsed as params.

        Args:
            workflow_ir: Workflow to validate
            registry: Node registry for interface metadata

        Returns:
            Diagnostics for unknown parameters
        """
        from pflow.core.suggestion_utils import find_similar_items

        # Framework-level params valid for any node type, independent of
        # the node's declared interface (handled by the wrapper chain)
        framework_keys = frozenset({"inputs"})

        diagnostics: list[Diagnostic] = []

        try:
            node_types = {node.get("type") for node in workflow_ir.get("nodes", []) if node.get("type")}
            nodes_metadata = registry.get_nodes_metadata(node_types) if node_types else {}
        except Exception as e:
            logger.debug(f"Could not load registry metadata for unknown param validation: {e}")
            return diagnostics

        # Workflow node type bypasses the registry (it lives in runtime/, not nodes/),
        # so it's not covered by the Interface-docstring path. It declares its
        # allowed top-level fields via the ``ALLOWED_PARAMS`` class attribute —
        # the forward-compatible shape for the planned schema-declaration refactor.
        workflow_node_types = {"workflow", "pflow.runtime.workflow_executor"}

        for node in workflow_ir.get("nodes", []):
            node_id = node.get("id", "unknown")
            node_type = node.get("type", "")
            params = node.get("params", {})

            if not params:
                continue

            if node_type in workflow_node_types:
                from pflow.runtime.workflow_executor import WorkflowExecutor

                known_keys = set(WorkflowExecutor.ALLOWED_PARAMS)
            else:
                interface = nodes_metadata.get(node_type, {}).get("interface", {})
                known_keys = WorkflowValidator._extract_known_keys(interface)

            if not known_keys:
                continue

            for param_key in params:
                if param_key not in known_keys and param_key not in framework_keys:
                    sorted_known = sorted(known_keys)
                    similar = find_similar_items(param_key, sorted_known, max_results=2, method="fuzzy")
                    diagnostics.append(
                        Diagnostic(
                            severity=Severity.ERROR,
                            source="validator",
                            title="Validation Error",
                            node_id=node_id,
                            message=f"Unknown parameter '{param_key}' on node '{node_id}' (type: {node_type}).",
                            suggestions=[f"Did you mean '{similar[0]}'?"] if similar else None,
                            context={
                                "category": "validation",
                                "path": f"nodes[id={node_id}].params.{param_key}",
                                "node_type": node_type,
                                "available_fields": sorted_known,
                                "available_fields_total": len(sorted_known),
                                "available_fields_label": "parameters",
                                "similar_names": similar or None,
                            },
                        )
                    )

        return diagnostics

    # =========================================================================
    # Node-Specific Param Semantics (Step 9)
    # =========================================================================

    @staticmethod
    def _validate_node_param_semantics(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
        """Validate node parameter combinations that are knowable statically.

        Runtime ``prep()`` remains the enforcement boundary for values that need
        actual input resolution. This validator catches literal node contracts so
        ``--validate-only`` and ``--dry-run`` agree with normal execution.
        """
        diagnostics: list[Diagnostic] = []
        # Each entry: (node_id, display_model, provider_name, candidate_forms)
        # ``provider_name`` is the canonical provider detected from the user's
        # ``model:`` string (``anthropic`` / ``openai`` / ``gemini``). It's
        # carried into the catalog check so a bare-form catalog hit can be
        # rejected when the entry's ``litellm_provider`` field names a
        # DIFFERENT canonical provider — that catches typos like
        # ``anthropic/gpt-4`` (gpt-4 is bundled as bare under openai).
        catalog_check_list: list[tuple[str, str, str, tuple[str, ...]]] = []

        for node in workflow_ir.get("nodes", []):
            params = node.get("params", {})
            if not isinstance(params, dict):
                continue
            node_id = node.get("id", "unknown")
            node_type = node.get("type")
            if node_type == "claude-code":
                diagnostics.extend(WorkflowValidator._validate_claude_code_params(node_id, params))
            elif node_type == "llm":
                llm_diags, display_model, provider_name, forms = WorkflowValidator._validate_llm_model_id_lite(
                    node_id, params
                )
                diagnostics.extend(llm_diags)
                if forms is not None and display_model is not None and provider_name is not None:
                    catalog_check_list.append((node_id, display_model, provider_name, forms))
            elif node_type == "workflow" and node.get("retry") is not None:
                diagnostics.append(WorkflowValidator._retry_on_workflow_node_advisory(node_id))

        if catalog_check_list:
            diagnostics.extend(WorkflowValidator._validate_llm_model_id_catalog(catalog_check_list))

        return diagnostics

    @staticmethod
    def _retry_on_workflow_node_advisory(node_id: str) -> Diagnostic:
        """Advisory: a ``retry:`` block on a ``workflow`` (sub-workflow) node is inert.

        ``WorkflowExecutor`` returns child failures as an action rather than
        raising, so the node-level retry loop never fires. Surface this as an
        INFO advisory (``source="validator"`` → non-degrading) so an agent that
        wrote ``retry:`` there learns it has no effect instead of hitting a
        silent no-op.
        """
        return Diagnostic(
            severity=Severity.INFO,
            source="validator",
            title="Retry on Sub-Workflow Node",
            node_id=node_id,
            message=(
                "`retry:` has no effect on a `workflow` (sub-workflow) node — a failing "
                "sub-workflow is not retried. Put `retry:` on the child workflow's own steps, "
                "or use `- on-error:` to route a failed sub-workflow elsewhere."
            ),
            suggestions=[
                "Move `retry:` onto the relevant step inside the child workflow.",
                "Or add `- on-error: <node>` to handle a failed sub-workflow.",
            ],
            context={
                "category": "node_semantics",
                "node_type": "workflow",
                "path": f"nodes[id={node_id}].retry",
            },
        )

    @staticmethod
    def _validate_claude_code_params(node_id: str, params: dict[str, Any]) -> list[Diagnostic]:
        """Validate Claude Code structured-output constraints without SDK calls.

        Predicates live in ``pflow.nodes.claude.schema_validation`` so the
        runtime path (``ClaudeCodeNode._validate_schema``) and this static
        preflight path can't drift on shape detection.
        """
        from pflow.nodes.claude.schema_validation import (
            is_legacy_python_alias_schema,
            top_level_object_violation,
        )

        output_schema = params.get("output_schema")
        if output_schema is None:
            return []

        # Templated values resolve at runtime; matches max_turns' defer-on-template
        # policy below. Without this, composition patterns like
        # ``output_schema: ${upstream.schema}`` would be hard-rejected at preflight
        # even though runtime ``_validate_schema`` handles them correctly.
        if isinstance(output_schema, str) and "${" in output_schema:
            return []

        diagnostics: list[Diagnostic] = []
        if not isinstance(output_schema, dict):
            diagnostics.append(
                WorkflowValidator._claude_code_param_error(
                    node_id=node_id,
                    message=f"output_schema must be a dict (JSON Schema), got {type(output_schema).__name__}.",
                    path=f"nodes[id={node_id}].params.output_schema",
                    suggestions=["Use a YAML `output_schema` block or remove the output_schema field."],
                )
            )
            return diagnostics

        if not output_schema:
            diagnostics.append(
                WorkflowValidator._claude_code_param_error(
                    node_id=node_id,
                    message=(
                        "output_schema is an empty dict. Did you forget to populate the schema body? "
                        'Use a real JSON Schema (e.g. {"type": "object", "properties": {...}}) '
                        "or remove the output_schema field entirely."
                    ),
                    path=f"nodes[id={node_id}].params.output_schema",
                    suggestions=["Populate the schema body or remove output_schema."],
                )
            )
            return diagnostics

        if is_legacy_python_alias_schema(output_schema):
            diagnostics.append(
                WorkflowValidator._claude_code_param_error(
                    node_id=node_id,
                    message=(
                        "output_schema appears to use the legacy Python-alias format "
                        '({"field": {"type": "str", ...}}). Use JSON Schema instead: '
                        '{"type": "object", "properties": {...}, "required": [...]}.'
                    ),
                    path=f"nodes[id={node_id}].params.output_schema",
                    suggestions=["Convert field definitions to JSON Schema under `properties`."],
                )
            )

        violation = top_level_object_violation(output_schema)
        if violation is not None:
            # The shared predicate covers non-"object" types AND combinator-only
            # schemas (oneOf/anyOf/allOf/enum without a top-level type). Both
            # classes return HTTP 400 from the Anthropic API (Phase 0 + oneOf probe).
            if violation.kind == "missing_type":
                message = (
                    "output_schema on claude-code nodes must declare top-level type: object "
                    f"({violation.cause}). Combinators like oneOf/anyOf/allOf/enum must live "
                    "inside an object wrapper."
                )
            else:
                message = f"output_schema on claude-code nodes must have top-level type: object ({violation.cause})."
            diagnostics.append(
                WorkflowValidator._claude_code_param_error(
                    node_id=node_id,
                    message=message,
                    path=f"nodes[id={node_id}].params.output_schema.type",
                    suggestions=[
                        'Wrap in an object, e.g. {"type": "object", "properties": '
                        '{"result": <your schema>}, "required": ["result"]}.'
                    ],
                )
            )

        max_turns = params.get("max_turns", 50)
        try:
            max_turns_int = int(max_turns)
        except (TypeError, ValueError):
            max_turns_int = None
        if max_turns_int is not None and max_turns_int < 2:
            diagnostics.append(
                WorkflowValidator._claude_code_param_error(
                    node_id=node_id,
                    message=f"max_turns must be >= 2 when output_schema is set (got {max_turns_int}).",
                    path=f"nodes[id={node_id}].params.max_turns",
                    suggestions=["Set max_turns to 2 or higher, or remove output_schema."],
                )
            )

        return diagnostics

    @staticmethod
    def _claude_code_param_error(
        *,
        node_id: str,
        message: str,
        path: str,
        suggestions: list[str],
    ) -> Diagnostic:
        return Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Claude Code Structured Output Validation Error",
            node_id=node_id,
            message=message,
            suggestions=suggestions,
            context={
                "category": "validation",
                "node_type": "claude-code",
                "path": path,
            },
            see_also=["claude-code"],
        )

    # =========================================================================
    # LLM Model-Id Static Validation (Step 9 — LLM branch)
    # =========================================================================

    @staticmethod
    def _strip_provider_prefix_case_preserving(model: str, provider_prefix: str) -> str:
        """Return the bare model name with the user's case preserved.

        Distinct from ``llm_providers.model_name_without_provider`` which
        lowercases the result — this validator-local helper preserves case so
        the catalog lookup mirrors what the runtime adapter would actually
        send to LiteLLM. Without case preservation, a user writing
        ``Anthropic/Claude-Sonnet-4-5`` would match a lowercase catalog entry
        at validate time but the runtime call would use mixed case and
        potentially fail.

        Matches the prefix case-insensitively (``Anthropic/`` and
        ``anthropic/`` both strip) but returns the SUFFIX with its original
        case. When the model doesn't carry the prefix, returns it unchanged.

        Defensively normalizes ``provider_prefix`` to lowercase internally,
        so the function is robust if a future caller passes a mixed-case
        prefix. The current sole caller in ``_validate_llm_model_id_lite``
        passes ``provider.provider_prefix`` from ``PROVIDERS`` (always
        lowercase), but the function shouldn't silently mismatch if the
        contract relaxes.
        """
        provider_prefix = provider_prefix.lower()
        if model.lower().startswith(provider_prefix):
            return model[len(provider_prefix) :]
        return model

    @staticmethod
    def _validate_llm_model_id_lite(
        node_id: str,
        params: dict[str, Any],
    ) -> tuple[list[Diagnostic], str | None, str | None, tuple[str, ...] | None]:
        """Per-node lite check: type, template-defer, provider prefix, key.

        Returns ``(diagnostics, display_model, provider_name, catalog_candidate_forms)``.

        - ``diagnostics``: validate-time ERROR diagnostics (wrong type or
          missing API key) for this node.
        - ``display_model``: the model identifier as the user wrote it,
          for use in subsequent diagnostic messages.
        - ``provider_name``: the canonical provider name (``"anthropic"`` /
          ``"openai"`` / ``"gemini"``) — carried into the catalog check so a
          bare-form catalog hit can be rejected when the entry belongs to a
          DIFFERENT canonical provider (closes the cross-provider FP class
          where e.g. ``anthropic/gpt-4`` would silently pass because
          ``gpt-4`` is bundled bare under openai).
        - ``catalog_candidate_forms``: a tuple of strings to try against
          ``litellm.model_cost``. The bundled catalog uses bare names for
          most providers but prefixed names for some (e.g. gemini), so we
          collect both forms and check each. All forms are case-preserving
          to mirror the runtime call shape. ``None`` when this node should
          be skipped from catalog checks.
        """
        from pflow.core.exceptions import MissingApiKeyError
        from pflow.core.llm_config import _has_provider_key
        from pflow.core.llm_providers import detect_provider, normalize_model_name

        if "model" not in params:
            return [], None, None, None  # compiler injects default; raises CompilationError if none

        model = params["model"]
        if model is None or model == "":
            return [], None, None, None  # treat as absent — compiler handles

        if not isinstance(model, str):
            diag = Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="LLM Configuration",
                node_id=node_id,
                message=(f"LLM node 'model:' must be a string identifier, got {type(model).__name__} ({model!r})."),
                suggestions=[
                    "Set `- model: <provider>/<model-name>` (e.g. `- model: anthropic/claude-sonnet-4-5`).",
                    "Run `pflow settings llm show` to see configured defaults.",
                    "Remove the `- model:` line to use the workflow default.",
                ],
                context={
                    "category": "llm_validation",
                    "path": f"nodes[id={node_id}].params.model",
                    "value": model,
                    "value_type": type(model).__name__,
                },
                see_also=["llm"],
                id="llm.model-not-string",
            )
            return [diag], None, None, None

        if TemplateResolver.has_templates(model):
            return [], None, None, None  # defer to runtime

        provider = detect_provider(model)
        if provider is None:
            return [], None, None, None  # non-canonical provider, trust user

        if not _has_provider_key(provider.name):
            exc = MissingApiKeyError(
                f"Missing API key for model '{model}'",
                model=model,
                kind="missing_key",
            )
            diag = exc.to_diagnostics()[0]
            return [WorkflowValidator._decorate_llm_validator_diag(diag, node_id)], None, None, None

        # Build candidate forms for catalog lookup. LiteLLM's bundled catalog
        # uses bare names for most providers (e.g. ``gpt-4``,
        # ``claude-sonnet-4-5``), so a user writing ``openai/gpt-4`` would
        # false-positive as Unknown Model if we only checked the prefixed form.
        # Conversely, some entries (gemini) are bundled with the prefix. We
        # accept either form, then disambiguate with the per-entry
        # ``litellm_provider`` field in ``_validate_llm_model_id_catalog`` so
        # ``anthropic/gpt-4`` (wrong provider for gpt-4) doesn't silently pass.
        # Use the case-preserving bare-strip so the lookup mirrors the
        # runtime's case behavior (matters for users who write mixed-case
        # model identifiers).
        bare = WorkflowValidator._strip_provider_prefix_case_preserving(model, provider.provider_prefix)
        # De-duplicate while preserving order so the upstream-merge benefit
        # still applies when the user-written form differs from both
        # normalized variants. ``dict.fromkeys`` is the canonical ordered-set
        # idiom on Python 3.7+ (insertion-ordered dicts).
        candidate_forms = tuple(dict.fromkeys(f for f in (model, normalize_model_name(model), bare) if f))
        return [], model, provider.name, candidate_forms

    @staticmethod
    def _catalog_form_known_for_provider(
        litellm_module: Any,
        canonical_provider_names: set[str],
        form: str,
        expected_provider: str,
    ) -> bool:
        """True iff ``form`` is in the catalog AND the entry doesn't
        explicitly name a DIFFERENT canonical provider.

        Accepting when ``litellm_provider`` is missing, non-canonical, or
        matches ``expected_provider`` keeps the lookup permissive on
        best-effort metadata (some bundled entries lack the field; others
        use non-canonical values like ``vertex_ai-language-models`` for the
        bare Gemini namespace). Only an explicit canonical mismatch rejects.
        Closes the cross-provider FP class where e.g. ``anthropic/gpt-4``
        would silently pass because ``gpt-4`` is bundled bare under openai.
        """
        entry = litellm_module.model_cost.get(form)
        if not isinstance(entry, dict):
            # Defense in depth: treat junk catalog entries as unknown rather
            # than best-effort accept. Both upstream-fetch paths in
            # ``litellm_runtime`` now filter malformed entries before
            # registration (see ``_filter_well_formed_upstream_entries``), so
            # a non-dict entry should not be reachable via normal flow.
            # Returning False here closes the residual silent-accept window
            # if a future code path bypasses the filter.
            return False
        entry_provider = entry.get("litellm_provider")
        if entry_provider == expected_provider:
            return True
        # Reject ONLY explicit canonical mismatch. Unknown / non-canonical /
        # missing values are accepted (best-effort).
        return not (isinstance(entry_provider, str) and entry_provider in canonical_provider_names)

    @staticmethod
    def _build_catalog_unreachable_info(deferred_node_ids: list[str]) -> Diagnostic:
        """Build the single INFO breadcrumb emitted when upstream fetch fails.

        Network failure means we couldn't authoritatively check the catalog.
        Rather than silently passing, we tell the user verification was
        skipped — so the agent can interpret a runtime LLM error correctly.
        """
        deferred_count = len(deferred_node_ids)
        return Diagnostic(
            severity=Severity.INFO,
            source="validator",
            title="LLM Configuration",
            message=(
                f"Could not verify {deferred_count} model identifier(s) "
                f"against the upstream catalog (network unavailable). "
                f"Validation passed for these; model names will be "
                f"checked at runtime."
            ),
            suggestions=[
                "Check your network connection if this is unexpected.",
                "The runtime will surface a precise error if the model is invalid.",
            ],
            context={
                "category": "llm_validation",
                "deferred_node_ids": deferred_node_ids,
            },
            see_also=["llm"],
            id="llm.catalog-unreachable",
        )

    @staticmethod
    def _validate_llm_model_id_catalog(
        items: list[tuple[str, str, str, tuple[str, ...]]],
    ) -> list[Diagnostic]:
        """Batch catalog check across all LLM nodes that passed lite check.

        Each item is ``(node_id, display_model, provider_name, candidate_forms)``.
        A node is considered "known" when at least one candidate form is present
        in ``litellm.model_cost`` AND the entry's ``litellm_provider`` field
        doesn't explicitly name a DIFFERENT canonical provider (see
        ``_catalog_form_known_for_provider``).

        Severity policy: catalog-miss after successful upstream merge emits
        Severity.WARNING (not ERROR). LiteLLM's ``model_cost`` is a pricing
        catalog, not a "this name is callable" registry — fine-tunes
        (``openai/ft:...``), custom endpoints, and brand-new models may be
        callable but absent from the catalog. The WARNING signals the
        condition without blocking ``--validate-only`` or save. The original
        bug fix is preserved by the lite check's ERROR-severity missing-key
        diagnostic, which still fires before any upstream node executes.

        One litellm import. At most one HTTP request per process (latched
        in ``try_load_upstream_catalog``). On network failure, emit a
        single INFO breadcrumb instead of silently passing through.
        """
        from pflow.core.litellm_runtime import import_litellm, try_load_upstream_catalog
        from pflow.core.llm_providers import PROVIDERS

        litellm = import_litellm()
        canonical_provider_names = {p.name for p in PROVIDERS}

        def _any_known(forms: tuple[str, ...], expected_provider: str) -> bool:
            return any(
                WorkflowValidator._catalog_form_known_for_provider(
                    litellm, canonical_provider_names, form, expected_provider
                )
                for form in forms
            )

        to_check = [(nid, display, prov, forms) for nid, display, prov, forms in items if not _any_known(forms, prov)]
        if not to_check:
            return []

        merge_ok = try_load_upstream_catalog()

        diagnostics: list[Diagnostic] = []
        deferred_node_ids: list[str] = []
        for node_id, display_model, provider_name, forms in to_check:
            if _any_known(forms, provider_name):
                continue
            if merge_ok:
                diagnostics.append(
                    WorkflowValidator._build_unknown_model_warning(node_id, display_model, provider_name)
                )
            else:
                deferred_node_ids.append(node_id)

        if deferred_node_ids:
            diagnostics.append(WorkflowValidator._build_catalog_unreachable_info(deferred_node_ids))

        return diagnostics

    @staticmethod
    def _build_unknown_model_warning(node_id: str, display_model: str, provider_name: str) -> Diagnostic:
        """Build the WARNING-severity diagnostic for catalog-miss models.

        Distinct from the runtime ``UnknownModelError`` ERROR diagnostic
        (which fires when LiteLLM itself rejects the call): this validator
        finding is best-effort against ``litellm.model_cost``, which is a
        pricing catalog and not authoritative for callability. The wording
        reflects that — naming legitimate uses (fine-tunes, brand-new
        models, custom endpoints) the WARNING does NOT mean to reject.
        """
        return Diagnostic(
            severity=Severity.WARNING,
            source="validator",
            title="LLM Configuration",
            node_id=node_id,
            message=(
                f"Model '{display_model}' is not in the LiteLLM catalog. This may be a fine-tune, "
                f"a brand-new release, or a custom endpoint — the runtime will confirm. If this "
                f"is a typo, the LLM call will fail at execution time."
            ),
            suggestions=[
                "If this is intentional (fine-tune, custom endpoint), the warning can be ignored.",
                f"If this is a typo, fix the '- model:' line (provider prefix '{provider_name}/').",
                "Run 'pflow settings llm show' to see your configured defaults.",
                "See https://docs.litellm.ai/docs/providers for supported models.",
            ],
            context={
                "category": "llm_validation",
                "path": f"nodes[id={node_id}].params.model",
                "model": display_model,
                "provider": provider_name,
                "reason": "not_in_catalog",
            },
            see_also=["llm"],
            id="llm.model-not-in-catalog",
        )

    @staticmethod
    def _decorate_llm_validator_diag(diag: Diagnostic, node_id: str) -> Diagnostic:
        """Adapt a runtime-shaped LLMCallError diagnostic for validate-time emission.

        Adjusts:

        - ``source``: ``"runtime"`` -> ``"validator"`` (validate-time provenance)
        - ``node_id``: attach (runtime exceptions don't know the node yet)
        - ``context.category``: ``"llm_failure"`` -> ``"llm_validation"`` (the
          model hasn't been CALLED yet; the fix lives in the workflow file)
        - ``context.path``: add for editor click-to-source navigation
        - ``context.provider_message``: strip (always None at validate time;
          the suggestion text references a "provider authentication error
          above" that doesn't apply pre-call)

        ``title`` and ``suggestions`` from the exception are preserved
        unchanged — they're more specific than category-derived alternatives,
        and the runtime suggestions remain the right next step at validate
        time.
        """
        import dataclasses

        from pflow.core.diagnostic import LLM_VALIDATION_CATEGORY

        new_context = dict(diag.context or {})
        new_context["category"] = LLM_VALIDATION_CATEGORY
        new_context["path"] = f"nodes[id={node_id}].params.model"
        new_context.pop("provider_message", None)
        return dataclasses.replace(
            diag,
            source="validator",
            node_id=node_id,
            context=new_context,
        )

    # =========================================================================
    # Sub-Workflow Validation (Step 10)
    # =========================================================================

    @staticmethod
    def _validate_sub_workflows(
        workflow_ir: dict[str, Any],
        extracted_params: Optional[dict[str, Any]],
        registry: Optional[Registry],
        _seen: Optional[set[str]],
        _ir_cache: Optional[dict[str, tuple[dict[str, Any], Optional[Path]]]] = None,
        skip_node_types: bool = False,
        workflow_file: Optional[Path] = None,
    ) -> list[Diagnostic]:
        """Recursively validate sub-workflow references.

        For each workflow-type node, loads the child workflow and runs
        full validation on it. Catches parse errors, structural errors,
        missing required inputs, and cycles.
        """

        diagnostics: list[Diagnostic] = []
        seen = _seen if _seen is not None else set()
        # Cache loaded child IRs so duplicate references can still run the input check.
        # Shared across recursion levels so a grandchild validated via one path
        # is still available for input checking when referenced from another path.
        ir_cache = _ir_cache if _ir_cache is not None else {}
        workflow_types = {"workflow", "pflow.runtime.workflow_executor"}

        for node in workflow_ir.get("nodes", []):
            if node.get("type", "") not in workflow_types:
                continue

            node_id = node.get("id", "unknown")

            # A workflow-type node makes one or more child calls. The enumerator
            # yields one call per batch item (or a single call for non-batch).
            # Every call runs the full input-contract check — a previous iteration
            # validating against child_a tells us nothing about child_b's contract.
            # Truly-identical diagnostics (same child, same bug, N items) collapse
            # at the ``deduplicate_diagnostics`` boundary below.
            for effective_params, batch_item_index, inputs_from_item in WorkflowValidator._enumerate_child_calls(node):
                call_diagnostics = WorkflowValidator._validate_one_child_call(
                    node_id=node_id,
                    effective_params=effective_params,
                    batch_item_index=batch_item_index,
                    inputs_from_item=inputs_from_item,
                    seen=seen,
                    ir_cache=ir_cache,
                    workflow_file=workflow_file,
                    registry=registry,
                    skip_node_types=skip_node_types,
                )
                diagnostics.extend(call_diagnostics)

        # Dedup here (not just at the runner) because ``save_service`` and other
        # callers invoke ``WorkflowValidator.validate()`` directly, bypassing the
        # runner's dedup step. Per-item diagnostics carry a ``batch.items[N]``
        # prefix and won't collapse; this is a safety net for truly-identical
        # diagnostics (e.g. child-side parser warnings wrapped by
        # ``_add_child_provenance`` from multiple caller sites).
        return deduplicate_diagnostics(diagnostics)

    @staticmethod
    def _validate_one_child_call(
        *,
        node_id: str,
        effective_params: dict[str, Any],
        batch_item_index: Optional[int],
        inputs_from_item: bool,
        seen: set[str],
        ir_cache: dict[str, tuple[dict[str, Any], Optional[Path]]],
        workflow_file: Optional[Path],
        registry: Optional[Registry],
        skip_node_types: bool,
    ) -> list[Diagnostic]:
        """Validate a single parent→child call: load the child, check input
        contract, recurse. Extracted from ``_validate_sub_workflows`` to keep
        the outer loop within the cyclomatic-complexity budget.
        """
        from pflow.core.ir_schema import normalize_ir
        from pflow.core.validation_utils import generate_dummy_parameters

        diagnostics: list[Diagnostic] = []

        child_ir, child_path, ref_label, load_errors, already_seen, child_parser_warnings = (
            WorkflowValidator._load_child_workflow(
                node_id, effective_params, seen, ir_cache, workflow_file, batch_item_index
            )
        )
        diagnostics.extend(load_errors)
        diagnostics.extend(_add_child_provenance(child_parser_warnings, node_id, ref_label))

        if child_ir is not None and "nodes" in child_ir:
            if not already_seen:
                normalize_ir(child_ir)
                file_ref_error = WorkflowValidator._resolve_child_file_refs(
                    child_ir, child_path, ref_label, node_id, batch_item_index
                )
                if file_ref_error is not None:
                    diagnostics.append(file_ref_error)
                    return _stamp_affected_workflow(diagnostics, str(child_path) if child_path else None)

            child_inputs = child_ir.get("inputs") or {}
            inputs_item_idx = batch_item_index if inputs_from_item else None
            diagnostics.extend(
                WorkflowValidator._check_required_inputs(
                    node_id, ref_label, effective_params, child_inputs, inputs_item_idx
                )
            )

            if not already_seen:
                dummy_params = generate_dummy_parameters(child_ir.get("inputs") or {})
                if child_path:
                    dummy_params["_pflow_workflow_file"] = str(child_path)
                child_diagnostics = WorkflowValidator.validate(
                    child_ir,
                    extracted_params=dummy_params,
                    registry=registry,
                    skip_node_types=skip_node_types,
                    workflow_file=child_path,
                    _seen=seen,
                    _ir_cache=ir_cache,
                )
                diagnostics.extend(_add_child_provenance(child_diagnostics, node_id, ref_label))

        return _stamp_affected_workflow(diagnostics, str(child_path) if child_path else None)

    @staticmethod
    def _resolve_child_file_refs(
        child_ir: dict[str, Any],
        child_path: Optional[Path],
        ref_label: str,
        node_id: str,
        batch_item_index: Optional[int],
    ) -> Optional[Diagnostic]:
        """Resolve external ``@./file.ext`` refs inside the child IR so template
        validation sees their contents. Returns an error diagnostic on failure,
        ``None`` on success (including when there's no ``child_path``).
        """
        from pflow.core.file_resolver import resolve_file_references

        if child_path is None:
            return None
        try:
            resolve_file_references(child_ir, child_path.parent)
            return None
        except (FileNotFoundError, OSError, UnicodeDecodeError) as e:
            item_context = {"batch_item_index": batch_item_index} if batch_item_index is not None else {}
            return Diagnostic(
                severity=Severity.ERROR,
                source="validator",
                title="Validation Error",
                node_id=node_id,
                message=f"In sub-workflow '{ref_label}' (step '{node_id}'): {e}",
                context={
                    "category": "validation",
                    "sub_workflow_path": ref_label,
                    "sub_workflow_step": node_id,
                    **item_context,
                },
            )

    @staticmethod
    def _enumerate_child_calls(
        node: dict[str, Any],
    ) -> Iterator[tuple[dict[str, Any], Optional[int], bool]]:
        """Yield ``(effective_params, batch_item_index, inputs_from_item)`` per
        child call this node makes.

        A workflow node conceptually makes one child call (non-batch) or N
        (one per batch item — matches the runtime loop at
        ``batch_executor._execute_batch_item``). For inline-static batches,
        per-item template bindings are resolved so downstream helpers see
        concrete ``workflow:`` paths and ``inputs:`` dicts; for template-items
        batches, non-dict batches, or missing batches, a single yield returns
        the raw params and the existing defer-to-runtime paths kick in
        unchanged.

        When ``params`` don't reference the batch alias at all (neither
        ``workflow:`` nor ``inputs:`` use ``${<alias>...}``), every iteration
        would produce an identical check. We short-circuit to a single yield
        in that case — both to avoid N-1 duplicate diagnostics (which dedup
        collapses, but with misleading ``items[0]`` provenance) and to validate
        empty inline batches ``items: []`` the same way as non-batch calls.

        ``inputs_from_item`` is ``True`` iff the raw ``params.inputs`` was a
        template string (e.g. ``${item.inputs}``). That signal tells callers
        whether an inputs-contract violation should be blamed on the specific
        item (``batch.items[N].inputs``) or on the invariant params dict
        (``params.inputs``). A literal dict whose VALUES happen to reference
        the item (``inputs: {msg: "${item.x}"}``) is NOT ``inputs_from_item`` —
        only the key set matters for the contract check, and keys in a literal
        dict are invariant regardless of what values contain.

        Mirrors the runtime binding at ``batch_executor.py:286``
        (``item_shared[alias] = item`` before per-item template resolution).
        """
        params = node.get("params", {})
        batch = node.get("batch")

        if not isinstance(batch, dict):
            yield params, None, False
            return

        items = batch.get("items")
        # ``items:`` may be a template string per IR schema ``oneOf``. When it's
        # not a list, we can't statically enumerate — yield the raw params once
        # and let the existing resolver return ``None`` for the template ref.
        if not isinstance(items, list):
            yield params, None, False
            return

        alias = batch.get("as", "item")
        if not WorkflowValidator._params_reference_alias(params, alias):
            # Params are invariant across iterations → single check suffices.
            # Also covers empty-items batches with static refs, where we'd
            # otherwise skip validation entirely.
            yield params, None, False
            return

        # Note: when ``items == []`` AND params DO reference the alias, the
        # loop below yields zero times — child validation is silently skipped.
        # This matches runtime semantics (empty batch runs nothing) but means
        # authoring errors in a never-executed child file go unreported at
        # parse time. See ``test_empty_items_list_with_alias_refs_skips_validation``
        # for the regression pin.

        raw_inputs = params.get("inputs")
        inputs_from_item = isinstance(raw_inputs, str) and "${" in raw_inputs
        for idx, item in enumerate(items):
            # Build a minimal resolution context matching the runtime shape. When
            # item is a scalar, ``${alias}`` resolves naturally; ``${alias.key}``
            # stays unresolved → ``_load_child_workflow`` defers.
            context = {alias: item}
            effective_params = TemplateResolver.resolve_nested(params, context)
            yield effective_params, idx, inputs_from_item

    @staticmethod
    def _params_reference_alias(value: Any, alias: str) -> bool:
        """Return True iff any ``${<alias>...}`` template reference appears
        anywhere within ``value`` (strings, dicts, lists). Uses the template
        extractor's own parse of variable roots rather than a substring needle
        so single-character aliases (``as: i``) don't match unrelated variables
        like ``${input.x}``.
        """
        if isinstance(value, str):
            for var in TemplateResolver.extract_variables(value):
                if TemplateResolver.extract_root_node_id(var) == alias:
                    return True
            return False
        if isinstance(value, dict):
            return any(WorkflowValidator._params_reference_alias(v, alias) for v in value.values())
        if isinstance(value, list):
            return any(WorkflowValidator._params_reference_alias(v, alias) for v in value)
        return False

    @staticmethod
    def _step_locator(node_id: str, batch_item_index: Optional[int]) -> str:
        """Return ``Step 'X' (batch.items[N])`` when ``batch_item_index`` is set,
        else ``Step 'X'``. This prefix is what makes per-item diagnostics survive
        ``Diagnostic.__hash__`` dedup (hash includes message, excludes context).
        """
        if batch_item_index is not None:
            return f"Step '{node_id}' (batch.items[{batch_item_index}])"
        return f"Step '{node_id}'"

    @staticmethod
    def _check_required_inputs(
        node_id: str,
        ref_label: str,
        parent_params: dict[str, Any],
        child_inputs: dict[str, Any],
        batch_item_index: Optional[int] = None,
    ) -> list[Diagnostic]:
        """Check the parent→child input boundary in both directions.

        * Missing required: every required child input with no default must be
          provided by the parent.
        * Undeclared extras: every key in the parent's ``inputs:`` dict must
          correspond to a declared child input (symmetric to the child-side
          "declared input never used as template variable" rule).

        ``batch_item_index`` is the 0-based index of the batch item when this
        call was produced by ``_enumerate_child_calls`` from an inline-static
        batch; diagnostic paths are rooted at ``batch.items[N].inputs`` instead
        of ``params.inputs`` so they point at the author's actual YAML location.
        """
        from pflow.core.suggestion_utils import find_similar_items

        diagnostics: list[Diagnostic] = []
        inputs_value = parent_params.get("inputs")

        inputs_path_root = (
            f"nodes[id={node_id}].batch.items[{batch_item_index}].inputs"
            if batch_item_index is not None
            else f"nodes[id={node_id}].params.inputs"
        )
        item_context = {"batch_item_index": batch_item_index} if batch_item_index is not None else {}
        # Locator prefix survives ``Diagnostic.__hash__`` dedup (hash excludes
        # ``context``), so two items with the same underlying bug against the
        # same child produce two distinct user-visible diagnostics — not one
        # misleadingly tagged to item 0. Same dedup-survival precedent as
        # ``format_child_provenance`` in ``core/diagnostic.py``.
        step_locator = WorkflowValidator._step_locator(node_id, batch_item_index)

        # Opaque template (e.g. ``inputs: '${item}'``) — keys aren't statically
        # knowable; defer to runtime ``_extract_child_inputs`` shape check.
        # Any other non-dict (literal string, list, number, bool) is a shape bug.
        if inputs_value is not None and not isinstance(inputs_value, dict):
            if isinstance(inputs_value, str) and "${" in inputs_value:
                return []
            type_name = type(inputs_value).__name__
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    node_id=node_id,
                    message=(
                        f"{step_locator}: 'inputs:' on workflow node '{ref_label}' must be a dict "
                        f"of child inputs, got {type_name}."
                    ),
                    suggestions=["Use a mapping: ``- inputs:\\n    key: value``"],
                    context={
                        "category": "validation",
                        "sub_workflow_path": ref_label,
                        "sub_workflow_step": node_id,
                        "path": inputs_path_root,
                        "actual_type": type_name,
                        **item_context,
                    },
                    see_also=["sub-workflows"],
                )
            )
            return diagnostics

        parent_keys: set[str] = set(inputs_value.keys()) if isinstance(inputs_value, dict) else set()

        # Missing-required direction.
        for input_name, input_spec in child_inputs.items():
            is_required = input_spec.get("required", True)
            has_default = "default" in input_spec
            if is_required and not has_default and input_name not in parent_keys:
                sorted_inputs = sorted(child_inputs.keys())
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        source="validator",
                        title="Validation Error",
                        node_id=node_id,
                        message=(
                            f"{step_locator}: sub-workflow '{ref_label}' requires input '{input_name}' "
                            "but it is not provided."
                        ),
                        context={
                            "category": "validation",
                            "sub_workflow_path": ref_label,
                            "sub_workflow_step": node_id,
                            # Path points at the inputs dict (the missing key is named in
                            # ``message`` and ``available_fields``). For batch items this
                            # is critical: without it an agent can't tell which of N items
                            # omitted the required input.
                            "path": inputs_path_root,
                            "available_fields": sorted_inputs,
                            "available_fields_total": len(sorted_inputs),
                            "available_fields_label": "required inputs",
                            **item_context,
                        },
                        see_also=["sub-workflows"],
                    )
                )

        # Undeclared-extras direction — closes Bug A: typos like ``lyric:`` vs
        # ``lyrics:`` are now rejected at parse time instead of silently dropped.
        declared_names = set(child_inputs.keys())
        extras = sorted(parent_keys - declared_names)
        if extras:
            sorted_declared = sorted(declared_names)
            for extra in extras:
                similar = find_similar_items(extra, sorted_declared, max_results=2, method="fuzzy")
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        source="validator",
                        title="Validation Error",
                        node_id=node_id,
                        message=(
                            f"{step_locator}: sub-workflow '{ref_label}' does not declare input "
                            f"'{extra}' (passed via inputs: dict)."
                        ),
                        suggestions=[f"Did you mean '{similar[0]}'?"] if similar else None,
                        context={
                            "category": "validation",
                            "sub_workflow_path": ref_label,
                            "sub_workflow_step": node_id,
                            "path": f"{inputs_path_root}.{extra}",
                            "available_fields": sorted_declared,
                            "available_fields_total": len(sorted_declared),
                            "available_fields_label": "declared inputs",
                            "similar_names": similar or None,
                            **item_context,
                        },
                        see_also=["sub-workflows"],
                    )
                )

        return diagnostics

    @staticmethod
    def _load_child_workflow(
        node_id: str,
        params: dict[str, Any],
        seen: set[str],
        ir_cache: dict[str, tuple[dict[str, Any], Optional[Path]]],
        workflow_file: Optional[Path] = None,
        batch_item_index: Optional[int] = None,
    ) -> tuple[Optional[dict[str, Any]], Optional[Path], str, list[Diagnostic], bool, tuple[Diagnostic, ...]]:
        """Load a child workflow from a file reference or saved name.

        ``batch_item_index`` is threaded into load-error diagnostics so per-item
        resolution failures (e.g. broken child path in ``batch.items[2]``) carry
        enough provenance for an agent to locate the offending item.

        Returns:
            (child_ir, child_path, ref_label, errors, already_seen, parser_warnings)
            already_seen=True means recursive validation should be skipped.
        """
        from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow

        # Determine the reference label for error messages
        workflow_ref = params.get("workflow")
        ref_label = workflow_ref if isinstance(workflow_ref, str) and workflow_ref else ""

        # Resolve using shared resolver
        base_path = workflow_file.parent if workflow_file else None
        try:
            result = resolve_sub_workflow(params, base_path=base_path)
        except Exception as e:
            logger.debug("Failed to load sub-workflow for step '%s'", node_id, exc_info=True)
            # Batch-item suffix in the message so per-item load failures don't
            # collapse under ``Diagnostic.__hash__`` dedup when multiple items
            # reference the same missing file.
            item_suffix = f", batch.items[{batch_item_index}]" if batch_item_index is not None else ""
            msg = (
                f"In sub-workflow '{ref_label}' (step '{node_id}'{item_suffix}): {e}"
                if ref_label
                else f"Step '{node_id}'{item_suffix}: failed to load sub-workflow: {e}"
            )
            item_context = {"batch_item_index": batch_item_index} if batch_item_index is not None else {}
            # Preserve see_also from the inner exception (e.g. MarkdownParseError
            # on a grandchild's routing error): the wrapped message still embeds
            # the inner rule-class text, so the guide pointer remains relevant.
            # The saved-name path (WorkflowManager.load_ir) wraps MarkdownParseError
            # in WorkflowValidationError — union across all validation_errors so
            # aggregate wrappers (today length 1, potentially more in the future)
            # don't silently drop pointers from errors beyond the first.
            inner_see_also = getattr(e, "see_also", None)
            if inner_see_also is None and isinstance(e, WorkflowValidationError) and e.validation_errors:
                topics = sorted({t for ve in e.validation_errors for t in (ve.see_also or [])})
                inner_see_also = topics or None
            return (
                None,
                None,
                ref_label,
                [
                    Diagnostic(
                        severity=Severity.ERROR,
                        source="validator",
                        title="Validation Error",
                        node_id=node_id,
                        message=msg,
                        context={
                            "category": "validation",
                            "sub_workflow_path": ref_label or None,
                            "sub_workflow_step": node_id,
                            **item_context,
                        },
                        see_also=inner_see_also,
                    )
                ],
                False,
                (),
            )

        # None means template ref or missing — skip silently
        if result is None:
            if isinstance(workflow_ref, str) and "${" in workflow_ref:
                logger.debug(
                    "Skipping sub-workflow validation for step '%s': template reference '%s'",
                    node_id,
                    workflow_ref,
                )
            return None, None, ref_label, [], False, ()

        # Dedup/cycle detection via seen set
        seen_key = str(result.path) if result.path else f"name:{workflow_ref}"

        if seen_key in seen:
            # Already validated — return cached IR for input check
            cached = ir_cache.get(seen_key)
            if cached:
                return cached[0], cached[1], ref_label, [], True, ()
            return None, None, ref_label, [], True, ()
        seen.add(seen_key)

        # Cache for cross-reference input checking
        ir_cache[seen_key] = (result.ir, result.path)
        return result.ir, result.path, ref_label, [], False, result.warnings
