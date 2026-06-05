"""Integration tests for type checking in template validator."""

import pytest

from pflow.core.diagnostic import Severity
from pflow.registry.registry import Registry
from pflow.runtime.template_validation import validate_workflow_templates
from tests.shared.diagnostic_helpers import (
    split_template_diagnostics,
    split_validator_diagnostics,
)


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
        "code": {
            "class_name": "PythonCodeNode",
            "module": "pflow.nodes.python.python_code",
            "interface": {
                "outputs": [
                    {"key": "result", "type": "any", "description": "Value of result variable after execution"},
                    {"key": "stdout", "type": "str", "description": "Captured print output"},
                    {"key": "stderr", "type": "str", "description": "Captured stderr output"},
                ],
                "params": [
                    {"key": "code", "type": "str", "description": "Python code to execute"},
                    {"key": "inputs", "type": "dict", "description": "Variable name to value mapping"},
                    {"key": "timeout", "type": "int", "description": "Execution timeout in seconds"},
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        type_errors = [d for d in errors if "Type mismatch" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        type_errors = [d for d in errors if "Type mismatch" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        type_errors = [d for d in errors if "Type mismatch" in d.message]
        assert len(type_errors) == 1
        assert "producer.response" in type_errors[0].message
        assert "'dict'" in type_errors[0].message
        assert "'int'" in type_errors[0].message

        # Structural assertion (task 147): the type-validation producer must
        # preserve the structural context fields — path, inferred_type,
        # expected_type, node_id. Without this, the substring assertions above
        # would pass even if the producer regressed to a bare message string.
        diagnostics = validate_workflow_templates(workflow_ir, {}, test_registry)
        type_diag = next(d for d in diagnostics if "Type mismatch" in d.message)
        assert type_diag.node_id == "consumer"
        assert type_diag.context["path"] == "nodes[id=consumer].params.count"
        assert type_diag.context["inferred_type"] == "dict"
        assert type_diag.context["expected_type"] == "int"

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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        type_errors = [d for d in errors if "Type mismatch" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        type_errors = [d for d in errors if "Type mismatch" in d.message]
        assert len(type_errors) == 1
        assert "'str'" in type_errors[0].message
        assert "'int'" in type_errors[0].message

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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        type_errors = [d for d in errors if "Type mismatch" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        type_errors = [d for d in errors if "Type mismatch" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        type_errors = [d for d in errors if "Type mismatch" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        type_errors = [d for d in errors if "Type mismatch" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        type_errors = [d for d in errors if "Type mismatch" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        type_errors = [d for d in errors if "Type mismatch" in d.message]
        assert len(type_errors) == 1

        error = type_errors[0]
        # Check error includes all necessary information
        assert error.node_id == "consumer"
        assert "count" in error.message
        assert "producer.response" in error.message
        assert "dict" in error.message
        assert "int" in error.message

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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        # Should have error about dict in shell command
        shell_errors = [d for d in errors if "Shell node" in d.message or "stdin" in d.message.lower()]
        assert len(shell_errors) == 1
        assert "producer.response" in shell_errors[0].message
        assert "dict" in shell_errors[0].message
        assert shell_errors[0].suggestions
        assert any("stdin" in suggestion.lower() for suggestion in shell_errors[0].suggestions)

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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        # Should have error about list in shell command
        shell_errors = [d for d in errors if "Shell node" in d.message or "stdin" in d.message.lower()]
        assert len(shell_errors) == 1
        assert "producer.items" in shell_errors[0].message
        assert "list" in shell_errors[0].message

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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        # No shell-specific errors for stdin
        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        # Should block dict workflow input in shell command
        shell_errors = [d for d in errors if "Shell node" in d.message]
        assert len(shell_errors) == 1
        assert "data" in shell_errors[0].message
        # "stdin" lives in the structured suggestions (TY2 producer emits 3 fix options)
        suggestions = shell_errors[0].suggestions or []
        assert any("stdin" in s.lower() for s in suggestions), f"Expected 'stdin' in suggestions: {shell_errors[0]}"

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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        # No errors - accessing string field from dict is safe
        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        # Should pass - dict|str contains str, which is a safe type
        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
        assert len(shell_errors) == 1
        assert "dict" in shell_errors[0].message or "list" in shell_errors[0].message

        # Structural assertion (task 147): _build_shell_command_diagnostic is one of
        # the most user-visible task 147 producer rewrites — 3 concrete fix options
        # plus structured context. Without this, the producer could regress to a
        # bare Diagnostic(message=...) with suggestions=None and the substring
        # assertion above would still pass.
        diagnostics = validate_workflow_templates(workflow_ir, {}, test_registry)
        shell_diag = next(d for d in diagnostics if d.message.startswith("Shell node"))
        assert shell_diag.node_id == "shell-node"
        assert shell_diag.context["path"] == "nodes[id=shell-node].params.command"
        assert shell_diag.context["template"] == "${producer.data}"
        assert shell_diag.context["shell_command"] == "echo ${producer.data}"
        assert shell_diag.suggestions is not None
        assert len(shell_diag.suggestions) == 3
        assert any("stdin" in s for s in shell_diag.suggestions)

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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        # Should block - base type "list" is blocked
        shell_errors = [d for d in errors if "Shell node" in d.message]
        assert len(shell_errors) == 1
        assert "list" in shell_errors[0].message

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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        # Should pass - quoted template bypasses type check
        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
        assert len(shell_errors) == 1
        assert "dict" in shell_errors[0].message

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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
        assert len(shell_errors) == 0

    def test_quoted_nested_field_access_with_array_indices(self, test_registry):
        """'${node.field[0].subfield}' works correctly with nested paths and array indices.

        This tests that the quote escape pattern correctly captures complex paths
        including array indices (which use [] not {}), nested field access,
        and combinations thereof.
        """
        workflow_ir = {
            "enable_namespacing": True,
            "inputs": {},
            "nodes": [
                {"id": "producer", "type": "list-dict-producer", "params": {}},
                {
                    "id": "shell-node",
                    "type": "shell",
                    # Complex nested path with array index
                    "params": {"command": "echo '${producer.data}' | jq '.[0].field'"},
                },
            ],
            "edges": [{"from": "producer", "to": "shell-node"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        # Should pass - quoted template with nested path is escaped
        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
        assert len(shell_errors) == 1  # Only unquoted one blocked
        assert "producer2" in shell_errors[0].message

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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
        assert len(shell_errors) == 1
        # Check that error message suggests quote escape
        assert shell_errors[0].suggestions
        assert any(
            "quote" in suggestion.lower() or "single quotes" in suggestion.lower()
            for suggestion in shell_errors[0].suggestions
        )


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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
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

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)

        shell_errors = [d for d in errors if "Shell node" in d.message]
        assert len(shell_errors) == 0


class TestShellCommandValidationTiming:
    """Integration tests verifying validation happens at compile time, not runtime.

    This is critical - if validation runs after template resolution, we'd get
    the same bug where dict/list slips through and causes runtime shell failures.
    """

    def test_dict_in_shell_command_fails_at_compile_time(self):
        """Dict in shell command should fail during pre-execution validation.

        After Task 138, type validation moved from the compiler to
        WorkflowValidator. The behavior (catching dict-in-shell-command
        before execution) is preserved, just at a different stage.
        """
        from pflow.registry.registry import Registry

        workflow_ir = {
            "ir_version": "0.1.0",
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

        # WorkflowValidator catches type-incompatible templates
        errors, _warnings = split_validator_diagnostics(
            workflow_ir=workflow_ir,
            extracted_params={"data": {"key": "value"}},
            registry=registry,
            skip_node_types=False,
        )

        # Error should mention stdin as the solution for dict-in-shell
        assert any(d.suggestions and any("stdin" in suggestion.lower() for suggestion in d.suggestions) for d in errors)

    def test_list_in_shell_command_fails_at_compile_time(self):
        """List in shell command should fail during pre-execution validation.

        After Task 138, type validation moved from the compiler to
        WorkflowValidator. The behavior is preserved at the validation stage.
        """
        from pflow.registry.registry import Registry

        workflow_ir = {
            "ir_version": "0.1.0",
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

        errors, _warnings = split_validator_diagnostics(
            workflow_ir=workflow_ir,
            extracted_params={"items": [1, 2, 3]},
            registry=registry,
            skip_node_types=False,
        )

        assert any(d.suggestions and any("stdin" in suggestion.lower() for suggestion in d.suggestions) for d in errors)

    def test_dict_in_shell_command_without_validation_fails_at_runtime(self):
        """Without validation, dict in command causes runtime shell error.

        Documents expected behavior when validation is bypassed.
        The shell node cannot detect the problem (templates already resolved),
        so users get a cryptic shell syntax error instead of our helpful message.

        This is why validation should always be enabled for user-facing workflows.
        """
        from pflow.registry.registry import Registry
        from pflow.runtime import compile_workflow
        from pflow.runtime.engine import WorkflowEngine

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
        initial_params = {"data": {"msg": "it's broken"}}  # Apostrophe in data

        # Compilation succeeds — template validation now in WorkflowValidator, not compiler
        workflow = compile_workflow(
            workflow_ir,
            registry=registry,
            initial_params=initial_params,
        )

        # Execution fails at shell level with cryptic error
        shared = {}
        shared.update({k: v for k, v in initial_params.items() if not k.startswith("__")})
        shared.update(workflow.resolved_defaults)
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

        # Shell fails due to quote escaping issues
        from pflow.runtime.node_state import get_node_output

        assert result == "error"
        node_output = get_node_output(shared, "shell-node")
        assert node_output is not None
        assert node_output["exit_code"] != 0
        # The error is a shell syntax error, not our helpful message
        stderr = node_output["stderr"].lower()
        assert "unexpected" in stderr or "syntax" in stderr or "eof" in stderr


def test_shell_blocks_multiple_structured_templates_preserves_structure(test_registry) -> None:
    """Multi-template shell diagnostics should preserve blocked template metadata."""
    workflow_ir = {
        "enable_namespacing": True,
        "inputs": {},
        "nodes": [
            {"id": "a", "type": "dict-producer", "params": {}},
            {"id": "b", "type": "list-producer", "params": {}},
            {
                "id": "shell-node",
                "type": "shell",
                "params": {"command": "echo ${a.response} ${b.items}"},
            },
        ],
        "edges": [
            {"from": "a", "to": "shell-node"},
            {"from": "b", "to": "shell-node"},
        ],
    }

    diagnostics = validate_workflow_templates(workflow_ir, {}, test_registry)
    errors = [
        d for d in diagnostics if d.severity == Severity.ERROR and "multiple structured data templates" in d.message
    ]

    assert len(errors) == 1
    diagnostic = errors[0]
    assert diagnostic.context is not None
    assert diagnostic.context.get("path") == "nodes[id=shell-node].params.command"
    assert "shell_command" in diagnostic.context
    blocked_templates = diagnostic.context.get("blocked_templates")
    assert isinstance(blocked_templates, list)
    assert len(blocked_templates) == 2
    assert diagnostic.suggestions is not None
    assert len(diagnostic.suggestions) == 4
    assert any("stdin" in suggestion for suggestion in diagnostic.suggestions)
    assert any("temp files" in suggestion for suggestion in diagnostic.suggestions)


class TestCodeNodeInputAnnotationValidation:
    """Pass 9 validates code-node inputs against code-block annotations."""

    def test_dict_annotation_rejects_list_upstream(self, test_registry):
        """Annotation `x: dict` with upstream `list` fires a type-mismatch error."""
        workflow_ir = {
            "nodes": [
                {"id": "producer", "type": "list-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "x: dict\nresult: str = str(x)",
                        "inputs": {"x": "${producer.items}"},
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        annotation_errors = [d for d in errors if "expects dict" in d.message]
        assert len(annotation_errors) == 1, [d.message for d in errors]

        diagnostic = annotation_errors[0]
        assert diagnostic.node_id == "consumer"
        assert diagnostic.context["path"] == "nodes[id=consumer].params.inputs.x"
        assert diagnostic.context["annotation"] == "dict"
        # Both inferred and expected types are Python vocabulary for consistency:
        # agents consuming JSON can compare them directly without crossing the
        # S1/Python bridge.
        assert diagnostic.context["inferred_type"] == "list"
        assert diagnostic.context["expected_type"] == "dict"
        assert diagnostic.context["template"] == "${producer.items}"
        assert diagnostic.suggestions is not None
        assert len(diagnostic.suggestions) == 3
        # Locality hints tell the agent which file/section each fix applies to.
        assert any("params.code" in s and "x: list" in s for s in diagnostic.suggestions), diagnostic.suggestions
        assert any("${producer.items}" in s for s in diagnostic.suggestions), diagnostic.suggestions
        assert any("params.code" in s and "x: Any" in s for s in diagnostic.suggestions), diagnostic.suggestions

    def test_compatible_types_pass(self, test_registry):
        """Matching annotation and upstream type produces no diagnostic."""
        workflow_ir = {
            "nodes": [
                {"id": "producer", "type": "list-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "x: list\nresult: int = len(x)",
                        "inputs": {"x": "${producer.items}"},
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        annotation_errors = [d for d in errors if "expects" in d.message and "receives" in d.message]
        assert annotation_errors == []

    def test_missing_annotation_fires_and_infers_type(self, test_registry):
        """Input bound but no annotation — suggestion includes the inferred upstream type."""
        workflow_ir = {
            "nodes": [
                {"id": "producer", "type": "list-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "result: str = 'hi'",
                        "inputs": {"x": "${producer.items}"},
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        annotation_errors = [d for d in errors if "missing a type annotation" in d.message]
        assert len(annotation_errors) == 1
        diagnostic = annotation_errors[0]
        assert diagnostic.context["input_key"] == "x"
        # The upstream is a typed list — suggestion should offer the concrete
        # annotation instead of a `<type>` placeholder so agents can copy-paste.
        assert diagnostic.context["inferred_type"] == "list"
        assert diagnostic.suggestions is not None
        assert any("x: list" in s and "inferred from" in s for s in diagnostic.suggestions), diagnostic.suggestions
        assert not any("<type>" in s for s in diagnostic.suggestions)

    def test_missing_annotation_falls_back_when_type_unknown(self, test_registry):
        """When upstream type can't be inferred (literal value), suggestion keeps <type> placeholder."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "result: str = 'hi'",
                        "inputs": {"x": "literal-value"},  # no template, no source to infer from
                    },
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        annotation_errors = [d for d in errors if "missing a type annotation" in d.message]
        assert len(annotation_errors) == 1
        diagnostic = annotation_errors[0]
        assert "inferred_type" not in diagnostic.context
        assert any("<type>" in s for s in diagnostic.suggestions or []), diagnostic.suggestions

    def test_missing_annotation_complex_template_infers_str(self, test_registry):
        """Complex template (text + ref) coerces to str at runtime — infer str, not the source type.

        Runtime concatenates ``"prefix ${source}"`` into a string regardless of
        what ``source`` declares. The suggestion must reflect the runtime
        contract: ``x: str``, not ``x: list``.
        """
        workflow_ir = {
            "nodes": [
                {"id": "producer", "type": "list-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "result: str = x",
                        "inputs": {"x": "prefix ${producer.items}"},  # complex — coerces to str
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        annotation_errors = [d for d in errors if "missing a type annotation" in d.message]
        assert len(annotation_errors) == 1
        diagnostic = annotation_errors[0]
        assert diagnostic.context["inferred_type"] == "str"
        assert any("x: str" in s for s in diagnostic.suggestions or []), diagnostic.suggestions
        # Must NOT suggest the source type (list) — that's wrong for complex templates.
        assert not any("x: list" in s for s in diagnostic.suggestions or []), diagnostic.suggestions

    def test_orphan_annotation_unused_suggests_removal(self, test_registry):
        """Orphan annotation with no Load reference is dead code — canonical fix is remove."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        # y is annotated but never read in the body — pure dead code.
                        "code": "x: dict\ny: list\nresult: str = 'hi'",
                        "inputs": {"x": "literal_value"},
                    },
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        annotation_errors = [d for d in errors if "has no corresponding entry in 'inputs'" in d.message]
        assert len(annotation_errors) == 1
        diagnostic = annotation_errors[0]
        assert diagnostic.context["annotation_key"] == "y"
        assert diagnostic.suggestions is not None
        # Opinionated one-fix-per-case — "Remove" is the canonical answer here.
        assert any("Remove" in s and "never read" in s for s in diagnostic.suggestions), diagnostic.suggestions
        assert not any("Add" in s for s in diagnostic.suggestions), diagnostic.suggestions

    def test_orphan_annotation_used_suggests_adding_to_inputs(self, test_registry):
        """Orphan annotation read in the body signals missing binding — canonical fix is add."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        # y has annotation AND is read later — author expected it bound.
                        "code": "x: dict\ny: list\nresult: int = len(y)",
                        "inputs": {"x": "literal_value"},
                    },
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        annotation_errors = [d for d in errors if "has no corresponding entry in 'inputs'" in d.message]
        assert len(annotation_errors) == 1
        diagnostic = annotation_errors[0]
        assert any("Add 'y' to the inputs dict" in s for s in diagnostic.suggestions or []), diagnostic.suggestions
        assert not any("Remove" in s for s in diagnostic.suggestions or []), diagnostic.suggestions

    def test_orphan_annotation_assigned_suggests_remove_or_add(self, test_registry):
        """Orphan annotation that is ALSO assigned is a local — offer remove (lead) or add.

        Removing the annotation is safe because the name carries a value, so both
        fixes are valid. Contrast with the read-but-unassigned case above, where
        removing would leave the name unbound and only "add" is offered.
        """
        workflow_ir = {
            "nodes": [
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        # all_items is annotated AND assigned -> a local, not an input.
                        "code": "x: dict\nall_items: list = [x]\nresult: int = len(all_items)",
                        "inputs": {"x": "literal_value"},
                    },
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        annotation_errors = [
            d for d in errors if "has no corresponding entry in 'inputs'" in d.message and "all_items" in d.message
        ]
        assert len(annotation_errors) == 1
        suggestions = annotation_errors[0].suggestions or []
        # Both fixes present...
        assert any("Remove the annotation 'all_items" in s and "local variable" in s for s in suggestions), suggestions
        assert any("add 'all_items' to the inputs dict" in s.lower() for s in suggestions), suggestions
        # ...and the local reading leads.
        assert "Remove" in suggestions[0], suggestions

    def test_orphan_annotation_conditional_assignment_is_not_safe_local(self, test_registry):
        """Orphan assigned only inside `if` may be unbound at runtime — add, don't lead with remove (C1)."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "items: list\nif True:\n    items = []\nresult: int = len(items)",
                        "inputs": {},
                    },
                },
            ],
            "edges": [],
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann = [d for d in errors if "Annotation 'items: list'" in d.message]
        assert len(ann) == 1, [d.message for d in errors]
        suggestions = ann[0].suggestions or []
        assert any("Add 'items' to the inputs dict" in s for s in suggestions), suggestions
        assert not any("local variable" in s for s in suggestions), suggestions

    def test_orphan_annotation_augmented_assignment_is_not_safe_local(self, test_registry):
        """`count += 1` reads before storing, so removing the annotation unbinds it — add, not remove (C4)."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "count: int\ncount += 1\nresult: int = count",
                        "inputs": {},
                    },
                },
            ],
            "edges": [],
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann = [d for d in errors if "Annotation 'count: int'" in d.message]
        assert len(ann) == 1, [d.message for d in errors]
        suggestions = ann[0].suggestions or []
        assert any("Add 'count' to the inputs dict" in s for s in suggestions), suggestions
        assert not any("local variable" in s for s in suggestions), suggestions

    def test_orphan_annotation_on_def_name_suggests_remove(self, test_registry):
        """A def name is a module-level local binding — removing the orphan annotation is right (C2)."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "helper: Any\ndef helper():\n    return 1\nresult: int = helper()",
                        "inputs": {},
                    },
                },
            ],
            "edges": [],
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann = [d for d in errors if "Annotation 'helper: Any'" in d.message]
        assert len(ann) == 1, [d.message for d in errors]
        suggestions = ann[0].suggestions or []
        assert any("Remove the annotation 'helper" in s and "local variable" in s for s in suggestions), suggestions
        assert "Remove" in suggestions[0], suggestions

    def test_orphan_batch_alias_assigned_preserves_alias_suggestion(self, test_registry):
        """An assigned batch alias still needs `item: ${item}` — the alias isn't injected into exec (C3)."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "batched",
                    "type": "code",
                    "params": {"code": "item: dict\nitem = {'k': 1}\nresult: dict = item"},
                    "batch": {"items": [1, 2, 3]},  # default alias = "item"
                },
            ],
            "edges": [],
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann = [d for d in errors if "Annotation 'item: dict'" in d.message]
        assert len(ann) == 1, [d.message for d in errors]
        suggestions = ann[0].suggestions or []
        # Batch alias keeps its exact binding, not the remove-local lead.
        assert any("item: ${item}" in s for s in suggestions), suggestions
        assert not any("local variable" in s for s in suggestions), suggestions

    def test_orphan_annotation_typo_surfaces_fuzzy_match(self, test_registry):
        """Typo'd orphan (read in body) surfaces fuzzy-matched input key via similar_names."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        # Annotation is `item` (typo); input binding is `items`.
                        # Body reads `item` so it's a used-orphan; fuzzy match finds `items`.
                        "code": "items: list\nitem: dict\nresult: int = len(item)",
                        "inputs": {"items": "literal_value"},
                    },
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        annotation_errors = [d for d in errors if "has no corresponding entry in 'inputs'" in d.message]
        assert len(annotation_errors) == 1
        diagnostic = annotation_errors[0]
        assert diagnostic.context.get("similar_names") == ["items"]
        assert any("Rename" in s and "items" in s for s in diagnostic.suggestions or []), diagnostic.suggestions

    def test_result_and_next_are_not_flagged_as_orphan(self, test_registry):
        """`result` and `next` are routing/output annotations, not input orphans."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "router",
                    "type": "code",
                    "params": {
                        "code": "next: str = 'target'\nresult: str = 'done'",
                        "inputs": {},
                    },
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        assert not any("no corresponding entry" in d.message for d in errors)

    def test_missing_result_or_next_annotation_fires(self, test_registry):
        """Code with neither `result:` nor `next:` annotation fails validation.

        Mirrors the runtime ``ValueError`` in ``python_code.py::prep`` so
        ``--validate-only`` and ``--dry-run`` catch the gap at validate-time
        with byte-identical wording.
        """
        workflow_ir = {
            "nodes": [
                {
                    "id": "split",
                    "type": "code",
                    "params": {"code": "items = [1, 2, 3]", "inputs": {}},
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        missing = [d for d in errors if "Code must declare result type annotation" in d.message]
        assert len(missing) == 1, [d.message for d in errors]

        diagnostic = missing[0]
        assert diagnostic.severity == Severity.ERROR
        # source="validator" is part of the producer contract that the
        # renderer relies on (see template_validation/CLAUDE.md).
        assert diagnostic.source == "validator"
        assert diagnostic.node_id == "split"
        # Byte-identical to runtime check in python_code.py::prep.
        assert diagnostic.message == (
            "Code must declare result type annotation (result: <type> = ...) "
            "or next type annotation (next: str = ...) for routing"
        )
        assert diagnostic.context["category"] == "validation"
        assert diagnostic.context["path"] == "nodes[id=split].params.code"
        assert diagnostic.context["node_type"] == "code"
        # Programmatic consumers (MCP / JSON output) get a structured signal
        # of which declarations are missing without parsing the message text.
        assert diagnostic.context["missing"] == ["result", "next"]
        # Agents get a direct pointer to the code-node guide topic, matching
        # the see_also pattern used by Pass 5 and Pass 8 diagnostics.
        assert diagnostic.see_also == ["code"]

    def test_result_annotation_alone_passes(self, test_registry):
        """`result:` without `next:` is sufficient — the check is OR, not AND."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "producer",
                    "type": "code",
                    "params": {"code": "result: list = [1, 2, 3]", "inputs": {}},
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        assert not any("Code must declare result type annotation" in d.message for d in errors)

    def test_next_annotation_alone_passes(self, test_registry):
        """`next:` without `result:` is sufficient — dynamic-routing code nodes."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "router",
                    "type": "code",
                    "params": {"code": "next: str = 'target'", "inputs": {}},
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        assert not any("Code must declare result type annotation" in d.message for d in errors)

    def test_next_annotation_must_be_str(self, test_registry):
        """`next: int` must fail validation, mirroring the runtime prep check.

        Runtime rejects at ``python_code.py:566-572`` with ``'next' must be
        annotated as str, got <type>``. Validate-time emits a symmetric
        Diagnostic so ``--validate-only`` catches the same error.
        """
        workflow_ir = {
            "nodes": [
                {
                    "id": "router",
                    "type": "code",
                    "params": {"code": "next: int = 42", "inputs": {}},
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        type_errors = [d for d in errors if "'next' must be annotated as str" in d.message]
        assert len(type_errors) == 1, [d.message for d in errors]

        diagnostic = type_errors[0]
        assert diagnostic.severity == Severity.ERROR
        assert diagnostic.source == "validator"
        assert diagnostic.node_id == "router"
        assert diagnostic.message == "'next' must be annotated as str, got int"
        assert diagnostic.context["path"] == "nodes[id=router].params.code"
        assert diagnostic.context["annotation"] == "int"
        assert diagnostic.context["expected_type"] == "str"
        assert diagnostic.see_also == ["code"]

    def test_next_str_annotation_passes(self, test_registry):
        """`next: str` is the canonical routing declaration — must not fire the type check."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "router",
                    "type": "code",
                    "params": {"code": 'next: str = "target"', "inputs": {}},
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        assert not any("'next' must be annotated as str" in d.message for d in errors)

    def test_next_unknown_type_skips_check(self, test_registry):
        """Unknown/user-defined next annotation types skip the check (matches runtime)."""
        # Runtime's `_get_outer_type` returns None for types outside _TYPE_MAP.
        # Validate-time must skip the check too — otherwise we'd reject valid
        # code that runtime accepts via the user-class escape hatch.
        workflow_ir = {
            "nodes": [
                {
                    "id": "router",
                    "type": "code",
                    "params": {"code": 'next: UserDefinedType = "target"', "inputs": {}},
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        assert not any("'next' must be annotated as str" in d.message for d in errors)

    def test_next_forward_ref_wrong_type_rejected(self, test_registry):
        """Forward-ref `next: "int"` must be unwrapped and rejected.

        `_get_outer_type` unwraps forward-ref quotes via `_annotation_outer_base`
        (landed in #317). Without the unwrap, `"'int'"` would miss the type map
        and silently skip — letting `next: "int"` pass validation only to fail
        at runtime. This test pins the Pass 9 ↔ unwrap-helper integration so
        the forward-ref handling can't silently regress.
        """
        workflow_ir = {
            "nodes": [
                {
                    "id": "router",
                    "type": "code",
                    "params": {"code": 'next: "int" = 42', "inputs": {}},
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        type_errors = [d for d in errors if "'next' must be annotated as str" in d.message]
        assert len(type_errors) == 1, [d.message for d in errors]

    def test_result_annotation_inside_helper_function_matches_runtime(self, test_registry):
        """Presence check uses walk-mode so validate-time matches runtime parity.

        Runtime ``_extract_annotations`` walks into function bodies; the
        presence gate must accept what runtime accepts. A ``result:``
        annotation inside a helper function that's then reassigned at
        module level runs cleanly at runtime and must pass validation too.
        """
        code = "def build():\n    result: dict = {'ok': True}\n    return result\n\nresult = build()"
        workflow_ir = {
            "nodes": [{"id": "build", "type": "code", "params": {"code": code, "inputs": {}}}],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        assert not any("Code must declare result type annotation" in d.message for d in errors), [
            d.message for d in errors
        ]

    def test_any_annotation_skips_check(self, test_registry):
        """`x: Any` accepts any upstream type."""
        workflow_ir = {
            "nodes": [
                {"id": "producer", "type": "list-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "x: Any\nresult: str = str(x)",
                        "inputs": {"x": "${producer.items}"},
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        assert not any("expects" in d.message and "receives" in d.message for d in errors)

    def test_optional_annotation_decomposes_correctly(self, test_registry):
        """`x: list | None` is compatible with upstream `list`."""
        workflow_ir = {
            "nodes": [
                {"id": "producer", "type": "list-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "x: list | None\nresult: str = str(x)",
                        "inputs": {"x": "${producer.items}"},
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        assert not any("expects" in d.message and "receives" in d.message for d in errors)

    def test_user_defined_class_skips_check(self, test_registry):
        """Unknown/user-defined annotations skip validate-time type checking."""
        workflow_ir = {
            "nodes": [
                {"id": "producer", "type": "list-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "x: DataFrame\nresult: str = str(x)",
                        "inputs": {"x": "${producer.items}"},
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        assert not any("expects DataFrame" in d.message for d in errors)

    def test_code_to_code_chain_catches_mismatch(self, test_registry):
        """Code -> code mismatch is visible once upstream result typing is enriched."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "upstream",
                    "type": "code",
                    "params": {"code": "result: list = [1, 2, 3]"},
                },
                {
                    "id": "downstream",
                    "type": "code",
                    "params": {
                        "code": "x: dict\nresult: str = str(x)",
                        "inputs": {"x": "${upstream.result}"},
                    },
                },
            ],
            "edges": [{"from": "upstream", "to": "downstream"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        annotation_errors = [d for d in errors if "Input 'x' expects dict" in d.message]
        assert len(annotation_errors) == 1, [d.message for d in errors]

        # Code-block annotations are Python — display must speak Python too.
        # "x: array" is invalid Python; a user copy-pasting it gets a NameError.
        diagnostic = annotation_errors[0]
        assert "receives list" in diagnostic.message, diagnostic.message
        assert "array" not in diagnostic.message
        assert diagnostic.context["inferred_type"] == "list"
        assert diagnostic.suggestions is not None
        assert any("x: list" in s for s in diagnostic.suggestions), diagnostic.suggestions
        assert not any("x: array" in s for s in diagnostic.suggestions)

    def test_malformed_code_skips_pass(self, test_registry):
        """SyntaxError in code skips Pass 9 entirely — runtime surfaces the error.

        Pass 9 must not crash or emit spurious Class 1/2/3 errors on unparseable
        code; the SyntaxError is the user's primary concern and runtime will
        report it with a clean line number. Validate-time emitting additional
        diagnostics here would obscure the real issue.
        """
        workflow_ir = {
            "nodes": [
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "x: dict =",  # SyntaxError — no RHS
                        "inputs": {"x": "literal"},
                    },
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        # Pass 9 must not emit its three error classes on unparseable code.
        pass_9_markers = (
            "expects",
            "missing a type annotation",
            "has no corresponding entry",
        )
        pass_9_errors = [d for d in errors if any(marker in d.message for marker in pass_9_markers)]
        assert pass_9_errors == [], [d.message for d in pass_9_errors]

    def test_literal_values_skipped(self, test_registry):
        """Literal string values stay out of Pass 9 scope."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "x: dict\nresult: str = str(x)",
                        "inputs": {"x": "hello"},
                    },
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        assert not any("expects dict" in d.message and "receives" in d.message for d in errors)

    def test_batch_code_node_result_enrichment_catches_downstream_mismatch(self, test_registry):
        """Batch code-node `result:` annotation enriches inner output type.

        Exercises `_register_batch_outputs`'s enrichment path: a batch code node
        with `result: list` should produce `results[*].result` with enriched type
        `array`, so a downstream consumer declaring `x: dict` bound to the
        indexed path fails validation with the correct type mismatch.

        The batch producer uses the canonical pattern ``inputs: {item: ${item}}``
        — the engine only injects the batch alias into template resolution,
        not into code exec, so the binding is required for the `item` load
        reference inside the code body.
        """
        workflow_ir = {
            "nodes": [
                {
                    "id": "batch_producer",
                    "type": "code",
                    # `item: Any` (capitalized) — pflow auto-injects typing.Any.
                    # Lowercase `any` is the builtin function, not a type; it
                    # passes validation here only because _get_outer_type_name
                    # returns None for unknown names, which is a readability
                    # footgun for future readers.
                    "params": {
                        "code": "item: Any\nresult: list = [item]",
                        "inputs": {"item": "${item}"},
                    },
                    "batch": {"items": ["a", "b"], "error_handling": "fail_fast"},
                },
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "x: dict\nresult: str = str(x)",
                        "inputs": {"x": "${batch_producer.results[0].result}"},
                    },
                },
            ],
            "edges": [{"from": "batch_producer", "to": "consumer"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        annotation_errors = [d for d in errors if "Input 'x' expects dict" in d.message]
        assert len(annotation_errors) == 1, [d.message for d in errors]
        diagnostic = annotation_errors[0]
        # Batch enrichment produces S1 `array` internally → displayed as `list`.
        assert "receives list" in diagnostic.message, diagnostic.message
        assert any("x: list" in s for s in diagnostic.suggestions or []), diagnostic.suggestions

    def test_workflow_input_source_suggestion_wording(self, test_registry):
        """Workflow-input templates shouldn't suggest 'change X to return Y' — X isn't returned by anything.

        Points the agent at the declared input's type instead.
        """
        workflow_ir = {
            "inputs": {
                "data": {"type": "array", "required": True},
            },
            "nodes": [
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "x: dict\nresult: str = str(x)",
                        "inputs": {"x": "${data}"},
                    },
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann_errors = [d for d in errors if "Input 'x' expects dict" in d.message]
        assert len(ann_errors) == 1, [d.message for d in errors]
        suggestions = ann_errors[0].suggestions or []
        # Must reference the workflow input declaration, not "change to return".
        assert any("workflow input declaration for 'data'" in s and "- type: dict" in s for s in suggestions), (
            suggestions
        )
        assert not any("return dict" in s for s in suggestions), suggestions

    def test_optional_annotation_preserved_in_suggestion(self, test_registry):
        """`x: dict | None` mismatch must suggest `x: list | None`, not strip the `| None`."""
        workflow_ir = {
            "nodes": [
                {"id": "producer", "type": "list-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "x: dict | None\nresult: str = str(x)",
                        "inputs": {"x": "${producer.items}"},
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann_errors = [d for d in errors if "Input 'x'" in d.message]
        assert len(ann_errors) == 1, [d.message for d in errors]
        suggestions = ann_errors[0].suggestions or []
        # Preserves the user's Optional semantics.
        assert any("x: list | None" in s for s in suggestions), suggestions
        # Must NOT suggest bare `x: list` (would silently drop None-tolerance).
        assert not any(s.endswith("x: list") or s.endswith("x: list\n") for s in suggestions), suggestions

    def test_optional_typing_form_also_preserved(self, test_registry):
        """`x: Optional[dict]` mismatch suggests `x: list | None` (modernized)."""
        workflow_ir = {
            "nodes": [
                {"id": "producer", "type": "list-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": "x: Optional[dict]\nresult: str = str(x)",
                        "inputs": {"x": "${producer.items}"},
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann_errors = [d for d in errors if "Input 'x'" in d.message]
        assert len(ann_errors) == 1, [d.message for d in errors]
        suggestions = ann_errors[0].suggestions or []
        assert any("x: list | None" in s for s in suggestions), suggestions

    def test_batch_orphan_suggests_alias_not_placeholder(self, test_registry):
        """Missing-inputs.item binding for a batch code node suggests `${item}` literally, not `${<source>}`."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "batched",
                    "type": "code",
                    "params": {"code": "item: int\nresult: int = item * 2"},
                    "batch": {"items": [1, 2, 3]},
                },
            ],
            "edges": [],
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann_errors = [d for d in errors if "no corresponding entry" in d.message]
        assert len(ann_errors) == 1, [d.message for d in errors]
        suggestions = ann_errors[0].suggestions or []
        # Tells the agent the exact binding, not `${<source>}`.
        assert any("item: ${item}" in s for s in suggestions), suggestions
        assert not any("${<source>}" in s for s in suggestions), suggestions

    def test_batch_orphan_with_custom_alias_uses_that_alias(self, test_registry):
        """Custom batch.as='row' produces 'row: ${row}' in the suggestion."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "batched",
                    "type": "code",
                    "params": {"code": "row: int\nresult: int = row * 2"},
                    "batch": {"items": [1, 2, 3], "as": "row"},
                },
            ],
            "edges": [],
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann_errors = [d for d in errors if "no corresponding entry" in d.message]
        assert len(ann_errors) == 1, [d.message for d in errors]
        suggestions = ann_errors[0].suggestions or []
        assert any("row: ${row}" in s for s in suggestions), suggestions

    def test_batch_alias_wins_over_fuzzy_match(self, test_registry):
        """When the orphan key matches batch.as AND fuzzy-matches an input, alias wins.

        Fuzzy match of `item` against `['items']` passes with difflib ratio ~0.89,
        producing "Rename to 'items'" — which would break valid code that reads
        the per-iteration `item`. The batch-alias branch is deterministic metadata
        and must take precedence over the heuristic.
        """
        workflow_ir = {
            "nodes": [
                {
                    "id": "batched",
                    "type": "code",
                    "params": {
                        # Code uses `item` (the batch iteration variable).
                        # `items` is separately bound as a list-typed input.
                        "code": "items: list\nitem: int\nresult: int = item * 2",
                        "inputs": {"items": "${items}"},
                    },
                    "batch": {"items": [1, 2, 3]},  # default alias = "item"
                },
            ],
            "edges": [],
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann_errors = [d for d in errors if "Annotation 'item: int'" in d.message]
        assert len(ann_errors) == 1, [d.message for d in errors]
        suggestions = ann_errors[0].suggestions or []
        # Must suggest binding `item: ${item}`, NOT renaming to `items`.
        assert any("item: ${item}" in s for s in suggestions), suggestions
        assert not any("Rename" in s for s in suggestions), suggestions
        # similar_names context key must be absent (fuzzy path was skipped).
        assert "similar_names" not in ann_errors[0].context

    def test_complex_template_bypass_caught(self, test_registry):
        """Complex templates coerce to str at runtime — Pass 9 must enforce the str contract.

        Pre-fix: Class 3 validated each embedded ``${ref}`` source type
        independently. When an embedded source type happened to match the
        target (e.g. upstream dict → annotation dict), Pass 9 accepted
        ``"prefix ${x}"`` even though runtime would coerce the whole value
        to str and TypeError on the isinstance check.
        """
        workflow_ir = {
            "nodes": [
                {
                    "id": "produce",
                    "type": "code",
                    "params": {"code": "result: dict = {'a': 1}"},
                },
                {
                    "id": "consume",
                    "type": "code",
                    "params": {
                        "code": "x: dict\nresult: str = str(x)",
                        # Complex template: prefix + ${produce.result}. Embedded
                        # source type is dict (matches annotation), but runtime
                        # coerces the whole string → str.
                        "inputs": {"x": "prefix ${produce.result}"},
                    },
                },
            ],
            "edges": [{"from": "produce", "to": "consume"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann_errors = [d for d in errors if "Input 'x'" in d.message and "complex templates" in d.message]
        assert len(ann_errors) == 1, [d.message for d in errors]
        diagnostic = ann_errors[0]
        # Exactly one diagnostic — not one-per-embedded-ref.
        assert "receives str" in diagnostic.message
        # References the full value, not the embedded ref alone.
        assert diagnostic.context["inferred_type"] == "str"
        assert diagnostic.context["expected_type"] == "dict"
        assert diagnostic.suggestions is not None
        assert any("x: str" in s for s in diagnostic.suggestions), diagnostic.suggestions

    def test_complex_template_with_compatible_str_target_passes(self, test_registry):
        """Complex template + `x: str` annotation is valid — no error."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "produce",
                    "type": "code",
                    "params": {"code": "result: dict = {'a': 1}"},
                },
                {
                    "id": "consume",
                    "type": "code",
                    "params": {
                        "code": "x: str\nresult: str = x",
                        "inputs": {"x": "prefix ${produce.result}"},
                    },
                },
            ],
            "edges": [{"from": "produce", "to": "consume"}],
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann_errors = [d for d in errors if "Input 'x' expects" in d.message]
        assert ann_errors == [], [d.message for d in ann_errors]

    def test_function_local_annotation_not_flagged_as_orphan(self, test_registry):
        """Function-local `y: int` inside `def helper()` must not trip Pass 9's orphan check."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node",
                    "type": "code",
                    "params": {
                        "code": ("def helper():\n    y: int = 1\n    return y\n\nx: dict\nresult: int = helper()"),
                        "inputs": {"x": "literal_dict_binding"},
                    },
                },
            ],
            "edges": [],
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        orphan_errors = [d for d in errors if "no corresponding entry" in d.message]
        # `y` must NOT be flagged — it's a function-local, not a code-node input.
        assert not any("'y:" in d.message for d in orphan_errors), [d.message for d in orphan_errors]

    def test_class_body_annotation_not_flagged_as_orphan(self, test_registry):
        """Class body annotations (`class Config: timeout: int`) must not be orphans."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node",
                    "type": "code",
                    "params": {
                        "code": ("class Config:\n    timeout: int\n    name: str\n\nx: dict\nresult: int = 1"),
                        "inputs": {"x": "literal_dict_binding"},
                    },
                },
            ],
            "edges": [],
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        orphan_errors = [d for d in errors if "no corresponding entry" in d.message]
        assert not any("timeout" in d.message or "name" in d.message for d in orphan_errors), [
            d.message for d in orphan_errors
        ]

    def test_forward_reference_annotation_type_checked(self, test_registry):
        """Forward-ref `x: "dict"` must be unwrapped so Pass 9 sees the inner type.

        Pre-fix: ast.unparse preserves quotes, the lookup missed, and the
        mismatch silently passed validation AND runtime. Both layers now see
        through the quotes.
        """
        workflow_ir = {
            "nodes": [
                {"id": "producer", "type": "list-producer", "params": {}},
                {
                    "id": "consumer",
                    "type": "code",
                    "params": {
                        "code": 'x: "dict"\nresult: str = str(x)',
                        "inputs": {"x": "${producer.items}"},
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "consumer"}],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        ann_errors = [d for d in errors if "Input 'x' expects" in d.message]
        assert len(ann_errors) == 1, [d.message for d in errors]

    def test_batch_code_without_item_input_flags_orphan(self, test_registry):
        """Batch code node referencing `item` without `inputs.item` is a real runtime bug.

        Runtime doesn't auto-inject the batch alias into code exec — only
        template resolution. Pass 9 must flag the missing binding as an orphan
        annotation so the user gets the fix at validate-time rather than
        "Undefined variable 'item'" at runtime.
        """
        workflow_ir = {
            "nodes": [
                {
                    "id": "batched",
                    "type": "code",
                    "params": {"code": "item: int\nresult: int = item * 2"},
                    "batch": {"items": [1, 2, 3]},
                },
            ],
            "edges": [],
        }

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, test_registry)
        orphan_errors = [d for d in errors if "has no corresponding entry in 'inputs'" in d.message]
        assert len(orphan_errors) == 1, [d.message for d in errors]
        diagnostic = orphan_errors[0]
        assert diagnostic.context["annotation_key"] == "item"
        # `item` is read in the body → canonical fix is "Add to the inputs dict".
        assert any("Add 'item' to the inputs dict" in s for s in diagnostic.suggestions or []), diagnostic.suggestions
