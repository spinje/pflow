"""
Tests for the node registry.

REFACTOR HISTORY:
- 2024-01-30: Removed internal state testing (registry_path attribute)
- 2024-01-30: Removed logging mock tests - focus on behavior, not implementation
- 2024-01-30: Removed JSON formatting tests - focus on data integrity, not cosmetics
- 2024-01-30: Added more integration tests and real workflow scenarios
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.registry.registry import Registry


class TestRegistryDataPersistence:
    """Test that registry correctly saves and loads node data."""

    def test_saves_and_loads_node_data(self):
        """Test that node data can be saved and loaded correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            test_data = {
                "llm": {
                    "module": "pflow.nodes.llm",
                    "class_name": "LLMNode",
                    "docstring": "LLM node",
                    "file_path": "/path/llm.py",
                },
                "read-file": {
                    "module": "pflow.nodes.file.read",
                    "class_name": "ReadFileNode",
                    "docstring": "Read file node",
                    "file_path": "/path/read.py",
                },
            }

            # Save data
            registry.save(test_data)

            # Load data back
            loaded_data = registry.load()

            # Verify data integrity
            assert loaded_data == test_data
            assert len(loaded_data) == 2
            assert "llm" in loaded_data
            assert "read-file" in loaded_data

    def test_handles_missing_registry_file(self):
        """Test that missing registry files trigger auto-discovery of core nodes.

        FIX HISTORY:
        - 2025-08-29: Updated test to reflect new auto-discovery behavior
          Registry now auto-discovers core nodes when file doesn't exist
          instead of returning empty dict
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "missing.json"
            registry = Registry(registry_path)

            # Should auto-discover core nodes when file doesn't exist
            result = registry.load()

            # Verify core nodes were discovered
            assert len(result) > 0, "Should have discovered core nodes"

            # Check for expected core nodes
            expected_core_nodes = ["read-file", "write-file", "llm", "shell"]
            for node_name in expected_core_nodes:
                assert node_name in result, f"Core node '{node_name}' should be discovered"

            # Verify nodes have required metadata
            for node_name, node_data in result.items():
                assert "module" in node_data, f"Node {node_name} missing 'module'"
                assert "class_name" in node_data, f"Node {node_name} missing 'class_name'"
                assert "type" in node_data, f"Node {node_name} missing 'type'"
                assert node_data["type"] == "core", f"Node {node_name} should be marked as 'core'"

            # Verify registry file was created
            assert registry_path.exists(), "Registry file should be created after auto-discovery"

    def test_handles_empty_registry_file(self):
        """Test that empty registry files are handled gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "empty.json"
            registry_path.write_text("")
            registry = Registry(registry_path)

            # Should return empty dict, not crash
            result = registry.load()
            assert result == {}

    def test_handles_corrupted_registry_file(self):
        """Test that corrupted JSON files are handled gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "corrupt.json"
            registry_path.write_text("{ invalid json }")
            registry = Registry(registry_path)

            # Should return empty dict, not crash
            result = registry.load()
            assert result == {}

    def test_creates_parent_directories(self):
        """Test that save creates parent directories when needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Path with non-existent parent directories
            registry_path = Path(tmpdir) / "subdir" / "another" / "registry.json"
            registry = Registry(registry_path)

            test_data = {"test": {"module": "test.module"}}
            registry.save(test_data)

            # Verify parent directories were created
            assert registry_path.parent.exists()
            assert registry_path.exists()

            # Verify data was saved correctly
            loaded_data = registry.load()
            assert loaded_data == test_data

    def test_overwrites_existing_registry(self):
        """Test that save completely replaces existing registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "overwrite.json"
            registry = Registry(registry_path)

            # Save initial data
            initial_data = {"old": {"module": "old.module"}}
            registry.save(initial_data)

            # Save new data
            new_data = {"new": {"module": "new.module"}}
            registry.save(new_data)

            # Verify old data is completely replaced
            loaded_data = registry.load()
            assert loaded_data == new_data
            assert "old" not in loaded_data
            assert "new" in loaded_data

    def test_handles_permission_errors_on_save(self):
        """Test that permission errors on save are properly raised."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Make directory read-only
            Path(tmpdir).chmod(0o555)

            try:
                registry_path = Path(tmpdir) / "noperm.json"
                registry = Registry(registry_path)

                with pytest.raises(PermissionError):
                    registry.save({"test": {"data": "value"}})
            finally:
                # Restore permissions for cleanup
                Path(tmpdir).chmod(0o755)


