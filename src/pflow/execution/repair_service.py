"""LLM-based workflow repair service for automatic error correction."""

import json
import logging
import re
from typing import Any, Optional

import llm

logger = logging.getLogger(__name__)


def repair_workflow(
    workflow_ir: dict,
    errors: list[dict[str, Any]],
    original_request: Optional[str] = None,
    shared_store: Optional[dict[str, Any]] = None,
    planner_cache_chunks: Optional[list[dict[str, Any]]] = None,
) -> tuple[bool, Optional[dict]]:
    """
    Attempt to repair a broken workflow using LLM.

    Args:
        workflow_ir: The workflow that failed
        errors: List of error dictionaries from execution
        original_request: Original user request for context
        shared_store: Execution state for additional context

    Returns:
        (success, repaired_workflow_ir or None)
    """
    if not errors:
        logger.warning("No errors provided for repair")
        return False, None

    try:
        # Analyze errors for repair context
        repair_context = _analyze_errors_for_repair(errors, shared_store)

        # Build repair prompt (no cache chunks in prompt text!)
        prompt = _build_repair_prompt(workflow_ir, errors, repair_context, original_request)

        # Test Sonnet using the exact same pattern as planner
        model = llm.get_model("anthropic/claude-sonnet-4-0")

        # Use FlowIR schema like WorkflowGeneratorNode does
        from pflow.planning.ir_models import FlowIR

        # CRITICAL: Pass cache chunks as cache_blocks parameter, not in prompt text
        cache_blocks = planner_cache_chunks if planner_cache_chunks else None

        # Generate repair with planner-compatible interface (mimicking WorkflowGeneratorNode)
        response = model.prompt(
            prompt,
            schema=FlowIR,  # Same schema as WorkflowGeneratorNode
            cache_blocks=cache_blocks,  # Pass cache chunks here for caching!
            temperature=0.0,
            thinking_budget=0,
        )

        # Parse structured response like WorkflowGeneratorNode does
        from pflow.planning.utils.llm_helpers import parse_structured_response

        result = parse_structured_response(response, FlowIR)

        # Convert to dict if it's a Pydantic model
        repaired_ir = result.model_dump() if hasattr(result, "model_dump") else result

        logger.debug(f"Structured repair result: {str(repaired_ir)[:500]}...")

        if not repaired_ir:
            logger.warning("Failed to extract valid workflow from LLM response")
            return False, None

        # Basic validation
        if not _validate_repaired_workflow(repaired_ir):
            logger.warning("Repaired workflow failed validation")
            return False, None

        logger.info("Successfully generated workflow repair")
        return True, repaired_ir

    except Exception:
        logger.exception("Repair generation failed")
        return False, None


def repair_workflow_with_validation(
    workflow_ir: dict,
    errors: list[Any],  # Can be list of strings (validation) or dicts (runtime)
    original_request: Optional[str] = None,
    shared_store: Optional[dict[str, Any]] = None,
    execution_params: Optional[dict[str, Any]] = None,
    max_attempts: int = 3,
) -> tuple[bool, Optional[dict], Optional[list[dict[str, Any]]]]:
    """
    Repair workflow with static validation loop.

    This function:
    1. Generates repair based on errors
    2. Validates the repair statically
    3. If validation fails, regenerates with validation errors
    4. Returns repaired workflow only if it passes validation

    Args:
        workflow_ir: The workflow that failed
        errors: List of errors (strings for validation, dicts for runtime)
        original_request: Original user request for context
        shared_store: Execution state for additional context
        execution_params: Parameters for template validation
        max_attempts: Maximum repair generation attempts (default: 3)

    Returns:
        Tuple of:
        - success: True if repair succeeded and validated
        - repaired_workflow_ir: The repaired and validated workflow (or None)
        - validation_errors: Any remaining validation errors (or None)
    """
    attempt = 0
    current_errors = _normalize_errors(errors)
    current_workflow = workflow_ir

    # Extract cache chunks from execution params if available
    planner_cache_chunks = _extract_planner_cache_chunks(execution_params)

    while attempt < max_attempts:
        logger.info(f"Repair attempt {attempt + 1}/{max_attempts}")

        # 1. Generate repair based on current errors
        success, repaired_ir = repair_workflow(
            workflow_ir=current_workflow,
            errors=current_errors,
            original_request=original_request,
            shared_store=shared_store,
            planner_cache_chunks=planner_cache_chunks,
        )

        if not success or not repaired_ir:
            logger.warning(f"Repair generation failed at attempt {attempt + 1}")
            return False, None, None

        # 2. Validate the repaired workflow
        validation_result = _validate_repaired_workflow_static(repaired_ir, execution_params)

        if validation_result["success"]:
            logger.info(f"Repair validated successfully at attempt {attempt + 1}")
            return True, repaired_ir, None

        # Validation failed, prepare for retry
        current_errors = validation_result["errors"]
        current_workflow = repaired_ir
        attempt += 1

    # Max attempts reached
    logger.warning(f"Max repair attempts ({max_attempts}) reached")
    return False, None, current_errors


