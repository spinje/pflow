"""Unified workflow validation system.

This module provides the single source of truth for all workflow validation,
ensuring consistency between production, tests, and any other consumers.
"""

import logging
from pathlib import Path
from typing import Any, Optional

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.exceptions import MarkdownParseError, SchemaValidationError
from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver

logger = logging.getLogger(__name__)


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
    ) -> tuple[list[str], list[Diagnostic]]:
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
            Tuple of (errors, warnings):
            - errors: List of validation errors that prevent execution
            - warnings: List of Diagnostic objects for runtime-validated templates
        """
        errors: list[str] = []
        warnings: list[Diagnostic] = []

        # 1. Structural validation (ALWAYS run)
        struct_errors = WorkflowValidator._validate_structure(workflow_ir)
        errors.extend(struct_errors)

        # 2. Stdin input validation (ALWAYS run - only one stdin: true allowed)
        stdin_errors = WorkflowValidator._validate_stdin_inputs(workflow_ir)
        errors.extend(stdin_errors)

        # 3. Data flow validation (ALWAYS run)
        flow_errors = WorkflowValidator._validate_data_flow(workflow_ir)
        errors.extend(flow_errors)

        # 4. Template validation (if params provided)
        if extracted_params is not None:
            if registry is None:
                registry = Registry()
            template_errors, template_warnings = WorkflowValidator._validate_templates(
                workflow_ir, extracted_params, registry
            )
            errors.extend(template_errors)
            warnings.extend(template_warnings)

        # 5. Node type validation (if not skipped)
        if not skip_node_types:
            if registry is None:
                registry = Registry()
            type_errors = WorkflowValidator._validate_node_types(workflow_ir, registry)
            errors.extend(type_errors)

        # 6. Output source validation (ALWAYS run - validate output references)
        output_errors, output_warnings = WorkflowValidator._validate_output_sources(workflow_ir, registry)
        errors.extend(output_errors)
        warnings.extend(output_warnings)

        # 7. Unknown param errors
        # Only run if registry available (need interface metadata for param keys)
        if registry is not None:
            unknown_param_errors = WorkflowValidator._validate_unknown_params(workflow_ir, registry)
            errors.extend(unknown_param_errors)

        # 8. Sub-workflow validation (recursive)
        sub_errors, sub_parser_warnings = WorkflowValidator._validate_sub_workflows(
            workflow_ir, extracted_params, registry, _seen, _ir_cache, skip_node_types, workflow_file
        )
        errors.extend(sub_errors)
        warnings.extend(sub_parser_warnings)

        # 9. Cache lint — warn about input-less shell nodes
        cache_warnings = WorkflowValidator._warn_inputless_shell_nodes(workflow_ir)
        warnings.extend(cache_warnings)

        if errors:
            logger.debug(f"Validation found {len(errors)} errors")
        elif warnings:
            logger.debug(f"Validation passed with {len(warnings)} runtime-validated template(s)")
        else:
            logger.debug("Validation passed")

        return (errors, warnings)

    @staticmethod
    def _validate_structure(workflow_ir: dict[str, Any]) -> list[str]:
        """Validate IR structure and schema compliance.

        Args:
            workflow_ir: Workflow to validate

        Returns:
            List of structural validation errors
        """
        from pflow.core.ir_schema import validate_ir

        try:
            validate_ir(workflow_ir)
            return []
        except SchemaValidationError as e:
            # Use str(e) to get full error including suggestions
            # ValidationError.__str__() includes path, message, and suggestions
            return [f"Structure: {e}"]
        except Exception as e:
            return [f"Structure: Unexpected error during validation: {e}"]

    @staticmethod
    def _validate_stdin_inputs(workflow_ir: dict[str, Any]) -> list[str]:
        """Validate that at most one input has stdin: true.

        Args:
            workflow_ir: Workflow to validate

        Returns:
            List of stdin validation errors
        """
        inputs = workflow_ir.get("inputs", {})
        if not inputs:
            return []

        stdin_inputs = [name for name, spec in inputs.items() if spec.get("stdin") is True]

        if len(stdin_inputs) > 1:
            return [
                f'Multiple inputs marked with "stdin": true: {", ".join(stdin_inputs)}. '
                "Only one input can receive piped stdin."
            ]

        return []

    @staticmethod
    def _validate_data_flow(workflow_ir: dict[str, Any]) -> list[str]:
        """Validate execution order and data dependencies.

        Args:
            workflow_ir: Workflow to validate

        Returns:
            List of data flow validation errors
        """
        from pflow.core.workflow.data_flow import validate_data_flow

        try:
            return validate_data_flow(workflow_ir)
        except Exception as e:
            return [f"Data flow validation error: {e!s}"]

    @staticmethod
    def _validate_templates(
        workflow_ir: dict[str, Any], extracted_params: dict[str, Any], registry: Registry
    ) -> tuple[list[str], list[Diagnostic]]:
        """Validate template variables and parameters.

        Args:
            workflow_ir: Workflow to validate
            extracted_params: Parameters extracted from user input
            registry: Node registry

        Returns:
            Tuple of (errors, warnings):
            - errors: List of template validation errors
            - warnings: List of Diagnostic objects
        """
        from pflow.runtime.template_validation import validate_workflow_templates

        try:
            errors, warnings = validate_workflow_templates(workflow_ir, extracted_params, registry)
            return (errors, warnings)
        except Exception as e:
            return ([f"Template validation error: {e!s}"], [])

    @staticmethod
    def _validate_node_types(workflow_ir: dict[str, Any], registry: Registry) -> list[str]:
        """Validate all node types exist in registry.

        Args:
            workflow_ir: Workflow to validate
            registry: Node registry

        Returns:
            List of unknown node type errors
        """
        errors = []

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

                # Check if any are unknown
                for node_type in registry_types:
                    if node_type not in metadata:
                        errors.append(f"Unknown node type: '{node_type}'")
        except Exception as e:
            errors.append(f"Registry validation error: {e!s}")

        return errors

    @staticmethod
    def _validate_output_sources(
        workflow_ir: dict[str, Any], registry: Optional[Registry] = None
    ) -> tuple[list[str], list[Diagnostic]]:
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
            Tuple of (errors, warnings):
            - errors: List of validation errors (non-existent node references)
            - warnings: List of warnings (template variables, etc.)
        """
        errors: list[str] = []
        warnings: list[Diagnostic] = []

        # Early return if no outputs defined
        outputs = workflow_ir.get("outputs", {})
        if not outputs:
            return (errors, warnings)

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
                errors.append(
                    f"Output '{output_name}' has empty source field. Use 'node_id' or 'node_id.output_key' format."
                )
                continue

            # Validate templates instead of skipping
            if "${" in source:
                template_errors = WorkflowValidator._validate_template_in_source(output_name, source, nodes_map)
                errors.extend(template_errors)
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
                error_msg = WorkflowValidator._format_node_not_found_error(output_name, node_id, nodes_map)
                errors.append(error_msg)
                continue

            # Note: Output key validation skipped in v1
            # We don't have reliable node output metadata at validation time
            # This could be added in future versions when registry has full interface specs

        return (errors, warnings)

    @staticmethod
    def _validate_template_in_source(output_name: str, source: str, nodes_map: dict[str, Any]) -> list[str]:
        """Validate template variable references in output source.

        Validates that ${node.key} templates reference existing nodes.
        Provides "Did you mean?" suggestions for typos.

        Args:
            output_name: Name of output being validated
            source: Source value with template (e.g., "${node.key}")
            nodes_map: Map of node IDs to definitions

        Returns:
            List of error messages (empty if valid)
        """
        errors = []

        # Extract template variables: ${...}
        matches = TemplateResolver.TEMPLATE_EXTRACT_PATTERN.findall(source)

        if not matches:
            # Has ${ but malformed
            errors.append(
                f"Output '{output_name}' has malformed template: '{source}'\n"
                f"Use format: ${{variable}} or ${{node.output_key}}"
            )
            return errors

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
                    error_msg = WorkflowValidator._format_template_node_error(
                        output_name, source, node_id, output_key, nodes_map
                    )
                    errors.append(error_msg)

        return errors

    @staticmethod
    def _format_node_not_found_error(output_name: str, node_id: str, nodes_map: dict[str, Any]) -> str:
        """Format error for plain reference to non-existent node."""
        available = sorted(nodes_map.keys())

        lines = [f"Output '{output_name}' references non-existent node '{node_id}'."]

        if available:
            lines.append(f"\nAvailable nodes: {', '.join(available)}")

            # Fuzzy match suggestions
            from pflow.core.suggestion_utils import find_similar_items

            similar = find_similar_items(node_id, available, max_results=3, method="fuzzy")

            if similar:
                lines.append("\nDid you mean?")
                for suggestion in similar:
                    lines.append(f"  - {suggestion}")
        else:
            lines.append("\nWorkflow has no nodes.")

        return "\n".join(lines)

    @staticmethod
    def _format_template_node_error(
        output_name: str,
        source: str,
        node_id: str,
        output_key: str | None,
        nodes_map: dict[str, Any],
    ) -> str:
        """Format enhanced error for template reference (follows template_validator pattern).

        This provides the "gold standard" error format:
        - Problem statement
        - Available options
        - Suggestions with fuzzy matching
        - Concrete fix
        """
        available = sorted(nodes_map.keys())

        # Section 1: Problem
        lines = [
            f"Output '{output_name}' source references non-existent node '{node_id}'",
            f"Template: {source}",
        ]

        # Section 2: Available nodes
        if available:
            lines.append("\nAvailable nodes in workflow:")
            for node in available[:10]:
                lines.append(f"  ✓ {node}")
            if len(available) > 10:
                lines.append(f"  ... and {len(available) - 10} more")
        else:
            lines.append("\nWorkflow has no nodes.")
            return "\n".join(lines)

        # Section 3: Suggestions (fuzzy match)
        from pflow.core.suggestion_utils import find_similar_items

        similar = find_similar_items(node_id, available, max_results=3, method="fuzzy")

        if similar:
            lines.append("\nDid you mean one of these?")
            for suggestion in similar:
                # Reconstruct template with correct node
                corrected = f"${{{suggestion}.{output_key}}}" if output_key else f"${{{suggestion}}}"
                lines.append(f"  - {corrected}")

            # Section 4: Concrete fix
            best = similar[0]
            corrected = f"${{{best}.{output_key}}}" if output_key else f"${{{best}}}"

            lines.append("\nSuggested fix:")
            lines.append(f'  Change: "{source}"')
            lines.append(f'  To:     "{corrected}"')

        return "\n".join(lines)

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
    ) -> list[str]:
        """Validate that node parameters are recognized by the node's interface.

        Compares each node's params keys against the known params from registry
        interface metadata. Unknown params produce errors since they indicate
        typos or documentation bullets accidentally parsed as params.

        Args:
            workflow_ir: Workflow to validate
            registry: Node registry for interface metadata

        Returns:
            List of error strings for unknown parameters
        """
        from pflow.core.suggestion_utils import find_similar_items

        # Framework-level params valid for any node type, independent of
        # the node's declared interface (handled by the wrapper chain)
        framework_keys = frozenset({"inputs"})

        error_list: list[str] = []

        try:
            node_types = {node.get("type") for node in workflow_ir.get("nodes", []) if node.get("type")}
            nodes_metadata = registry.get_nodes_metadata(node_types) if node_types else {}
        except Exception as e:
            logger.debug(f"Could not load registry metadata for unknown param validation: {e}")
            return error_list

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
                    valid_params = ", ".join(sorted(known_keys))
                    msg = f"Node '{node_id}' ({node_type}): unknown parameter '{param_key}'."
                    similar = find_similar_items(param_key, sorted(known_keys), max_results=2, method="fuzzy")
                    if similar:
                        suggestions = ", ".join(f"'{s}'" for s in similar)
                        msg += f" Did you mean {suggestions}?"
                    msg += f" Valid parameters: {valid_params}"
                    error_list.append(msg)

        return error_list

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
    ) -> tuple[list[str], list[Diagnostic]]:
        """Recursively validate sub-workflow references.

        For each workflow-type node, loads the child workflow and runs
        full validation on it. Catches parse errors, structural errors,
        missing required inputs, and cycles.
        """
        from pflow.core.file_resolver import resolve_file_references
        from pflow.core.ir_schema import normalize_ir
        from pflow.core.validation_utils import generate_dummy_parameters

        errors: list[str] = []
        parser_warnings: list[Diagnostic] = []
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
            errors.extend(load_errors)
            parser_warnings.extend(child_parser_warnings)

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
                        errors.append(f"In sub-workflow '{ref_label}' (step '{node_id}'): {e}")
                        continue

            # Static required-input check — always runs, even for already-seen children,
            # because each parent node may provide different params.
            child_inputs = child_ir.get("inputs", {})
            errors.extend(WorkflowValidator._check_required_inputs(node_id, ref_label, params, child_inputs))

            # Recursive validation — skip if this child was already validated
            if not already_seen:
                dummy_params = generate_dummy_parameters(child_inputs)
                if child_path:
                    dummy_params["_pflow_workflow_file"] = str(child_path)

                child_errors, _child_warnings = WorkflowValidator.validate(
                    child_ir,
                    extracted_params=dummy_params,
                    registry=registry,
                    skip_node_types=skip_node_types,
                    workflow_file=child_path,
                    _seen=seen,
                    _ir_cache=ir_cache,
                )
                for err in child_errors:
                    errors.append(f"In sub-workflow '{ref_label}' (step '{node_id}'): {err}")

        return errors, parser_warnings

    @staticmethod
    def _check_required_inputs(
        node_id: str,
        ref_label: str,
        parent_params: dict[str, Any],
        child_inputs: dict[str, Any],
    ) -> list[str]:
        """Check that all required child inputs are provided by the parent node."""
        from pflow.runtime.workflow_executor import WorkflowExecutor

        errors: list[str] = []
        parent_keys = {k for k in parent_params if k not in WorkflowExecutor.RESERVED_PARAMS and not k.startswith("__")}
        for input_name, input_spec in child_inputs.items():
            is_required = input_spec.get("required", True)
            has_default = "default" in input_spec
            if is_required and not has_default and input_name not in parent_keys:
                available = ", ".join(sorted(child_inputs.keys()))
                errors.append(
                    f"Step '{node_id}': sub-workflow '{ref_label}' requires "
                    f"input '{input_name}' but it is not provided. "
                    f"Available inputs: {available}"
                )
        return errors

    @staticmethod
    def _load_child_workflow(
        node_id: str,
        params: dict[str, Any],
        seen: set[str],
        ir_cache: dict[str, tuple[dict[str, Any], Optional[Path]]],
        workflow_file: Optional[Path] = None,
    ) -> tuple[Optional[dict[str, Any]], Optional[Path], str, list[str], bool, tuple[Diagnostic, ...]]:
        """Load a child workflow from inline IR, file reference, or saved name.

        Returns:
            (child_ir, child_path, ref_label, errors, already_seen, parser_warnings)
            already_seen=True means recursive validation should be skipped.
        """
        from pflow.core.file_resolver import is_workflow_file_reference
        from pflow.core.markdown_parser import parse_markdown
        from pflow.core.workflow.manager import WorkflowManager

        inline_ir = params.get("workflow_ir")
        workflow_ref = params.get("workflow")

        if isinstance(inline_ir, dict):
            # Inline IR is embedded, not a file/name reference — no cycle possible
            return inline_ir, None, "<inline>", [], False, ()

        if not isinstance(workflow_ref, str) or not workflow_ref:
            return None, None, "", [], False, ()

        # Template references can't be resolved statically
        if "${" in workflow_ref:
            logger.debug(
                "Skipping sub-workflow validation for step '%s': template reference '%s'", node_id, workflow_ref
            )
            return None, None, "", [], False, ()

        if is_workflow_file_reference(workflow_ref):
            return WorkflowValidator._load_child_from_file(node_id, workflow_ref, seen, ir_cache, workflow_file)

        # Saved workflow name
        seen_key = f"name:{workflow_ref}"
        if seen_key in seen:
            # Already validated — return cached IR for input check
            cached = ir_cache.get(seen_key)
            if cached:
                return cached[0], cached[1], workflow_ref, [], True, ()
            return None, None, workflow_ref, [], True, ()
        seen.add(seen_key)

        try:
            wm = WorkflowManager()
            child_ir = wm.load_ir(workflow_ref)
            child_path_value = wm.get_path(workflow_ref)
            child_path = Path(child_path_value) if isinstance(child_path_value, str) else None
            parser_warnings: tuple[Diagnostic, ...] = ()
            if child_path and child_path.exists():
                content = child_path.read_text(encoding="utf-8")
                result = parse_markdown(content)
                child_ir = result.ir
                parser_warnings = tuple(result.warnings)
            ir_cache[seen_key] = (child_ir, child_path)
            return child_ir, child_path, workflow_ref, [], False, parser_warnings
        except Exception as e:
            logger.debug("Failed to load saved workflow '%s'", workflow_ref, exc_info=True)
            return (
                None,
                None,
                workflow_ref,
                [f"In sub-workflow '{workflow_ref}' (step '{node_id}'): failed to load: {e}"],
                False,
                (),
            )

    @staticmethod
    def _load_child_from_file(
        node_id: str,
        workflow_ref: str,
        seen: set[str],
        ir_cache: dict[str, tuple[dict[str, Any], Optional[Path]]],
        workflow_file: Optional[Path] = None,
    ) -> tuple[Optional[dict[str, Any]], Optional[Path], str, list[str], bool, tuple[Diagnostic, ...]]:
        """Load a child workflow from a file reference."""
        from pflow.core.markdown_parser import parse_markdown

        path = Path(workflow_ref)
        if not path.is_absolute():
            if workflow_file is not None:
                base_dir = workflow_file.parent
                path = base_dir / path
            else:
                # Relative path with no file context will also fail at runtime
                return (
                    None,
                    None,
                    workflow_ref,
                    [
                        f"Step '{node_id}': cannot resolve relative sub-workflow "
                        f"'{workflow_ref}' -- use an absolute path or load the "
                        f"workflow from a file so relative paths can be resolved"
                    ],
                    False,
                    (),
                )
        child_path = path.resolve()

        seen_key = str(child_path)
        if seen_key in seen:
            # Already validated — return cached IR for input check
            cached = ir_cache.get(seen_key)
            if cached:
                return cached[0], cached[1], workflow_ref, [], True, ()
            return None, None, workflow_ref, [], True, ()
        seen.add(seen_key)

        try:
            if not child_path.exists():
                return (
                    None,
                    None,
                    workflow_ref,
                    [f"Step '{node_id}': sub-workflow file not found: '{workflow_ref}' (resolved to: {child_path})"],
                    False,
                    (),
                )
            content = child_path.read_text(encoding="utf-8")
            result = parse_markdown(content)
            ir_cache[seen_key] = (result.ir, child_path)
            return result.ir, child_path, workflow_ref, [], False, tuple(result.warnings)
        except MarkdownParseError as e:
            return (
                None,
                None,
                workflow_ref,
                [f"In sub-workflow '{workflow_ref}' (step '{node_id}'): {e}"],
                False,
                (),
            )
        except Exception as e:
            return (
                None,
                None,
                workflow_ref,
                [f"In sub-workflow '{workflow_ref}' (step '{node_id}'): failed to load: {e}"],
                False,
                (),
            )

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
                        suggestion=("Add '- cache: false' if this node reads runtime state (git, env, filesystem)."),
                    )
                )

        return warnings
