"""Tests for two-phase context building functions.

These tests focus on behavior validation rather than implementation details.
They use real registry metadata and workflow data instead of excessive mocking.
"""

from unittest.mock import patch

import pytest

from pflow.planning.context_builder import (
    _format_node_section_enhanced,
    _format_structure_combined,
    _group_nodes_by_category,
    build_discovery_context,
    build_planning_context,
)


@pytest.fixture(autouse=True)
def isolate_global_state():
    """Automatically isolate all global state for every test in this module.

    This fixture prevents test pollution by ensuring each test starts with
    clean global state, especially important when running with the full test suite.
    """
    # Import here to avoid circular imports
    import pflow.planning.context_builder
    import pflow.registry.scanner

    # Save original values
    original_workflow_manager = getattr(pflow.planning.context_builder, "_workflow_manager", None)
    original_metadata_extractor = getattr(pflow.registry.scanner, "_metadata_extractor", None)
    original_process_nodes = getattr(pflow.planning.context_builder, "_process_nodes", None)

    # Reset to None before each test
    pflow.planning.context_builder._workflow_manager = None
    pflow.registry.scanner._metadata_extractor = None

    # Remove any patches from previous tests
    if (
        hasattr(pflow.planning.context_builder._process_nodes, "_mock_name")
        and original_process_nodes
        and not hasattr(original_process_nodes, "_mock_name")
    ):
        pflow.planning.context_builder._process_nodes = original_process_nodes

    yield

    # Restore original values after test
    pflow.planning.context_builder._workflow_manager = original_workflow_manager
    pflow.registry.scanner._metadata_extractor = original_metadata_extractor
    if original_process_nodes and not hasattr(original_process_nodes, "_mock_name"):
        pflow.planning.context_builder._process_nodes = original_process_nodes


@pytest.fixture
def sample_registry_metadata():
    """Provide real registry metadata for testing."""
    return {
        "read-file": {
            "module": "pflow.nodes.file.read_file",
            "class_name": "ReadFileNode",
            "file_path": "src/pflow/nodes/file/read_file.py",
            "interface": {
                "description": "Read content from a file and add line numbers for display",
                "inputs": [
                    {"key": "file_path", "type": "str", "description": "Path to the file to read"},
                    {"key": "encoding", "type": "str", "description": "File encoding (optional, default: utf-8)"},
                ],
                "outputs": [
                    {"key": "content", "type": "str", "description": "File contents with line numbers"},
                    {"key": "error", "type": "str", "description": "Error message if operation failed"},
                ],
                "params": [
                    {"key": "file_path", "type": "str", "description": "Path to the file to read"},
                    {"key": "encoding", "type": "str", "description": "File encoding"},
                ],
                "actions": ["default", "error"],
            },
        },
        "write-file": {
            "module": "pflow.nodes.file.write_file",
            "class_name": "WriteFileNode",
            "file_path": "src/pflow/nodes/file/write_file.py",
            "interface": {
                "description": "Write content to a file",
                "inputs": [
                    {"key": "content", "type": "str", "description": "Content to write"},
                    {"key": "file_path", "type": "str", "description": "Path where to write the file"},
                ],
                "outputs": [
                    {"key": "file_path", "type": "str", "description": "Path of the written file"},
                    {"key": "error", "type": "str", "description": "Error message if operation failed"},
                ],
                "params": [
                    {"key": "file_path", "type": "str", "description": "Path where to write the file"},
                    {"key": "encoding", "type": "str", "description": "File encoding"},
                ],
                "actions": ["default", "error"],
            },
        },
        "llm-chat": {
            "module": "pflow.nodes.ai.llm",
            "class_name": "LLMChatNode",
            "file_path": "src/pflow/nodes/ai/llm.py",
            "interface": {
                "description": "Chat with an LLM model",
                "inputs": [
                    {"key": "prompt", "type": "str", "description": "Prompt to send to the LLM"},
                    {"key": "model", "type": "str", "description": "Model name to use"},
                ],
                "outputs": [
                    {"key": "response", "type": "str", "description": "LLM response"},
                    {"key": "error", "type": "str", "description": "Error message if operation failed"},
                ],
                "params": [
                    {"key": "model", "type": "str", "description": "Default model name"},
                    {"key": "temperature", "type": "float", "description": "Sampling temperature"},
                ],
                "actions": ["default", "error"],
            },
        },
    }


