"""Tests for ${item.field} validation against inferred item structure.

Tests batch item field validation (Pass 8) through the orchestrator.
Validates that ${item.field} references resolve against the inferred
structure of batch items from upstream results arrays.
"""

from unittest.mock import Mock

from pflow.core.diagnostic import Severity
from pflow.runtime.template_validation import validate_workflow_templates
from tests.shared.diagnostic_helpers import split_template_diagnostics


def create_mock_registry():
    """Create a mock registry with test node metadata."""
    registry = Mock()

    nodes_metadata = {
        "llm": {
            "interface": {
                "inputs": [{"key": "prompt", "type": "str", "description": "LLM prompt"}],
                "outputs": [
                    {"key": "response", "type": "any", "description": "Model's response"},
                    {
                        "key": "llm_usage",
                        "type": "dict",
                        "description": "Token usage metrics",
                        "structure": {
                            "model": {"type": "str", "description": "Model identifier"},
                            "input_tokens": {"type": "int", "description": "Input tokens"},
                            "output_tokens": {"type": "int", "description": "Output tokens"},
                        },
                    },
                ],
                "params": [],
                "actions": ["default", "error"],
            }
        },
        "shell": {
            "interface": {
                "inputs": [{"key": "command", "type": "str", "description": "Shell command"}],
                "outputs": [
                    {"key": "stdout", "type": "str", "description": "Standard output"},
                    {"key": "stderr", "type": "str", "description": "Standard error"},
                    {"key": "returncode", "type": "int", "description": "Exit code"},
                ],
                "params": [],
                "actions": ["default", "error"],
            }
        },
    }

    def get_nodes_metadata(node_types):
        result = {}
        for node_type in node_types:
            if node_type in nodes_metadata:
                result[node_type] = nodes_metadata[node_type]
        return result

    registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata)
    return registry


