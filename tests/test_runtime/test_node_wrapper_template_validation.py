"""Test template validation in template resolution.

This test suite verifies the fix for Issue #95 where simple templates
(like ${var}) were skipping error validation, allowing literal template
text to propagate to node execution.

Migrated from TemplateAwareNodeWrapper tests to use standalone functions
in pflow.runtime.engine.template_resolution.
"""

import pytest

from pflow.runtime.engine.template_resolution import (
    build_type_cache,
    inject_none_for_optional_inputs,
    resolve_templates,
    split_params,
)
from pflow.runtime.engine.types import TemplateConfig
from pflow.runtime.template_resolver import resolve


def _resolve(
    params: dict,
    shared: dict,
    interface_metadata: dict | None = None,
    resolution_mode: str = "strict",
    node_id: str = "test-node",
) -> dict:
    """Helper: split params, build config, resolve templates, return merged_params."""
    expected_types = build_type_cache(interface_metadata)
    template_params, static_params = split_params(params, expected_types)
    config = TemplateConfig(
        template_params=template_params,
        static_params=static_params,
        expected_types=expected_types,
        resolution_mode=resolution_mode,
    )
    merged_params, _last_resolutions, _template_errors = resolve_templates(config, shared, node_id)
    return merged_params


class TestSimpleTemplateValidation:
    """Test that simple templates are validated (bug fix for Issue #95)."""

    def test_simple_template_missing_variable_raises_error(self):
        """Simple template with missing variable should raise ValueError.

        This is the PRIMARY bug fix test. Previously, simple templates like
        ${missing_variable} would skip error checking and be passed literally
        to nodes, causing broken data in production.

        After fix: ValueError should be raised immediately.
        """
        with pytest.raises(ValueError, match="Unresolved variables"):
            _resolve({"prompt": "${missing_variable}"}, {})

    def test_simple_template_missing_variable_error_message(self):
        """Error message should be clear and actionable."""
        with pytest.raises(ValueError) as exc_info:
            _resolve({"prompt": "${missing_variable}"}, {})

        error_msg = str(exc_info.value)
        # Check essential error message components
        assert "prompt" in error_msg  # Parameter name
        assert "${missing_variable}" in error_msg  # Variable name
        assert "Unresolved variables" in error_msg  # Error type is clear

    def test_simple_template_existing_variable_resolves(self):
        """Simple template with existing variable should resolve correctly."""
        result = _resolve({"prompt": "${data}"}, {"data": "resolved value"})

        assert result["prompt"] == "resolved value"

    def test_simple_template_type_preservation(self):
        """Simple templates should preserve original type (not convert to string)."""
        # Integer
        result = _resolve({"count": "${total}"}, {"total": 42})
        assert result["count"] == 42
        assert isinstance(result["count"], int)

        # Boolean
        result = _resolve({"enabled": "${flag}"}, {"flag": True})
        assert result["enabled"] is True
        assert isinstance(result["enabled"], bool)

        # Dict
        result = _resolve({"data": "${config}"}, {"config": {"key": "value"}})
        assert result["data"] == {"key": "value"}
        assert isinstance(result["data"], dict)

        # List
        result = _resolve({"items": "${list}"}, {"list": [1, 2, 3]})
        assert result["items"] == [1, 2, 3]
        assert isinstance(result["items"], list)

    def test_simple_template_from_shared_store(self):
        """Templates should resolve from shared store."""
        result = _resolve(
            {"issue": "${issue_number}"},
            {"issue_number": "123"},
        )
        assert result["issue"] == "123"

    def test_simple_template_shared_store_values(self):
        """Shared store values are used for resolution.

        initial_params override behavior is removed; values come from shared store.
        """
        result = _resolve(
            {"field": "${data}"},
            {"data": "from_shared_store"},
        )

        assert result["field"] == "from_shared_store"