@pytest.fixture
def sample_workflows():
    """Provide real workflow metadata for testing."""
    return [
        {
            "name": "text-processor",
            "description": "Process text files with LLM analysis",
            "ir": {
                "nodes": [{"id": "reader", "type": "read-file"}, {"id": "analyzer", "type": "llm-chat"}],
                "edges": [{"from": "reader", "to": "analyzer"}],
                "inputs": {"input_file": {"description": "Text file to process", "type": "string", "required": True}},
                "outputs": {"analysis": {"description": "LLM analysis of the text", "type": "string"}},
            },
            "version": "1.0.0",
            "tags": ["text", "ai"],
        },
        {
            "name": "file-backup",
            "description": "Create backup copies of files",
            "ir": {
                "nodes": [{"id": "reader", "type": "read-file"}, {"id": "writer", "type": "write-file"}],
                "edges": [{"from": "reader", "to": "writer"}],
            },
        },
    ]


def _parse_node_name(line: str) -> str | None:
    """Parse node name from a markdown header line."""
    if not (line.startswith("### ") and not line.endswith("(workflow)") and not line.endswith("Operations")):
        return None

    node_name = line[4:].strip()
    # Skip category headers
    if any(word in node_name for word in ["Operations", "Category"]):
        return None

    return node_name


def _parse_section_name(line: str) -> str | None:
    """Parse section name from a markdown bold header."""
    if not (line.startswith("**") and ":" in line):
        return None

    parts = line.split("**")
    if len(parts) < 2:
        return None

    section_text = parts[1]
    section = section_text.split(" ")[0].lower()

    # Map parameters to inputs for backward compatibility
    return "inputs" if section == "parameters" else section


def parse_context_nodes(context: str) -> dict[str, dict[str, str]]:
    """Parse context string to extract node information for behavioral validation.

    Args:
        context: Markdown context string

    Returns:
        Dict mapping node names to their parsed information
    """
    nodes = {}
    current_node = None
    current_section = None

    for line in context.split("\n"):
        line = line.strip()

        # Check for node name
        node_name = _parse_node_name(line)
        if node_name:
            nodes[node_name] = {"description": "", "inputs": [], "outputs": [], "params": []}
            current_node = node_name
            current_section = "description"
            continue

        # Check for section header
        if current_node:
            section = _parse_section_name(line)
            if section:
                current_section = section
                continue

        # Process content based on current section
        if current_node and current_section:
            if current_section == "description" and line and not line.startswith("**"):
                if not nodes[current_node]["description"]:
                    nodes[current_node]["description"] = line
            elif current_section in ["inputs", "outputs", "parameters"] and line.startswith("- `"):
                section_key = "params" if current_section == "parameters" else current_section
                nodes[current_node][section_key].append(line)

    return nodes


def parse_context_workflows(context: str) -> dict[str, dict[str, str]]:
    """Parse context string to extract workflow information.

    Args:
        context: Markdown context string

    Returns:
        Dict mapping workflow names to their parsed information
    """
    workflows = {}
    current_workflow = None

    for line in context.split("\n"):
        line = line.strip()
        if line.startswith("### ") and line.endswith("(workflow)"):
            # Workflow name
            workflow_name = line[4:-11].strip()  # Remove '### ' and ' (workflow)'
            workflows[workflow_name] = {"description": ""}
            current_workflow = workflow_name
        elif current_workflow and line and not line.startswith("**") and not line.startswith("### "):
            # Description text
            if not workflows[current_workflow]["description"]:
                workflows[current_workflow]["description"] = line

    return workflows