def _extract_planner_cache_chunks(execution_params: Optional[dict[str, Any]]) -> Optional[list[dict[str, Any]]]:
    """Extract planner cache chunks from execution params."""
    if execution_params:
        return execution_params.get("__planner_cache_chunks__")
    return None


def _validate_repaired_workflow_static(repaired_ir: dict, execution_params: Optional[dict[str, Any]]) -> dict[str, Any]:
    """
    Validate a repaired workflow statically.

    Returns:
        Dictionary with "success" bool and optional "errors" list
    """
    from pflow.core.workflow_validator import WorkflowValidator
    from pflow.registry import Registry

    try:
        registry = Registry()
        validation_errors = WorkflowValidator.validate(
            repaired_ir,
            extracted_params=execution_params or {},
            registry=registry,
            skip_node_types=False,  # Always validate node types
        )

        if not validation_errors:
            return {"success": True}

        # Validation failed, convert errors to repair format
        logger.warning(f"Repair validation failed with {len(validation_errors)} errors")
        repair_errors = _convert_validation_errors_to_repair_format(validation_errors)
        return {"success": False, "errors": repair_errors}

    except Exception:
        logger.exception("Validation error")
        return {"success": False, "errors": [{"source": "validation", "message": "Validation failed with exception"}]}


def _convert_validation_errors_to_repair_format(validation_errors: list[str]) -> list[dict[str, Any]]:
    """Convert validation error strings to repair error format."""
    repair_errors: list[dict[str, Any]] = []

    for error in validation_errors[:3]:  # Limit to top 3 errors
        error_dict = {
            "source": "validation",
            "category": "static_validation",
            "message": error,
            "fixable": True,
        }

        # Add specific context based on error type
        if "Template" in error:
            error_dict["category"] = "template_error"
            # Extract template path if possible
            template_match = re.search(r"\$\{([^}]+)\}", error)
            if template_match:
                error_dict["template"] = template_match.group(0)
        elif "Edge" in error or "from" in error:
            error_dict["category"] = "edge_format"
            error_dict["hint"] = "Use 'from' and 'to' keys, not 'from_node' and 'to_node'"
        elif "node type" in error.lower():
            error_dict["category"] = "invalid_node_type"

        repair_errors.append(error_dict)

    return repair_errors


def _normalize_errors(errors: list[Any]) -> list[dict[str, Any]]:
    """Normalize errors to consistent dict format.

    Handles both:
    - List of strings (from validation)
    - List of dicts (from runtime)
    """
    normalized = []
    for error in errors:
        if isinstance(error, str):
            # Validation error (string)
            error_dict = {"source": "validation", "category": "static_validation", "message": error, "fixable": True}
            # Try to categorize
            if "Template" in error:
                error_dict["category"] = "template_error"
            elif "Edge" in error or "'from'" in error or "'to'" in error:
                error_dict["category"] = "edge_format"
            elif "node type" in error.lower():
                error_dict["category"] = "invalid_node_type"

            normalized.append(error_dict)
        elif isinstance(error, dict):
            # Runtime error (already dict)
            normalized.append(error)
        else:
            # Unknown format, convert to string
            normalized.append({"source": "unknown", "message": str(error), "fixable": True})

    return normalized


def _analyze_errors_for_repair(errors: list[dict[str, Any]], shared_store: Optional[dict[str, Any]]) -> dict[str, Any]:
    """
    Extract repair context from errors and execution state.

    Simplified from RuntimeValidationNode's error analysis.
    """
    context: dict[str, Any] = {
        "primary_error": errors[0] if errors else {},
        "error_count": len(errors),
        "completed_nodes": [],
        "failed_node": None,
        "template_issues": [],
    }

    # Extract checkpoint information if available
    if shared_store and "__execution__" in shared_store:
        execution_data = shared_store["__execution__"]
        context["completed_nodes"] = execution_data.get("completed_nodes", [])
        context["failed_node"] = execution_data.get("failed_node")

    # Analyze template errors (most common issue)
    for error in errors:
        msg = error.get("message", "").lower()
        category = error.get("category", "")

        if "template" in msg or category == "template_error" or "${" in msg:
            # Try to extract template path and suggestions
            template_match = re.search(r"\$\{([^}]+)\}", error.get("message", ""))
            if template_match:
                template = template_match.group(0)
                path = template_match.group(1)

                # Try to find available fields from error message
                available_match = re.search(r"available.*?:?\s*([\w,\s]+)", msg, re.IGNORECASE)
                available = []
                if available_match:
                    available = [f.strip() for f in available_match.group(1).split(",")]

                context["template_issues"].append({
                    "template": template,
                    "path": path,
                    "available_fields": available,
                    "node_id": context.get("failed_node"),
                })

    return context


