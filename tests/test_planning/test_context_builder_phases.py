"""Tests for two-phase context building functions."""

from unittest.mock import patch

import pytest

from pflow.planning.context_builder import (
    _format_exclusive_parameters,
    _format_node_section_enhanced,
    _format_structure_combined,
    _group_nodes_by_category,
    _process_nodes,
    build_discovery_context,
    build_planning_context,
)
from pocketflow import BaseNode


class MockNode(BaseNode):
    """Mock node class for testing."""

    def exec(self, shared: dict) -> str:
        """Mock exec implementation."""
        return "default"


class TestDiscoveryContext:
    """Tests for build_discovery_context function."""

    def test_discovery_context_input_validation(self):
        """Test input validation for discovery context."""
        # Test invalid node_ids type
        with pytest.raises(TypeError, match="node_ids must be a list or None, got str"):
            build_discovery_context(node_ids="github-node")

        # Test invalid workflow_names type
        with pytest.raises(TypeError, match="workflow_names must be a list or None, got dict"):
            build_discovery_context(workflow_names={"workflow": "name"})

        # Test invalid registry_metadata type
        with pytest.raises(TypeError, match="registry_metadata must be a dict or None, got list"):
            build_discovery_context(registry_metadata=[])

    def test_discovery_context_empty_registry(self):
        """Test discovery context with no nodes."""
        # Need to also mock _process_nodes to ensure empty registry behavior
        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = ({}, 0)  # Empty processed nodes
            with patch("pflow.planning.context_builder._load_saved_workflows", return_value=[]):
                context = build_discovery_context(registry_metadata={})

        assert "## Available Nodes" in context
        assert len(context.split("\n")) < 5  # Should be minimal

    def test_discovery_context_with_nodes(self):
        """Test discovery context shows only names and descriptions."""
        registry_metadata = {
            "read-file": {
                "module": "pflow.nodes.file.read_file",
                "class_name": "ReadFileNode",
                "file_path": "src/pflow/nodes/file/read_file.py",
            }
        }

        # Mock the metadata extraction
        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (
                {
                    "read-file": {
                        "description": "Read content from a file",
                        "inputs": [{"key": "file_path", "type": "str"}],
                        "outputs": [{"key": "content", "type": "str"}],
                        "params": [],
                        "actions": [],
                    }
                },
                0,
            )

            with patch("pflow.planning.context_builder._load_saved_workflows", return_value=[]):
                context = build_discovery_context(registry_metadata=registry_metadata)

        # Should contain name and description
        assert "### read-file" in context
        assert "Read content from a file" in context

        # Should NOT contain interface details
        assert "**Inputs**" not in context
        assert "**Outputs**" not in context
        assert "**Parameters**" not in context
        assert "file_path" not in context

    def test_discovery_context_omits_missing_descriptions(self):
        """Test that nodes without descriptions don't show placeholder text."""
        registry_metadata = {"no-desc-node": {"module": "test", "class_name": "TestNode"}}

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (
                {
                    "no-desc-node": {
                        "description": "",  # Empty description
                        "inputs": [],
                        "outputs": [],
                        "params": [],
                        "actions": [],
                    }
                },
                0,
            )

            with patch("pflow.planning.context_builder._load_saved_workflows", return_value=[]):
                context = build_discovery_context(registry_metadata=registry_metadata)

        # Should show name but no description or placeholder
        assert "### no-desc-node" in context
        assert "No description" not in context

        # Verify the node appears without description by checking
        # that it's either followed by an empty line or is the last item
        lines = context.split("\n")
        for i, line in enumerate(lines):
            if "### no-desc-node" in line:
                # Either it's the last line, or the next line is empty/another section
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    # Should be empty or start of another section
                    assert next_line == "" or next_line.startswith("##") or next_line.startswith("###")
                break

    def test_discovery_context_with_workflows(self):
        """Test discovery context includes workflows."""
        workflows = [
            {
                "name": "test-pipeline",
                "description": "Test workflow for data processing",
                "inputs": ["data"],
                "outputs": ["result"],
                "ir": {},
            }
        ]

        with patch("pflow.planning.context_builder._load_saved_workflows", return_value=workflows):
            context = build_discovery_context(registry_metadata={})

        assert "## Available Workflows" in context
        assert "### test-pipeline (workflow)" in context
        assert "Test workflow for data processing" in context
        assert "inputs" not in context.lower()  # No interface details

    def test_discovery_context_filtered_nodes(self):
        """Test discovery with filtered node IDs."""
        registry_metadata = {
            "node1": {"module": "test", "class_name": "Node1"},
            "node2": {"module": "test", "class_name": "Node2"},
            "node3": {"module": "test", "class_name": "Node3"},
        }

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (
                {
                    "node1": {"description": "Node 1", "inputs": [], "outputs": [], "params": [], "actions": []},
                    "node2": {"description": "Node 2", "inputs": [], "outputs": [], "params": [], "actions": []},
                    "node3": {"description": "Node 3", "inputs": [], "outputs": [], "params": [], "actions": []},
                },
                0,
            )

            with patch("pflow.planning.context_builder._load_saved_workflows", return_value=[]):
                context = build_discovery_context(node_ids=["node1", "node3"], registry_metadata=registry_metadata)

        assert "### node1" in context
        assert "### node3" in context
        assert "### node2" not in context

    def test_discovery_context_categories(self):
        """Test nodes are grouped by category."""
        registry_metadata = {
            "read-file": {"module": "test", "class_name": "ReadFile"},
            "llm": {"module": "test", "class_name": "LLM"},
        }

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (
                {
                    "read-file": {
                        "description": "Read files",
                        "inputs": [],
                        "outputs": [],
                        "params": [],
                        "actions": [],
                    },
                    "llm": {
                        "description": "LLM operations",
                        "inputs": [],
                        "outputs": [],
                        "params": [],
                        "actions": [],
                    },
                },
                0,
            )

            with patch("pflow.planning.context_builder._load_saved_workflows", return_value=[]):
                context = build_discovery_context(registry_metadata=registry_metadata)

        assert "### File Operations" in context
        assert "### AI/LLM Operations" in context


