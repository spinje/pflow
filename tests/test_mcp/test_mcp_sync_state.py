"""Persistence-level tests for MCP per-server reconciliation."""

from pathlib import Path
from unittest.mock import Mock, patch

from pflow.mcp import MCPRegistrar, MCPServerManager
from pflow.mcp.sync_state import MCP_SERVER_FINGERPRINTS_KEY, fingerprint_server_config
from pflow.registry import Registry


def _tool(name: str) -> dict:
    return {"name": name, "description": name}


def _entry(registrar: MCPRegistrar, server: str, tool: str) -> dict:
    return registrar._create_registry_entry(server, _tool(tool))


def _build(tmp_path: Path, configs: dict[str, dict]) -> tuple[MCPServerManager, Registry, Mock, MCPRegistrar]:
    manager = MCPServerManager(config_path=tmp_path / "mcp-servers.json")
    manager.save({"mcpServers": configs})
    registry = Registry(registry_path=tmp_path / "registry.json")
    registry._save_with_metadata({})
    discovery = Mock()
    registrar = MCPRegistrar(registry=registry, manager=manager, discovery=discovery)
    registrar._settings_manager = Mock()
    registrar._settings_manager.should_include_node.return_value = True
    return manager, registry, discovery, registrar


def test_fingerprint_uses_canonical_raw_json_and_sha256() -> None:
    config = {"env": {"TOKEN": "${TOKEN}"}, "command": "cmd", "args": ["x"]}

    assert fingerprint_server_config(config) == "753d4b739030191da0cdd56a8859f1e0d2723f256b3cd84d0e20a84feb433b64"


def test_partial_failure_replaces_success_preserves_failure_and_cleans_removed(tmp_path: Path) -> None:
    configs = {"good": {"command": "good"}, "bad": {"command": "bad"}}
    _, registry, discovery, registrar = _build(tmp_path, configs)
    nodes = {
        "mcp-good-old": _entry(registrar, "good", "old"),
        "mcp-bad-old": _entry(registrar, "bad", "old"),
        "mcp-removed-old": _entry(registrar, "removed", "old"),
        "mcp-legacy": {"type": "mcp"},
        "user-node": {"type": "user"},
    }
    registry.save(
        nodes,
        metadata_updates={
            MCP_SERVER_FINGERPRINTS_KEY: {
                "good": "old-good",
                "bad": "old-bad",
                "removed": "old-removed",
            }
        },
    )
    discovery.discover_tools.side_effect = [[_tool("new")], RuntimeError("temporary outage")]

    with patch.object(registry, "save", wraps=registry.save) as save:
        batch = registrar.sync_servers(["good", "bad"], reconcile_all=True)

    assert save.call_count == 1
    assert [result.error for result in batch.servers] == [None, "temporary outage"]
    persisted = registry.load(include_filtered=True)
    assert set(persisted) == {"mcp-good-new", "mcp-bad-old", "user-node"}
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == {
        "good": fingerprint_server_config(configs["good"]),
        "bad": "old-bad",
    }


def test_total_failure_preserves_tools_and_fingerprints(tmp_path: Path) -> None:
    configs = {"one": {"command": "one"}, "two": {"command": "two"}}
    _, registry, discovery, registrar = _build(tmp_path, configs)
    nodes = {
        "mcp-one-old": _entry(registrar, "one", "old"),
        "mcp-two-old": _entry(registrar, "two", "old"),
    }
    old_fingerprints = {"one": "old-one", "two": "old-two"}
    registry.save(nodes, metadata_updates={MCP_SERVER_FINGERPRINTS_KEY: old_fingerprints})
    discovery.discover_tools.side_effect = [RuntimeError("one down"), RuntimeError("two down")]

    batch = registrar.sync_servers(["one", "two"], reconcile_all=True)

    assert all(result.error for result in batch.servers)
    assert registry.load(include_filtered=True) == nodes
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == old_fingerprints


def test_empty_success_removes_owned_tools_and_advances_fingerprint(tmp_path: Path) -> None:
    configs = {"empty": {"command": "empty"}}
    _, registry, discovery, registrar = _build(tmp_path, configs)
    registry.save({"mcp-empty-old": _entry(registrar, "empty", "old")})
    discovery.discover_tools.return_value = []

    batch = registrar.sync_servers(["empty"], reconcile_all=True)

    assert batch.servers[0].tools_discovered == 0
    assert registry.load(include_filtered=True) == {}
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == {"empty": fingerprint_server_config(configs["empty"])}


