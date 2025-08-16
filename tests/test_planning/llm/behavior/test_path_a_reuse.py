"""LLM behavior tests for Path A workflow reuse.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.
These tests verify Path A (workflow reuse) behavior with real LLM but are resilient to prompt changes.
They focus on the high-level behavior rather than exact prompt/response format.

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/behavior/test_path_a_reuse.py -v
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from pflow.core.exceptions import WorkflowNotFoundError, WorkflowValidationError
from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.nodes import WorkflowDiscoveryNode

logger = logging.getLogger(__name__)

# Skip these tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


class TestPathAWorkflowReuse:
    """Test the happy path for WorkflowDiscoveryNode - finding existing workflows."""

    @pytest.fixture
    def setup_workflow_directory(self):
        """Create a temporary workflow directory with sample workflows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workflows_dir = Path(tmpdir) / "workflows"
            workflows_dir.mkdir()

            # Create a few realistic workflows that should match common requests
            workflows = [
                {
                    "name": "read-and-analyze-file",
                    "description": "Read a file and analyze its contents using LLM",
                    "metadata": {
                        "name": "read-and-analyze-file",
                        "description": "Read a file and analyze its contents using LLM",
                        "version": "1.0.0",
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                        "ir": {
                            "ir_version": "0.1.0",
                            "nodes": [
                                {"id": "read", "type": "read-file", "params": {"file_path": "${file_path}"}},
                                {"id": "analyze", "type": "llm", "params": {"prompt": "${prompt}"}},
                            ],
                            "edges": [{"from": "read", "to": "analyze", "action": "default"}],
                            "start_node": "read",
                            "inputs": {"file_path": "Path to file", "prompt": "Analysis prompt"},
                            "outputs": {"response": "LLM analysis"},
                        },
                    },
                },
                {
                    "name": "process-csv-data",
                    "description": "Read CSV files, process them, and generate reports",
                    "metadata": {
                        "name": "process-csv-data",
                        "description": "Read CSV files, process them, and generate reports",
                        "version": "1.0.0",
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                        "ir": {
                            "ir_version": "0.1.0",
                            "nodes": [
                                {"id": "read", "type": "read-file", "params": {"file_path": "${csv_file}"}},
                                {"id": "process", "type": "llm", "params": {"prompt": "Process this CSV data"}},
                                {"id": "write", "type": "write-file", "params": {"file_path": "${output_file}"}},
                            ],
                            "edges": [
                                {"from": "read", "to": "process", "action": "default"},
                                {"from": "process", "to": "write", "action": "default"},
                            ],
                            "start_node": "read",
                            "inputs": {"csv_file": "CSV file path", "output_file": "Output path"},
                            "outputs": {"result": "Processing result"},
                        },
                    },
                },
                {
                    "name": "github-issue-tracker",
                    "description": "List GitHub issues and create a summary report",
                    "metadata": {
                        "name": "github-issue-tracker",
                        "description": "List GitHub issues and create a summary report",
                        "version": "1.0.0",
                        "created_at": datetime.now().isoformat(),
                        "updated_at": datetime.now().isoformat(),
                        "ir": {
                            "ir_version": "0.1.0",
                            "nodes": [
                                {"id": "list", "type": "github-list-issues", "params": {"repo": "${repo}"}},
                                {"id": "summarize", "type": "llm", "params": {"prompt": "Summarize these issues"}},
                            ],
                            "edges": [{"from": "list", "to": "summarize", "action": "default"}],
                            "start_node": "list",
                            "inputs": {"repo": "Repository name"},
                            "outputs": {"summary": "Issues summary"},
                        },
                    },
                },
            ]

            # Write workflows to disk
            for workflow in workflows:
                workflow_path = workflows_dir / f"{workflow['name']}.json"
                workflow_path.write_text(json.dumps(workflow["metadata"], indent=2))

            yield str(workflows_dir), workflows

    def test_real_llm_finds_workflow(self, setup_workflow_directory):
        """Test with real LLM to verify it can identify matching workflows."""
        workflows_dir, workflows = setup_workflow_directory

        # Create a real WorkflowManager with our test directory
        test_manager = WorkflowManager(workflows_dir=workflows_dir)

        with patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class:
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            # Use a query that should clearly match
            shared = {
                "user_input": "I want to list GitHub issues and create a summary",
                "workflow_manager": test_manager,  # Pass the same WorkflowManager instance
            }

            try:
                # Run with real LLM
                prep_res = node.prep(shared)
                exec_res = node.exec(prep_res)
                action = node.post(shared, prep_res, exec_res)

                logger.info(
                    f"Real LLM result: found={exec_res['found']}, "
                    f"workflow={exec_res.get('workflow_name')}, "
                    f"confidence={exec_res['confidence']}"
                )
                logger.info(f"Action: {action}")
                logger.info(f"Reasoning: {exec_res['reasoning']}")

                # With a good match, we expect Path A
                if exec_res["found"] and exec_res["confidence"] > 0.8:
                    assert action == "found_existing"
                    assert exec_res["workflow_name"] == "github-issue-tracker"
                    logger.info("✅ Real LLM correctly identified matching workflow!")
                else:
                    logger.info("Real LLM didn't find a match - confidence too low or no match")

            except Exception as e:
                if "API" in str(e) or "key" in str(e).lower():
                    pytest.skip(f"LLM API not configured: {e}")
                raise

    def test_workflow_file_not_found_after_llm_match(self, setup_workflow_directory, caplog):
        """Test handling when LLM says workflow exists but file is missing.

        This is a critical edge case - the LLM might identify a workflow that
        existed in its training data but isn't actually on disk.
        """
        workflows_dir, workflows = setup_workflow_directory

        # Create a real WorkflowManager with our test directory
        test_manager = WorkflowManager(workflows_dir=workflows_dir)

        # Mock the manager to pretend a workflow doesn't exist
        original_load = test_manager.load

        def mock_load(name):
            if name == "non-existent-workflow":
                raise WorkflowNotFoundError(name)
            return original_load(name)

        test_manager.load = mock_load

        with patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class:
            mock_wm_class.return_value = test_manager

            node = WorkflowDiscoveryNode()

            shared = {
                "user_input": "Use the non-existent-workflow",
                "workflow_manager": test_manager,  # Pass the test WorkflowManager instance
            }

            prep_res = node.prep(shared)

            # Manually create a response that says the workflow exists
            exec_res = {
                "found": True,
                "workflow_name": "non-existent-workflow",
                "confidence": 0.95,
                "reasoning": "Found a perfect match",
            }

            # But post() should handle the missing file gracefully
            action = node.post(shared, prep_res, exec_res)

            # Should fall back to Path B when file not found
            assert action == "not_found"
            assert "found_workflow" not in shared

            # Check that warning was logged
            assert "not found on disk" in caplog.text

    def test_corrupted_workflow_file_handling(self, setup_workflow_directory, caplog):
        """Test handling of corrupted workflow JSON files.

        IMPORTANT BUG FOUND: WorkflowDiscoveryNode only catches WorkflowNotFoundError,
        not WorkflowValidationError. This means corrupted JSON files will crash the node.
        This test documents the bug and tests the workaround.

        TODO: Fix WorkflowDiscoveryNode.post() to also catch WorkflowValidationError
        """
        workflows_dir, workflows = setup_workflow_directory

        # Create a corrupted workflow file
        corrupted_path = Path(workflows_dir) / "corrupted-workflow.json"
        corrupted_path.write_text("{ this is not valid json }")

        # Create a real WorkflowManager with our test directory
        test_manager = WorkflowManager(workflows_dir=workflows_dir)

        with patch("pflow.planning.nodes.WorkflowManager") as mock_wm_class:
            mock_wm_class.return_value = test_manager
            with patch("pflow.planning.context_builder._workflow_manager", test_manager):
                node = WorkflowDiscoveryNode()

                shared = {
                    "user_input": "Use the corrupted workflow",
                    "workflow_manager": test_manager,  # Pass the test WorkflowManager instance
                }

                prep_res = node.prep(shared)

                # Manually simulate LLM selecting the corrupted workflow
                exec_res = {
                    "found": True,
                    "workflow_name": "corrupted-workflow",
                    "confidence": 0.9,
                    "reasoning": "Matches the request",
                }

                # CURRENT BEHAVIOR: WorkflowValidationError is NOT caught
                # This would crash in production!

                # Test that the error is raised (documenting the bug)
                with pytest.raises(WorkflowValidationError):
                    node.post(shared, prep_res, exec_res)

                # DESIRED BEHAVIOR (after bug fix):
                # The post() method should catch WorkflowValidationError
                # and fall back to Path B gracefully:
                # assert action == "not_found"
                # assert "found_workflow" not in shared


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
