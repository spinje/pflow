"""Shared validation utilities for template validation.

Provides common infrastructure used across multiple validation modules:
- ValidationWarning dataclass
- Display constants
- Path splitting, sanitization, and suggestion matching
- Output structure flattening
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Display limits for error messages - balances information vs overwhelming output
MAX_DISPLAYED_FIELDS = 20  # Fits in ~25 terminal lines with formatting
MAX_DISPLAYED_SUGGESTIONS = 3  # Cognitive limit for processing alternatives
MAX_FLATTEN_DEPTH = 5  # Prevent infinite recursion on circular refs


@dataclass
class ValidationWarning:
    """Pre-execution warning about a node or template.

    General-purpose warning type used by all validation steps.
    Template warnings include the template field; lint warnings
    (e.g., cache advisories) set template to None.
    """

    node_id: str  # Node this warning applies to
    message: str  # Human-readable explanation
    template: str | None = None  # Template string (for template warnings only)


def split_template_path(template: str) -> list[str]:
    """Split template path on dots, preserving dots inside ${...}.

    Standard str.split(".") breaks nested templates like ${item.field}
    inside array brackets. This function correctly handles:

    - drafts.results[${item.draft_index}].response
      -> ['drafts', 'results[${item.draft_index}]', 'response']

    - node.data[${__index__}].field
      -> ['node', 'data[${__index__}]', 'field']

    Args:
        template: Template path string (without ${} wrapper)

    Returns:
        List of path components with nested templates preserved
    """
    parts: list[str] = []
    current = ""
    depth = 0  # Track nesting level of ${...}

    i = 0
    while i < len(template):
        if template[i : i + 2] == "${":
            depth += 1
            current += template[i : i + 2]
            i += 2
        elif template[i] == "}" and depth > 0:
            depth -= 1
            current += template[i]
            i += 1
        elif template[i] == "." and depth == 0:
            if current:
                parts.append(current)
            current = ""
            i += 1
        else:
            current += template[i]
            i += 1

    if current:
        parts.append(current)

    return parts


def get_node_ids(workflow_ir: dict[str, Any]) -> set[str]:
    """Extract all node IDs from the workflow.

    Args:
        workflow_ir: The workflow IR

    Returns:
        Set of all node IDs in the workflow
    """
    return {node.get("id") for node in workflow_ir.get("nodes", []) if node.get("id")}


def sanitize_for_display(value: str, max_length: int = 100) -> str:
    """Sanitize string for safe display in error messages.

    Removes control characters and limits length to prevent:
    - Terminal escape sequences
    - Log injection (newlines, carriage returns)
    - Information disclosure

    Args:
        value: String to sanitize (node_id, template variable, etc.)
        max_length: Maximum length before truncation

    Returns:
        Sanitized string safe for error messages
    """
    # Remove non-printable characters AND newlines/carriage returns
    # Allow only printable characters, excluding control chars that enable log injection
    sanitized = "".join(c for c in value if c.isprintable() and c not in ("\n", "\r", "\t", "\x0b", "\x0c"))

    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."

    return sanitized


def flatten_output_structure(  # noqa: C901
    base_key: str,
    base_type: str,
    structure: dict[str, Any],
    _current_path: str = "",
    _paths: list[tuple[str, str]] | None = None,
    _depth: int = 0,
    _max_depth: int = MAX_FLATTEN_DEPTH,
) -> list[tuple[str, str]]:
    """Recursively flatten output structure to list of (path, type) tuples.

    Note: This function has inherent complexity (noqa: C901) due to recursive
    tree traversal of arbitrary nested structures. Refactoring would require
    breaking the recursion pattern, which could reduce readability without
    meaningful benefit. The complexity is managed through:
    - Clear function boundaries (prep/traverse/handle)
    - Depth limiting to prevent infinite recursion
    - Comprehensive docstrings
    - Type hints for all parameters

    Args:
        base_key: The base output key (e.g., "result")
        base_type: Type of the base key (e.g., "dict")
        structure: Nested structure dictionary
        _current_path: Current path during recursion (internal)
        _paths: Accumulated paths (internal)
        _depth: Current recursion depth (internal)
        _max_depth: Maximum recursion depth to prevent infinite loops

    Returns:
        List of (path, type) tuples representing all accessible paths

    Example:
        Input: base_key="result", base_type="dict", structure={
            "messages": {"type": "array", "items": {"type": "dict", "structure": {...}}}
        }
        Output: [
            ("result", "dict"),
            ("result.messages", "array"),
            ("result.messages[0].text", "string"),
            ...
        ]
    """
    if _paths is None:
        _paths = []

    # Prevent infinite recursion on malformed structures
    if _depth > _max_depth:
        return _paths

    # Add the base path first
    if _current_path == "":
        _paths.append((base_key, base_type))
        _current_path = base_key

    # Recursively traverse structure
    if structure and isinstance(structure, dict):
        for field_name, field_info in structure.items():
            field_path = f"{_current_path}.{field_name}"

            if isinstance(field_info, dict):
                field_type = field_info.get("type", "any")
                _paths.append((field_path, field_type))

                # Handle arrays with example index
                if field_type == "array" and "items" in field_info:
                    items = field_info["items"]
                    if isinstance(items, dict):
                        item_type = items.get("type", "any")
                        item_path = f"{field_path}[0]"
                        _paths.append((item_path, item_type))

                        # Recurse into array item structure
                        if "structure" in items and isinstance(items["structure"], dict):
                            flatten_output_structure(
                                base_key="",  # Not used in recursion
                                base_type="",
                                structure=items["structure"],
                                _current_path=item_path,
                                _paths=_paths,
                                _depth=_depth + 1,
                                _max_depth=_max_depth,
                            )

                # Recurse into nested dict structure
                elif "structure" in field_info and isinstance(field_info["structure"], dict):
                    flatten_output_structure(
                        base_key="",
                        base_type="",
                        structure=field_info["structure"],
                        _current_path=field_path,
                        _paths=_paths,
                        _depth=_depth + 1,
                        _max_depth=_max_depth,
                    )
            elif isinstance(field_info, str):
                # Direct type string (legacy format)
                _paths.append((field_path, field_info))

    return _paths


def find_similar_paths(attempted_key: str, available_paths: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Find paths similar to the attempted key.

    Uses simple substring matching for MVP.

    Args:
        attempted_key: The key user tried to access (e.g., "msg")
        available_paths: List of (path, type) tuples

    Returns:
        List of (path, type) tuples that match, sorted by relevance

    Example:
        attempted_key="msg"
        available_paths=[("result", "dict"), ("result.messages", "array")]
        returns=[("result.messages", "array")]
    """
    attempted_lower = attempted_key.lower()
    matches = []

    for path, path_type in available_paths:
        # Extract just the last component of the path for matching
        last_component = path.split(".")[-1].split("[")[0]  # Handle array notation

        # Substring match (case-insensitive)
        if attempted_lower in last_component.lower():
            # Calculate match quality (longer substring match = better)
            match_quality = len(attempted_lower) / len(last_component) if last_component else 0
            matches.append((path, path_type, match_quality))

    # Sort by match quality (best matches first), then alphabetically
    matches.sort(key=lambda x: (-x[2], x[0]))

    # Return just the (path, type) tuples, top 3 matches
    return [(path, path_type) for path, path_type, _ in matches[:MAX_DISPLAYED_SUGGESTIONS]]


