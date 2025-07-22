"""Tests for the node registry."""

import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.registry.registry import Registry


class TestRegistryInit:
    """Test Registry initialization."""

    def test_default_path(self):
        """Test default registry path is ~/.pflow/registry.json."""
        registry = Registry()
        expected = Path.home() / ".pflow" / "registry.json"
        assert registry.registry_path == expected

    def test_custom_path(self):
        """Test custom registry path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_path = Path(tmpdir) / "custom" / "registry.json"
            registry = Registry(custom_path)
            assert registry.registry_path == custom_path

    def test_path_conversion(self):
        """Test string path is converted to Path object."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = str(Path(tmpdir) / "test.json")
            registry = Registry(test_path)
            assert isinstance(registry.registry_path, Path)
            assert registry.registry_path == Path(test_path)


class TestRegistryLoad:
    """Test Registry load functionality."""

    def test_load_missing_file(self):
        """Test loading when file doesn't exist returns empty dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Registry(Path(tmpdir) / "missing.json")
            result = registry.load()
            assert result == {}

    def test_load_empty_file(self):
        """Test loading empty file returns empty dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "empty.json"
            file_path.write_text("")

            registry = Registry(file_path)
            result = registry.load()
            assert result == {}

    def test_load_valid_json(self):
        """Test loading valid JSON data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "valid.json"
            test_data = {
                "test-node": {
                    "module": "pflow.nodes.test",
                    "class_name": "TestNode",
                    "docstring": "Test docstring",
                    "file_path": "/path/to/test.py",
                }
            }
            file_path.write_text(json.dumps(test_data))

            registry = Registry(file_path)
            result = registry.load()
            assert result == test_data

    def test_load_corrupt_json(self):
        """Test loading corrupt JSON returns empty dict with warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "corrupt.json"
            file_path.write_text("{ invalid json }")

            registry = Registry(file_path)
            with patch.object(logging.getLogger("pflow.registry.registry"), "warning") as mock_warning:
                result = registry.load()
                assert result == {}
                mock_warning.assert_called_once()
                assert "Failed to parse" in str(mock_warning.call_args)

    def test_load_permission_error(self):
        """Test handling permission errors gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "noperm.json"
            file_path.write_text("{}")
            file_path.chmod(0o000)

            try:
                registry = Registry(file_path)
                with patch.object(logging.getLogger("pflow.registry.registry"), "warning") as mock_warning:
                    result = registry.load()
                    assert result == {}
                    mock_warning.assert_called_once()
            finally:
                # Restore permissions for cleanup
                file_path.chmod(0o644)


class TestRegistrySave:
    """Test Registry save functionality."""

    def test_save_creates_directory(self):
        """Test save creates parent directory if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "subdir" / "registry.json"
            registry = Registry(file_path)

            test_data = {"node1": {"module": "test.module"}}
            registry.save(test_data)

            assert file_path.parent.exists()
            assert file_path.exists()

    def test_save_pretty_json(self):
        """Test JSON is saved with proper formatting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "pretty.json"
            registry = Registry(file_path)

            test_data = {"node-b": {"module": "test.b"}, "node-a": {"module": "test.a"}}
            registry.save(test_data)

            content = file_path.read_text()
            # Check indentation
            assert "  " in content
            # Check sorting (a should come before b)
            assert content.index("node-a") < content.index("node-b")

    def test_save_overwrites_existing(self):
        """Test save completely replaces existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "overwrite.json"

            # Write initial data
            registry = Registry(file_path)
            registry.save({"old": {"data": "value"}})

            # Save new data
            new_data = {"new": {"data": "different"}}
            registry.save(new_data)

            # Verify old data is gone
            loaded = json.loads(file_path.read_text())
            assert loaded == new_data
            assert "old" not in loaded

    def test_save_permission_error(self):
        """Test save raises on permission errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Make directory read-only
            Path(tmpdir).chmod(0o555)

            try:
                file_path = Path(tmpdir) / "noperm.json"
                registry = Registry(file_path)

                with pytest.raises(PermissionError):
                    registry.save({"test": {"data": "value"}})
            finally:
                # Restore permissions for cleanup
                Path(tmpdir).chmod(0o755)


class TestRegistryUpdateFromScanner:
    """Test Registry update_from_scanner functionality."""

    def test_converts_list_to_dict(self):
        """Test scanner list format is converted to dict format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Registry(Path(tmpdir) / "test.json")

            scan_results = [
                {
                    "name": "test-node",
                    "module": "pflow.nodes.test",
                    "class_name": "TestNode",
                    "docstring": "Test",
                    "file_path": "/path/test.py",
                }
            ]

            registry.update_from_scanner(scan_results)

            # Load and verify
            saved_data = json.loads(registry.registry_path.read_text())
            assert "test-node" in saved_data
            assert saved_data["test-node"]["module"] == "pflow.nodes.test"
            # Name should not be in the stored data
            assert "name" not in saved_data["test-node"]

    def test_duplicate_names_warning(self):
        """Test warning is logged for duplicate node names."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Registry(Path(tmpdir) / "test.json")

            scan_results = [
                {"name": "duplicate", "module": "first.module"},
                {"name": "unique", "module": "unique.module"},
                {"name": "duplicate", "module": "second.module"},
            ]

            with patch.object(logging.getLogger("pflow.registry.registry"), "warning") as mock_warning:
                registry.update_from_scanner(scan_results)

                # Check warning was called
                warning_calls = [str(call) for call in mock_warning.call_args_list]
                assert any("Duplicate node names" in call for call in warning_calls)
                assert any("duplicate" in call for call in warning_calls)

            # Verify last-wins behavior
            saved_data = json.loads(registry.registry_path.read_text())
            assert saved_data["duplicate"]["module"] == "second.module"

    def test_missing_name_field(self):
        """Test nodes without name field are skipped with warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Registry(Path(tmpdir) / "test.json")

            scan_results = [
                {"module": "no.name.module"},  # Missing name
                {"name": "valid", "module": "valid.module"},
            ]

            with patch.object(logging.getLogger("pflow.registry.registry"), "warning") as mock_warning:
                registry.update_from_scanner(scan_results)

                # Check warning about missing name
                warning_calls = [str(call) for call in mock_warning.call_args_list]
                assert any("missing 'name'" in call for call in warning_calls)

            # Only valid node should be saved
            saved_data = json.loads(registry.registry_path.read_text())
            assert len(saved_data) == 1
            assert "valid" in saved_data

    def test_empty_scan_results(self):
        """Test empty scan results creates empty registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Registry(Path(tmpdir) / "test.json")

            registry.update_from_scanner([])

            saved_data = json.loads(registry.registry_path.read_text())
            assert saved_data == {}


class TestRegistryIntegration:
    """Integration tests with real scanner output."""

    def test_scanner_to_registry_workflow(self):
        """Test full workflow from scanner output to persisted registry."""
        # Simulate real scanner output format
        scanner_output = [
            {
                "module": "pflow.nodes.file.read_file",
                "class_name": "ReadFileNode",
                "name": "read-file",
                "docstring": "Read file contents.\n\nReads a file and returns its contents.",
                "file_path": "/home/user/pflow/src/pflow/nodes/file/read_file.py",
            },
            {
                "module": "pflow.nodes.llm.llm_node",
                "class_name": "LLMNode",
                "name": "llm",
                "docstring": "Process text with LLM.",
                "file_path": "/home/user/pflow/src/pflow/nodes/llm/llm_node.py",
            },
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test_registry.json"
            registry = Registry(registry_path)

            # Update registry with scanner output
            registry.update_from_scanner(scanner_output)

            # Create new registry instance and load
            registry2 = Registry(registry_path)
            loaded_data = registry2.load()

            # Verify data persistence and format
            assert len(loaded_data) == 2
            assert "read-file" in loaded_data
            assert "llm" in loaded_data

            # Check data integrity
            assert loaded_data["read-file"]["module"] == "pflow.nodes.file.read_file"
            assert loaded_data["read-file"]["class_name"] == "ReadFileNode"
            assert "Read file contents" in loaded_data["read-file"]["docstring"]

            # Verify names are not stored in values
            assert "name" not in loaded_data["read-file"]
            assert "name" not in loaded_data["llm"]

    def test_real_scanner_integration(self):
        """Test integration with actual scanner module."""
        from pflow.registry.scanner import scan_for_nodes

        # Get path to test nodes
        project_root = Path(__file__).parent.parent
        nodes_dir = project_root / "src" / "pflow" / "nodes"

        if nodes_dir.exists():
            # Run scanner
            scan_results = scan_for_nodes([nodes_dir])

            # Create registry and update
            with tempfile.TemporaryDirectory() as tmpdir:
                registry_path = Path(tmpdir) / "test_registry.json"
                registry = Registry(registry_path)

                registry.update_from_scanner(scan_results)

                # Verify file was created
                assert registry_path.exists()

                # Load and verify
                loaded = registry.load()

                # Should have found our test nodes
                assert len(loaded) > 0
                assert "test" in loaded  # TestNode
                assert "custom-name" in loaded  # NamedNode

                # Verify structure
                for _name, metadata in loaded.items():
                    assert "module" in metadata
                    assert "class_name" in metadata
                    assert "docstring" in metadata
                    assert "file_path" in metadata
                    assert "name" not in metadata  # Name is the key, not in value


class TestGetNodesMetadata:
    """Test Registry.get_nodes_metadata functionality."""

    def test_valid_node_types(self):
        """Test with valid node types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            # Set up test data
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
                "write-file": {
                    "module": "pflow.nodes.file.write",
                    "class_name": "WriteFileNode",
                    "docstring": "Write file node",
                    "file_path": "/path/write.py",
                },
            }
            registry.save(test_data)

            # Test getting specific nodes
            result = registry.get_nodes_metadata(["llm", "read-file"])

            assert len(result) == 2
            assert "llm" in result
            assert "read-file" in result
            assert result["llm"] == test_data["llm"]
            assert result["read-file"] == test_data["read-file"]
            assert "write-file" not in result

    def test_mix_valid_invalid(self):
        """Test with mix of valid and invalid node types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            # Set up test data
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
            registry.save(test_data)

            # Request mix of valid and non-existent nodes
            result = registry.get_nodes_metadata(["llm", "non-existent", "read-file"])

            assert len(result) == 2
            assert "llm" in result
            assert "read-file" in result
            assert "non-existent" not in result
            assert result["llm"] == test_data["llm"]
            assert result["read-file"] == test_data["read-file"]

    def test_empty_collection(self):
        """Test with empty collection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            # Set up test data
            test_data = {"llm": {"module": "pflow.nodes.llm", "class_name": "LLMNode"}}
            registry.save(test_data)

            # Test with empty list
            result = registry.get_nodes_metadata([])
            assert result == {}

            # Test with empty set
            result = registry.get_nodes_metadata(set())
            assert result == {}

            # Test with empty tuple
            result = registry.get_nodes_metadata(())
            assert result == {}

    def test_none_input(self):
        """Test with None input raises TypeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            with pytest.raises(TypeError, match="node_types cannot be None"):
                registry.get_nodes_metadata(None)

    def test_non_string_items(self):
        """Test with non-string items in collection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "test.json"
            registry = Registry(registry_path)

            # Set up test data
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
            registry.save(test_data)

            # Test with mixed types including non-strings
            result = registry.get_nodes_metadata(["llm", 123, "read-file", None, {"dict": "value"}, 45.6])

            # Should only include string matches
            assert len(result) == 2
            assert "llm" in result
            assert "read-file" in result
            assert result["llm"] == test_data["llm"]
            assert result["read-file"] == test_data["read-file"]

    def test_empty_registry(self):
        """Test with empty/missing registry file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "missing.json"
            registry = Registry(registry_path)

            # Registry file doesn't exist
            result = registry.get_nodes_metadata(["llm", "read-file"])

            assert result == {}


class TestRegistryEdgeCases:
    """Test registry behavior with edge cases and error scenarios."""

    def test_unicode_handling(self):
        """Test registry handles unicode in node names and docstrings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "unicode_test.json"
            registry = Registry(registry_path)

            # Create scanner output with unicode
            scan_results = [
                {
                    "name": "emoji-node-🚀",
                    "module": "test.emoji",
                    "class_name": "EmojiNode",
                    "docstring": "Unicode test: 你好世界 🌍",
                    "file_path": "/test/emoji.py",
                },
                {
                    "name": "special-chars-λ",
                    "module": "test.special",
                    "class_name": "SpecialNode",
                    "docstring": "Lambda λ, Pi π, Sigma Σ",
                    "file_path": "/test/special.py",
                },
            ]

            # Update and verify
            registry.update_from_scanner(scan_results)
            loaded = registry.load()

            assert "emoji-node-🚀" in loaded
            assert loaded["emoji-node-🚀"]["docstring"] == "Unicode test: 你好世界 🌍"
            assert "special-chars-λ" in loaded

    def test_partial_scanner_failures(self):
        """Test registry update when scanner has some failures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "partial_test.json"
            registry = Registry(registry_path)

            # Mix of valid and invalid nodes
            scan_results = [
                {
                    "name": "valid-node",
                    "module": "test.valid",
                    "class_name": "ValidNode",
                    "docstring": "This is valid",
                    "file_path": "/test/valid.py",
                },
                {
                    # Missing name - should be skipped with warning
                    "module": "test.invalid",
                    "class_name": "InvalidNode",
                    "file_path": "/test/invalid.py",
                },
                {
                    "name": "another-valid",
                    "module": "test.another",
                    "class_name": "AnotherNode",
                    "docstring": "Also valid",
                    "file_path": "/test/another.py",
                },
            ]

            with patch.object(logging.getLogger("pflow.registry.registry"), "warning") as mock_warn:
                registry.update_from_scanner(scan_results)

                # Should warn about missing name
                assert mock_warn.called
                warning_args = str(mock_warn.call_args)
                assert "missing 'name'" in warning_args

            # Should save only valid nodes
            loaded = registry.load()
            assert len(loaded) == 2
            assert "valid-node" in loaded
            assert "another-valid" in loaded

    def test_very_large_registry(self):
        """Test registry handles large number of nodes efficiently."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "large_test.json"
            registry = Registry(registry_path)

            # Create 1000 nodes
            scan_results = []
            for i in range(1000):
                scan_results.append({
                    "name": f"node-{i:04d}",
                    "module": f"test.nodes.node_{i}",
                    "class_name": f"Node{i}",
                    "docstring": f"Test node {i} with some documentation",
                    "file_path": f"/test/nodes/node_{i}.py",
                })

            # Time the update (should be reasonably fast)
            import time

            start = time.time()
            registry.update_from_scanner(scan_results)
            duration = time.time() - start

            # Should complete in reasonable time (< 1 second)
            assert duration < 1.0

            # Verify all nodes saved
            loaded = registry.load()
            assert len(loaded) == 1000
            assert "node-0500" in loaded

    def test_registry_file_corruption_recovery(self):
        """Test registry handles various corruption scenarios."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "corrupt_test.json"
            registry = Registry(registry_path)

            # Test 1: Truncated JSON
            registry_path.write_text('{"incomplete": "json')
            result = registry.load()
            assert result == {}  # Should return empty dict

            # Test 2: Invalid JSON structure (array instead of dict)
            registry_path.write_text('["not", "a", "dict"]')
            result = registry.load()
            # Current implementation returns the parsed JSON, not empty dict
            assert result == ["not", "a", "dict"]

            # Test 3: Nested corruption
            registry_path.write_text('{"node": {"bad": }')
            result = registry.load()
            assert result == {}  # Should return empty dict

    def test_concurrent_registry_updates(self):
        """Test registry behavior with simulated concurrent access."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "concurrent_test.json"

            # Create two registry instances (simulating concurrent processes)
            registry1 = Registry(registry_path)
            registry2 = Registry(registry_path)

            # First update
            registry1.update_from_scanner([
                {
                    "name": "node-1",
                    "module": "test.node1",
                    "class_name": "Node1",
                    "docstring": "First node",
                    "file_path": "/test/node1.py",
                }
            ])

            # Second update (would overwrite first in current implementation)
            registry2.update_from_scanner([
                {
                    "name": "node-2",
                    "module": "test.node2",
                    "class_name": "Node2",
                    "docstring": "Second node",
                    "file_path": "/test/node2.py",
                }
            ])

            # Load and verify - second update wins (complete replacement)
            final = Registry(registry_path).load()
            assert len(final) == 1
            assert "node-2" in final
            assert "node-1" not in final  # Lost due to overwrite

    def test_error_recovery_integration(self):
        """Test full scanner->registry workflow with various errors."""
        from pflow.registry.scanner import scan_for_nodes

        with tempfile.TemporaryDirectory() as tmpdir:
            error_dir = Path(tmpdir) / "errors"
            error_dir.mkdir()

            # Create files with various errors
            (error_dir / "syntax_error.py").write_text("def broken(: pass")
            (error_dir / "import_error.py").write_text("""
import nonexistent
from pocketflow import BaseNode
class Node(BaseNode):
    def exec(self, shared): pass
""")

            # Create one valid node
            (error_dir / "valid.py").write_text('''
from pocketflow import BaseNode
class ValidNode(BaseNode):
    """A valid node among errors."""
    def exec(self, shared): pass
''')

            registry_path = Path(tmpdir) / "error_test.json"
            registry = Registry(registry_path)

            # Add paths for imports
            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            import sys

            sys.path.insert(0, str(project_root))
            sys.path.insert(0, str(pocketflow_path))
            sys.path.insert(0, str(error_dir))

            try:
                # Scan directory with errors
                results = scan_for_nodes([error_dir])

                # Update registry
                registry.update_from_scanner(results)

                # Registry should exist
                assert registry_path.exists()

                # Should have found the valid node
                loaded = registry.load()
                assert isinstance(loaded, dict)
                assert len(loaded) == 1
                assert "valid" in loaded
            finally:
                # Clean up sys.path
                sys.path.remove(str(error_dir))
                sys.path.remove(str(pocketflow_path))
                sys.path.remove(str(project_root))

    def test_registry_path_edge_cases(self):
        """Test registry with unusual path scenarios."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test 1: Very deep path
            deep_path = Path(tmpdir) / "a" / "b" / "c" / "d" / "e" / "registry.json"
            registry = Registry(deep_path)
            registry.save({"test": {"module": "test"}})
            assert deep_path.exists()

            # Test 2: Path with spaces
            space_path = Path(tmpdir) / "path with spaces" / "registry.json"
            registry = Registry(space_path)
            registry.save({"test": {"module": "test"}})
            assert space_path.exists()

            # Test 3: Path with special characters (if OS allows)
            special_path = Path(tmpdir) / "special-chars_123" / "registry.json"
            registry = Registry(special_path)
            registry.save({"test": {"module": "test"}})
            assert special_path.exists()

    def test_registry_performance_baseline(self):
        """Establish performance baseline for registry operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "perf_test.json"
            registry = Registry(registry_path)

            # Create a moderately large dataset
            nodes = {}
            for i in range(100):
                nodes[f"node-{i}"] = {
                    "module": f"test.node{i}",
                    "class_name": f"Node{i}",
                    "docstring": "x" * 1000,  # 1KB docstring
                    "file_path": f"/test/node{i}.py",
                }

            # Test save performance
            import time

            start = time.time()
            registry.save(nodes)
            save_time = time.time() - start

            # Test load performance
            start = time.time()
            loaded = registry.load()
            load_time = time.time() - start

            # Performance assertions (reasonable for 100 nodes)
            assert save_time < 0.1  # Should save in < 100ms
            assert load_time < 0.1  # Should load in < 100ms
            assert len(loaded) == 100
