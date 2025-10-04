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
    trace_collector: Optional[Any] = None,
    repair_model: Optional[str] = None,
) -> tuple[bool, Optional[dict]]:
    """
    Attempt to repair a broken workflow using LLM.

    Args:
        workflow_ir: The workflow that failed
        errors: List of error dictionaries from execution
        original_request: Original user request for context
        shared_store: Execution state for additional context
        planner_cache_chunks: Cache chunks from planner for context
        trace_collector: Optional trace collector for debugging
        repair_model: LLM model to use for repairs (default: auto-detect)

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

        # Set up LLM and get model
        model, is_anthropic = _setup_llm_model(repair_model, planner_cache_chunks, trace_collector)

        # Invoke LLM to generate repair
        result = _invoke_llm_for_repair(model, prompt, is_anthropic, planner_cache_chunks)
        if not result:
            return False, None

        # Convert LLM response to workflow IR
        repaired_ir = _convert_llm_response(result, is_anthropic)

        # Finalize and validate repair result
        return _finalize_repair_result(repaired_ir, prompt, trace_collector)

    except Exception:
        logger.exception("Repair generation failed")
        return False, None


def _setup_llm_model(
    repair_model: Optional[str],
    planner_cache_chunks: Optional[list[dict[str, Any]]],
    trace_collector: Optional[Any],
) -> tuple[Any, bool]:
    """
    Set up LLM model for repair generation.

    Args:
        repair_model: LLM model name or None for auto-detect
        planner_cache_chunks: Cache chunks for context
        trace_collector: Optional trace collector

    Returns:
        Tuple of (model, is_anthropic)
    """
    # Set up LLM interception for trace if available
    if trace_collector and hasattr(trace_collector, "setup_llm_interception"):
        trace_collector.setup_llm_interception("repair_workflow")

    # Use same model as planner (or auto-detect if not specified)
    if repair_model is None:
        from pflow.core.llm_config import get_default_llm_model

        repair_model = get_default_llm_model() or "anthropic/claude-sonnet-4-5"

    # Get the LLM model
    model = llm.get_model(repair_model)

    # Check if this is an Anthropic model (monkey-patched models need cache_blocks)
    is_anthropic = bool(
        repair_model
        and (
            repair_model.startswith("anthropic/")
            or repair_model.startswith("claude-")
            or "claude" in repair_model.lower()
        )
    )

    return model, is_anthropic


def _invoke_llm_for_repair(
    model: Any,
    prompt: str,
    is_anthropic: bool,
    planner_cache_chunks: Optional[list[dict[str, Any]]],
) -> Optional[Any]:
    """
    Invoke LLM to generate workflow repair.

    Args:
        model: LLM model instance
        prompt: Repair prompt
        is_anthropic: Whether model is Anthropic
        planner_cache_chunks: Cache chunks for context

    Returns:
        Parsed repair result or None on failure
    """
    from pflow.planning.ir_models import FlowIR

    # CRITICAL: Pass cache chunks as cache_blocks parameter, not in prompt text
    cache_blocks = planner_cache_chunks if planner_cache_chunks else None

    result: Any
    # Build kwargs based on model type
    if is_anthropic:
        # Anthropic: Use full FlowIR with nested models (supports $defs/$ref and structured output)
        llm_kwargs = {
            "schema": FlowIR,
            "temperature": 0.0,
            "thinking_budget": 0,
            "cache_blocks": cache_blocks,
        }
        # Generate repair with structured output
        response = model.prompt(prompt, **llm_kwargs)

        # Parse structured response
        from pflow.planning.utils.llm_helpers import parse_structured_response

        result = parse_structured_response(response, FlowIR)
    else:
        # Non-Anthropic (Gemini, OpenAI): Use text mode, no structured output
        # These providers have limited/unreliable structured output support
        llm_kwargs = {
            "temperature": 0.0,
        }
        # Generate repair in text mode
        response = model.prompt(prompt, **llm_kwargs)

        # Extract JSON from text response
        response_text = response.text() if callable(response.text) else response.text
        result = _extract_workflow_from_response(response_text)
        if not result:
            logger.error(f"Failed to extract JSON from LLM response: {response_text[:200]}")
            return None

    return result


def _convert_llm_response(result: Any, is_anthropic: bool) -> dict[str, Any]:
    """
    Convert LLM response to workflow IR format.

    Args:
        result: LLM response (structured or dict)
        is_anthropic: Whether model is Anthropic

    Returns:
        Workflow IR dict
    """
    from pflow.planning.ir_models import FlowIR

    # Convert result to dict format
    if is_anthropic:
        # Anthropic: FlowIR result needs validation and alias conversion
        if isinstance(result, dict):
            # Validate through Pydantic model
            flow_model = FlowIR.model_validate(result)
            # Dump with aliases to get correct edge format
            repaired_ir: dict[str, Any] = flow_model.model_dump(by_alias=True)
        elif hasattr(result, "model_dump"):
            # Already a Pydantic model
            repaired_ir = result.model_dump(by_alias=True)
        else:
            # Fallback: use as-is
            repaired_ir = result
    else:
        # Non-Anthropic: result is already a dict from JSON extraction
        repaired_ir = result

    return repaired_ir


def _finalize_repair_result(
    repaired_ir: dict[str, Any],
    prompt: str,
    trace_collector: Optional[Any],
) -> tuple[bool, Optional[dict]]:
    """
    Finalize repair result with validation and trace recording.

    Args:
        repaired_ir: Repaired workflow IR
        prompt: Repair prompt used
        trace_collector: Optional trace collector

    Returns:
        Tuple of (success, repaired_workflow_ir or None)
    """
    # Record repair LLM call in trace if available
    if trace_collector and hasattr(trace_collector, "record_repair_llm_call"):
        # Convert to JSON string for proper formatting in traces
        response_json = json.dumps(repaired_ir, indent=2)
        trace_collector.record_repair_llm_call(prompt=prompt, response=response_json, success=True)

    logger.debug(f"Structured repair result: {str(repaired_ir)[:500]}...")

    # Basic validation
    if not _validate_repaired_workflow(repaired_ir):
        logger.warning("Repaired workflow failed validation")
        return False, None

    logger.info("Successfully generated workflow repair")
    return True, repaired_ir


def repair_workflow_with_validation(
    workflow_ir: dict,
    errors: list[Any],  # Can be list of strings (validation) or dicts (runtime)
    original_request: Optional[str] = None,
    shared_store: Optional[dict[str, Any]] = None,
    execution_params: Optional[dict[str, Any]] = None,
    max_attempts: int = 3,
    trace_collector: Optional[Any] = None,
    repair_model: Optional[str] = None,
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
        trace_collector: Optional trace collector for debugging
        repair_model: LLM model to use for repairs (default: auto-detect)

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
            trace_collector=trace_collector,
            repair_model=repair_model,
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
        "is_mcp_tool": False,  # Track if this is an MCP tool error
        "mcp_server": None,
        "mcp_tool": None,
    }

    # Extract checkpoint information if available
    _extract_checkpoint_info(context, shared_store)

    # Check if failed node is an MCP tool
    _check_mcp_tool_error(context, shared_store)

    # Analyze template errors (most common issue)
    _analyze_template_errors(context, errors)

    return context


def _extract_checkpoint_info(context: dict[str, Any], shared_store: Optional[dict[str, Any]]) -> None:
    """Extract checkpoint information from shared store into context."""
    if shared_store and "__execution__" in shared_store:
        execution_data = shared_store["__execution__"]
        context["completed_nodes"] = execution_data.get("completed_nodes", [])
        context["failed_node"] = execution_data.get("failed_node")


def _check_mcp_tool_error(context: dict[str, Any], shared_store: Optional[dict[str, Any]]) -> None:
    """Check if the failed node is an MCP tool and update context."""
    failed_node = context.get("failed_node")
    if not (failed_node and shared_store and failed_node in shared_store):
        return

    node_data = shared_store[failed_node]
    # Check for MCP error pattern in the result
    if not (isinstance(node_data, dict) and "result" in node_data):
        return

    import json

    try:
        # MCP nodes often store result as JSON string
        if isinstance(node_data["result"], str):
            result_data = json.loads(node_data["result"])
            # Fix nested if: combine conditions with 'and'
            if isinstance(result_data, dict) and ("successfull" in result_data or "successful" in result_data):
                context["is_mcp_tool"] = True
                # Try to extract server/tool info from error logs
                if "logs" in result_data:
                    context["mcp_context"] = "MCP tool execution"
    except (json.JSONDecodeError, TypeError):
        pass


def _analyze_template_errors(context: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    """Analyze template errors and extract relevant information into context."""
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


# Category-specific guidance for repair
# TODO: Improve CATEGORY_GUIDANCE prompts to be more actionable and LLM-friendly
# Current issues:
# 1. Guidance is too generic and doesn't provide concrete step-by-step instructions
# 2. Missing examples of actual error patterns and their fixes
# 3. Should include code snippets showing before/after transformations
# 4. Need better decision trees (e.g., "if error contains X, then check Y")
# 5. Should reference specific node types that commonly cause each error type
# 6. Missing guidance on how to verify the fix will work
# 7. Could benefit from common antipatterns to avoid
# See GitHub issue for detailed improvement plan
CATEGORY_GUIDANCE = {
    "execution_failure": {
        "title": "Runtime Execution Failures",
        "guidance": [
            "Data format mismatch between what a node receives vs what it expects",
            "Check the UPSTREAM node that produces the failing input",
            "If an LLM node produces the data, its output format likely needs fixing",
            "Solution: Add clear format instructions and examples to LLM prompts",
            "Solution: Add intermediate transformation nodes if needed",
        ],
    },
    "api_validation": {
        "title": "API Parameter Validation Errors",
        "guidance": [
            "External API/tool rejecting the parameter format",
            "Error message usually shows expected format (e.g., 'should be a list')",
            "Check how the data is prepared in upstream nodes",
            "Solution: Match the exact format the API expects",
            "Solution: If LLM prepares data, show it example of correct format",
            "Important: Preserve all working parameters when fixing format issues",
        ],
    },
    "template_error": {
        "title": "Template Variable Resolution Errors",
        "guidance": [
            "Template path ${node.field} references non-existent data",
            "Check what fields the referenced node ACTUALLY outputs",
            "Common issue: Assuming a field exists when it doesn't",
            "Solution: Correct the template path to match actual output",
            "Solution: Modify upstream node to produce the expected field",
            "Tip: Check if the node uses namespacing (data might be at ${node.result.field})",
        ],
    },
    "static_validation": {
        "title": "Workflow Structure Validation Errors",
        "guidance": [
            "Workflow IR structure issues detected before execution",
            "Common issues: Invalid edges, missing required fields",
            "These must be fixed in the workflow structure itself",
            "Solution: Ensure edges use 'from' and 'to' (not 'from_node'/'to_node')",
            "Solution: Check all node IDs referenced in edges actually exist",
        ],
    },
    "edge_format": {
        "title": "Edge Format Errors",
        "guidance": [
            "Edge structure doesn't match expected format",
            "Edges must have 'from' and 'to' fields",
            "Solution: Change {'from_node': 'a', 'to_node': 'b'} to {'from': 'a', 'to': 'b'}",
            "Solution: Ensure all referenced nodes exist",
        ],
    },
    "invalid_node_type": {
        "title": "Invalid Node Type Errors",
        "guidance": [
            "Node type doesn't exist in the registry",
            "Check for typos in the node type",
            "Solution: Use a valid node type from the registry",
            "Solution: Check if you need a different node that provides similar functionality",
        ],
    },
}


def _get_category_guidance(errors: list[dict[str, Any]]) -> str:
    """Build category-specific guidance based on error categories present.

    Args:
        errors: List of error dictionaries with 'category' field

    Returns:
        Formatted guidance text for categories present in errors
    """
    # Extract unique categories from errors
    categories = set()
    for error in errors:
        category = error.get("category")
        if category and category in CATEGORY_GUIDANCE:
            categories.add(category)

    if not categories:
        return ""

    # Build guidance section
    sections = ["\n## Guidance for Error Categories Present\n"]

    for category in sorted(categories):
        guidance_info = CATEGORY_GUIDANCE[category]
        sections.append(f"### {guidance_info['title']}")
        for item in guidance_info["guidance"]:
            sections.append(f"- {item}")
        sections.append("")  # Empty line between categories

    return "\n".join(sections)


def _build_repair_prompt(
    workflow_ir: dict, errors: list[dict[str, Any]], repair_context: dict[str, Any], original_request: Optional[str]
) -> str:
    """Create prompt for LLM repair."""

    # Format errors for prompt
    error_text = _format_errors_for_prompt(errors, repair_context)

    # Get category-specific guidance
    category_guidance = _get_category_guidance(errors)

    # Single unified repair prompt that works for all error types
    prompt = f"""Fix this workflow that has errors. [v2]

## Core Repair Principle
The error occurred at one node, but the fix might be in a different node. Consider the data flow:
- If a node fails because of bad input format, fix the UPSTREAM node that produces that data
- If an LLM node's output causes downstream failures, improve its prompt with clear formatting instructions and examples
- Read the error carefully to understand what data format is expected vs what was received

## Original Request
{original_request or "Not available"}

## Failed Workflow
```json
{json.dumps(workflow_ir, indent=2)}
```

## Errors to Fix
{error_text}

## Repair Context
- Completed nodes: {", ".join(repair_context.get("completed_nodes", [])) or "none"}
- Failed at node: {repair_context.get("failed_node", "unknown")}
{category_guidance}
## Your Task
Analyze the error and fix the root cause, which may be in an upstream node. Only modify what's necessary to fix the issue.

Return ONLY the corrected workflow JSON.

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
                logger.warning(f"Edge missing from or to: {edge}")
                return False

    return True
