"""Error context utilities for enriching error messages with upstream node data.

This module provides utilities for extracting diagnostic context from upstream
nodes when a downstream node fails. The primary use case is showing stderr
from shell nodes when a batch or template resolution error occurs.

Note: While primarily designed for shell nodes, these utilities work for any
node type that writes stderr to the shared store.
"""

import re
from typing import Any

from pflow.runtime.template_resolver import TemplateResolver


def extract_node_ids_from_template(template: str) -> set[str]:
    """Extract base node IDs from template variables.

    Args:
        template: Template string containing ${...} references

    Returns:
        Set of node IDs (e.g., {"extract-urls"} from "${extract-urls.stdout}")

    Examples:
        >>> extract_node_ids_from_template("${node.stdout}")
        {'node'}
        >>> extract_node_ids_from_template("${a.x} and ${b.y}")
        {'a', 'b'}
        >>> extract_node_ids_from_template("${data[0].name}")
        {'data'}
    """
    variables = TemplateResolver.extract_variables(template)
    node_ids = set()
    for var in variables:
        # Split on '.' or '[' to get base node ID
        # e.g., "extract-urls.stdout" -> "extract-urls"
        # e.g., "data[0].name" -> "data"
        base_id = re.split(r"[\.\[]", var)[0]
        node_ids.add(base_id)
    return node_ids


def get_upstream_stderr(
    template: str,
    shared: dict[str, Any],
    max_stderr_len: int = 500,
) -> str | None:
    """Get stderr context from upstream nodes referenced in a template.

    When a downstream node fails because of unexpected upstream output,
    this function extracts stderr from referenced nodes to help diagnose
    the root cause. Works for any node type that writes stderr to shared store
    (primarily shell nodes, but also any future node types with stderr output).

    Args:
        template: Template string with ${node.field} references
        shared: Shared store containing node outputs
        max_stderr_len: Maximum characters of stderr to include per node

    Returns:
        Formatted stderr context string, or None if no relevant stderr found

    Example output:
        "\\n\\n  ⚠️  Upstream node 'extract-urls' stderr:\\n     grep: invalid option -- P\\n     usage: grep ..."
    """
    node_ids = extract_node_ids_from_template(template)

    stderr_contexts = []
    for node_id in sorted(node_ids):  # Sort for deterministic output
        node_output = shared.get(node_id, {})
        if not isinstance(node_output, dict):
            continue

        stderr = node_output.get("stderr", "")
        if not stderr or not isinstance(stderr, str) or not stderr.strip():
            continue

        # Truncate if too long
        stderr_display = stderr.strip()
        if len(stderr_display) > max_stderr_len:
            stderr_display = stderr_display[:max_stderr_len] + "..."

        # Indent multi-line stderr for readability
        indented_stderr = stderr_display.replace("\n", "\n     ")

        stderr_contexts.append(f"  ⚠️  Upstream node '{node_id}' stderr:\n     {indented_stderr}")

    if stderr_contexts:
        return "\n\n" + "\n\n".join(stderr_contexts)
    return None
