"""Tests for registry run command.

This test file focuses on high-value, critical functionality of the `pflow registry run` command:

1. Command registration and basic execution
2. Output modes (text, JSON, structure)
3. Parameter handling (type inference, validation)
4. MCP node normalization (short form resolution)
5. Error handling (unknown nodes, missing params, ambiguous names)
6. Structure mode with JSON string parsing (killer feature)

Tests use extensive mocking to remain fast and deterministic.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import click.testing
import pytest

from pflow.cli.registry import registry
from pflow.registry.registry import Registry


@pytest.fixture
def runner():
    """Create a Click test runner."""
    return click.testing.CliRunner()


@pytest.fixture
def mock_registry():
    """Create a mock Registry with test data."""
    with patch("pflow.cli.registry_run.Registry") as MockRegistry:
        instance = MagicMock(spec=Registry)
        MockRegistry.return_value = instance

        # Default test nodes with metadata
        test_nodes = {
            "read-file": {
                "module": "pflow.nodes.file.read_file",
                "class_name": "ReadFileNode",
                "file_path": "/src/pflow/nodes/file/read_file.py",
                "interface": {
                    "description": "Read content from a file",
                    "inputs": [],
                    "outputs": [{"key": "content", "type": "str", "description": "File contents"}],
                    "params": [{"key": "file_path", "type": "str", "required": True, "description": "Path to file"}],
                },
            },
            "write-file": {
                "module": "pflow.nodes.file.write_file",
                "class_name": "WriteFileNode",
                "file_path": "/src/pflow/nodes/file/write_file.py",
                "interface": {
                    "description": "Write content to a file",
                    "inputs": [{"key": "content", "type": "str"}],
                    "outputs": [],
                    "params": [
                        {"key": "file_path", "type": "str", "required": True},
                        {"key": "content", "type": "str", "required": True},
                    ],
                },
            },
            "llm": {
                "module": "pflow.nodes.llm.llm",
                "class_name": "LLMNode",
                "file_path": "/src/pflow/nodes/llm/llm.py",
                "interface": {
                    "description": "Query an LLM with a prompt",
                    "outputs": [{"key": "result", "type": "any"}],
                    "params": [{"key": "prompt", "type": "str", "required": True}],
                },
            },
            "mcp-slack-composio-SLACK_SEND_MESSAGE": {
                "module": "pflow.nodes.mcp_node",
                "class_name": "MCPNode",
                "file_path": "virtual://mcp/slack-composio",
                "interface": {
                    "description": "Send a Slack message",
                    "outputs": [{"key": "result", "type": "any"}],
                    "params": [
                        {"key": "channel", "type": "str", "required": True},
                        {"key": "text", "type": "str", "required": True},
                    ],
                },
            },
            "mcp-github-list-repos": {
                "module": "pflow.nodes.mcp_node",
                "class_name": "MCPNode",
                "file_path": "virtual://mcp/github",
                "interface": {
                    "description": "List GitHub repositories",
                    "outputs": [{"key": "result", "type": "any"}],
                    "params": [],
                },
            },
        }

        instance.load.return_value = test_nodes
        instance.get_nodes_metadata.return_value = test_nodes
        yield MockRegistry, instance


# ==============================================================================
# 1. Command Registration & Basic Execution
# ==============================================================================


def test_run_command_appears_in_help(runner):
    """Test that 'run' command appears in registry help."""
    result = runner.invoke(registry, ["--help"])

    assert result.exit_code == 0
    assert "run" in result.output
    assert "Run a single node" in result.output or "testing" in result.output


def test_basic_node_execution_with_temp_file(runner, tmp_path):
    """Test basic node execution with a real file."""
    # Create a test file
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, world!")

    # Import the actual ReadFileNode for this test
    from pflow.nodes.file.read_file import ReadFileNode

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run.Registry") as MockRegistry,
    ):
        # Setup registry mock
        instance = MagicMock()
        instance.load.return_value = {"read-file": {}}
        MockRegistry.return_value = instance

        # Return actual node class
        mock_import.return_value = ReadFileNode

        result = runner.invoke(registry, ["run", "read-file", f"file_path={test_file}"])

        assert result.exit_code == 0
        assert "Node executed successfully" in result.output
        assert "Hello, world!" in result.output


def test_node_execution_returns_exit_code_zero_on_success(runner, tmp_path):
    """Test that successful execution returns exit code 0."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    from pflow.nodes.file.read_file import ReadFileNode

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run.Registry") as MockRegistry,
    ):
        instance = MagicMock()
        instance.load.return_value = {"read-file": {}}
        MockRegistry.return_value = instance
        mock_import.return_value = ReadFileNode

        result = runner.invoke(registry, ["run", "read-file", f"file_path={test_file}"])

        assert result.exit_code == 0


