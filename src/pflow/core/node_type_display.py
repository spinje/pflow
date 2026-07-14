"""Short display tags for Python node-class names.

Used by report renderers and the dry-run plan formatter so both surfaces use
the same vocabulary (llm, shell, http, ...) when summarising what kind of work
ran. Unknown class names fall back to a lowercased form of the class name.
"""

NODE_TYPE_TAGS: dict[str, str] = {
    "LLMNode": "llm",
    "AgentNode": "agent",
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


def is_llm_node_type(node_type_name: str) -> bool:
    """Return whether ``node_type_name`` is pflow's built-in LLM node.

    Lives here (a dependency-free ``core`` module that already special-cases
    ``"LLMNode"``) so trace-shape code can import it without pulling in the
    ``runtime.engine`` package — see ``runtime/workflow_trace.py``.
    """
    return node_type_name == "LLMNode"


def is_model_node_type(node_type_name: str) -> bool:
    """Return whether a node has model prompt/usage trace semantics."""
    return node_type_name in {"LLMNode", "AgentNode"}
