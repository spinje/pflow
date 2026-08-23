"""Tests for the reworked `pflow mcp` namespace."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import click.testing

from pflow.cli.commands.mcp import mcp
from pflow.mcp import MCPRegistrar, MCPServerManager
from pflow.mcp.sync_state import MCP_SERVER_FINGERPRINTS_KEY, fingerprint_server_config
from pflow.registry import Registry
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


def _manual_sync_components(tmp_path: Path, configs: dict[str, dict]):
    manager = MCPServerManager(config_path=tmp_path / "mcp-servers.json")
    manager.save({"mcpServers": configs})
    registry = Registry(registry_path=tmp_path / "registry.json")
    registry._save_with_metadata({})
    discovery = MagicMock()
    registrar = MCPRegistrar(registry=registry, manager=manager, discovery=discovery)
    registrar._settings_manager = MagicMock()
    registrar._settings_manager.should_include_node.return_value = True
    return manager, registry, discovery, registrar


def _mcp_entry(registrar: MCPRegistrar, server: str, tool: str) -> dict:
    return registrar._create_registry_entry(server, {"name": tool})


def test_manual_single_sync_replaces_tools_and_advances_fingerprint(tmp_path: Path) -> None:
    configs = {"one": {"command": "one"}}
    manager, registry, discovery, registrar = _manual_sync_components(tmp_path, configs)
    registry.save({"mcp-one-old": _mcp_entry(registrar, "one", "old")})
    discovery.discover_tools.return_value = [{"name": "new"}]

    with (
        patch("pflow.cli.commands.mcp.MCPServerManager", return_value=manager),
        patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar),
    ):
        result = click.testing.CliRunner().invoke(mcp, ["sync", "one"])

    assert result.exit_code == 0
    assert "mcp-one-new" in registry.load(include_filtered=True)
    assert "mcp-one-old" not in registry.load(include_filtered=True)
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == {"one": fingerprint_server_config(configs["one"])}


def test_manual_single_sync_failure_preserves_tools_and_fingerprint(tmp_path: Path) -> None:
    configs = {"one": {"command": "one"}}
    manager, registry, discovery, registrar = _manual_sync_components(tmp_path, configs)
    old = {"mcp-one-old": _mcp_entry(registrar, "one", "old")}
    registry.save(old, metadata_updates={MCP_SERVER_FINGERPRINTS_KEY: {"one": "old"}})
    discovery.discover_tools.side_effect = RuntimeError("temporarily unavailable")

    with (
        patch("pflow.cli.commands.mcp.MCPServerManager", return_value=manager),
        patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar),
    ):
        result = click.testing.CliRunner().invoke(mcp, ["sync", "one"])

    assert result.exit_code == 1
    assert registry.load(include_filtered=True) == old
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == {"one": "old"}


def test_manual_sync_all_advances_success_and_preserves_failure(tmp_path: Path) -> None:
    configs = {"good": {"command": "good"}, "bad": {"command": "bad"}}
    manager, registry, discovery, registrar = _manual_sync_components(tmp_path, configs)
    registry.save(
        {
            "mcp-good-old": _mcp_entry(registrar, "good", "old"),
            "mcp-bad-old": _mcp_entry(registrar, "bad", "old"),
        },
        metadata_updates={MCP_SERVER_FINGERPRINTS_KEY: {"good": "old-good", "bad": "old-bad"}},
    )

    def discover(server_name, **_kwargs):
        if server_name == "bad":
            raise RuntimeError("down")
        return [{"name": "new"}]

    discovery.discover_tools.side_effect = discover
    with (
        patch("pflow.cli.commands.mcp.MCPServerManager", return_value=manager),
        patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar),
        patch.object(manager, "list_servers", side_effect=AssertionError("forced all must use coordinator snapshot")),
    ):
        result = click.testing.CliRunner().invoke(mcp, ["sync", "--all"])

    assert result.exit_code == 0
    assert set(registry.load(include_filtered=True)) == {"mcp-good-new", "mcp-bad-old"}
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == {
        "good": fingerprint_server_config(configs["good"]),
        "bad": "old-bad",
    }


def test_manual_single_config_change_during_discovery_aborts_without_registry_write(tmp_path: Path) -> None:
    configs = {"one": {"command": "old"}}
    manager, registry, discovery, registrar = _manual_sync_components(tmp_path, configs)
    old_nodes = {"mcp-one-old": _mcp_entry(registrar, "one", "old")}
    registry.save(old_nodes, metadata_updates={MCP_SERVER_FINGERPRINTS_KEY: {"one": "old"}})

    def discover(*_args, **_kwargs):
        manager.save({"mcpServers": {"one": {"command": "changed"}}})
        return [{"name": "observed"}]

    discovery.discover_tools.side_effect = discover
    with (
        patch("pflow.cli.commands.mcp.MCPServerManager", return_value=manager),
        patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar),
        patch.object(registry, "save", wraps=registry.save) as save,
    ):
        result = click.testing.CliRunner().invoke(mcp, ["sync", "one"])

    assert result.exit_code == 1
    save.assert_not_called()
    assert registry.load(include_filtered=True) == old_nodes
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == {"one": "old"}


def test_manual_single_config_disappears_before_discovery_reports_error(tmp_path: Path) -> None:
    configs = {"one": {"command": "one"}}
    manager, _, discovery, registrar = _manual_sync_components(tmp_path, configs)

    def remove_after_read(name: str):
        manager.config_path.unlink()
        return configs[name]

    with (
        patch("pflow.cli.commands.mcp.MCPServerManager", return_value=manager),
        patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar),
        patch.object(manager, "get_server", side_effect=remove_after_read),
    ):
        result = click.testing.CliRunner().invoke(mcp, ["sync", "one"])

    assert result.exit_code == 1
    assert "MCP configuration is no longer available" in result.output
    assert "list index out of range" not in result.output
    discovery.discover_tools.assert_not_called()


def test_manual_sync_all_missing_config_preserves_registry(tmp_path: Path) -> None:
    manager, registry, discovery, registrar = _manual_sync_components(tmp_path, {"old": {"command": "old"}})
    old_nodes = {"mcp-old-tool": _mcp_entry(registrar, "old", "tool")}
    registry.save(old_nodes, metadata_updates={MCP_SERVER_FINGERPRINTS_KEY: {"old": "old"}})
    manager.config_path.unlink()

    with (
        patch("pflow.cli.commands.mcp.MCPServerManager", return_value=manager),
        patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar),
    ):
        result = click.testing.CliRunner().invoke(mcp, ["sync", "--all"])

    assert result.exit_code == 0
    assert "No MCP server configuration found" in result.output
    discovery.discover_tools.assert_not_called()
    assert registry.load(include_filtered=True) == old_nodes
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == {"old": "old"}


def test_manual_sync_all_explicit_empty_config_reports_no_servers(tmp_path: Path) -> None:
    manager, _, discovery, registrar = _manual_sync_components(tmp_path, {})

    with (
        patch("pflow.cli.commands.mcp.MCPServerManager", return_value=manager),
        patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar),
    ):
        result = click.testing.CliRunner().invoke(mcp, ["sync", "--all"])

    assert result.exit_code == 0
    assert "No MCP servers configured" in result.output
    discovery.discover_tools.assert_not_called()


def test_remove_uses_exact_owner_and_removes_zero_tool_fingerprint(tmp_path: Path) -> None:
    configs = {"foo": {"command": "foo"}, "foo-bar": {"command": "foo-bar"}}
    manager, registry, _, registrar = _manual_sync_components(tmp_path, configs)
    registry.save(
        {"mcp-foo-bar-tool": _mcp_entry(registrar, "foo-bar", "tool")},
        metadata_updates={MCP_SERVER_FINGERPRINTS_KEY: {"foo": "foo", "foo-bar": "foo-bar"}},
    )

    with (
        patch("pflow.cli.commands.mcp.MCPServerManager", return_value=manager),
        patch("pflow.cli.commands.mcp.MCPRegistrar", return_value=registrar),
    ):
        result = click.testing.CliRunner().invoke(mcp, ["remove", "foo", "--force"])

    assert result.exit_code == 0
    assert registrar.list_registered_tools("foo-bar", include_filtered=True) == ["mcp-foo-bar-tool"]
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == {"foo-bar": "foo-bar"}
    assert manager.list_servers() == ["foo-bar"]