class TestRegistryScannerIntegration:
    """Test registry integration with scanner results."""

    def test_converts_scanner_results_to_registry_format(self):
        """Test that scanner list format is converted to registry dict format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            # Scanner output format
            scan_results = [
                {
                    "name": "shell",
                    "module": "pflow.nodes.shell.shell",
                    "class_name": "ShellNode",
                    "docstring": "Shell node",
                    "file_path": "/path/shell.py",
                },
                {
                    "name": "llm-node",
                    "module": "pflow.nodes.llm",
                    "class_name": "LLMNode",
                    "docstring": "LLM processing",
                    "file_path": "/path/llm.py",
                },
            ]

            # Convert to registry format
            registry.update_from_scanner(scan_results)

            # Load and verify conversion
            loaded_data = registry.load()

            # Should be keyed by node name
            assert "shell" in loaded_data
            assert "llm-node" in loaded_data

            # Name should not be in the stored data (it's the key)
            assert "name" not in loaded_data["shell"]
            assert "name" not in loaded_data["llm-node"]

            # Other fields should be preserved
            assert loaded_data["shell"]["module"] == "pflow.nodes.shell.shell"
            assert loaded_data["shell"]["class_name"] == "ShellNode"

    def test_handles_scanner_nodes_without_names(self):
        """Test that scanner nodes missing names are skipped gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            scan_results = [
                {"module": "no.name.module"},  # Missing name
                {"name": "valid", "module": "valid.module"},
            ]

            # Should not crash
            registry.update_from_scanner(scan_results)

            # Only valid node should be saved
            loaded_data = registry.load()
            assert len(loaded_data) == 1
            assert "valid" in loaded_data

    def test_handles_duplicate_node_names(self):
        """Test that duplicate node names are handled (last-wins behavior)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            scan_results = [
                {"name": "duplicate", "module": "first.module"},
                {"name": "unique", "module": "unique.module"},
                {"name": "duplicate", "module": "second.module"},  # Should win
            ]

            registry.update_from_scanner(scan_results)

            loaded_data = registry.load()
            assert len(loaded_data) == 2
            assert loaded_data["duplicate"]["module"] == "second.module"  # Last wins
            assert loaded_data["unique"]["module"] == "unique.module"

    def test_handles_empty_scanner_results(self):
        """Test that empty scanner results create empty registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            registry.update_from_scanner([])

            loaded_data = registry.load()
            assert loaded_data == {}


