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
        "shell": {
            "class_name": "ShellNode",
            "module": "pflow.nodes.shell.shell",
            "interface": {
                "outputs": [
                    {"key": "stdout", "type": "str", "description": "Standard output"},
                    {"key": "stderr", "type": "str", "description": "Standard error"},
                    {"key": "exit_code", "type": "int", "description": "Exit code"},
                ],
                "params": [
                    {"key": "command", "type": "str", "description": "Shell command to execute"},
                    {"key": "stdin", "type": "str", "description": "Standard input (optional)"},
                ],
            },
        },
        "list-producer": {
            "class_name": "ListProducer",
            "module": "test",
            "interface": {
                "outputs": [
                    {"key": "items", "type": "list", "description": "List of items"},
                ],
                "params": [],
            },
        },
        # Additional nodes for shell type validation tests
        "list-dict-producer": {
            "class_name": "ListDictProducer",
            "module": "test",
            "interface": {
                "outputs": [
                    {"key": "data", "type": "list[dict]", "description": "List of dicts (generic type)"},
                ],
                "params": [],
            },
        },
        "dict-list-union-producer": {
            "class_name": "DictListUnionProducer",
            "module": "test",
            "interface": {
                "outputs": [
                    {"key": "data", "type": "dict|list", "description": "Dict or list (no safe type)"},
                ],
                "params": [],
            },
        },
        "dict-any-union-producer": {
            "class_name": "DictAnyUnionProducer",
            "module": "test",
            "interface": {
                "outputs": [
                    {"key": "data", "type": "dict|any", "description": "Dict or any (has safe type)"},
                ],
                "params": [],
            },
        },
        "list-str-union-producer": {
            "class_name": "ListStrUnionProducer",
            "module": "test",
            "interface": {
                "outputs": [
                    {"key": "data", "type": "list|str", "description": "List or str (has safe type)"},
                ],
                "params": [],
            },
        },
        "any-producer": {
            "class_name": "AnyProducer",
            "module": "test",
            "interface": {
                "outputs": [
                    {"key": "data", "type": "any", "description": "Any type"},
                ],
                "params": [],
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

    def test_shell_command_blocks_dict_type(self, test_registry):
        """Shell command parameter should not accept dict types."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    # Note: unquoted template - quoted would trigger escape hatch
                    "params": {"command": "echo ${producer.response}"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        # Should have error about dict in shell command
        shell_errors = [e for e in errors if "Shell node" in e or "stdin" in e.lower()]
        assert len(shell_errors) == 1
        assert "producer.response" in shell_errors[0]
        assert "dict" in shell_errors[0]
        assert "stdin" in shell_errors[0].lower()  # Should suggest stdin

    def test_shell_command_blocks_list_type(self, test_registry):
        """Shell command parameter should not accept list types."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "list-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    # Note: unquoted template - quoted would trigger escape hatch
                    "params": {"command": "echo ${producer.items}"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        # Should have error about list in shell command
        shell_errors = [e for e in errors if "Shell node" in e or "stdin" in e.lower()]
        assert len(shell_errors) == 1
        assert "producer.items" in shell_errors[0]
        assert "list" in shell_errors[0]

    def test_shell_stdin_allows_dict_type(self, test_registry):
        """Shell stdin parameter should accept dict types (safe path)."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {
                        "stdin": "${producer.response}",  # dict in stdin is OK
                        "command": "jq '.message'",
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        # No shell-specific errors for stdin
        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 0

    def test_shell_command_allows_string_type(self, test_registry):
        """Shell command parameter should accept string types normally."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "string-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo '${producer.result}'"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        # No errors for string in command
        assert len(errors) == 0

    def test_shell_command_blocks_workflow_input_dict(self, test_registry):
        """Workflow input with dict type should be blocked in shell command.

        This is a common user path: declaring an input and using it directly.
        """
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {
                "data": {"type": "object", "required": True},  # User declares dict input
            },
            "nodes": [
                {
                    "id": "shell-node",
                    "type": "shell",
                    # Note: unquoted template - quoted would trigger escape hatch
                    "params": {"command": "echo ${data}"},  # Uses input in command
                },
            ],
            "edges": [],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        # Should block dict workflow input in shell command
        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 1
        assert "data" in shell_errors[0]
        assert "stdin" in shell_errors[0].lower()

    def test_shell_command_allows_nested_string_field_from_dict(self, test_registry):
        """Accessing a string field from a dict should be allowed in shell command.

        ${producer.response} is dict (blocked), but ${producer.response.message} is string (allowed).
        """
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo '${producer.response.message}'"},  # Access string field
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        # No errors - accessing string field from dict is safe
        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 0

    def test_shell_command_allows_union_with_str(self, test_registry):
        """Union type containing str should be ALLOWED in shell command (Tier 1).

        dict|str contains a safe type (str), so it's auto-allowed.
        Runtime coercion will handle dict → JSON string if needed.
        Uses the LLM node from test_registry which has output type dict|str.
        """
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                # LLM node has output type "dict|str" - contains str, so allowed
                {"id": "llm-node", "type": "llm", "params": {"prompt": "test", "max_tokens": 100}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    # Note: even without quotes, dict|str is allowed due to Tier 1
                    "params": {"command": "echo ${llm-node.response}"},
                },
            ],
            "edges": [{"from": "llm-node", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        # Should pass - dict|str contains str, which is a safe type
        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 0


class TestShellCommandUnionTypes:
    """Tests for Tier 1: auto-allow unions with safe types (str, string, any)."""

    def test_shell_allows_list_str_union(self, test_registry):
        """list|str union is allowed (contains str)."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "list-str-union-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo ${producer.data}"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 0

    def test_shell_allows_dict_any_union(self, test_registry):
        """dict|any union is allowed (contains any)."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-any-union-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo ${producer.data}"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 0

    def test_shell_blocks_dict_list_union(self, test_registry):
        """dict|list union is blocked (no safe type in union)."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-list-union-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo ${producer.data}"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 1
        assert "dict" in shell_errors[0] or "list" in shell_errors[0]

    def test_shell_allows_any_type(self, test_registry):
        """Pure 'any' type is allowed (safe type)."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "any-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo ${producer.data}"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 0


class TestShellCommandGenericTypes:
    """Tests for Fix 0: generic type base extraction (bug fix).

    Generic types like list[dict] should have their base type extracted
    before checking against blocked types.
    """

    def test_shell_blocks_list_dict_generic(self, test_registry):
        """list[dict] is blocked (base type is list)."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "list-dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo ${producer.data}"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        # Should block - base type "list" is blocked
        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 1
        assert "list" in shell_errors[0]

    def test_shell_allows_quoted_generic_type(self, test_registry):
        """'${data}' with list[dict] type is allowed (quote escape)."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "list-dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    # Quoted template triggers escape hatch
                    "params": {"command": "echo '${producer.data}'"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        # Should pass - quoted template bypasses type check
        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 0


class TestShellCommandQuoteEscape:
    """Tests for Tier 2: quote escape for structured types.

    Templates wrapped in single quotes '${var}' bypass type validation,
    signaling the user accepts runtime coercion.
    """

    def test_quoted_dict_template_allowed(self, test_registry):
        """'${data}' with dict type is allowed."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo '${producer.response}'"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 0

    def test_unquoted_dict_template_blocked(self, test_registry):
        """${data} with dict type is blocked."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo ${producer.response}"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 1
        assert "dict" in shell_errors[0]

    def test_quoted_dict_list_union_allowed(self, test_registry):
        """'${data}' with dict|list type is allowed (escape hatch)."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-list-union-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo '${producer.data}'"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 0

    def test_double_quoted_template_not_escaped(self, test_registry):
        """ "${data}" does NOT trigger escape (only single quotes)."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    # Double quotes don't trigger escape
                    "params": {"command": 'echo "${producer.response}"'},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 1  # Still blocked

    def test_quoted_with_prefix_not_escaped(self, test_registry):
        """'prefix ${data}' does NOT trigger escape (not exact match)."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    # Has prefix inside quotes - not exact '${var}' pattern
                    "params": {"command": "echo 'Data: ${producer.response}'"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 1  # Still blocked

    def test_multiple_quoted_templates(self, test_registry):
        """Multiple '${a}' '${b}' patterns each get escape."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer1", "type": "dict-producer", "params": {}},
                {"id": "producer2", "type": "list-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    # Both templates are individually quoted
                    "params": {"command": "echo '${producer1.response}' '${producer2.items}'"},
                },
            ],
            "edges": [
                {"from": "producer1", "to": "shell-node"},
                {"from": "producer2", "to": "shell-node"},
            ],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 0  # Both escaped

    def test_mixed_quoted_and_unquoted(self, test_registry):
        """Mix of quoted and unquoted - only unquoted blocked."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer1", "type": "dict-producer", "params": {}},
                {"id": "producer2", "type": "list-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    # First quoted (escaped), second unquoted (blocked)
                    "params": {"command": "echo '${producer1.response}' ${producer2.items}"},
                },
            ],
            "edges": [
                {"from": "producer1", "to": "shell-node"},
                {"from": "producer2", "to": "shell-node"},
            ],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 1  # Only unquoted one blocked
        assert "producer2" in shell_errors[0]

    def test_error_message_suggests_quote_escape(self, test_registry):
        """Error message should suggest the quote escape option."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo ${producer.response}"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 1
        # Check that error message suggests quote escape
        assert "Quote the template" in shell_errors[0] or "single quotes" in shell_errors[0]


class TestShellCommandRegressions:
    """Regression tests - ensure existing behavior is preserved."""

    def test_pure_dict_still_blocked_unquoted(self, test_registry):
        """Pure dict type without quotes is still blocked."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo ${producer.response}"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 1

    def test_pure_list_still_blocked_unquoted(self, test_registry):
        """Pure list type without quotes is still blocked."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "list-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo ${producer.items}"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 1

    def test_str_type_still_allowed(self, test_registry):
        """Pure str type is still allowed."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "string-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    "params": {"command": "echo ${producer.result}"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 0

    def test_stdin_still_allows_dict(self, test_registry):
        """stdin parameter still accepts dict (not command)."""
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    # stdin allows dict - only command param is checked
                    "params": {"stdin": "${producer.response}", "command": "jq '.message'"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, warnings = TemplateValidator.validate_workflow_templates(workflow_ir, {}, test_registry)

        shell_errors = [e for e in errors if "Shell node" in e]
        assert len(shell_errors) == 0


class TestShellCommandValidationTiming:
    """Integration tests verifying validation happens at compile time, not runtime.

    This is critical - if validation runs after template resolution, we'd get
    the same bug where dict/list slips through and causes runtime shell failures.
    """

    def test_dict_in_shell_command_fails_at_compile_time(self):
        """Dict in shell command should fail during compilation, not runtime.

        This tests the full compilation path to ensure the error is caught early.
        """
        from pflow.registry.registry import Registry
        from pflow.runtime.compiler import compile_ir_to_flow

        workflow_ir = {
            "inputs": {"data": {"type": "object", "required": True}},
            "nodes": [
                {
                    "id": "shell-node",
                    "type": "shell",
                    # Note: unquoted template - quoted would trigger escape hatch
                    "params": {"command": "echo ${data}"},
                }
            ],
            "edges": [],
            "outputs": {},
        }

        registry = Registry()

        # Should fail during compile_ir_to_flow, not later during flow.run()
        with pytest.raises(ValueError) as exc_info:
            compile_ir_to_flow(
                workflow_ir,
                registry=registry,
                initial_params={"data": {"key": "value"}},
                validate=True,  # Validation enabled
            )

        # Error should mention stdin as the solution
        assert "stdin" in str(exc_info.value).lower()

    def test_list_in_shell_command_fails_at_compile_time(self):
        """List in shell command should fail during compilation, not runtime."""
        from pflow.registry.registry import Registry
        from pflow.runtime.compiler import compile_ir_to_flow

        workflow_ir = {
            "inputs": {"items": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "shell-node",
                    "type": "shell",
                    # Note: unquoted template - quoted would trigger escape hatch
                    "params": {"command": "echo ${items}"},
                }
            ],
            "edges": [],
            "outputs": {},
        }

        registry = Registry()

        with pytest.raises(ValueError) as exc_info:
            compile_ir_to_flow(
                workflow_ir,
                registry=registry,
                initial_params={"items": [1, 2, 3]},
                validate=True,
            )

        assert "stdin" in str(exc_info.value).lower()

    def test_dict_in_shell_command_without_validation_fails_at_runtime(self):
        """Without validation, dict in command causes runtime shell error.

        Documents expected behavior when validation is bypassed.
        The shell node cannot detect the problem (templates already resolved),
        so users get a cryptic shell syntax error instead of our helpful message.

        This is why validation should always be enabled for user-facing workflows.
        """
        from pflow.registry.registry import Registry
        from pflow.runtime.compiler import compile_ir_to_flow

        workflow_ir = {
            "inputs": {"data": {"type": "object", "required": True}},
            "nodes": [
                {
                    "id": "shell-node",
                    "type": "shell",
                    # JSON with apostrophe will break shell quoting
                    "params": {"command": "echo '${data}'"},
                }
            ],
            "edges": [],
            "outputs": {},
        }

        registry = Registry()

        # Compilation succeeds with validate=False
        flow = compile_ir_to_flow(
            workflow_ir,
            registry=registry,
            initial_params={"data": {"msg": "it's broken"}},  # Apostrophe in data
            validate=False,  # Bypass validation
        )

        # Execution fails at shell level with cryptic error
        shared = {}
        result = flow.run(shared)

        # Shell fails due to quote escaping issues
        assert result == "error"
        assert shared["shell-node"]["exit_code"] != 0
        # The error is a shell syntax error, not our helpful message
        stderr = shared["shell-node"]["stderr"].lower()
        assert "unexpected" in stderr or "syntax" in stderr or "eof" in stderr