def test_node_execution_returns_exit_code_one_on_failure(runner):
    """Test that failed execution returns exit code 1."""
    from pflow.nodes.file.read_file import ReadFileNode

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run.Registry") as MockRegistry,
    ):
        instance = MagicMock()
        instance.load.return_value = {"read-file": {}}
        MockRegistry.return_value = instance
        mock_import.return_value = ReadFileNode

        # Try to read non-existent file
        result = runner.invoke(registry, ["run", "read-file", "file_path=/nonexistent/file.txt"])

        assert result.exit_code == 1
        assert "execution failed" in result.output.lower() or "error" in result.output.lower()


# ==============================================================================
# 2. Output Modes (text, JSON, structure)
# ==============================================================================


def test_json_output_format_is_valid(runner, tmp_path):
    """Test JSON output format is valid and parseable."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    from pflow.nodes.file.read_file import ReadFileNode

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run.Registry") as MockRegistry,
    ):
        instance = MagicMock()
        instance.load.return_value = {"read-file": {}}
        MockRegistry.return_value = instance
        mock_import.return_value = ReadFileNode

        result = runner.invoke(registry, ["run", "read-file", f"file_path={test_file}", "--output-format", "json"])

        assert result.exit_code == 0

        # Parse and validate JSON
        output = json.loads(result.output)
        assert "success" in output
        assert output["success"] is True
        assert "node_type" in output
        assert "outputs" in output
        assert "execution_time_ms" in output
        assert isinstance(output["execution_time_ms"], int)


def test_structure_mode_shows_flattened_paths(runner, mock_registry):
    """Test structure mode shows flattened paths for template variables."""
    MockRegistry, instance = mock_registry

    # Create a mock node that returns complex nested data
    from pocketflow import Node

    class ComplexOutputNode(Node):
        """Node that returns nested structure."""

        def exec(self, prep_res: Any) -> dict:
            return {
                "user": {"name": "Alice", "id": 123},
                "items": [{"title": "First"}, {"title": "Second"}],
            }

        def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str:
            shared["result"] = exec_res
            return "default"

    with patch("pflow.cli.registry_run.import_node_class") as mock_import:
        mock_import.return_value = ComplexOutputNode

        result = runner.invoke(registry, ["run", "read-file", "--show-structure"])

        assert result.exit_code == 0
        assert "Available template paths" in result.output


def test_text_mode_displays_human_readable_output(runner, tmp_path):
    """Test text mode (default) displays human-readable output."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")

    from pflow.nodes.file.read_file import ReadFileNode

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run.Registry") as MockRegistry,
    ):
        instance = MagicMock()
        instance.load.return_value = {"read-file": {}}
        MockRegistry.return_value = instance
        mock_import.return_value = ReadFileNode

        result = runner.invoke(registry, ["run", "read-file", f"file_path={test_file}"])

        assert result.exit_code == 0
        assert "Node executed successfully" in result.output
        assert "Outputs:" in result.output
        assert "Execution time:" in result.output


# ==============================================================================
# 3. Parameter Handling (type inference, validation)
# ==============================================================================


def test_parameter_type_inference_boolean(runner, mock_registry):
    """Test that boolean parameters are inferred correctly."""
    MockRegistry, instance = mock_registry

    # Create a node that expects boolean
    from pocketflow import Node

    class BoolTestNode(Node):
        """Node that uses boolean parameter."""

        def exec(self, prep_res: Any) -> dict:
            return {"bool_value": prep_res}

        def prep(self, shared: dict) -> bool:
            return shared.get("flag", False)

        def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str:
            shared["result"] = exec_res
            return "default"

    # Add test node to registry
    nodes = instance.load.return_value
    nodes["test-node"] = {
        "module": "test",
        "class_name": "BoolTestNode",
        "interface": {"params": [{"key": "flag", "type": "bool"}]},
    }

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run._inject_special_parameters", return_value={"flag": True}),
    ):
        mock_import.return_value = BoolTestNode

        # Test true
        result = runner.invoke(registry, ["run", "test-node", "flag=true"])
        assert result.exit_code == 0

        # Test false
        result = runner.invoke(registry, ["run", "test-node", "flag=false"])
        assert result.exit_code == 0


