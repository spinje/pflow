"""Workflow resolution utilities for MCP server.

This module provides functions to resolve workflow references
(name, path, or raw markdown content) into executable workflow IR.
"""

import logging
from pathlib import Path
from typing import Any

from pflow.core.markdown_parser import MarkdownParseError, parse_markdown
from pflow.core.suggestion_utils import find_similar_items
from pflow.core.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)


def resolve_workflow(workflow: str | dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, str]:
    """Resolve a workflow reference to executable IR.

    Resolution order:
    1. If dict: Use directly as IR
    2. If string with newline: Parse as raw markdown content
    3. If string ending .pflow.md (single-line): Read as file path
    4. If single-line string: Try as saved workflow name, then as file path
    5. Return error with suggestions

    Args:
        workflow: Workflow name, file path, raw markdown content, or IR dict

    Returns:
        Tuple of (workflow_ir, error_message, source)
        Source is one of: "direct", "library", "file", "content"
    """
    # Case 1: Direct IR dictionary
    if isinstance(workflow, dict):
        logger.debug("Using workflow as direct IR")
        return workflow, None, "direct"

    # Case 2: String reference
    if not isinstance(workflow, str):
        return None, f"Invalid workflow type: {type(workflow)}", ""

    # Case 2a: Raw markdown content (contains newlines)
    if "\n" in workflow:
        logger.debug("Parsing workflow from raw markdown content")
        try:
            result = parse_markdown(workflow)
            return result.ir, None, "content"
        except MarkdownParseError as e:
            return None, f"Invalid markdown content: {e}", ""
        except Exception as e:
            return None, f"Failed to parse markdown content: {e!s}", ""

    # Case 2b: File path (ends with .pflow.md)
    if workflow.lower().endswith(".pflow.md"):
        path = Path(workflow).expanduser()
        if path.exists() and path.is_file():
            logger.debug(f"Loading workflow from file: {path}")
            return _load_from_file(path)
        else:
            return None, f"Workflow file not found: {workflow}", ""

    # Case 2c: Try as saved workflow name, then file path
    return _resolve_by_name(workflow)


def _load_from_file(path: Path) -> tuple[dict[str, Any] | None, str | None, str]:
    """Load and parse a workflow file.

    Args:
        path: Path to the .pflow.md file

    Returns:
        Tuple of (workflow_ir, error_message, source)
    """
    try:
        content = path.read_text(encoding="utf-8")
        result = parse_markdown(content)
        return result.ir, None, "file"
    except MarkdownParseError as e:
        return None, f"Invalid workflow file '{path}': {e}", ""
    except Exception as e:
        return None, f"Failed to read file: {e!s}", ""


def _resolve_by_name(workflow: str) -> tuple[dict[str, Any] | None, str | None, str]:
    """Resolve workflow by name, then file path, with suggestions on failure.

    Args:
        workflow: Workflow name or file path

    Returns:
        Tuple of (workflow_ir, error_message, source)
    """
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

    # Try as file path (without .pflow.md extension)
    path = Path(workflow).expanduser()
    if path.exists() and path.is_file():
        logger.debug(f"Loading workflow from file: {path}")
        return _load_from_file(path)

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
