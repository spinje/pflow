"""Tests for template-aware node wrapper."""

from unittest.mock import Mock

import pytest

from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper
from pocketflow import Node


class WrapperTestNode(Node):
    """Simple test node for wrapper testing."""

    def __init__(self):
        super().__init__()
        self.prep_called = False
        self.exec_called = False
        self.post_called = False

    def prep(self, shared):
        self.prep_called = True
        return {"prep_data": "test"}

    def exec(self, prep_res):
        self.exec_called = True
        return f"Executed with params: {self.params}"

    def post(self, shared, prep_res, exec_res):
        self.post_called = True
        shared["result"] = exec_res
        return "default"


class TestWrapperInitialization:
    """Test wrapper initialization and setup."""

    def test_basic_initialization(self):
        """Test basic wrapper initialization."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        assert wrapper.inner_node is node
        assert wrapper.node_id == "test_node"
        assert wrapper.initial_params == {}
        assert wrapper.template_params == {}
        assert wrapper.static_params == {}

    def test_initialization_with_initial_params(self):
        """Test initialization with initial parameters."""
        node = WrapperTestNode()
        initial_params = {"url": "https://example.com", "count": 5}
        wrapper = TemplateAwareNodeWrapper(node, "test_node", initial_params)

        assert wrapper.initial_params == initial_params


class TestParameterSeparation:
    """Test separation of template and static parameters."""

    def test_separates_template_params(self):
        """Test that params with templates are separated."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        params = {"url": "${endpoint}", "format": "json", "message": "Processing ${count} items"}

        wrapper.set_params(params)

        assert wrapper.template_params == {"url": "${endpoint}", "message": "Processing ${count} items"}
        assert wrapper.static_params == {"format": "json"}

        # Inner node should only have static params initially
        assert node.params == {"format": "json"}

    def test_all_static_params(self):
        """Test handling when all params are static."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        params = {"format": "json", "count": 10, "enabled": True}
        wrapper.set_params(params)

        assert wrapper.template_params == {}
        assert wrapper.static_params == params
        assert node.params == params

    def test_all_template_params(self):
        """Test handling when all params have templates."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        params = {"url": "${endpoint}", "token": "${auth_token}", "id": "${item_id}"}
        wrapper.set_params(params)

        assert wrapper.template_params == params
        assert wrapper.static_params == {}
        assert node.params == {}

    def test_updates_params_on_subsequent_calls(self):
        """Test that set_params updates parameters correctly."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        # First set
        wrapper.set_params({"a": "${var1}", "b": "static1"})
        assert wrapper.template_params == {"a": "${var1}"}
        assert wrapper.static_params == {"b": "static1"}

        # Second set (should replace)
        wrapper.set_params({"c": "${var2}", "d": "static2"})
        assert wrapper.template_params == {"c": "${var2}"}
        assert wrapper.static_params == {"d": "static2"}


class TestTemplateResolution:
    """Test template resolution during execution."""

    def test_no_templates_bypasses_resolution(self):
        """Test that execution without templates bypasses resolution."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        # Set only static params
        wrapper.set_params({"format": "json", "count": 10})

        shared = {"some_data": "value"}
        result = wrapper._run(shared)

        assert node.prep_called
        assert node.exec_called
        assert node.post_called
        assert result == "default"  # post() returns "default"
        assert "Executed with params: {'format': 'json', 'count': 10}" in shared["result"]

    def test_resolves_simple_templates(self):
        """Test resolution of simple template variables."""
        node = WrapperTestNode()
        initial_params = {"endpoint": "https://api.example.com"}
        wrapper = TemplateAwareNodeWrapper(node, "test_node", initial_params)

        wrapper.set_params({"url": "${endpoint}", "format": "json"})

        shared = {}
        result = wrapper._run(shared)

        # Check that params were resolved during execution
        expected_params = "{'format': 'json', 'url': 'https://api.example.com'}"
        assert result == "default"
        assert expected_params in shared["result"]

    def test_shared_store_resolution(self):
        """Test resolution from shared store."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        wrapper.set_params({"message": "Processing ${item_name}"})

        shared = {"item_name": "Document.pdf"}
        result = wrapper._run(shared)

        assert result == "default"
        assert "'message': 'Processing Document.pdf'" in shared["result"]

    def test_priority_initial_over_shared(self):
        """Test that initial params have priority over shared store."""
        node = WrapperTestNode()
        initial_params = {"count": "100"}  # From planner
        wrapper = TemplateAwareNodeWrapper(node, "test_node", initial_params)

        wrapper.set_params({"message": "Count: ${count}"})

        shared = {"count": "50"}  # Different value in shared
        result = wrapper._run(shared)

        # Should use initial_params value (100), not shared (50)
        assert result == "default"
        assert "'message': 'Count: 100'" in shared["result"]

    def test_path_resolution(self):
        """Test resolution of nested paths."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        wrapper.set_params({"title": "${video.title}", "author": "${video.metadata.author}"})

        shared = {"video": {"title": "Python Tutorial", "metadata": {"author": "TechTeacher", "duration": 3600}}}

        result = wrapper._run(shared)

        assert result == "default"
        assert "'title': 'Python Tutorial'" in shared["result"]
        assert "'author': 'TechTeacher'" in shared["result"]

    def test_unresolved_templates_raise_error(self):
        """Test that unresolved templates raise ValueError (Issue #95 fix).

        This test was updated as part of Task 85 (Runtime Template Resolution Hardening).
        Previously, unresolved templates were left as-is for "debugging visibility",
        which caused literal ${...} text to propagate to production (e.g., Slack messages).

        Now, unresolved templates correctly raise ValueError to prevent data corruption.
        """
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        wrapper.set_params({"found": "${existing}", "missing": "${undefined}"})

        shared = {"existing": "value"}

        # Should raise ValueError because ${undefined} cannot be resolved
        with pytest.raises(ValueError, match="Unresolved variables"):
            wrapper._run(shared)

    def test_params_restored_after_execution(self):
        """Test that original params are restored after execution."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node", {"var": "resolved"})

        wrapper.set_params({"param": "${var}"})

        # Check initial state
        assert node.params == {}

        # Run with resolution
        shared = {}
        wrapper._run(shared)

        # After execution, params should be restored (though node copy is discarded)
        assert node.params == {}


class TestAttributeDelegation:
    """Test attribute delegation to inner node."""

    def test_getattr_delegation(self):
        """Test that attribute access is delegated to inner node."""
        node = WrapperTestNode()
        node.custom_attr = "test_value"
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        # Access custom attribute through wrapper
        assert wrapper.custom_attr == "test_value"

        # Access node methods
        assert hasattr(wrapper, "prep")
        assert hasattr(wrapper, "exec")
        assert hasattr(wrapper, "post")

    def test_setattr_delegation(self):
        """Test that attribute setting is delegated correctly."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        # Set attribute through wrapper
        wrapper.custom_value = 42
        assert node.custom_value == 42

        # Wrapper's own attributes should not be delegated
        wrapper.initial_params = {"test": "value"}
        assert not hasattr(node, "initial_params")

    def test_wrapper_transparency(self):
        """Test that wrapper is transparent to PocketFlow."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        # Wrapper should look like a Node to PocketFlow
        assert hasattr(wrapper, "set_params")
        assert hasattr(wrapper, "_run")
        assert hasattr(wrapper, "prep")
        assert hasattr(wrapper, "exec")
        assert hasattr(wrapper, "post")

        # Should be able to set successors
        mock_successor = Mock()
        wrapper.successors = {"default": mock_successor}
        assert node.successors["default"] is mock_successor


class TestComplexScenarios:
    """Test complex real-world scenarios."""

    def test_multiple_template_resolution(self):
        """Test resolution of multiple templates in one parameter."""
        node = WrapperTestNode()
        initial_params = {"repo": "pflow", "issue": "123"}
        wrapper = TemplateAwareNodeWrapper(node, "github_node", initial_params)

        wrapper.set_params({
            "message": "Working on ${repo} issue #${issue}",
            "url": "https://github.com/${repo}/issues/${issue}",
        })

        shared = {"status": "in_progress"}  # Additional shared data
        result = wrapper._run(shared)

        assert result == "default"
        assert "'message': 'Working on pflow issue #123'" in shared["result"]
        assert "'url': 'https://github.com/pflow/issues/123'" in shared["result"]

    def test_complete_vs_embedded_templates(self):
        """Test that complete value templates work same as embedded."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test", {"video_id": "xyz123"})

        wrapper.set_params({
            "id": "${video_id}",  # Complete value
            "message": "Processing video ${video_id}",  # Embedded in string
        })

        shared = {}
        result = wrapper._run(shared)

        # Both forms should resolve identically
        assert result == "default"
        assert "'id': 'xyz123'" in shared["result"]
        assert "'message': 'Processing video xyz123'" in shared["result"]

    def test_type_conversion_in_templates(self):
        """Test type conversion during template resolution."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test")

        wrapper.set_params({"none_val": "Value: ${none}", "zero_val": "Count: ${zero}", "bool_val": "Flag: ${flag}"})

        shared = {"none": None, "zero": 0, "flag": False}

        result = wrapper._run(shared)

        assert result == "default"
        assert "'none_val': 'Value: '" in shared["result"]  # None -> ""
        assert "'zero_val': 'Count: 0'" in shared["result"]
        assert "'bool_val': 'Flag: False'" in shared["result"]


class TestErrorHandling:
    """Test error handling in the wrapper."""

    def test_node_execution_error_propagates(self):
        """Test that node execution errors propagate through wrapper."""
        node = WrapperTestNode()

        # Make node raise an error
        def failing_exec(prep_res):
            raise ValueError("Node execution failed")

        node.exec = failing_exec

        wrapper = TemplateAwareNodeWrapper(node, "test_node")
        wrapper.set_params({"param": "value"})

        shared = {}
        with pytest.raises(ValueError, match="Node execution failed"):
            wrapper._run(shared)

    def test_handles_non_string_param_values(self):
        """Test handling of non-string parameter values."""
        node = WrapperTestNode()
        wrapper = TemplateAwareNodeWrapper(node, "test_node")

        # Mix of types including non-strings
        params = {"string": "${var}", "number": 42, "boolean": True, "list": [1, 2, 3], "dict": {"key": "value"}}

        wrapper.set_params(params)

        # Only string should be in template_params
        assert wrapper.template_params == {"string": "${var}"}
        assert len(wrapper.static_params) == 4
