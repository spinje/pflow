"""Test template validation in TemplateAwareNodeWrapper.

This test suite verifies the fix for Issue #95 where simple templates
(like ${var}) were skipping error validation, allowing literal template
text to propagate to node execution.
"""

import pytest

from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper


class DummyNode:
    """Minimal node for testing template resolution."""

    def __init__(self):
        self.params = {}
        self.params_at_execution = {}  # Capture params when _run is called

    def set_params(self, params):
        self.params = params

    def _run(self, shared):
        # Capture params at execution time (before wrapper restores them)
        self.params_at_execution = dict(self.params)
        return "default"


class TestSimpleTemplateValidation:
    """Test that simple templates are validated (bug fix for Issue #95)."""

    def test_simple_template_missing_variable_raises_error(self):
        """Simple template with missing variable should raise ValueError.

        This is the PRIMARY bug fix test. Previously, simple templates like
        ${missing_variable} would skip error checking and be passed literally
        to nodes, causing broken data in production (literal "${...}" in Slack
        messages, etc.).

        After fix: ValueError should be raised immediately.
        """
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
        )

        # Set parameter with unresolvable simple template
        wrapper.set_params({"prompt": "${missing_variable}"})

        # Execute should raise ValueError with clear message
        with pytest.raises(ValueError, match="Unresolved variables"):
            wrapper._run(shared={})

    def test_simple_template_missing_variable_error_message(self):
        """Error message should be clear and actionable."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})
        wrapper.set_params({"prompt": "${missing_variable}"})

        with pytest.raises(ValueError) as exc_info:
            wrapper._run(shared={})

        error_msg = str(exc_info.value)
        # Check essential error message components (simplified format)
        assert "prompt" in error_msg  # Parameter name
        assert "${missing_variable}" in error_msg  # Variable name
        assert "Unresolved variables" in error_msg  # Error type is clear
        # Note: "Node ID" and "Available context keys: (none)" removed as redundant/unclear

    def test_simple_template_existing_variable_resolves(self):
        """Simple template with existing variable should resolve correctly."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={},
        )

        wrapper.set_params({"prompt": "${data}"})

        # Execute with context containing the variable
        result = wrapper._run(shared={"data": "resolved value"})

        # Should execute successfully
        assert node.params_at_execution["prompt"] == "resolved value"
        assert result == "default"

    def test_simple_template_type_preservation(self):
        """Simple templates should preserve original type (not convert to string)."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        # Integer
        wrapper.set_params({"count": "${total}"})
        wrapper._run(shared={"total": 42})
        assert node.params_at_execution["count"] == 42
        assert isinstance(node.params_at_execution["count"], int)

        # Boolean
        wrapper.set_params({"enabled": "${flag}"})
        wrapper._run(shared={"flag": True})
        assert node.params_at_execution["enabled"] is True
        assert isinstance(node.params_at_execution["enabled"], bool)

        # Dict
        wrapper.set_params({"data": "${config}"})
        wrapper._run(shared={"config": {"key": "value"}})
        assert node.params_at_execution["data"] == {"key": "value"}
        assert isinstance(node.params_at_execution["data"], dict)

        # List
        wrapper.set_params({"items": "${list}"})
        wrapper._run(shared={"list": [1, 2, 3]})
        assert node.params_at_execution["items"] == [1, 2, 3]
        assert isinstance(node.params_at_execution["items"], list)

    def test_simple_template_from_initial_params(self):
        """Templates should resolve from initial_params (planner extraction)."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={"issue_number": "123"},  # From planner
        )

        wrapper.set_params({"issue": "${issue_number}"})

        # Execute with empty shared store - should still resolve
        result = wrapper._run(shared={})

        assert node.params_at_execution["issue"] == "123"
        assert result == "default"

    def test_simple_template_initial_params_priority(self):
        """initial_params should have priority over shared store."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(
            node,
            "test-node",
            initial_params={"data": "from_planner"},
        )

        wrapper.set_params({"field": "${data}"})

        # Execute with conflicting shared store value
        wrapper._run(shared={"data": "from_shared_store"})

        # Should use initial_params value (higher priority)
        assert node.params_at_execution["field"] == "from_planner"


class TestComplexTemplateValidation:
    """Test complex templates (with text around variables) still work correctly."""

    def test_complex_template_missing_variable_raises_error(self):
        """Complex template with missing variable should raise ValueError.

        This already worked before the bug fix, but we verify it still works.
        """
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"prompt": "Hello ${missing_variable}!"})

        with pytest.raises(ValueError, match="Unresolved variables"):
            wrapper._run(shared={})

    def test_complex_template_existing_variable_resolves(self):
        """Complex template with existing variable should resolve to string."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"prompt": "Hello ${name}!"})

        wrapper._run(shared={"name": "World"})

        # Should resolve to complete string
        assert node.params_at_execution["prompt"] == "Hello World!"
        assert isinstance(node.params_at_execution["prompt"], str)

    def test_complex_template_type_coercion(self):
        """Complex templates always produce strings, even from non-string values."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        # Integer in template
        wrapper.set_params({"message": "Count: ${count}"})
        wrapper._run(shared={"count": 42})
        assert node.params_at_execution["message"] == "Count: 42"
        assert isinstance(node.params_at_execution["message"], str)

        # Dict in template (should JSON serialize)
        wrapper.set_params({"message": "Data: ${config}"})
        wrapper._run(shared={"config": {"key": "value"}})
        assert "Data: {" in node.params_at_execution["message"]
        assert isinstance(node.params_at_execution["message"], str)


class TestNestedStructureTemplates:
    """Test templates in nested dicts and lists."""

    def test_dict_with_simple_template_missing_variable(self):
        """Dict containing simple template with missing variable should raise."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({
            "config": {
                "url": "${base_url}",
                "port": 8080,
            }
        })

        with pytest.raises(ValueError, match="Unresolved variables"):
            wrapper._run(shared={})

    def test_dict_with_simple_template_resolves(self):
        """Dict containing simple template should resolve correctly."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({
            "config": {
                "url": "${base_url}",
                "port": 8080,
            }
        })

        wrapper._run(shared={"base_url": "https://api.example.com"})

        assert node.params_at_execution["config"]["url"] == "https://api.example.com"
        assert node.params_at_execution["config"]["port"] == 8080

    def test_list_with_simple_template_missing_variable(self):
        """List containing simple template with missing variable should raise."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"args": ["echo", "${message}"]})

        with pytest.raises(ValueError, match="Unresolved variables"):
            wrapper._run(shared={})

    def test_list_with_simple_template_resolves(self):
        """List containing simple template should resolve correctly."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"args": ["echo", "${message}"]})

        wrapper._run(shared={"message": "Hello World"})

        assert node.params_at_execution["args"] == ["echo", "Hello World"]


class TestPathTemplates:
    """Test templates with path access (dot notation and array indices)."""

    def test_simple_path_template_missing_path(self):
        """Path template with non-existent path should raise ValueError."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"field": "${data.missing.path}"})

        with pytest.raises(ValueError, match="Unresolved variables"):
            wrapper._run(shared={"data": {"existing": "value"}})

    def test_simple_path_template_resolves(self):
        """Path template should resolve through nested structure."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"field": "${user.profile.name}"})

        wrapper._run(shared={"user": {"profile": {"name": "Alice"}}})

        assert node.params_at_execution["field"] == "Alice"

    def test_array_index_template_missing_index(self):
        """Array index template with out-of-bounds index should raise."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"field": "${items[5]}"})

        with pytest.raises(ValueError, match="Unresolved variables"):
            wrapper._run(shared={"items": [1, 2, 3]})

    def test_array_index_template_resolves(self):
        """Array index template should resolve to array element."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"field": "${items[1]}"})

        wrapper._run(shared={"items": ["first", "second", "third"]})

        assert node.params_at_execution["field"] == "second"

    def test_combined_path_and_array_template(self):
        """Combined path and array access should work."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"field": "${users[0].profile.email}"})

        wrapper._run(shared={"users": [{"profile": {"email": "alice@example.com"}}]})

        assert node.params_at_execution["field"] == "alice@example.com"


