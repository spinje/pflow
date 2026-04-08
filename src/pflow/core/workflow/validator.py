"""Unified workflow validation system.

This module provides the single source of truth for all workflow validation,
ensuring consistency between production, tests, and any other consumers.
"""

import logging
from pathlib import Path
from typing import Any, Optional

from pflow.core.diagnostic import Diagnostic, Severity, format_child_provenance
from pflow.core.exceptions import SchemaValidationError
from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver

logger = logging.getLogger(__name__)


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
    from dataclasses import replace

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
        2. Stdin input validation - Only one stdin: true allowed
        3. Data flow validation - Execution order and dependencies
        4. Template validation - Variable resolution
        5. Node type validation - Registry verification
        6. Output source validation - Output node references
        7. Unknown param errors - Rejects params not in node interface
        8. Sub-workflow validation - Recursive validation of child workflows
        9. Cache lint - Warn about input-less shell nodes without cache: false

        Args:
            workflow_ir: Workflow to validate
            extracted_params: Parameters extracted from user input
            registry: Node registry (uses default if None)
            skip_node_types: Skip node type validation (for mock nodes in tests)
            workflow_file: Path to the workflow file being validated. Used to
                resolve relative sub-workflow file references in step 8. When
                None and a relative path is encountered, a validation error
                is produced (relative paths are also unresolvable at runtime).

        Returns:
            Validation diagnostics. Severity distinguishes errors from warnings.
        """
        diagnostics: list[Diagnostic] = []

        # 1. Structural validation (ALWAYS run)
        diagnostics.extend(WorkflowValidator._validate_structure(workflow_ir))

        # 2. Stdin input validation (ALWAYS run - only one stdin: true allowed)
        diagnostics.extend(WorkflowValidator._validate_stdin_inputs(workflow_ir))

        # 3. Data flow validation (ALWAYS run)
        diagnostics.extend(WorkflowValidator._validate_data_flow(workflow_ir))

        # 4. Template validation (if params provided)
        if extracted_params is not None:
            if registry is None:
                registry = Registry()
            diagnostics.extend(WorkflowValidator._validate_templates(workflow_ir, extracted_params, registry))

        # 5. Node type validation (if not skipped)
        if not skip_node_types:
            if registry is None:
                registry = Registry()
            diagnostics.extend(WorkflowValidator._validate_node_types(workflow_ir, registry))

        # 6. Output source validation (ALWAYS run - validate output references)
        diagnostics.extend(WorkflowValidator._validate_output_sources(workflow_ir, registry))

        # 7. Unknown param errors
        # Only run if registry available (need interface metadata for param keys)
        if registry is not None:
            diagnostics.extend(WorkflowValidator._validate_unknown_params(workflow_ir, registry))

        # 8. Sub-workflow validation (recursive)
        diagnostics.extend(
            WorkflowValidator._validate_sub_workflows(
                workflow_ir, extracted_params, registry, _seen, _ir_cache, skip_node_types, workflow_file
            )
        )

        # 9. Cache lint — warn about input-less shell nodes
        diagnostics.extend(WorkflowValidator._warn_inputless_shell_nodes(workflow_ir))

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
    def _validate_data_flow(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
        """Validate execution order and data dependencies.

        Args:
            workflow_ir: Workflow to validate

        Returns:
            Data flow validation diagnostics
        """
        from pflow.core.workflow.data_flow import validate_data_flow

        try:
            return validate_data_flow(workflow_ir)
        except Exception as e:
            return [
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    message=f"Data flow validation error: {e!s}",
                    context={"category": "validation"},
                )
            ]

    @staticmethod
    def _validate_templates(
        workflow_ir: dict[str, Any], extracted_params: dict[str, Any], registry: Registry
    ) -> list[Diagnostic]:
        """Validate template variables and parameters.

        Args:
            workflow_ir: Workflow to validate
            extracted_params: Parameters extracted from user input
            registry: Node registry

        Returns:
            Template validation diagnostics
        """
        from pflow.runtime.template_validation import validate_workflow_templates

        try:
            return validate_workflow_templates(workflow_ir, extracted_params, registry)
        except Exception as e:
            return [
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Template Error",
                    message=f"Template validation error: {e!s}",
                    context={"category": "template_error"},
                )
            ]

    @staticmethod
    def _validate_node_types(workflow_ir: dict[str, Any], registry: Registry) -> list[Diagnostic]:
        """Validate all node types exist in registry.

        Args:
            workflow_ir: Workflow to validate
            registry: Node registry

        Returns:
            Node type validation diagnostics
        """
        from pflow.core.suggestion_utils import find_similar_items

        diagnostics: list[Diagnostic] = []

        # Types handled specially by the compiler, not registered in the node registry
        compiler_special_types = {"workflow", "pflow.runtime.workflow_executor"}

        try:
            # Extract all node types from the workflow
            node_types = {node.get("type") for node in workflow_ir.get("nodes", []) if node.get("type")}

            # Filter out compiler-handled special types
            registry_types = node_types - compiler_special_types

            if registry_types:
                # Get metadata for these specific node types
                metadata = registry.get_nodes_metadata(registry_types)

                unknown_types = registry_types - set(metadata.keys())
                known_types = sorted(metadata.keys())

                for index, node in enumerate(workflow_ir.get("nodes", [])):
                    node_type = node.get("type")
                    if node_type in unknown_types:
                        similar = (
                            find_similar_items(node_type, known_types, max_results=3, method="fuzzy")
                            if known_types
                            else []
                        )
                        diagnostics.append(
                            Diagnostic(
                                severity=Severity.ERROR,
                                source="validator",
                                title="Validation Error",
                                node_id=node.get("id", "unknown"),
                                message=f"Unknown node type: '{node_type}'",
                                suggestions=[f"Did you mean '{similar[0]}'?"] if similar else None,
                                context={
                                    "category": "validation",
                                    "path": f"nodes[{index}].type",
                                    "node_type": node_type,
                                    "similar_names": similar or None,
                                },
                            )
                        )
        except Exception as e:
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    message=f"Registry validation error: {e!s}",
                    context={"category": "validation"},
                )
            )

        return diagnostics

    @staticmethod
    def _validate_output_sources(workflow_ir: dict[str, Any], registry: Optional[Registry] = None) -> list[Diagnostic]:
        """Validate that workflow outputs reference valid nodes and output keys.

        This validation ensures that output source fields (when specified) point to
        existing nodes in the workflow. The source field can use two formats:
        - "node_id" - References entire node output
        - "node_id.output_key" - References specific output key

        Template variables (${...}) are skipped as they cannot be validated statically.

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

        # Build nodes map for O(1) lookup
        nodes_map = {node["id"]: node for node in workflow_ir.get("nodes", [])}

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
                diagnostics.extend(WorkflowValidator._validate_template_in_source(output_name, source, nodes_map))
                continue

            # Parse source format: "node_id.output_key" or "node_id"
            if "." in source:
                # Split on first dot only (supports nested keys like "node.a.b.c")
                node_id, _output_key = source.split(".", 1)
            else:
                # Reference to entire node output
                node_id = source

            # Validate node exists
            if node_id not in nodes_map:
                diagnostics.append(WorkflowValidator._build_node_not_found_diagnostic(output_name, node_id, nodes_map))
                continue

            # Note: Output key validation skipped in v1
            # We don't have reliable node output metadata at validation time
            # This could be added in future versions when registry has full interface specs

        return diagnostics

    @staticmethod
    def _validate_template_in_source(output_name: str, source: str, nodes_map: dict[str, Any]) -> list[Diagnostic]:
        """Validate template variable references in output source.

        Validates that ${node.key} templates reference existing nodes.
        Provides "Did you mean?" suggestions for typos.

        Args:
            output_name: Name of output being validated
            source: Source value with template (e.g., "${node.key}")
            nodes_map: Map of node IDs to definitions

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
                # Skip if not a node reference (no dot)
                if "." not in operand:
                    continue  # Could be workflow input

                # Parse node.key
                node_id = operand.split(".", 1)[0]
                output_key = operand.split(".", 1)[1]

                # Validate node exists
                if node_id not in nodes_map:
                    diagnostics.append(
                        WorkflowValidator._build_template_node_diagnostic(
                            output_name, source, node_id, output_key, nodes_map
                        )
                    )

        return diagnostics

    @staticmethod
    def _build_node_not_found_diagnostic(
        output_name: str,
        missing_node_id: str,
        nodes_map: dict[str, Any],
    ) -> Diagnostic:
        """Build diagnostic for plain reference to non-existent node."""
        from pflow.core.suggestion_utils import find_similar_items

        available = sorted(nodes_map.keys())
        similar = find_similar_items(missing_node_id, available, max_results=3, method="fuzzy") if available else []

        return Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Validation Error",
            message=f"Output '{output_name}' references non-existent node '{missing_node_id}'.",
            suggestions=[f"Did you mean '{similar[0]}'?"] if similar else None,
            context={
                "category": "validation",
                "path": f"outputs.{output_name}.source",
                "available_fields": available,
                "available_fields_total": len(available),
                "available_fields_label": "nodes",
                "similar_names": similar or None,
            },
        )

    @staticmethod
    def _build_template_node_diagnostic(
        output_name: str,
        source: str,
        missing_node_id: str,
        output_key: str | None,
        nodes_map: dict[str, Any],
    ) -> Diagnostic:
        """Build structured diagnostic for template reference to missing node."""
        from pflow.core.suggestion_utils import find_similar_items

        available = sorted(nodes_map.keys())
        similar = find_similar_items(missing_node_id, available, max_results=3, method="fuzzy") if available else []

        suggestions: list[str] = []
        if similar:
            best = similar[0]
            corrected = f"${{{best}.{output_key}}}" if output_key else f"${{{best}}}"
            suggestions.append(f'Change "{source}" to "{corrected}"')
            for suggestion in similar[1:]:
                alternative = f"${{{suggestion}.{output_key}}}" if output_key else f"${{{suggestion}}}"
                suggestions.append(f"Or use {alternative}")

        return Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Template Error",
            message=f"Output '{output_name}' source references non-existent node '{missing_node_id}'.",
            suggestions=suggestions or None,
            context={
                "category": "template_error",
                "path": f"outputs.{output_name}.source",
                "template": source,
                "available_fields": available,
                "available_fields_total": len(available),
                "available_fields_label": "nodes",
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

        for node in workflow_ir.get("nodes", []):
            node_id = node.get("id", "unknown")
            node_type = node.get("type", "")
            params = node.get("params", {})

            if not params:
                continue

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
    # Sub-Workflow Validation (Step 8)
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
        from pflow.core.file_resolver import resolve_file_references
        from pflow.core.ir_schema import normalize_ir
        from pflow.core.validation_utils import generate_dummy_parameters

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
            params = node.get("params", {})

            # Load child workflow (file, saved name, or inline IR).
            # already_seen=True means the child was loaded before — skip recursive
            # validation (already done) but still check this node's provided inputs.
            (
                child_ir,
                child_path,
                ref_label,
                load_errors,
                already_seen,
                child_parser_warnings,
            ) = WorkflowValidator._load_child_workflow(node_id, params, seen, ir_cache, workflow_file)
            diagnostics.extend(load_errors)
            diagnostics.extend(_add_child_provenance(child_parser_warnings, node_id, ref_label))

            if child_ir is None or "nodes" not in child_ir:
                continue

            if not already_seen:
                # Normalize child IR (adds ir_version, edges) — same as CLI/save paths
                normalize_ir(child_ir)

                # Resolve file references so template validation sees variables
                # inside external files (e.g. prompt files referenced in batch items).
                # Matches the top-level pipeline: resolve → file_refs → validate.
                if child_path:
                    try:
                        resolve_file_references(child_ir, child_path.parent)
                    except (FileNotFoundError, OSError, UnicodeDecodeError) as e:
                        diagnostics.append(
                            Diagnostic(
                                severity=Severity.ERROR,
                                source="validator",
                                title="Validation Error",
                                node_id=node_id,
                                message=f"In sub-workflow '{ref_label}' (step '{node_id}'): {e}",
                                context={
                                    "category": "validation",
                                    "sub_workflow_path": ref_label,
                                    "sub_workflow_step": node_id,
                                },
                            )
                        )
                        continue

            # Static required-input check — always runs, even for already-seen children,
            # because each parent node may provide different params.
            child_inputs = child_ir.get("inputs", {})
            diagnostics.extend(WorkflowValidator._check_required_inputs(node_id, ref_label, params, child_inputs))

            # Recursive validation — skip if this child was already validated
            if not already_seen:
                dummy_params = generate_dummy_parameters(child_inputs)
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

        return diagnostics

    @staticmethod
    def _check_required_inputs(
        node_id: str,
        ref_label: str,
        parent_params: dict[str, Any],
        child_inputs: dict[str, Any],
    ) -> list[Diagnostic]:
        """Check that all required child inputs are provided by the parent node."""
        from pflow.runtime.workflow_executor import WorkflowExecutor

        diagnostics: list[Diagnostic] = []
        parent_keys = {k for k in parent_params if k not in WorkflowExecutor.RESERVED_PARAMS and not k.startswith("__")}
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
                            f"Step '{node_id}': sub-workflow '{ref_label}' requires input '{input_name}' "
                            "but it is not provided."
                        ),
                        context={
                            "category": "validation",
                            "sub_workflow_path": ref_label,
                            "sub_workflow_step": node_id,
                            "available_fields": sorted_inputs,
                            "available_fields_total": len(sorted_inputs),
                            "available_fields_label": "required inputs",
                        },
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
    ) -> tuple[Optional[dict[str, Any]], Optional[Path], str, list[Diagnostic], bool, tuple[Diagnostic, ...]]:
        """Load a child workflow from inline IR, file reference, or saved name.

        Returns:
            (child_ir, child_path, ref_label, errors, already_seen, parser_warnings)
            already_seen=True means recursive validation should be skipped.
        """
        from pflow.core.workflow.sub_workflow_resolver import resolve_sub_workflow

        # Determine the reference label for error messages
        workflow_ref = params.get("workflow")
        inline_ir = params.get("workflow_ir")
        if isinstance(inline_ir, dict):
            ref_label = "<inline>"
        elif isinstance(workflow_ref, str) and workflow_ref:
            ref_label = workflow_ref
        else:
            ref_label = ""

        # Resolve using shared resolver
        base_path = workflow_file.parent if workflow_file else None
        try:
            result = resolve_sub_workflow(params, base_path=base_path)
        except Exception as e:
            logger.debug("Failed to load sub-workflow for step '%s'", node_id, exc_info=True)
            msg = (
                f"In sub-workflow '{ref_label}' (step '{node_id}'): {e}"
                if ref_label
                else f"Step '{node_id}': failed to load sub-workflow: {e}"
            )
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
                        },
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

        # Inline IR has no cycle concerns
        if isinstance(inline_ir, dict):
            return result.ir, result.path, ref_label, [], False, result.warnings

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

    @staticmethod
    def _warn_inputless_shell_nodes(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
        """Warn when shell nodes have no template inputs and no cache: false.

        A shell node with no ${...} variables in its params produces the same
        cache key every run. If it reads external state (git branch, env vars,
        filesystem), cached results silently return stale values.

        Only warns when:
        - Node type is 'shell'
        - No template variables in any param value
        - No batch config (batch nodes get different cache keys per item)
        - No explicit cache: false already set
        """
        warnings: list[Diagnostic] = []
        for node in workflow_ir.get("nodes", []):
            if node.get("type") != "shell":
                continue
            if "cache" in node:
                continue
            if node.get("batch"):
                continue

            params = node.get("params", {})
            if not params:
                continue  # No params at all (unusual for shell, but nothing to warn about)

            # Check if any param value contains real pflow template variables.
            # Uses extract_variables() (strict regex) instead of has_templates()
            # (naive "${" substring) to avoid false positives on bash syntax
            # like ${var:-default}, ${array[@]}, and $${escaped}.
            has_pflow_templates = False
            for value in params.values():
                if isinstance(value, str) and TemplateResolver.extract_variables(value):
                    has_pflow_templates = True
                    break

            if not has_pflow_templates:
                warnings.append(
                    Diagnostic(
                        severity=Severity.WARNING,
                        source="validator",
                        node_id=node["id"],
                        message=(
                            "Shell node has no template inputs — cached results will "
                            "persist across runs. Consider '- cache: false' if this "
                            "node reads runtime state (git, env, filesystem)."
                        ),
                        suggestions=["Add '- cache: false' if this node reads runtime state (git, env, filesystem)."],
                    )
                )

        return warnings
