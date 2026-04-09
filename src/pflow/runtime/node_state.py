"""Node execution state queries and failure bookkeeping.

This module is the single source of truth for "did this node succeed,
fail, or never run?". It also owns the move of failed-node data from
the main shared store namespace into shared["__failures__"][node_id].

The invariant this module enforces:
    shared[node_id]            ↔ node_id ran successfully
    shared["__failures__"][id] ↔ node_id executed and failed
    neither                    ↔ node_id did not execute

Failed-node data is preserved (not deleted) so error enrichment,
diagnostics, and traces can still surface it. The move means the
template resolver and every other consumer that asks "is this node's
output usable?" can use the simple check ``node_id in shared`` and
get the right answer.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class NodeStatus(Enum):
    """Three execution states a node can be in."""

    ABSENT = "absent"  # Did not execute (branch not taken)
    SUCCEEDED = "succeeded"  # Ran, produced authoritative output
    FAILED = "failed"  # Ran, failed (on-error routed, api warning, exception)


# Categories used by mark_node_failed. Set at the failure site so the
# formatter doesn't have to regex the error message or sniff data-key
# shapes to guess the type. Every reader (display renderer, category
# mapper, failure data extractor) dispatches purely on this string.
FAILURE_CATEGORY_SHELL = "shell_failure"
FAILURE_CATEGORY_HTTP = "http_failure"
FAILURE_CATEGORY_MCP = "mcp_failure"
FAILURE_CATEGORY_NODE_ERROR = "node_action_error"
FAILURE_CATEGORY_API_WARNING = "api_warning"
FAILURE_CATEGORY_ROUTING = "routing_error"
FAILURE_CATEGORY_EXCEPTION = "exception"
FAILURE_CATEGORY_TEMPLATE = "template_error"


def get_node_status(shared: dict[str, Any], node_id: str) -> NodeStatus:
    """Return the execution state of a node.

    Order of checks matters: __failures__ is checked first because a
    revisited (loop) node may temporarily appear in both during the
    transition; FAILED wins until the new run commits.
    """
    if node_id in shared.get("__failures__", {}):
        return NodeStatus.FAILED
    if node_id in shared and not (node_id.startswith("__") and node_id.endswith("__")):
        return NodeStatus.SUCCEEDED
    return NodeStatus.ABSENT


def node_succeeded(shared: dict[str, Any], node_id: str) -> bool:
    """True if and only if the node ran successfully and has output."""
    return get_node_status(shared, node_id) == NodeStatus.SUCCEEDED


def get_node_output(shared: dict[str, Any], node_id: str) -> Any | None:
    """Return node output regardless of success/failure.

    Used by consumers that need the data either way (trace, error
    enrichment, get_upstream_stderr). Returns None only when the node
    did not execute. For failed nodes, returns the ``data`` field of
    the failure record — same shape consumers saw before the
    step 17.5 archive move.

    Trusts the single-writer invariant: ``mark_node_failed`` is the
    only path that writes ``__failures__`` and always writes a dict
    with a ``data`` field, so no isinstance guards are needed.
    """
    failure = shared.get("__failures__", {}).get(node_id)
    if failure is not None:
        return failure["data"]
    return shared.get(node_id)


def get_node_failure(shared: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    """Return the failure record for a failed node, or None.

    The failure record has shape::

        {
            "data": {...},        # what was at shared[node_id] before the move
            "category": "...",    # one of the FAILURE_CATEGORY_* constants
            "error": "...",       # human-readable error message (optional)
            "warning": "...",     # for api_warning category only (optional)
        }

    Trusts the single-writer invariant — see ``get_node_output``.
    """
    failures: dict[str, Any] = shared.get("__failures__", {})
    return failures.get(node_id)


def mark_node_failed(
    shared: dict[str, Any],
    node_id: str,
    *,
    category: str,
    error: str | None = None,
    warning: str | None = None,
) -> None:
    """Archive a failed node's output and update execution state.

    This is the SINGLE write site for "this node failed". All five
    failure paths in the engine funnel through this function:

    1. ``cache_result`` when the node returned an action starting with "error"
    2. ``handle_api_warning`` when the API warning detector triggered
    3. ``_handle_no_successor`` when the action has no matching edge
    4. ``_execute_node`` except block when the node raised
    5. Defensive paths in the runner

    Effects:
    - Moves ``shared[node_id]`` to ``shared["__failures__"][node_id]``
      wrapped in a failure record. The original namespace key is removed.
    - Sets ``shared["__execution__"]["failed_node"] = node_id``.
    - If a warning is given, also writes it to ``shared["__warnings__"]``
      (used for DEGRADED status detection).
    - Removes the node from ``__execution__["completed_nodes"]`` and
      ``node_actions`` if it was previously recorded there (loop case).

    The data field of the failure record is whatever was at
    ``shared[node_id]`` (an empty dict if nothing was written before
    failure). The category and error fields are set from arguments.
    """
    # Internal ``__*__`` keys are reserved for per-workflow bookkeeping
    # (``__execution__``, ``__warnings__``, ``__failures__``, ...). Marking
    # one of them "failed" would corrupt the structure — it would write
    # ``__failures__["__execution__"]`` AND ``__execution__["failed_node"]
    # = "__execution__"``. Fail loudly at the call site instead of silently
    # accepting an invalid node_id. Every caller today passes
    # ``config.node_id`` (an IR-validated user node), so this raise is
    # defense-in-depth — it catches future misuse.
    if node_id.startswith("__") and node_id.endswith("__"):
        raise ValueError(
            f"mark_node_failed called with reserved internal key: {node_id!r}. Only user node ids can be marked failed."
        )

    if "__execution__" not in shared:
        shared["__execution__"] = {
            "completed_nodes": [],
            "node_actions": {},
            "node_hashes": {},
            "failed_node": None,
            "node_visit_counts": {},
        }

    popped = shared.pop(node_id, None)
    data: dict[str, Any] = popped if isinstance(popped, dict) else ({} if popped is None else {"value": popped})

    record: dict[str, Any] = {
        "data": data,
        "category": category,
    }
    if error is not None:
        record["error"] = str(error)
    if warning is not None:
        record["warning"] = str(warning)

    shared.setdefault("__failures__", {})[node_id] = record
    shared["__execution__"]["failed_node"] = node_id

    # Loop case: a node that previously succeeded is being marked failed
    # on re-entry. Strip its successful bookkeeping.
    completed = shared["__execution__"].get("completed_nodes", [])
    if node_id in completed:
        completed.remove(node_id)
    shared["__execution__"].get("node_actions", {}).pop(node_id, None)
    shared["__execution__"].get("node_hashes", {}).pop(node_id, None)

    if warning is not None:
        shared.setdefault("__warnings__", {})[node_id] = warning


def clear_node_failure(shared: dict[str, Any], node_id: str) -> None:
    """Clear all per-failure bookkeeping for a node.

    Used when a previously-failed node is being re-executed (loop case).
    Clears BOTH ``__failures__[node_id]`` AND ``__warnings__[node_id]`` —
    without the latter, a recovered node would still appear in
    ``__warnings__`` and ``_determine_status`` would incorrectly report
    ``DEGRADED`` after a successful retry (e.g. an api_warning failure on
    visit 1 followed by a clean success on visit 2).

    The new execution will populate ``shared[node_id]`` if it succeeds,
    or call ``mark_node_failed`` again if it fails.
    """
    failures = shared.get("__failures__")
    if isinstance(failures, dict):
        failures.pop(node_id, None)
    warnings = shared.get("__warnings__")
    if isinstance(warnings, dict):
        warnings.pop(node_id, None)
