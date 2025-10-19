"""Tests for type checking utilities."""

import pytest

from pflow.registry.registry import Registry
from pflow.runtime.type_checker import (
    get_parameter_type,
    infer_template_type,
    is_type_compatible,
)


class TestTypeCompatibility:
    """Tests for is_type_compatible()."""

    def test_exact_match(self):
        """Exact type matches are always compatible."""
        assert is_type_compatible("str", "str") is True
        assert is_type_compatible("int", "int") is True
        assert is_type_compatible("dict", "dict") is True

    def test_any_type_universal(self):
        """'any' type is compatible with everything."""
        assert is_type_compatible("any", "str") is True
        assert is_type_compatible("any", "int") is True
        assert is_type_compatible("any", "dict") is True
        assert is_type_compatible("str", "any") is True
        assert is_type_compatible("int", "any") is True

    def test_int_to_float_compatible(self):
        """int can widen to float."""
        assert is_type_compatible("int", "float") is True

    def test_float_to_int_incompatible(self):
        """float cannot narrow to int."""
        assert is_type_compatible("float", "int") is False

    def test_str_to_int_incompatible(self):
        """str cannot be used as int."""
        assert is_type_compatible("str", "int") is False

    def test_dict_to_str_incompatible(self):
        """dict cannot be used as str (the original bug!)."""
        assert is_type_compatible("dict", "str") is False

    def test_bool_to_str_compatible(self):
        """bool can be stringified."""
        assert is_type_compatible("bool", "str") is True

    def test_union_source_all_must_match(self):
        """With union source, ALL types must be compatible with target."""
        # str|any -> str: both str and any are compatible with str
        assert is_type_compatible("str|any", "str") is True

        # dict|str -> str: dict is NOT compatible with str
        assert is_type_compatible("dict|str", "str") is False

        # int|float -> float: both int and float compatible with float
        assert is_type_compatible("int|float", "float") is True

    def test_union_target_any_must_match(self):
        """With union target, source must match ANY target type."""
        # str -> str|int: str matches str in union
        assert is_type_compatible("str", "str|int") is True

        # int -> str|int: int matches int in union
        assert is_type_compatible("int", "str|int") is True

        # dict -> str|int: dict matches neither
        assert is_type_compatible("dict", "str|int") is False

        # int -> int|float: int matches both
        assert is_type_compatible("int", "int|float") is True

    def test_union_both_sides(self):
        """Complex union type compatibility."""
        # dict|str source, str|int target
        # For each source type, check if compatible with any target type:
        # - dict: compatible with int? No. compatible with str? No.
        # - str: compatible with int? No. compatible with str? Yes!
        # Result: False (dict is not compatible)
        assert is_type_compatible("dict|str", "str|int") is False

        # str|any source, str|int target
        # - str: compatible with str|int? Yes
        # - any: compatible with str|int? Yes
        # Result: True
        assert is_type_compatible("str|any", "str|int") is True