class TestRegistryNodeRetrieval:
    """Test registry node metadata retrieval functionality."""

    def test_retrieves_specific_nodes(self):
        """Test that specific node metadata can be retrieved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            test_data = {
                "llm": {"module": "pflow.nodes.llm", "class_name": "LLMNode"},
                "read-file": {"module": "pflow.nodes.file.read", "class_name": "ReadFileNode"},
                "write-file": {"module": "pflow.nodes.file.write", "class_name": "WriteFileNode"},
            }
            registry.save(test_data)

            # Retrieve specific nodes
            result = registry.get_nodes_metadata(["llm", "read-file"])

            assert len(result) == 2
            assert "llm" in result
            assert "read-file" in result
            assert "write-file" not in result
            assert result["llm"] == test_data["llm"]
            assert result["read-file"] == test_data["read-file"]

    def test_output_types_by_kind_ships_declared_types_and_drops_any(self):
        """The kind->field->type read-model: declared docstring types verbatim;
        ``any`` entries dropped (a type that says nothing is not a fact worth
        shipping); kinds with no typed outputs absent entirely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Registry(Path(tmpdir) / "test.json")
            registry.save({
                "shell": {
                    "module": "m",
                    "class_name": "C",
                    "interface": {
                        "outputs": [
                            {"key": "stdout", "type": "str", "description": ""},
                            {"key": "exit_code", "type": "int", "description": ""},
                        ]
                    },
                },
                "mcp-some-tool": {
                    "module": "m",
                    "class_name": "C",
                    "interface": {"outputs": [{"key": "result", "type": "any", "description": ""}]},
                },
                "bare": {"module": "m", "class_name": "C"},
            })

            types = registry.output_types_by_kind()

            assert types["shell"] == {"stdout": "str", "exit_code": "int"}
            assert "mcp-some-tool" not in types  # only output was `any`
            assert "bare" not in types  # no interface at all

    def test_output_types_by_kind_on_real_core_nodes(self):
        """The real scanned shell interface produces the documented types
        (guards the docstring convention end-to-end, not just the read-model)."""
        registry = Registry()
        types = registry.output_types_by_kind()

        assert types["shell"]["stdout"] == "str"
        assert types["shell"]["exit_code"] == "int"
        assert all("any" not in fields.values() for fields in types.values())

    def test_filters_invalid_node_names(self):
        """Test that invalid node names are filtered out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            test_data = {
                "llm": {"module": "pflow.nodes.llm", "class_name": "LLMNode"},
                "read-file": {"module": "pflow.nodes.file.read", "class_name": "ReadFileNode"},
            }
            registry.save(test_data)

            # Request mix of valid and invalid node names
            result = registry.get_nodes_metadata(["llm", "non-existent", "read-file"])

            # Should only return valid nodes
            assert len(result) == 2
            assert "llm" in result
            assert "read-file" in result
            assert "non-existent" not in result

    def test_handles_empty_node_list(self):
        """Test that empty node lists return empty results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            test_data = {"llm": {"module": "pflow.nodes.llm"}}
            registry.save(test_data)

            # Test various empty collections
            assert registry.get_nodes_metadata([]) == {}
            assert registry.get_nodes_metadata(set()) == {}
            assert registry.get_nodes_metadata(()) == {}

    def test_validates_node_types_parameter(self):
        """Test that None parameter raises appropriate error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            with pytest.raises(TypeError, match="node_types cannot be None"):
                registry.get_nodes_metadata(None)

    def test_handles_mixed_parameter_types(self):
        """Test that non-string items in collection are filtered out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            test_data = {
                "llm": {"module": "pflow.nodes.llm", "class_name": "LLMNode"},
                "read-file": {"module": "pflow.nodes.file.read", "class_name": "ReadFileNode"},
            }
            registry.save(test_data)

            # Mix of valid strings and invalid types
            result = registry.get_nodes_metadata(["llm", 123, "read-file", None, {"dict": "value"}])

            # Should only process string matches
            assert len(result) == 2
            assert "llm" in result
            assert "read-file" in result


