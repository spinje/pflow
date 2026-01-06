"""Tests for type validation in TemplateAwareNodeWrapper.

These tests verify that template resolution validates resolved types
against expected parameter types from node metadata.
"""

import pytest

from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper


class DummyNode:
    """Minimal node for testing template resolution and type validation."""

    def __init__(self):
        self.params = {}
        self.params_at_execution = {}

    def set_params(self, params):
        self.params = params

    def _run(self, shared):
        # Capture params at execution time (before wrapper restores them)
        self.params_at_execution = dict(self.params)
        return "default"


class TestBasicTypeValidation:
    """Test basic type validation logic."""

    def test_string_param_receives_string_no_error(self):
        """String parameter receiving string value should not raise error."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="strict",
            interface_metadata=interface_metadata,
        )

        # Set template param that will resolve to string
        wrapper.set_params({"prompt": "${message}"})

        # Execute with string in shared store
        shared = {"message": "Hello, World!"}

        # Should not raise error
        result = wrapper._run(shared)
        assert result == "default"
        assert node.params_at_execution["prompt"] == "Hello, World!"

    def test_string_param_receives_dict_gets_coerced(self):
        """String parameter receiving dict should be coerced to JSON string."""
        import json

        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="strict",
            interface_metadata=interface_metadata,
        )

        # Set template param that will resolve to dict
        wrapper.set_params({"prompt": "${data}"})

        # Execute with dict in shared store
        shared = {"data": {"status": "ok", "result": "test"}}

        # Should NOT raise - dict gets coerced to JSON string
        result = wrapper._run(shared)
        assert result == "default"

        # Verify the dict was serialized to JSON string
        prompt_value = node.params_at_execution["prompt"]
        assert isinstance(prompt_value, str)
        assert json.loads(prompt_value) == {"status": "ok", "result": "test"}

    def test_string_param_receives_list_gets_coerced(self):
        """String parameter receiving list should be coerced to JSON string."""
        import json

        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="strict",
            interface_metadata=interface_metadata,
        )

        # Set template param that will resolve to list
        wrapper.set_params({"prompt": "${items}"})

        # Execute with list in shared store
        shared = {"items": ["item1", "item2", "item3"]}

        # Should NOT raise - list gets coerced to JSON string
        result = wrapper._run(shared)
        assert result == "default"

        # Verify the list was serialized to JSON string
        prompt_value = node.params_at_execution["prompt"]
        assert isinstance(prompt_value, str)
        assert json.loads(prompt_value) == ["item1", "item2", "item3"]

    def test_any_param_receives_dict_no_error(self):
        """'any' type parameter should accept dict without error."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "data", "type": "any"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="strict",
            interface_metadata=interface_metadata,
        )

        # Set template param that will resolve to dict
        wrapper.set_params({"data": "${response}"})

        # Execute with dict in shared store
        shared = {"response": {"status": "ok"}}

        # Should not raise error (any type accepts anything)
        result = wrapper._run(shared)
        assert result == "default"
        assert node.params_at_execution["data"] == {"status": "ok"}

    def test_dict_param_receives_dict_no_error(self):
        """'dict' type parameter should accept dict without error."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "config", "type": "dict"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="strict",
            interface_metadata=interface_metadata,
        )

        # Set template param that will resolve to dict
        wrapper.set_params({"config": "${settings}"})

        # Execute with dict in shared store
        shared = {"settings": {"timeout": 30}}

        # Should not raise error
        result = wrapper._run(shared)
        assert result == "default"
        assert node.params_at_execution["config"] == {"timeout": 30}

    def test_list_param_receives_list_no_error(self):
        """'list' type parameter should accept list without error."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "items", "type": "list"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="strict",
            interface_metadata=interface_metadata,
        )

        # Set template param that will resolve to list
        wrapper.set_params({"items": "${data}"})

        # Execute with list in shared store
        shared = {"data": [1, 2, 3]}

        # Should not raise error
        result = wrapper._run(shared)
        assert result == "default"
        assert node.params_at_execution["items"] == [1, 2, 3]