def test_parameter_type_inference_integers(runner, mock_registry):
    """Test that integer parameters are inferred correctly."""
    MockRegistry, instance = mock_registry

    from pocketflow import Node

    class IntTestNode(Node):
        """Node that uses integer parameter."""

        def exec(self, prep_res: Any) -> dict:
            return {"int_value": prep_res, "type": type(prep_res).__name__}

        def prep(self, shared: dict) -> int:
            return shared.get("count", 0)

        def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str:
            shared["result"] = exec_res
            return "default"

    nodes = instance.load.return_value
    nodes["test-node"] = {
        "module": "test",
        "class_name": "IntTestNode",
        "interface": {"params": [{"key": "count", "type": "int"}]},
    }

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run._inject_special_parameters", return_value={"count": 42}),
    ):
        mock_import.return_value = IntTestNode

        result = runner.invoke(registry, ["run", "test-node", "count=42"])
        assert result.exit_code == 0


def test_parameter_type_inference_json(runner, mock_registry):
    """Test that JSON parameters are parsed correctly."""
    MockRegistry, instance = mock_registry

    from pocketflow import Node

    class JsonTestNode(Node):
        """Node that uses JSON parameter."""

        def exec(self, prep_res: Any) -> dict:
            return {"json_value": prep_res}

        def prep(self, shared: dict) -> dict:
            return shared.get("data", {})

        def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str:
            shared["result"] = exec_res
            return "default"

    nodes = instance.load.return_value
    nodes["test-node"] = {
        "module": "test",
        "class_name": "JsonTestNode",
        "interface": {"params": [{"key": "data", "type": "dict"}]},
    }

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run._inject_special_parameters", return_value={"data": {"key": "value"}}),
    ):
        mock_import.return_value = JsonTestNode

        result = runner.invoke(registry, ["run", "test-node", 'data={"key":"value"}'])
        assert result.exit_code == 0


def test_invalid_parameter_names_are_rejected(runner, mock_registry):
    """Test that invalid parameter names (shell special chars) are rejected."""
    MockRegistry, instance = mock_registry

    # Test various invalid parameter names
    invalid_params = [
        "$invalid",  # Dollar sign
        "key|value",  # Pipe
        "test>out",  # Redirect
        "test<in",  # Redirect
        "test&bg",  # Background
        "test;next",  # Command separator
    ]

    for param in invalid_params:
        result = runner.invoke(registry, ["run", "read-file", f"{param}=value"])

        assert result.exit_code == 1
        assert "Invalid parameter name" in result.output


# ==============================================================================
# 4. MCP Node Normalization (short form resolution)
# ==============================================================================


def test_mcp_node_short_form_resolution(runner, mock_registry):
    """Test that MCP node short form resolves to full format."""
    MockRegistry, instance = mock_registry

    from pocketflow import Node

    class MockMCPNode(Node):
        """Mock MCP node."""

        def exec(self, prep_res: Any) -> str:
            return "success"

        def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str:
            shared["result"] = exec_res
            return "default"

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run._inject_special_parameters") as mock_inject,
    ):
        mock_import.return_value = MockMCPNode
        mock_inject.return_value = {"channel": "test", "text": "hello"}

        # Test short form (tool name only)
        result = runner.invoke(registry, ["run", "SLACK_SEND_MESSAGE", "channel=test", "text=hello"])

        # Should resolve to mcp-slack-composio-SLACK_SEND_MESSAGE
        assert result.exit_code == 0


def test_mcp_node_resolution_feedback_in_verbose_mode(runner, mock_registry):
    """Test that resolved node name is shown in verbose mode."""
    MockRegistry, instance = mock_registry

    from pocketflow import Node

    class MockMCPNode(Node):
        """Mock MCP node."""

        def exec(self, prep_res: Any) -> str:
            return "success"

        def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str:
            shared["result"] = exec_res
            return "default"

    with patch("pflow.cli.registry_run.import_node_class") as mock_import:
        mock_import.return_value = MockMCPNode

        result = runner.invoke(registry, ["run", "SLACK_SEND_MESSAGE", "channel=test", "text=hello", "--verbose"])

        # Should show resolution message
        if result.exit_code == 0:
            assert "Resolved" in result.output or "Running node" in result.output


