"""Test null default handling for smart defaults."""

import pytest

from pflow.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine
from pflow.runtime.engine.template_resolution import (
    build_type_cache,
    resolve_templates,
    split_params,
)
from pflow.runtime.engine.types import TemplateConfig
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
        """Test that null defaults are stored in resolved_defaults at compile time."""
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
        workflow = compile_workflow(workflow_ir, registry, initial_params={})

        # Defaults are stored in resolved_defaults on the CompiledWorkflow
        resolved_defaults = workflow.resolved_defaults
        assert "input_value" in resolved_defaults
        assert resolved_defaults["input_value"] is None

    def test_empty_string_default(self):
        """Test that empty string defaults are preserved in resolved_defaults."""
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
        workflow = compile_workflow(workflow_ir, registry, initial_params={})

        # Check that empty string default was preserved
        resolved_defaults = workflow.resolved_defaults
        assert "input_value" in resolved_defaults
        assert resolved_defaults["input_value"] == ""

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
        workflow = compile_workflow(workflow_ir, registry, initial_params={})

        # Check that null default was preserved at compile time
        resolved_defaults = workflow.resolved_defaults
        assert "input_value" in resolved_defaults
        assert resolved_defaults["input_value"] is None
        # In complex templates, None will become empty string during resolution

    def test_missing_variable_keeps_template_in_permissive_mode(self):
        """Test that unresolved templates are preserved in permissive mode.

        In permissive mode, when a template variable cannot be resolved, the template
        string is preserved as-is (e.g., '${missing_var}') rather than being replaced
        with an empty string. Template errors are reported but execution continues.

        Note: In strict mode (default), a ValueError is raised instead — see
        test_missing_variable_raises_in_strict_mode for that behavior.
        """
        params = {"message": "${missing_variable}"}
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)
        template_config = TemplateConfig(
            template_params=template_params,
            static_params=static_params,
            expected_types=expected_types,
            resolution_mode="permissive",
        )

        # Run with empty shared store — should NOT raise in permissive mode
        shared: dict = {}
        merged_params, _last_resolutions, template_errors = resolve_templates(template_config, shared, "test-node")

        # Template errors should be reported
        assert len(template_errors) > 0
        assert any("missing_variable" in str(err.get("message", "")) for err in template_errors)

        # The unresolved template should be preserved (passed as literal)
        assert merged_params.get("message") == "${missing_variable}"

    def test_missing_variable_raises_in_strict_mode(self):
        """Test that unresolved templates raise ValueError in strict mode.

        In strict mode (the default), when a template variable cannot be resolved,
        a ValueError is raised with a helpful error message.
        """
        params = {"message": "${missing_variable}"}
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)
        template_config = TemplateConfig(
            template_params=template_params,
            static_params=static_params,
            expected_types=expected_types,
            resolution_mode="strict",
        )

        # Run with empty shared store — should raise ValueError in strict mode
        shared: dict = {}
        with pytest.raises(ValueError) as exc_info:
            resolve_templates(template_config, shared, "test-node")

        # Verify error message contains helpful debugging info
        error_msg = str(exc_info.value)
        assert "missing_variable" in error_msg

    def test_null_value_type_preservation(self):
        """Test that different types including None are preserved correctly in resolved_defaults."""
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
        workflow = compile_workflow(workflow_ir, registry, initial_params={})

        # Check type preservation in resolved_defaults
        resolved_defaults = workflow.resolved_defaults
        assert resolved_defaults["null_input"] is None
        assert resolved_defaults["string_input"] == "test"
        assert resolved_defaults["number_input"] == 42
        assert resolved_defaults["bool_input"] is True

    def test_override_null_default_with_provided_value(self):
        """Test that provided values override null defaults.

        User-provided initial_params are seeded into the shared store at run()
        time, alongside (and overriding) resolved_defaults.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo ${input_value}"}}],
            "edges": [],
            "inputs": {"input_value": {"description": "Test input", "required": False, "default": None}},
        }

        registry = Registry()
        initial_params = {"input_value": "provided value"}

        # Provide a value that overrides the null default
        workflow = compile_workflow(workflow_ir, registry, initial_params=initial_params)

        # The resolved_defaults should NOT contain input_value because it was provided.
        # (prepare_inputs only adds defaults for MISSING optional inputs.)
        resolved_defaults = workflow.resolved_defaults
        assert "input_value" not in resolved_defaults

        # The provided value is in initial_params for seeding into shared store.
        # After compile_workflow, initial_params retains user-provided values.
        assert initial_params["input_value"] == "provided value"

    def test_shared_store_receives_defaults(self):
        """Test that values in shared store are used for template resolution.

        resolved_defaults are seeded into the shared store at run() time.
        The shared store is the single source of runtime data.
        """
        params = {"greeting": "${name}"}
        expected_types = build_type_cache(None)
        template_params, static_params = split_params(params, expected_types)
        template_config = TemplateConfig(
            template_params=template_params,
            static_params=static_params,
            expected_types=expected_types,
            resolution_mode="strict",
        )

        # Seed the value into shared store (as the engine does at run time)
        shared: dict = {"name": "world"}
        merged_params, _last_resolutions, template_errors = resolve_templates(template_config, shared, "test-node")

        assert template_errors == []
        assert merged_params["greeting"] == "world"

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
        workflow = compile_workflow(workflow_ir, registry, initial_params={})

        resolved_defaults = workflow.resolved_defaults
        assert resolved_defaults["input1"] is None  # explicit null default
        assert resolved_defaults["input2"] == ""  # empty string default
        assert resolved_defaults["input3"] is None  # implicit None (no default specified)

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
        workflow = compile_workflow(workflow_ir, registry, initial_params={})

        resolved_defaults = workflow.resolved_defaults
        assert "optional_param" in resolved_defaults
        assert resolved_defaults["optional_param"] is None

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
        initial_params = {"optional_param": "user_provided"}

        # Provide a value for the optional input
        workflow = compile_workflow(workflow_ir, registry, initial_params=initial_params)

        # When user provides a value, it should NOT appear in resolved_defaults
        # (prepare_inputs only adds defaults for missing inputs)
        resolved_defaults = workflow.resolved_defaults
        assert "optional_param" not in resolved_defaults

        # The provided value is in initial_params for seeding into shared store
        assert initial_params["optional_param"] == "user_provided"

    def test_nested_path_on_none_optional_input_fails_gracefully(self):
        """Test that nested path access on None-valued optional input fails with clear error.

        When an optional input without default resolves to None, attempting to access
        nested paths like ${optional_param.field} should fail with an informative error,
        not silently pass or crash.

        This is the expected behavior: you can't access .field on None.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {
                        "stdin": "${optional_config.api_key}",
                        "command": "cat",
                    },
                }
            ],
            "edges": [],
            "inputs": {
                "optional_config": {
                    "type": "object",
                    "required": False,
                    # No default - will resolve to None
                },
            },
        }

        registry = Registry()

        # Compilation should succeed - the input is optional
        workflow = compile_workflow(workflow_ir, registry, initial_params={})

        # But execution should fail because we can't access .api_key on None
        # This is correct behavior - nested path on None is an error
        shared = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        with pytest.raises(ValueError, match="optional_config"):
            engine.run(workflow, shared)

    def test_nested_path_on_provided_optional_input_succeeds(self):
        """Test that nested path access works when optional input is provided."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "test",
                    "type": "shell",
                    "params": {
                        "stdin": "${optional_config.api_key}",
                        "command": "cat",
                    },
                }
            ],
            "edges": [],
            "inputs": {
                "optional_config": {
                    "type": "object",
                    "required": False,
                },
            },
        }

        registry = Registry()
        initial_params = {"optional_config": {"api_key": "secret123"}}

        # Provide the optional input with nested structure
        workflow = compile_workflow(workflow_ir, registry, initial_params=initial_params)

        # Seed shared store: initial_params (skip __ keys) then resolved_defaults
        shared: dict = {}
        shared.update({k: v for k, v in initial_params.items() if not k.startswith("__")})
        shared.update(workflow.resolved_defaults)

        # Execution should succeed
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # Verify the nested value was resolved
        assert shared.get("test", {}).get("stdout", "").strip() == "secret123"
