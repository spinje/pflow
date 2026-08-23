"""Persistence-level tests for workflow-start MCP synchronization."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pflow.cli.mcp_sync import _auto_discover_mcp_servers
from pflow.mcp import MCPRegistrar, MCPServerManager
from pflow.mcp.sync_state import MCP_SERVER_FINGERPRINTS_KEY, fingerprint_server_configs
from pflow.registry import Registry


def _tool(name: str) -> dict:
    return {"name": name, "description": name}


def _setup(tmp_path: Path, configs: dict[str, dict]) -> tuple[MCPServerManager, Registry, Mock]:
    manager = MCPServerManager(config_path=tmp_path / "mcp-servers.json")
    manager.save({"mcpServers": configs})
    registry = Registry(registry_path=tmp_path / "registry.json")
    registry._save_with_metadata({})
    discovery = Mock()
    discovery.convert_to_pflow_params.return_value = []
    return manager, registry, discovery


def _run(
    manager: MCPServerManager,
    registry: Registry,
    discovery: Mock,
    *,
    interactive: bool = False,
    verbose: bool = False,
) -> None:
    controller = Mock()
    controller.is_interactive.return_value = interactive
    ctx = Mock(obj={})
    with (
        patch("pflow.cli.mcp_sync._get_output_controller", return_value=controller),
        patch("pflow.mcp.MCPServerManager", return_value=manager),
        patch("pflow.registry.Registry", return_value=registry),
        patch("pflow.mcp.MCPDiscovery", return_value=discovery),
    ):
        _auto_discover_mcp_servers(ctx, verbose=verbose)


def _entry(registry: Registry, server: str, tool: str) -> dict:
    registrar = MCPRegistrar(registry=registry)
    return registrar._create_registry_entry(server, _tool(tool))


def test_bootstrap_adds_servers_and_unchanged_second_run_does_nothing(tmp_path: Path) -> None:
    configs = {"one": {"command": "one"}, "two": {"command": "two"}}
    manager, registry, discovery = _setup(tmp_path, configs)
    discovery.discover_tools.side_effect = [[_tool("first")], [_tool("second")]]

    _run(manager, registry, discovery)
    with patch.object(registry, "save", wraps=registry.save) as save:
        _run(manager, registry, discovery)

    assert [call.args[0] for call in discovery.discover_tools.call_args_list] == ["one", "two"]
    save.assert_not_called()
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == fingerprint_server_configs(configs)
    assert set(registry.load(include_filtered=True)) == {"mcp-one-first", "mcp-two-second"}


@pytest.mark.parametrize(
    ("initial", "changed"),
    [
        ({"command": "old"}, {"command": "new"}),
        ({"command": "cmd", "args": ["old"]}, {"command": "cmd", "args": ["new"]}),
        ({"command": "cmd", "env": {"TOKEN": "${OLD}"}}, {"command": "cmd", "env": {"TOKEN": "${NEW}"}}),
        ({"type": "http", "url": "https://old"}, {"type": "http", "url": "https://new"}),
        (
            {"type": "http", "url": "https://same", "headers": {"Authorization": "${OLD}"}},
            {"type": "http", "url": "https://same", "headers": {"Authorization": "${NEW}"}},
        ),
    ],
)
def test_raw_config_value_change_contacts_only_changed_server(
    tmp_path: Path,
    initial: dict,
    changed: dict,
) -> None:
    configs = {"target": initial, "peer": {"command": "peer"}}
    manager, registry, discovery = _setup(tmp_path, configs)
    target_attempts = 0

    def discover(server_name, **_kwargs):
        nonlocal target_attempts
        if server_name == "peer":
            return [_tool("peer")]
        target_attempts += 1
        return [_tool("old" if target_attempts == 1 else "new")]

    discovery.discover_tools.side_effect = discover
    _run(manager, registry, discovery)
    manager.save({"mcpServers": {"target": changed, "peer": configs["peer"]}})

    _run(manager, registry, discovery)

    calls = [call.args[0] for call in discovery.discover_tools.call_args_list]
    assert set(calls[:2]) == {"target", "peer"}
    assert calls[2:] == ["target"]
    assert "mcp-target-new" in registry.load(include_filtered=True)


def test_formatting_and_key_order_only_rewrite_contacts_none_and_writes_nothing(tmp_path: Path) -> None:
    configs = {"one": {"command": "cmd", "args": ["a"], "env": {"B": "2", "A": "1"}}}
    manager, registry, discovery = _setup(tmp_path, configs)
    discovery.discover_tools.return_value = [_tool("tool")]
    _run(manager, registry, discovery)
    discovery.reset_mock()
    manager.config_path.write_text(
        json.dumps({"mcpServers": {"one": {"env": {"A": "1", "B": "2"}, "args": ["a"], "command": "cmd"}}}),
        encoding="utf-8",
    )

    with patch.object(registry, "save", wraps=registry.save) as save:
        _run(manager, registry, discovery)

    discovery.discover_tools.assert_not_called()
    save.assert_not_called()


def test_resolved_environment_change_does_not_change_raw_config_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configs = {"one": {"command": "cmd", "env": {"TOKEN": "${TOKEN}"}}}
    manager, registry, discovery = _setup(tmp_path, configs)
    discovery.discover_tools.return_value = [_tool("tool")]
    monkeypatch.setenv("TOKEN", "first-secret")
    _run(manager, registry, discovery)
    discovery.reset_mock()
    monkeypatch.setenv("TOKEN", "rotated-secret")

    with patch.object(registry, "save", wraps=registry.save) as save:
        _run(manager, registry, discovery)

    discovery.discover_tools.assert_not_called()
    save.assert_not_called()


def test_partial_failure_retries_only_failed_server(tmp_path: Path) -> None:
    configs = {"good": {"command": "good"}, "bad": {"command": "bad"}}
    manager, registry, discovery = _setup(tmp_path, configs)
    registry.save({
        "mcp-good-old": _entry(registry, "good", "old"),
        "mcp-bad-old": _entry(registry, "bad", "old"),
    })
    bad_attempts = 0

    def discover(server_name, **_kwargs):
        nonlocal bad_attempts
        if server_name == "good":
            return [_tool("new")]
        bad_attempts += 1
        if bad_attempts == 1:
            raise RuntimeError("down")
        return [_tool("recovered")]

    discovery.discover_tools.side_effect = discover

    _run(manager, registry, discovery)
    after_failure = registry.load(include_filtered=True)
    _run(manager, registry, discovery)

    assert set(after_failure) == {"mcp-good-new", "mcp-bad-old"}
    calls = [call.args[0] for call in discovery.discover_tools.call_args_list]
    assert set(calls[:2]) == {"good", "bad"}
    assert calls[2:] == ["bad"]
    assert set(registry.load(include_filtered=True)) == {"mcp-good-new", "mcp-bad-recovered"}


def test_total_failure_preserves_state_and_retries_all(tmp_path: Path) -> None:
    configs = {"one": {"command": "one"}, "two": {"command": "two"}}
    manager, registry, discovery = _setup(tmp_path, configs)
    old_nodes = {
        "mcp-one-old": _entry(registry, "one", "old"),
        "mcp-two-old": _entry(registry, "two", "old"),
    }
    registry.save(old_nodes)
    discovery.discover_tools.side_effect = [
        RuntimeError("one down"),
        RuntimeError("two down"),
        RuntimeError("one still down"),
        RuntimeError("two still down"),
    ]

    _run(manager, registry, discovery)
    _run(manager, registry, discovery)

    assert registry.load(include_filtered=True) == old_nodes
    assert [call.args[0] for call in discovery.discover_tools.call_args_list] == ["one", "two", "one", "two"]


def test_empty_success_and_removed_overlapping_server_names(tmp_path: Path) -> None:
    configs = {"foo": {"command": "foo"}, "foo-bar": {"command": "foo-bar"}}
    manager, registry, discovery = _setup(tmp_path, configs)
    discovery.discover_tools.side_effect = [[_tool("old")], [_tool("peer")], []]
    _run(manager, registry, discovery)
    manager.save({"mcpServers": {"foo": {"command": "changed"}}})

    _run(manager, registry, discovery)

    assert registry.load(include_filtered=True) == {}
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == fingerprint_server_configs({
        "foo": {"command": "changed"}
    })


def test_explicit_empty_cleans_canonical_and_legacy_while_missing_file_preserves(tmp_path: Path) -> None:
    manager, registry, discovery = _setup(tmp_path, {"one": {"command": "one"}})
    registry.save({
        "mcp-one-old": _entry(registry, "one", "old"),
        "mcp-legacy": {"type": "mcp"},
        "user-node": {"type": "user"},
    })
    manager.config_path.unlink()

    _run(manager, registry, discovery)
    assert set(registry.load(include_filtered=True)) == {"mcp-one-old", "mcp-legacy", "user-node"}

    manager.save({"mcpServers": {}})
    _run(manager, registry, discovery)
    assert registry.load(include_filtered=True) == {"user-node": {"type": "user"}}
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == {}


def test_failure_warning_names_servers_only_in_interactive_mode(tmp_path: Path) -> None:
    manager, registry, discovery = _setup(tmp_path, {"broken": {"command": "broken"}})
    discovery.discover_tools.side_effect = RuntimeError("down")

    with patch("pflow.cli.mcp_sync.click.echo") as echo:
        _run(manager, registry, discovery, interactive=False)
        echo.assert_not_called()
        _run(manager, registry, discovery, interactive=True)

    assert any("broken" in call.args[0] for call in echo.call_args_list)