class TestPlanningContext:
    """Tests for build_planning_context function."""

    def test_planning_context_input_validation(self):
        """Test input validation for planning context."""
        registry = {"node1": {"module": "test", "class_name": "Test"}}

        # Test invalid selected_node_ids type
        with pytest.raises(TypeError, match="selected_node_ids must be a list, got str"):
            build_planning_context("node1", [], registry)

        # Test invalid selected_workflow_names type
        with pytest.raises(TypeError, match="selected_workflow_names must be a list, got str"):
            build_planning_context([], "workflow", registry)

        # Test invalid registry_metadata type
        with pytest.raises(TypeError, match="registry_metadata must be a dict, got list"):
            build_planning_context([], [], [])

        # Test invalid saved_workflows type
        with pytest.raises(TypeError, match="saved_workflows must be a list or None, got str"):
            build_planning_context([], [], registry, saved_workflows="invalid")

    def test_planning_context_missing_nodes(self):
        """Test error dict returned when nodes are missing."""
        registry_metadata = {"node1": {}, "node2": {}}

        result = build_planning_context(
            selected_node_ids=["node1", "node3"],  # node3 doesn't exist
            selected_workflow_names=[],
            registry_metadata=registry_metadata,
            saved_workflows=[],
        )

        assert isinstance(result, dict)
        assert "error" in result
        assert "missing_nodes" in result
        assert "missing_workflows" in result
        assert result["missing_nodes"] == ["node3"]
        assert result["missing_workflows"] == []
        assert "Unknown nodes: node3" in result["error"]

    def test_planning_context_missing_workflows(self):
        """Test error dict returned when workflows are missing."""
        workflows = [{"name": "workflow1", "description": "Test", "inputs": [], "outputs": [], "ir": {}}]

        result = build_planning_context(
            selected_node_ids=[],
            selected_workflow_names=["workflow1", "workflow2"],  # workflow2 doesn't exist
            registry_metadata={},
            saved_workflows=workflows,
        )

        assert isinstance(result, dict)
        assert result["missing_workflows"] == ["workflow2"]
        assert "Unknown workflows: workflow2" in result["error"]

    def test_planning_context_valid_selection(self):
        """Test planning context with valid component selection."""
        registry_metadata = {
            "test-node": {"module": "pflow.nodes.test", "class_name": "TestNode", "file_path": "test.py"}
        }

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (
                {
                    "test-node": {
                        "description": "Test node",
                        "inputs": [{"key": "input1", "type": "str", "description": "Test input"}],
                        "outputs": [{"key": "output1", "type": "str", "description": "Test output"}],
                        "params": [{"key": "param1", "type": "bool", "description": "Test param"}],
                        "actions": [],
                    }
                },
                0,
            )

            result = build_planning_context(
                selected_node_ids=["test-node"],
                selected_workflow_names=[],
                registry_metadata=registry_metadata,
                saved_workflows=[],
            )

        # Should return markdown string, not error dict
        assert isinstance(result, str)
        assert "## Selected Components" in result
        assert "### test-node" in result
        assert "**Inputs**:" in result
        assert "**Outputs**:" in result
        assert "**Parameters**:" in result

    def test_planning_context_structure_display(self):
        """Test enhanced structure display with JSON + paths."""
        registry_metadata = {"struct-node": {"module": "test", "class_name": "StructNode"}}

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (
                {
                    "struct-node": {
                        "description": "Node with structure",
                        "inputs": [],
                        "outputs": [
                            {
                                "key": "user_data",
                                "type": "dict",
                                "description": "User information",
                                "structure": {
                                    "id": {"type": "str", "description": "User ID"},
                                    "profile": {
                                        "type": "dict",
                                        "description": "Profile info",
                                        "structure": {
                                            "name": {"type": "str", "description": "Full name"},
                                            "age": {"type": "int", "description": "Age in years"},
                                        },
                                    },
                                },
                            }
                        ],
                        "params": [],
                        "actions": [],
                    }
                },
                0,
            )

            result = build_planning_context(
                selected_node_ids=["struct-node"],
                selected_workflow_names=[],
                registry_metadata=registry_metadata,
            )

        # Check JSON format section
        assert "Structure (JSON format):" in result
        assert "```json" in result
        assert '"user_data": {' in result
        assert '"id": "str"' in result
        assert '"profile": {' in result

        # Check paths section
        assert "Available paths:" in result
        assert "user_data.id (str) - User ID" in result
        assert "user_data.profile.name (str) - Full name" in result
        assert "user_data.profile.age (int) - Age in years" in result

    def test_planning_context_exclusive_params(self):
        """Test that params in inputs are excluded."""
        registry_metadata = {"param-node": {"module": "test", "class_name": "ParamNode"}}

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (
                {
                    "param-node": {
                        "description": "Node with params",
                        "inputs": [
                            {"key": "file_path", "type": "str"},
                            {"key": "encoding", "type": "str"},
                        ],
                        "outputs": [],
                        "params": [
                            {"key": "encoding", "type": "str"},  # Should be excluded
                            {"key": "validate", "type": "bool"},  # Should be included
                        ],
                        "actions": [],
                    }
                },
                0,
            )

            result = build_planning_context(
                selected_node_ids=["param-node"], selected_workflow_names=[], registry_metadata=registry_metadata
            )

        # Only validate should appear in parameters
        assert "validate: bool" in result
        # encoding should not appear in parameters section
        lines = result.split("\n")
        param_section_started = False
        for line in lines:
            if "**Parameters**:" in line:
                param_section_started = True
            elif param_section_started and line.strip() == "":
                break  # End of parameters section
            elif param_section_started and "encoding" in line:
                pytest.fail("encoding should not appear in parameters section")

    def test_planning_context_with_workflows(self):
        """Test planning context includes workflow details."""
        workflows = [
            {
                "name": "data-pipeline",
                "description": "Process data through steps",
                "inputs": ["raw_data", "config"],
                "outputs": ["processed_data", "report"],
                "version": "1.0.0",
                "tags": ["data", "etl"],
                "ir": {},
            }
        ]

        result = build_planning_context(
            selected_node_ids=[],
            selected_workflow_names=["data-pipeline"],
            registry_metadata={},
            saved_workflows=workflows,
        )

        assert isinstance(result, str)
        assert "## Selected Workflows" in result
        assert "### data-pipeline (workflow)" in result
        assert "Process data through steps" in result
        assert "**Inputs**:" in result
        assert "raw_data" in result
        assert "**Outputs**:" in result
        assert "processed_data" in result
        assert "**Version**: 1.0.0" in result
        assert "**Tags**: data, etl" in result