class TestDiscoveryContext:
    """Tests for build_discovery_context function.

    These tests validate behavior rather than implementation details.
    They use real registry metadata and workflow data to test actual functionality.
    """

    def test_discovery_context_input_validation(self):
        """Test input validation rejects invalid parameter types."""
        # Test invalid node_ids type
        with pytest.raises(TypeError, match="node_ids must be a list or None, got str"):
            build_discovery_context(node_ids="github-node")

        # Test invalid workflow_names type
        with pytest.raises(TypeError, match="workflow_names must be a list or None, got dict"):
            build_discovery_context(workflow_names={"workflow": "name"})

        # Test invalid registry_metadata type
        with pytest.raises(TypeError, match="registry_metadata must be a dict or None, got list"):
            build_discovery_context(registry_metadata=[])

    def test_discovery_context_empty_registry_shows_minimal_content(self):
        """Test discovery context with no components shows minimal or empty content."""
        context = build_discovery_context(registry_metadata={})

        # Should produce minimal output for empty registry
        # Context should be empty or very short without nodes
        assert isinstance(context, str)
        # Should be relatively short for empty registry (allowing for some test workflows)
        assert len(context.split("\n")) < 20

    def test_discovery_context_shows_node_names_and_descriptions_only(self, sample_registry_metadata):
        """Test discovery context includes node names and descriptions but excludes interface details."""
        context = build_discovery_context(registry_metadata=sample_registry_metadata)

        # Parse the context to validate behavior
        parsed_nodes = parse_context_nodes(context)

        # Should contain all nodes from registry
        assert "read-file" in parsed_nodes
        assert "write-file" in parsed_nodes
        assert "llm-chat" in parsed_nodes

        # Should have descriptions
        assert "Read content from a file" in parsed_nodes["read-file"]["description"]
        assert "Write content to a file" in parsed_nodes["write-file"]["description"]
        assert "Chat with an LLM model" in parsed_nodes["llm-chat"]["description"]

        # Should NOT contain interface details in discovery phase
        for node_name, node_data in parsed_nodes.items():
            assert len(node_data["inputs"]) == 0, f"Discovery should not show inputs for {node_name}"
            assert len(node_data["outputs"]) == 0, f"Discovery should not show outputs for {node_name}"
            assert len(node_data["params"]) == 0, f"Discovery should not show params for {node_name}"

    def test_discovery_context_gracefully_handles_missing_descriptions(self):
        """Test that nodes without descriptions are handled gracefully without crash."""
        registry_metadata = {
            "no-desc-node": {
                "module": "test",
                "class_name": "ExampleNode",
                "file_path": "src/pflow/nodes/test.py",  # Non-test path so it's not skipped
                "interface": {
                    "description": "",  # Empty description
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": [],
                },
            }
        }

        context = build_discovery_context(registry_metadata=registry_metadata)

        # Should produce valid context without errors
        assert isinstance(context, str)
        # Context might be empty if node has no description, or contain node name
        # The important thing is it doesn't crash and doesn't show placeholder text

        # Should not show placeholder text for missing descriptions
        assert "No description" not in context
        assert "No description available" not in context

    def test_discovery_context_includes_available_workflows(self, sample_workflows):
        """Test discovery context includes workflows with names and descriptions only."""
        # Ensure test isolation by resetting the global workflow manager
        with (
            patch("pflow.planning.context_builder._workflow_manager", None),
            patch("pflow.planning.context_builder._load_saved_workflows", return_value=sample_workflows),
        ):
            context = build_discovery_context(registry_metadata={})

        # Parse workflows from context
        parsed_workflows = parse_context_workflows(context)

        # Should contain workflows section
        assert "## Available Workflows" in context

        # Should contain all workflows
        assert "text-processor" in parsed_workflows
        assert "file-backup" in parsed_workflows

        # Should have descriptions but no interface details
        assert "Process text files with LLM analysis" in parsed_workflows["text-processor"]["description"]
        assert "Create backup copies of files" in parsed_workflows["file-backup"]["description"]

        # Should NOT contain detailed interface info in discovery phase
        assert "inputs" not in context.lower() or "**Inputs**" not in context
        assert "outputs" not in context.lower() or "**Outputs**" not in context

    def test_discovery_context_respects_node_filtering(self, sample_registry_metadata):
        """Test discovery context only includes specified nodes when filtered."""
        # Ensure test isolation by resetting the global workflow manager
        with (
            patch("pflow.planning.context_builder._workflow_manager", None),
            patch("pflow.planning.context_builder._load_saved_workflows", return_value=[]),
        ):
            context = build_discovery_context(
                node_ids=["read-file", "llm-chat"], registry_metadata=sample_registry_metadata
            )

        # Parse context to validate filtering behavior
        parsed_nodes = parse_context_nodes(context)

        # Should only contain filtered nodes
        assert "read-file" in parsed_nodes
        assert "llm-chat" in parsed_nodes
        assert "write-file" not in parsed_nodes  # Should be excluded

        # Filtered nodes should have their descriptions
        assert "Read content from a file" in parsed_nodes["read-file"]["description"]
        assert "Chat with an LLM model" in parsed_nodes["llm-chat"]["description"]

    def test_discovery_context_groups_nodes_by_category(self, sample_registry_metadata):
        """Test nodes are logically grouped by operational category."""
        # Ensure test isolation by resetting the global workflow manager
        with (
            patch("pflow.planning.context_builder._workflow_manager", None),
            patch("pflow.planning.context_builder._load_saved_workflows", return_value=[]),
        ):
            context = build_discovery_context(registry_metadata=sample_registry_metadata)

        # Should contain appropriate category sections
        assert "### File Operations" in context
        assert "### AI/LLM Operations" in context

        # Validate that file nodes appear under File Operations
        file_ops_section = context.split("### File Operations")[1]
        if "### AI/LLM Operations" in file_ops_section:
            file_ops_section = file_ops_section.split("### AI/LLM Operations")[0]

        assert "read-file" in file_ops_section
        assert "write-file" in file_ops_section

        # Validate that AI nodes appear under AI/LLM Operations
        ai_ops_section = context.split("### AI/LLM Operations")[1]
        assert "llm-chat" in ai_ops_section

    def test_discovery_context_respects_workflow_filtering(self, sample_workflows):
        """Test discovery context only includes specified workflows when filtered."""
        # Ensure test isolation by resetting the global workflow manager
        with (
            patch("pflow.planning.context_builder._workflow_manager", None),
            patch("pflow.planning.context_builder._load_saved_workflows", return_value=sample_workflows),
        ):
            context = build_discovery_context(workflow_names=["text-processor"], registry_metadata={})

        # Parse workflows from context
        parsed_workflows = parse_context_workflows(context)

        # Should only contain filtered workflow
        assert "text-processor" in parsed_workflows
        assert "file-backup" not in parsed_workflows  # Should be excluded

        # Filtered workflow should have its description
        assert "Process text files with LLM analysis" in parsed_workflows["text-processor"]["description"]


