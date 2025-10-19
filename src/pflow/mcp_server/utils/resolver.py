"""Workflow resolution utilities for MCP server.

This module provides functions to resolve workflow references
(name, path, or IR) into executable workflow IR.
"""

import json
import logging
from pathlib import Path
from typing import Any

from pflow.core.suggestion_utils import find_similar_items
from pflow.core.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)


def resolve_workflow(workflow: str | dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, str]:
    """Resolve a workflow reference to executable IR.

    Resolution order:
    1. If dict: Use directly as IR
    2. If string: Try as saved workflow name
    3. If string: Try as file path
    4. Return error with suggestions

    Args:
        workflow: Workflow name, path, or IR dict

    Returns:
        Tuple of (workflow_ir, error_message, source)
        Source is one of: "direct", "library", "file"
    """
    # Case 1: Direct IR dictionary
    if isinstance(workflow, dict):
        logger.debug("Using workflow as direct IR")
        return workflow, None, "direct"

    # Case 2: String reference (name or path)
    if not isinstance(workflow, str):
        return None, f"Invalid workflow type: {type(workflow)}", ""

    # Try as saved workflow name
    manager = WorkflowManager()
    if manager.exists(workflow):
        logger.debug(f"Loading workflow from library: {workflow}")
        try:
            workflow_ir = manager.load_ir(workflow)
            return workflow_ir, None, "library"
        except Exception:
            logger.exception(f"Failed to load workflow {workflow}")
            return None, "Failed to load workflow", ""

    # Try as file path
    path = Path(workflow).expanduser()  # Expand ~ to home directory
    if path.exists() and path.is_file():
        # No path validation needed - user is reading their own files on their own machine
        logger.debug(f"Loading workflow from file: {path}")
        try:
            with open(path) as f:
                workflow_ir = json.load(f)
            return workflow_ir, None, "file"
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON in file: {e!s}", ""
        except Exception as e:
            return None, f"Failed to read file: {e!s}", ""

    # Not found - provide suggestions
    suggestions = get_workflow_suggestions(workflow, manager)
    error_msg = f"Workflow not found: '{workflow}'"
    if suggestions:
        error_msg += "\n\nDid you mean one of these?\n"
        error_msg += "\n".join(f"  - {s}" for s in suggestions[:5])

    return None, error_msg, ""


def get_workflow_suggestions(query: str, manager: WorkflowManager | None = None) -> list[str]:
    """Get workflow name suggestions for a query.

    Finds workflows with similar names to help users.

    Args:
        query: The query string
        manager: Optional WorkflowManager instance

    Returns:
        List of suggested workflow names
    """
    if manager is None:
        manager = WorkflowManager()

    try:
        all_workflows = manager.list_all()
        # Extract names from list of workflow metadata dicts
        workflow_names = [wf.get("name", "") for wf in all_workflows if wf.get("name")]

        # Find similar workflows using shared utility
        suggestions = find_similar_items(query, workflow_names, max_results=5, method="substring", sort_by_length=True)

        return suggestions
    except Exception:
        logger.exception("Failed to get workflow suggestions")
        return []
