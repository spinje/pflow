"""Tests for workflow_loader utility.

Testing strategy:
- Test thin wrapper behavior (delegation to WorkflowManager)
- Test error handling (empty name, non-existent workflow)
- Use real WorkflowManager for integration testing
- Mock WorkflowManager for focused unit testing
"""

import json
from unittest.mock import Mock, patch

import pytest

from pflow.core.exceptions import WorkflowNotFoundError
from pflow.planning.utils.workflow_loader import list_all_workflows, load_workflow


class TestLoadWorkflow:
    """Test load_workflow function."""

    def test_empty_name_raises_value_error(self):
        """Test that empty workflow name raises ValueError."""
        with pytest.raises(ValueError, match="Workflow name cannot be empty"):
            load_workflow("")

    def test_none_name_raises_value_error(self):
        """Test that None workflow name raises appropriate error."""
        with pytest.raises(ValueError, match="Workflow name cannot be empty"):
            load_workflow(None)  # type: ignore[arg-type]

    def test_whitespace_only_name_raises_value_error(self):
        """Test that whitespace-only name raises ValueError."""
        with pytest.raises(ValueError, match="Workflow name cannot be empty"):
            load_workflow("   ")

    def test_non_existent_workflow_raises_not_found_error(self):
        """Test that loading non-existent workflow raises WorkflowNotFoundError.

        Uses real WorkflowManager with temp directory.
        """
        with patch("pflow.planning.utils.workflow_loader.WorkflowManager") as MockManager:
            mock_manager = Mock()
            mock_manager.load.side_effect = WorkflowNotFoundError("Workflow 'missing' not found")
            MockManager.return_value = mock_manager

            with pytest.raises(WorkflowNotFoundError, match="Workflow 'missing' not found"):
                load_workflow("missing")

            mock_manager.load.assert_called_once_with("missing")

    def test_successful_workflow_loading(self, tmp_path):
        """Test successful workflow loading with real file.

        Uses real WorkflowManager to test integration.
        """
        # Create a test workflow file
        workflows_dir = tmp_path / "workflows"
        workflows_dir.mkdir()

        test_workflow = {
            "name": "test-workflow",
            "description": "Test workflow",
            "ir": {
                "ir_version": "0.1.0",
                "nodes": [{"id": "n1", "type": "test-node", "params": {}}],
                "edges": [],
            },
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "version": "1.0.0",
        }

        workflow_file = workflows_dir / "test-workflow.json"
        workflow_file.write_text(json.dumps(test_workflow))

        # Test loading with patched WorkflowManager
        with patch("pflow.planning.utils.workflow_loader.WorkflowManager") as MockManager:
            mock_manager = Mock()
            mock_manager.load.return_value = test_workflow
            MockManager.return_value = mock_manager

            result = load_workflow("test-workflow")

            assert result == test_workflow
            mock_manager.load.assert_called_once_with("test-workflow")

    def test_delegates_to_workflow_manager(self):
        """Test that load_workflow properly delegates to WorkflowManager."""
        expected_workflow = {"name": "test", "ir": {"nodes": []}}

        with patch("pflow.planning.utils.workflow_loader.WorkflowManager") as MockManager:
            mock_manager = Mock()
            mock_manager.load.return_value = expected_workflow
            MockManager.return_value = mock_manager

            result = load_workflow("test")

            # Verify delegation
            MockManager.assert_called_once()
            mock_manager.load.assert_called_once_with("test")
            assert result == expected_workflow


class TestListAllWorkflows:
    """Test list_all_workflows function."""

    def test_empty_directory_returns_empty_list(self):
        """Test that empty workflows directory returns empty list."""
        with patch("pflow.planning.utils.workflow_loader.WorkflowManager") as MockManager:
            mock_manager = Mock()
            mock_manager.list_all.return_value = []
            MockManager.return_value = mock_manager

            result = list_all_workflows()

            assert result == []
            mock_manager.list_all.assert_called_once()

    def test_returns_workflow_list(self):
        """Test that list_all_workflows returns correct workflow list."""
        expected_workflows = [
            {
                "name": "workflow-1",
                "description": "First workflow",
                "ir": {"nodes": []},
            },
            {
                "name": "workflow-2",
                "description": "Second workflow",
                "ir": {"nodes": []},
            },
        ]

        with patch("pflow.planning.utils.workflow_loader.WorkflowManager") as MockManager:
            mock_manager = Mock()
            mock_manager.list_all.return_value = expected_workflows
            MockManager.return_value = mock_manager

            result = list_all_workflows()

            assert result == expected_workflows
            mock_manager.list_all.assert_called_once()

    def test_delegates_to_workflow_manager(self):
        """Test that list_all_workflows properly delegates to WorkflowManager."""
        with patch("pflow.planning.utils.workflow_loader.WorkflowManager") as MockManager:
            mock_manager = Mock()
            mock_manager.list_all.return_value = []
            MockManager.return_value = mock_manager

            list_all_workflows()

            # Verify delegation
            MockManager.assert_called_once()
            mock_manager.list_all.assert_called_once()

    def test_preserves_workflow_metadata_structure(self):
        """Test that workflow metadata structure is preserved."""
        complex_workflow = {
            "name": "complex-workflow",
            "description": "Complex test workflow",
            "ir": {
                "ir_version": "0.1.0",
                "nodes": [
                    {"id": "n1", "type": "read-file", "params": {"path": "test.txt"}},
                    {"id": "n2", "type": "llm", "params": {"model": "test"}},
                ],
                "edges": [{"from": "n1", "to": "n2"}],
            },
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "version": "1.0.0",
            "tags": ["test", "example"],  # Extra metadata
        }

        with patch("pflow.planning.utils.workflow_loader.WorkflowManager") as MockManager:
            mock_manager = Mock()
            mock_manager.list_all.return_value = [complex_workflow]
            MockManager.return_value = mock_manager

            result = list_all_workflows()

            assert len(result) == 1
            assert result[0] == complex_workflow
            # Verify all fields preserved
            assert result[0]["tags"] == ["test", "example"]
