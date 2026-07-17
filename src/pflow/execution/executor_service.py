"""Error extraction from workflow execution results.

Stateless functions that extract structured error information from
PocketFlow's shared_store after a failed workflow execution. Used by
WorkflowRunner._build_errors() to convert raw execution state into
agent-friendly error dicts.
"""

import json
import logging
from dataclasses import replace
from typing import Any

from pflow.core.diagnostic import (
    CATEGORY_TITLES,
    Diagnostic,
    Severity,
    format_child_provenance,
    normalize_runtime_warning,
)

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


def build_error_list(success: bool, action_result: str | None, shared_store: dict[str, Any]) -> list[Diagnostic]:
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

    from pflow.runtime.node_state import get_node_failure, get_node_output

    # A failed sub-workflow node carries the child's structured failure state
    # forward in its archived data (the reserved `_pflow_child_failure` bundle,
    # written by WorkflowExecutor.post()). Reconstruct the child's diagnostics
    # recursively and wrap them with parent provenance instead of collapsing to
    # the generic one-line message (issues #233/#252). Checked BEFORE the generic
    # path so the rich reconstruction wins. The reserved `_pflow_` key is written
    # only by WorkflowExecutor.post() (collision-proof); even so, reconstruction
    # degrades gracefully on a malformed bundle (empty `failures` → generic
    # "Workflow execution failed").
    failed_node = _get_failed_node(shared_store)
    if failed_node:
        node_output = get_node_output(shared_store, failed_node)
        if isinstance(node_output, dict) and isinstance(node_output.get("_pflow_child_failure"), dict):
            return build_subworkflow_diagnostics(node_output["_pflow_child_failure"], failed_node)

    error_info = _extract_error_info(action_result, shared_store)
    category = determine_error_category(error_info["message"] or "")

    context: dict[str, Any] = {
        "category": category,
        "action": action_result,
    }

    # Extract rich error data from namespaced node output
    failed_node = error_info.get("failed_node")
    if failed_node:
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
    diagnostic_title = None
    if failed_node:
        node_output = get_node_output(shared_store, failed_node) or {}
        if isinstance(node_output, dict) and isinstance(node_output.get("_diagnostic_title"), str):
            diagnostic_title = node_output["_diagnostic_title"]

    return [
        Diagnostic(
            severity=Severity.ERROR,
            message=error_info["message"] or "Workflow execution failed",
            title=diagnostic_title or CATEGORY_TITLES.get(category, "Execution Failed"),
            node_id=failed_node,
            source="runtime",
            context=context,
        )
    ]


def build_subworkflow_diagnostics(bundle: dict[str, Any], parent_step_id: str) -> list[Diagnostic]:
    """Rebuild a failed sub-workflow child's diagnostics, wrapped with parent provenance.

    The runtime layer (``WorkflowExecutor``) ferries a JSON-able ``child_failure``
    bundle across the parent boundary — it cannot import this module without an
    import cycle. Here we reconstruct the child's structured diagnostics by
    reusing ``build_error_list`` so a nested failure renders byte-identical to a
    top-level one (shell ``exit_code``/``command``/``stderr``, HTTP status, MCP
    details, template ``unresolved_references``), then prefix each message via
    ``format_child_provenance``. Nesting recurses naturally: the reconstructed
    child shape's failed-node data may itself carry a ``child_failure`` bundle,
    which ``build_error_list`` detects and dispatches back here, so provenance
    chains outermost-first across arbitrary depth.

    Used by ``build_error_list`` (non-batch sub-workflow failures) and the batch
    error formatter (per-item sub-workflow failures).
    """
    workflow_ref = bundle.get("workflow_path")

    template_diagnostic = bundle.get("template_diagnostic")
    if isinstance(template_diagnostic, dict):
        # Strict-mode template failure: the rich Diagnostic (unresolved_references,
        # peer suggestions) lives only on the child exception — captured verbatim
        # into the bundle, never present in the child's archived failure record.
        inner: list[Diagnostic] = [Diagnostic.from_dict(template_diagnostic)]
    else:
        child_shape: dict[str, Any] = {
            "__execution__": {"failed_node": bundle.get("failed_node")},
            "__failures__": bundle.get("failures") or {},
        }
        if bundle.get("error"):
            child_shape["error"] = bundle["error"]
        inner = build_error_list(False, "error", child_shape)

    wrapped: list[Diagnostic] = []
    for d in inner:
        # Mirror the provenance contract of `_propagate_child_parser_warnings`
        # exactly (message via the shared helper, node_id fallback, setdefault
        # context keys) — see core/diagnostic.py::format_child_provenance.
        context = dict(d.context or {})
        context.setdefault("sub_workflow_step", parent_step_id)
        if isinstance(workflow_ref, str) and workflow_ref:
            context.setdefault("sub_workflow_path", workflow_ref)
        wrapped.append(
            replace(
                d,
                message=format_child_provenance(parent_step_id, d.message),
                node_id=d.node_id or parent_step_id,
                context=context,
            )
        )
    return wrapped


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


def _extract_error_info(action_result: str | None, shared_store: dict[str, Any]) -> dict[str, str | None]:
    """Extract error message and failed node from shared store.

    Priority order (most authoritative first):

    1. **Node-level error** from the failure record. ``mark_node_failed`` is
       the single write site for node failures and always records the precise
       error (shell exit code, API error, exception text). This includes
       api-warning nodes — ``handle_api_warning`` mirrors the warning text
       into ``failure.error`` so downstream readers don't need a side channel.
    2. **Root-level error** for errors not scoped to a node.
    3. **``__warnings__`` mirror** as a last-resort fallback for legacy paths
       that never populated ``failure.error``.

    The previous order put ``__warnings__`` first, which meant a routing hint
    in ``__warnings__`` masked the real ``"Command failed with exit code N"``
    message. ``_handle_no_successor`` no longer writes that hint for an
    error-action node (GH #437 — the real failure already stands in
    ``__failures__``), but this node-level-first ordering remains correct for
    any other ``__warnings__`` content that could co-exist with a failure.
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


def _get_failed_node(shared_store: dict[str, Any]) -> str | None:
    """Get failed node ID from execution checkpoint."""
    if "__execution__" in shared_store:
        execution_data = shared_store.get("__execution__", {})
        failed_node = execution_data.get("failed_node")
        return failed_node if isinstance(failed_node, str) else None
    return None


def _extract_root_level_error(shared_store: dict[str, Any]) -> dict[str, str] | None:
    """Extract error from root level of shared store."""
    if "error" not in shared_store:
        return None

    result: dict[str, str] = {"message": str(shared_store["error"])}

    if "error_details" in shared_store:
        error_details = shared_store.get("error_details", {})
        if isinstance(error_details, dict) and "server" in error_details and "tool" in error_details:
            result["node"] = f"{error_details['server']}_{error_details['tool']}"

    return result


def _extract_node_level_error(failed_node: str | None, shared_store: dict[str, Any]) -> str | None:
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


def _extract_error_from_mcp_result(result: Any) -> str | None:
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
