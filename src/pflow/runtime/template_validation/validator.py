"""Template variable validation for workflow execution.

This module is the orchestrator for template validation. It runs all
validation passes in sequence and aggregates errors/warnings.

Validation passes are split by concern into separate modules:
- path_validation: Pass 5 (path existence)
- type_validation: Passes 6+7 (type matching, shell command types)
- batch_item_validation: Pass 8 (${item.field} validation)
- utils: Shared infrastructure

This module owns:
- The main entry point (validate_workflow_templates)
- Output extraction (building the node_outputs dict)
- Template extraction
- Simple passes (malformed syntax, unused inputs)
"""

import logging
import re
from typing import Any, Optional

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver
from pflow.runtime.template_validation.batch_item_validation import validate_batch_item_fields
from pflow.runtime.template_validation.path_validation import validate_template_paths
from pflow.runtime.template_validation.type_validation import (
    validate_shell_command_types,
    validate_template_types,
)
from pflow.runtime.template_validation.utils import get_node_ids

__all__ = ["extract_node_outputs", "validate_workflow_templates"]

logger = logging.getLogger(__name__)

# More permissive pattern to catch malformed templates for validation
# Supports array notation: ${node[0].field}, ${node.field[0].subfield}
# Also supports nested index templates: ${node[${__index__}].field}
# Also supports coalesce operator: ${a.field ?? b.field}
_PERM_VAR = r"[a-zA-Z_][\w-]*(?:(?:\[(?:[\d]+|\$\{[^}]+\})\])?(?:\.[\w-]*(?:\[(?:[\d]+|\$\{[^}]+\})\])?)*)?"
_PERMISSIVE_PATTERN = re.compile(rf"\$\{{({_PERM_VAR}(?:\s*\?\?\s*{_PERM_VAR})*)\}}")

# Batch output definitions matching PflowBatchNode.post() structure
BATCH_OUTPUTS: list[dict[str, str]] = [
    {"key": "results", "type": "array", "description": "Array of results in input order"},
    {"key": "count", "type": "number", "description": "Total items processed"},
    {"key": "success_count", "type": "number", "description": "Items that succeeded"},
    {"key": "error_count", "type": "number", "description": "Items that failed"},
    {"key": "errors", "type": "array", "description": "Error details (null if none)"},
    {"key": "batch_metadata", "type": "dict", "description": "Execution statistics"},
]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def validate_workflow_templates(
    workflow_ir: dict[str, Any], available_params: dict[str, Any], registry: Registry
) -> list[Diagnostic]:
    """
    Validates all template variables in a workflow.

    Uses the registry to determine which variables are written by nodes
    and validates that all template paths exist in the node outputs.
    Also validates that all declared inputs are actually used.

    Args:
        workflow_ir: The workflow IR containing nodes with template parameters
        available_params: Parameters available from workflow inputs or CLI
        registry: Registry instance with parsed node metadata

    Returns:
        Validation diagnostics. Severity distinguishes errors from warnings.
    """
    diagnostics: list[Diagnostic] = []

    # Check for malformed template syntax FIRST
    malformed_diagnostics = _validate_malformed_templates(workflow_ir)
    diagnostics.extend(malformed_diagnostics)

    # If malformed syntax found, return early with those errors
    if malformed_diagnostics:
        logger.error(
            f"Found {len(malformed_diagnostics)} malformed template(s)",
            extra={"errors": [d.message for d in malformed_diagnostics]},
        )
        return diagnostics

    # Extract all templates from workflow
    all_templates = _extract_all_templates(workflow_ir)

    if all_templates:
        logger.debug(
            f"Found {len(all_templates)} template variables to validate", extra={"templates": sorted(all_templates)}
        )
    else:
        logger.debug("No template variables found in workflow")

    # Check for unused inputs
    unused_input_diagnostics = _validate_unused_inputs(workflow_ir, all_templates)
    diagnostics.extend(unused_input_diagnostics)

    # If no templates, we can return early (after checking for unused inputs)
    if not all_templates:
        return diagnostics

    # Get full output structure from nodes
    node_outputs = extract_node_outputs(workflow_ir, registry, available_params)

    # Remove inputs keys from templates — these are resolved by the inputs-as-context
    # mechanism at runtime, not from node_outputs. Per-node scoping is handled by
    # data_flow.py validation (which gives better errors with node ID and param name).
    inputs_keys: set[str] = set()
    for node in workflow_ir.get("nodes", []):
        inputs_param = node.get("params", {}).get("inputs")
        if isinstance(inputs_param, dict):
            inputs_keys.update(inputs_param.keys())
    all_templates -= inputs_keys

    logger.debug(
        f"Extracted outputs from {len(node_outputs)} node variables", extra={"outputs": sorted(node_outputs.keys())}
    )

    # Pass 5: Validate each template path
    diagnostics.extend(validate_template_paths(all_templates, available_params, node_outputs, workflow_ir, registry))

    # Pass 6: Validate template types match parameter expectations
    diagnostics.extend(validate_template_types(workflow_ir, node_outputs, registry))

    # Pass 7: Block structured data (dict/list) in shell command parameters
    diagnostics.extend(validate_shell_command_types(workflow_ir, node_outputs))

    # Pass 8: Validate batch item field access (${item.field} against inferred structure)
    diagnostics.extend(validate_batch_item_fields(workflow_ir, node_outputs))

    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    warnings = [d for d in diagnostics if d.severity != Severity.ERROR]

    if errors:
        logger.warning(
            f"Template validation found {len(errors)} errors", extra={"error_count": len(errors), "errors": errors}
        )
    elif warnings:
        logger.info(
            f"Template validation passed with {len(warnings)} runtime-validated template(s)",
            extra={"warning_count": len(warnings)},
        )
    else:
        logger.info("Template validation passed")

    return diagnostics