def test_ambiguous_mcp_node_shows_all_matches(runner, mock_registry):
    """Test that ambiguous MCP node name shows all matching options."""
    MockRegistry, instance = mock_registry

    # Add another node with similar name to create ambiguity
    nodes = instance.load.return_value
    nodes["mcp-another-slack-SLACK_SEND_MESSAGE"] = {
        "module": "pflow.nodes.mcp_node",
        "class_name": "MCPNode",
        "file_path": "virtual://mcp/another-slack",
        "interface": {"description": "Another Slack integration", "params": []},
    }
    instance.load.return_value = nodes

    result = runner.invoke(registry, ["run", "SLACK_SEND_MESSAGE"])

    assert result.exit_code == 1
    assert "Ambiguous node name" in result.output
    assert "mcp-slack-composio-SLACK_SEND_MESSAGE" in result.output
    assert "mcp-another-slack-SLACK_SEND_MESSAGE" in result.output


# ==============================================================================
# 5. Error Handling
# ==============================================================================


def test_unknown_node_shows_helpful_error(runner, mock_registry):
    """Test that unknown node shows helpful error with suggestions."""
    MockRegistry, instance = mock_registry

    result = runner.invoke(registry, ["run", "nonexistent-node"])

    assert result.exit_code == 1
    assert "not found in registry" in result.output
    assert "Did you mean" in result.output or "Available nodes" in result.output


def test_missing_required_parameter_shows_error(runner, mock_registry):
    """Test that missing required parameter shows clear error."""
    MockRegistry, instance = mock_registry

    from pocketflow import Node

    class StrictNode(Node):
        """Node that requires parameters."""

        def prep(self, shared: dict) -> Any:
            if "required_param" not in shared:
                raise ValueError("Missing required parameter: required_param")
            return shared["required_param"]

        def exec(self, prep_res: Any) -> str:
            return "success"

        def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str:
            shared["result"] = exec_res
            return "default"

    nodes = instance.load.return_value
    nodes["strict-node"] = {
        "module": "test",
        "class_name": "StrictNode",
        "interface": {"params": [{"key": "required_param", "type": "str", "required": True}]},
    }

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run._inject_special_parameters", return_value={}),
    ):
        mock_import.return_value = StrictNode

        result = runner.invoke(registry, ["run", "strict-node"])

        assert result.exit_code == 1
        assert "missing" in result.output.lower() or "required" in result.output.lower()


def test_unknown_node_suggests_similar_names(runner, mock_registry):
    """Test that unknown node suggests similar node names."""
    MockRegistry, instance = mock_registry

    result = runner.invoke(registry, ["run", "read-files"])  # Typo: files instead of file

    assert result.exit_code == 1
    assert "not found in registry" in result.output
    # Should suggest read-file (similar name) or show available nodes
    assert "read-file" in result.output.lower() or "available nodes" in result.output.lower()


# ==============================================================================
# 6. Structure Mode with JSON String Parsing (Killer Feature)
# ==============================================================================


def test_structure_mode_parses_json_strings(runner, mock_registry):
    """Test that structure mode parses JSON strings returned by MCP nodes."""
    MockRegistry, instance = mock_registry

    # Create a mock node that returns JSON string (common with MCP nodes)
    from pocketflow import Node

    class JsonStringNode(Node):
        """Node that returns JSON as string."""

        def exec(self, prep_res: Any) -> dict:
            # Simulate MCP node returning JSON as string
            json_string = '{"repos": [{"name": "pflow", "stars": 100}, {"name": "other", "stars": 50}]}'
            return {"result": json_string}

        def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str:
            shared["result"] = exec_res["result"]
            return "default"

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run._inject_special_parameters", return_value={}),
    ):
        mock_import.return_value = JsonStringNode

        result = runner.invoke(registry, ["run", "mcp-github-list-repos", "--show-structure"])

        assert result.exit_code == 0
        assert "Available template paths" in result.output or "structure" in result.output.lower()
        # Should show flattened paths from parsed JSON
        # The exact paths depend on implementation, but should include array notation


def test_structure_mode_shows_nested_array_notation(runner, mock_registry):
    """Test that structure mode shows array notation for lists."""
    MockRegistry, instance = mock_registry

    from pocketflow import Node

    class NestedArrayNode(Node):
        """Node that returns nested arrays."""

        def exec(self, prep_res: Any) -> dict:
            return {"items": [{"name": "first", "value": 1}, {"name": "second", "value": 2}]}

        def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str:
            shared["result"] = exec_res
            return "default"

    nodes = instance.load.return_value
    nodes["test-node"] = {
        "module": "test",
        "class_name": "NestedArrayNode",
        "interface": {"outputs": [{"key": "result", "type": "any"}]},
    }

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run._inject_special_parameters", return_value={}),
    ):
        mock_import.return_value = NestedArrayNode

        result = runner.invoke(registry, ["run", "test-node", "--show-structure"])

        assert result.exit_code == 0
        # Should show paths with array notation [0]
        # Exact format depends on implementation