class TestRegistryRealWorldScenarios:
    """Test registry behavior in real-world scenarios."""

    def test_full_scanner_to_registry_workflow(self):
        """Test complete workflow from scanner output to registry persistence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "workflow_test.json"
            registry = Registry(registry_path)

            # Simulate real scanner output
            scanner_output = [
                {
                    "module": "pflow.nodes.file.read_file",
                    "class_name": "ReadFileNode",
                    "name": "read-file",
                    "docstring": "Read file contents.\n\nReads a file and returns contents.",
                    "file_path": "/project/src/pflow/nodes/file/read_file.py",
                },
                {
                    "module": "pflow.nodes.llm.llm_node",
                    "class_name": "LLMNode",
                    "name": "llm",
                    "docstring": "Process text with LLM.",
                    "file_path": "/project/src/pflow/nodes/llm/llm_node.py",
                },
            ]

            # Update registry
            registry.update_from_scanner(scanner_output)

            # Create new registry instance to test persistence
            registry2 = Registry(registry_path)
            loaded_data = registry2.load()

            # Verify complete workflow
            assert len(loaded_data) == 2
            assert "read-file" in loaded_data
            assert "llm" in loaded_data

            # Verify data integrity
            assert loaded_data["read-file"]["module"] == "pflow.nodes.file.read_file"
            assert loaded_data["read-file"]["class_name"] == "ReadFileNode"
            assert "Read file contents" in loaded_data["read-file"]["docstring"]

            # Verify names are keys, not values
            assert "name" not in loaded_data["read-file"]
            assert "name" not in loaded_data["llm"]

    def test_handles_unicode_in_node_data(self):
        """Test that unicode in node names and docstrings works correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "unicode_test.json"
            registry = Registry(registry_path)

            scan_results = [
                {
                    "name": "emoji-node-🚀",
                    "module": "test.emoji",
                    "class_name": "EmojiNode",
                    "docstring": "Unicode test: 你好世界 🌍",
                    "file_path": "/test/emoji.py",
                },
            ]

            # Should handle unicode correctly
            registry.update_from_scanner(scan_results)
            # Load unfiltered to test storage, not filtering
            loaded = registry.load(include_filtered=True)

            assert "emoji-node-🚀" in loaded
            assert loaded["emoji-node-🚀"]["docstring"] == "Unicode test: 你好世界 🌍"

    def test_handles_large_registry_efficiently(self):
        """Test that registry handles large numbers of nodes efficiently."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "large_test.json"
            registry = Registry(registry_path)

            # Create many nodes
            scan_results = []
            for i in range(100):
                scan_results.append({
                    "name": f"node-{i:03d}",
                    "module": f"test.nodes.node_{i}",
                    "class_name": f"Node{i}",
                    "docstring": f"Test node {i}",
                    "file_path": f"/test/nodes/node_{i}.py",
                })

            # Should handle large datasets efficiently
            registry.update_from_scanner(scan_results)
            # Load unfiltered to test storage, not filtering
            loaded = registry.load(include_filtered=True)

            # Verify all nodes saved
            assert len(loaded) == 100
            assert "node-050" in loaded
            assert loaded["node-050"]["class_name"] == "Node50"

    def test_concurrent_registry_access_behavior(self):
        """Test registry behavior with multiple instances (simulated concurrency)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "concurrent_test.json"

            # Two registry instances
            registry1 = Registry(registry_path)
            registry2 = Registry(registry_path)

            # First saves
            registry1.update_from_scanner([{"name": "node-1", "module": "test.node1", "class_name": "Node1"}])

            # Second overwrites (current behavior - complete replacement)
            registry2.update_from_scanner([{"name": "node-2", "module": "test.node2", "class_name": "Node2"}])

            # Load final state
            # Load unfiltered to test storage, not filtering
            final = Registry(registry_path).load(include_filtered=True)

            # Document current behavior: last write wins
            assert len(final) == 1
            assert "node-2" in final
            assert "node-1" not in final

    def test_deepcopy_returns_same_instance(self):
        """Registry must survive deep copy — parallel batch depends on this.

        PflowBatchNode deep-copies the inner node chain for thread isolation.
        Registry is injected as a param into workflow nodes and contains
        SettingsManager._lock (threading.RLock), which cannot be pickled.

        Registry.__deepcopy__ returns self because it's a shared, read-only
        resource during execution. If this method is removed, parallel batch
        on workflow nodes fails with 'cannot pickle _thread.RLock object'.
        """
        import copy

        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Registry(Path(tmpdir) / "test.json")
            copied = copy.deepcopy(registry)
            assert copied is registry


