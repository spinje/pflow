"""Tests for JSON string template anti-pattern detection.

This validates the detection of manually constructed JSON strings with templates,
which is a common mistake that leads to runtime failures when template values
contain special characters (newlines, quotes, backslashes).

The anti-pattern:
    "body_schema": "{\"content\": \"${var}\"}"

The correct pattern:
    "body_schema": {"content": "${var}"}
"""

import pytest

from pflow.core.workflow_validator import WorkflowValidator
from pflow.registry import Registry


class TestCheckJsonStringWithTemplate:
    """Unit tests for the _check_json_string_with_template method."""

    def test_detects_json_object_with_template(self):
        """Should detect JSON object string with template variable."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="body_schema",
            param_value='{"content": "${message}"}',
            expected_type="str",
            node_id="test-node",
        )
        assert error is not None
        assert "body_schema" in error
        assert "object syntax" in error.lower()

    def test_detects_nested_json_with_template(self):
        """Should detect nested JSON structure with templates."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="data",
            param_value='{"outer": {"inner": "${value}"}}',
            expected_type="str",
            node_id="test-node",
        )
        assert error is not None

    def test_detects_json_array_with_template(self):
        """Should detect JSON array string with template."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="items",
            param_value='["${item1}", "${item2}"]',
            expected_type="str",
            node_id="test-node",
        )
        assert error is not None
        assert "array syntax" in error.lower()

    def test_detects_array_of_objects_with_template(self):
        """Should detect array of objects with templates."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="records",
            param_value='[{"id": "${id}"}]',
            expected_type="str",
            node_id="test-node",
        )
        assert error is not None
        assert "array syntax" in error.lower()

    def test_ignores_object_syntax(self):
        """Should NOT flag when value is already an object (not string)."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="body_schema",
            param_value={"content": "${message}"},  # Object, not string
            expected_type="str",
            node_id="test-node",
        )
        assert error is None

    def test_ignores_non_str_typed_params(self):
        """Should NOT flag when expected type is not str."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="config",
            param_value='{"key": "${value}"}',
            expected_type="dict",  # Expects dict, not str
            node_id="test-node",
        )
        assert error is None

    def test_ignores_json_without_templates(self):
        """Should NOT flag JSON strings without template variables."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="body_schema",
            param_value='{"content": "static message"}',
            expected_type="str",
            node_id="test-node",
        )
        assert error is None

    def test_ignores_plain_string_with_template(self):
        """Should NOT flag plain strings (not JSON) with templates."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="message",
            param_value="Hello ${name}!",
            expected_type="str",
            node_id="test-node",
        )
        assert error is None

    def test_ignores_template_only(self):
        """Should NOT flag simple template references."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="data",
            param_value="${json_data}",
            expected_type="str",
            node_id="test-node",
        )
        assert error is None

    def test_ignores_curly_braces_not_json(self):
        """Should NOT flag curly braces that aren't JSON.

        The pattern {hello ${name}} doesn't start with {" so it's not JSON object syntax.
        """
        error = WorkflowValidator._check_json_string_with_template(
            param_key="template",
            param_value="{hello ${name}}",
            expected_type="str",
            node_id="test-node",
        )
        assert error is None

    def test_ignores_none_expected_type(self):
        """Should NOT flag when expected type is unknown."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="unknown",
            param_value='{"key": "${value}"}',
            expected_type=None,
            node_id="test-node",
        )
        assert error is None

    def test_error_message_shows_suggested_fix(self):
        """Error message should show the correct object syntax."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="body_schema",
            param_value='{"content": "${message}"}',
            expected_type="str",
            node_id="post-message",
        )
        assert error is not None
        # Should mention the specific template that could cause issues
        assert "${message}" in error
        # Should show both problematic and correct versions
        assert '{"content": "${message}"}' in error
        # Should mention object syntax as the fix
        assert "object syntax" in error.lower()
        # Should have visual markers for wrong/right
        assert "\u2717" in error  # ✗
        assert "\u2713" in error  # ✓

    def test_handles_whitespace_before_json(self):
        """Should detect JSON with leading whitespace."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="data",
            param_value='  {"key": "${value}"}',  # Leading spaces
            expected_type="str",
            node_id="test-node",
        )
        assert error is not None

    def test_ignores_list_typed_params(self):
        """Should NOT flag when expected type is list."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="items",
            param_value='["${item}"]',
            expected_type="list",
            node_id="test-node",
        )
        assert error is None

    def test_ignores_any_typed_params(self):
        """Should NOT flag when expected type is 'any'."""
        error = WorkflowValidator._check_json_string_with_template(
            param_key="data",
            param_value='{"key": "${value}"}',
            expected_type="any",
            node_id="test-node",
        )
        assert error is None


class TestBuildParamTypeMap:
    """Tests for _build_param_type_map helper."""

    def test_extracts_from_params_array(self):
        """Should extract types from params array."""
        interface = {
            "params": [
                {"key": "path_params", "type": "str"},
                {"key": "body_schema", "type": "str"},
            ]
        }
        type_map = WorkflowValidator._build_param_type_map(interface)
        assert type_map == {"path_params": "str", "body_schema": "str"}

    def test_extracts_from_inputs_array(self):
        """Should extract types from inputs array."""
        interface = {
            "inputs": [
                {"key": "file_path", "type": "str"},
            ]
        }
        type_map = WorkflowValidator._build_param_type_map(interface)
        assert type_map == {"file_path": "str"}

    def test_combines_params_and_inputs(self):
        """Should extract from both params and inputs arrays."""
        interface = {
            "params": [
                {"key": "prompt", "type": "str"},
            ],
            "inputs": [
                {"key": "context", "type": "str"},
            ],
        }
        type_map = WorkflowValidator._build_param_type_map(interface)
        assert type_map == {"prompt": "str", "context": "str"}

    def test_handles_empty_interface(self):
        """Should return empty map for empty interface."""
        type_map = WorkflowValidator._build_param_type_map({})
        assert type_map == {}

    def test_handles_malformed_entries(self):
        """Should skip entries missing key or type."""
        interface = {
            "params": [
                {"key": "valid", "type": "str"},
                {"key": "missing_type"},
                {"type": "str"},  # Missing key
                "not_a_dict",
            ]
        }
        type_map = WorkflowValidator._build_param_type_map(interface)
        assert type_map == {"valid": "str"}

    def test_handles_various_types(self):
        """Should handle various parameter types."""
        interface = {
            "params": [
                {"key": "text", "type": "str"},
                {"key": "count", "type": "int"},
                {"key": "items", "type": "list[str]"},
                {"key": "config", "type": "dict"},
                {"key": "data", "type": "any"},
            ]
        }
        type_map = WorkflowValidator._build_param_type_map(interface)
        assert type_map == {
            "text": "str",
            "count": "int",
            "items": "list[str]",
            "config": "dict",
            "data": "any",
        }


class TestValidateJsonStringTemplatesIntegration:
    """Integration tests for _validate_json_string_templates with real registry."""

    @pytest.fixture
    def registry(self):
        """Load real registry for integration tests."""
        return Registry()

    def test_detects_antipattern_with_llm_node(self, registry):
        """Should detect anti-pattern with real LLM node type."""
        # The llm node has str-typed params: prompt, system, model
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "llm",
                    "params": {
                        # This is the anti-pattern - JSON string with template in str param
                        "prompt": '{"content": "${some_var}"}',
                    },
                }
            ],
            "edges": [],
        }

        errors = WorkflowValidator._validate_json_string_templates(workflow_ir, registry)

        assert len(errors) == 1
        assert "prompt" in errors[0]
        assert "object syntax" in errors[0].lower()

    def test_no_error_for_object_syntax(self, registry):
        """Should not flag object syntax (the correct approach)."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "llm",
                    "params": {
                        # Object syntax - this is correct and should not be flagged
                        "prompt": {"content": "${some_var}"},
                    },
                }
            ],
            "edges": [],
        }

        errors = WorkflowValidator._validate_json_string_templates(workflow_ir, registry)

        assert len(errors) == 0

    def test_no_error_for_plain_template_string(self, registry):
        """Should not flag plain template strings."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "llm",
                    "params": {
                        # This is normal usage - plain string with template
                        "prompt": "Process this: ${data}",
                    },
                }
            ],
            "edges": [],
        }

        errors = WorkflowValidator._validate_json_string_templates(workflow_ir, registry)

        assert len(errors) == 0

    def test_no_error_for_unknown_node_type(self, registry):
        """Should skip validation for unknown node types (no interface metadata)."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "nonexistent-node-type",
                    "params": {
                        "body_schema": '{"content": "${some_var}"}',
                    },
                }
            ],
            "edges": [],
        }

        errors = WorkflowValidator._validate_json_string_templates(workflow_ir, registry)

        # Should not error - unknown node type means no interface metadata
        # so we can't know if body_schema expects str
        assert len(errors) == 0

    def test_no_error_for_static_json_string(self, registry):
        """Should not flag static JSON strings (no templates)."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "llm",
                    "params": {
                        # Static JSON - no templates, so this is fine
                        "prompt": '{"content": "hello"}',
                    },
                }
            ],
            "edges": [],
        }

        errors = WorkflowValidator._validate_json_string_templates(workflow_ir, registry)

        assert len(errors) == 0


class TestWorkflowValidatorFullIntegration:
    """Full integration tests through WorkflowValidator.validate()."""

    @pytest.fixture
    def registry(self):
        """Load real registry for integration tests."""
        return Registry()

    def test_full_validation_catches_antipattern(self, registry):
        """Should catch the anti-pattern in full workflow validation."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {"message": {"type": "string", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "params": {
                        # This is the anti-pattern
                        "prompt": '{"content": "${message}"}',
                    },
                }
            ],
            "edges": [],
        }

        errors, warnings = WorkflowValidator.validate(
            workflow_ir=workflow_ir,
            extracted_params={"message": "test"},
            registry=registry,
        )

        # Should have error about JSON string syntax
        json_errors = [e for e in errors if "object syntax" in e.lower()]
        assert len(json_errors) == 1
        assert "prompt" in json_errors[0]

    def test_full_validation_passes_object_syntax(self, registry):
        """Should pass when using correct object syntax."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "inputs": {"message": {"type": "string", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "params": {
                        # Object syntax - correct approach
                        "prompt": {"content": "${message}"},
                    },
                }
            ],
            "edges": [],
        }

        errors, warnings = WorkflowValidator.validate(
            workflow_ir=workflow_ir,
            extracted_params={"message": "test"},
            registry=registry,
        )

        # Should not have JSON string template errors
        json_errors = [e for e in errors if "object syntax" in e.lower()]
        assert len(json_errors) == 0

    def test_validation_without_registry_skips_json_check(self):
        """When registry is None, JSON string validation should be skipped."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "llm",
                    "params": {
                        "prompt": '{"content": "${var}"}',
                    },
                }
            ],
            "edges": [],
        }

        # When registry is None and skip_node_types is True,
        # the registry remains None throughout validation
        errors, warnings = WorkflowValidator.validate(
            workflow_ir=workflow_ir,
            extracted_params=None,  # Don't trigger template validation
            registry=None,
            skip_node_types=True,  # Don't trigger node type validation
        )

        # JSON string validation should be skipped (registry is None)
        # So no JSON-related errors
        json_errors = [e for e in errors if "object syntax" in e.lower()]
        assert len(json_errors) == 0

    def test_multiple_nodes_multiple_errors(self, registry):
        """Should detect anti-pattern in multiple nodes."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "node1",
                    "type": "llm",
                    "params": {"prompt": '{"a": "${x}"}'},
                },
                {
                    "id": "node2",
                    "type": "llm",
                    "params": {"prompt": '{"b": "${y}"}'},
                },
            ],
            "edges": [{"from": "node1", "to": "node2"}],
        }

        errors = WorkflowValidator._validate_json_string_templates(workflow_ir, registry)

        assert len(errors) == 2
        # Check both nodes are mentioned
        error_text = " ".join(errors)
        assert "node1" in error_text
        assert "node2" in error_text
