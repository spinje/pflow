"""Tests for flow construction functionality in the compiler module.

FIX HISTORY:
- Removed MockNode class that tested mock behavior instead of real behavior
- Replace all mocking with real node implementations and test registries
- Focus on testing actual workflow construction and execution
- Test behavior, not implementation details like mock call counts
- Updated for compile-once redesign: removed wrapper isinstance checks,
  use compile_workflow() + NodeConfig for structural assertions,
  use compile_ir_to_flow() shim for execution tests.
- Migrated from compile_ir_to_flow shim to compile_workflow + WorkflowEngine
  for all execution tests.
"""

import tempfile
from pathlib import Path

import pytest

from pflow.core.node import BaseNode
from pflow.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.compilation.compiler import (
    CompilationError,
    _get_start_node,
    _instantiate_nodes_for_workflow,
    _wire_nodes,
)
from pflow.runtime.engine import WorkflowEngine


def create_test_registry() -> tuple[Registry, dict]:
    """Create a test registry with real test nodes for consistent testing."""
    registry_dir = tempfile.mkdtemp()
    registry_path = Path(registry_dir) / "test.json"
    registry = Registry(registry_path)

    # Register real test nodes
    test_nodes_metadata = {
        "test-node": {
            "module": "tests.shared.mock_nodes",
            "class_name": "ExampleNode",
            "docstring": "Test node for validation",
            "file_path": "tests/shared/mock_nodes.py",
        },
        "test-node-retry": {
            "module": "tests.shared.mock_nodes",
            "class_name": "RetryExampleNode",
            "docstring": "Test node with retry",
            "file_path": "tests/shared/mock_nodes.py",
        },
    }
    registry.save(test_nodes_metadata)
    return registry, test_nodes_metadata


