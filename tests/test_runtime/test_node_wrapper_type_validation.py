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

    def test_string_param_receives_dict_raises_error(self):
        """String parameter receiving dict should raise ValueError in strict mode."""
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

        # Should raise ValueError with enhanced message
        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        # Verify error message has all components
        assert "prompt" in error_msg
        assert "expects str but received dict" in error_msg
        assert "💡 Common fixes:" in error_msg
        assert '"${data}"' in error_msg  # Quoted fix shown

    def test_string_param_receives_list_raises_error(self):
        """String parameter receiving list should raise ValueError in strict mode."""
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

        # Should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "expects str but received list" in error_msg
        assert "contains 3 items" in error_msg

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

    def test_permissive_mode_stores_warning_not_error(self):
        """Permissive mode should store warning in __template_errors__ instead of raising."""
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

        # Should not raise error - permissive mode continues
        result = wrapper._run(shared)
        assert result == "default"

        # Should store error in shared["__template_errors__"]
        assert "__template_errors__" in shared
        assert "test-node" in shared["__template_errors__"]
        assert "type_validation" in shared["__template_errors__"]["test-node"]["type"]

    def test_permissive_mode_continues_execution(self):
        """Permissive mode should continue execution after type error."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "text", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
            template_resolution_mode="permissive",
            interface_metadata=interface_metadata,
        )

        # Set template that resolves to dict
        wrapper.set_params({"text": "${response}"})

        # Execute
        shared = {"response": {"data": "test"}}
        result = wrapper._run(shared)

        # Should execute successfully despite type mismatch
        assert result == "default"
        # Node should receive the dict (permissive allows it)
        assert node.params_at_execution["text"] == {"data": "test"}


class TestErrorMessages:
    """Test error message formatting."""

    def test_error_shows_parameter_name(self):
        """Error message should include parameter name."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"prompt": "${data}"})
        shared = {"data": {"key": "value"}}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        assert "Parameter 'prompt'" in str(exc_info.value)

    def test_error_shows_template_used(self):
        """Error message should show the template that resolved."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "message", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"message": "${response}"})
        shared = {"response": {"status": "ok"}}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        assert "Template used: ${response}" in str(exc_info.value)

    def test_error_shows_fix_suggestions(self):
        """Error message should provide 3 fix suggestions."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "text", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"text": "${data}"})
        shared = {"data": {"field": "value"}}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "💡 Common fixes:" in error_msg
        assert "1. Serialize to JSON" in error_msg
        assert "2. Access a specific field" in error_msg
        assert "3. Combine with text" in error_msg

    def test_error_shows_available_fields_for_dict(self):
        """For dict values, error should list available fields."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "prompt", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"prompt": "${response}"})
        shared = {"response": {"status": "ok", "data": "test", "code": 200}}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "Available fields in response:" in error_msg
        assert "- status" in error_msg
        assert "- data" in error_msg
        assert "- code" in error_msg

    def test_error_shows_item_count_for_list(self):
        """For list values, error should show item count."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "summary", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"summary": "${items}"})
        shared = {"items": ["a", "b", "c", "d", "e"]}

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        error_msg = str(exc_info.value)
        assert "contains 5 items" in error_msg
        assert "${items[0]}" in error_msg


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

    def test_empty_dict_value(self):
        """Empty dict should still trigger validation."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "text", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"text": "${data}"})
        shared = {"data": {}}  # Empty dict

        # Should raise ValueError even for empty dict
        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        assert "expects str but received dict" in str(exc_info.value)

    def test_empty_list_value(self):
        """Empty list should still trigger validation."""
        node = DummyNode()
        interface_metadata = {"inputs": [{"key": "message", "type": "str"}], "params": []}
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={}, interface_metadata=interface_metadata)

        wrapper.set_params({"message": "${items}"})
        shared = {"items": []}  # Empty list

        # Should raise ValueError even for empty list
        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared)

        assert "expects str but received list" in str(exc_info.value)


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
