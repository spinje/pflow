"""Tests for MCP workflow save service.

CRITICAL: These tests prevent regression of the workflow_save bug discovered
on 2025-10-18.

Before fix: workflow_save used empty dict for extracted_params, causing
validation to fail for any workflow with inputs (required or optional).

After fix: Generates dummy parameters for template validation, matching
the behavior of workflow_validate.

If these tests fail, someone likely broke the dummy parameter generation
in workflow_save_service.py.
"""

import pytest

from pflow.mcp_server.services.execution_service import ExecutionService


class TestWorkflowSaveWithInputs:
    """Regression tests for workflow_save input handling bug.

    Bug discovered 2025-10-18: workflow_save passed extracted_params={}
    to WorkflowValidator, causing it to reject workflows with inputs.

    These tests verify workflows with inputs can be saved.
    """

    def test_save_workflow_with_required_inputs(self):
        """CRITICAL: Regression test for required input bug.

        Before fix: Failed with "Required input '${message}' not provided"
        After fix: Saves successfully

        This test would FAIL if dummy parameter generation is removed.
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "message": {
                    "type": "string",
                    "required": True,
                    "description": "Test message",
                }
            },
            "nodes": [
                {
                    "id": "test-node",
                    "type": "llm",
                    "params": {"prompt": "${message}"},  # Uses required input
                }
            ],
            "edges": [],
            "outputs": {"result": {"source": "${test-node.response}", "description": "Test output"}},
        }

        # Should not raise - workflow is structurally valid even without runtime values
        result = ExecutionService.save_workflow(
            workflow=workflow, name="test-required-inputs", description="Test workflow", force=True
        )

        assert isinstance(result, str), "Should return string"
        assert "✓" in result or "Saved" in result, "Should indicate success"
        assert "test-required-inputs" in result, "Should mention workflow name"

    def test_save_workflow_with_optional_inputs(self):
        """CRITICAL: Regression test for optional input bug.

        Before fix: Failed with contradictory error message:
        "Required input '${channel}' not provided - (optional, default: ...)"

        After fix: Saves successfully

        This test would FAIL if dummy parameter generation is removed.
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "message": {
                    "type": "string",
                    "required": False,
                    "default": "hello",
                    "description": "Optional message",
                }
            },
            "nodes": [
                {
                    "id": "test-node",
                    "type": "llm",
                    "params": {"prompt": "${message}"},  # Uses optional input
                }
            ],
            "edges": [],
            "outputs": {"result": {"source": "${test-node.response}", "description": "Test output"}},
        }

        result = ExecutionService.save_workflow(
            workflow=workflow, name="test-optional-inputs", description="Test workflow", force=True
        )

        assert isinstance(result, str), "Should return string"
        assert "✓" in result or "Saved" in result, "Should indicate success"

    def test_save_workflow_with_mixed_inputs(self):
        """Test saving workflow with both required and optional inputs.

        This was the original bug report scenario (message-softener workflow).
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "message": {
                    "type": "string",
                    "required": True,
                    "description": "Required message",
                },
                "channel": {
                    "type": "string",
                    "required": False,
                    "default": "C09C16NAU5B",
                    "description": "Optional channel",
                },
            },
            "nodes": [
                {
                    "id": "soften",
                    "type": "llm",
                    "params": {"prompt": "Soften: ${message}"},
                },
                {
                    "id": "post",
                    "type": "llm",  # Using llm instead of MCP node for test
                    "params": {"prompt": "Post to ${channel}: ${soften.response}"},
                },
            ],
            "edges": [{"from": "soften", "to": "post"}],
            "outputs": {
                "result": {"source": "${soften.response}", "description": "Softened message"},
            },
        }

        result = ExecutionService.save_workflow(
            workflow=workflow, name="test-mixed-inputs", description="Test workflow", force=True
        )

        assert isinstance(result, str), "Should return string"
        assert "✓" in result or "Saved" in result, "Should indicate success"

    def test_save_workflow_with_no_inputs(self):
        """Sanity check: Workflows without inputs should still work.

        This always worked, but verify it still does after the fix.
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {},
            "nodes": [
                {
                    "id": "test-node",
                    "type": "llm",
                    "params": {"prompt": "Say hello"},
                }
            ],
            "edges": [],
            "outputs": {"result": {"source": "${test-node.response}", "description": "Test output"}},
        }

        result = ExecutionService.save_workflow(
            workflow=workflow, name="test-no-inputs", description="Test workflow", force=True
        )

        assert isinstance(result, str), "Should return string"
        assert "✓" in result or "Saved" in result, "Should indicate success"


