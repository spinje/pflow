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
        custom_path = Path("/tmp/custom/registry.json")
        registry = Registry(custom_path)
        assert registry.registry_path == custom_path

    def test_path_conversion(self):
        """Test string path is converted to Path object."""
        registry = Registry("/tmp/test.json")
        assert isinstance(registry.registry_path, Path)
        assert registry.registry_path == Path("/tmp/test.json")


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

                with pytest.raises(Exception):
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