class TestComplexTemplateValidation:
    """Test complex templates (with text around variables) still work correctly."""

    def test_complex_template_missing_variable_raises_error(self):
        """Complex template with missing variable should raise ValueError.

        This already worked before the bug fix, but we verify it still works.
        """
        with pytest.raises(ValueError, match="Unresolved variables"):
            _resolve({"prompt": "Hello ${missing_variable}!"}, {})

    def test_complex_template_existing_variable_resolves(self):
        """Complex template with existing variable should resolve to string."""
        result = _resolve({"prompt": "Hello ${name}!"}, {"name": "World"})

        assert result["prompt"] == "Hello World!"
        assert isinstance(result["prompt"], str)

    def test_complex_template_type_coercion(self):
        """Complex templates always produce strings, even from non-string values."""
        # Integer in template
        result = _resolve({"message": "Count: ${count}"}, {"count": 42})
        assert result["message"] == "Count: 42"
        assert isinstance(result["message"], str)

        # Dict in template (should JSON serialize)
        result = _resolve({"message": "Data: ${config}"}, {"config": {"key": "value"}})
        assert "Data: {" in result["message"]
        assert isinstance(result["message"], str)


class TestNestedStructureTemplates:
    """Test templates in nested dicts and lists."""

    def test_dict_with_simple_template_missing_variable(self):
        """Dict containing simple template with missing variable should raise."""
        with pytest.raises(ValueError, match="Unresolved variables"):
            _resolve(
                {"config": {"url": "${base_url}", "port": 8080}},
                {},
            )

    def test_dict_with_simple_template_resolves(self):
        """Dict containing simple template should resolve correctly."""
        result = _resolve(
            {"config": {"url": "${base_url}", "port": 8080}},
            {"base_url": "https://api.example.com"},
        )

        assert result["config"]["url"] == "https://api.example.com"
        assert result["config"]["port"] == 8080

    def test_list_with_simple_template_missing_variable(self):
        """List containing simple template with missing variable should raise."""
        with pytest.raises(ValueError, match="Unresolved variables"):
            _resolve({"args": ["echo", "${message}"]}, {})

    def test_list_with_simple_template_resolves(self):
        """List containing simple template should resolve correctly."""
        result = _resolve({"args": ["echo", "${message}"]}, {"message": "Hello World"})

        assert result["args"] == ["echo", "Hello World"]


class TestPathTemplates:
    """Test templates with path access (dot notation and array indices)."""

    def test_simple_path_template_missing_path(self):
        """Path template with non-existent path should raise ValueError."""
        with pytest.raises(ValueError, match="Unresolved variables"):
            _resolve(
                {"field": "${data.missing.path}"},
                {"data": {"existing": "value"}},
            )

    def test_simple_path_template_resolves(self):
        """Path template should resolve through nested structure."""
        result = _resolve(
            {"field": "${user.profile.name}"},
            {"user": {"profile": {"name": "Alice"}}},
        )

        assert result["field"] == "Alice"

    def test_array_index_template_missing_index(self):
        """Array index template with out-of-bounds index should raise."""
        with pytest.raises(ValueError, match="Unresolved variables"):
            _resolve(
                {"field": "${items[5]}"},
                {"items": [1, 2, 3]},
            )

    def test_array_index_template_resolves(self):
        """Array index template should resolve to array element."""
        result = _resolve(
            {"field": "${items[1]}"},
            {"items": ["first", "second", "third"]},
        )

        assert result["field"] == "second"

    def test_combined_path_and_array_template(self):
        """Combined path and array access should work."""
        result = _resolve(
            {"field": "${users[0].profile.email}"},
            {"users": [{"profile": {"email": "alice@example.com"}}]},
        )

        assert result["field"] == "alice@example.com"


