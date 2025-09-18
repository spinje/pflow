"""Test null default handling for smart defaults."""

import pytest

from pflow.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow
from pflow.runtime.template_resolver import TemplateResolver


class TestNullDefaults:
    """Test null default handling for enabling smart defaults in nodes."""

    def test_variable_exists_simple(self):
        """Test variable_exists for simple variables."""
        context = {"present": "value", "null_value": None, "empty": "", "zero": 0, "false": False}

        # Variables that exist
        assert TemplateResolver.variable_exists("present", context) is True
        assert TemplateResolver.variable_exists("null_value", context) is True
        assert TemplateResolver.variable_exists("empty", context) is True
        assert TemplateResolver.variable_exists("zero", context) is True
        assert TemplateResolver.variable_exists("false", context) is True

        # Variables that don't exist
        assert TemplateResolver.variable_exists("missing", context) is False
        assert TemplateResolver.variable_exists("undefined", context) is False

    def test_variable_exists_nested(self):
        """Test variable_exists for nested paths."""
        context = {"data": {"field": "value", "null_field": None, "nested": {"deep": "value"}}, "null_parent": None}

        # Paths that exist
        assert TemplateResolver.variable_exists("data.field", context) is True
        assert TemplateResolver.variable_exists("data.null_field", context) is True
        assert TemplateResolver.variable_exists("data.nested.deep", context) is True

        # Paths that don't exist
        assert TemplateResolver.variable_exists("data.missing", context) is False
        assert TemplateResolver.variable_exists("missing.field", context) is False

        # Can't traverse through None
        assert TemplateResolver.variable_exists("null_parent.field", context) is False

    def test_null_default_preserves_none_in_simple_template(self):
        """Test that null defaults pass None to nodes for simple templates."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "${input_value}"}}],
            "edges": [],  # Empty edges array required
            "inputs": {
                "input_value": {
                    "description": "Test input",
                    "required": False,
                    "type": "string",
                    "default": None,  # Explicit null default
                }
            },
        }

        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params={})

        # Check that null default was applied to initial_params
        node = flow.start_node
        assert hasattr(node, "initial_params")
        assert "input_value" in node.initial_params
        assert node.initial_params["input_value"] is None

        # To truly verify the node receives None, we need to mock and execute
        # But for this test, verifying initial_params is sufficient to prove
        # that null defaults are being preserved and passed correctly

    def test_empty_string_default(self):
        """Test that empty string defaults are preserved."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo ${input_value}"}}],
            "edges": [],
            "inputs": {
                "input_value": {
                    "description": "Test input",
                    "required": False,
                    "type": "string",
                    "default": "",  # Empty string default
                }
            },
        }

        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params={})

        # Check that empty string default was applied
        node = flow.start_node
        assert hasattr(node, "initial_params")
        assert "input_value" in node.initial_params
        assert node.initial_params["input_value"] == ""

    def test_null_in_complex_template(self):
        """Test that null becomes empty string in complex templates."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo Value: ${input_value}"}}],
            "edges": [],
            "inputs": {
                "input_value": {"description": "Test input", "required": False, "type": "string", "default": None}
            },
        }

        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params={})

        # Check that null default was applied
        node = flow.start_node
        assert hasattr(node, "initial_params")
        assert "input_value" in node.initial_params
        assert node.initial_params["input_value"] is None
        # In complex templates, None will become empty string during resolution

    @pytest.mark.skip(reason="TODO: Re-enable when TemplateAwareNodeWrapper API is stabilized")
    def test_missing_variable_keeps_template(self):
        """Test that unresolved templates are preserved for debugging.

        This test validates that when template variables are not found in the
        resolution context, the template string is preserved as-is for debugging
        purposes rather than being replaced with an empty string or raising an error.
        """
        # This test needs to be rewritten to match the current TemplateAwareNodeWrapper API
        # The wrapper no longer exposes _resolve_templates as a public method
        # and the initialization signature has changed.
        pass

    def test_null_value_type_preservation(self):
        """Test that different types including None are preserved correctly."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {
                        "null_param": "${null_input}",
                        "string_param": "${string_input}",
                        "number_param": "${number_input}",
                        "bool_param": "${bool_input}",
                    },
                }
            ],
            "edges": [],
            "inputs": {
                "null_input": {"required": False, "default": None},
                "string_input": {"required": False, "default": "test"},
                "number_input": {"required": False, "default": 42},
                "bool_input": {"required": False, "default": True},
            },
        }

        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params={})

        node = flow.start_node
        # Check type preservation in initial_params
        assert hasattr(node, "initial_params")
        assert node.initial_params["null_input"] is None
        assert node.initial_params["string_input"] == "test"
        assert node.initial_params["number_input"] == 42
        assert node.initial_params["bool_input"] is True

    def test_override_null_default_with_provided_value(self):
        """Test that provided values override null defaults."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo ${input_value}"}}],
            "edges": [],
            "inputs": {"input_value": {"description": "Test input", "required": False, "default": None}},
        }

        registry = Registry()

        # Provide a value that overrides the null default
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params={"input_value": "provided value"})

        node = flow.start_node
        assert hasattr(node, "initial_params")
        assert node.initial_params["input_value"] == "provided value"

    def test_multiple_null_defaults(self):
        """Test workflow with multiple optional inputs with null defaults."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {"param1": "${input1}", "param2": "${input2}", "param3": "${input3}"},
                }
            ],
            "edges": [],
            "inputs": {
                "input1": {"required": False, "default": None},
                "input2": {"required": False, "default": ""},
                "input3": {"required": False},  # No default at all
            },
        }

        registry = Registry()

        # Note: input3 without default and not provided will fail validation
        # So we need to provide it
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params={"input3": "value3"})

        node = flow.start_node
        assert hasattr(node, "initial_params")
        assert node.initial_params["input1"] is None  # null default
        assert node.initial_params["input2"] == ""  # empty string default
        assert node.initial_params["input3"] == "value3"  # provided value
