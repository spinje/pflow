"""Tests for MCP workflow save service.

CRITICAL: These tests prevent regression of the workflow_save bug discovered
on 2025-10-18.

Before fix: workflow_save used empty dict for extracted_params, causing
validation to fail for any workflow with inputs (required or optional).

After fix: Generates dummy parameters for template validation, matching
the behavior of workflow_validate.

If these tests fail, someone likely broke the dummy parameter generation
in workflow_save_service.py.

Updated for Task 107: Markdown workflow format. ExecutionService.save_workflow()
now accepts raw .pflow.md content strings instead of IR dicts.
"""

import pytest

from pflow.mcp_server.services.execution_service import ExecutionService
from tests.shared.markdown_utils import ir_to_markdown


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
                    "params": {"prompt": "${message}"},
                }
            ],
            "edges": [],
            "outputs": {"result": {"source": "${test-node.response}", "description": "Test output"}},
        }

        markdown_content = ir_to_markdown(workflow)
        result = ExecutionService.save_workflow(workflow=markdown_content, name="test-required-inputs", force=True)

        assert isinstance(result, str), "Should return string"
        assert "\u2713" in result or "Saved" in result, "Should indicate success"
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
                    "params": {"prompt": "${message}"},
                }
            ],
            "edges": [],
            "outputs": {"result": {"source": "${test-node.response}", "description": "Test output"}},
        }

        markdown_content = ir_to_markdown(workflow)
        result = ExecutionService.save_workflow(workflow=markdown_content, name="test-optional-inputs", force=True)

        assert isinstance(result, str), "Should return string"
        assert "\u2713" in result or "Saved" in result, "Should indicate success"

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
                    "type": "llm",
                    "params": {"prompt": "Post to ${channel}: ${soften.response}"},
                },
            ],
            "edges": [{"from": "soften", "to": "post"}],
            "outputs": {
                "result": {"source": "${soften.response}", "description": "Softened message"},
            },
        }

        markdown_content = ir_to_markdown(workflow)
        result = ExecutionService.save_workflow(workflow=markdown_content, name="test-mixed-inputs", force=True)

        assert isinstance(result, str), "Should return string"
        assert "\u2713" in result or "Saved" in result, "Should indicate success"

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

        markdown_content = ir_to_markdown(workflow)
        result = ExecutionService.save_workflow(workflow=markdown_content, name="test-no-inputs", force=True)

        assert isinstance(result, str), "Should return string"
        assert "\u2713" in result or "Saved" in result, "Should indicate success"


class TestWorkflowSaveValidation:
    """Test that workflow_save still performs proper validation."""

    def test_rejects_invalid_node_type(self):
        """Ensure workflow_save still validates node types."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"message": {"type": "string", "required": True, "description": "Test message"}},
            "nodes": [
                {
                    "id": "test-node",
                    "type": "this-does-not-exist",
                    "params": {"prompt": "${message}"},
                }
            ],
            "edges": [],
            "outputs": {},
        }

        markdown_content = ir_to_markdown(workflow)
        with pytest.raises(ValueError, match=r"Invalid workflow|Unknown node type|this-does-not-exist"):
            ExecutionService.save_workflow(workflow=markdown_content, name="test-invalid-node", force=True)

    def test_rejects_malformed_templates(self):
        """Ensure workflow_save still validates template syntax.

        The malformed template ${malformed (missing closing brace) is in a
        prompt code block. The markdown parser accepts it as content, but
        IR validation catches the malformed template reference.
        """
        # Build markdown directly since ir_to_markdown won't produce malformed templates
        markdown_content = """\
# Test Workflow

Test workflow with malformed template.

## Inputs

### message

Test message input.

- type: string
- required: true

## Steps

### test-node

Test node with malformed template.

- type: llm

```markdown prompt
${malformed
```
"""

        with pytest.raises(ValueError, match=r"Invalid workflow|malformed|template"):
            ExecutionService.save_workflow(workflow=markdown_content, name="test-malformed", force=True)

    def test_rejects_unused_inputs(self):
        """Ensure workflow_save detects unused declared inputs."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "used": {"type": "string", "required": True, "description": "Used input"},
                "unused": {"type": "string", "required": True, "description": "Unused input"},
            },
            "nodes": [
                {
                    "id": "test-node",
                    "type": "llm",
                    "params": {"prompt": "${used}"},
                }
            ],
            "edges": [],
            "outputs": {},
        }

        markdown_content = ir_to_markdown(workflow)
        with pytest.raises(ValueError, match=r"Invalid workflow|unused|Declared input"):
            ExecutionService.save_workflow(workflow=markdown_content, name="test-unused-input", force=True)


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

        markdown_content = ir_to_markdown(workflow)
        with pytest.raises(ValueError, match="Invalid workflow name"):
            ExecutionService.save_workflow(workflow=markdown_content, name="Invalid Name!", force=True)

    def test_rejects_reserved_workflow_name(self):
        """Ensure reserved names are rejected."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {},
            "nodes": [{"id": "test", "type": "llm", "params": {"prompt": "hello"}}],
            "edges": [],
            "outputs": {},
        }

        markdown_content = ir_to_markdown(workflow)
        with pytest.raises(ValueError, match="reserved"):
            ExecutionService.save_workflow(workflow=markdown_content, name="settings", force=True)


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

        markdown_content = ir_to_markdown(workflow)

        # Save first time
        ExecutionService.save_workflow(workflow=markdown_content, name="test-duplicate", force=True)

        # Try to save again without force - should fail
        with pytest.raises(FileExistsError, match="already exists"):
            ExecutionService.save_workflow(workflow=markdown_content, name="test-duplicate", force=False)

    def test_allows_overwrite_with_force(self):
        """Ensure workflows can be overwritten with force=True."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {},
            "nodes": [{"id": "test", "type": "llm", "params": {"prompt": "hello"}}],
            "edges": [],
            "outputs": {},
        }

        markdown_content = ir_to_markdown(workflow)

        result1 = ExecutionService.save_workflow(workflow=markdown_content, name="test-overwrite", force=True)
        assert "\u2713" in result1 or "Saved" in result1

        # Overwrite with force - should succeed
        result2 = ExecutionService.save_workflow(workflow=markdown_content, name="test-overwrite", force=True)
        assert "\u2713" in result2 or "Saved" in result2