class TestInstantiateNodes:
    """Test the _instantiate_nodes_for_workflow helper with real nodes.

    After the compile-once redesign, _instantiate_nodes was replaced by
    _instantiate_nodes_for_workflow which returns (nodes, configs) —
    bare nodes + NodeConfig metadata instead of wrapper chains.
    """

    def test_instantiate_single_node_creates_working_node(self):
        """Test instantiating a single node creates a working bare node instance."""
        registry, _ = create_test_registry()

        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}]}

        nodes, configs = _instantiate_nodes_for_workflow(ir_dict, registry, {})

        # Verify: one bare node created with correct config
        assert len(nodes) == 1
        assert "node1" in nodes
        node = nodes["node1"]

        # Node is a bare BaseNode instance (no wrappers)
        assert isinstance(node, BaseNode)
        assert node.node_id == "node1"

        # Config captures metadata
        assert "node1" in configs
        config = configs["node1"]
        assert config.node_id == "node1"
        assert config.node_type_name == "ExampleNode"
        assert config.namespaced is True  # default

        # Test the bare node directly
        shared_store = {"test_input": "hello"}
        result = node.prep(shared_store)
        processed = node.exec(result)
        action = node.post(shared_store, result, processed)

        assert shared_store["test_output"] == "Processed: hello"
        assert action == "default"

    def test_instantiate_multiple_nodes_creates_different_instances(self):
        """Test instantiating multiple nodes creates separate working instances."""
        registry, _ = create_test_registry()

        ir_dict = {
            "nodes": [
                {"id": "node1", "type": "test-node"},
                {"id": "node2", "type": "test-node-retry"},
                {"id": "node3", "type": "test-node"},
            ]
        }

        nodes, configs = _instantiate_nodes_for_workflow(ir_dict, registry, {})

        # Verify: correct number of distinct bare node instances
        assert len(nodes) == 3
        assert all(key in nodes for key in ["node1", "node2", "node3"])

        # All are bare BaseNode instances
        assert all(isinstance(n, BaseNode) for n in nodes.values())

        # Different instances (not the same object)
        assert nodes["node1"] is not nodes["node3"]
        assert type(nodes["node1"]).__name__ == "ExampleNode"
        assert type(nodes["node2"]).__name__ == "RetryExampleNode"
        assert type(nodes["node3"]).__name__ == "ExampleNode"

        # Configs track node types correctly
        assert configs["node1"].node_type_name == "ExampleNode"
        assert configs["node2"].node_type_name == "RetryExampleNode"
        assert configs["node3"].node_type_name == "ExampleNode"

        # Test all nodes can execute independently
        for node_id, node in nodes.items():
            if type(node).__name__ == "RetryExampleNode":
                shared_store = {"retry_input": f"input-{node_id}"}
                expected_output_key = "retry_output"
            else:
                shared_store = {"test_input": f"input-{node_id}"}
                expected_output_key = "test_output"

            result = node.prep(shared_store)
            processed = node.exec(result)
            node.post(shared_store, result, processed)

            assert expected_output_key in shared_store
            assert f"input-{node_id}" in shared_store[expected_output_key]

    def test_instantiate_with_params_sets_params_correctly(self):
        """Test instantiating nodes with parameters actually sets them on the node."""
        registry, _ = create_test_registry()

        ir_dict = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {"custom_param": "test_value"},
                }
            ]
        }

        nodes, _configs = _instantiate_nodes_for_workflow(ir_dict, registry, {})

        assert len(nodes) == 1
        node = nodes["node1"]

        # Bare node — params set directly
        assert isinstance(node, BaseNode)
        assert hasattr(node, "params")
        assert node.params.get("custom_param") == "test_value"

        # Node still functions correctly with params
        shared_store = {"test_input": "param_test"}
        result = node.prep(shared_store)
        processed = node.exec(result)
        action = node.post(shared_store, result, processed)

        assert shared_store["test_output"] == "Processed: param_test"
        assert action == "default"

    def test_instantiate_with_nonexistent_node_type_raises_error(self):
        """Test error handling when node type doesn't exist in registry."""
        registry, _ = create_test_registry()

        ir_dict = {"nodes": [{"id": "node1", "type": "nonexistent-node"}]}

        with pytest.raises(CompilationError) as exc_info:
            _instantiate_nodes_for_workflow(ir_dict, registry, {})

        error = exc_info.value
        assert error.node_id == "node1"
        assert "nonexistent-node" in str(error)
        assert error.phase == "node_resolution"

    def test_instantiate_with_no_params_works_correctly(self):
        """Test that nodes work correctly when no params are provided."""
        registry, _ = create_test_registry()

        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}]}

        nodes, _configs = _instantiate_nodes_for_workflow(ir_dict, registry, {})

        assert len(nodes) == 1
        node = nodes["node1"]
        assert isinstance(node, BaseNode)

        # Node functions correctly without params
        shared_store = {"test_input": "no_params_test"}
        result = node.prep(shared_store)
        processed = node.exec(result)
        action = node.post(shared_store, result, processed)

        assert shared_store["test_output"] == "Processed: no_params_test"
        assert action == "default"


