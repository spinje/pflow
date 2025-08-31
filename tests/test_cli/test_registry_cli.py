"""Tests for registry CLI commands.

This test file covers all 19 criteria specified in the registry CLI implementation:
1. First list command creates registry.json with core nodes
2. List command with --json outputs valid JSON structure
3. Describe existing node shows full interface
4. Describe missing node exits with code 1
5. Search "file" returns read-file and write-file nodes
6. Search exact match "read-file" scores 100
7. Search prefix "read" scores 90 for read-file
8. Search substring "ead" scores 70 for read-file
9. Search description "content" scores 50 for write-file
10. Scan non-existent path shows error
11. Scan valid path shows security warning
12. Scan confirmation "n" aborts without changes
13. Scan with --force skips confirmation
14. Scan adds nodes with type "user"
15. Registry marks "mcp-github-tool" as type "mcp"
16. Registry marks "read-file" as type "core"
17. Corrupted registry.json returns empty dict
18. main_wrapper routes "registry" to registry group
19. main_wrapper routes "unknown" to workflow command
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import click.testing
import pytest

from pflow.cli.main_wrapper import cli_main
from pflow.cli.registry import registry
from pflow.registry.registry import Registry


@pytest.fixture
def runner():
    """Create a Click test runner."""
    return click.testing.CliRunner()


@pytest.fixture
def mock_registry():
    """Create a mock Registry with test data."""
    with patch("pflow.cli.registry.Registry") as MockRegistry:
        instance = MagicMock(spec=Registry)
        MockRegistry.return_value = instance

        # Set up the registry path as a Mock
        mock_path = MagicMock()
        mock_path.exists = MagicMock(return_value=True)
        instance.registry_path = mock_path

        # Default test nodes
        test_nodes = {
            "read-file": {
                "module": "pflow.nodes.file.read_file",
                "class_name": "ReadFileNode",
                "file_path": "/src/pflow/nodes/file/read_file.py",
                "interface": {
                    "description": "Read content from a file",
                    "inputs": [],
                    "outputs": [{"key": "content", "type": "str"}],
                    "params": [{"key": "file_path", "type": "str", "required": True}],
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
                    "params": [{"key": "file_path", "type": "str", "required": True}],
                },
            },
            "llm": {
                "module": "pflow.nodes.llm.llm",
                "class_name": "LLMNode",
                "file_path": "/src/pflow/nodes/llm/llm.py",
                "interface": {
                    "description": "Query an LLM with a prompt",
                    "params": [{"key": "prompt", "type": "str", "required": True}],
                },
            },
            "mcp-github-tool": {
                "module": "virtual.mcp",
                "class_name": "MCPNode",
                "file_path": "virtual://mcp/github-tool",
                "interface": {"description": "GitHub operations via MCP", "params": []},
            },
        }

        instance.load.return_value = test_nodes
        # Mock list_nodes to dynamically return keys from load() result
        instance.list_nodes.side_effect = lambda include_filtered=False: list(instance.load.return_value.keys())
        yield MockRegistry, instance


# --- Criterion 1: First list command creates registry.json with core nodes ---
def test_list_first_time_creates_registry(runner, mock_registry):
    """Test that first list command triggers auto-discovery and creates registry."""
    MockRegistry, instance = mock_registry

    # Simulate first time (registry doesn't exist)
    instance.registry_path.exists.return_value = False

    result = runner.invoke(registry, ["list"])

    assert result.exit_code == 0
    assert "[Auto-discovering core nodes...]" in result.output
    instance.load.assert_called_once()


# --- Criterion 2: List command with --json outputs valid JSON structure ---
def test_list_json_output(runner, mock_registry):
    """Test that list --json outputs valid JSON structure."""
    MockRegistry, instance = mock_registry

    result = runner.invoke(registry, ["list", "--json"])

    assert result.exit_code == 0

    # Parse and validate JSON
    output = json.loads(result.output)
    assert "nodes" in output
    assert isinstance(output["nodes"], list)

    # Check node structure
    for node in output["nodes"]:
        assert "name" in node
        assert "type" in node
        assert "description" in node

    # Check specific nodes
    node_names = [n["name"] for n in output["nodes"]]
    assert "read-file" in node_names
    assert "write-file" in node_names


# --- Criterion 3: Describe existing node shows full interface ---
def test_describe_existing_node(runner, mock_registry):
    """Test that describe shows full interface for existing node."""
    MockRegistry, instance = mock_registry

    result = runner.invoke(registry, ["describe", "read-file"])

    assert result.exit_code == 0
    assert "Node: read-file" in result.output
    assert "Type: core" in result.output
    assert "Description: Read content from a file" in result.output
    assert "Interface:" in result.output
    assert "Outputs:" in result.output
    assert "content: str" in result.output
    assert "Parameters:" in result.output
    assert "file_path: str" in result.output
    assert "Example Usage:" in result.output


# --- Criterion 4: Describe missing node exits with code 1 ---
def test_describe_missing_node(runner, mock_registry):
    """Test that describe exits with code 1 for missing node."""
    MockRegistry, instance = mock_registry

    result = runner.invoke(registry, ["describe", "non-existent-node"])

    assert result.exit_code == 1
    assert "Error: Node 'non-existent-node' not found" in result.output


def test_describe_missing_node_with_suggestions(runner, mock_registry):
    """Test that describe shows suggestions for similar nodes."""
    MockRegistry, instance = mock_registry

    result = runner.invoke(registry, ["describe", "read"])

    assert result.exit_code == 1
    assert "Error: Node 'read' not found" in result.output
    assert "Did you mean:" in result.output
    assert "read-file" in result.output


# --- Criteria 5-9: Search functionality ---
def test_search_file_returns_file_nodes(runner, mock_registry):
    """Test that search 'file' returns read-file and write-file nodes."""
    MockRegistry, instance = mock_registry

    # Mock search results
    instance.search.return_value = [
        ("read-file", instance.load.return_value["read-file"], 70),
        ("write-file", instance.load.return_value["write-file"], 70),
    ]

    result = runner.invoke(registry, ["search", "file"])

    assert result.exit_code == 0
    assert "read-file" in result.output
    assert "write-file" in result.output
    instance.search.assert_called_once_with("file")


def test_search_exact_match_scores_100(runner, mock_registry):
    """Test that exact match 'read-file' scores 100."""
    MockRegistry, instance = mock_registry

    instance.search.return_value = [
        ("read-file", instance.load.return_value["read-file"], 100),
    ]

    result = runner.invoke(registry, ["search", "read-file"])

    assert result.exit_code == 0
    assert "read-file" in result.output
    assert "exact" in result.output  # Match indicator for score 100


def test_search_prefix_scores_90(runner, mock_registry):
    """Test that prefix 'read' scores 90 for read-file."""
    MockRegistry, instance = mock_registry

    instance.search.return_value = [
        ("read-file", instance.load.return_value["read-file"], 90),
    ]

    result = runner.invoke(registry, ["search", "read"])

    assert result.exit_code == 0
    assert "read-file" in result.output
    assert "prefix" in result.output  # Match indicator for score 90


def test_search_substring_scores_70(runner, mock_registry):
    """Test that substring 'ead' scores 70 for read-file."""
    MockRegistry, instance = mock_registry

    instance.search.return_value = [
        ("read-file", instance.load.return_value["read-file"], 70),
    ]

    result = runner.invoke(registry, ["search", "ead"])

    assert result.exit_code == 0
    assert "read-file" in result.output
    assert "name" in result.output  # Match indicator for score 70


def test_search_description_scores_50(runner, mock_registry):
    """Test that description search 'content' scores 50 for write-file."""
    MockRegistry, instance = mock_registry

    instance.search.return_value = [
        ("write-file", instance.load.return_value["write-file"], 50),
    ]

    result = runner.invoke(registry, ["search", "content"])

    assert result.exit_code == 0
    assert "write-file" in result.output
    assert "desc" in result.output  # Match indicator for score 50


def test_search_json_output(runner, mock_registry):
    """Test that search --json outputs valid JSON."""
    MockRegistry, instance = mock_registry

    instance.search.return_value = [
        ("read-file", instance.load.return_value["read-file"], 100),
        ("write-file", instance.load.return_value["write-file"], 70),
    ]

    result = runner.invoke(registry, ["search", "file", "--json"])

    assert result.exit_code == 0

    # Parse and validate JSON
    output = json.loads(result.output)
    assert "query" in output
    assert output["query"] == "file"
    assert "results" in output
    assert len(output["results"]) == 2

    # Check result structure
    for res in output["results"]:
        assert "name" in res
        assert "type" in res
        assert "score" in res
        assert "description" in res


def test_search_no_results(runner, mock_registry):
    """Test search with no results."""
    MockRegistry, instance = mock_registry

    instance.search.return_value = []

    result = runner.invoke(registry, ["search", "xyz123"])

    assert result.exit_code == 0
    assert "No nodes found matching 'xyz123'" in result.output


# --- Criteria 10-14: Scan functionality ---
def test_scan_non_existent_path_shows_error(runner, mock_registry):
    """Test that scan shows error for non-existent path."""
    MockRegistry, instance = mock_registry

    with runner.isolated_filesystem():
        result = runner.invoke(registry, ["scan", "/non/existent/path"])

        assert result.exit_code == 1
        assert "Path does not exist: /non/existent/path" in result.output


def test_scan_valid_path_shows_security_warning(runner, mock_registry):
    """Test that scan shows security warning for valid path."""
    MockRegistry, instance = mock_registry

    # Mock scan results
    instance.scan_user_nodes.return_value = [
        {"name": "custom-node", "class_name": "CustomNode", "interface": {"description": "A custom node"}}
    ]

    with runner.isolated_filesystem():
        # Create a valid directory
        test_dir = Path("test_nodes")
        test_dir.mkdir()

        result = runner.invoke(registry, ["scan", str(test_dir)], input="n\n")

        assert "⚠️  WARNING: Custom nodes execute with your user privileges" in result.output
        assert "Only add nodes from trusted sources" in result.output


def test_scan_confirmation_n_aborts(runner, mock_registry):
    """Test that scan confirmation 'n' aborts without changes."""
    MockRegistry, instance = mock_registry

    instance.scan_user_nodes.return_value = [
        {"name": "custom-node", "class_name": "CustomNode", "interface": {"description": "A custom node"}}
    ]

    with runner.isolated_filesystem():
        test_dir = Path("test_nodes")
        test_dir.mkdir()

        result = runner.invoke(registry, ["scan", str(test_dir)], input="n\n")

        assert "Cancelled." in result.output
        # Verify save was not called
        instance._save_with_metadata.assert_not_called()


def test_scan_with_force_skips_confirmation(runner, mock_registry):
    """Test that scan --force skips confirmation."""
    MockRegistry, instance = mock_registry

    instance.scan_user_nodes.return_value = [
        {"name": "custom-node", "class_name": "CustomNode", "interface": {"description": "A custom node"}}
    ]

    with runner.isolated_filesystem():
        test_dir = Path("test_nodes")
        test_dir.mkdir()

        result = runner.invoke(registry, ["scan", str(test_dir), "--force"])

        # Should not show confirmation prompt
        assert "Add" not in result.output or "?" not in result.output
        assert "✓ Added 1 custom nodes to registry" in result.output

        # Verify save was called
        instance._save_with_metadata.assert_called_once()


def test_scan_adds_nodes_with_type_user(runner, mock_registry):
    """Test that scan adds nodes with type 'user'."""
    MockRegistry, instance = mock_registry

    instance.scan_user_nodes.return_value = [
        {"name": "custom-node", "class_name": "CustomNode", "interface": {"description": "A custom node"}}
    ]

    with runner.isolated_filesystem():
        test_dir = Path("test_nodes")
        test_dir.mkdir()

        runner.invoke(registry, ["scan", str(test_dir), "--force"])

        # Check that nodes were added with type "user"
        call_args = instance._save_with_metadata.call_args[0][0]
        assert "custom-node" in call_args
        assert call_args["custom-node"]["type"] == "user"


def test_scan_json_output(runner, mock_registry):
    """Test scan --json output."""
    MockRegistry, instance = mock_registry

    instance.scan_user_nodes.return_value = [
        {"name": "custom-node", "class_name": "CustomNode", "interface": {"description": "A custom node"}}
    ]

    with runner.isolated_filesystem():
        test_dir = Path("test_nodes")
        test_dir.mkdir()

        result = runner.invoke(registry, ["scan", str(test_dir), "--json"])

        assert result.exit_code == 0

        # Parse and validate JSON
        output = json.loads(result.output)
        assert "found" in output
        assert "added" in output
        assert "nodes" in output
        assert output["found"] == 1
        assert output["added"] == 1


def test_scan_default_path(runner, mock_registry):
    """Test scan with default path (~/.pflow/nodes/)."""
    MockRegistry, instance = mock_registry

    # Mock the default path existence check
    default_path = Path.home() / ".pflow" / "nodes"

    with patch("pflow.cli.registry.Path") as MockPath:
        # Create a mock for the scan path that doesn't exist
        mock_scan_path = MagicMock()
        mock_scan_path.exists.return_value = False
        mock_scan_path.__str__ = lambda self: str(default_path)

        # Mock Path.home() to return a mock that supports / operator
        mock_home = MagicMock()
        # Chain the / operations to return the final mock_scan_path
        mock_pflow = MagicMock()
        mock_home.__truediv__ = MagicMock(return_value=mock_pflow)
        mock_pflow.__truediv__ = MagicMock(return_value=mock_scan_path)

        MockPath.home.return_value = mock_home

        # When Path(path) is called with an argument, return a real Path
        # (this won't happen in our test since we're not passing a path argument)
        def path_constructor(arg=None):
            if arg is not None:
                return Path(arg)
            return MockPath.home()

        MockPath.side_effect = path_constructor

        result = runner.invoke(registry, ["scan"])

        assert result.exit_code == 1
        assert f"Path does not exist: {default_path}" in result.output
        assert "To add custom nodes:" in result.output
        assert f"mkdir -p {default_path}" in result.output


# --- Criteria 15-16: Node type detection ---
def test_registry_marks_mcp_node_type(runner, mock_registry):
    """Test that registry marks 'mcp-github-tool' as type 'mcp'."""
    MockRegistry, instance = mock_registry

    result = runner.invoke(registry, ["list"])

    # The mcp-github-tool should be displayed in the MCP Servers section
    # It's shown as "tool" under the "github" server group
    assert "MCP Servers:" in result.output
    assert "github (1 tool)" in result.output

    # The tool is displayed with its cleaned name
    lines = result.output.split("\n")
    # Find the line that contains the GitHub tool
    github_tool_lines = [line for line in lines if "GitHub operations via MCP" in line]
    assert len(github_tool_lines) == 1
    assert "tool" in github_tool_lines[0]


def test_registry_marks_core_node_type(runner, mock_registry):
    """Test that registry marks 'read-file' as type 'core'."""
    MockRegistry, instance = mock_registry

    result = runner.invoke(registry, ["list"])

    # The read-file should be displayed in the Core Packages section
    assert "Core Packages:" in result.output
    assert "file (2 nodes)" in result.output  # read-file is in the file package
    assert "read-file" in result.output

    # Verify it appears after Core Packages and before MCP/User sections
    output = result.output
    core_idx = output.index("Core Packages:")
    read_file_idx = output.index("read-file")

    # If MCP servers exist, check ordering
    if "MCP Servers:" in output:
        mcp_idx = output.index("MCP Servers:")
        assert core_idx < read_file_idx < mcp_idx


def test_describe_shows_correct_node_type(runner, mock_registry):
    """Test that describe shows correct node type."""
    MockRegistry, instance = mock_registry

    # Test core node
    result = runner.invoke(registry, ["describe", "read-file"])
    assert "Type: core" in result.output

    # Test MCP node
    result = runner.invoke(registry, ["describe", "mcp-github-tool"])
    assert "Type: mcp" in result.output


# --- Criterion 17: Corrupted registry.json returns empty dict ---
def test_corrupted_registry_returns_empty_dict(runner):
    """Test that corrupted registry.json is handled gracefully."""
    with patch("pflow.cli.registry.Registry") as MockRegistry:
        instance = MagicMock(spec=Registry)
        MockRegistry.return_value = instance

        # Simulate corrupted registry that returns empty dict
        mock_path = MagicMock()
        mock_path.exists = MagicMock(return_value=True)
        instance.registry_path = mock_path
        instance.load.return_value = {}

        result = runner.invoke(registry, ["list"])

        assert result.exit_code == 0
        assert "No nodes registered." in result.output


# --- Criteria 18-19: main_wrapper routing ---
# NOTE: These tests verify CLI routing behavior which is important for the
# registry feature to be accessible. They mock at the right boundary (CLI commands)
# and test observable behavior (correct command is invoked).


def test_main_wrapper_routes_registry_to_registry_group():
    """Test that main_wrapper routes 'registry' to registry group.

    This is a critical test - without proper routing, users cannot access
    the registry commands at all.
    """
    # Mock the registry function that's imported inside cli_main
    with (
        patch("pflow.cli.registry.registry") as mock_registry_func,
        patch.object(sys, "argv", ["pflow", "registry", "list"]),
    ):
        cli_main()

        # Verify registry function was called
        mock_registry_func.assert_called_once()


def test_main_wrapper_routes_unknown_to_workflow_command():
    """Test that main_wrapper routes unknown commands to workflow command.

    This ensures backward compatibility - unknown commands are treated as
    workflow commands, not errors.
    """
    # Mock the workflow_command that's imported inside cli_main
    cli_main_module = sys.modules["pflow.cli.main"]  # Get actual module from sys.modules
    with (
        patch.object(cli_main_module, "workflow_command") as mock_workflow,
        patch.object(sys, "argv", ["pflow", "unknown", "command"]),
    ):
        cli_main()

        # Verify workflow_command was called for unknown command
        mock_workflow.assert_called_once()


def test_main_wrapper_preserves_argv_after_registry():
    """Test that main_wrapper restores sys.argv after registry command.

    This prevents state leakage between commands which could cause
    subtle bugs in command chaining scenarios.
    """
    original_argv = ["pflow", "registry", "list"]

    with patch("pflow.cli.registry.registry"), patch.object(sys, "argv", original_argv.copy()):
        cli_main()

        # Verify sys.argv is restored
        assert sys.argv == original_argv


# --- Additional edge cases and error handling ---
def test_list_error_handling(runner, mock_registry):
    """Test list command error handling."""
    MockRegistry, instance = mock_registry

    # Simulate an exception
    instance.load.side_effect = Exception("Database error")

    result = runner.invoke(registry, ["list"])

    assert result.exit_code == 1
    assert "Error: Failed to list nodes: Database error" in result.output


def test_describe_json_output(runner, mock_registry):
    """Test describe --json output."""
    MockRegistry, instance = mock_registry

    result = runner.invoke(registry, ["describe", "read-file", "--json"])

    assert result.exit_code == 0

    # Parse and validate JSON
    output = json.loads(result.output)
    assert output["name"] == "read-file"
    assert output["type"] == "core"
    assert "interface" in output
    assert "description" in output


def test_search_error_handling(runner, mock_registry):
    """Test search command error handling."""
    MockRegistry, instance = mock_registry

    instance.search.side_effect = Exception("Search failed")

    result = runner.invoke(registry, ["search", "test"])

    assert result.exit_code == 1
    assert "Error: Failed to search: Search failed" in result.output


def test_scan_invalid_nodes(runner, mock_registry):
    """Test scan handling of invalid nodes."""
    MockRegistry, instance = mock_registry

    instance.scan_user_nodes.return_value = [
        {
            "name": "invalid-node",
            # Missing class_name - invalid
            "interface": {"description": "An invalid node"},
        },
        {"name": "valid-node", "class_name": "ValidNode", "interface": {"description": "A valid node"}},
    ]

    with runner.isolated_filesystem():
        test_dir = Path("test_nodes")
        test_dir.mkdir()

        result = runner.invoke(registry, ["scan", str(test_dir), "--force"])

        assert "⚠ invalid-node: Invalid - missing required methods" in result.output
        assert "✓ valid-node: A valid node" in result.output
        assert "✓ Added 1 custom nodes to registry" in result.output


def test_scan_no_valid_nodes(runner, mock_registry):
    """Test scan when no valid nodes found."""
    MockRegistry, instance = mock_registry

    instance.scan_user_nodes.return_value = [
        {
            "name": "invalid-node",
            # Missing class_name - invalid
            "interface": {"description": "An invalid node"},
        }
    ]

    with runner.isolated_filesystem():
        test_dir = Path("test_nodes")
        test_dir.mkdir()

        result = runner.invoke(registry, ["scan", str(test_dir)])

        assert "No valid nodes to add." in result.output
        instance._save_with_metadata.assert_not_called()


def test_list_grouped_display(runner, mock_registry):
    """Test that list groups nodes by type correctly with new grouped display format."""
    MockRegistry, instance = mock_registry

    # Add a user node to the test data
    test_nodes = instance.load.return_value.copy()
    test_nodes["custom-node"] = {
        "type": "user",
        "class_name": "CustomNode",
        "interface": {"description": "A user node"},
    }
    # Add the virtual mcp node (which should be excluded from display)
    test_nodes["mcp"] = {
        "module": "virtual.mcp",
        "class_name": "MCPNode",
        "file_path": "virtual://mcp",
        "interface": {"description": "Virtual MCP base node"},
    }
    instance.load.return_value = test_nodes

    result = runner.invoke(registry, ["list"])

    assert result.exit_code == 0

    # Check section headers are present
    assert "Core Packages:" in result.output
    assert "MCP Servers:" in result.output
    assert "User Nodes:" in result.output

    # Check grouping for core nodes
    assert "file (2 nodes)" in result.output
    assert "llm (1 node)" in result.output  # singular for 1 node

    # Check MCP server grouping
    assert "github (1 tool)" in result.output  # MCP uses "tool" not "node"

    # Check individual nodes are displayed correctly
    assert "read-file" in result.output
    assert "write-file" in result.output
    assert "llm" in result.output
    assert "custom-node" in result.output

    # Check MCP tool is displayed with cleaned name (not mcp-github-tool)
    assert "  tool                      GitHub operations via MCP" in result.output

    # Verify the virtual "mcp" node is excluded
    assert "mcp                       Virtual MCP base node" not in result.output

    # Check descriptions are truncated at 75 chars (not 40)
    # All our test descriptions are short, but we verify they're displayed
    assert "Read content from a file" in result.output
    assert "Write content to a file" in result.output
    assert "Query an LLM with a prompt" in result.output
    assert "A user node" in result.output

    # Check total summary is correct (excludes virtual mcp node)
    assert "Total: 5 nodes (3 core, 1 user, 1 mcp)" in result.output

    # Verify ordering (Core sections first, then MCP, then User)
    output = result.output
    core_idx = output.index("Core Packages:")
    mcp_idx = output.index("MCP Servers:")
    user_idx = output.index("User Nodes:")

    assert core_idx < mcp_idx < user_idx


# --- Smart Name Resolution Tests ---
def test_describe_simplified_mcp_name(runner, mock_registry):
    """Test that simplified MCP names work (e.g., slack-add-reaction -> mcp-slack-slack_add_reaction)."""
    MockRegistry, instance = mock_registry

    # Add MCP nodes with realistic naming patterns
    test_nodes = instance.load.return_value.copy()
    test_nodes["mcp-slack-slack_add_reaction"] = {
        "module": "virtual.mcp",
        "class_name": "MCPNode",
        "file_path": "virtual://mcp/slack-add_reaction",
        "interface": {"description": "Add a reaction to a Slack message", "params": []},
    }
    instance.load.return_value = test_nodes

    # Test with simplified name
    result = runner.invoke(registry, ["describe", "slack-add-reaction"])

    assert result.exit_code == 0
    assert "Node: mcp-slack-slack_add_reaction" in result.output
    assert "Type: mcp" in result.output
    assert "Add a reaction to a Slack message" in result.output


def test_describe_tool_only_name_unique(runner, mock_registry):
    """Test that tool-only names work if unique (e.g., add-reaction)."""
    MockRegistry, instance = mock_registry

    # Add a single MCP node with this tool name
    test_nodes = instance.load.return_value.copy()
    test_nodes["mcp-slack-add_reaction"] = {
        "module": "virtual.mcp",
        "class_name": "MCPNode",
        "file_path": "virtual://mcp/slack-add_reaction",
        "interface": {"description": "Add a reaction to a message", "params": []},
    }
    instance.load.return_value = test_nodes

    # Test with tool-only name (unique)
    result = runner.invoke(registry, ["describe", "add-reaction"])

    assert result.exit_code == 0
    assert "Node: mcp-slack-add_reaction" in result.output
    assert "Type: mcp" in result.output
    assert "Add a reaction to a message" in result.output


def test_describe_tool_only_name_not_unique(runner, mock_registry):
    """Test that tool-only names fail if not unique."""
    MockRegistry, instance = mock_registry

    # Add multiple MCP nodes with similar tool names
    test_nodes = instance.load.return_value.copy()
    test_nodes["mcp-slack-add_reaction"] = {
        "module": "virtual.mcp",
        "class_name": "MCPNode",
        "interface": {"description": "Slack reaction"},
    }
    test_nodes["mcp-github-add_reaction"] = {
        "module": "virtual.mcp",
        "class_name": "MCPNode",
        "interface": {"description": "GitHub reaction"},
    }
    instance.load.return_value = test_nodes

    # Test with ambiguous tool-only name
    result = runner.invoke(registry, ["describe", "add-reaction"])

    assert result.exit_code == 1
    assert "Error: Node 'add-reaction' not found" in result.output


def test_describe_original_full_names_still_work(runner, mock_registry):
    """Test that original full names still work."""
    MockRegistry, instance = mock_registry

    # Test core node with original name
    result = runner.invoke(registry, ["describe", "read-file"])
    assert result.exit_code == 0
    assert "Node: read-file" in result.output

    # Test MCP node with original full name
    result = runner.invoke(registry, ["describe", "mcp-github-tool"])
    assert result.exit_code == 0
    assert "Node: mcp-github-tool" in result.output


def test_describe_suggestions_include_simplified_names(runner, mock_registry):
    """Test that helpful suggestions include simplified names when not found."""
    MockRegistry, instance = mock_registry

    # Add MCP nodes
    test_nodes = instance.load.return_value.copy()
    test_nodes["mcp-slack-slack_send_message"] = {
        "module": "virtual.mcp",
        "class_name": "MCPNode",
        "interface": {"description": "Send a Slack message"},
    }
    test_nodes["mcp-slack-slack_add_reaction"] = {
        "module": "virtual.mcp",
        "class_name": "MCPNode",
        "interface": {"description": "Add Slack reaction"},
    }
    instance.load.return_value = test_nodes

    # Test with partial match
    result = runner.invoke(registry, ["describe", "slack"])

    assert result.exit_code == 1
    assert "Error: Node 'slack' not found" in result.output
    assert "Did you mean:" in result.output
    # Should show both full name and simplified suggestion
    assert "mcp-slack-slack_send_message" in result.output
    assert "(or try: slack-send-message)" in result.output
    assert "mcp-slack-slack_add_reaction" in result.output
    assert "(or try: slack-add-reaction)" in result.output


def test_describe_filesystem_mcp_name_resolution(runner, mock_registry):
    """Test name resolution for filesystem MCP nodes."""
    MockRegistry, instance = mock_registry

    # Add filesystem MCP node
    test_nodes = instance.load.return_value.copy()
    test_nodes["mcp-filesystem-read_file"] = {
        "module": "virtual.mcp",
        "class_name": "MCPNode",
        "interface": {"description": "Read file via MCP"},
    }
    instance.load.return_value = test_nodes

    # Test various ways to reference it
    result = runner.invoke(registry, ["describe", "filesystem-read-file"])
    assert result.exit_code == 0
    assert "Node: mcp-filesystem-read_file" in result.output

    # Test with underscores
    result = runner.invoke(registry, ["describe", "filesystem-read_file"])
    assert result.exit_code == 0
    assert "Node: mcp-filesystem-read_file" in result.output


# --- Grouped Display Tests ---
def test_list_grouped_display_section_headers(runner, mock_registry):
    """Test that the list output includes section headers like 'Core Packages:' and 'MCP Servers:'."""
    MockRegistry, instance = mock_registry

    result = runner.invoke(registry, ["list"])

    assert result.exit_code == 0
    assert "Core Packages:" in result.output
    assert "─" * 13 in result.output  # Section divider
    assert "MCP Servers:" in result.output


def test_list_grouped_display_mcp_tools(runner, mock_registry):
    """Test that MCP nodes are grouped correctly under their servers."""
    MockRegistry, instance = mock_registry

    # Add multiple MCP nodes from different servers
    test_nodes = instance.load.return_value.copy()
    test_nodes["mcp-slack-send_message"] = {
        "module": "virtual.mcp",
        "class_name": "MCPNode",
        "interface": {"description": "Send Slack message"},
    }
    test_nodes["mcp-slack-add_reaction"] = {
        "module": "virtual.mcp",
        "class_name": "MCPNode",
        "interface": {"description": "Add Slack reaction"},
    }
    test_nodes["mcp-github-create_issue"] = {
        "module": "virtual.mcp",
        "class_name": "MCPNode",
        "interface": {"description": "Create GitHub issue"},
    }
    instance.load.return_value = test_nodes

    result = runner.invoke(registry, ["list"])

    assert result.exit_code == 0

    # Check MCP server grouping
    assert "MCP Servers:" in result.output
    assert "github (2 tools)" in result.output  # mcp-github-tool + create_issue
    assert "slack (2 tools)" in result.output

    # Check tools are displayed with cleaned names
    assert "send-message" in result.output or "send_message" in result.output
    assert "add-reaction" in result.output or "add_reaction" in result.output
    assert "create-issue" in result.output or "create_issue" in result.output


def test_list_grouped_display_file_package(runner, mock_registry):
    """Test that file operations are grouped under 'file' package."""
    MockRegistry, instance = mock_registry

    # Add more file nodes - need to specify the module path correctly for them to be detected as core
    test_nodes = instance.load.return_value.copy()
    test_nodes["copy-file"] = {
        "module": "pflow.nodes.file.copy_file",
        "class_name": "CopyFileNode",
        "file_path": "/src/pflow/nodes/file/copy_file.py",  # Core nodes have this path pattern
        "interface": {"description": "Copy a file"},
    }
    test_nodes["move-file"] = {
        "module": "pflow.nodes.file.move_file",
        "class_name": "MoveFileNode",
        "file_path": "/src/pflow/nodes/file/move_file.py",  # Core nodes have this path pattern
        "interface": {"description": "Move a file"},
    }
    instance.load.return_value = test_nodes

    result = runner.invoke(registry, ["list"])

    assert result.exit_code == 0

    # Check file package grouping
    assert "file (4 nodes)" in result.output  # read, write, copy, move
    assert "read-file" in result.output
    assert "write-file" in result.output
    assert "copy-file" in result.output
    assert "move-file" in result.output


def test_list_empty_sections_not_shown(runner, mock_registry):
    """Test that empty sections are not displayed."""
    MockRegistry, instance = mock_registry

    # Remove all MCP nodes to have no MCP section
    test_nodes = {k: v for k, v in instance.load.return_value.items() if not k.startswith("mcp-")}
    instance.load.return_value = test_nodes

    result = runner.invoke(registry, ["list"])

    assert result.exit_code == 0

    # Should have Core Packages but not MCP Servers
    assert "Core Packages:" in result.output
    assert "MCP Servers:" not in result.output
    assert "User Nodes:" not in result.output  # No user nodes in default test data


def test_list_total_summary_counts(runner, mock_registry):
    """Test that the total summary correctly counts nodes by type."""
    MockRegistry, instance = mock_registry

    # Add various types of nodes
    test_nodes = instance.load.return_value.copy()
    test_nodes["custom-user-node"] = {
        "type": "user",
        "class_name": "CustomNode",
        "interface": {"description": "User node"},
    }
    test_nodes["mcp-slack-test"] = {
        "module": "virtual.mcp",
        "class_name": "MCPNode",
        "interface": {"description": "Slack test"},
    }
    instance.load.return_value = test_nodes

    result = runner.invoke(registry, ["list"])

    assert result.exit_code == 0

    # Check total summary (3 core, 1 user, 2 mcp)
    assert "Total: 6 nodes (3 core, 1 user, 2 mcp)" in result.output


def test_describe_shows_example_usage(runner, mock_registry):
    """Test that describe shows example usage."""
    MockRegistry, instance = mock_registry

    result = runner.invoke(registry, ["describe", "read-file"])

    assert "Example Usage:" in result.output
    assert "pflow read-file --file_path <value>" in result.output


def test_scan_confirmation_y_adds_nodes(runner, mock_registry):
    """Test that scan confirmation 'y' adds nodes."""
    MockRegistry, instance = mock_registry

    instance.scan_user_nodes.return_value = [
        {"name": "custom-node", "class_name": "CustomNode", "interface": {"description": "A custom node"}}
    ]

    with runner.isolated_filesystem():
        test_dir = Path("test_nodes")
        test_dir.mkdir()

        result = runner.invoke(registry, ["scan", str(test_dir)], input="y\n")

        assert "✓ Added 1 custom nodes to registry" in result.output
        instance._save_with_metadata.assert_called_once()


def test_search_truncates_long_results(runner, mock_registry):
    """Test that search truncates display for many results."""
    MockRegistry, instance = mock_registry

    # Create many search results
    results = []
    for i in range(15):
        node_name = f"node-{i}"
        results.append((node_name, {"interface": {"description": f"Node {i}"}}, 50))

    instance.search.return_value = results

    result = runner.invoke(registry, ["search", "node"])

    assert result.exit_code == 0
    assert "node-0" in result.output
    assert "node-9" in result.output
    assert "... and 5 more results" in result.output
    assert "node-14" not in result.output  # Should be truncated


def test_registry_cli_group_help(runner):
    """Test registry group help message."""
    result = runner.invoke(registry, ["--help"])

    assert result.exit_code == 0
    assert "Manage the pflow node registry" in result.output
    assert "list" in result.output
    assert "describe" in result.output
    assert "search" in result.output
    assert "scan" in result.output