class TestStructureCombined:
    """Tests for _format_structure_combined helper."""

    def test_simple_structure(self):
        """Test formatting simple flat structure."""
        structure = {
            "field1": {"type": "str", "description": "First field"},
            "field2": {"type": "int", "description": "Second field"},
        }

        json_struct, paths = _format_structure_combined(structure)

        assert json_struct == {"field1": "str", "field2": "int"}
        assert len(paths) == 2
        assert ("field1", "str", "First field") in paths
        assert ("field2", "int", "Second field") in paths

    def test_nested_dict_structure(self):
        """Test formatting nested dictionary structure."""
        structure = {
            "user": {
                "type": "dict",
                "description": "User info",
                "structure": {
                    "name": {"type": "str", "description": "Username"},
                    "settings": {
                        "type": "dict",
                        "description": "User settings",
                        "structure": {"theme": {"type": "str", "description": "UI theme"}},
                    },
                },
            }
        }

        json_struct, paths = _format_structure_combined(structure)

        assert json_struct == {"user": {"name": "str", "settings": {"theme": "str"}}}
        assert len(paths) == 4
        assert ("user", "dict", "User info") in paths
        assert ("user.name", "str", "Username") in paths
        assert ("user.settings", "dict", "User settings") in paths
        assert ("user.settings.theme", "str", "UI theme") in paths

    def test_list_structure(self):
        """Test formatting list structure with array notation."""
        structure = {
            "items": {
                "type": "list",
                "description": "List of items",
                "structure": {
                    "id": {"type": "int", "description": "Item ID"},
                    "name": {"type": "str", "description": "Item name"},
                },
            }
        }

        json_struct, paths = _format_structure_combined(structure)

        assert json_struct == {"items": [{"id": "int", "name": "str"}]}
        assert ("items", "list", "List of items") in paths
        assert ("items[].id", "int", "Item ID") in paths
        assert ("items[].name", "str", "Item name") in paths

    def test_empty_structure(self):
        """Test handling empty structure."""
        structure = {}

        json_struct, paths = _format_structure_combined(structure)

        assert json_struct == {}
        assert paths == []