class TestMultipleTemplatesInParameter:
    """Test parameters with multiple template variables."""

    def test_multiple_templates_one_missing(self):
        """If any template in parameter is missing, should raise ValueError."""
        with pytest.raises(ValueError, match="Unresolved variables"):
            _resolve(
                {"message": "User ${name} has ${missing_count} items"},
                {"name": "Alice"},
            )

    def test_multiple_templates_all_resolved(self):
        """Multiple templates in one parameter should all resolve."""
        result = _resolve(
            {"message": "User ${name} has ${count} items"},
            {"name": "Alice", "count": 5},
        )

        assert result["message"] == "User Alice has 5 items"

    def test_no_false_positive_on_mcp_data(self):
        """Resolved data containing ${...} should not trigger false positives."""
        # Simulate MCP response that contains ${OLD_VAR} in its data
        mcp_result = {"message": "The old format used ${OLD_VAR} syntax"}

        result = _resolve(
            {"data": "${mcp.result}"},
            {"mcp": {"result": mcp_result}},
        )

        # Should NOT raise error - the ${OLD_VAR} is part of resolved data, not a template
        assert result["data"] == mcp_result

    def test_partial_resolution_with_three_variables(self):
        """Test partial resolution detection with 3+ variables."""
        with pytest.raises(ValueError, match="Unresolved variables"):
            _resolve(
                {"message": "${greeting} ${name}, you have ${count} items"},
                {"greeting": "Hello", "name": "Alice"},
            )

    def test_similar_variable_names_no_confusion(self):
        """Variables with similar names should be handled correctly."""
        with pytest.raises(ValueError, match="Unresolved variables"):
            _resolve(
                {"message": "User: ${user}, Username: ${username}"},
                {"user": "Alice"},
            )

    def test_partial_resolution_with_paths(self):
        """Test partial resolution with path-based templates."""
        with pytest.raises(ValueError, match="Unresolved variables"):
            _resolve(
                {"message": "Name: ${user.name}, Age: ${user.age}"},
                {"user": {"name": "Alice"}},
            )

    def test_complete_resolution_with_empty_values(self):
        """Empty string resolution should not be confused with unresolved."""
        result = _resolve(
            {"message": "User ${name} has ${count} items"},
            {"name": "Alice", "count": ""},
        )

        assert result["message"] == "User Alice has  items"


class TestDepthLimit:
    """Test recursion depth limit for defensive programming."""

    def test_deep_nesting_does_not_cause_stack_overflow(self):
        """Deeply nested structures should hit depth limit gracefully, not crash."""
        # Create a structure just deep enough to trigger the limit (105 levels)
        nested = {"level": "${var}"}
        current = nested
        for _ in range(104):  # 105 levels total
            current["level"] = {"level": "${var}"}
            current = current["level"]

        # In permissive mode, the unresolved leaves are recorded, not raised.
        result = _resolve({"data": nested}, {}, resolution_mode="permissive")

        # The execution should complete (depth limit returns False = resolved)
        assert "data" in result


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_none_value_resolves_to_empty_string(self):
        """None values should convert to empty string in complex templates."""
        result = _resolve({"message": "Value: ${data}"}, {"data": None})

        assert result["message"] == "Value: "

    def test_simple_template_with_none_preserves_type(self):
        """Simple template with None value should preserve None type."""
        result = _resolve({"field": "${data}"}, {"data": None})

        assert result["field"] is None

    def test_empty_string_value_resolves(self):
        """Empty string values should resolve correctly."""
        result = _resolve({"field": "${empty}"}, {"empty": ""})

        assert result["field"] == ""

    def test_zero_value_resolves(self):
        """Zero values should resolve correctly (not treated as False)."""
        result = _resolve({"count": "${zero}"}, {"zero": 0})

        assert result["count"] == 0
        assert result["count"] is not False

    def test_false_value_resolves(self):
        """False values should resolve correctly (not treated as None)."""
        result = _resolve({"flag": "${disabled}"}, {"disabled": False})

        assert result["flag"] is False

    def test_no_template_params_executes_immediately(self):
        """If no params contain templates, should skip resolution."""
        result = _resolve({"message": "static text", "count": 42}, {})

        assert result == {"message": "static text", "count": 42}


class TestErrorMessageAccuracy:
    """Test that error messages only report actually unresolved variables.

    Bug fix: Previously, when a parameter had multiple template variables
    and some resolved but others didn't, the error message would list ALL
    variables as unresolved - even ones that successfully resolved.
    """

    def test_error_only_shows_actually_unresolved_variables(self):
        """Error message should only list variables that are actually missing.

        Regression test for misleading error messages:
        - Parameter: {"a": "${provided}", "b": "${missing}"}
        - Old error: "Unresolved variables: ${provided}, ${missing}"  (wrong!)
        - Fixed error: "Unresolved variables: ${missing}"  (correct)
        """
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"data": {"has_value": "${provided}", "no_value": "${missing}"}},
                {"provided": "hello"},
            )

        error_msg = str(exc_info.value)

        # Error should mention the missing variable
        assert "${missing}" in error_msg

        # The structured renderer should still highlight the unresolved variable explicitly.
        assert "✗ ${missing}" in error_msg

    def test_error_shows_all_missing_when_multiple_missing(self):
        """When multiple variables are missing, error should list all of them."""
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"message": "Hello ${name}, you have ${count} items with status ${status}"},
                {"name": "Alice"},
            )

        error_msg = str(exc_info.value)

        # Should list both missing variables
        assert "${count}" in error_msg
        assert "${status}" in error_msg

        # The structured renderer should explicitly highlight the unresolved variables.
        assert "✗ ${count}" in error_msg
        assert "✗ ${status}" in error_msg

    def test_error_available_keys_shows_provided_context(self):
        """Error message should show what keys ARE available for debugging."""
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"field": "${missing}"},
                {"available_key": "value", "another_key": 42},
            )

        error_msg = str(exc_info.value)

        # Should show available keys to help user debug
        assert "available_key" in error_msg or "Available context keys" in error_msg


