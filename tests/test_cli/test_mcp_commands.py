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


_TOOL_INFO = {
    "node_name": "mcp-github-create-issue",
    "server": "github",
    "tool": "create-issue",
    "description": "Create an issue",
    "params": [{"key": "repo", "type": "str", "required": True}],
    "outputs": [{"key": "issue", "type": "dict"}],
    "output_schema": {},
    "module": "pflow.nodes.mcp.node",
    "class_name": "MCPNode",
}


def _make_registrar_mock(tool_info: dict | None = None) -> MagicMock:
    """Build a registrar mock with registry.load() for normalize_node_id."""
    registrar = MagicMock()
    registrar.get_tool_info.return_value = tool_info or _TOOL_INFO
    registrar.registry.load.return_value = {"mcp-github-create-issue": {}}
    return registrar


def test_mcp_describe_shows_tool_details() -> None:
    registrar = _make_registrar_mock()

    with patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar):
        result = click.testing.CliRunner().invoke(mcp, ["describe", "mcp-github-create-issue"])

    assert result.exit_code == 0
    assert "Tool: mcp-github-create-issue" in result.output
    assert "Server: github" in result.output
    assert "Parameters:" in result.output


def test_mcp_describe_shows_result_prefixed_output_schema_paths() -> None:
    registrar = _make_registrar_mock({
        **_TOOL_INFO,
        "outputs": [{"key": "result", "type": "any"}],
        "output_schema": {
            "$defs": {
                "Image": {
                    "$ref": "#/$defs/ImageDetails",
                },
                "ImageDetails": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
            "type": "object",
            "properties": {
                "issue_url": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "config": {
                    "oneOf": [
                        {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                        {"type": "null"},
                    ]
                },
                "images": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/Image"},
                },
            },
        },
    })

    with patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar):
        result = click.testing.CliRunner().invoke(mcp, ["describe", "mcp-github-create-issue"])

    assert result.exit_code == 0
    assert "Declared output paths (from server schema):" in result.output
    assert "result.issue_url: string | null" in result.output
    assert "result.config: object | null" in result.output
    assert "result.config.path: string" in result.output
    assert "result.images[0].path: string" in result.output
    assert "Hints only; server declarations may differ" in result.output


def test_mcp_describe_bounds_recursive_and_wide_output_schemas() -> None:
    properties = {f"field_{index}": {"type": "string"} for index in range(120)}
    properties["children"] = {"type": "array", "items": {"$ref": "#"}}
    registrar = _make_registrar_mock({
        **_TOOL_INFO,
        "outputs": [{"key": "result", "type": "any"}],
        "output_schema": {"properties": properties},
    })

    with patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar):
        result = click.testing.CliRunner().invoke(mcp, ["describe", "mcp-github-create-issue"])

    assert result.exit_code == 0
    assert "result.field_0: string" in result.output
    assert "result.field_99: string" in result.output
    assert "result.field_100: string" not in result.output
    assert "... (truncated)" in result.output


def test_mcp_describe_does_not_claim_truncation_at_exact_path_limit() -> None:
    registrar = _make_registrar_mock({
        **_TOOL_INFO,
        "outputs": [{"key": "result", "type": "any"}],
        "output_schema": {
            "type": "object",
            "properties": {f"field_{index}": {"type": "string"} for index in range(100)},
        },
    })

    with patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar):
        result = click.testing.CliRunner().invoke(mcp, ["describe", "mcp-github-create-issue"])

    assert result.exit_code == 0
    assert "result.field_99: string" in result.output
    assert "... (truncated)" not in result.output


def test_mcp_describe_bounds_self_referencing_output_schema_depth() -> None:
    registrar = _make_registrar_mock({
        **_TOOL_INFO,
        "outputs": [{"key": "result", "type": "any"}],
        "output_schema": {
            "type": "object",
            "properties": {"children": {"type": "array", "items": {"$ref": "#"}}},
        },
    })

    with patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar):
        result = click.testing.CliRunner().invoke(mcp, ["describe", "mcp-github-create-issue"])

    assert result.exit_code == 0
    assert "result.children[0].children[0]" in result.output
    assert "... (truncated)" in result.output


def test_mcp_describe_normalizes_hyphen_to_underscore() -> None:
    """Hyphenated tool names should resolve via normalize_node_id."""
    registrar = MagicMock()
    registrar.registry.load.return_value = {"mcp-slack-SLACK_SEND_MESSAGE": {}}
    registrar.get_tool_info.return_value = {
        **_TOOL_INFO,
        "node_name": "mcp-slack-SLACK_SEND_MESSAGE",
        "tool": "SLACK_SEND_MESSAGE",
        "server": "slack",
    }

    with patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar):
        # User types hyphens instead of underscores
        result = click.testing.CliRunner().invoke(mcp, ["describe", "mcp-slack-SLACK-SEND-MESSAGE"])

    assert result.exit_code == 0
    assert "SLACK_SEND_MESSAGE" in result.output


def test_mcp_describe_resolves_short_form() -> None:
    """Unique short-form suffix should resolve to the full ID."""
    registrar = MagicMock()
    registrar.registry.load.return_value = {"mcp-slack-SLACK_SEND_MESSAGE": {}}
    registrar.get_tool_info.return_value = {
        **_TOOL_INFO,
        "node_name": "mcp-slack-SLACK_SEND_MESSAGE",
        "tool": "SLACK_SEND_MESSAGE",
        "server": "slack",
    }

    with patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar):
        result = click.testing.CliRunner().invoke(mcp, ["describe", "SLACK_SEND_MESSAGE"])

    assert result.exit_code == 0
    assert "SLACK_SEND_MESSAGE" in result.output


def test_mcp_describe_unknown_tool_shows_suggestions() -> None:
    """When a tool is not found, mcp describe should show similar tools
    so agents can self-correct."""
    registrar = MagicMock()
    registrar.registry.load.return_value = {"mcp-github-create-issue": {}, "mcp-github-list-repos": {}}
    registrar.get_tool_info.return_value = None
    registrar.list_registered_tools.return_value = ["mcp-github-create-issue", "mcp-github-list-repos"]

    with patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar):
        result = click.testing.CliRunner().invoke(mcp, ["describe", "mcp-github-create-pr"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()
    # Should suggest similar tools (substring match on "github-create")
    assert "mcp-github-create-issue" in result.output


def test_mcp_list_keyword_no_match_shows_guidance() -> None:
    """When keyword filter matches nothing, mcp list should tell agents
    what to try instead."""
    registrar = MagicMock()
    registrar.registry.load.return_value = {
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
        MockManager.return_value.list_servers.return_value = ["github"]
        result = click.testing.CliRunner().invoke(mcp, ["list", "nonexistent-tool"])

    assert "No MCP tools match" in result.output


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