def _build_repair_prompt(
    workflow_ir: dict, errors: list[dict[str, Any]], repair_context: dict[str, Any], original_request: Optional[str]
) -> str:
    """Create prompt for LLM repair."""

    # Check if these are validation errors
    has_validation_errors = any(e.get("source") == "validation" for e in errors)

    # Format errors for prompt
    error_text = _format_errors_for_prompt(errors, repair_context)

    if has_validation_errors:
        # Validation-focused prompt
        prompt = f"""Fix this workflow that has validation errors.

## Original Request
{original_request or "Not available"}

## Workflow with Validation Issues
```json
{json.dumps(workflow_ir, indent=2)}
```

## Validation Errors to Fix
{error_text}

## Important Requirements
1. Edges must use "from" and "to" keys (NOT "from_node", "to_node", "from_node_id" or "to_node_id")
2. All template variables must reference actual node outputs
3. Node types must exist in the registry
4. JSON must be valid and properly formatted
5. Template format is ${{node_id.field}} - make sure node_id exists

## Common Validation Fixes
- Change edge format: {{"from_node": "a", "to_node": "b"}} → {{"from": "a", "to": "b"}}
- Fix template paths: ${{node.wrong_field}} → ${{node.correct_field}}
- Use valid node types from registry
- Ensure all referenced node IDs exist

Return ONLY the corrected workflow JSON. Do not include explanations.

## Corrected Workflow
```json
"""
    else:
        # Runtime error prompt
        prompt = f"""Fix this workflow that failed during execution.

## Original Request
{original_request or "Not available"}

## Failed Workflow
```json
{json.dumps(workflow_ir, indent=2)}
```

## Execution Errors
{error_text}

## Repair Context
- Completed nodes: {", ".join(repair_context.get("completed_nodes", [])) or "none"}
- Failed at node: {repair_context.get("failed_node", "unknown")}

## Your Task
Analyze the errors and generate a corrected workflow that fixes the issues.

Common fixes needed:
1. Template variable corrections (e.g., ${{data.username}} → ${{data.login}})
2. Missing parameters in node configs
3. Incorrect field references
4. Shell command syntax errors
5. API response structure changes

Focus on fixing the specific error that occurred. Do not change parts of the workflow that were working correctly.

Return ONLY the corrected workflow JSON. Do not include explanations.

## Corrected Workflow
```json
"""

    return prompt


def _format_errors_for_prompt(errors: list[dict[str, Any]], repair_context: dict[str, Any]) -> str:
    """Format errors for LLM consumption."""
    lines = []

    for i, error in enumerate(errors, 1):
        message = error.get("message", "Unknown error")
        lines.append(f"{i}. {message}")

        # Add additional context if available
        category = error.get("category", "")
        if category:
            lines.append(f"   Category: {category}")

        if error.get("hint"):
            lines.append(f"   Hint: {error['hint']}")

        if error.get("exception_type"):
            lines.append(f"   Exception type: {error['exception_type']}")

        if error.get("node_id"):
            lines.append(f"   Node: {error['node_id']}")

    # Add template-specific context
    if repair_context.get("template_issues"):
        lines.append("\nTemplate Issues Found:")
        for issue in repair_context["template_issues"]:
            template = issue.get("template", "unknown")
            available = issue.get("available_fields", [])
            lines.append(f"- Template {template} not found")
            if available:
                lines.append(f"  Available fields: {', '.join(available)}")

    return "\n".join(lines)


def _extract_workflow_from_response(response: str) -> Optional[dict[str, Any]]:
    """Extract JSON workflow from LLM response."""

    # Try to find JSON block in markdown code fence
    json_matches = re.findall(r"```(?:json)?\s*(.*?)\s*```", response, re.DOTALL)
    for json_str in json_matches:
        if json_str.strip():
            try:
                parsed: dict[str, Any] = json.loads(json_str)
                return parsed
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse JSON from code block: {e}")
                # Continue to next match

    # Try to parse entire response as JSON
    try:
        result: dict[str, Any] = json.loads(response)
        return result
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in response (start from { and end at })
    json_start = response.find("{")
    json_end = response.rfind("}") + 1
    if json_start >= 0 and json_end > json_start:
        try:
            extracted: dict[str, Any] = json.loads(response[json_start:json_end])
            return extracted
        except json.JSONDecodeError as e:
            logger.debug(f"Failed to parse JSON from brackets: {e}")

    return None


def _validate_repaired_workflow(workflow_ir: Optional[dict]) -> bool:
    """Basic validation of repaired workflow."""
    if not workflow_ir:
        return False

    # Check required fields
    if "ir_version" not in workflow_ir:
        logger.warning("Repaired workflow missing ir_version")
        return False

    if "nodes" not in workflow_ir or not workflow_ir["nodes"]:
        logger.warning("Repaired workflow missing or empty nodes")
        return False

    # Check node structure
    for i, node in enumerate(workflow_ir["nodes"]):
        if "id" not in node:
            logger.warning(f"Node {i} missing id")
            return False
        if "type" not in node:
            logger.warning(f"Node {i} missing type")
            return False

    # Check edges if present
    if "edges" in workflow_ir:
        for edge in workflow_ir["edges"]:
            if "from" not in edge or "to" not in edge:
                logger.warning("Edge missing from or to")
                return False

    return True
