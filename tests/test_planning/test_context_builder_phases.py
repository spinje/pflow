"""Tests for two-phase context building functions."""

from unittest.mock import patch

import pytest

from pflow.planning.context_builder import (
    _format_structure_combined,
    build_discovery_context,
    build_planning_context,
)


class TestDiscoveryContext:
    """Tests for build_discovery_context function."""

    def test_discovery_context_empty_registry(self):
        """Test discovery context with no nodes."""
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