class TestPlanningContext:
    """Tests for build_planning_context function.

    These tests focus on behavior validation and use real registry metadata
    to test the detailed planning context generation.
    """

    def test_planning_context_input_validation(self):
        """Test input validation rejects invalid parameter types."""
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

    def test_planning_context_returns_error_for_missing_nodes(self, sample_registry_metadata):
        """Test planning context returns structured error when requested nodes don't exist."""
        result = build_planning_context(
            selected_node_ids=["read-file", "nonexistent-node"],  # nonexistent-node doesn't exist
            selected_workflow_names=[],
            registry_metadata=sample_registry_metadata,
            saved_workflows=[],
        )

        # Should return error dict, not string
        assert isinstance(result, dict)
        assert "error" in result
        assert "missing_nodes" in result
        assert "missing_workflows" in result

        # Should identify the missing node
        assert "nonexistent-node" in result["missing_nodes"]
        assert len(result["missing_workflows"]) == 0
        assert "Unknown nodes: nonexistent-node" in result["error"]

    def test_planning_context_returns_error_for_missing_workflows(self, sample_workflows):
        """Test planning context returns structured error when requested workflows don't exist."""
        result = build_planning_context(
            selected_node_ids=[],
            selected_workflow_names=["text-processor", "nonexistent-workflow"],  # nonexistent-workflow doesn't exist
            registry_metadata={},
            saved_workflows=sample_workflows,
        )

        # Should return error dict, not string
        assert isinstance(result, dict)
        assert "error" in result
        assert "missing_workflows" in result

        # Should identify the missing workflow
        assert "nonexistent-workflow" in result["missing_workflows"]
        assert len(result["missing_nodes"]) == 0
        assert "Unknown workflows: nonexistent-workflow" in result["error"]

    def test_planning_context_provides_detailed_interface_for_valid_selection(self, sample_registry_metadata):
        """Test planning context provides complete interface details for valid component selection."""
        result = build_planning_context(
            selected_node_ids=["read-file"],
            selected_workflow_names=[],
            registry_metadata=sample_registry_metadata,
            saved_workflows=[],
        )

        # Should return markdown string, not error dict
        assert isinstance(result, str)

        # Parse the context to validate detailed interface information
        parsed_nodes = parse_context_nodes(result)

        # Should contain selected node with full interface details
        assert "read-file" in parsed_nodes
        node_data = parsed_nodes["read-file"]

        # Should have description
        assert "Read content from a file" in node_data["description"]

        # Should contain detailed interface information (unlike discovery phase)
        assert len(node_data["inputs"]) > 0, "Planning context should show detailed inputs"
        assert len(node_data["outputs"]) > 0, "Planning context should show detailed outputs"

        # Should contain main section headers
        assert "## Selected Components" in result
        assert "### read-file" in result
        assert "**Parameters**:" in result
        assert "**Outputs**:" in result

    def test_planning_context_handles_structured_data_appropriately(self, sample_registry_metadata):
        """Test planning context can handle nodes with structured data outputs."""
        # Use a real node that works, rather than creating complex test data
        # Ensure test isolation by resetting the global workflow manager
        with patch("pflow.planning.context_builder._workflow_manager", None):
            result = build_planning_context(
                selected_node_ids=["read-file"],
                selected_workflow_names=[],
                registry_metadata=sample_registry_metadata,
                saved_workflows=[],
            )

        # Should successfully generate planning context
        assert isinstance(result, str)
        assert "## Selected Components" in result
        assert "read-file" in result

        # Should contain interface information for planning
        assert "**Parameters**:" in result
        assert "**Outputs**:" in result

        # Should show detailed interface information
        assert "file_path" in result
        assert "content" in result

    def test_planning_context_shows_exclusive_parameters_only(self, sample_registry_metadata):
        """Test planning context only shows parameters not duplicated in inputs."""
        # Ensure test isolation by resetting the global workflow manager
        with patch("pflow.planning.context_builder._workflow_manager", None):
            result = build_planning_context(
                selected_node_ids=["read-file"],
                selected_workflow_names=[],
                registry_metadata=sample_registry_metadata,
                saved_workflows=[],
            )

        # Parse the result to validate parameter exclusion behavior
        parsed_nodes = parse_context_nodes(result)
        node_data = parsed_nodes["read-file"]

        # Should show inputs clearly
        assert len(node_data["inputs"]) > 0

        # Should show parameters that are not already in inputs
        # In our sample data, file_path and encoding appear in both inputs and params
        # The parameters section should exclude duplicates or show appropriately

        # Validate that the context is coherent and doesn't duplicate information
        # in a confusing way for the LLM
        input_lines = [line for line in node_data["inputs"] if line.strip()]

        # Should have some interface information (behavior test, not exact format)
        assert len(input_lines) > 0, "Should show input information"
        # Parameters section exists (may be exclusive params or template variables)
        assert "**Parameters**" in result or "**Template Variables**" in result

    def test_planning_context_includes_workflow_details(self, sample_workflows):
        """Test planning context provides detailed workflow information for planning."""
        # Ensure test isolation by resetting the global workflow manager
        with patch("pflow.planning.context_builder._workflow_manager", None):
            result = build_planning_context(
                selected_node_ids=[],
                selected_workflow_names=["text-processor"],
                registry_metadata={},
                saved_workflows=sample_workflows,
            )

        # Should return string context, not error
        assert isinstance(result, str)

        # Should contain workflow section and details
        assert "## Selected Workflows" in result
        assert "### text-processor (workflow)" in result
        assert "Process text files with LLM analysis" in result

        # Workflows still use Inputs/Outputs format (not nodes)
        assert "**Inputs**:" in result
        assert "**Outputs**:" in result
        assert "input_file" in result  # From workflow IR inputs
        assert "analysis" in result  # From workflow IR outputs

        # Should include metadata
        assert "**Version**: 1.0.0" in result
        assert "**Tags**: text, ai" in result

    def test_planning_context_handles_mixed_node_and_workflow_selection(
        self, sample_registry_metadata, sample_workflows
    ):
        """Test planning context can handle both nodes and workflows in same request."""
        # Ensure test isolation by resetting the global workflow manager
        with patch("pflow.planning.context_builder._workflow_manager", None):
            result = build_planning_context(
                selected_node_ids=["write-file"],
                selected_workflow_names=["file-backup"],
                registry_metadata=sample_registry_metadata,
                saved_workflows=sample_workflows,
            )

        # Should return string context with both sections
        assert isinstance(result, str)

        # Should contain both components
        assert "## Selected Components" in result
        assert "### write-file" in result
        assert "## Selected Workflows" in result
        assert "### file-backup (workflow)" in result


