"""Integration tests for two-phase context builder system.

These tests verify the complete discovery → planning workflow that users will experience,
including the structure display functionality that enables proxy mapping generation.
"""

import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from pflow.planning.context_builder import (
    build_discovery_context,
    build_planning_context,
)
from pflow.registry import Registry


class TestDiscoveryPlanningFlow:
    """Test the complete discovery → planning workflow."""

    def test_full_discovery_to_planning_flow(self):
        """Test complete two-phase workflow with real registry."""
        # Load real registry
        registry = Registry()
        metadata = registry.load()

        # Discovery phase - should include all available nodes
        discovery = build_discovery_context(registry_metadata=metadata)

        # Verify discovery content structure
        assert "## Available Nodes" in discovery
        assert "### File Operations" in discovery  # Category should be present

        # Should include basic file nodes that exist
        file_nodes = ["read-file", "write-file", "copy-file", "move-file", "delete-file"]
        available_nodes = [node for node in file_nodes if node in discovery]
        assert len(available_nodes) >= 2, f"Expected at least 2 file nodes, found: {available_nodes}"

        # Simulate LLM selection from discovery
        selected_nodes = available_nodes[:2]  # Take first 2 available nodes

        # Planning phase - should show detailed interfaces
        planning = build_planning_context(selected_nodes, [], metadata)

        # Verify planning content structure
        assert "## Selected Components" in planning
        assert "**Inputs**:" in planning
        assert "**Outputs**:" in planning

        # Should contain node details for selected nodes
        for node in selected_nodes:
            assert node in planning

    def test_discovery_planning_with_workflows(self):
        """Test workflow integration in both phases."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test workflow file
            workflow_file = Path(tmpdir) / "test-workflow.json"
            workflow_data = {
                "name": "test-integration-workflow",
                "description": "Test workflow for integration testing",
                "ir": {"nodes": [], "flows": []},
                "created_at": "2024-01-01T00:00:00Z",
            }
            workflow_file.write_text(json.dumps(workflow_data))

            # Mock the workflow loading to use our test directory
            with patch("pflow.planning.context_builder.Path.home") as mock_home:
                mock_home.return_value = Path(tmpdir).parent
                with patch("pflow.planning.context_builder._load_saved_workflows") as mock_load:
                    mock_load.return_value = [workflow_data]

                    # Discovery should include workflow
                    discovery = build_discovery_context()
                    assert "## Available Workflows" in discovery
                    assert "test-integration-workflow" in discovery

                    # Planning should show workflow details
                    planning = build_planning_context([], ["test-integration-workflow"], {})
                    assert "## Selected Workflows" in planning
                    assert "test-integration-workflow" in planning
                    assert "Test workflow for integration testing" in planning

    def test_error_recovery_flow(self):
        """Test error handling and recovery in planning phase."""
        # Create minimal registry with one real node
        registry_metadata = {"real-node": {"module": "test", "class_name": "Test"}}

        # Try planning with mix of real and fake nodes
        result = build_planning_context(
            ["real-node", "fake-node", "another-fake"], ["non-existent-workflow"], registry_metadata
        )

        # Should return error dict
        assert isinstance(result, dict)
        assert "error" in result
        assert "missing_nodes" in result
        assert "missing_workflows" in result

        # Check missing components
        assert "fake-node" in result["missing_nodes"]
        assert "another-fake" in result["missing_nodes"]
        assert "non-existent-workflow" in result["missing_workflows"]

        # Error message should help user
        assert "Missing components detected" in result["error"]
        assert "Unknown nodes" in result["error"]
        assert "Unknown workflows" in result["error"]

    def test_discovery_with_large_registry(self):
        """Test discovery performance with many nodes."""
        # Create registry with many mock nodes
        large_registry = {}
        for i in range(100):
            large_registry[f"test-node-{i:03d}"] = {
                "module": "test.module",
                "class_name": "TestNode",
                "metadata": {"description": f"Test node {i} for performance testing"},
            }

        # Discovery should complete quickly
        start_time = time.time()

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            # Mock the processed nodes with descriptions
            processed_nodes = {}
            for i in range(100):
                processed_nodes[f"test-node-{i:03d}"] = {
                    "description": f"Test node {i} for performance testing",
                    "inputs": [],
                    "outputs": [],
                    "params": [],
                    "actions": [],
                }
            mock_process.return_value = (processed_nodes, 0)

            discovery = build_discovery_context(registry_metadata=large_registry)

        discovery_time = time.time() - start_time

        # Should complete in reasonable time
        assert discovery_time < 2.0, f"Discovery took {discovery_time:.2f}s, should be < 2.0s"

        # Should include all nodes
        assert "test-node-050" in discovery
        assert "test-node-099" in discovery
        assert "## Available Nodes" in discovery


class TestStructureIntegration:
    """Test structure display in planning context."""

    def test_planning_with_structured_nodes(self):
        """Test planning context includes structure display."""
        # Create mock registry with structured node
        registry_metadata = {"struct-node": {"module": "test", "class_name": "StructNode"}}

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (
                {
                    "struct-node": {
                        "description": "Node with complex structure",
                        "inputs": [{"key": "user_id", "type": "str", "description": "User ID"}],
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
                                            "email": {"type": "str", "description": "Email address"},
                                        },
                                    },
                                    "tags": {
                                        "type": "list",
                                        "description": "User tags",
                                        "structure": {
                                            "name": {"type": "str", "description": "Tag name"},
                                            "color": {"type": "str", "description": "Tag color"},
                                        },
                                    },
                                },
                            }
                        ],
                        "params": [],
                        "actions": ["default"],
                    }
                },
                0,
            )

            planning = build_planning_context(["struct-node"], [], registry_metadata)

        # Verify combined format appears (Decision 9 requirement)
        assert "Structure (JSON format):" in planning
        assert "Available paths:" in planning

        # Verify JSON format section
        assert "```json" in planning
        assert '"user_data": {' in planning
        assert '"id": "str"' in planning
        assert '"profile": {' in planning

        # Verify paths section with dot notation
        assert "user_data.id (str)" in planning
        assert "user_data.profile.name (str)" in planning
        assert "user_data.profile.email (str)" in planning
        assert "user_data.tags[].name (str)" in planning
        assert "user_data.tags[].color (str)" in planning

    def test_structure_format_correctness(self):
        """Verify structure format matches Decision 9 requirements."""
        registry_metadata = {"test-node": {"module": "test", "class_name": "Test"}}

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            # Complex nested structure to test all format features
            mock_process.return_value = (
                {
                    "test-node": {
                        "description": "Test node with complex nested structure",
                        "inputs": [],
                        "outputs": [
                            {
                                "key": "github_issue",
                                "type": "dict",
                                "description": "GitHub issue data",
                                "structure": {
                                    "number": {"type": "int", "description": "Issue number"},
                                    "title": {"type": "str", "description": "Issue title"},
                                    "user": {
                                        "type": "dict",
                                        "description": "Issue author",
                                        "structure": {
                                            "login": {"type": "str", "description": "GitHub username"},
                                            "id": {"type": "int", "description": "User ID"},
                                        },
                                    },
                                    "labels": {
                                        "type": "list",
                                        "description": "Issue labels",
                                        "structure": {
                                            "name": {"type": "str", "description": "Label name"},
                                            "color": {"type": "str", "description": "Label color"},
                                        },
                                    },
                                },
                            }
                        ],
                        "params": [],
                        "actions": ["default"],
                    }
                },
                0,
            )

            planning = build_planning_context(["test-node"], [], registry_metadata)

        # Extract the structure section
        lines = planning.split("\n")
        json_start = -1
        json_end = -1
        paths_start = -1

        for i, line in enumerate(lines):
            if "Structure (JSON format):" in line:
                json_start = i + 2  # Skip header and ```json lines
            elif json_start != -1 and line.strip() == "```":
                json_end = i
            elif "Available paths:" in line:
                paths_start = i + 1
                break

        # Verify we found both sections
        assert json_start != -1, "JSON format section not found"
        assert json_end != -1, "JSON format end not found"
        assert paths_start != -1, "Available paths section not found"

        # Extract and verify JSON format
        json_lines = lines[json_start:json_end]
        json_content = "\n".join(json_lines)

        # Should be valid JSON with just types
        parsed_json = json.loads(json_content)
        assert "github_issue" in parsed_json
        assert parsed_json["github_issue"]["number"] == "int"
        assert parsed_json["github_issue"]["user"]["login"] == "str"
        assert isinstance(parsed_json["github_issue"]["labels"], list)

        # Extract and verify paths
        path_lines = []
        for i in range(paths_start, len(lines)):
            if lines[i].startswith("- github_issue."):
                path_lines.append(lines[i])
            elif lines[i].strip() == "" or lines[i].startswith("#"):
                break

        # Should have all expected paths
        expected_paths = [
            "github_issue.number (int)",
            "github_issue.title (str)",
            "github_issue.user.login (str)",
            "github_issue.user.id (int)",
            "github_issue.labels[].name (str)",
            "github_issue.labels[].color (str)",
        ]

        path_text = "\n".join(path_lines)
        for expected_path in expected_paths:
            assert expected_path in path_text, f"Missing path: {expected_path}"


class TestRealWorldScenarios:
    """Test with realistic node combinations."""

    def test_file_operation_workflow(self):
        """Test discovery and planning for file operations."""
        # Load real registry for file operations
        registry = Registry()
        metadata = registry.load()

        # Discovery phase
        discovery = build_discovery_context(registry_metadata=metadata)

        # Should show file operations category
        assert "File Operations" in discovery

        # Find available file operation nodes
        available_file_nodes = []
        for node in ["read-file", "write-file", "copy-file"]:
            if node in discovery:
                available_file_nodes.append(node)

        if len(available_file_nodes) >= 2:
            # Planning phase with file nodes
            planning = build_planning_context(available_file_nodes[:2], [], metadata)

            # Should show file-specific interface details
            assert "file_path" in planning  # Common to most file operations
            assert "**Inputs**:" in planning
            assert "**Outputs**:" in planning

            # File nodes shouldn't have complex structures
            assert "Structure (JSON format):" not in planning  # File nodes have simple outputs

    def test_mixed_node_types(self):
        """Test with different node categories."""
        # Create mock registry with different categories
        registry_metadata = {
            "file-reader": {"module": "test.file", "class_name": "FileReader"},
            "data-processor": {"module": "test.data", "class_name": "DataProcessor"},
            "api-caller": {"module": "test.api", "class_name": "ApiCaller"},
        }

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            # Mock different node types
            mock_process.return_value = (
                {
                    "file-reader": {
                        "description": "Reads data from files",
                        "category": "File Operations",
                        "inputs": [{"key": "file_path", "type": "str", "description": "File path"}],
                        "outputs": [{"key": "content", "type": "str", "description": "File content"}],
                        "params": [],
                        "actions": ["default", "error"],
                    },
                    "data-processor": {
                        "description": "Processes and transforms data",
                        "category": "Data Processing",
                        "inputs": [{"key": "raw_data", "type": "str", "description": "Raw input data"}],
                        "outputs": [{"key": "processed_data", "type": "dict", "description": "Processed result"}],
                        "params": [{"key": "format", "type": "str", "description": "Output format"}],
                        "actions": ["default"],
                    },
                    "api-caller": {
                        "description": "Makes HTTP API calls",
                        "category": "Network Operations",
                        "inputs": [{"key": "url", "type": "str", "description": "API endpoint"}],
                        "outputs": [{"key": "response", "type": "dict", "description": "API response"}],
                        "params": [{"key": "timeout", "type": "int", "description": "Request timeout"}],
                        "actions": ["default", "error", "retry"],
                    },
                },
                0,
            )

            # Discovery should group by categories
            discovery = build_discovery_context(registry_metadata=registry_metadata)

            # Should contain category headers
            assert "File Operations" in discovery or "Data Processing" in discovery or "Network Operations" in discovery

            # Should show all nodes
            assert "file-reader" in discovery
            assert "data-processor" in discovery
            assert "api-caller" in discovery

            # Planning with mixed selection
            planning = build_planning_context(["file-reader", "api-caller"], [], registry_metadata)

            # Should show details for both selected nodes
            assert "file-reader" in planning
            assert "api-caller" in planning
            assert "Reads data from files" in planning
            assert "Makes HTTP API calls" in planning

            # Should show different parameter types
            assert "timeout" in planning  # From api-caller
            assert "file_path" in planning  # From file-reader


class TestErrorAndEdgeCases:
    """Test error conditions and edge cases."""

    def test_empty_registry_handling(self):
        """Test behavior with empty registry."""
        discovery = build_discovery_context(registry_metadata={})

        # Should handle empty registry gracefully
        assert "## Available Nodes" in discovery
        # Should not show category headers for empty registry
        assert "###" not in discovery

    def test_malformed_registry_handling(self):
        """Test error handling with malformed registry data."""
        # Registry with missing required fields
        bad_registry = {
            "broken-node": {"module": "missing"},  # Missing class_name
            "empty-node": {},  # Completely empty
        }

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            # Simulate processing that skips broken nodes
            mock_process.return_value = ({}, 2)  # Empty processed, 2 skipped

            discovery = build_discovery_context(registry_metadata=bad_registry)

            # Should handle gracefully
            assert "## Available Nodes" in discovery
            # Should not crash

    def test_concurrent_context_building(self):
        """Test that context building functions can run concurrently."""
        # Test basic concurrent access to context building functions
        registry_metadata = {"test-node": {"module": "test", "class_name": "Test"}}

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (
                {"test-node": {"description": "Test node", "inputs": [], "outputs": [], "params": [], "actions": []}},
                0,
            )

            results = []
            errors = []

            def build_context():
                try:
                    # Test discovery context building
                    discovery = build_discovery_context(registry_metadata=registry_metadata)
                    results.append(len(discovery) > 0)  # Should have content
                except Exception as e:
                    errors.append(str(e))

            # Run multiple threads
            threads = [threading.Thread(target=build_context) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All threads should complete successfully
            assert len(errors) == 0, f"Errors in concurrent execution: {errors}"
            assert len(results) == 3
            assert all(results), "All threads should successfully build context"

    def test_unicode_in_descriptions(self):
        """Test handling of Unicode characters."""
        registry_metadata = {"unicode-node": {"module": "test.module", "class_name": "TestNode"}}

        with patch("pflow.planning.context_builder._process_nodes") as mock_process:
            mock_process.return_value = (
                {
                    "unicode-node": {
                        "description": "Node with émojis 🚀 and 中文 characters",
                        "inputs": [{"key": "input", "type": "str", "description": "Input with café and naïve"}],
                        "outputs": [{"key": "output", "type": "str", "description": "Output with ñ and ü"}],
                        "params": [],
                        "actions": ["default"],
                    }
                },
                0,
            )

            discovery = build_discovery_context(registry_metadata=registry_metadata)
            planning = build_planning_context(["unicode-node"], [], registry_metadata)

            # Should handle Unicode gracefully
            assert "émojis 🚀" in discovery
            assert "中文" in discovery
            assert "café and naïve" in planning
            assert "ñ and ü" in planning