class TestOptionalInputInjection:
    """Test inject_none_for_optional_inputs for branch convergence.

    When a code node has optional inputs (T | None), and the source node
    for that input didn't execute (its namespace is absent from the shared
    store), None should be injected instead of leaving the unresolved
    ${...} template string.
    """

    @staticmethod
    def _inject(template: dict, context: dict, optional: set[str]) -> tuple[dict, frozenset[str]]:
        """Resolve ``template`` per key as the engine does, then inject."""
        by_key = {k: resolve(v, context, auto_parse=True) for k, v in template.items()}
        resolved = {k: r.value for k, r in by_key.items()}
        return inject_none_for_optional_inputs(resolved, template, context, optional, by_key)

    def test_injects_none_when_source_node_absent(self):
        """When source node didn't execute (absent from context), inject None."""
        template = {"high": "${branch-high.stdout}", "low": "${branch-low.stdout}"}
        context = {"branch-low": {"stdout": "resolved-value"}}

        result, injected = self._inject(template, context, {"high"})

        assert result["high"] is None
        assert result["low"] == "resolved-value"
        assert injected == {"high"}

    def test_no_injection_when_source_node_present(self):
        """When source node executed (present in context), leave unresolved for error detection."""
        template = {"high": "${branch-high.stddout}", "low": "${branch-low.stdout}"}
        context = {"branch-high": {"stdout": "data"}, "branch-low": {"stdout": "resolved-value"}}

        result, injected = self._inject(template, context, {"high"})

        # Should NOT inject None -- source node exists, this is a typo
        assert result["high"] == "${branch-high.stddout}"
        assert result["low"] == "resolved-value"
        assert injected == frozenset()

    def test_no_injection_for_non_optional_keys(self):
        """Keys not in optional_input_keys should never be injected with None."""
        template = {"low": "${branch-low.stdout}"}

        result, injected = self._inject(template, {}, {"high"})

        # "low" is not in optional_input_keys, so it stays unchanged
        assert result["low"] == "${branch-low.stdout}"
        assert injected == frozenset()

    def test_no_injection_when_key_not_inputs(self):
        """Only the `inputs` param is injected; an optional key name under another param is not."""
        config = TemplateConfig(
            template_params={"prompt": {"x": "${source.value}"}},
            static_params={},
            expected_types={},
            resolution_mode="permissive",
            optional_input_keys={"x"},
        )

        merged, _, errors = resolve_templates(config, {}, "test-node")

        # key is "prompt", not "inputs" -- no injection; the miss is recorded
        assert merged["prompt"]["x"] == "${source.value}"
        assert [e["unresolved_expressions"] for e in errors] == [("source.value",)]

    def test_no_injection_when_no_optional_keys(self):
        """With empty optional_input_keys, function is a no-op."""
        template = {"high": "${branch-high.stdout}"}

        result, injected = self._inject(template, {}, set())

        # No optional keys configured -- no injection
        assert result["high"] == "${branch-high.stdout}"
        assert injected == frozenset()

    def test_injects_none_for_multiple_optional_keys(self):
        """When multiple optional keys have absent source nodes, all get None."""
        template = {"high": "${branch-high.stdout}", "low": "${branch-low.stdout}"}
        context = {}  # Neither source node executed

        result, injected = self._inject(template, context, {"high", "low"})

        assert result["high"] is None
        assert result["low"] is None
        assert injected == {"high", "low"}

    def test_resolved_value_not_modified(self):
        """Already-resolved values (no ${) should not be touched."""
        template = {"high": "${branch-high.stdout}"}
        context = {"branch-high": {"stdout": "already-resolved"}}

        result, injected = self._inject(template, context, {"high"})

        # Value is already resolved (no ${), so it stays as-is
        assert result["high"] == "already-resolved"
        assert injected == frozenset()


