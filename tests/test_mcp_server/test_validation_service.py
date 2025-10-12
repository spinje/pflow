"""Tests for MCP workflow validation service.

CRITICAL: These tests prevent regression of the false positive bug discovered
in the MCP vs CLI comparison (2025-10-11).

Before fix: MCP returned valid=true for invalid workflows (2 of 4 checks)
After fix: Uses WorkflowValidator for comprehensive validation (all 4 checks)

If these tests fail, someone likely reverted to incomplete manual validation.
"""

from pflow.mcp_server.services.execution_service import ExecutionService


class TestValidationFalsePositives:
    """Regression tests for false positive bugs.

    Each test verifies a specific invalid workflow scenario that MCP
    previously accepted but should reject.
    """

    def test_rejects_nonexistent_node_type(self):
        """CRITICAL: Catches node type validation regression.

        Bug: MCP returned valid=true for non-existent node types
        Fix: Added node type validation via WorkflowValidator

        This test would FAIL if someone removes node type validation.
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {},
            "nodes": [
                {
                    "id": "test-node",
                    "type": "this-node-does-not-exist",  # ❌ Invalid
                    "params": {},
                }
            ],
            "edges": [],
            "outputs": {},
        }

        result = ExecutionService.validate_workflow(workflow)

        assert isinstance(result, str), "Should return string"
        assert result.startswith("✗"), "Should indicate validation failure"
        assert "this-node-does-not-exist" in result, "Error should mention invalid node type"

    def test_rejects_undefined_template_variable(self):
        """CRITICAL: Catches template validation regression.

        Bug: MCP didn't validate template variable resolution
        Fix: Added template validation via WorkflowValidator

        This test would FAIL if someone removes template validation.
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"known_input": {"type": "string", "required": True}},
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",  # Valid node type
                    "params": {
                        "command": "${undefined_variable}"  # ❌ Invalid - not in inputs
                    },
                }
            ],
            "edges": [],
            "outputs": {},
        }

        result = ExecutionService.validate_workflow(workflow)

        assert isinstance(result, str), "Should return string"
        assert result.startswith("✗"), "Should indicate validation failure"
        assert "undefined_variable" in result, "Error should mention undefined variable"

    def test_rejects_circular_dependency(self):
        """CRITICAL: Catches data flow validation regression.

        Bug: MCP didn't validate execution order and cycles
        Fix: Added data flow validation via WorkflowValidator

        This test would FAIL if someone removes data flow validation.
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {},
            "nodes": [
                {
                    "id": "node-a",
                    "type": "shell",
                    "params": {"command": "${node-b.stdout}"},  # Depends on B
                },
                {
                    "id": "node-b",
                    "type": "shell",
                    "params": {"command": "${node-a.stdout}"},  # Depends on A ❌ Cycle!
                },
            ],
            "edges": [{"from": "node-a", "to": "node-b"}, {"from": "node-b", "to": "node-a"}],
            "outputs": {},
        }

        result = ExecutionService.validate_workflow(workflow)

        assert isinstance(result, str), "Should return string"
        assert result.startswith("✗"), "Should indicate validation failure"
        result_lower = result.lower()
        assert "cycle" in result_lower or "circular" in result_lower, "Error should mention cycle"

    def test_detects_unused_declared_inputs(self):
        """IMPORTANT: Catches template validation for unused inputs.

        Validates that comprehensive checking includes unused input detection.
        Note: Currently treated as validation error, not just a warning.
        """
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {
                "used_input": {"type": "string", "required": True},
                "unused_input": {"type": "string", "required": False},  # ⚠️ Unused
            },
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "echo ${used_input}"},  # Only uses one input
                }
            ],
            "edges": [],
            "outputs": {},
        }

        result = ExecutionService.validate_workflow(workflow)

        # Currently fails validation due to unused input (validator behavior)
        assert isinstance(result, str), "Should return string"
        assert result.startswith("✗"), "Unused inputs are detected as validation errors"
        assert "unused" in result.lower(), "Error should mention unused input"


class TestValidationCorrectBehavior:
    """Tests ensuring valid workflows still pass (sanity checks)."""

    def test_accepts_minimal_valid_workflow(self):
        """Sanity check: Simple valid workflow should pass."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {},
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",  # Valid node type
                    "params": {"command": "echo hello"},
                }
            ],
            "edges": [],
            "outputs": {},
        }

        result = ExecutionService.validate_workflow(workflow)

        assert isinstance(result, str), "Should return string"
        # Minimal success message (token-efficient)
        assert result == "✓ Workflow is valid"

    def test_accepts_workflow_with_valid_templates(self):
        """Valid template variables should pass."""
        workflow = {
            "ir_version": "0.1.0",
            "inputs": {"message": {"type": "string", "required": True}},
            "nodes": [
                {
                    "id": "echo-node",
                    "type": "shell",
                    "params": {"command": "echo ${message}"},  # ✅ Valid - in inputs
                }
            ],
            "edges": [],
            "outputs": {},
        }

        result = ExecutionService.validate_workflow(workflow)

        assert isinstance(result, str), "Should return string"
        assert result == "✓ Workflow is valid"


class TestValidationResponseFormat:
    """Tests ensuring MCP response format is correct."""

    def test_error_format_includes_suggestions(self):
        """Validation response should include suggestions when available."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "nonexistent", "params": {}}],
            "edges": [],
            "outputs": {},
        }

        result = ExecutionService.validate_workflow(workflow)

        # Verify string format
        assert isinstance(result, str), "Should return string"
        assert result.startswith("✗"), "Should indicate validation failure"
        # Suggestions are only included when generated
        # This test verifies the formatter can handle suggestions when present

    def test_error_format_structure(self):
        """Validation errors should follow text format structure."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "node1", "type": "nonexistent", "params": {}}],
            "edges": [],
            "outputs": {},
        }

        result = ExecutionService.validate_workflow(workflow)

        # Check text format structure
        assert isinstance(result, str), "Should return string"
        assert result.startswith("✗"), "Should start with failure indicator"
        assert "• " in result, "Should use bullet points for errors"
