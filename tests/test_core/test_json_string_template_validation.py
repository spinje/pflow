"""Tests for unknown parameter warning detection.

This validates the detection of parameters not recognized by a node's interface,
which may indicate typos or documentation bullets accidentally parsed as params.

Previously this file tested JSON string template anti-pattern detection (layer 7),
which was removed as part of the markdown format migration (Task 107). That
validation is no longer relevant since workflows are authored in markdown, not JSON.
"""

import pytest

from pflow.core.workflow_validator import WorkflowValidator
from pflow.registry import Registry


class TestValidateUnknownParams:
    """Tests for the _validate_unknown_params method."""

    @pytest.fixture
    def registry(self) -> Registry:
        """Load real registry for tests."""
        return Registry()

    def test_warns_on_unknown_param(self, registry: Registry) -> None:
        """Should warn when a node has a parameter not in its interface."""
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

        warnings = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(warnings) == 1
        assert "nonexistent_param" in warnings[0]
        assert "test" in warnings[0]

    def test_no_warning_for_known_params(self, registry: Registry) -> None:
        """Should not warn when all params are recognized."""
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

        warnings = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(warnings) == 0

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

        warnings = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(warnings) >= 1
        # Should suggest 'prompt' as a correction
        warning_text = warnings[0]
        assert "promt" in warning_text
        assert "Did you mean" in warning_text

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

        warnings = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(warnings) == 0

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

        warnings = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(warnings) == 0

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

        warnings = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(warnings) == 2
        warning_text = " ".join(warnings)
        assert "bad_param" in warning_text
        assert "another_bad" in warning_text


class TestUnknownParamWarningsIntegration:
    """Integration tests through WorkflowValidator.validate()."""

    @pytest.fixture
    def registry(self) -> Registry:
        """Load real registry for integration tests."""
        return Registry()

    def test_unknown_params_appear_as_warnings(self, registry: Registry) -> None:
        """Unknown params should appear in warnings, not errors."""
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

        _errors, warnings = WorkflowValidator.validate(
            workflow_ir=workflow_ir,
            registry=registry,
            skip_node_types=False,
        )

        # Unknown params should be warnings, not errors
        unknown_warnings = [w for w in warnings if "unknown parameter" in str(w).lower()]
        assert len(unknown_warnings) >= 1
        assert "Note" in str(unknown_warnings[0])

    def test_no_warnings_for_valid_workflow(self, registry: Registry) -> None:
        """A valid workflow should produce no unknown param warnings."""
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

        _errors, warnings = WorkflowValidator.validate(
            workflow_ir=workflow_ir,
            registry=registry,
            skip_node_types=False,
        )

        unknown_warnings = [w for w in warnings if "unknown parameter" in str(w).lower()]
        assert len(unknown_warnings) == 0

    def test_no_unknown_param_warnings_without_registry(self) -> None:
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

        _errors, warnings = WorkflowValidator.validate(
            workflow_ir=workflow_ir,
            extracted_params=None,
            registry=None,
            skip_node_types=True,
        )

        # No unknown param warnings since registry is None
        unknown_warnings = [w for w in warnings if "unknown parameter" in str(w).lower()]
        assert len(unknown_warnings) == 0