# ---------------------------------------------------------------------------
# Simple passes (too small for own file)
# ---------------------------------------------------------------------------


def _validate_unused_inputs(workflow_ir: dict[str, Any], all_templates: set[str]) -> list[Diagnostic]:
    """Validate that all declared inputs are actually used.

    Args:
        workflow_ir: The workflow IR
        all_templates: Set of all template variables found

    Returns:
        Diagnostics for unused inputs
    """
    diagnostics: list[Diagnostic] = []
    declared_inputs = set(workflow_ir.get("inputs", {}).keys())

    if declared_inputs:
        enable_namespacing = workflow_ir.get("enable_namespacing", True)
        node_ids = get_node_ids(workflow_ir) if enable_namespacing else set()

        # Extract root identifier from each template using the canonical
        # helper. A bare ``.split(".")[0]`` misses bracket syntax — e.g.
        # ``${items[0].name}`` would reduce to ``"items[0]"`` and then
        # never match a declared input named ``items``, producing a false
        # "unused input" error. ``extract_root_node_id`` handles all
        # variants (bare, dotted, indexed, mixed).
        used_inputs = set()
        for var in all_templates:
            base_var = TemplateResolver.extract_root_node_id(var) or var
            # Only count as used input if it's actually a declared input
            # and not a node ID (when namespacing is enabled)
            if base_var in declared_inputs and (not enable_namespacing or base_var not in node_ids):
                used_inputs.add(base_var)

        unused_inputs = declared_inputs - used_inputs
        if unused_inputs:
            sorted_unused = sorted(unused_inputs)
            # Severity.ERROR is intentional: declared inputs are a contract with
            # callers. An unused declaration means either the declaration is wrong
            # (spurious input) or a usage is missing (bug in the workflow), and
            # both are fixes the author should make before the workflow runs.
            # The existing test suite (test_unused_input_*, test_mixed_used_and_unused_inputs)
            # asserts this as blocking-severity; demoting to WARNING would require
            # updating ~6 tests and changing the declared-input contract.
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    message=f"Declared input(s) never used as template variable: {', '.join(sorted_unused)}",
                    suggestions=["Remove unused declarations from '## Inputs' or reference them in a node parameter."],
                    context={
                        "category": "validation",
                        "path": "inputs",
                        "unused_inputs": sorted_unused,
                    },
                )
            )
            logger.warning(f"Found {len(unused_inputs)} unused inputs", extra={"unused": sorted(unused_inputs)})

    return diagnostics