class TestWireNodes:
    """Test the _wire_nodes helper function with real nodes and actual workflow execution.

    _wire_nodes operates on bare nodes using PocketFlow's >> operator.
    After wiring, nodes have successors set. Execution is done via WorkflowEngine.
    """

    def test_wire_default_connection_creates_working_flow(self):
        """Test wiring nodes with default (>>) connection produces working workflow."""
        registry, _ = create_test_registry()

        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}, {"id": "node2", "type": "test-node"}]}
        nodes, _configs = _instantiate_nodes_for_workflow(ir_dict, registry, {})

        edges = [{"source": "node1", "target": "node2"}]
        _wire_nodes(nodes, edges)

        # Verify wiring: node1's default successor is node2
        assert nodes["node1"].successors.get("default") is nodes["node2"]

    def test_wire_chain_connection_executes_sequentially(self):
        """Test wiring a chain of nodes connects them in order."""
        registry, _ = create_test_registry()

        ir_dict = {
            "nodes": [
                {"id": "node1", "type": "test-node"},
                {"id": "node2", "type": "test-node"},
                {"id": "node3", "type": "test-node"},
            ]
        }
        nodes, _configs = _instantiate_nodes_for_workflow(ir_dict, registry, {})

        edges = [
            {"source": "node1", "target": "node2"},
            {"source": "node2", "target": "node3"},
        ]
        _wire_nodes(nodes, edges)

        # Verify chain: node1 -> node2 -> node3
        assert nodes["node1"].successors.get("default") is nodes["node2"]
        assert nodes["node2"].successors.get("default") is nodes["node3"]

    def test_wire_missing_source_node_raises_helpful_error(self):
        """Test error when edge references non-existent source."""
        registry, _ = create_test_registry()

        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}]}
        nodes, _configs = _instantiate_nodes_for_workflow(ir_dict, registry, {})

        edges = [{"source": "missing", "target": "node1"}]

        with pytest.raises(CompilationError) as exc_info:
            _wire_nodes(nodes, edges)

        error = exc_info.value
        assert error.phase == "flow_wiring"
        assert error.node_id == "missing"
        assert "non-existent source node" in str(error)
        assert "Available nodes: node1" in error.suggestion

    def test_wire_missing_target_node_raises_helpful_error(self):
        """Test error when edge references non-existent target."""
        registry, _ = create_test_registry()

        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}]}
        nodes, _configs = _instantiate_nodes_for_workflow(ir_dict, registry, {})

        edges = [{"source": "node1", "target": "missing"}]

        with pytest.raises(CompilationError) as exc_info:
            _wire_nodes(nodes, edges)

        error = exc_info.value
        assert error.phase == "flow_wiring"
        assert error.node_id == "missing"
        assert "non-existent target node" in str(error)
        assert "Available nodes: node1" in error.suggestion

    def test_wire_with_no_edges_leaves_nodes_unconnected(self):
        """Test wiring with no edges leaves individual nodes that can run independently."""
        registry, _ = create_test_registry()

        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}, {"id": "node2", "type": "test-node"}]}
        nodes, _configs = _instantiate_nodes_for_workflow(ir_dict, registry, {})

        _wire_nodes(nodes, [])

        # Each node should have no successors
        assert not nodes["node1"].successors
        assert not nodes["node2"].successors

        # Each node should work independently
        for node_id, node in nodes.items():
            shared_store = {"test_input": f"isolated_{node_id}"}
            result = node.prep(shared_store)
            processed = node.exec(result)
            action = node.post(shared_store, result, processed)

            assert shared_store["test_output"] == f"Processed: isolated_{node_id}"
            assert action == "default"


class TestGetStartNode:
    """Test the _get_start_node helper function with real nodes."""

    def test_get_start_node_uses_first_node_by_default(self):
        """Test using first node as start when no explicit start specified."""
        registry, _ = create_test_registry()

        ir_dict = {"nodes": [{"id": "node2", "type": "test-node"}, {"id": "node1", "type": "test-node"}]}
        nodes, _configs = _instantiate_nodes_for_workflow(ir_dict, registry, {})

        start = _get_start_node(nodes, ir_dict)

        # First node in IR is used
        assert start is nodes["node2"]

        # Start node can execute
        shared_store = {"test_input": "start_test"}
        result = start.prep(shared_store)
        processed = start.exec(result)
        action = start.post(shared_store, result, processed)

        assert shared_store["test_output"] == "Processed: start_test"
        assert action == "default"

    def test_get_start_node_respects_explicit_start_node(self):
        """Test using explicit start_node when specified."""
        registry, _ = create_test_registry()

        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}, {"id": "node2", "type": "test-node"}]}
        nodes, _configs = _instantiate_nodes_for_workflow(ir_dict, registry, {})

        ir_dict["start_node"] = "node2"

        start = _get_start_node(nodes, ir_dict)

        assert start is nodes["node2"]

        # The explicitly chosen start node can execute
        shared_store = {"test_input": "explicit_start"}
        result = start.prep(shared_store)
        processed = start.exec(result)
        start.post(shared_store, result, processed)

        assert shared_store["test_output"] == "Processed: explicit_start"

    def test_get_start_node_with_no_nodes_raises_helpful_error(self):
        """Test error when no nodes exist provides helpful context."""
        nodes = {}
        ir_dict = {"nodes": []}

        with pytest.raises(CompilationError) as exc_info:
            _get_start_node(nodes, ir_dict)

        error = exc_info.value
        assert error.phase == "start_detection"
        assert "Cannot create flow with no nodes" in str(error)

    def test_get_start_node_with_invalid_explicit_start_raises_helpful_error(self):
        """Test error when explicit start_node doesn't exist provides helpful context."""
        registry, _ = create_test_registry()

        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}]}
        nodes, _configs = _instantiate_nodes_for_workflow(ir_dict, registry, {})

        ir_dict["start_node"] = "missing"

        with pytest.raises(CompilationError) as exc_info:
            _get_start_node(nodes, ir_dict)

        error = exc_info.value
        assert error.phase == "start_detection"
        assert "Could not determine start node" in str(error)