def build_paths_from_entries(node_entries: dict[str, Any]) -> list[tuple[str, str]]:
    """Build flattened (path, type) list from node_outputs entries.

    Args:
        node_entries: Dict of output_key -> output_info for a single node

    Returns:
        List of (path, type) tuples for display
    """
    all_paths: list[tuple[str, str]] = []
    for key, info in node_entries.items():
        output_type = info.get("type", "any")
        all_paths.append((key, output_type))

        # Flatten nested structure if present
        structure = info.get("structure", {})
        if structure and isinstance(structure, dict):
            nested = flatten_output_structure(base_key=key, base_type=output_type, structure=structure)
            # Skip first entry (base key already added)
            all_paths.extend(nested[1:])

        # Flatten items structure for arrays (e.g., results array)
        items_info = info.get("items", {})
        if items_info and isinstance(items_info, dict):
            item_type = items_info.get("type", "any")
            item_path = f"{key}[0]"
            all_paths.append((item_path, item_type))

            items_structure = items_info.get("structure", {})
            if items_structure and isinstance(items_structure, dict):
                nested = flatten_output_structure(
                    base_key="",
                    base_type="",
                    structure=items_structure,
                    _current_path=item_path,
                    _paths=[],
                    _depth=0,
                )
                all_paths.extend(nested)

    return all_paths