class TestMultipleTemplatesInParameter:
    """Test parameters with multiple template variables."""

    def test_multiple_templates_one_missing(self):
        """If any template in parameter is missing, should raise ValueError."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"message": "User ${name} has ${missing_count} items"})

        with pytest.raises(ValueError, match="Unresolved variables"):
            wrapper._run(shared={"name": "Alice"})

    def test_multiple_templates_all_resolved(self):
        """Multiple templates in one parameter should all resolve."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"message": "User ${name} has ${count} items"})

        wrapper._run(shared={"name": "Alice", "count": 5})

        assert node.params_at_execution["message"] == "User Alice has 5 items"

    def test_no_false_positive_on_mcp_data(self):
        """Resolved data containing ${...} should not trigger false positives."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        # Simulate MCP response that contains ${OLD_VAR} in its data
        mcp_result = {"message": "The old format used ${OLD_VAR} syntax"}
        wrapper.set_params({"data": "${mcp.result}"})

        # Execute with MCP data that contains ${...} text
        wrapper._run(shared={"mcp": {"result": mcp_result}})

        # Should NOT raise error - the ${OLD_VAR} is part of resolved data, not a template
        assert node.params_at_execution["data"] == mcp_result

    def test_partial_resolution_with_three_variables(self):
        """Test partial resolution detection with 3+ variables."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        # Three variables, only two resolve
        wrapper.set_params({"message": "${greeting} ${name}, you have ${count} items"})

        with pytest.raises(ValueError, match="Unresolved variables"):
            wrapper._run(shared={"greeting": "Hello", "name": "Alice"})

    def test_similar_variable_names_no_confusion(self):
        """Variables with similar names should be handled correctly."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        # user resolves, username doesn't - should detect username is missing
        wrapper.set_params({"message": "User: ${user}, Username: ${username}"})

        with pytest.raises(ValueError, match="Unresolved variables"):
            wrapper._run(shared={"user": "Alice"})

    def test_partial_resolution_with_paths(self):
        """Test partial resolution with path-based templates."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        # One path resolves, another doesn't
        wrapper.set_params({"message": "Name: ${user.name}, Age: ${user.age}"})

        with pytest.raises(ValueError, match="Unresolved variables"):
            wrapper._run(shared={"user": {"name": "Alice"}})

    def test_complete_resolution_with_empty_values(self):
        """Empty string resolution should not be confused with unresolved."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"message": "User ${name} has ${count} items"})

        # Both resolve, but count is empty string
        wrapper._run(shared={"name": "Alice", "count": ""})

        assert node.params_at_execution["message"] == "User Alice has  items"


class TestDepthLimit:
    """Test recursion depth limit for defensive programming."""

    def test_deep_nesting_does_not_cause_stack_overflow(self):
        """Deeply nested structures should hit depth limit gracefully, not crash."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        # Create a structure just deep enough to trigger the limit (105 levels)
        # This is FAST - only as deep as needed to test the limit
        nested = {"level": "${var}"}
        current = nested
        for _ in range(104):  # 105 levels total
            current["level"] = {"level": "${var}"}
            current = current["level"]

        wrapper.set_params({"data": nested})

        # Should NOT raise RecursionError - depth limit prevents it
        # The depth limit assumes "resolved" and continues execution
        wrapper._run(shared={})  # No error raised due to depth limit

        # The execution should complete (depth limit returns False = resolved)
        assert "data" in node.params_at_execution

    def test_depth_limit_logs_debug_message(self, caplog):
        """Depth limit should log when reached."""
        import logging

        caplog.set_level(logging.DEBUG)

        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        # Create deep structure
        nested = {"level": "${var}"}
        current = nested
        for _ in range(104):  # 105 levels total
            current["level"] = {"level": "${var}"}
            current = current["level"]

        wrapper.set_params({"data": nested})
        wrapper._run(shared={})

        # Check that depth limit message was logged
        assert any("depth limit" in record.message.lower() for record in caplog.records)


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_none_value_resolves_to_empty_string(self):
        """None values should convert to empty string in complex templates."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"message": "Value: ${data}"})

        wrapper._run(shared={"data": None})

        # None converts to empty string
        assert node.params_at_execution["message"] == "Value: "

    def test_simple_template_with_none_preserves_type(self):
        """Simple template with None value should preserve None type."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"field": "${data}"})

        wrapper._run(shared={"data": None})

        assert node.params_at_execution["field"] is None

    def test_empty_string_value_resolves(self):
        """Empty string values should resolve correctly."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"field": "${empty}"})

        wrapper._run(shared={"empty": ""})

        assert node.params_at_execution["field"] == ""

    def test_zero_value_resolves(self):
        """Zero values should resolve correctly (not treated as False)."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"count": "${zero}"})

        wrapper._run(shared={"zero": 0})

        assert node.params_at_execution["count"] == 0
        assert node.params_at_execution["count"] is not False

    def test_false_value_resolves(self):
        """False values should resolve correctly (not treated as None)."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        wrapper.set_params({"flag": "${disabled}"})

        wrapper._run(shared={"disabled": False})

        assert node.params_at_execution["flag"] is False

    def test_no_template_params_executes_immediately(self):
        """If no params contain templates, should skip resolution."""
        node = DummyNode()
        wrapper = TemplateAwareNodeWrapper(node, "test-node", initial_params={})

        # No templates in params
        wrapper.set_params({"message": "static text", "count": 42})

        result = wrapper._run(shared={})

        assert result == "default"
        assert node.params_at_execution == {"message": "static text", "count": 42}