class TestRegistryVersionRefresh:
    """Test version-based registry refresh behavior.

    When pflow is upgraded, the registry version (stored during _save_with_metadata)
    may differ from the running pflow version. In that case, core nodes are rescanned
    while user and MCP nodes are preserved.

    FIX HISTORY:
    - 2025-02-10: Added to verify version-mismatch detection and selective
      refresh of core nodes while preserving user/MCP nodes.
    """

    def test_outdated_returns_false_when_versions_match(self):
        """Registry whose version matches the current pflow version is not outdated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Save a registry with current pflow version via _save_with_metadata
            test_nodes = {
                "test-node": {
                    "module": "test.module",
                    "class_name": "TestNode",
                    "type": "core",
                },
            }
            registry._save_with_metadata(test_nodes)

            # Load from file to populate _registry_version
            registry2 = Registry(registry_path)
            nodes = registry2._load_from_file()

            # Version should match -- _core_nodes_outdated should return False
            assert registry2._core_nodes_outdated(nodes) is False

    def test_outdated_returns_true_when_versions_differ(self):
        """Registry with a stale version should be detected as outdated.

        We save a registry with _save_with_metadata (which stamps the current
        version), load it, then patch get_version to return a newer value so
        the comparison sees a mismatch.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Save with current version
            test_nodes = {
                "test-node": {
                    "module": "test.module",
                    "class_name": "TestNode",
                    "type": "core",
                },
            }
            registry._save_with_metadata(test_nodes)

            # Load to populate _registry_version
            registry2 = Registry(registry_path)
            nodes = registry2._load_from_file()
            assert registry2._registry_version is not None

            # Patch _get_version on the Registry class directly
            with patch.object(Registry, "_get_version", return_value="99.99.99"):
                assert registry2._core_nodes_outdated(nodes) is True

    def test_refresh_preserves_user_nodes(self):
        """When core nodes are refreshed, every non-core node must survive.

        We write a registry containing core nodes plus user/MCP nodes, then
        call _refresh_core_nodes. The returned dict must still contain the
        user and MCP entries — including a legacy MCP entry with NO type field
        (synced before issue #462's fix stamped type="mcp"), which the fail-safe
        "preserve everything that isn't core" predicate must self-heal.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Build a mixed registry with core + user + mcp nodes
            mixed_nodes = {
                "shell": {
                    "module": "pflow.nodes.shell.shell",
                    "class_name": "ShellNode",
                    "type": "core",
                },
                "my-custom-node": {
                    "module": "my_project.nodes.custom",
                    "class_name": "CustomNode",
                    "type": "user",
                },
                "mcp-tool": {
                    "module": "pflow.nodes.mcp.mcp",
                    "class_name": "McpNode",
                    "type": "mcp",
                },
                # Legacy MCP entry as the registrar built it BEFORE the fix:
                # no "type" field, identified only by the virtual path.
                "mcp-legacy-tool": {
                    "module": "pflow.nodes.mcp.node",
                    "class_name": "MCPNode",
                    "file_path": "virtual://mcp",
                },
            }
            registry._save_with_metadata(mixed_nodes)

            # Reload so _registry_version is set
            registry2 = Registry(registry_path)
            nodes = registry2._load_from_file()

            # Refresh core nodes
            refreshed = registry2._refresh_core_nodes(nodes)

            # User and MCP nodes must be preserved
            assert "my-custom-node" in refreshed
            assert refreshed["my-custom-node"]["type"] == "user"
            assert "mcp-tool" in refreshed
            assert refreshed["mcp-tool"]["type"] == "mcp"
            # Untyped legacy MCP entry must self-heal through the refresh,
            # with its payload intact (the merge must not mutate it).
            assert "mcp-legacy-tool" in refreshed
            assert refreshed["mcp-legacy-tool"] == mixed_nodes["mcp-legacy-tool"]

            # Core nodes should be present (from real auto-discovery)
            core_nodes = {name: data for name, data in refreshed.items() if data.get("type") == "core"}
            assert len(core_nodes) > 0, "Refresh should have discovered core nodes"

    def test_refresh_does_not_shadow_core_node_with_untyped_entry(self):
        """A stale untyped entry sharing a core node's name must not shadow it.

        The fail-safe denylist preserves untyped entries, but fresh core metadata
        must win on a name collision (issue #462 review): a legacy untyped "shell"
        entry (e.g. left by the removed `registry scan` CLI) must be overridden by
        the freshly-discovered core node, never resurrected over it. A non-colliding
        untyped entry must still self-heal.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            stale_nodes = {
                # Untyped entry colliding with a real core node name.
                "shell": {
                    "module": "stale.shell",
                    "class_name": "StaleShellNode",
                    "file_path": "/stale/shell.py",
                },
                # Untyped MCP entry that does NOT collide — must self-heal.
                "mcp-legacy-tool": {
                    "module": "pflow.nodes.mcp.node",
                    "class_name": "MCPNode",
                    "file_path": "virtual://mcp",
                },
            }
            registry._save_with_metadata(stale_nodes)

            registry2 = Registry(registry_path)
            nodes = registry2._load_from_file()
            refreshed = registry2._refresh_core_nodes(nodes)

            # Fresh core "shell" wins — the stale untyped entry must not shadow it.
            assert refreshed["shell"]["type"] == "core"
            assert refreshed["shell"]["module"] == "pflow.nodes.shell.shell"
            assert refreshed["shell"]["class_name"] == "ShellNode"
            # Non-colliding untyped entry still self-heals through the refresh.
            assert "mcp-legacy-tool" in refreshed


class TestRegistrySourceMtimeRefresh:
    """Test mtime-based refresh when core node source files change.

    Version-based refresh only fires across pflow version bumps. Editable /
    from-source installs can carry stale registries indefinitely when a node's
    Interface docstring changes at the same version — that's the failure mode
    these tests guard against.
    """

    def test_not_outdated_when_sources_predate_scan(self):
        """Fresh scan timestamp + real source files (install mtimes) → not outdated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            test_nodes = {
                "test-node": {
                    "module": "test.module",
                    "class_name": "TestNode",
                    "type": "core",
                },
            }
            registry._save_with_metadata(test_nodes)

            registry2 = Registry(registry_path)
            nodes = registry2._load_from_file()

            # Version matches AND source files are older than the just-written scan
            assert registry2._core_nodes_outdated(nodes) is False

    def test_outdated_when_mtime_path_reports_stale(self):
        """When _source_newer_than_scan returns True, _core_nodes_outdated must too."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            registry._save_with_metadata({
                "test-node": {"module": "test.module", "class_name": "TestNode", "type": "core"}
            })
            registry2 = Registry(registry_path)
            nodes = registry2._load_from_file()

            with patch.object(Registry, "_source_newer_than_scan", return_value=True):
                assert registry2._core_nodes_outdated(nodes) is True

    def test_source_newer_than_scan_true_for_ancient_timestamp(self, tmp_path):
        """A year-2000 scan timestamp against real pflow.nodes sources must detect staleness."""
        registry = Registry(tmp_path / "registry.json")
        registry._registry_last_scan = "2000-01-01T00:00:00+00:00"

        assert registry._source_newer_than_scan() is True

    def test_source_newer_than_scan_true_when_timestamp_missing(self, tmp_path):
        """Legacy registry without last_core_scan should be treated as stale (self-heals)."""
        registry = Registry(tmp_path / "registry.json")
        registry._registry_last_scan = None

        assert registry._source_newer_than_scan() is True

    def test_outdated_runs_mtime_check_when_version_missing(self, tmp_path):
        """A wrapper registry with last_core_scan but no version must still mtime-check.

        Narrow scenario: manually-edited registry, partial write, or external tooling
        produced a structured wrapper without a `version` field. Early versions of
        the gate short-circuited on ``not self._registry_version``, hiding the
        mtime refresh entirely for these registries.
        """
        registry = Registry(tmp_path / "registry.json")
        registry._registry_version = None
        # Ancient scan timestamp — real pflow.nodes files are all newer
        registry._registry_last_scan = "2000-01-01T00:00:00+00:00"

        # Must detect staleness via the mtime path, not early-return False
        assert registry._core_nodes_outdated({}) is True

    def test_outdated_false_when_both_version_and_scan_missing(self, tmp_path):
        """No version AND no scan timestamp → nothing to compare, don't refresh.

        Preserves pre-mtime defensive behavior for legacy flat-format registries
        and partially-written wrappers.
        """
        registry = Registry(tmp_path / "registry.json")
        registry._registry_version = None
        registry._registry_last_scan = None

        assert registry._core_nodes_outdated({}) is False

    def test_naive_legacy_timestamp_handled(self, tmp_path):
        """Naive local-time ISO must (a) not raise, (b) compare correctly in both directions.

        Guards against a regression that drops the ``.astimezone()`` fallback —
        without it, ``datetime.fromisoformat(naive).timestamp()`` still works but
        a future `fromisoformat(aware) vs timestamp()` mix could raise on some
        paths, and/or the comparison direction could silently invert.
        """
        # Naive future: no files can possibly be newer → False
        registry_future = Registry(tmp_path / "registry-future.json")
        registry_future._registry_last_scan = "2099-01-01T00:00:00"
        result_future = registry_future._source_newer_than_scan()
        assert isinstance(result_future, bool)
        assert result_future is False

        # Naive past: real source files are newer → True
        # This half proves the naive comparison direction is correct.
        registry_past = Registry(tmp_path / "registry-past.json")
        registry_past._registry_last_scan = "2000-01-01T00:00:00"
        assert registry_past._source_newer_than_scan() is True

    def test_source_check_fails_safe_on_parse_error(self, tmp_path):
        """Malformed stored timestamp must not crash load() — fail-safe returns False."""
        registry = Registry(tmp_path / "registry.json")
        registry._registry_last_scan = "not-a-valid-iso-timestamp"

        # Parse failure is caught; method returns False (don't spuriously refresh).
        assert registry._source_newer_than_scan() is False

    def test_real_mtime_newer_than_scan_triggers_true(self, tmp_path, monkeypatch):
        """End-to-end: a real file with mtime > scan timestamp must return True.

        Guards the timestamp-comparison direction (> vs <) from silent regression —
        the kind of off-by-one that passes mock-based tests but breaks in production.
        """
        import os

        import pflow.nodes

        # Build a synthetic nodes tree and redirect pflow.nodes.__file__ to it.
        # (Patching __file__ is enough — `import pflow.nodes` binds via the parent
        # package's __dict__, so sys.modules manipulation alone is insufficient.)
        fake_nodes = tmp_path / "fake_nodes"
        fake_nodes.mkdir()
        (fake_nodes / "__init__.py").write_text("")
        sample = fake_nodes / "sample.py"
        sample.write_text("# placeholder")

        monkeypatch.setattr(pflow.nodes, "__file__", str(fake_nodes / "__init__.py"))

        # Scan time: now. File mtime: 1 hour in the future.
        registry = Registry(tmp_path / "registry.json")
        registry._registry_last_scan = datetime.now(timezone.utc).isoformat()
        future_ts = datetime.now(timezone.utc).timestamp() + 3600
        os.utime(sample, (future_ts, future_ts))

        assert registry._source_newer_than_scan() is True

    def test_scan_start_timestamp_captured_before_scan(self, tmp_path, monkeypatch):
        """last_core_scan must be captured BEFORE scan_for_nodes reads sources.

        Guards the race fix: if someone swaps ``scan_time=scan_start`` for the
        default ``_now_iso()`` call, the stored timestamp would be post-scan and
        concurrent edits during the scan window would be lost (their mtime sits
        below the stored timestamp, so the next load's mtime check misses them).
        """
        import time as time_mod

        from pflow.registry import scanner

        original_scan = scanner.scan_for_nodes

        def slow_scan(subdirs):
            # 50ms synthetic scan window — long enough to distinguish pre/post
            # scan timestamps, well under the tests/CLAUDE.md 0.1s budget.
            time_mod.sleep(0.05)
            return original_scan(subdirs)

        monkeypatch.setattr(scanner, "scan_for_nodes", slow_scan)

        registry = Registry(tmp_path / "registry.json")
        before = time_mod.time()
        registry._auto_discover_core_nodes()
        after = time_mod.time()

        stored_iso = json.loads((tmp_path / "registry.json").read_text())["last_core_scan"]
        stored_ts = datetime.fromisoformat(stored_iso).timestamp()

        # Stored must be at/after invocation start AND at least ~40ms before scan end
        # (i.e., pre-scan, not post-scan). Uses 40ms rather than the full 50ms to
        # absorb jitter on slow CI runners.
        assert stored_ts >= before, f"stored {stored_ts} < before {before}"
        assert stored_ts < after - 0.04, f"stored {stored_ts} too close to after {after} (post-scan)"

    def test_single_unreadable_file_does_not_abort_walk(self, tmp_path, monkeypatch):
        """A stat() failure on one file must not hide a newer file later in the walk.

        Regression guard: early versions wrapped the whole loop in a single try
        block, so one OSError aborted the entire check and silently returned False.

        Walk order is pinned via a Path.rglob patch — Path.rglob makes no
        cross-platform ordering guarantee, and if "good" ever iterates before
        "bad" the test would pass even against the buggy single-try implementation.
        """
        import os

        import pflow.nodes

        fake_nodes = tmp_path / "fake_nodes"
        fake_nodes.mkdir()
        (fake_nodes / "__init__.py").write_text("")
        bad = fake_nodes / "a_bad.py"
        bad.write_text("")
        good = fake_nodes / "b_good.py"
        good.write_text("")

        monkeypatch.setattr(pflow.nodes, "__file__", str(fake_nodes / "__init__.py"))

        registry = Registry(tmp_path / "registry.json")
        registry._registry_last_scan = datetime.now(timezone.utc).isoformat()
        future_ts = datetime.now(timezone.utc).timestamp() + 3600
        os.utime(good, (future_ts, future_ts))

        original_stat = Path.stat

        def selective_stat(self, *args, **kwargs):
            if self.name == "a_bad.py":
                raise OSError("simulated permission error")
            return original_stat(self, *args, **kwargs)

        # Pin walk order: bad first, good second. This forces the per-file
        # try/except to handle the OSError before reaching the newer file.
        def ordered_rglob(self, pattern):
            if pattern == "*.py":
                return iter([bad, good])
            return []

        with (
            patch.object(Path, "rglob", ordered_rglob),
            patch.object(Path, "stat", selective_stat),
        ):
            assert registry._source_newer_than_scan() is True