class TestSharedFunctionality:
    """Tests for shared functionality used by both old and new context builders."""

    # Note: The new discovery/planning functions don't have input validation
    # They use Optional types and handle None by loading from Registry
    # This is different from the old build_context() function

    def test_process_nodes_uses_interface_data(self):
        """Test _process_nodes uses pre-parsed interface data from registry."""
        registry = {
            "node-with-interface": {
                "module": "pflow.nodes.example",
                "class_name": "ExampleNode",
                "file_path": "/path/to/example.py",
                "interface": {
                    "description": "Example node",
                    "inputs": [{"key": "input1", "type": "str", "description": "Test input"}],
                    "outputs": [{"key": "output1", "type": "str", "description": "Test output"}],
                    "params": [{"key": "param1", "type": "any", "description": "Test param"}],
                    "actions": ["default", "error"],
                },
            },
            "node-without-interface": {
                "module": "pflow.nodes.broken",
                "class_name": "BrokenNode",
                "file_path": "/path/to/broken.py",
                # Missing interface field
            },
        }

        # First node should work
        nodes, _ = _process_nodes({"node-with-interface": registry["node-with-interface"]})
        assert "node-with-interface" in nodes
        assert nodes["node-with-interface"]["description"] == "Example node"
        assert len(nodes["node-with-interface"]["inputs"]) == 1
        assert nodes["node-with-interface"]["inputs"][0]["key"] == "input1"

        # Second node should fail
        with pytest.raises(ValueError, match="missing interface data"):
            _process_nodes({"node-without-interface": registry["node-without-interface"]})

    def test_process_nodes_requires_interface_field(self):
        """Test _process_nodes requires interface field in all nodes."""
        registry = {
            "legacy-node": {
                "module": "pflow.nodes.file.legacy",
                "class_name": "LegacyNode",
                "file_path": "/path/to/pflow/nodes/file/legacy.py",
                # No interface field - old format
            }
        }

        # Should raise error for missing interface
        with pytest.raises(ValueError, match="missing interface data"):
            _process_nodes(registry)

    def test_process_nodes_module_caching(self):
        """Test that _process_nodes no longer does module imports."""
        # This test is no longer relevant - _process_nodes uses pre-parsed data
        # Test that it processes nodes with interface data correctly
        registry = {
            "node-1": {
                "module": "pflow.nodes.test_shared",
                "class_name": "NodeOne",
                "file_path": "/path/to/shared.py",
                "interface": {
                    "description": "Test node one",
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": ["default"],
                },
            },
            "node-2": {
                "module": "pflow.nodes.test_shared",
                "class_name": "NodeTwo",
                "file_path": "/path/to/shared.py",
                "interface": {
                    "description": "Test node two",
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": ["default"],
                },
            },
        }

        # Process nodes with pre-parsed interface data
        processed, skipped = _process_nodes(registry)

        # Both nodes should be processed
        assert len(processed) == 2
        assert "node-1" in processed
        assert "node-2" in processed
        assert processed["node-1"]["description"] == "Test node one"
        assert processed["node-2"]["description"] == "Test node two"
        assert skipped == 0

    def test_process_nodes_skips_test_nodes(self):
        """Test that _process_nodes skips nodes with 'test' in file path."""
        registry = {
            "test-node": {
                "module": "tests.test_node",
                "class_name": "TestNode",
                "file_path": "/path/to/tests/test_node.py",
                "interface": {
                    "description": "Test node",
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": ["default"],
                },
            },
            "real-node": {
                "module": "pflow.nodes.real",
                "class_name": "RealNode",
                "file_path": "/path/to/pflow/nodes/real.py",
                "interface": {
                    "description": "A real node",
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": ["default"],
                },
            },
        }

        nodes, skipped_count = _process_nodes(registry)

        # Should only process real-node (test-node should be skipped)
        assert "real-node" in nodes
        assert "test-node" not in nodes
        assert skipped_count == 1


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_group_nodes_by_category_file_operations(self):
        """Test nodes with file-related names are grouped correctly."""
        nodes = {
            "read-file": {},
            "write-file": {},
            "copy-file": {},
            "process-data": {},
        }

        categories = _group_nodes_by_category(nodes)

        assert "File Operations" in categories
        assert set(categories["File Operations"]) == {"read-file", "write-file", "copy-file"}
        assert "process-data" in categories["General Operations"]

    def test_group_nodes_by_category_llm_operations(self):
        """Test LLM/AI nodes are grouped correctly."""
        nodes = {
            "llm": {},
            "ai-processor": {},
            "gpt-node": {},
        }

        categories = _group_nodes_by_category(nodes)

        assert "AI/LLM Operations" in categories
        assert set(categories["AI/LLM Operations"]) == {"llm", "ai-processor"}

    def test_group_nodes_by_category_git_operations(self):
        """Test git-related nodes are grouped correctly."""
        nodes = {
            "git-commit": {},
            "github-issue": {},
            "gitlab-merge": {},
        }

        categories = _group_nodes_by_category(nodes)

        assert "Git Operations" in categories
        assert set(categories["Git Operations"]) == {"git-commit", "github-issue", "gitlab-merge"}

    def test_format_exclusive_parameters(self):
        """Test that exclusive parameters are filtered correctly."""
        node_data = {
            "params": [
                {"key": "file_path", "type": "str"},
                {"key": "encoding", "type": "str"},
                {"key": "validate", "type": "bool"},
            ]
        }

        inputs = [
            {"key": "file_path", "type": "str"},
            {"key": "encoding", "type": "str"},
        ]

        lines = []
        _format_exclusive_parameters(node_data, inputs, lines)

        # Should only show validate (exclusive param)
        result = "\n".join(lines)
        assert "validate: bool" in result
        assert result.count("file_path") == 0
        assert result.count("encoding") == 0


