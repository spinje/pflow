"""Shared registry entry shapes."""

from typing import Any

MCP_CANONICAL_OUTPUT: dict[str, Any] = {
    "key": "result",
    "type": "any",
    "description": "Tool execution result",
}

# pflow-level params every MCP node accepts on top of the tool's inputSchema. MCPNode
# consumes them in prep() and never forwards them to the tool.
MCP_NODE_PARAMS: tuple[dict[str, Any], ...] = (
    {
        "key": "timeout",
        "type": "int",
        "required": False,
        "description": "Timeout in seconds for tool execution (default: 30)",
    },
    {
        "key": "result_format",
        "type": "str",
        "required": False,
        "description": (
            "Set to json_block to parse the single fenced ```json block of a text result as `result` "
            "(error on zero or several blocks)"
        ),
    },
)