class TestRegistryFormatConsistency:
    """Regression tests for issue #142: save() must preserve structured format."""

    def test_save_preserves_version_after_save_with_metadata(self):
        """Bug 1 regression: save() after _save_with_metadata() must not destroy version tracking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Step 1: Write structured format (simulates _auto_discover_core_nodes)
            test_nodes = {
                "shell": {"module": "pflow.nodes.shell.shell", "class_name": "ShellNode", "type": "core"},
            }
            registry._save_with_metadata(test_nodes)

            # Step 2: Call save() (simulates MCP sync overwriting)
            updated_nodes = dict(test_nodes)
            updated_nodes["mcp-tool"] = {"module": "pflow.nodes.mcp.mcp", "class_name": "McpNode", "type": "mcp"}
            registry.save(updated_nodes)

            # Step 3: Verify structured format is preserved
            raw = json.loads(registry_path.read_text())
            assert "nodes" in raw, "save() must write structured format with 'nodes' key"
            assert "version" in raw, "save() must preserve version in structured format"

            # Step 4: Verify _load_from_file() can read the version
            registry2 = Registry(registry_path)
            nodes = registry2._load_from_file()
            assert registry2._registry_version is not None, "_registry_version must be populated after save()"
            assert "shell" in nodes
            assert "mcp-tool" in nodes

    def test_save_preserves_metadata(self):
        """save() must preserve the metadata field (used by MCP sync caching)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Write initial nodes
            registry._save_with_metadata({"shell": {"module": "m", "class_name": "C", "type": "core"}})

            # Set metadata (MCP sync hash)
            registry.set_metadata("mcp_config_hash", "abc123")

            # Call save() with updated nodes
            registry.save({"shell": {"module": "m", "class_name": "C", "type": "core"}})

            # Metadata must survive
            assert registry.get_metadata("mcp_config_hash") == "abc123"

    def test_get_set_metadata_roundtrip(self):
        """get_metadata/set_metadata must work on structured format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # set_metadata on empty file creates structured format
            registry.set_metadata("key1", "value1")
            assert registry.get_metadata("key1") == "value1"
            assert registry.get_metadata("nonexistent", "default") == "default"

            # Verify file is structured
            raw = json.loads(registry_path.read_text())
            assert "nodes" in raw
            assert "metadata" in raw
            assert raw["metadata"]["key1"] == "value1"

    def test_legacy_flat_format_metadata_stripped(self):
        """Legacy __metadata__ in flat format must not leak as a phantom node."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"

            # Write legacy flat format with __metadata__
            flat_data = {
                "shell": {"module": "m", "class_name": "C", "type": "core"},
                "__metadata__": {"mcp_config_hash": "old"},
            }
            registry_path.write_text(json.dumps(flat_data))

            registry = Registry(registry_path)
            nodes = registry._load_from_file()

            assert "__metadata__" not in nodes, "__metadata__ must be stripped from flat format"
            assert "shell" in nodes