def test_exact_owner_replacement_removal_and_listing_isolate_overlapping_names(tmp_path: Path) -> None:
    configs = {"foo": {"command": "foo"}, "foo-bar": {"command": "foo-bar"}}
    _, registry, discovery, registrar = _build(tmp_path, configs)
    nodes = {
        "mcp-foo-old": _entry(registrar, "foo", "old"),
        "mcp-foo-bar-old": _entry(registrar, "foo-bar", "old"),
    }
    registry.save(
        nodes,
        metadata_updates={MCP_SERVER_FINGERPRINTS_KEY: {"foo": "old", "foo-bar": "peer"}},
    )
    discovery.discover_tools.return_value = [_tool("new")]

    registrar.sync_servers(["foo"], reconcile_all=False)
    assert registrar.list_registered_tools("foo") == ["mcp-foo-new"]
    assert registrar.list_registered_tools("foo-bar") == ["mcp-foo-bar-old"]

    assert registrar.remove_server_tools("foo") == 1
    assert registrar.list_registered_tools("foo") == []
    assert registrar.list_registered_tools("foo-bar") == ["mcp-foo-bar-old"]
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == {"foo-bar": "peer"}


def test_filtered_replacement_preserves_unrelated_filtered_entries(tmp_path: Path) -> None:
    configs = {"target": {"command": "target"}}
    _, registry, discovery, registrar = _build(tmp_path, configs)
    unrelated = _entry(registrar, "other", "denied")
    registry.save({"mcp-target-old": _entry(registrar, "target", "old"), "mcp-other-denied": unrelated})
    discovery.discover_tools.return_value = [_tool("allowed"), _tool("denied")]
    registrar._settings_manager.should_include_node.side_effect = lambda name: not name.endswith("denied")

    batch = registrar.sync_servers(["target"], reconcile_all=False)

    persisted = registry.load(include_filtered=True)
    assert set(persisted) == {"mcp-target-allowed", "mcp-other-denied"}
    assert batch.servers[0].tools_filtered == 1


def test_conversion_failure_preserves_server_while_valid_peer_advances(tmp_path: Path) -> None:
    configs = {"bad": {"command": "bad"}, "good": {"command": "good"}}
    _, registry, discovery, registrar = _build(tmp_path, configs)
    registry.save(
        {
            "mcp-bad-old": _entry(registrar, "bad", "old"),
            "mcp-good-old": _entry(registrar, "good", "old"),
        },
        metadata_updates={MCP_SERVER_FINGERPRINTS_KEY: {"bad": "old-bad", "good": "old-good"}},
    )
    discovery.discover_tools.side_effect = [
        [_tool("broken") | {"inputSchema": {"properties": []}}],
        [_tool("new")],
    ]
    discovery.convert_to_pflow_params.side_effect = AttributeError("invalid properties")

    batch = registrar.sync_servers(["bad", "good"], reconcile_all=True)

    assert batch.servers[0].error == "Could not build registry entries for 'bad': invalid properties"
    assert batch.servers[1].error is None
    assert set(registry.load(include_filtered=True)) == {"mcp-bad-old", "mcp-good-new"}
    assert registry.get_metadata(MCP_SERVER_FINGERPRINTS_KEY) == {
        "bad": "old-bad",
        "good": fingerprint_server_config(configs["good"]),
    }


def test_registry_change_during_discovery_survives_late_snapshot(tmp_path: Path) -> None:
    configs = {"target": {"command": "target"}}
    _, registry, discovery, registrar = _build(tmp_path, configs)
    registry.save({"existing": {"type": "user"}})

    def discover(*_args, **_kwargs):
        concurrent_registry = Registry(registry.registry_path)
        current = concurrent_registry.load(include_filtered=True)
        current["concurrent"] = {"type": "user"}
        concurrent_registry.save(current)
        return [_tool("new")]

    discovery.discover_tools.side_effect = discover
    registrar.sync_servers(["target"], reconcile_all=False)

    assert set(registry.load(include_filtered=True)) == {"existing", "concurrent", "mcp-target-new"}


def test_config_change_during_discovery_aborts_without_registry_write(tmp_path: Path) -> None:
    configs = {"target": {"command": "old"}}
    manager, registry, discovery, registrar = _build(tmp_path, configs)
    registry.save({"mcp-target-old": _entry(registrar, "target", "old")})
    before = registry.registry_path.read_text(encoding="utf-8")

    def discover(*_args, **_kwargs):
        manager.save({"mcpServers": {"target": {"command": "changed"}}})
        return [_tool("observed")]

    discovery.discover_tools.side_effect = discover
    with patch.object(registry, "save", wraps=registry.save) as save:
        batch = registrar.sync_servers(["target"], reconcile_all=True)

    assert batch.aborted_reason is not None
    save.assert_not_called()
    assert registry.registry_path.read_text(encoding="utf-8") == before