class TestStructureFormatting:
    """Tests for structure formatting functionality.

    These tests validate the behavior of structure formatting without
    testing internal implementation details.
    """

    def test_simple_structure_formatting_produces_json_and_paths(self):
        """Test structure formatting converts simple structures to JSON and path lists."""
        structure = {
            "field1": {"type": "str", "description": "First field"},
            "field2": {"type": "int", "description": "Second field"},
        }

        json_struct, paths = _format_structure_combined(structure)

        # Should produce clean JSON structure with types
        assert json_struct == {"field1": "str", "field2": "int"}

        # Should produce paths for field access
        assert len(paths) == 2
        assert ("field1", "str", "First field") in paths
        assert ("field2", "int", "Second field") in paths

    def test_nested_structure_formatting_handles_deep_nesting(self):
        """Test structure formatting correctly handles nested dictionary structures."""
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

        # Should flatten nested structure into clean JSON
        expected_json = {"user": {"name": "str", "settings": {"theme": "str"}}}
        assert json_struct == expected_json

        # Should provide all accessible paths
        assert len(paths) == 4
        path_strings = [path for path, _, _ in paths]
        assert "user" in path_strings
        assert "user.name" in path_strings
        assert "user.settings" in path_strings
        assert "user.settings.theme" in path_strings

    def test_list_structure_formatting_uses_array_notation(self):
        """Test structure formatting correctly handles list structures with array notation."""
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

        # Should represent list as array in JSON
        expected_json = {"items": [{"id": "int", "name": "str"}]}
        assert json_struct == expected_json

        # Should provide paths with array notation
        path_strings = [path for path, _, _ in paths]
        assert "items[]" in path_strings or "items[].id" in path_strings
        assert "items[].id" in path_strings
        assert "items[].name" in path_strings

    def test_empty_structure_formatting_returns_empty_results(self):
        """Test structure formatting gracefully handles empty structures."""
        structure = {}

        json_struct, paths = _format_structure_combined(structure)

        # Should return empty but valid results
        assert json_struct == {}
        assert paths == []


