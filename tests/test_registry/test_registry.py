"""
Tests for the node registry.

REFACTOR HISTORY:
- 2024-01-30: Removed internal state testing (registry_path attribute)
- 2024-01-30: Removed logging mock tests - focus on behavior, not implementation
- 2024-01-30: Removed JSON formatting tests - focus on data integrity, not cosmetics
- 2024-01-30: Added more integration tests and real workflow scenarios
"""

import tempfile
from pathlib import Path

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
        """Test that missing registry files are handled gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "missing.json"
            registry = Registry(registry_path)

            # Should return empty dict, not crash
            result = registry.load()
            assert result == {}

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
                    "name": "test-node",
                    "module": "pflow.nodes.test",
                    "class_name": "TestNode",
                    "docstring": "Test node",
                    "file_path": "/path/test.py",
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
            assert "test-node" in loaded_data
            assert "llm-node" in loaded_data

            # Name should not be in the stored data (it's the key)
            assert "name" not in loaded_data["test-node"]
            assert "name" not in loaded_data["llm-node"]

            # Other fields should be preserved
            assert loaded_data["test-node"]["module"] == "pflow.nodes.test"
            assert loaded_data["test-node"]["class_name"] == "TestNode"

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
            loaded = registry.load()

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
            loaded = registry.load()

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
            final = Registry(registry_path).load()

            # Document current behavior: last write wins
            assert len(final) == 1
            assert "node-2" in final
            assert "node-1" not in final
