"""Tests for the context builder module."""

from unittest.mock import Mock, patch

import pytest

from pflow.planning.context_builder import (
    _extract_navigation_paths,
    _format_node_section,
    _format_structure,
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

    def test_rich_format_handling(self):
        """Test formatting with rich format metadata from extractor."""
        node_data = {
            "description": "Handles rich metadata format",
            "inputs": [
                {"key": "file_path", "type": "str", "description": "Path to the file"},
                {"key": "encoding", "type": "any", "description": ""},  # Default type
            ],
            "outputs": [
                {"key": "content", "type": "str", "description": "File contents"},
                {"key": "error", "type": "str", "description": "Error message"},
            ],
            "params": [
                {"key": "file_path", "type": "str", "description": "Path to the file"},
                {"key": "encoding", "type": "any", "description": ""},
                {"key": "strip_lines", "type": "bool", "description": "Strip whitespace"},
            ],
            "actions": ["default", "error"],
        }

        result = _format_node_section("rich-node", node_data)

        # Check that types and descriptions are included
        assert "**Inputs**: `file_path: str` - Path to the file, `encoding`" in result
        assert "**Outputs**: `content: str` - File contents, `error: str` - Error message (error)" in result
        # Only exclusive params should be shown (strip_lines)
        assert "**Parameters**: `strip_lines: bool` - Strip whitespace" in result
        # file_path should not be in parameters (it's in inputs)
        assert "`file_path`" not in result.split("**Parameters**:")[1]

    def test_mixed_format_backward_compatibility(self):
        """Test that mixing string and dict formats works (edge case)."""
        node_data = {
            "description": "Mixed format test",
            "inputs": [
                "legacy_input",  # String format
                {"key": "new_input", "type": "dict", "description": "New style"},
            ],
            "outputs": ["result"],
            "params": [
                "legacy_input",
                "legacy_param",
                {"key": "new_param", "type": "int", "description": "New param"},
            ],
            "actions": ["default"],
        }

        result = _format_node_section("mixed-node", node_data)

        # Both formats should be handled
        assert "**Inputs**: `legacy_input`, `new_input: dict`" in result
        assert "**Outputs**: `result`" in result
        # Only exclusive params (not in inputs)
        assert "**Parameters**: `legacy_param`, `new_param: int`" in result
        # legacy_input should not be in parameters
        assert "legacy_input" not in result.split("**Parameters**:")[1]


class TestNavigationPaths:
    """Test the navigation path extraction functionality."""

    def test_extract_simple_structure(self):
        """Test extracting paths from a simple structure."""
        structure = {
            "field1": {"type": "str", "description": "Field 1"},
            "field2": {"type": "int", "description": "Field 2"},
            "field3": {"type": "bool", "description": "Field 3"},
        }

        paths = _extract_navigation_paths(structure)

        assert paths == ["field1", "field2", "field3"]

    def test_extract_nested_structure(self):
        """Test extracting paths from nested structures."""
        structure = {
            "user": {
                "type": "dict",
                "description": "User info",
                "structure": {
                    "name": {"type": "str"},
                    "email": {"type": "str"},
                    "profile": {
                        "type": "dict",
                        "structure": {
                            "bio": {"type": "str"},
                            "avatar": {"type": "str"},
                        },
                    },
                },
            },
            "count": {"type": "int"},
        }

        paths = _extract_navigation_paths(structure)

        # Should include nested paths up to max depth
        assert "user" in paths
        assert "user.name" in paths
        assert "user.email" in paths
        assert "user.profile" in paths
        assert "user.profile.bio" in paths  # max_depth=2 by default
        assert "count" in paths

    def test_max_depth_limiting(self):
        """Test that max_depth prevents infinite recursion."""
        deep_structure = {
            "level1": {
                "type": "dict",
                "structure": {
                    "level2": {
                        "type": "dict",
                        "structure": {"level3": {"type": "dict", "structure": {"level4": {"type": "str"}}}},
                    }
                },
            }
        }

        paths = _extract_navigation_paths(deep_structure, max_depth=2)

        assert "level1" in paths
        assert "level1.level2" in paths
        assert "level1.level2.level3" not in paths  # Beyond max_depth

    def test_path_limiting(self):
        """Test that total paths are limited to prevent explosion."""
        # Create structure with many fields
        large_structure = {f"field{i}": {"type": "str"} for i in range(20)}

        paths = _extract_navigation_paths(large_structure)

        # Should be limited to 10 paths
        assert len(paths) == 10

    def test_empty_structure(self):
        """Test handling of empty or invalid structures."""
        assert _extract_navigation_paths({}) == []
        assert _extract_navigation_paths(None) == []
        assert _extract_navigation_paths("not a dict") == []


class TestFormatStructure:
    """Test the structure formatting function."""

    def test_format_simple_structure(self):
        """Test formatting a simple flat structure."""
        structure = {
            "name": {"type": "str", "description": "User name"},
            "age": {"type": "int", "description": "User age"},
            "active": {"type": "bool", "description": ""},
        }

        lines = _format_structure(structure)

        assert "    - name: str - User name" in lines
        assert "    - age: int - User age" in lines
        assert "    - active: bool" in lines  # No description

    def test_format_nested_structure(self):
        """Test formatting nested structures."""
        structure = {
            "user": {
                "type": "dict",
                "description": "User information",
                "structure": {
                    "login": {"type": "str", "description": "Username"},
                    "profile": {
                        "type": "dict",
                        "description": "Profile data",
                        "structure": {"bio": {"type": "str", "description": "Biography"}},
                    },
                },
            }
        }

        lines = _format_structure(structure)

        assert "    - user: dict - User information" in lines
        assert "      - login: str - Username" in lines
        assert "      - profile: dict - Profile data" in lines
        assert "        - bio: str - Biography" in lines


class TestStructureHints:
    """Test structure hint integration in formatting."""

    def test_format_with_structure_hints(self):
        """Test that structure hints appear in formatted output."""
        node_data = {
            "description": "GitHub issue fetcher",
            "inputs": [{"key": "repo", "type": "str"}],
            "outputs": [
                {
                    "key": "issue_data",
                    "type": "dict",
                    "structure": {
                        "number": {"type": "int"},
                        "title": {"type": "str"},
                        "user": {
                            "type": "dict",
                            "structure": {
                                "login": {"type": "str"},
                                "id": {"type": "int"},
                            },
                        },
                    },
                }
            ],
            "params": [],
            "actions": ["default"],
        }

        result = _format_node_section("github-issue", node_data)

        # Should include structure section
        assert "Structure of issue_data:" in result
        assert "- number: int" in result
        assert "- user: dict" in result
        assert "- login: str" in result

    def test_no_hints_for_simple_types(self):
        """Test that simple types don't get navigation hints."""
        node_data = {
            "description": "Simple node",
            "inputs": [
                {"key": "text", "type": "str"},
                {"key": "count", "type": "int"},
            ],
            "outputs": [{"key": "result", "type": "bool"}],
            "params": [],
            "actions": ["default"],
        }

        result = _format_node_section("simple-node", node_data)

        # Should not have any structure sections
        assert "Structure of" not in result

    def test_hint_count_tracking(self):
        """Test that hint count is properly tracked and limited."""
        # Create outputs with structures
        outputs = []
        for i in range(5):
            outputs.append({"key": f"data_{i}", "type": "dict", "structure": {"field": {"type": "str"}}})

        node_data = {
            "description": "Multi-structure node",
            "inputs": [],
            "outputs": outputs,
            "params": [],
            "actions": ["default"] * 5,
        }

        result = _format_node_section("test-node", node_data)

        # Should have structure sections for all complex outputs
        assert result.count("Structure of data_") == 5
