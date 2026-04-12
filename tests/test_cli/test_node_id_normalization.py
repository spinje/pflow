"""Tests for registry node ID normalization."""

from pflow.registry.node_id import normalize_node_id


def test_normalize_node_id_exact_match() -> None:
    available_nodes = {"read-file", "mcp-slack-composio-SLACK_SEND_MESSAGE"}

    assert normalize_node_id("read-file", available_nodes) == "read-file"


def test_normalize_node_id_hyphenated_mcp_tool() -> None:
    available_nodes = {"mcp-slack-composio-SLACK_SEND_MESSAGE"}

    assert (
        normalize_node_id("mcp-slack-composio-SLACK-SEND-MESSAGE", available_nodes)
        == "mcp-slack-composio-SLACK_SEND_MESSAGE"
    )


def test_normalize_node_id_unique_short_form() -> None:
    available_nodes = {"mcp-slack-composio-SLACK_SEND_MESSAGE", "read-file"}

    assert normalize_node_id("SLACK_SEND_MESSAGE", available_nodes) == "mcp-slack-composio-SLACK_SEND_MESSAGE"


def test_normalize_node_id_ambiguous_short_form_returns_none() -> None:
    available_nodes = {
        "mcp-slack-composio-SLACK_SEND_MESSAGE",
        "mcp-other-SLACK_SEND_MESSAGE",
    }

    assert normalize_node_id("SLACK_SEND_MESSAGE", available_nodes) is None


def test_normalize_node_id_invalid_returns_none() -> None:
    available_nodes = {"llm", "shell", "write-file", "mcp-slack-composio-SLACK_SEND_MESSAGE"}

    assert normalize_node_id("nonexistent-node", available_nodes) is None
    assert normalize_node_id("FAKE_MCP_TOOL", available_nodes) is None


def test_normalize_node_id_filesystem_mcp_tools() -> None:
    """Filesystem MCP tools use multi-hyphen server names — exercises the
    reverse-hyphen matching branch (count('-') >= 2)."""
    available_nodes = {"mcp-filesystem-create_directory", "mcp-filesystem-read_file"}

    # Exact match
    assert normalize_node_id("mcp-filesystem-create_directory", available_nodes) == "mcp-filesystem-create_directory"
    # Hyphen variant of tool name (reverse-hyphen branch)
    assert normalize_node_id("mcp-filesystem-create-directory", available_nodes) == "mcp-filesystem-create_directory"
    # Short form with underscores
    assert normalize_node_id("create_directory", available_nodes) == "mcp-filesystem-create_directory"
    # Short form with hyphens
    assert normalize_node_id("create-directory", available_nodes) == "mcp-filesystem-create_directory"


def test_normalize_node_id_case_sensitive() -> None:
    """MCP tool names are case-significant — normalize must NOT lowercase."""
    available_nodes = {"mcp-server-TOOL_NAME"}

    assert normalize_node_id("tool_name", available_nodes) is None
    assert normalize_node_id("TOOL_name", available_nodes) is None
