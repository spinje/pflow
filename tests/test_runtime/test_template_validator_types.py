"""Integration tests for type checking in template validator."""

import pytest

from pflow.registry.registry import Registry
from pflow.runtime.template_validator import TemplateValidator


@pytest.fixture
def test_registry(tmp_path):
    """Create a test registry with nodes that have typed parameters."""
    registry_file = tmp_path / "registry.json"
    registry = Registry(registry_file)

    test_data = {
        "string-producer": {
            "class_name": "StringProducer",
            "module": "test",
            "interface": {
                "outputs": [{"key": "result", "type": "str", "description": "String output"}],
                "params": [],
            },
        },
        "int-producer": {
            "class_name": "IntProducer",
            "module": "test",
            "interface": {
                "outputs": [{"key": "result", "type": "int", "description": "Integer output"}],
                "params": [],
            },
        },
        "dict-producer": {
            "class_name": "DictProducer",
            "module": "test",
            "interface": {
                "outputs": [
                    {
                        "key": "response",
                        "type": "dict",
                        "description": "Response data",
                        "structure": {
                            "message": {"type": "str", "description": "Message text"},
                            "count": {"type": "int", "description": "Count value"},
                        },
                    }
                ],
                "params": [],
            },
        },
        "llm": {
            "class_name": "LLMNode",
            "module": "test",
            "interface": {
                "outputs": [{"key": "response", "type": "dict|str", "description": "LLM response"}],
                "params": [
                    {"key": "prompt", "type": "str", "description": "Prompt text"},
                    {"key": "max_tokens", "type": "int", "description": "Max tokens"},
                ],
            },
        },
        "string-consumer": {
            "class_name": "StringConsumer",
            "module": "test",
            "interface": {
                "outputs": [],
                "params": [
                    {"key": "text", "type": "str", "description": "Text to process"},
                ],
            },
        },
        "int-consumer": {
            "class_name": "IntConsumer",
            "module": "test",
            "interface": {
                "outputs": [],
                "params": [
                    {"key": "count", "type": "int", "description": "Count value"},
                ],
            },
        },
    }
    registry.save(test_data)

    return registry


class TestTypeValidationIntegration:
    """Integration tests for type validation in workflows."""

    def test_compatible_types_pass(self, test_registry):
        """Compatible types should pass validation."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "string-producer", "params": {}},
                {"id": "consumer", "type": "string-consumer", "params": {"text": "${producer.result}"}},
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        type_errors = [e for e in errors if "Type mismatch" in e]
        assert len(type_errors) == 0

    def test_dict_to_string_compatible(self, test_registry):
        """Dict → string is now compatible via JSON serialization."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "string-consumer",
                    "params": {"text": "${producer.response}"},  # dict → str now allowed
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        type_errors = [e for e in errors if "Type mismatch" in e]
        assert len(type_errors) == 0  # No error - dict serializes to JSON string

    def test_dict_to_int_mismatch(self, test_registry):
        """Dict → int mismatch should be detected."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "int-consumer",
                    "params": {"count": "${producer.response}"},  # dict → int mismatch
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        type_errors = [e for e in errors if "Type mismatch" in e]
        assert len(type_errors) == 1
        assert "producer.response" in type_errors[0]
        assert "'dict'" in type_errors[0]
        assert "'int'" in type_errors[0]

    def test_nested_field_access_passes(self, test_registry):
        """Accessing a nested field with correct type should pass."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "string-consumer",
                    "params": {"text": "${producer.response.message}"},  # dict.str → str OK
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        type_errors = [e for e in errors if "Type mismatch" in e]
        assert len(type_errors) == 0

    def test_str_to_int_mismatch(self, test_registry):
        """String → int mismatch should be detected."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "string-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "int-consumer",
                    "params": {"count": "${producer.result}"},  # str → int mismatch
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        type_errors = [e for e in errors if "Type mismatch" in e]
        assert len(type_errors) == 1
        assert "'str'" in type_errors[0]
        assert "'int'" in type_errors[0]

    def test_int_to_string_compatible(self, test_registry):
        """Int can be passed to parameters expecting int."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "int-producer", "params": {}},
                {"id": "consumer", "type": "int-consumer", "params": {"count": "${producer.result}"}},
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        type_errors = [e for e in errors if "Type mismatch" in e]
        assert len(type_errors) == 0

    def test_union_type_compatibility(self, test_registry):
        """Union types should work correctly."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "llm", "type": "llm", "params": {"prompt": "test", "max_tokens": 100}},
                {
                    "id": "consumer",
                    "type": "string-consumer",
                    "params": {"text": "${llm.response}"},  # dict|str → str (both now compatible)
                },
            ],
            "edges": [{"from": "llm", "to": "consumer"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        type_errors = [e for e in errors if "Type mismatch" in e]
        # dict|str → str now passes because both dict and str can serialize to str
        assert len(type_errors) == 0

    def test_union_type_incompatibility(self, test_registry):
        """Union types with incompatible members should fail."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "llm", "type": "llm", "params": {"prompt": "test", "max_tokens": 100}},
                {
                    "id": "consumer",
                    "type": "int-consumer",
                    "params": {"count": "${llm.response}"},  # dict|str → int (incompatible)
                },
            ],
            "edges": [{"from": "llm", "to": "consumer"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        type_errors = [e for e in errors if "Type mismatch" in e]
        # dict|str → int should fail because neither dict nor str can convert to int
        assert len(type_errors) == 1

    def test_any_type_skips_validation(self, test_registry):
        """Parameters with type 'any' should skip type checking."""
        # Add a node that accepts any type
        test_data = test_registry.load(include_filtered=True)
        test_data["any-consumer"] = {
            "class_name": "AnyConsumer",
            "module": "test",
            "interface": {
                "outputs": [],
                "params": [
                    {"key": "value", "type": "any", "description": "Any value"},
                ],
            },
        }
        test_registry.save(test_data)

        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "any-consumer",
                    "params": {"value": "${producer.response}"},  # dict → any (always OK)
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        type_errors = [e for e in errors if "Type mismatch" in e]
        assert len(type_errors) == 0

    def test_multiple_type_errors(self, test_registry):
        """Multiple type mismatches should all be detected."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "str_prod", "type": "string-producer", "params": {}},
                {"id": "dict_prod", "type": "dict-producer", "params": {}},
                {
                    "id": "consumer1",
                    "type": "int-consumer",
                    "params": {"count": "${str_prod.result}"},  # str → int mismatch
                },
                {
                    "id": "consumer2",
                    "type": "int-consumer",
                    "params": {"count": "${dict_prod.response}"},  # dict → int mismatch
                },
            ],
            "edges": [
                {"from": "str_prod", "to": "consumer1"},
                {"from": "dict_prod", "to": "consumer2"},
            ],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        type_errors = [e for e in errors if "Type mismatch" in e]
        assert len(type_errors) == 2  # str→int and dict→int both fail

    def test_error_message_format(self, test_registry):
        """Error messages should be clear and include suggestions."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "int-consumer",
                    "params": {"count": "${producer.response}"},  # dict → int mismatch
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        type_errors = [e for e in errors if "Type mismatch" in e]
        assert len(type_errors) == 1

        error = type_errors[0]
        # Check error includes all necessary information
        assert "consumer" in error  # node ID
        assert "count" in error  # parameter name
        assert "producer.response" in error  # template
        assert "dict" in error  # inferred type
        assert "int" in error  # expected type
