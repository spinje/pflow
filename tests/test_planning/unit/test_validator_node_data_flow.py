"""Test ValidatorNode with data flow validation enabled.

WHEN TO RUN:
- After modifying ValidatorNode validation logic
- After changing data flow validation
- When USE_NEW_VALIDATOR feature flag is modified

WHAT IT VALIDATES:
- ValidatorNode catches forward references when new validator enabled
- ValidatorNode catches circular dependencies when new validator enabled
- ValidatorNode catches undefined inputs when new validator enabled
- Old validator behavior unchanged when feature flag disabled
"""

from unittest.mock import MagicMock

import pytest

from pflow.planning.nodes import ValidatorNode


class TestValidatorNodeDataFlow:
    """Test ValidatorNode with data flow validation."""

    @pytest.fixture
    def validator(self):
        """Create ValidatorNode with mocked registry."""
        validator = ValidatorNode()
        # Mock registry to avoid real node type validation
        validator.registry = MagicMock()
        validator.registry.get_nodes_metadata.return_value = {
            "test": {"interface": {"outputs": ["output"]}},
            "read-file": {"interface": {"outputs": ["content"]}},
            "llm": {"interface": {"outputs": ["response"]}},
            "write-file": {"interface": {"outputs": ["success"]}},
        }
        return validator

    def test_validator_catches_forward_references(self, validator):
        """Test that validator catches forward references (now default behavior)."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "node2", "type": "test", "params": {"data": "${node1.output}"}},
                {"id": "node1", "type": "test", "params": {}},
            ],
            "edges": [
                {"from": "node2", "to": "node1"}  # Wrong order!
            ],
            "inputs": {},
        }

        prep_res = {
            "workflow": workflow,
            "extracted_params": {},
            "generation_attempts": 0,
        }

        result = validator.exec(prep_res)
        errors = result.get("errors", [])

        # Should catch the forward reference
        assert len(errors) > 0
        assert any("after" in str(e) for e in errors), f"Expected 'after' in errors: {errors}"

    def test_validator_catches_circular_dependencies(self, validator):
        """Test that validator catches circular dependencies."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "a", "type": "test", "params": {"data": "${b.output}"}},
                {"id": "b", "type": "test", "params": {"data": "${a.output}"}},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "a"},  # Creates cycle
            ],
            "inputs": {},
        }

        prep_res = {
            "workflow": workflow,
            "extracted_params": {},
            "generation_attempts": 0,
        }

        result = validator.exec(prep_res)
        errors = result.get("errors", [])

        # Should catch circular dependency
        assert len(errors) > 0
        assert any("Circular dependency" in str(e) for e in errors)

    def test_validator_catches_undefined_inputs(self, validator):
        """Test that validator catches undefined input parameters."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "node1",
                    "type": "test",
                    "params": {
                        "data": "${missing_input}"  # Not in inputs!
                    },
                },
            ],
            "edges": [],
            "inputs": {},  # Empty inputs
        }

        prep_res = {
            "workflow": workflow,
            "extracted_params": {},
            "generation_attempts": 0,
        }

        result = validator.exec(prep_res)
        errors = result.get("errors", [])

        # Should catch undefined input
        assert len(errors) > 0
        assert any("undefined input" in str(e) for e in errors)

    def test_valid_workflow_passes(self, validator):
        """Test that valid workflows pass validation."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "read", "type": "read-file", "params": {"file": "${input_file}"}},
                {"id": "process", "type": "llm", "params": {"prompt": "Process: ${read.content}"}},
                {"id": "write", "type": "write-file", "params": {"content": "${process.response}"}},
            ],
            "edges": [
                {"from": "read", "to": "process"},
                {"from": "process", "to": "write"},
            ],
            "inputs": {"input_file": {"type": "string", "required": True}},
        }

        prep_res = {
            "workflow": workflow,
            "extracted_params": {"input_file": "test.txt"},
            "generation_attempts": 0,
        }

        result = validator.exec(prep_res)
        errors = result.get("errors", [])

        # Valid workflow should pass
        assert errors == []

    def test_parallel_branches_valid(self, validator):
        """Test that parallel execution branches are valid."""
        workflow = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "input", "type": "read-file", "params": {"file": "data.txt"}},
                {"id": "branch1", "type": "llm", "params": {"data": "${input.content}"}},
                {"id": "branch2", "type": "llm", "params": {"data": "${input.content}"}},
                {
                    "id": "merge",
                    "type": "write-file",
                    "params": {"content": "${branch1.response} + ${branch2.response}"},
                },
            ],
            "edges": [
                {"from": "input", "to": "branch1"},
                {"from": "input", "to": "branch2"},
                {"from": "branch1", "to": "merge"},
                {"from": "branch2", "to": "merge"},
            ],
            "inputs": {},
        }

        prep_res = {
            "workflow": workflow,
            "extracted_params": {},
            "generation_attempts": 0,
        }

        result = validator.exec(prep_res)
        errors = result.get("errors", [])

        # Parallel branches should be valid
        assert errors == []
