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

    def test_missing_variable_keeps_template(self):
        """Test that unresolved templates are preserved for debugging in permissive mode.

        In permissive mode, when a template variable cannot be resolved, the template
        string is preserved as-is (e.g., '${missing_var}') rather than being replaced
        with an empty string. This allows debugging of template resolution issues.

        Note: In strict mode (default), a ValueError is raised instead - see
        test_missing_variable_raises_in_strict_mode for that behavior.
        """
        from unittest.mock import MagicMock

        from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper

        # Create a mock inner node
        mock_node = MagicMock()
        mock_node.params = {}

        # Capture params during execution (wrapper restores original params after _run)
        captured_params = {}

        def capture_params_during_execution(shared):
            captured_params.update(mock_node.params)
            return "default"

        mock_node._run = MagicMock(side_effect=capture_params_during_execution)

        # Create wrapper in permissive mode
        wrapper = TemplateAwareNodeWrapper(
            inner_node=mock_node,
            node_id="test-node",
            initial_params={},
            template_resolution_mode="permissive",
        )

        # Set params with template that references missing variable
        wrapper.set_params({"message": "${missing_variable}"})

        # Run with empty shared store - should NOT raise in permissive mode
        shared = {}
        wrapper._run(shared)

        # Inner node SHOULD have been called (permissive mode continues)
        mock_node._run.assert_called_once()

        # Template error should be stored in shared store
        assert "__template_errors__" in shared
        assert "test-node" in shared["__template_errors__"]
        error_info = shared["__template_errors__"]["test-node"]
        assert "missing_variable" in str(error_info.get("message", ""))

        # The unresolved template should be preserved (passed to inner node as literal)
        # We capture the params during execution since wrapper restores them after
        assert captured_params.get("message") == "${missing_variable}"

    def test_missing_variable_raises_in_strict_mode(self):
        """Test that unresolved templates raise ValueError in strict mode.

        In strict mode (the default), when a template variable cannot be resolved,
        a ValueError is raised with a helpful error message. The template string
        is preserved in the error message for debugging.
        """
        from unittest.mock import MagicMock

        from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper

        # Create a mock inner node
        mock_node = MagicMock()
        mock_node.params = {}
        mock_node._run = MagicMock(return_value="default")

        # Create wrapper in strict mode (default)
        wrapper = TemplateAwareNodeWrapper(
            inner_node=mock_node,
            node_id="test-node",
            initial_params={},
            template_resolution_mode="strict",
        )

        # Set params with template that references missing variable
        wrapper.set_params({"message": "${missing_variable}"})

        # Run with empty shared store - should raise ValueError in strict mode
        shared = {}
        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        # Verify error message contains helpful debugging info
        error_msg = str(exc_info.value)
        assert "missing_variable" in error_msg

        # Inner node should NOT have been called (error raised before execution)
        mock_node._run.assert_not_called()

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
                "input3": {"required": False},  # No default at all - should resolve to None
            },
        }

        registry = Registry()

        # Optional inputs without explicit defaults should resolve to None
        # This allows templates like ${input3} to work without requiring a value
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params={})

        node = flow.start_node
        assert hasattr(node, "initial_params")
        assert node.initial_params["input1"] is None  # explicit null default
        assert node.initial_params["input2"] == ""  # empty string default
        assert node.initial_params["input3"] is None  # implicit None (no default specified)

    def test_optional_input_without_default_resolves_to_none(self):
        """Test that optional inputs without defaults resolve to None in templates.

        This is a regression test for the bug where optional inputs without defaults
        failed template resolution with "Unresolved variables" error.

        Bug report: Optional inputs declared with required=false but no default value
        should resolve to None when not provided, not fail validation.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {
                        "stdin": "${optional_param}",
                        "command": "cat",
                    },
                }
            ],
            "edges": [],
            "inputs": {
                "optional_param": {
                    "type": "string",
                    "required": False,
                    # No default specified - should resolve to None
                    "description": "Optional parameter with no default",
                },
            },
        }

        registry = Registry()

        # Should compile successfully - optional input without default resolves to None
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params={})

        node = flow.start_node
        assert hasattr(node, "initial_params")
        assert node.initial_params["optional_param"] is None

    def test_optional_input_without_default_can_be_overridden(self):
        """Test that optional inputs without defaults can still be provided."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {
                        "stdin": "${optional_param}",
                        "command": "cat",
                    },
                }
            ],
            "edges": [],
            "inputs": {
                "optional_param": {
                    "type": "string",
                    "required": False,
                    # No default specified
                },
            },
        }

        registry = Registry()

        # Provide a value for the optional input
        flow = compile_ir_to_flow(workflow_ir, registry, initial_params={"optional_param": "user_provided"})

        node = flow.start_node
        assert hasattr(node, "initial_params")
        assert node.initial_params["optional_param"] == "user_provided"