class TestComplexTemplates:
    """Test that complex templates skip validation (already stringified)."""

    def test_complex_template_with_dict_no_validation(self):
        """Complex template like 'text ${var}' is already string, no validation needed."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="strict",
            interface_metadata=interface_metadata,
        )

        # Set complex template (will be stringified)
        wrapper.set_params({"prompt": "Status: ${response}"})

        # Execute with dict in shared store
        shared = {"response": {"status": "ok"}}

        # Should not raise error - complex template serializes to JSON
        result = wrapper._run(shared)
        assert result == "default"
        # Complex template should serialize dict to JSON
        assert "status" in node.params_at_execution["prompt"]


class TestPermissiveMode:
    """Test permissive mode behavior."""

    def test_permissive_mode_coerces_dict_to_str(self):
        """Permissive mode should coerce dict to str without storing warning."""
        import json

        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="permissive",  # Permissive mode
            interface_metadata=interface_metadata,
        )

        # Set template param that will resolve to dict
        wrapper.set_params({"prompt": "${data}"})

        # Execute with dict in shared store
        shared = {"data": {"status": "ok"}}

        # Should not raise error - dict gets coerced to JSON string
        result = wrapper._run(shared)
        assert result == "default"

        # No template errors stored (coercion is silent)
        assert "__template_errors__" not in shared or "test-node" not in shared.get("__template_errors__", {})

        # Verify coercion happened
        assert isinstance(node.params_at_execution["prompt"], str)
        assert json.loads(node.params_at_execution["prompt"]) == {"status": "ok"}

    def test_permissive_mode_coerces_list_to_str(self):
        """Permissive mode should coerce list to str without storing warning."""
        import json

        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "text", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="permissive",
            interface_metadata=interface_metadata,
        )

        # Set template that resolves to list
        wrapper.set_params({"text": "${response}"})

        # Execute
        shared = {"response": ["a", "b", "c"]}
        result = wrapper._run(shared)

        # Should execute successfully with coerced value
        assert result == "default"
        # Node should receive JSON string, not list
        assert isinstance(node.params_at_execution["text"], str)
        assert json.loads(node.params_at_execution["text"]) == ["a", "b", "c"]


class TestErrorMessages:
    """Test error message formatting for type mismatches that still raise errors.

    Note: dict/list → str is now auto-coerced (not an error).
    These tests verify error messages for other type mismatches.
    """

    def test_error_for_malformed_json_when_dict_expected(self):
        """Malformed JSON → dict should raise clear error."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "config", "type": "dict"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"config": "${data}"})
        # String that looks like JSON but is malformed
        shared = {"data": "{invalid json}"}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "Parameter 'config'" in error_msg
        assert "malformed JSON" in error_msg

    def test_error_for_malformed_json_when_list_expected(self):
        """Malformed JSON → list should raise clear error."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "items", "type": "list"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"items": "${data}"})
        # String that looks like JSON array but is malformed
        shared = {"data": "[invalid json]"}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "Parameter 'items'" in error_msg
        assert "malformed JSON" in error_msg

    def test_dict_to_str_no_longer_errors(self):
        """Verify that dict → str is now coerced, not an error."""
        import json

        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"prompt": "${data}"})
        shared = {"data": {"key": "value"}}

        # Should NOT raise - gets coerced to JSON string
        result = wrapper._run(shared)
        assert result == "default"
        assert isinstance(node.params_at_execution["prompt"], str)
        assert json.loads(node.params_at_execution["prompt"]) == {"key": "value"}

    def test_list_to_str_no_longer_errors(self):
        """Verify that list → str is now coerced, not an error."""
        import json

        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "summary", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"summary": "${items}"})
        shared = {"items": ["a", "b", "c"]}

        # Should NOT raise - gets coerced to JSON string
        result = wrapper._run(shared)
        assert result == "default"
        assert isinstance(node.params_at_execution["summary"], str)
        assert json.loads(node.params_at_execution["summary"]) == ["a", "b", "c"]


class TestEdgeCases:
    """Test edge cases and graceful degradation."""

    def test_no_metadata_skips_validation(self):
        """When no metadata available, validation should be skipped."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="strict",
            interface_metadata=None,  # No metadata
        )

        # Set template that resolves to dict
        wrapper.set_params({"prompt": "${data}"})
        shared = {"data": {"key": "value"}}

        # Should not raise error - no metadata means no validation
        result = wrapper._run(shared)
        assert result == "default"

    def test_incomplete_metadata_skips_validation(self):
        """When metadata missing type info, validation should be skipped."""
        node = DummyNode()
        # Metadata without type information
        interface_metadata = {"inputs": [{"key": "prompt"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="strict",
            interface_metadata=interface_metadata,
        )

        # Set template that resolves to dict
        wrapper.set_params({"prompt": "${data}"})
        shared = {"data": {"key": "value"}}

        # Should not raise error - missing type info means skip validation
        result = wrapper._run(shared)
        assert result == "default"

    def test_empty_dict_coerced_to_empty_json_object(self):
        """Empty dict should be coerced to '{}'."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "text", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"text": "${data}"})
        shared = {"data": {}}  # Empty dict

        # Should NOT raise - empty dict coerced to "{}"
        result = wrapper._run(shared)
        assert result == "default"
        assert node.params_at_execution["text"] == "{}"

    def test_empty_list_coerced_to_empty_json_array(self):
        """Empty list should be coerced to '[]'."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "message", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"message": "${items}"})
        shared = {"items": []}  # Empty list

        # Should NOT raise - empty list coerced to "[]"
        result = wrapper._run(shared)
        assert result == "default"
        assert node.params_at_execution["message"] == "[]"


class TestPerformance:
    """Test performance characteristics."""

    def test_type_cache_built_once(self):
        """Type cache should be built during __init__, not per resolution."""
        node = DummyNode()
        interface_metadata = {
            "inputs": [
                {"key": "prompt", "type": "str"},
                {"key": "system", "type": "str"},
                {"key": "images", "type": "list[str]"},
            ],
            "params": [{"key": "model", "type": "str"}, {"key": "temperature", "type": "float"}],
        }

        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        # Type cache should be built
        assert hasattr(wrapper, "_expected_types")
        assert len(wrapper._expected_types) == 5
        assert wrapper._expected_types["prompt"] == "str"
        assert wrapper._expected_types["model"] == "str"
        assert wrapper._expected_types["images"] == "list[str]"

        # Cache should persist across multiple executions
        wrapper.set_params({"prompt": "${msg}"})
        shared1 = {"msg": "Hello"}
        wrapper._run(shared1)

        # Same cache instance
        cache_id = id(wrapper._expected_types)

        wrapper.set_params({"prompt": "${msg2}"})
        shared2 = {"msg2": "World"}
        wrapper._run(shared2)

        # Cache should be the same object (not rebuilt)
        assert id(wrapper._expected_types) == cache_id
