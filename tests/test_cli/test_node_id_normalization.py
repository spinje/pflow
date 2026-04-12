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
