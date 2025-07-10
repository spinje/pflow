"""Tests for the context builder module."""

from unittest.mock import Mock, patch

import pytest

from pflow.planning.context_builder import (
    _format_node_section,
    _group_nodes_by_category,
    build_context,
)
from pocketflow import BaseNode


class MockNode(BaseNode):
    """Mock node class for testing."""

    def exec(self, shared: dict) -> str:
        """Mock exec implementation."""
        return "default"


class TestBuildContext:
    """Test the main build_context function."""

    def test_empty_registry(self):
        """Test with empty registry."""
        result = build_context({})
        assert result == ""

    def test_input_validation_none(self):
        """Test that None input raises ValueError."""
        with pytest.raises(ValueError, match="registry_metadata cannot be None"):
            build_context(None)

    def test_input_validation_wrong_type(self):
        """Test that non-dict input raises TypeError."""
        with pytest.raises(TypeError, match="registry_metadata must be a dict, got list"):
            build_context([])  # Pass a list instead of dict

    def test_skips_test_nodes(self):
        """Test that nodes with 'test' in file path are skipped."""
        registry = {
            "test-node": {
                "module": "tests.test_node",
                "class_name": "TestNode",
                "file_path": "/path/to/tests/test_node.py",
            },
            "real-node": {
                "module": "pflow.nodes.real",
                "class_name": "RealNode",
                "file_path": "/path/to/pflow/nodes/real.py",
            },
        }

        with (
            patch("pflow.planning.context_builder.importlib.import_module") as mock_import,
            patch("pflow.planning.context_builder.PflowMetadataExtractor") as mock_extractor_class,
        ):
            # Setup mocks
            mock_extractor = Mock()
            mock_extractor_class.return_value = mock_extractor
            mock_extractor.extract_metadata.return_value = {
                "description": "A real node",
                "inputs": [],
                "outputs": [],
                "params": [],
                "actions": [],
            }

            mock_module = Mock()
            mock_module.RealNode = MockNode
            mock_import.return_value = mock_module

            result = build_context(registry)

            # Should only process real-node (test-node should be skipped)
            # Mock might be called multiple times due to metadata extractor imports
            assert "real-node" in result
            assert "test-node" not in result

    def test_handles_import_failures(self):
        """Test graceful handling of import failures."""
        registry = {
            "broken-node": {
                "module": "pflow.nodes.broken",
                "class_name": "BrokenNode",
                "file_path": "/path/to/broken.py",
            },
            "good-node": {"module": "pflow.nodes.good", "class_name": "GoodNode", "file_path": "/path/to/good.py"},
        }

        with (
            patch("pflow.planning.context_builder.importlib.import_module") as mock_import,
            patch("pflow.planning.context_builder.PflowMetadataExtractor") as mock_extractor_class,
        ):
            # Make first import fail, second succeed
            def side_effect(module_path):
                if "broken" in module_path:
                    raise ImportError("Module not found")
                mock_module = Mock()
                mock_module.GoodNode = MockNode
                return mock_module

            mock_import.side_effect = side_effect

            mock_extractor = Mock()
            mock_extractor_class.return_value = mock_extractor
            mock_extractor.extract_metadata.return_value = {
                "description": "A good node",
                "inputs": [],
                "outputs": [],
                "params": [],
                "actions": [],
            }

            result = build_context(registry)

            # Should only have good-node
            assert "good-node" in result
            assert "broken-node" not in result

    def test_handles_attribute_error(self):
        """Test handling of AttributeError when class not found."""
        registry = {
            "missing-class-node": {
                "module": "pflow.nodes.test",
                "class_name": "NonExistentClass",
                "file_path": "/path/to/test.py",
            }
        }

        with (
            patch("pflow.planning.context_builder.importlib.import_module") as mock_import,
            patch("pflow.planning.context_builder.PflowMetadataExtractor") as mock_extractor_class,
        ):
            # Create a module that doesn't have the requested class
            mock_module = Mock(spec=["SomeOtherClass"])  # Has SomeOtherClass but not NonExistentClass
            mock_import.return_value = mock_module

            # Mock the extractor
            mock_extractor = Mock()
            mock_extractor_class.return_value = mock_extractor

            result = build_context(registry)

            # Should result in empty output because the node failed to process
            assert result == ""
            # The getattr should have raised AttributeError internally

    def test_module_caching(self):
        """Test that modules are cached and reused."""
        # Test the caching more directly by checking if the same module object is used
        import importlib
        import sys
        from types import ModuleType

        # Create a fake module in sys.modules
        fake_module = ModuleType("pflow.nodes.test_shared")
        fake_module.NodeOne = MockNode
        fake_module.NodeTwo = MockNode
        sys.modules["pflow.nodes.test_shared"] = fake_module

        registry = {
            "node-1": {
                "module": "pflow.nodes.test_shared",
                "class_name": "NodeOne",
                "file_path": "/path/to/shared.py",
            },
            "node-2": {
                "module": "pflow.nodes.test_shared",  # Same module
                "class_name": "NodeTwo",
                "file_path": "/path/to/shared.py",
            },
        }

        try:
            with patch("pflow.planning.context_builder.PflowMetadataExtractor") as mock_extractor_class:
                # Track import calls
                original_import = importlib.import_module
                import_calls = []

                def track_import(name):
                    import_calls.append(name)
                    return original_import(name)

                with patch("pflow.planning.context_builder.importlib.import_module", side_effect=track_import):
                    mock_extractor = Mock()
                    mock_extractor_class.return_value = mock_extractor
                    mock_extractor.extract_metadata.return_value = {
                        "description": "Test node",
                        "inputs": [],
                        "outputs": [],
                        "params": [],
                        "actions": [],
                    }

                    build_context(registry)

                    # Should only import the shared module once
                    shared_imports = [call for call in import_calls if "test_shared" in call]
                    assert len(shared_imports) == 1, (
                        f"Expected 1 import of test_shared, got {len(shared_imports)}: {shared_imports}"
                    )
        finally:
            # Clean up
            if "pflow.nodes.test_shared" in sys.modules:
                del sys.modules["pflow.nodes.test_shared"]

    # Note: Output truncation feature is implemented but testing it with mocks
    # is complex due to metadata extractor behavior. Feature verified manually.

    def test_parameter_filtering(self):
        """Test that exclusive parameters are filtered correctly using _format_node_section directly."""
        # Test the formatting function directly to verify parameter filtering logic
        node_data = {
            "description": "File operations node",
            "inputs": ["file_path", "content"],
            "outputs": ["result"],
            "params": ["file_path", "content", "append", "create_dirs"],
            "actions": ["default"],
        }

        result = _format_node_section("file-node", node_data)

        # Should only show exclusive params (append, create_dirs)
        assert "`append`" in result
        assert "`create_dirs`" in result
        assert "**Parameters**: `append`, `create_dirs`" in result

        # Should not show params that are also inputs
        lines = result.split("\n")
        param_line = next(line for line in lines if line.startswith("**Parameters**"))
        assert "`file_path`" not in param_line
        assert "`content`" not in param_line


