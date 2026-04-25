"""Error extraction from workflow execution results.

Stateless functions that extract structured error information from
PocketFlow's shared_store after a failed workflow execution. Used by
WorkflowRunner._build_errors() to convert raw execution state into
agent-friendly error dicts.
"""

import json
import logging
from typing import Any, Optional

from pflow.core.diagnostic import CATEGORY_TITLES, Diagnostic, Severity, normalize_runtime_warning

logger = logging.getLogger(__name__)


def _map_failure_category_to_diagnostic(failure_category: str) -> str:
    """Map node_state.FAILURE_CATEGORY_* values to Diagnostic context categories.

    The node_state categories are precise ("shell_failure", "api_warning", etc.).
    The Diagnostic categories are coarser ("execution_failure", "template_error", etc.)
    and drive CATEGORY_TITLES lookup. Some node_state categories collapse to the
    same Diagnostic category.
    """
    return _FAILURE_CATEGORY_MAP.get(failure_category, "execution_failure")


_FAILURE_CATEGORY_MAP: dict[str, str] = {
    "shell_failure": "execution_failure",
    "http_failure": "execution_failure",
    "mcp_failure": "execution_failure",
    # LLM gets its own diagnostic category (not collapsed into
    # "execution_failure") because agents most commonly cost-gate, retry-gate,
    # and key-rotate on LLM specifically — and the auth/permission/model-name
    # remediations are unusually structured. The string is also the constant
    # at core/diagnostic.py::LLM_FAILURE_CATEGORY; keep them in sync.
    "llm_failure": "llm_failure",
    "node_action_error": "execution_failure",
    "api_warning": "api_validation",
    "routing_error": "execution_failure",
    "exception": "execution_failure",
    "template_error": "template_error",
}


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
        from pflow.runtime.node_state import get_node_failure, get_node_output

        node_output = get_node_output(shared_store, failed_node) or {}
        if isinstance(node_output, dict):
            _enrich_error_from_node_output(context, node_output, category)

        # Use the explicitly-recorded category from the failure record
        # when available (set at the failure site by mark_node_failed),
        # falling back to the legacy regex-based detection.
        failure = get_node_failure(shared_store, failed_node)
        if failure and failure.get("category"):
            context["category"] = _map_failure_category_to_diagnostic(str(failure["category"]))

    category = str(context["category"])

    return [
        Diagnostic(
            severity=Severity.ERROR,
            message=error_info["message"] or "Workflow execution failed",
            title=CATEGORY_TITLES.get(category, "Execution Failed"),
            node_id=failed_node,
            source="runtime",
            context=context,
        )
    ]


def determine_error_category(error_message: str) -> str:
    """Determine error category from message content (regex-on-message fallback).

    Only used when no failure record carries an explicit category — e.g. a
    root-level error with no ``failed_node``. Task 148's ``mark_node_failed``
    is the authoritative category source for every node-level failure, and
    ``build_error_list`` overwrites the result of this function with
    ``__failures__[id].category`` whenever a failure record is present.

    The previous implementation also regex-matched ``"${"`` or the literal
    word ``"template"`` to return ``"template_error"``. That was a fragile
    heuristic from before Task 148 — shell commands that legitimately echo
    ``${PATH}`` or ``"template"`` would get misclassified. It has been
    removed. Template errors now flow through ``mark_node_failed`` with
    ``category=FAILURE_CATEGORY_TEMPLATE`` set at the failure site.
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

    return "execution_failure"


# --- Internal helpers ---


def _extract_error_info(action_result: Optional[str], shared_store: dict[str, Any]) -> dict[str, Optional[str]]:
    """Extract error message and failed node from shared store.

    Priority order (most authoritative first):

    1. **Node-level error** from the failure record. ``mark_node_failed`` is
       the single write site for node failures and always records the precise
       error (shell exit code, API error, exception text). This includes
       api-warning nodes — ``handle_api_warning`` mirrors the warning text
       into ``failure.error`` so downstream readers don't need a side channel.
    2. **Root-level error** for errors not scoped to a node (e.g. MCP protocol
       errors that return ``"default"`` and write ``shared["error"]`` directly).
    3. **``__warnings__`` mirror** as a last-resort fallback for legacy paths
       that never populated ``failure.error``.

    The previous order put ``__warnings__`` first, which meant
    ``_handle_no_successor``'s routing hint (written via ``__warnings__`` to
    preserve the rich shell failure record — see Task 148 Fix #2) masked the
    real ``"Command failed with exit code N"`` message.
    """
    failed_node = _get_failed_node(shared_store)

    if failed_node:
        node_error = _extract_node_level_error(failed_node, shared_store)
        if node_error:
            return {"message": node_error, "failed_node": failed_node}

    root_error = _extract_root_level_error(shared_store)
    if root_error:
        return {
            "message": root_error["message"],
            "failed_node": failed_node or root_error.get("node"),
        }

    api_warnings = shared_store.get("__warnings__", {})
    if failed_node and failed_node in api_warnings:
        message, _context = normalize_runtime_warning(api_warnings[failed_node])
        return {"message": message, "failed_node": failed_node}

    return {
        "message": f"Workflow failed with action: {action_result}",
        "failed_node": failed_node,
    }


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
    """Extract error from failed node's output (succeeded namespace OR __failures__)."""
    if not failed_node:
        return None

    from pflow.runtime.node_state import get_node_failure, get_node_output

    # Prefer the failure record's explicit error field if present
    failure = get_node_failure(shared_store, failed_node)
    if failure and failure.get("error"):
        return str(failure["error"])

    node_output = get_node_output(shared_store, failed_node)
    if not isinstance(node_output, dict):
        return None

    if node_output.get("error"):
        return str(node_output["error"])

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
        context["available_fields_label"] = "fields in node"

        total_fields = len(all_fields)
        if total_fields > MAX_DISPLAYED_FIELDS:
            context["available_fields_total"] = total_fields

    # LLM node data: lift the structured diagnostic context built by the
    # exception's to_diagnostics() override, so the runtime Diagnostic that
    # reaches JSON output carries the same structured fields (error_class,
    # model, reason/kind, etc.) the override produced. LLMNode.post() writes
    # _diagnostic_context into shared[node_id]; mark_node_failed archives
    # node_output → __failures__[id]["data"]; this is where it's read.
    # setdefault preserves any context keys the runtime path already set
    # (e.g. category from _FAILURE_CATEGORY_MAP).
    llm_diagnostic_context = node_output.get("_diagnostic_context")
    if isinstance(llm_diagnostic_context, dict):
        for key, value in llm_diagnostic_context.items():
            context.setdefault(key, value)
