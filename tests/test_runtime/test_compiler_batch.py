"""Tests for batch processing compiler integration.

These tests verify that the compiler correctly builds BatchConfig in NodeConfig
when nodes have batch configuration, and that batch execution works end-to-end
through the WorkflowEngine.

FIX HISTORY:
- Updated for compile-once redesign: removed wrapper isinstance checks,
  use compile_workflow() + NodeConfig for structural assertions,
  use compile_workflow() + WorkflowEngine for execution tests.
"""

import tempfile
from pathlib import Path
from typing import Any

import pytest

from pflow.core.node import Node
from pflow.registry.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine


class ValueNode(Node):
    """Simple test node that returns a configured value.

    Interface:
    - Params: value: Any  # Value to return
    - Writes: shared["result"]: Any  # The configured value
    """

    def prep(self, shared: dict[str, Any]) -> Any:
        return self.params.get("value")

    def exec(self, prep_res: Any) -> Any:
        return prep_res

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["result"] = exec_res
        return "default"


@pytest.fixture
def test_registry():
    """Create a temp registry with test nodes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry_path = Path(tmpdir) / "test_registry.json"
        registry = Registry(registry_path)

        test_node_metadata = {
            "value-node": {
                "module": "tests.test_runtime.test_compiler_batch",
                "class_name": "ValueNode",
                "docstring": "Simple test node that returns a configured value",
                "file_path": str(Path(__file__)),
                "type": "core",
                "interface": {
                    "params": [{"name": "value", "type": "any"}],
                    "outputs": [{"name": "result", "type": "any"}],
                },
            }
        }
        registry.save(test_node_metadata)
        yield registry


class TestBatchNodeConfig:
    """Tests for batch NodeConfig creation during compilation."""

    def test_batch_node_gets_batch_config(self, test_registry):
        """Batch-configured node gets BatchConfig in its NodeConfig."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "data_source", "type": "value-node", "params": {"value": [1, 2, 3]}},
                {
                    "id": "batch_processor",
                    "type": "value-node",
                    "batch": {"items": "${data_source.result}"},
                    "params": {"value": "${item}"},
                },
            ],
            "edges": [{"from": "data_source", "to": "batch_processor"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)

        config = workflow.node_configs["batch_processor"]
        assert config.batch_config is not None
        assert config.batch_config.items_template == "${data_source.result}"

    def test_non_batch_node_has_no_batch_config(self, test_registry):
        """Node without batch config has BatchConfig = None."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "normal_node", "type": "value-node", "params": {"value": "hello"}},
            ],
            "edges": [],
        }

        workflow = compile_workflow(ir, registry=test_registry)

        config = workflow.node_configs["normal_node"]
        assert config.batch_config is None

    def test_node_config_structure_correct(self, test_registry):
        """NodeConfig captures all compilation metadata for batch and non-batch nodes."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "source", "type": "value-node", "params": {"value": ["a", "b"]}},
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},
                    "params": {"value": "${item}"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)

        # Source node: no batch, has template config for static params
        source_config = workflow.node_configs["source"]
        assert source_config.node_id == "source"
        assert source_config.node_type_name == "ValueNode"
        assert source_config.batch_config is None
        assert source_config.namespaced is True

        # Batch node: has batch config and template config
        batch_config = workflow.node_configs["batch"]
        assert batch_config.node_id == "batch"
        assert batch_config.node_type_name == "ValueNode"
        assert batch_config.batch_config is not None
        assert batch_config.template_config is not None
        assert batch_config.namespaced is True


class TestBatchConfigParsing:
    """Tests for batch configuration parsing in compiler."""

    def test_batch_config_items_parsed(self, test_registry):
        """Batch items template is correctly captured in BatchConfig."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "source", "type": "value-node", "params": {"value": [1, 2]}},
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        config = workflow.node_configs["batch"]

        assert config.batch_config is not None
        assert config.batch_config.items_template == "${source.result}"

    def test_batch_config_custom_alias(self, test_registry):
        """Custom 'as' alias is correctly captured in BatchConfig."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "source", "type": "value-node", "params": {"value": [1, 2]}},
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}", "as": "record"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        config = workflow.node_configs["batch"]

        assert config.batch_config.item_alias == "record"

    def test_batch_config_error_handling(self, test_registry):
        """Error handling mode is correctly captured in BatchConfig."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "source", "type": "value-node", "params": {"value": [1, 2]}},
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}", "error_handling": "continue"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        config = workflow.node_configs["batch"]

        assert config.batch_config.error_handling == "continue"

    def test_batch_config_defaults_applied(self, test_registry):
        """Default values applied when optional fields not specified."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "source", "type": "value-node", "params": {"value": [1, 2]}},
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        config = workflow.node_configs["batch"]

        assert config.batch_config.item_alias == "item"
        assert config.batch_config.error_handling == "fail_fast"