class TestRegistryAtomicWrite:
    """Registry persistence is atomic: a torn or failed write never corrupts it.

    Regression guard for the cold-`pflow ui` concurrency bug — concurrent readers
    of a plain truncate-and-write registry observed half-written JSON → an empty
    node set → spurious "unknown node type" errors. The fix writes to a tempfile
    and ``os.replace``s it (atomic on POSIX). These tests pin the resulting
    behavior without depending on the implementation: a failed write leaves the
    previous registry intact, and no temp debris is left behind.
    """

    def test_failed_write_preserves_the_existing_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)
            registry.save({"shell": {"module": "m", "class_name": "C", "type": "core"}})
            original = registry_path.read_text()

            class _Unserializable:
                pass

            # json.dump raises partway through — a truncate-and-write would have
            # already destroyed the file by now; os.replace never touched it.
            with pytest.raises(TypeError):
                registry._write_atomic({"nodes": {"bad": _Unserializable()}})

            assert registry_path.read_text() == original, "failed write corrupted the registry"
            # Only the intact registry remains — no temp debris. iterdir is robust
            # to hidden dot-prefixed temp files across Python versions; glob is not.
            assert [p.name for p in Path(tmpdir).iterdir()] == ["registry.json"]

    def test_failed_write_leaves_no_temp_debris(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            class _Unserializable:
                pass

            with pytest.raises(TypeError):
                registry._write_atomic({"nodes": {"bad": _Unserializable()}})

            # Nothing was created (no prior save) and the temp file was cleaned up.
            assert list(Path(tmpdir).iterdir()) == [], "temp file left behind after failed write"

    def test_successful_write_round_trips(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)
            registry.save({"shell": {"module": "m", "class_name": "C", "type": "core"}})

            assert json.loads(registry_path.read_text())["nodes"]["shell"]["module"] == "m"
            assert [p.name for p in Path(tmpdir).iterdir()] == ["registry.json"]
