"""Short display tags for Python node-class names.

Used by report renderers and the dry-run plan formatter so both surfaces use
the same vocabulary (llm, shell, http, ...) when summarising what kind of work
ran. Unknown class names fall back to a lowercased form of the class name.
"""

NODE_TYPE_TAGS: dict[str, str] = {
    "LLMNode": "llm",
    "ClaudeCodeNode": "claude",
    "HttpNode": "http",
    "ShellNode": "shell",
    "MCPNode": "mcp",
    "PythonCodeNode": "code",
    "ReadFileNode": "read-file",
    "WriteFileNode": "write-file",
    "CopyFileNode": "copy-file",
    "MoveFileNode": "move-file",
    "DeleteFileNode": "delete-file",
    "WorkflowExecutor": "workflow",
}


def node_type_tag(node_type: str) -> str:
    """Return short display tag for a Python node class name."""
    return NODE_TYPE_TAGS.get(node_type, node_type.lower())