class TestBatchExecutionIntegration:
    """End-to-end tests for batch execution through compiler."""

    def test_batch_workflow_executes_correctly(self, test_registry):
        """Compiled batch workflow processes items correctly."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source",
                    "type": "value-node",
                    "params": {"value": ["a", "b", "c"]},
                },
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},
                    "params": {"value": "processed"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # Source node should have result
        assert "source" in shared
        assert shared["source"]["result"] == ["a", "b", "c"]

        # Batch node should have processed all items
        assert "batch" in shared
        assert shared["batch"]["count"] == 3
        assert shared["batch"]["success_count"] == 3
        assert shared["batch"]["error_count"] == 0
        assert len(shared["batch"]["results"]) == 3

    def test_batch_with_item_alias_template_resolution(self, test_registry):
        """Item alias is available for template resolution during batch execution."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source",
                    "type": "value-node",
                    "params": {"value": [10, 20, 30]},
                },
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},
                    "params": {"value": "${item}"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        results = shared["batch"]["results"]
        assert len(results) == 3
        assert results[0].get("result") == 10
        assert results[1].get("result") == 20
        assert results[2].get("result") == 30

    def test_batch_with_custom_alias_template_resolution(self, test_registry):
        """Custom alias (not 'item') works for template resolution."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source",
                    "type": "value-node",
                    "params": {"value": ["x", "y"]},
                },
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}", "as": "letter"},
                    "params": {"value": "${letter}"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        results = shared["batch"]["results"]
        assert results[0].get("result") == "x"
        assert results[1].get("result") == "y"

    def test_batch_with_nested_item_field(self, test_registry):
        """Nested field access ${item.field} resolves correctly in batch context."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source",
                    "type": "value-node",
                    "params": {
                        "value": [
                            {"name": "Alice", "age": 30},
                            {"name": "Bob", "age": 25},
                        ]
                    },
                },
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},
                    "params": {"value": "${item.name}"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        results = shared["batch"]["results"]
        assert results[0].get("result") == "Alice"
        assert results[1].get("result") == "Bob"

    def test_batch_with_namespacing_enabled(self, test_registry):
        """Batch works correctly with namespacing enabled (default)."""
        ir = {
            "ir_version": "0.1.0",
            "enable_namespacing": True,
            "nodes": [
                {
                    "id": "source",
                    "type": "value-node",
                    "params": {"value": [1, 2]},
                },
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        assert "batch" in shared
        assert "results" in shared["batch"]
        assert shared["batch"]["count"] == 2

    def test_batch_trace_initialized(self, test_registry):
        """Batch trace is captured and cleaned up after execution."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source",
                    "type": "value-node",
                    "params": {"value": ["a", "b", "c"]},
                },
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # After execution, _batch_trace is cleaned up from shared store
        assert "_batch_trace" not in shared


class TestBatchEdgeCases:
    """Edge case tests for batch compilation."""

    def test_batch_empty_items_executes(self, test_registry):
        """Batch with empty items array executes without error."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source",
                    "type": "value-node",
                    "params": {"value": []},
                },
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        assert shared["batch"]["count"] == 0
        assert shared["batch"]["results"] == []

    def test_multiple_batch_nodes_in_workflow(self, test_registry):
        """Multiple batch nodes in same workflow work independently."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source1",
                    "type": "value-node",
                    "params": {"value": [1, 2]},
                },
                {
                    "id": "batch1",
                    "type": "value-node",
                    "batch": {"items": "${source1.result}"},
                },
                {
                    "id": "source2",
                    "type": "value-node",
                    "params": {"value": ["a", "b", "c"]},
                },
                {
                    "id": "batch2",
                    "type": "value-node",
                    "batch": {"items": "${source2.result}"},
                },
            ],
            "edges": [
                {"from": "source1", "to": "batch1"},
                {"from": "batch1", "to": "source2"},
                {"from": "source2", "to": "batch2"},
            ],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        assert shared["batch1"]["count"] == 2
        assert shared["batch2"]["count"] == 3

    def test_batch_inline_array_with_templates_compiles_and_executes(self, test_registry):
        """Full pipeline: IR with inline batch array -> compile -> execute.

        This is the primary use case: different operations on same data.
        Verifies templates inside inline array elements resolve correctly.
        """
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source",
                    "type": "value-node",
                    "params": {"value": {"content": "hello world"}},
                },
                {
                    "id": "multi-op",
                    "type": "value-node",
                    "batch": {
                        "items": [
                            {"op": "upper", "data": "${source.result}"},
                            {"op": "lower", "data": "${source.result}"},
                        ]
                    },
                    "params": {"value": "${item}"},
                },
            ],
            "edges": [{"from": "source", "to": "multi-op"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # Verify inline array resolved templates and executed both items
        assert shared["multi-op"]["count"] == 2
        results = shared["multi-op"]["results"]

        # Templates inside inline array should be resolved (type preserved)
        assert results[0]["result"]["op"] == "upper"
        assert results[0]["result"]["data"] == {"content": "hello world"}
        assert results[1]["result"]["op"] == "lower"
        assert results[1]["result"]["data"] == {"content": "hello world"}


class TestInputsAsTemplateContext:
    """Tests for inputs-as-context through the full compiled pipeline.

    Exercises the engine pipeline (template resolution -> batch -> namespace)
    to verify that 'inputs' values are available as template context for other params.
    """

    def test_batch_inputs_resolve_in_other_params(self, test_registry):
        """Inputs mapping from batch item fields resolves in another param."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source",
                    "type": "value-node",
                    "params": {
                        "value": [
                            {"name": "Alice", "role": "engineer"},
                            {"name": "Bob", "role": "designer"},
                        ]
                    },
                },
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},
                    "params": {
                        "inputs": {
                            "person_name": "${item.name}",
                            "person_role": "${item.role}",
                        },
                        "value": "Name=${person_name}, Role=${person_role}",
                    },
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        results = shared["batch"]["results"]
        assert len(results) == 2
        assert results[0]["result"] == "Name=Alice, Role=engineer"
        assert results[1]["result"] == "Name=Bob, Role=designer"

    def test_static_inputs_resolve_in_other_params(self, test_registry):
        """Static inputs (no templates) also enrich the template context."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "node",
                    "type": "value-node",
                    "params": {
                        "inputs": {"greeting": "hello", "target": "world"},
                        "value": "${greeting} ${target}",
                    },
                },
            ],
            "edges": [],
        }

        workflow = compile_workflow(ir, registry=test_registry)
        shared: dict[str, Any] = dict(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        assert shared["node"]["result"] == "hello world"