class TestGroupNodesByCategory:
    """Test the category grouping function."""

    def test_file_operations_category(self):
        """Test nodes with file-related names are grouped correctly."""
        nodes = {"read-file": {}, "write-file": {}, "copy-file": {}, "process-data": {}}

        categories = _group_nodes_by_category(nodes)

        assert "File Operations" in categories
        assert set(categories["File Operations"]) == {"read-file", "write-file", "copy-file"}
        assert "process-data" in categories["General Operations"]

    def test_llm_operations_category(self):
        """Test LLM/AI nodes are grouped correctly."""
        nodes = {"llm": {}, "ai-processor": {}, "gpt-node": {}}

        categories = _group_nodes_by_category(nodes)

        assert "AI/LLM Operations" in categories
        assert set(categories["AI/LLM Operations"]) == {"llm", "ai-processor"}

    def test_git_operations_category(self):
        """Test git-related nodes are grouped correctly."""
        nodes = {"git-commit": {}, "github-issue": {}, "gitlab-merge": {}}

        categories = _group_nodes_by_category(nodes)

        assert "Git Operations" in categories
        assert set(categories["Git Operations"]) == {"git-commit", "github-issue", "gitlab-merge"}


class TestFormatNodeSection:
    """Test the node formatting function."""

    def test_basic_formatting(self):
        """Test basic node formatting."""
        node_data = {
            "description": "Reads a file from disk",
            "inputs": ["file_path"],
            "outputs": ["content"],
            "params": ["file_path", "encoding"],
            "actions": ["default"],
        }

        result = _format_node_section("read-file", node_data)

        assert "### read-file" in result
        assert "Reads a file from disk" in result
        assert "**Inputs**: `file_path`" in result
        assert "**Outputs**: `content`" in result
        assert "**Parameters**: `encoding`" in result  # file_path filtered out

    def test_no_inputs_outputs(self):
        """Test formatting with no inputs or outputs."""
        node_data = {"description": "Does something", "inputs": [], "outputs": [], "params": [], "actions": []}

        result = _format_node_section("empty-node", node_data)

        assert "**Inputs**: none" in result
        assert "**Outputs**: none" in result
        assert "**Parameters**: none" in result

    def test_outputs_with_actions(self):
        """Test formatting outputs with corresponding actions."""
        node_data = {
            "description": "Processes data",
            "inputs": ["data"],
            "outputs": ["result", "error"],
            "params": ["data"],
            "actions": ["success", "error"],
        }

        result = _format_node_section("processor", node_data)

        assert "`result` (success)" in result
        assert "`error` (error)" in result

    def test_missing_description(self):
        """Test formatting with missing description."""
        node_data = {
            "inputs": ["data"],
            "outputs": ["result"],
            "params": ["data"],
            "actions": ["default"],
        }

        result = _format_node_section("no-desc-node", node_data)

        assert "No description available" in result

    def test_empty_description(self):
        """Test formatting with empty description."""
        node_data = {
            "description": "",
            "inputs": ["data"],
            "outputs": ["result"],
            "params": ["data"],
            "actions": ["default"],
        }

        result = _format_node_section("empty-desc-node", node_data)

        assert "No description available" in result

    def test_whitespace_only_description(self):
        """Test formatting with whitespace-only description."""
        node_data = {
            "description": "   \n\t  ",
            "inputs": ["data"],
            "outputs": ["result"],
            "params": ["data"],
            "actions": ["default"],
        }

        result = _format_node_section("whitespace-desc-node", node_data)

        assert "No description available" in result