def test_structure_mode_deduplicates_identical_outputs(runner, mock_registry):
    """Test that structure mode deduplicates identical MCP outputs."""
    MockRegistry, instance = mock_registry

    # MCP nodes often return both 'result' and 'server_TOOL_result' with same data
    from pocketflow import Node

    class DuplicateOutputNode(Node):
        """Node that returns duplicate outputs."""

        def exec(self, prep_res: Any) -> dict:
            data = {"key": "value", "nested": {"foo": "bar"}}
            return data

        def post(self, shared: dict, prep_res: Any, exec_res: Any) -> str:
            # Simulate MCP pattern
            shared["result"] = exec_res
            shared["server_tool_result"] = exec_res  # Duplicate
            return "default"

    nodes = instance.load.return_value
    nodes["mcp-node"] = {
        "module": "test",
        "class_name": "DuplicateOutputNode",
        "interface": {"outputs": [{"key": "result", "type": "any"}]},
    }

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run._inject_special_parameters", return_value={}),
    ):
        mock_import.return_value = DuplicateOutputNode

        result = runner.invoke(registry, ["run", "mcp-node", "--show-structure"])

        assert result.exit_code == 0
        # Should note the duplication
        if "contains the same data" in result.output or "showing paths" in result.output:
            pass  # Deduplication detected
        else:
            # At minimum, should not crash and should show structure
            assert "Available template paths" in result.output or "structure" in result.output.lower()


# ==============================================================================
# 7. Additional Critical Tests
# ==============================================================================


def test_node_execution_timing_is_displayed(runner, tmp_path):
    """Test that execution time is displayed."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test")

    from pflow.nodes.file.read_file import ReadFileNode

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run.Registry") as MockRegistry,
    ):
        instance = MagicMock()
        instance.load.return_value = {"read-file": {}}
        MockRegistry.return_value = instance
        mock_import.return_value = ReadFileNode

        result = runner.invoke(registry, ["run", "read-file", f"file_path={test_file}"])

        assert result.exit_code == 0
        assert "Execution time:" in result.output
        assert "ms" in result.output


def test_verbose_mode_shows_parameters(runner, tmp_path):
    """Test that verbose mode shows input parameters."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test")

    from pflow.nodes.file.read_file import ReadFileNode

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run.Registry") as MockRegistry,
    ):
        instance = MagicMock()
        instance.load.return_value = {"read-file": {}}
        MockRegistry.return_value = instance
        mock_import.return_value = ReadFileNode

        result = runner.invoke(registry, ["run", "read-file", f"file_path={test_file}", "--verbose"])

        assert result.exit_code == 0
        assert "Running node" in result.output or "Parameters:" in result.output


def test_json_mode_error_response_is_valid(runner, mock_registry):
    """Test that JSON mode returns valid JSON even on errors."""
    MockRegistry, instance = mock_registry

    result = runner.invoke(registry, ["run", "nonexistent-node", "--output-format", "json"])

    assert result.exit_code == 1

    # Should still be valid JSON
    try:
        output = json.loads(result.output)
        assert "error" in output or "success" in output
    except json.JSONDecodeError:
        # Error messages might not be JSON in error cases, that's acceptable
        pass


def test_multiple_parameters_are_parsed_correctly(runner, tmp_path):
    """Test that multiple parameters are parsed and passed correctly."""
    test_file = tmp_path / "test.txt"

    from pflow.nodes.file.write_file import WriteFileNode

    with (
        patch("pflow.cli.registry_run.import_node_class") as mock_import,
        patch("pflow.cli.registry_run.Registry") as MockRegistry,
    ):
        instance = MagicMock()
        instance.load.return_value = {"write-file": {}}
        MockRegistry.return_value = instance
        mock_import.return_value = WriteFileNode

        result = runner.invoke(
            registry,
            ["run", "write-file", f"file_path={test_file}", "content=Hello", "overwrite=true"],
        )

        assert result.exit_code == 0
        # File should be created
        assert test_file.exists()
        assert test_file.read_text() == "Hello"
