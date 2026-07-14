"""Tests for unknown parameter error detection.

This validates the detection of parameters not recognized by a node's interface,
which may indicate typos or documentation bullets accidentally parsed as params.

Previously this file tested JSON string template anti-pattern detection (layer 7),
which was removed as part of the markdown format migration (Task 107). That
validation is no longer relevant since workflows are authored in markdown, not JSON.
"""

import pytest

from pflow.core.diagnostic import Severity
from pflow.core.diagnostic_render import format_diagnostic
from pflow.core.workflow.validator import WorkflowValidator
from pflow.registry import Registry
from tests.shared.diagnostic_helpers import split_validator_diagnostics


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

        diagnostics = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(diagnostics) == 1
        error_text = format_diagnostic(diagnostics[0])
        assert "nonexistent_param" in error_text
        assert "test" in error_text

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

    @pytest.mark.parametrize("backend", ["claude", "codex"])
    def test_no_error_for_agent_use_api_key(self, registry: Registry, backend: str) -> None:
        """use_api_key is a recognized shared agent param.

        Guards the docstring → metadata → validator allow-list chain end-to-end:
        if the `- Params: use_api_key:` line is dropped from the node docstring,
        every workflow using the param would fail validation as "unknown".
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "agent",
                    "type": "agent",
                    "params": {
                        "backend": backend,
                        "prompt": "do a thing",
                        "use_api_key": True,
                    },
                }
            ],
            "edges": [],
        }

        errors = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert errors == []

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

        diagnostics = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(diagnostics) >= 1
        # Should suggest 'prompt' as a correction
        diagnostic = diagnostics[0]
        assert "promt" in format_diagnostic(diagnostic)
        assert diagnostic.context is not None
        assert diagnostic.context.get("similar_names")

    def test_unknown_param_diagnostic_preserves_structure(self, registry: Registry) -> None:
        """Unknown parameter diagnostics should keep structured fix data."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "writer",
                    "type": "write-file",
                    "params": {
                        "file_pat": "output.txt",
                        "content": "hello",
                    },
                }
            ],
            "edges": [],
        }

        diagnostics = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(diagnostics) == 1
        diagnostic = diagnostics[0]
        context = diagnostic.context or {}

        assert diagnostic.severity == Severity.ERROR
        assert diagnostic.node_id == "writer"
        assert diagnostic.title == "Validation Error"
        assert "file_pat" in diagnostic.message
        assert diagnostic.suggestions
        assert any("file_path" in suggestion for suggestion in diagnostic.suggestions)
        assert context.get("path") == "nodes[id=writer].params.file_pat"
        assert "file_path" in (context.get("available_fields") or [])
        assert "file_path" in (context.get("similar_names") or [])

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

        diagnostics = WorkflowValidator._validate_unknown_params(workflow_ir, registry)

        assert len(diagnostics) == 2
        error_text = " ".join(format_diagnostic(diagnostic) for diagnostic in diagnostics)
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

        errors, _warnings = split_validator_diagnostics(
            workflow_ir=workflow_ir,
            registry=registry,
            skip_node_types=False,
        )

        # Unknown params should be errors, not warnings
        unknown_errors = [d for d in errors if "unknown parameter" in d.message.lower()]
        assert len(unknown_errors) >= 1
        assert "'Note'" in unknown_errors[0].message

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

        errors, _warnings = split_validator_diagnostics(
            workflow_ir=workflow_ir,
            registry=registry,
            skip_node_types=False,
        )

        unknown_errors = [d for d in errors if "unknown parameter" in d.message.lower()]
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

        errors, _warnings = split_validator_diagnostics(
            workflow_ir=workflow_ir,
            extracted_params=None,
            registry=None,
            skip_node_types=True,
        )

        # No unknown param errors since registry is None
        unknown_errors = [d for d in errors if "unknown parameter" in d.message.lower()]
        assert len(unknown_errors) == 0


class TestUnknownParamBlocksExecution:
    """Test that unknown params block workflow execution (the #100 scenario).

    This tests the WorkflowValidator pipeline: validate() → error.
    Unknown param detection is step 7 of WorkflowValidator — it's not checked
    by the compiler. Each caller owns its preconditions: CLI validates via
    _validate_before_execution(), MCP validates in execution_service.py.
    """

    @pytest.fixture
    def registry(self) -> Registry:
        """Load real registry for tests."""
        return Registry()

    def test_typo_param_blocks_execution_with_suggestion(self, registry: Registry) -> None:
        """A param typo should be caught by WorkflowValidator and suggest the correct name.

        This is the core scenario from GitHub Issue #100: a user writes
        'promt' instead of 'prompt', and the workflow silently ignores it.
        After the fix, validation catches it with a helpful error.
        """
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

        errors, _warnings = split_validator_diagnostics(
            workflow_ir=workflow_ir,
            registry=registry,
            skip_node_types=False,
        )

        # Error should identify the typo and suggest the fix
        diagnostic = next(d for d in errors if "promt" in d.message)
        assert "promt" in diagnostic.message
        assert diagnostic.context is not None
        assert diagnostic.context.get("similar_names")