class TestTemplateTypeInference:
    """Tests for infer_template_type()."""

    def test_infer_simple_output(self):
        """Infer type for simple node output."""
        workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "n1"}]}
        node_outputs = {"n1.result": {"type": "dict", "node_id": "n1"}}

        result = infer_template_type("n1.result", workflow_ir, node_outputs)
        assert result == "dict"

    def test_infer_nested_field(self):
        """Infer type for nested field access."""
        workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "n1"}]}
        node_outputs = {
            "n1.data": {
                "type": "dict",
                "structure": {"count": {"type": "int", "description": "Count"}},
            }
        }

        result = infer_template_type("n1.data.count", workflow_ir, node_outputs)
        assert result == "int"

    def test_infer_deep_nested_structure(self):
        """Infer type for deeply nested structures."""
        workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "github"}]}
        node_outputs = {
            "github.issue": {
                "type": "dict",
                "structure": {
                    "user": {
                        "type": "dict",
                        "description": "User info",
                        "structure": {
                            "login": {"type": "str", "description": "Username"},
                            "id": {"type": "int", "description": "User ID"},
                        },
                    }
                },
            }
        }

        result = infer_template_type("github.issue.user.login", workflow_ir, node_outputs)
        assert result == "str"

        result = infer_template_type("github.issue.user.id", workflow_ir, node_outputs)
        assert result == "int"

    def test_infer_with_array_indices(self):
        """Infer type with array access in path."""
        workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "api"}]}
        node_outputs = {
            "api.items": {
                "type": "list",
                "structure": {"name": {"type": "str", "description": "Item name"}},
            }
        }

        # Array indices are stripped for structure lookup
        result = infer_template_type("api.items[0].name", workflow_ir, node_outputs)
        assert result == "str"

    def test_infer_unknown_field(self):
        """Return None for unknown fields."""
        workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "n1"}]}
        node_outputs = {"n1.result": {"type": "dict"}}

        result = infer_template_type("n1.result.unknown", workflow_ir, node_outputs)
        # No structure, but dict type allows traversal -> returns "any"
        assert result == "any"

    def test_infer_with_any_type(self):
        """'any' type allows traversal but returns 'any'."""
        workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "mcp"}]}
        node_outputs = {"mcp.result": {"type": "any"}}

        result = infer_template_type("mcp.result.field", workflow_ir, node_outputs)
        assert result == "any"

    def test_infer_union_type_with_dict(self):
        """Union types with dict allow traversal."""
        workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "n1"}]}
        node_outputs = {"n1.response": {"type": "dict|str"}}

        result = infer_template_type("n1.response.field", workflow_ir, node_outputs)
        assert result == "any"  # dict allows traversal, returns any

    def test_infer_workflow_input(self):
        """Infer type from workflow inputs."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {"api_key": {"type": "str", "description": "API key"}},
            "nodes": [],
        }
        node_outputs = {}

        result = infer_template_type("api_key", workflow_ir, node_outputs)
        assert result == "str"

    def test_infer_non_traversable_type(self):
        """Non-traversable types return None for nested access."""
        workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "n1"}]}
        node_outputs = {"n1.count": {"type": "int"}}

        result = infer_template_type("n1.count.field", workflow_ir, node_outputs)
        assert result is None  # int doesn't allow traversal

    def test_infer_invalid_node_only(self):
        """Just node ID without output key returns None."""
        workflow_ir = {"enable_namespacing": True, "nodes": [{"id": "n1"}]}
        node_outputs = {"n1.result": {"type": "str"}}

        result = infer_template_type("n1", workflow_ir, node_outputs)
        assert result is None

    def test_infer_without_namespacing(self):
        """Handle workflows without namespacing."""
        workflow_ir = {"enable_namespacing": False, "nodes": [{"id": "n1"}]}
        node_outputs = {"result": {"type": "str", "node_id": "n1"}}

        result = infer_template_type("result", workflow_ir, node_outputs)
        assert result == "str"


class TestParameterTypeLookup:
    """Tests for get_parameter_type()."""

    @pytest.fixture
    def mock_registry(self, tmp_path):
        """Create a mock registry with test nodes."""
        registry_file = tmp_path / "registry.json"
        registry = Registry(registry_file)

        # Save test registry data
        test_data = {
            "test-node": {
                "class_name": "TestNode",
                "module": "test",
                "interface": {
                    "params": [
                        {"key": "timeout", "type": "int", "description": "Timeout in seconds"},
                        {"key": "url", "type": "str", "description": "Target URL"},
                        {"key": "config", "type": "dict", "description": "Configuration"},
                    ]
                },
            },
            "simple-node": {
                "class_name": "SimpleNode",
                "module": "test",
                "interface": {
                    "params": [
                        {"key": "value", "type": "str"},  # No description
                    ]
                },
            },
        }
        registry.save(test_data)

        return registry

    def test_get_parameter_type(self, mock_registry):
        """Get parameter type from registry."""
        param_type = get_parameter_type("test-node", "timeout", mock_registry)
        assert param_type == "int"

        param_type = get_parameter_type("test-node", "url", mock_registry)
        assert param_type == "str"

        param_type = get_parameter_type("test-node", "config", mock_registry)
        assert param_type == "dict"

    def test_get_parameter_type_not_found(self, mock_registry):
        """Return None for unknown parameter."""
        param_type = get_parameter_type("test-node", "nonexistent", mock_registry)
        assert param_type is None

    def test_get_parameter_type_invalid_node(self, mock_registry):
        """Return None for unknown node."""
        param_type = get_parameter_type("invalid-node", "param", mock_registry)
        assert param_type is None

    def test_get_parameter_type_defaults_to_any(self, mock_registry):
        """Parameters without type default to 'any'."""
        # Add node with param missing type
        test_data = mock_registry.load(include_filtered=True)
        test_data["no-type-node"] = {
            "class_name": "NoTypeNode",
            "module": "test",
            "interface": {"params": [{"key": "value"}]},  # No type field
        }
        mock_registry.save(test_data)

        param_type = get_parameter_type("no-type-node", "value", mock_registry)
        assert param_type == "any"