class TestCompileWorkflow:
    """Test the compile_workflow function with real integration testing.

    Uses compile_workflow() + WorkflowEngine for both structural assertions
    and execution tests.

    FIX HISTORY:
    - Originally TestCompileIrToFlow using the backward-compat shim.
    - Migrated to compile_workflow + WorkflowEngine (no shim).
    """

    def test_compile_and_execute_simple_flow_end_to_end(self):
        """Test compiling and executing a simple linear flow works end-to-end."""
        registry, _ = create_test_registry()

        ir_dict = {
            "nodes": [
                {"id": "input", "type": "test-node"},
                {"id": "process", "type": "test-node"},
                {"id": "output", "type": "test-node-retry"},
            ],
            "edges": [
                {"source": "input", "target": "process"},
                {"source": "process", "target": "output"},
            ],
        }

        # Structural checks
        workflow = compile_workflow(ir_dict, registry)
        assert workflow is not None
        assert workflow.start_node is not None
        assert "input" in workflow.node_configs
        assert "process" in workflow.node_configs
        assert "output" in workflow.node_configs

        # Execution via WorkflowEngine
        shared_store: dict = {"test_input": "integration_test", "retry_input": "retry_test"}
        shared_store.update(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared_store)

        # Verify the entire workflow executed through all nodes (with namespacing)
        assert "output" in shared_store
        assert "retry_output" in shared_store["output"]
        assert "input" in shared_store
        assert "process" in shared_store

    def test_compile_with_node_parameters_end_to_end(self):
        """Test compiling and executing flow with node parameters works correctly."""
        registry, _ = create_test_registry()

        ir_dict = {
            "nodes": [{"id": "node1", "type": "test-node", "params": {"custom_param": "param_value"}}],
            "edges": [],
        }

        workflow = compile_workflow(ir_dict, registry)
        assert workflow is not None

        shared_store: dict = {"test_input": "param_test"}
        shared_store.update(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared_store)

        # Verify workflow executed correctly with parameters (with namespacing)
        assert "node1" in shared_store
        assert "test_output" in shared_store["node1"]
        assert "param_test" in shared_store["node1"]["test_output"]

    def test_compile_from_json_string_works_end_to_end(self):
        """Test compiling from JSON string input produces working workflow."""
        registry, _ = create_test_registry()

        ir_json = '{"nodes": [{"id": "test", "type": "test-node"}], "edges": []}'

        workflow = compile_workflow(ir_json, registry)
        assert workflow is not None

        shared_store: dict = {"test_input": "json_test"}
        shared_store.update(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared_store)

        # With namespacing
        assert "test" in shared_store
        assert "test_output" in shared_store["test"]
        assert "json_test" in shared_store["test"]["test_output"]

    def test_compile_with_invalid_json_raises_json_decode_error(self):
        """Test error on invalid JSON string provides clear error."""
        registry, _ = create_test_registry()

        ir_json = '{"nodes": [invalid json}'

        with pytest.raises(Exception) as exc_info:
            compile_workflow(ir_json, registry)

        assert exc_info.type.__name__ == "JSONDecodeError"

    def test_compile_with_validation_error_provides_helpful_context(self):
        """Test error during IR validation provides helpful debugging context."""
        registry, _ = create_test_registry()

        ir_dict = {"edges": []}  # Missing nodes

        with pytest.raises(CompilationError) as exc_info:
            compile_workflow(ir_dict, registry)

        error = exc_info.value
        assert error.phase == "validation"
        assert "Missing 'nodes' key" in str(error)
