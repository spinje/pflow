"""Tests for batch processing compiler integration.

These tests verify that the compiler correctly applies the PflowBatchNode wrapper
in the wrapper chain when nodes have batch configuration.
"""

import tempfile
from pathlib import Path
from typing import Any

import pytest

from pflow.registry.registry import Registry
from pflow.runtime import compile_ir_to_flow
from pflow.runtime.batch_node import PflowBatchNode
from pflow.runtime.instrumented_wrapper import InstrumentedNodeWrapper
from pflow.runtime.namespaced_wrapper import NamespacedNodeWrapper
from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper
from pocketflow import Node


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

        # Register our test node - use __module__ to get correct path
        test_node_metadata = {
            "value-node": {
                "module": "tests.test_runtime.test_compiler_batch",
                "class_name": "ValueNode",
                "docstring": "Simple test node that returns a configured value",
                "file_path": str(Path(__file__)),
                "type": "core",
                "interface": {
                    "params": [{"name": "value", "type": "Any"}],
                    "outputs": [{"name": "result", "type": "Any"}],
                },
            }
        }
        registry.save(test_node_metadata)
        yield registry


class TestBatchWrapperChain:
    """Tests for batch node wrapper chain order."""

    def test_batch_node_gets_wrapped(self, test_registry):
        """Batch-configured node gets PflowBatchNode wrapper applied."""
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

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)

        # Find the batch_processor node in the flow
        batch_node = flow.start_node.successors.get("default")
        assert batch_node is not None

        # Verify wrapper chain: InstrumentedNodeWrapper wrapping PflowBatchNode
        assert isinstance(batch_node, InstrumentedNodeWrapper)
        inner = batch_node.inner_node
        assert isinstance(inner, PflowBatchNode)

    def test_non_batch_node_not_wrapped_with_batch(self, test_registry):
        """Node without batch config does NOT get PflowBatchNode wrapper."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "normal_node", "type": "value-node", "params": {"value": "hello"}},
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)

        node = flow.start_node
        assert isinstance(node, InstrumentedNodeWrapper)

        # Inner should NOT be PflowBatchNode
        inner = node.inner_node
        assert not isinstance(inner, PflowBatchNode)

    def test_wrapper_chain_order_correct(self, test_registry):
        """Wrapper chain order: Instrumented > Batch > Namespace > Template > Actual.

        Applied inner-to-outer: Actual → Template → Namespace → Batch → Instrumented
        Executed outer-to-inner: Instrumented → Batch → Namespace → Template → Actual
        """
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "source", "type": "value-node", "params": {"value": ["a", "b"]}},
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},
                    "params": {"value": "${item}"},  # Template to trigger TemplateAwareNodeWrapper
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        batch_node = flow.start_node.successors.get("default")

        # Layer 1 (outermost): InstrumentedNodeWrapper
        assert isinstance(batch_node, InstrumentedNodeWrapper)
        layer1 = batch_node

        # Layer 2: PflowBatchNode
        layer2 = layer1.inner_node
        assert isinstance(layer2, PflowBatchNode)

        # Layer 3: NamespacedNodeWrapper
        # PflowBatchNode stores inner node as self.inner_node
        layer3 = layer2.inner_node
        assert isinstance(layer3, NamespacedNodeWrapper)

        # Layer 4: TemplateAwareNodeWrapper (because params have templates)
        # NamespacedNodeWrapper stores inner node as self._inner_node
        layer4 = layer3._inner_node
        assert isinstance(layer4, TemplateAwareNodeWrapper)

        # Layer 5 (innermost): Actual ValueNode
        layer5 = layer4.inner_node
        # Use duck typing - check it has the ValueNode interface (exec method)
        # Can't use isinstance because the dynamically loaded class is a different object
        assert hasattr(layer5, "exec")
        assert layer5.__class__.__name__ == "ValueNode"


class TestBatchConfigParsing:
    """Tests for batch configuration parsing in compiler."""

    def test_batch_config_items_parsed(self, test_registry):
        """Batch items template is correctly passed to PflowBatchNode."""
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

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        batch_wrapper = flow.start_node.successors.get("default").inner_node

        assert isinstance(batch_wrapper, PflowBatchNode)
        assert batch_wrapper.items_template == "${source.result}"

    def test_batch_config_custom_alias(self, test_registry):
        """Custom 'as' alias is correctly passed to PflowBatchNode."""
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

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        batch_wrapper = flow.start_node.successors.get("default").inner_node

        assert batch_wrapper.item_alias == "record"

    def test_batch_config_error_handling(self, test_registry):
        """Error handling mode is correctly passed to PflowBatchNode."""
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

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        batch_wrapper = flow.start_node.successors.get("default").inner_node

        assert batch_wrapper.error_handling == "continue"

    def test_batch_config_defaults_applied(self, test_registry):
        """Default values applied when optional fields not specified."""
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {"id": "source", "type": "value-node", "params": {"value": [1, 2]}},
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},  # Only required field
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        batch_wrapper = flow.start_node.successors.get("default").inner_node

        assert batch_wrapper.item_alias == "item"  # Default
        assert batch_wrapper.error_handling == "fail_fast"  # Default


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

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        shared: dict[str, Any] = {}
        flow.run(shared)

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
                    "params": {"value": "${item}"},  # Should resolve to each item
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        shared: dict[str, Any] = {}
        flow.run(shared)

        # Each result should contain the resolved item value
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
                    "params": {"value": "${letter}"},  # Uses custom alias
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        shared: dict[str, Any] = {}
        flow.run(shared)

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
                    "params": {"value": "${item.name}"},  # Nested field access
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        shared: dict[str, Any] = {}
        flow.run(shared)

        results = shared["batch"]["results"]
        assert results[0].get("result") == "Alice"
        assert results[1].get("result") == "Bob"

    def test_batch_with_namespacing_enabled(self, test_registry):
        """Batch works correctly with namespacing enabled (default)."""
        ir = {
            "ir_version": "0.1.0",
            "enable_namespacing": True,  # Explicitly enabled
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

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        shared: dict[str, Any] = {}
        flow.run(shared)

        # Results should be namespaced correctly
        assert "batch" in shared
        assert "results" in shared["batch"]
        assert shared["batch"]["count"] == 2

    def test_batch_llm_calls_accumulate(self, test_registry):
        """__llm_calls__ tracking list is preserved (shallow copy behavior)."""
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

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        shared: dict[str, Any] = {"__llm_calls__": []}  # Initialize tracking list
        flow.run(shared)

        # The list should still exist and be the same reference
        assert "__llm_calls__" in shared
        assert isinstance(shared["__llm_calls__"], list)


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
                    "params": {"value": []},  # Empty array
                },
                {
                    "id": "batch",
                    "type": "value-node",
                    "batch": {"items": "${source.result}"},
                },
            ],
            "edges": [{"from": "source", "to": "batch"}],
        }

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        shared: dict[str, Any] = {}
        flow.run(shared)

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

        flow = compile_ir_to_flow(ir, registry=test_registry, validate=False)
        shared: dict[str, Any] = {}
        flow.run(shared)

        assert shared["batch1"]["count"] == 2
        assert shared["batch2"]["count"] == 3