class TestEnhancedFormatter:
    """Tests for the enhanced node section formatter."""

    def test_format_node_section_enhanced_basic(self):
        """Test basic node formatting with enhanced formatter."""
        node_data = {
            "description": "Reads a file from disk",
            "inputs": [{"key": "file_path", "type": "str", "description": "Path to file"}],
            "outputs": [{"key": "content", "type": "str", "description": "File contents"}],
            "params": [
                {"key": "file_path", "type": "str"},
                {"key": "encoding", "type": "str", "description": "File encoding"},
            ],
            "actions": ["default"],
        }

        result = _format_node_section_enhanced("read-file", node_data)

        assert "### read-file" in result
        assert "Reads a file from disk" in result
        assert "**Inputs**:" in result
        assert "`file_path: str` - Path to file" in result
        assert "**Outputs**:" in result
        assert "`content: str` - File contents" in result
        assert "**Parameters**:" in result
        assert "`encoding: str` - File encoding" in result
        # file_path should not be in parameters
        assert result.split("**Parameters**:")[1].count("file_path") == 0

    def test_format_node_section_enhanced_missing_description(self):
        """Test formatting with missing description."""
        node_data = {
            "inputs": [{"key": "data"}],
            "outputs": [{"key": "result"}],
            "params": [],
            "actions": ["default"],
        }

        result = _format_node_section_enhanced("no-desc-node", node_data)

        assert "No description available" in result

    def test_format_node_section_enhanced_empty_description(self):
        """Test formatting with empty description."""
        node_data = {
            "description": "",
            "inputs": [{"key": "data"}],
            "outputs": [{"key": "result"}],
            "params": [],
            "actions": ["default"],
        }

        result = _format_node_section_enhanced("empty-desc-node", node_data)

        assert "No description available" in result

    def test_format_node_section_enhanced_whitespace_description(self):
        """Test formatting with whitespace-only description."""
        node_data = {
            "description": "   \n\t  ",
            "inputs": [{"key": "data"}],
            "outputs": [{"key": "result"}],
            "params": [],
            "actions": ["default"],
        }

        result = _format_node_section_enhanced("whitespace-desc-node", node_data)

        assert "No description available" in result

    def test_format_node_section_enhanced_no_interface(self):
        """Test formatting with no inputs, outputs, or params."""
        node_data = {
            "description": "Does something",
            "inputs": [],
            "outputs": [],
            "params": [],
            "actions": [],
        }

        result = _format_node_section_enhanced("empty-node", node_data)

        assert "**Inputs**: none" in result
        assert "**Outputs**: none" in result
        assert "**Parameters**: none" in result

    def test_format_node_section_enhanced_outputs_with_actions(self):
        """Test formatting outputs with corresponding actions."""
        node_data = {
            "description": "Processes data",
            "inputs": [{"key": "data"}],
            "outputs": [
                {"key": "result", "type": "str"},
                {"key": "error", "type": "str"},
            ],
            "params": [],
            "actions": ["success", "error"],
        }

        result = _format_node_section_enhanced("processor", node_data)

        # Check for outputs with actions - the enhanced formatter doesn't include action mapping
        assert "`result: str`" in result
        assert "`error: str`" in result

    def test_format_node_section_enhanced_mixed_formats(self):
        """Test that mixing string and dict formats works."""
        node_data = {
            "description": "Mixed format test",
            "inputs": [
                "legacy_input",  # String format
                {"key": "new_input", "type": "dict", "description": "New style"},
            ],
            "outputs": ["result"],
            "params": [
                "legacy_param",
                {"key": "new_param", "type": "int", "description": "New param"},
            ],
            "actions": ["default"],
        }

        result = _format_node_section_enhanced("mixed-node", node_data)

        # Both formats should be handled
        assert "legacy_input" in result
        assert "`new_input: dict` - New style" in result
        assert "result" in result
        assert "legacy_param" in result
        assert "`new_param: int` - New param" in result