class TestBatchItemFieldValidation:
    """Tests for ${item.field} validation against inferred item structure."""

    def test_valid_field_passes(self):
        """${item.response} should pass when items come from LLM batch results."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Analyze: ${item.response}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_invalid_field_caught(self):
        """${item.nonexistent} should produce error when field not in inferred structure."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Analyze: ${item.nonexistent}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 1
        assert "nonexistent" in errors[0].message
        assert "not available on batch items" in errors[0].message
        assert errors[0].context is not None
        assert any("response" in field for field in errors[0].context.get("available_fields", []))

    def test_did_you_mean_suggestion(self):
        """${item.resp} should suggest ${item.response}."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Analyze: ${item.resp}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 1
        assert errors[0].context is not None
        similar = errors[0].context.get("similar_names") or []
        assert any("item.response" in name for name in similar), (
            f"Expected 'item.response' in similar_names: {errors[0]}"
        )

    def test_permissive_when_items_from_workflow_input(self):
        """${item.anything} should pass when items come from a workflow input."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item.anything}"},
                },
            ],
            "edges": [],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_permissive_when_items_is_inline_array(self):
        """${item.anything} should pass when items is an inline array."""
        workflow_ir = {
            "inputs": {},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": ["a", "b", "c"]},
                    "params": {"prompt": "Process: ${item.anything}"},
                },
            ],
            "edges": [],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_permissive_when_items_from_non_batch_source(self):
        """${item.anything} should pass when items come from a non-batch output (e.g., stdout)."""
        workflow_ir = {
            "inputs": {},
            "nodes": [
                {
                    "id": "fetch",
                    "type": "shell",
                    "params": {"command": "echo '[1,2,3]'"},
                },
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${fetch.stdout}"},
                    "params": {"prompt": "Process: ${item.anything}"},
                },
            ],
            "edges": [{"from": "fetch", "to": "process"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_multiple_batch_nodes_validated_independently(self):
        """Each batch node should validate item fields against its own source."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "step-a",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "step-b",
                    "type": "shell",
                    "batch": {"items": "${data}"},
                    "params": {"command": "echo ${item}"},
                },
                {
                    "id": "use-a",
                    "type": "llm",
                    "batch": {"items": "${step-a.results}"},
                    "params": {"prompt": "LLM result: ${item.response}"},
                },
                {
                    "id": "use-b",
                    "type": "llm",
                    "batch": {"items": "${step-b.results}"},
                    "params": {"prompt": "Shell result: ${item.stdout}"},
                },
            ],
            "edges": [
                {"from": "step-a", "to": "use-a"},
                {"from": "step-b", "to": "use-b"},
            ],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_multiple_batch_nodes_wrong_field_caught(self):
        """Using shell field on LLM items should be caught."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Got: ${item.stdout}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 1
        assert "stdout" in errors[0].message
        assert "not available on batch items" in errors[0].message

    def test_custom_alias(self):
        """Custom alias via as: should validate correctly."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}", "as": "src"},
                    "params": {"prompt": "Analyze: ${src.response}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_custom_alias_invalid_field_caught(self):
        """Invalid field with custom alias should be caught."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}", "as": "src"},
                    "params": {"prompt": "Analyze: ${src.nonexistent}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 1
        assert "nonexistent" in errors[0].message

    def test_coalesce_in_items_template(self):
        """${z.results ?? a.results} should infer structure from FIRST operand, not alphabetical.

        Uses node IDs where alphabetical order differs from ?? order:
        z-primary (LLM, has response) comes first in ??, but last alphabetically.
        a-fallback (shell, has stdout) comes second in ??, but first alphabetically.
        ${item.response} should pass because the primary (first ??) is an LLM node.
        """
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "z-primary",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "a-fallback",
                    "type": "shell",
                    "batch": {"items": "${data}"},
                    "params": {"command": "echo ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${z-primary.results ?? a-fallback.results}"},
                    "params": {"prompt": "Analyze: ${item.response}"},
                },
            ],
            "edges": [
                {"from": "z-primary", "to": "analyze"},
                {"from": "a-fallback", "to": "analyze"},
            ],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_bare_item_not_checked(self):
        """${item} without field access should not trigger field validation."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Analyze: ${item}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_item_field_original_input_accessible(self):
        """${item.item} (original batch input) should always be valid."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Original: ${item.item}, Result: ${item.response}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_error_shows_available_fields(self):
        """Error message should list all available fields on item."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "shell",
                    "batch": {"items": "${data}"},
                    "params": {"command": "echo ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Result: ${item.content}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 1
        # Should show available shell output fields
        assert errors[0].context is not None
        assert any("${item.stdout}" in field for field in errors[0].context.get("available_fields", []))
        assert any("${item.item}" in field for field in errors[0].context.get("available_fields", []))

    def test_error_shows_items_source(self):
        """Error message should show where items come from."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "fetch",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${fetch.results}"},
                    "params": {"prompt": "Result: ${item.content}"},
                },
            ],
            "edges": [{"from": "fetch", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 1
        assert "${fetch.results}" in errors[0].message
        # Must NOT double-wrap: ${${fetch.results}} would be wrong
        assert "${${" not in errors[0].message

    def test_deduplicate_errors_for_same_field(self):
        """Multiple references to same invalid field should produce one error."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "First: ${item.bad_field}, Second: ${item.bad_field}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 1

    def test_workflow_batch_item_fields_validated(self):
        """${item.field} on workflow batch results should validate against child outputs.

        This is the exact scenario from the batch-output-ux issue: a batched workflow
        node feeds into a downstream batch node. The child workflow's declared outputs
        (e.g., content, source_type) should be the known item fields.
        """
        child_ir = {
            "nodes": [{"id": "step", "type": "llm", "params": {"prompt": "hi"}}],
            "edges": [],
            "outputs": {
                "content": {"type": "str"},
                "source_type": {"type": "str"},
            },
        }
        workflow_ir = {
            "inputs": {"sources": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "fetch-sources",
                    "type": "workflow",
                    "batch": {"items": "${sources}"},
                    "params": {"workflow_ir": child_ir, "url": "${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${fetch-sources.results}"},
                    "params": {"prompt": "Analyze: ${item.content} from ${item.source_type}"},
                },
            ],
            "edges": [{"from": "fetch-sources", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"sources": ["a"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_workflow_batch_item_invalid_field_caught(self):
        """Invalid field on workflow batch items should be caught with child output fields shown."""
        child_ir = {
            "nodes": [{"id": "step", "type": "llm", "params": {"prompt": "hi"}}],
            "edges": [],
            "outputs": {
                "content": {"type": "str"},
                "source_type": {"type": "str"},
            },
        }
        workflow_ir = {
            "inputs": {"sources": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "fetch-sources",
                    "type": "workflow",
                    "batch": {"items": "${sources}"},
                    "params": {"workflow_ir": child_ir, "url": "${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${fetch-sources.results}"},
                    "params": {"prompt": "Got: ${item.stdout}"},
                },
            ],
            "edges": [{"from": "fetch-sources", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"sources": ["a"]}, registry)
        assert len(errors) == 1
        assert "stdout" in errors[0].message
        assert "not available on batch items" in errors[0].message
        # Should show the workflow's actual output fields
        assert errors[0].context is not None
        assert any("content" in field for field in errors[0].context.get("available_fields", []))
        assert any("source_type" in field for field in errors[0].context.get("available_fields", []))

    def test_workflow_batch_unresolvable_child_permissive(self):
        """When workflow child can't be resolved (dynamic path), fall back to permissive."""
        workflow_ir = {
            "inputs": {
                "sources": {"type": "array", "required": True},
                "workflow_path": {"type": "str", "required": True},
            },
            "nodes": [
                {
                    "id": "fetch-sources",
                    "type": "workflow",
                    "batch": {"items": "${sources}"},
                    "params": {"workflow": "${workflow_path}", "input": "${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${fetch-sources.results}"},
                    "params": {"prompt": "Got: ${item.anything_goes}"},
                },
            ],
            "edges": [{"from": "fetch-sources", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(
            workflow_ir, {"sources": ["a"], "workflow_path": "some.pflow.md"}, registry
        )
        # Should NOT produce item field errors — structure is unknown
        batch_item_errors = [d for d in errors if "not available on batch items" in d.message]
        assert len(batch_item_errors) == 0, f"Should be permissive for unresolvable child: {batch_item_errors}"

    def test_nested_item_path_valid(self):
        """${item.llm_usage.model} should pass when model exists in llm_usage structure."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Model: ${item.llm_usage.model}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_nested_item_path_invalid_caught(self):
        """${item.llm_usage.nope} should fail — 'nope' doesn't exist in llm_usage structure."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Bad: ${item.llm_usage.nope}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 1
        assert "nope" in errors[0].message
        assert "llm_usage" in errors[0].message
        # Should show available nested fields
        assert errors[0].context is not None
        assert any("model" in field for field in errors[0].context.get("available_fields", []))

    def test_nested_item_path_invalid_shows_suggestions(self):
        """${item.llm_usage.mod} should suggest ${item.llm_usage.model}."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Bad: ${item.llm_usage.mod}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 1
        assert errors[0].context is not None
        similar = errors[0].context.get("similar_names") or []
        assert any("item.llm_usage.model" in name for name in similar), (
            f"Expected 'item.llm_usage.model' in similar_names: {errors[0]}"
        )

    def test_nested_item_path_on_any_type_permissive(self):
        """${item.response.anything} should pass — response has type 'any'."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Deep: ${item.response.anything.nested}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        registry = create_mock_registry()
        errors, _warnings = split_template_diagnostics(workflow_ir, {"data": ["a", "b"]}, registry)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_batch_item_field_miss_preserves_batch_context(self):
        """Top-level batch item misses should preserve source and available field metadata."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Analyze: ${item.resp}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        diagnostics = validate_workflow_templates(workflow_ir, {"data": ["a", "b"]}, create_mock_registry())
        errors = [d for d in diagnostics if d.severity == Severity.ERROR]

        assert errors
        diagnostic = errors[0]
        assert diagnostic.context is not None
        assert diagnostic.context.get("batch_alias") == "item"
        assert diagnostic.context.get("items_source") == "${process.results}"
        assert diagnostic.context.get("available_fields_label") == "batch item fields"
        assert diagnostic.context.get("available_fields")

    def test_batch_item_nested_miss_preserves_parent_path(self):
        """Nested batch item misses should preserve parent-path metadata."""
        workflow_ir = {
            "inputs": {"data": {"type": "array", "required": True}},
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${data}"},
                    "params": {"prompt": "Process: ${item}"},
                },
                {
                    "id": "analyze",
                    "type": "llm",
                    "batch": {"items": "${process.results}"},
                    "params": {"prompt": "Bad: ${item.llm_usage.mod}"},
                },
            ],
            "edges": [{"from": "process", "to": "analyze"}],
        }

        diagnostics = validate_workflow_templates(workflow_ir, {"data": ["a", "b"]}, create_mock_registry())
        errors = [d for d in diagnostics if d.severity == Severity.ERROR]

        assert errors
        diagnostic = errors[0]
        assert diagnostic.context is not None
        assert diagnostic.context.get("parent_path") == "item.llm_usage"
        assert diagnostic.context.get("parent_type") == "dict"
        assert diagnostic.context.get("available_fields_label") == "nested fields"