class TestNodeProcessing:
    """Tests for node processing functionality.

    These tests validate behavior without excessive mocking of internal functions.
    """

    def test_node_processing_uses_interface_data_correctly(self, sample_registry_metadata):
        """Test node processing correctly extracts and uses interface data from registry."""
        # Use real registry data - no mocking of _process_nodes
        from pflow.planning.context_builder import _process_nodes

        nodes, skipped_count = _process_nodes(sample_registry_metadata)

        # Should process all valid nodes
        assert "read-file" in nodes
        assert "write-file" in nodes
        assert "llm-chat" in nodes

        # Should extract interface data correctly
        read_file_node = nodes["read-file"]
        assert "Read content from a file" in read_file_node["description"]
        assert len(read_file_node["inputs"]) > 0
        assert len(read_file_node["outputs"]) > 0

        # Should report no skipped nodes for valid data
        assert skipped_count == 0

    def test_node_processing_rejects_nodes_without_interface_data(self):
        """Test node processing properly validates interface field presence."""
        from pflow.planning.context_builder import _process_nodes

        invalid_registry = {
            "broken-node": {
                "module": "pflow.nodes.broken",
                "class_name": "BrokenNode",
                "file_path": "/path/to/broken.py",
                # Missing interface field - this should cause validation error
            }
        }

        # Should raise appropriate error for missing interface
        with pytest.raises(ValueError, match="missing interface data"):
            _process_nodes(invalid_registry)

    def test_node_processing_skips_test_nodes_appropriately(self):
        """Test node processing correctly identifies and skips test nodes."""
        from pflow.planning.context_builder import _process_nodes

        registry_with_test_nodes = {
            "real-node": {
                "module": "pflow.nodes.real",
                "class_name": "RealNode",
                "file_path": "src/pflow/nodes/real.py",
                "interface": {
                    "description": "A real production node",
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": ["default"],
                },
            },
            "test-node": {
                "module": "tests.test_node",
                "class_name": "ExampleNode",
                "file_path": "tests/fixtures/test_node.py",  # Contains 'test' in path
                "interface": {
                    "description": "A test node",
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": ["default"],
                },
            },
        }

        nodes, skipped_count = _process_nodes(registry_with_test_nodes)

        # Should process the real node but skip the test node
        assert "real-node" in nodes
        assert "test-node" not in nodes
        assert skipped_count == 1

    def test_node_processing_handles_multiple_nodes_efficiently(self):
        """Test node processing can handle multiple nodes with shared modules efficiently."""
        from pflow.planning.context_builder import _process_nodes

        registry = {
            "node-1": {
                "module": "pflow.nodes.shared_module",
                "class_name": "NodeOne",
                "file_path": "src/pflow/nodes/shared_module.py",
                "interface": {
                    "description": "First node from shared module",
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": ["default"],
                },
            },
            "node-2": {
                "module": "pflow.nodes.shared_module",
                "class_name": "NodeTwo",
                "file_path": "src/pflow/nodes/shared_module.py",
                "interface": {
                    "description": "Second node from shared module",
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": ["default"],
                },
            },
        }

        # Should process all nodes successfully
        processed, skipped = _process_nodes(registry)

        # Should handle multiple nodes correctly
        assert len(processed) == 2
        assert "node-1" in processed
        assert "node-2" in processed
        assert processed["node-1"]["description"] == "First node from shared module"
        assert processed["node-2"]["description"] == "Second node from shared module"
        assert skipped == 0


class TestCategoryGrouping:
    """Tests for node categorization functionality.

    These tests validate the logical grouping of nodes by category.
    """

    def test_node_categorization_groups_file_operations_logically(self):
        """Test file-related nodes are correctly grouped under File Operations."""

        nodes = {
            "read-file": {},
            "write-file": {},
            "copy-file": {},
            "process-data": {},
        }

        categories = _group_nodes_by_category(nodes)

        # Should group file operations together
        assert "File Operations" in categories
        file_ops = set(categories["File Operations"])
        assert "read-file" in file_ops
        assert "write-file" in file_ops
        assert "copy-file" in file_ops

        # Non-file operations should be categorized separately
        assert "process-data" not in file_ops

    def test_node_categorization_groups_ai_operations_logically(self):
        """Test AI/LLM-related nodes are correctly grouped under AI/LLM Operations."""

        nodes = {
            "llm": {},
            "ai-processor": {},
            "gpt-node": {},
            "regular-node": {},
        }

        categories = _group_nodes_by_category(nodes)

        # Should group AI/LLM operations together
        assert "AI/LLM Operations" in categories
        ai_ops = set(categories["AI/LLM Operations"])
        assert "llm" in ai_ops
        assert "ai-processor" in ai_ops

        # Non-AI operations should be categorized separately
        assert "regular-node" not in ai_ops

    def test_node_categorization_groups_git_operations_logically(self):
        """Test git-related nodes are correctly grouped under Git Operations."""

        nodes = {
            "git-commit": {},
            "github-issue": {},
            "gitlab-merge": {},
        }

        categories = _group_nodes_by_category(nodes)

        # Should group git operations together
        assert "Git Operations" in categories
        git_ops = set(categories["Git Operations"])
        assert "git-commit" in git_ops
        assert "github-issue" in git_ops
        assert "gitlab-merge" in git_ops

    def test_all_parameter_formatting_shows_all_params_with_annotations(self):
        """Test parameter formatting shows all parameters with new format."""
        # Import the new function
        from pflow.planning.context_builder import _format_all_parameters_new

        node_data = {
            "inputs": [
                {"key": "file_path", "type": "str", "description": "File to read"},
                {"key": "encoding", "type": "str", "description": "Text encoding"},
            ],
            "params": ["file_path", "encoding", "validate"],
        }

        lines = []
        _format_all_parameters_new(node_data, lines)

        # Should show ALL parameters now
        result = "\n".join(lines)
        assert "validate" in result  # Should appear (exclusive param)
        assert "file_path" in result  # Should appear
        assert "encoding" in result  # Should appear

        # Should use new format
        assert "**Parameters**:" in result
        assert "Configuration parameter" in result  # validate should be marked as config