class TestWorkflowSaveValidation:
    """Test that workflow_save still performs proper validation."""

    def test_rejects_invalid_node_type(self):
        """Ensure workflow_save still validates node types."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"message": {"type": "string", "required": True}},
            "nodes": [
                {
                    "id": "test-node",
                    "type": "this-does-not-exist",  # ❌ Invalid
                    "params": {"prompt": "${message}"},
                }
            ],
            "edges": [],
            "outputs": {},
        }

        with pytest.raises(ValueError, match="Invalid workflow|Unknown node type|this-does-not-exist"):
            ExecutionService.save_workflow(
                workflow=workflow, name="test-invalid-node", description="Test workflow", force=True
            )

    def test_rejects_malformed_templates(self):
        """Ensure workflow_save still validates template syntax."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"message": {"type": "string", "required": True}},
            "nodes": [
                {
                    "id": "test-node",
                    "type": "llm",
                    "params": {"prompt": "${malformed"},  # ❌ Missing closing brace
                }
            ],
            "edges": [],
            "outputs": {},
        }

        with pytest.raises(ValueError, match="Invalid workflow|malformed|template"):
            ExecutionService.save_workflow(
                workflow=workflow, name="test-malformed", description="Test workflow", force=True
            )

    def test_rejects_unused_inputs(self):
        """Ensure workflow_save detects unused declared inputs."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "used": {"type": "string", "required": True},
                "unused": {"type": "string", "required": True},  # ⚠️ Declared but never used
            },
            "nodes": [
                {
                    "id": "test-node",
                    "type": "llm",
                    "params": {"prompt": "${used}"},  # Only uses 'used', not 'unused'
                }
            ],
            "edges": [],
            "outputs": {},
        }

        with pytest.raises(ValueError, match="Invalid workflow|unused|Declared input"):
            ExecutionService.save_workflow(
                workflow=workflow, name="test-unused-input", description="Test workflow", force=True
            )


class TestWorkflowSaveNameValidation:
    """Test workflow name validation during save."""

    def test_rejects_invalid_workflow_name(self):
        """Ensure workflow names are validated."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {},
            "nodes": [{"id": "test", "type": "llm", "params": {"prompt": "hello"}}],
            "edges": [],
            "outputs": {},
        }

        # Invalid characters in name
        with pytest.raises(ValueError, match="Invalid workflow name"):
            ExecutionService.save_workflow(workflow=workflow, name="Invalid Name!", description="Test", force=True)

    def test_rejects_reserved_workflow_name(self):
        """Ensure reserved names are rejected."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {},
            "nodes": [{"id": "test", "type": "llm", "params": {"prompt": "hello"}}],
            "edges": [],
            "outputs": {},
        }

        # Reserved name
        with pytest.raises(ValueError, match="reserved"):
            ExecutionService.save_workflow(workflow=workflow, name="settings", description="Test", force=True)


class TestWorkflowSaveOverwrite:
    """Test workflow overwrite behavior."""

    def test_rejects_duplicate_without_force(self):
        """Ensure workflows cannot be overwritten without force=True."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {},
            "nodes": [{"id": "test", "type": "llm", "params": {"prompt": "hello"}}],
            "edges": [],
            "outputs": {},
        }

        # Save first time (use copy to avoid in-place metadata modification)
        import copy

        ExecutionService.save_workflow(
            workflow=copy.deepcopy(workflow), name="test-duplicate", description="Test workflow", force=True
        )

        # Try to save again without force - should fail
        with pytest.raises(FileExistsError, match="already exists"):
            ExecutionService.save_workflow(
                workflow=copy.deepcopy(workflow), name="test-duplicate", description="Test workflow", force=False
            )

    def test_allows_overwrite_with_force(self):
        """Ensure workflows can be overwritten with force=True."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {},
            "nodes": [{"id": "test", "type": "llm", "params": {"prompt": "hello"}}],
            "edges": [],
            "outputs": {},
        }

        # Save first time (use copy to avoid in-place metadata modification)
        import copy

        result1 = ExecutionService.save_workflow(
            workflow=copy.deepcopy(workflow), name="test-overwrite", description="Test workflow", force=True
        )
        assert "✓" in result1 or "Saved" in result1

        # Overwrite with force - should succeed
        result2 = ExecutionService.save_workflow(
            workflow=copy.deepcopy(workflow), name="test-overwrite", description="Test workflow", force=True
        )
        assert "✓" in result2 or "Saved" in result2