class TestInputsResolvedPerKey:
    """`resolve_templates` judges `inputs` per key: an injected None drops only its own key's miss."""

    @staticmethod
    def _config(inputs: dict, optional: set[str], mode: str = "strict") -> TemplateConfig:
        return TemplateConfig(
            template_params={"inputs": inputs},
            static_params={},
            expected_types={},
            resolution_mode=mode,
            optional_input_keys=optional,
        )

    def test_required_sibling_sharing_the_text_still_fails(self):
        """`opt` gets None; `req` reads the same absent node and must still raise."""
        config = self._config({"opt": "${b.stdout}", "req": "prefix ${b.stdout}"}, {"opt"})
        with pytest.raises(ValueError, match=r"\$\{b\.stdout\}"):
            resolve_templates(config, {}, "n")

    def test_injected_key_alone_is_clean(self):
        config = self._config({"opt": "${b.stdout}", "req": "${a.x}"}, {"opt"})
        merged, _, errors = resolve_templates(config, {"a": {"x": 1}}, "n")
        assert merged["inputs"] == {"opt": None, "req": 1}
        assert errors == []

    def test_dynamic_index_from_an_absent_branch_is_injected(self):
        """Outer and inner both from the skipped branch: the pre-pass cannot rewrite the index,
        and the optional input still gets None."""
        config = self._config({"opt": "${g.items[${g.i}].x}", "idx": "${g.items[${__index__}].x}"}, {"opt", "idx"})
        merged, _, errors = resolve_templates(config, {"__index__": 0}, "n")
        assert merged["inputs"] == {"opt": None, "idx": None}
        assert errors == []

    def test_partially_resolved_optional_input_is_not_injected(self):
        """One present root means the miss is a real error, not a skipped branch."""
        config = self._config({"opt": "${a.x} ${b.y}"}, {"opt"})
        with pytest.raises(ValueError, match=r"\$\{b\.y\}"):
            resolve_templates(config, {"a": {"x": 1}}, "n")

    def test_optional_input_with_a_literal_fallback_is_not_injected(self):
        """`${b.x ?? "d"}` resolved to "d", so the key did not stay wholly literal."""
        config = self._config({"opt": '${b.x ?? "d"} ${c.y}'}, {"opt"}, mode="permissive")
        merged, _, errors = resolve_templates(config, {}, "n")
        assert merged["inputs"] == {"opt": "d ${c.y}"}
        assert [e["unresolved_expressions"] for e in errors] == [("c.y",)]

    def test_permissive_entry_carries_both_channels(self):
        config = self._config({"x": "${src.result.items.0}", "y": "${src.nope}"}, set(), mode="permissive")
        _, _, errors = resolve_templates(config, {"src": {"result": {"items": [1]}}}, "n")
        assert len(errors) == 1
        assert errors[0]["unresolved"] == ["inputs"]
        assert errors[0]["unresolved_expressions"] == ("src.nope",)
        assert errors[0]["issues"] == ("${src.result.items.0}",)


class TestCoalesceErrorMessages:
    """Test that coalesce errors show per-operand diagnosis."""

    def test_coalesce_error_shows_absent_nodes(self):
        """When neither branch ran, error shows which nodes didn't execute."""
        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"command": "${branch-high.stdout ?? branch-low.stdout}"},
                {},
            )

        error_msg = str(exc_info.value)
        assert "branch-high.stdout ?? branch-low.stdout" in error_msg
        assert "branch-high" in error_msg and "did not execute" in error_msg
        assert "branch-low" in error_msg and "did not execute" in error_msg

    def test_coalesce_error_shows_path_error(self):
        """When a branch ran but path is wrong, error shows the typo."""
        shared = {"branch-high": {"stdout": "data"}}  # branch-high ran

        with pytest.raises(ValueError) as exc_info:
            _resolve(
                {"command": "${branch-high.stddout ?? branch-low.stdout}"},
                shared,
            )

        error_msg = str(exc_info.value)
        assert "branch-high.stddout" in error_msg
        assert "does not produce field 'stddout'" in error_msg
