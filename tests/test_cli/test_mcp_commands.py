"""Tests for the reworked `pflow mcp` namespace."""

from unittest.mock import MagicMock, patch

import click.testing

from pflow.cli.commands.mcp import mcp
from pflow.registry.discovery import ComponentSelection


def test_mcp_servers_lists_configured_servers() -> None:
    with patch("pflow.cli.commands.mcp.MCPServerManager") as MockManager:
        MockManager.return_value.get_all_servers.return_value = {
            "slack": {"type": "http", "url": "https://example.com/slack"},
        }
        result = click.testing.CliRunner().invoke(mcp, ["servers"])

    assert result.exit_code == 0
    assert "Configured MCP servers:" in result.output
    assert "slack" in result.output


def test_mcp_list_without_keywords_shows_grouped_summary() -> None:
    registrar = MagicMock()
    registrar.registry.load.return_value = {
        "mcp-slack-send-message": {
            "interface": {"description": "Send a message", "mcp_metadata": {"server": "slack", "tool": "send-message"}}
        },
        "mcp-github-create-issue": {
            "interface": {
                "description": "Create an issue",
                "mcp_metadata": {"server": "github", "tool": "create-issue"},
            }
        },
    }

    with (
        patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar),
        patch("pflow.cli.commands.mcp.MCPServerManager") as MockManager,
    ):
        MockManager.return_value.list_servers.return_value = ["slack", "github"]
        result = click.testing.CliRunner().invoke(mcp, ["list"])

    assert result.exit_code == 0
    assert "MCP Tools (2 total across 2 servers)" in result.output
    assert "slack (1 tools)" in result.output
    assert "github (1 tools)" in result.output


def test_mcp_list_with_keywords_filters_tools() -> None:
    registrar = MagicMock()
    registrar.registry.load.return_value = {
        "mcp-slack-send-message": {
            "interface": {"description": "Send a message", "mcp_metadata": {"server": "slack", "tool": "send-message"}}
        },
        "mcp-github-create-issue": {
            "interface": {
                "description": "Create an issue",
                "mcp_metadata": {"server": "github", "tool": "create-issue"},
            }
        },
    }

    with (
        patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar),
        patch("pflow.cli.commands.mcp.MCPServerManager") as MockManager,
    ):
        MockManager.return_value.list_servers.return_value = ["slack", "github"]
        result = click.testing.CliRunner().invoke(mcp, ["list", "slack", "send"])

    assert result.exit_code == 0
    assert "Matching MCP tools (1 results):" in result.output
    assert "mcp-slack-send-message" in result.output
    assert "mcp-github-create-issue" not in result.output


def test_mcp_find_uses_filtered_registry_metadata() -> None:
    registrar = MagicMock()
    registrar.registry.load.return_value = {
        "mcp-slack-send-message": {
            "interface": {"description": "Send a message", "mcp_metadata": {"server": "slack", "tool": "send-message"}}
        },
    }
    selection = ComponentSelection(
        node_ids=["mcp-slack-send-message"],
        reasoning="Slack send tool fits",
        component_context="",
    )

    with (
        patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar),
        patch("pflow.registry.discovery.find_components", return_value=selection) as mock_discover,
    ):
        result = click.testing.CliRunner().invoke(mcp, ["find", "send a slack message"])

    assert result.exit_code == 0
    assert "mcp-slack-send-message" in result.output
    assert "Reasoning: Slack send tool fits" in result.output
    assert "registry_metadata" in mock_discover.call_args[1]


def test_mcp_describe_shows_tool_details() -> None:
    registrar = MagicMock()
    registrar.get_tool_info.return_value = {
        "node_name": "mcp-github-create-issue",
        "server": "github",
        "tool": "create-issue",
        "description": "Create an issue",
        "params": [{"key": "repo", "type": "str", "required": True}],
        "outputs": [{"key": "issue", "type": "dict"}],
        "module": "pflow.nodes.mcp.node",
        "class_name": "MCPNode",
    }

    with patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar):
        result = click.testing.CliRunner().invoke(mcp, ["describe", "mcp-github-create-issue"])

    assert result.exit_code == 0
    assert "Tool: mcp-github-create-issue" in result.output
    assert "Server: github" in result.output
    assert "Parameters:" in result.output


def test_removed_mcp_tools_and_info_commands_fail() -> None:
    runner = click.testing.CliRunner()

    tools_result = runner.invoke(mcp, ["tools"])
    info_result = runner.invoke(mcp, ["info", "whatever"])

    assert tools_result.exit_code != 0
    assert "'mcp tools' command was removed" in tools_result.output
    assert "pflow mcp list" in tools_result.output
    assert info_result.exit_code != 0
    assert "'mcp info' command was removed" in info_result.output
    assert "pflow mcp describe" in info_result.output