def _validate_malformed_templates(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
    """Detect malformed template syntax by counting ${ vs valid template matches.

    A malformed template is one where we find ${ but it doesn't form a valid template.
    Examples: ${unclosed, ${}, ${ }

    Args:
        workflow_ir: The workflow IR

    Returns:
        Diagnostics for malformed templates
    """
    diagnostics: list[Diagnostic] = []

    for node in workflow_ir.get("nodes", []):
        node_id = node.get("id", "unknown")
        params = node.get("params", {})

        def check_value(value: Any, node_id: str, param_path: str = "") -> None:
            """Recursively check for malformed templates in any value type."""
            if isinstance(value, str) and "${" in value:
                # Count how many ${ we have
                dollar_brace_count = value.count("${")

                # Count how many valid templates we matched
                valid_matches = _PERMISSIVE_PATTERN.findall(value)

                # Account for nested templates inside brackets - they're part of
                # outer templates and shouldn't be counted separately.
                # Example: ${results[${__index__}]} has 2 '${' but is 1 logical template
                # - valid_matches = ['results[${__index__}]', '__index__'] (2 matches)
                # - nested_count = 1 (one match contains '[${')
                # - dollar_brace_count = 2
                # - len(valid_matches) + nested_count = 3 >= 2 ✓ (no error)
                nested_count = sum(f"${{{m}}}".count("[${") for m in valid_matches)

                # If mismatch (accounting for nested), we have malformed syntax
                if len(valid_matches) + nested_count < dollar_brace_count:
                    diagnostics.append(
                        Diagnostic(
                            severity=Severity.ERROR,
                            source="validator",
                            title="Template Error",
                            node_id=node_id,
                            message=(
                                f"Malformed template syntax: found {dollar_brace_count} '${{' but only "
                                f"{len(valid_matches)} valid template(s)."
                            ),
                            suggestions=["Check for missing '}' or empty templates like '${}'."],
                            context={
                                "category": "template_error",
                                "path": (
                                    f"nodes[id={node_id}].params.{param_path}"
                                    if param_path
                                    else f"nodes[id={node_id}].params"
                                ),
                                "template": value if isinstance(value, str) else None,
                            },
                        )
                    )
            elif isinstance(value, dict):
                for key, val in value.items():
                    check_value(val, node_id, f"{param_path}.{key}" if param_path else key)
            elif isinstance(value, list):
                for idx, item in enumerate(value):
                    check_value(item, node_id, f"{param_path}[{idx}]")

        for param_key, param_value in params.items():
            check_value(param_value, node_id, param_key)

    return diagnostics


# ---------------------------------------------------------------------------
# Template extraction
# ---------------------------------------------------------------------------


def _extract_all_templates(workflow_ir: dict[str, Any]) -> set[str]:  # noqa: C901
    """Extract all template variables from workflow.

    Scans all node parameters for template variables.
    Uses a more permissive pattern than TemplateResolver to catch
    malformed templates that need syntax validation.

    Args:
        workflow_ir: The workflow IR

    Returns:
        Set of all template variable names found
    """
    templates = set()

    for node in workflow_ir.get("nodes", []):
        node_id = node.get("id", "unknown")
        params = node.get("params", {})

        def extract_from_value(value: Any, node_id: str, path: str = "") -> None:
            """Recursively extract templates from any value type."""
            if isinstance(value, str) and "$" in value:
                # Use permissive pattern to catch malformed templates
                matches = _PERMISSIVE_PATTERN.findall(value)
                # Split coalesce operands so each is validated individually
                split_matches: list[str] = []
                for match in matches:
                    if "??" in match:
                        split_matches.extend(TemplateResolver.split_coalesce_operands(match))
                    else:
                        split_matches.append(match)
                templates.update(split_matches)

                if matches:
                    logger.debug(
                        f"Found templates in node '{node_id}' at path '{path}'",
                        extra={"node_id": node_id, "path": path, "templates": sorted(matches)},
                    )
            elif isinstance(value, dict):
                for key, val in value.items():
                    extract_from_value(val, node_id, f"{path}.{key}" if path else key)
            elif isinstance(value, list):
                for idx, item in enumerate(value):
                    extract_from_value(item, node_id, f"{path}[{idx}]")

        for param_key, param_value in params.items():
            extract_from_value(param_value, node_id, param_key)

        # Also extract templates from batch.items if present
        batch_config = node.get("batch")
        if batch_config:
            items_template = batch_config.get("items")
            if items_template:
                extract_from_value(items_template, node_id, "batch.items")

    return templates


# ---------------------------------------------------------------------------
# Output extraction (builds node_outputs dict used by all passes)
# ---------------------------------------------------------------------------


def extract_node_outputs(
    workflow_ir: dict[str, Any],
    registry: Registry,
    initial_params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Extract full output structures from nodes using interface metadata.

    When namespacing is enabled, outputs are registered under both:
    - The original key (for backward compatibility checks)
    - The namespaced path "node_id.output_key"

    For batch nodes, registers batch-specific outputs (results, count, etc.)
    instead of the inner node's normal outputs, and adds the item alias
    as an available variable.

    Returns:
        Dict mapping variable names to their full structure/type info
    """
    node_outputs: dict[str, dict[str, Any]] = {}
    enable_namespacing = workflow_ir.get("enable_namespacing", True)

    for node in workflow_ir.get("nodes", []):
        node_id = node.get("id")
        node_type = node.get("type")
        if not node_type or not node_id:
            continue

        # Workflow nodes: resolve child outputs for validation.
        if node_type in ("workflow", "pflow.runtime.workflow_executor"):
            _register_workflow_node_outputs(
                node_outputs,
                node,
                node_id,
                node_type,
                enable_namespacing,
                registry,
                initial_params,
            )
            continue

        # Check for batch configuration
        batch_config = node.get("batch")

        if batch_config:
            # Batch node: register batch outputs instead of normal outputs
            _register_batch_outputs(node_outputs, node_id, node_type, enable_namespacing, registry)
            _register_batch_item_variables(node_outputs, node_id, node_type, batch_config)
        else:
            # Non-batch node: extract outputs from registry interface
            _register_node_outputs_from_registry(node_outputs, node_id, node_type, enable_namespacing, registry)

    return node_outputs


def _register_workflow_node_outputs(
    node_outputs: dict[str, Any],
    node: dict[str, Any],
    node_id: str,
    node_type: str,
    enable_namespacing: bool,
    registry: Registry,
    initial_params: Optional[dict[str, Any]],
) -> None:
    """Register outputs for a workflow node, handling both batch and non-batch cases.

    Resolves the child workflow's declared outputs. When the node has batch config,
    wraps those outputs in the batch structure (results, count, etc.) instead of
    exposing them directly.
    """
    child_outputs = _resolve_child_workflow_outputs(node, initial_params)
    batch_config = node.get("batch")

    if batch_config:
        # Batch workflow: wrap child outputs in batch structure
        if child_outputs is not None:
            inner_outputs: dict[str, Any] = {}
            for output_name, output_spec in child_outputs.items():
                output_type = output_spec.get("type", "any") if isinstance(output_spec, dict) else "any"
                inner_outputs[output_name] = {"type": output_type}
            _register_batch_outputs(
                node_outputs,
                node_id,
                node_type,
                enable_namespacing,
                registry,
                inner_outputs_override=inner_outputs,
            )
        else:
            # Child unresolvable: register batch outputs without inner structure.
            # skip_results_structure=True lets the validator accept any results[N].* path
            # (falls through to permissive "array type" check).
            _register_batch_outputs(
                node_outputs,
                node_id,
                node_type,
                enable_namespacing,
                registry,
                skip_results_structure=True,
            )
        _register_batch_item_variables(node_outputs, node_id, node_type, batch_config)
    elif child_outputs is not None:
        # Non-batch workflow with resolvable outputs
        for output_name, output_spec in child_outputs.items():
            output_type = output_spec.get("type", "any") if isinstance(output_spec, dict) else "any"
            output_info = {"type": output_type, "node_id": node_id, "node_type": node_type}
            node_outputs[output_name] = output_info
            if enable_namespacing:
                node_outputs[f"{node_id}.{output_name}"] = output_info
    else:
        # Can't resolve child outputs — mark as dynamic
        node_outputs[node_id] = {
            "type": "any",
            "node_id": node_id,
            "node_type": node_type,
            "is_workflow_dynamic": True,
        }


def _register_batch_item_variables(
    node_outputs: dict[str, Any],
    node_id: str,
    node_type: str,
    batch_config: dict[str, Any],
) -> None:
    """Register the item alias and __index__ as available variables for batch nodes."""
    item_alias = batch_config.get("as", "item")
    node_outputs[item_alias] = {
        "type": "any",
        "description": f"Current batch item during iteration (from node '{node_id}')",
        "node_id": node_id,
        "node_type": node_type,
        "is_batch_item": True,
    }
    node_outputs["__index__"] = {
        "type": "int",
        "description": f"Current batch item index (0-based) during iteration (from node '{node_id}')",
        "node_id": node_id,
        "node_type": node_type,
        "is_batch_item": True,
    }


def _resolve_child_workflow_outputs(
    node: dict[str, Any],
    initial_params: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Try to resolve a workflow node's child outputs for validation.

    Returns the child's declared outputs dict if resolvable, or None if
    the child can't be loaded (dynamic reference, missing file, etc.).
    """
    params = node.get("params", {})

    # Inline workflow_ir — read outputs directly
    workflow_ir = params.get("workflow_ir")
    if isinstance(workflow_ir, dict):
        outputs = workflow_ir.get("outputs", {})
        return outputs if outputs else None

    # File or saved name reference
    workflow_ref = params.get("workflow")
    if not workflow_ref or not isinstance(workflow_ref, str):
        return None

    # Skip template references — can't resolve at validation time
    if "${" in workflow_ref:
        return None

    from pflow.core.file_resolver import is_workflow_file_reference

    if is_workflow_file_reference(workflow_ref):
        # File reference — try to load
        try:
            from pathlib import Path

            from pflow.core.markdown_parser import parse_markdown

            path = Path(workflow_ref)
            if not path.is_absolute() and initial_params:
                parent_file = initial_params.get("_pflow_workflow_file")
                base_dir = Path(parent_file).parent if parent_file else Path.cwd()
                path = base_dir / path
            path = path.resolve()
            if not path.exists():
                return None
            content = path.read_text(encoding="utf-8")
            result = parse_markdown(content)
            outputs = result.ir.get("outputs", {})
            return outputs if outputs else None
        except Exception:
            logger.debug("Could not resolve child workflow outputs for '%s'", workflow_ref, exc_info=True)
            return None
    else:
        # Saved workflow name — try to load via WorkflowManager
        try:
            from pflow.core.workflow.manager import WorkflowManager

            wm = WorkflowManager()
            child_ir = wm.load_ir(workflow_ref)
            outputs = child_ir.get("outputs", {})
            return outputs if outputs else None
        except Exception:
            logger.debug("Could not resolve child workflow outputs for '%s'", workflow_ref, exc_info=True)
            return None


def _get_inner_outputs_from_registry(node_type: str, registry: Registry) -> dict[str, Any]:
    """Look up a node type's output structure from the registry.

    Returns a dict mapping output key → {type, description, structure}.
    Returns empty dict if node type is not found.
    """
    inner_outputs: dict[str, Any] = {}
    try:
        nodes_metadata = registry.get_nodes_metadata([node_type])
        if node_type in nodes_metadata:
            interface = nodes_metadata[node_type]["interface"]
            for output in interface.get("outputs", []):
                if isinstance(output, str):
                    inner_outputs[output] = {"type": "any"}
                else:
                    key = output.get("key", "")
                    if key:
                        inner_outputs[key] = {
                            "type": output.get("type", "any"),
                            "description": output.get("description", ""),
                            "structure": output.get("structure", {}),
                        }
    except (ValueError, KeyError):
        pass
    return inner_outputs


def _register_batch_outputs(
    node_outputs: dict[str, Any],
    node_id: str,
    node_type: str,
    enable_namespacing: bool,
    registry: Registry,
    inner_outputs_override: Optional[dict[str, Any]] = None,
    skip_results_structure: bool = False,
) -> None:
    """Register batch-specific outputs for a node with batch configuration.

    Batch nodes wrap their inner node's outputs in a structured result with:
    - results: Array of per-item results (with inner node's output structure)
    - count: Total items processed
    - success_count/error_count: Success/failure counts
    - errors: Error details if any
    - batch_metadata: Execution statistics

    Args:
        inner_outputs_override: Pre-resolved inner output structure (e.g., from
            child workflow outputs). When provided, skips registry lookup.
        skip_results_structure: When True, don't attach items structure to results.
            Used when inner outputs are unknown (e.g., dynamic workflow child ref)
            so the validator accepts any results[N].* path at validation time.
    """
    if skip_results_structure:
        inner_outputs_structure: dict[str, Any] = {}
    elif inner_outputs_override is not None:
        inner_outputs_structure = inner_outputs_override
    else:
        inner_outputs_structure = _get_inner_outputs_from_registry(node_type, registry)

    for output in BATCH_OUTPUTS:
        key = output["key"]
        output_info: dict[str, Any] = {
            "type": output["type"],
            "description": output["description"],
            "node_id": node_id,
            "node_type": node_type,
            "is_batch_output": True,
        }

        # For 'results' array, add inner node's output structure plus 'item'.
        # When skip_results_structure is True, omit items so the validator
        # falls through to permissive array-type access for unknown inner outputs.
        if key == "results" and not skip_results_structure:
            # Each result always contains 'item' (original batch input)
            result_structure = {"item": {"type": "any", "description": "Original batch input"}}
            if inner_outputs_structure:
                result_structure.update(inner_outputs_structure)
            output_info["items"] = {
                "type": "dict",
                "structure": result_structure,
            }

        # Register under original key for backward compatibility
        node_outputs[key] = output_info

        # If namespacing is enabled, also register under node_id.output
        if enable_namespacing:
            namespaced_key = f"{node_id}.{key}"
            node_outputs[namespaced_key] = output_info


def _register_node_outputs_from_registry(
    node_outputs: dict[str, Any],
    node_id: str,
    node_type: str,
    enable_namespacing: bool,
    registry: Registry,
) -> None:
    """Register outputs from registry interface metadata for non-batch nodes.

    Silently skips unknown node types — the pre-execution
    ``WorkflowValidator._validate_node_types`` step (step 5) produces a rich
    ``Unknown node type`` diagnostic with ``similar_names`` and structured
    path, which is strictly more useful than anything this function could
    emit. Raising here would be caught by the defensive ``except Exception``
    wrapper around ``validate_workflow_templates`` (step 4, runs before
    step 5) and produce a duplicate generic ``"Template validation error:
    Unknown node type: ..."`` diagnostic on top of the rich one.
    """
    # Get node metadata from registry
    nodes_metadata = registry.get_nodes_metadata([node_type])
    if node_type not in nodes_metadata:
        return

    interface = nodes_metadata[node_type]["interface"]

    # Extract outputs with full structure
    for output in interface["outputs"]:
        if isinstance(output, str):
            # Simple format: just the key, no structure
            output_info = {"type": "any", "node_id": node_id, "node_type": node_type}

            # Register under original key for backward compatibility
            node_outputs[output] = output_info

            # If namespacing is enabled, also register under node_id.output
            if enable_namespacing:
                namespaced_key = f"{node_id}.{output}"
                node_outputs[namespaced_key] = output_info
        else:
            # Rich format: includes type and structure
            key = output["key"]
            output_info = {
                "type": output.get("type", "any"),
                "structure": output.get("structure", {}),
                "node_id": node_id,
                "node_type": node_type,
            }

            # Register under original key for backward compatibility
            node_outputs[key] = output_info

            # If namespacing is enabled, also register under node_id.output
            if enable_namespacing:
                namespaced_key = f"{node_id}.{key}"
                node_outputs[namespaced_key] = output_info
