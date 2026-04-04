"""Error extraction from workflow execution results.

Stateless functions that extract structured error information from
PocketFlow's shared_store after a failed workflow execution. Used by
WorkflowRunner._build_errors() to convert raw execution state into
agent-friendly error dicts.
"""

import json
import logging
from typing import Any, Optional

from pflow.core.diagnostic import _CATEGORY_TITLES, Diagnostic, Severity

logger = logging.getLogger(__name__)


def build_error_list(success: bool, action_result: Optional[str], shared_store: dict[str, Any]) -> list[Diagnostic]:
    """Build error list from a failed workflow execution.

    Args:
        success: Whether execution was successful
        action_result: The action result from flow.run()
        shared_store: The shared store containing error details

    Returns:
        List of error diagnostics with rich context (shell, HTTP, MCP details)
    """
    if success:
        return []

    error_info = _extract_error_info(action_result, shared_store)
    category = determine_error_category(error_info["message"] or "")

    context: dict[str, Any] = {
        "category": category,
        "action": action_result,
    }

    # Extract rich error data from namespaced node output
    failed_node = error_info.get("failed_node")
    if failed_node:
        node_output = shared_store.get(failed_node, {})
        if isinstance(node_output, dict):
            _enrich_error_from_node_output(context, node_output, category)

    return [
        Diagnostic(
            severity=Severity.ERROR,
            message=error_info["message"] or "Workflow execution failed",
            title=_CATEGORY_TITLES.get(category, "Execution Failed"),
            node_id=failed_node,
            source="runtime",
            context=context,
        )
    ]


def determine_error_category(error_message: str) -> str:
    """Determine error category based on message content.

    Args:
        error_message: The error message

    Returns:
        Error category string: "api_validation", "template_error", or "execution_failure"
    """
    error_lower = error_message.lower()

    api_patterns = [
        "input should be",
        "field required",
        "invalid request data",
        "following fields are missing",
        "validation error",
        "parameter `",
    ]

    if any(pattern in error_lower for pattern in api_patterns):
        return "api_validation"

    if "${" in error_message or "template" in error_lower:
        return "template_error"

    return "execution_failure"


# --- Internal helpers ---


def _extract_error_info(action_result: Optional[str], shared_store: dict[str, Any]) -> dict[str, Optional[str]]:
    """Extract error message and failed node from shared store."""
    error_message = f"Workflow failed with action: {action_result}"
    failed_node = _get_failed_node(shared_store)

    # Priority 1: API warnings from InstrumentedNodeWrapper
    api_warnings = shared_store.get("__warnings__", {})
    if failed_node and failed_node in api_warnings:
        return {"message": api_warnings[failed_node], "failed_node": failed_node}

    # Priority 2: Root-level error field
    root_error = _extract_root_level_error(shared_store)
    if root_error:
        error_message = root_error["message"]
        if not failed_node:
            failed_node = root_error.get("node")
    else:
        # Priority 3: Node-level error from shared store
        node_error = _extract_node_level_error(failed_node, shared_store)
        if node_error:
            error_message = node_error

    return {"message": error_message, "failed_node": failed_node}


def _get_failed_node(shared_store: dict[str, Any]) -> Optional[str]:
    """Get failed node ID from execution checkpoint."""
    if "__execution__" in shared_store:
        execution_data = shared_store.get("__execution__", {})
        failed_node = execution_data.get("failed_node")
        return failed_node if isinstance(failed_node, str) else None
    return None


def _extract_root_level_error(shared_store: dict[str, Any]) -> Optional[dict[str, str]]:
    """Extract error from root level of shared store."""
    if "error" not in shared_store:
        return None

    result: dict[str, str] = {"message": str(shared_store["error"])}

    if "error_details" in shared_store:
        error_details = shared_store.get("error_details", {})
        if isinstance(error_details, dict) and "server" in error_details and "tool" in error_details:
            result["node"] = f"{error_details['server']}_{error_details['tool']}"

    return result


def _extract_node_level_error(failed_node: Optional[str], shared_store: dict[str, Any]) -> Optional[str]:
    """Extract error from failed node's output."""
    if not failed_node or failed_node not in shared_store:
        return None

    node_output = shared_store.get(failed_node, {})
    if not isinstance(node_output, dict):
        return None

    # Direct error field (skip None/falsy — MCP responses have "error": null)
    if node_output.get("error"):
        return str(node_output["error"])

    # MCP result format
    if "result" in node_output:
        return _extract_error_from_mcp_result(node_output["result"])

    return None


def _extract_error_from_mcp_result(result: Any) -> Optional[str]:
    """Extract error from MCP result format.

    Handles nested payloads like Slack/Discord responses:
    {"successful": true, "error": null, "data": {"ok": false, "error": "channel_not_found"}}
    """
    if not isinstance(result, str):
        return None

    try:
        result_data = json.loads(result)
        if not isinstance(result_data, dict):
            return None

        if result_data.get("error"):
            error = result_data["error"]
            return error if isinstance(error, str) else str(error)

        data = result_data.get("data")
        if isinstance(data, dict) and data.get("error"):
            error = data["error"]
            return error if isinstance(error, str) else str(error)

    except (json.JSONDecodeError, TypeError):
        pass

    return None


def _enrich_error_from_node_output(context: dict[str, Any], node_output: dict[str, Any], category: str) -> None:
    """Add rich error context from the failed node's output dict.

    Mutates the context dict in place with HTTP, MCP, shell, and template details.
    """
    # HTTP node data
    if "status_code" in node_output:
        context["status_code"] = node_output["status_code"]
        context["raw_response"] = node_output.get("response")
        context["response_headers"] = node_output.get("response_headers")
        context["response_time"] = node_output.get("response_time")

    # MCP node data
    if "error_details" in node_output:
        context["mcp_error_details"] = node_output["error_details"]

    if "result" in node_output and isinstance(node_output["result"], dict) and "error" in node_output["result"]:
        context["mcp_error"] = node_output["result"]["error"]

    # Shell node data
    if "exit_code" in node_output and "command" in node_output:
        context["shell_command"] = node_output.get("command")
        context["shell_exit_code"] = node_output.get("exit_code")
        context["shell_stdout"] = node_output.get("stdout")
        context["shell_stderr"] = node_output.get("stderr")

    # Template errors: capture available fields
    if category == "template_error":
        from pflow.runtime.template_validation import MAX_DISPLAYED_FIELDS

        all_fields = list(node_output.keys()) if isinstance(node_output, dict) else []
        context["available_fields"] = [str(f) for f in all_fields[:MAX_DISPLAYED_FIELDS]]

        total_fields = len(all_fields)
        if total_fields > MAX_DISPLAYED_FIELDS:
            context["available_fields_total"] = total_fields
            context["available_fields_truncated"] = True
            context["trace_file_hint"] = (
                f"Showing {MAX_DISPLAYED_FIELDS} of {total_fields} fields. "
                "Full field list saved automatically to ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json"
            )