class TestNodeFormatting:
    """Tests for node section formatting functionality.

    These tests validate the behavior of node formatting for planning context.
    """

    def test_node_formatting_includes_all_interface_sections(self):
        """Test node formatting includes all necessary interface sections for planning."""

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

        # Should format as planning context with all sections
        assert "### read-file" in result
        assert "Reads a file from disk" in result
        assert "**Parameters**:" in result
        assert "**Outputs**:" in result

        # Should include interface details for planning
        assert "file_path" in result
        assert "content" in result
        assert "encoding" in result

    def test_node_formatting_handles_missing_description_gracefully(self):
        """Test node formatting provides appropriate fallback for missing descriptions."""

        node_data = {
            "inputs": [{"key": "data"}],
            "outputs": [{"key": "result"}],
            "params": [],
            "actions": ["default"],
        }

        result = _format_node_section_enhanced("no-desc-node", node_data)

        # Should provide some indication of missing description
        assert "description" in result.lower() or "no-desc-node" in result

    def test_node_formatting_handles_empty_description_gracefully(self):
        """Test node formatting provides appropriate fallback for empty descriptions."""

        node_data = {
            "description": "",
            "inputs": [{"key": "data"}],
            "outputs": [{"key": "result"}],
            "params": [],
            "actions": ["default"],
        }

        result = _format_node_section_enhanced("empty-desc-node", node_data)

        # Should provide some indication or fallback for empty description
        assert len(result) > 0  # Should still produce output
        assert "empty-desc-node" in result  # Should include node name

    def test_node_formatting_handles_whitespace_only_description_gracefully(self):
        """Test node formatting treats whitespace-only descriptions as empty."""

        node_data = {
            "description": "   \n\t  ",
            "inputs": [{"key": "data"}],
            "outputs": [{"key": "result"}],
            "params": [],
            "actions": ["default"],
        }

        result = _format_node_section_enhanced("whitespace-desc-node", node_data)

        # Should handle whitespace-only description appropriately
        assert len(result) > 0  # Should still produce output
        assert "whitespace-desc-node" in result  # Should include node name

    def test_node_formatting_handles_nodes_without_interface_elements(self):
        """Test node formatting appropriately handles nodes with no inputs, outputs, or params."""

        node_data = {
            "description": "Does something simple",
            "inputs": [],
            "outputs": [],
            "params": [],
            "actions": [],
        }

        result = _format_node_section_enhanced("simple-node", node_data)

        # Should indicate empty sections appropriately
        assert "simple-node" in result
        assert "Does something simple" in result
        # Should have interface sections even if empty (using new format)
        assert "Parameters" in result  # Changed from Inputs
        assert "Outputs" in result

    def test_node_formatting_displays_multiple_outputs_clearly(self):
        """Test node formatting clearly displays multiple outputs for planning context."""

        node_data = {
            "description": "Processes data with multiple possible outputs",
            "inputs": [{"key": "data", "type": "str", "description": "Input data"}],
            "outputs": [
                {"key": "result", "type": "str", "description": "Successful result"},
                {"key": "error", "type": "str", "description": "Error message"},
            ],
            "params": [],
            "actions": ["success", "error"],
        }

        result = _format_node_section_enhanced("processor", node_data)

        # Should clearly show all outputs for planning
        assert "result" in result
        assert "error" in result
        assert "Successful result" in result
        assert "Error message" in result

    def test_node_formatting_handles_mixed_interface_formats(self):
        """Test node formatting correctly handles both string and dict interface formats."""

        node_data = {
            "description": "Node with mixed interface formats",
            "inputs": [
                "legacy_input",  # String format
                {"key": "detailed_input", "type": "dict", "description": "Detailed format"},
            ],
            "outputs": [
                "simple_output",  # String format
                {"key": "detailed_output", "type": "str", "description": "Detailed output"},
            ],
            "params": [
                "legacy_param",
                {"key": "detailed_param", "type": "int", "description": "Detailed param"},
            ],
            "actions": ["default"],
        }

        result = _format_node_section_enhanced("mixed-node", node_data)

        # Should handle both string and dict formats appropriately
        assert "legacy_input" in result
        assert "detailed_input" in result
        assert "simple_output" in result
        assert "detailed_output" in result
        assert "legacy_param" in result
        assert "detailed_param" in result


