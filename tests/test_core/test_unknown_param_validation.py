"""Tests for unknown parameter error detection.

This validates the detection of parameters not recognized by a node's interface,
which may indicate typos or documentation bullets accidentally parsed as params.

Previously this file tested JSON string template anti-pattern detection (layer 7),
which was removed as part of the markdown format migration (Task 107). That
validation is no longer relevant since workflows are authored in markdown, not JSON.
"""

import pytest

from pflow.core.workflow.validator import WorkflowValidator
from pflow.registry import Registry


class TestValidateUnknownParams:
    """Tests for the _validate_unknown_params method."""

    @pytest.fixture
    def registry(self) -> Registry:
        """Load real registry for tests."""
        return Registry()

    def test_errors_on_unknown_param(self, registry: Registry) -> None:
        """Should error when a node has a parameter not in its interface."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {
                        "command": "echo hello",
                        "nonexistent_param": "value",
                    },
                }
            ],
            "edges": [],
        }

        errors = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(errors) == 1
        assert "nonexistent_param" in errors[0]
        assert "test" in errors[0]

    def test_no_error_for_known_params(self, registry: Registry) -> None:
        """Should not error when all params are recognized."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {
                        "command": "echo hello",
                    },
                }
            ],
            "edges": [],
        }

        errors = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(errors) == 0

    def test_suggests_similar_param(self, registry: Registry) -> None:
        """Should suggest similar params when a typo is detected."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "llm",
                    "params": {
                        "promt": "hello",  # Typo for 'prompt'
                    },
                }
            ],
            "edges": [],
        }

        errors = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(errors) >= 1
        # Should suggest 'prompt' as a correction
        error_text = errors[0]
        assert "promt" in error_text
        assert "Did you mean" in error_text

    def test_skips_nodes_without_params(self, registry: Registry) -> None:
        """Should skip nodes that have no params."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                }
            ],
            "edges": [],
        }

        errors = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(errors) == 0

    def test_skips_unknown_node_types(self, registry: Registry) -> None:
        """Should skip nodes with unknown types (no interface metadata)."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "nonexistent-node-type",
                    "params": {
                        "anything": "value",
                    },
                }
            ],
            "edges": [],
        }

        errors = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(errors) == 0

    def test_multiple_unknown_params_multiple_nodes(self, registry: Registry) -> None:
        """Should detect unknown params across multiple nodes."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "node1",
                    "type": "shell",
                    "params": {
                        "command": "echo a",
                        "bad_param": "x",
                    },
                },
                {
                    "id": "node2",
                    "type": "llm",
                    "params": {
                        "prompt": "hello",
                        "another_bad": "y",
                    },
                },
            ],
            "edges": [{"from": "node1", "to": "node2"}],
        }

        errors = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(errors) == 2
        error_text = " ".join(errors)
        assert "bad_param" in error_text
        assert "another_bad" in error_text


class TestUnknownParamErrorsIntegration:
    """Integration tests through WorkflowValidator.validate()."""

    @pytest.fixture
    def registry(self) -> Registry:
        """Load real registry for integration tests."""
        return Registry()

    def test_unknown_params_appear_as_errors(self, registry: Registry) -> None:
        """Unknown params should appear in errors, not warnings."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {
                        "command": "echo hello",
                        "Note": "this is a note",  # Accidentally parsed as param
                    },
                }
            ],
            "edges": [],
        }

        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=workflow_ir,
            registry=registry,
            skip_node_types=False,
        )

        # Unknown params should be errors, not warnings
        unknown_errors = [e for e in errors if "unknown parameter" in e.lower()]
        assert len(unknown_errors) >= 1
        assert "Note" in unknown_errors[0]

    def test_no_errors_for_valid_workflow(self, registry: Registry) -> None:
        """A valid workflow should produce no unknown param errors."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {
                        "command": "echo hello",
                    },
                }
            ],
            "edges": [],
        }

        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=workflow_ir,
            registry=registry,
            skip_node_types=False,
        )

        unknown_errors = [e for e in errors if "unknown parameter" in e.lower()]
        assert len(unknown_errors) == 0

    def test_no_unknown_param_errors_without_registry(self) -> None:
        """When registry is None and skip_node_types, unknown param check skipped."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {
                        "command": "echo hello",
                        "bad_param": "x",
                    },
                }
            ],
            "edges": [],
        }

        errors, _warnings = WorkflowValidator.validate(
            workflow_ir=workflow_ir,
            extracted_params=None,
            registry=None,
            skip_node_types=True,
        )

        # No unknown param errors since registry is None
        unknown_errors = [e for e in errors if "unknown parameter" in e.lower()]
        assert len(unknown_errors) == 0


class TestUnknownParamBlocksExecution:
    """Test that unknown params block workflow execution (the #100 scenario).

    This tests the full pipeline: execute_workflow() → validate() → error →
    ExecutionResult(FAILED). The unit and integration tests above only test
    validate() in isolation — this tests the actual user-facing behavior.
    """

    def test_typo_param_blocks_execution_with_suggestion(self) -> None:
        """A param typo should block execution and suggest the correct name.

        This is the core scenario from GitHub Issue #100: a user writes
        'promt' instead of 'prompt', and the workflow silently ignores it.
        After the fix, execution should fail with a helpful error.
        """
        from pflow.core.workflow.status import WorkflowStatus
        from pflow.execution.workflow_execution import execute_workflow

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "summarize",
                    "type": "llm",
                    "params": {
                        "promt": "Summarize this text",  # Typo: 'promt' instead of 'prompt'
                    },
                }
            ],
            "edges": [],
        }

        result = execute_workflow(workflow_ir=workflow_ir, execution_params={})

        assert not result.success
        assert result.status == WorkflowStatus.FAILED
        assert result.action_result == "validation_failed"

        # Error should identify the typo and suggest the fix
        error_messages = " ".join(e["message"] for e in result.errors)
        assert "promt" in error_messages
        assert "Did you mean" in error_messages