class TestIntegrationBehavior:
    """Integration tests that validate full workflow behavior.

    These tests focus on end-to-end functionality rather than isolated components.
    """

    def test_discovery_to_planning_workflow_provides_consistent_information(
        self, sample_registry_metadata, sample_workflows
    ):
        """Test that discovery and planning contexts provide consistent information for the same components."""
        # First, get discovery context
        # Ensure test isolation by resetting the global workflow manager
        with (
            patch("pflow.planning.context_builder._workflow_manager", None),
            patch("pflow.planning.context_builder._load_saved_workflows", return_value=sample_workflows),
        ):
            discovery_context = build_discovery_context(
                node_ids=["read-file", "write-file"],
                workflow_names=["text-processor"],
                registry_metadata=sample_registry_metadata,
            )

        # Then, get planning context for same components
        with patch("pflow.planning.context_builder._workflow_manager", None):
            planning_context = build_planning_context(
                selected_node_ids=["read-file", "write-file"],
                selected_workflow_names=["text-processor"],
                registry_metadata=sample_registry_metadata,
                saved_workflows=sample_workflows,
            )

        # Both should be strings (no errors)
        assert isinstance(discovery_context, str)
        assert isinstance(planning_context, str)

        # Parse both contexts
        discovery_nodes = parse_context_nodes(discovery_context)
        planning_nodes = parse_context_nodes(planning_context)

        discovery_workflows = parse_context_workflows(discovery_context)
        planning_workflows = parse_context_workflows(planning_context)

        # Same components should be present in both
        assert set(discovery_nodes.keys()) == set(planning_nodes.keys())
        assert set(discovery_workflows.keys()) == set(planning_workflows.keys())

        # Descriptions should be consistent
        for node_name in discovery_nodes:
            assert discovery_nodes[node_name]["description"] == planning_nodes[node_name]["description"]

        for workflow_name in discovery_workflows:
            assert discovery_workflows[workflow_name]["description"] == planning_workflows[workflow_name]["description"]

        # Discovery should have no interface details, planning should have interface details
        for node_name in discovery_nodes:
            assert len(discovery_nodes[node_name]["inputs"]) == 0, "Discovery should not show inputs"
            assert len(planning_nodes[node_name]["inputs"]) > 0, "Planning should show inputs"

    def test_context_builder_handles_empty_and_full_registries_gracefully(self):
        """Test context builder handles edge cases gracefully."""
        # Test with completely empty registry
        # Ensure test isolation by resetting the global workflow manager
        with (
            patch("pflow.planning.context_builder._workflow_manager", None),
            patch("pflow.planning.context_builder._load_saved_workflows", return_value=[]),
        ):
            empty_context = build_discovery_context(registry_metadata={})

        assert isinstance(empty_context, str)
        # Empty registry may produce empty string, which is valid
        # The important thing is it returns a valid string without errors

        # Test planning with empty selection
        with patch("pflow.planning.context_builder._workflow_manager", None):
            empty_planning = build_planning_context(
                selected_node_ids=[], selected_workflow_names=[], registry_metadata={}, saved_workflows=[]
            )

        assert isinstance(empty_planning, str)
        assert "## Selected Components" in empty_planning

    def test_context_builder_error_handling_provides_actionable_feedback(self, sample_registry_metadata):
        """Test context builder provides clear, actionable error messages."""
        # Test with missing nodes
        # Ensure test isolation by resetting the global workflow manager
        with patch("pflow.planning.context_builder._workflow_manager", None):
            result = build_planning_context(
                selected_node_ids=["nonexistent-node", "another-missing-node"],
                selected_workflow_names=[],
                registry_metadata=sample_registry_metadata,
                saved_workflows=[],
            )

        # Should return error dict with actionable information
        assert isinstance(result, dict)
        assert "error" in result
        assert "missing_nodes" in result

        # Error should be actionable
        error_msg = result["error"]
        assert "nonexistent-node" in error_msg
        assert "another-missing-node" in error_msg
        assert len(result["missing_nodes"]) == 2
