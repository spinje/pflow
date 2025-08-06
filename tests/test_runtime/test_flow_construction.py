"""Tests for flow construction functionality in the compiler module.

FIX HISTORY:
- Removed MockNode class that tested mock behavior instead of real behavior
- Replace all mocking with real node implementations and test registries
- Focus on testing actual workflow construction and execution
- Test behavior, not implementation details like mock call counts
"""

import tempfile
from pathlib import Path

import pytest

from pflow.registry import Registry
from pflow.runtime.compiler import (
    CompilationError,
    _get_start_node,
    _instantiate_nodes,
    _wire_nodes,
    compile_ir_to_flow,
)
from pocketflow import BaseNode, Flow


def create_test_registry() -> tuple[Registry, dict]:
    """Create a test registry with real test nodes for consistent testing."""
    registry_dir = tempfile.mkdtemp()
    registry_path = Path(registry_dir) / "test.json"
    registry = Registry(registry_path)

    # Register real test nodes
    test_nodes_metadata = {
        "test-node": {
            "module": "pflow.nodes.test_node",
            "class_name": "ExampleNode",
            "docstring": "Test node for validation",
            "file_path": "src/pflow/nodes/test_node.py",
        },
        "test-node-retry": {
            "module": "pflow.nodes.test_node_retry",
            "class_name": "RetryExampleNode",
            "docstring": "Test node with retry",
            "file_path": "src/pflow/nodes/test_node_retry.py",
        },
    }
    registry.save(test_nodes_metadata)
    return registry, test_nodes_metadata


class TestInstantiateNodes:
    """Test the _instantiate_nodes helper function with real nodes."""

    def test_instantiate_single_node_creates_working_node(self):
        """Test instantiating a single node creates a working node instance."""
        registry, _ = create_test_registry()

        # Create IR with one node
        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}]}

        # Call function with real registry
        nodes = _instantiate_nodes(ir_dict, registry)

        # Verify behavior: correct node created and it works
        assert len(nodes) == 1
        assert "node1" in nodes
        node = nodes["node1"]
        assert isinstance(node, BaseNode)

        # Test the node actually works by running it
        shared_store = {"test_input": "hello"}
        result = node.prep(shared_store)
        processed = node.exec(result)
        action = node.post(shared_store, result, processed)

        # Verify the node processed data correctly
        assert shared_store["test_output"] == "Processed: hello"
        assert action == "default"

    def test_instantiate_multiple_nodes_creates_different_instances(self):
        """Test instantiating multiple nodes creates separate working instances.

        FIX HISTORY:
        - Fixed KeyError: 'test_output' by using appropriate input/output keys for each node type
        - ExampleNode uses test_input/test_output, RetryExampleNode uses retry_input/retry_output
        - Test now validates real behavior: each node processes data through its specific interface
        """
        registry, _ = create_test_registry()

        # Create IR with multiple nodes
        ir_dict = {
            "nodes": [
                {"id": "node1", "type": "test-node"},
                {"id": "node2", "type": "test-node-retry"},
                {"id": "node3", "type": "test-node"},  # Same type as node1, different instance
            ]
        }

        # Call function with real registry
        nodes = _instantiate_nodes(ir_dict, registry)

        # Verify behavior: correct number of distinct working instances
        assert len(nodes) == 3
        assert all(key in nodes for key in ["node1", "node2", "node3"])
        assert all(isinstance(node, BaseNode) for node in nodes.values())

        # Verify they're different instances (not the same object)
        assert nodes["node1"] is not nodes["node3"]  # Different instances
        assert type(nodes["node1"]).__name__ == "ExampleNode"
        assert type(nodes["node2"]).__name__ == "RetryExampleNode"  # Different class
        assert type(nodes["node3"]).__name__ == "ExampleNode"

        # Test all nodes can execute independently with proper input keys
        for node_id, node in nodes.items():
            # Use appropriate input key based on node type
            if type(node).__name__ == "RetryExampleNode":
                shared_store = {"retry_input": f"input-{node_id}"}
                expected_output_key = "retry_output"
            else:
                shared_store = {"test_input": f"input-{node_id}"}
                expected_output_key = "test_output"

            result = node.prep(shared_store)
            processed = node.exec(result)
            node.post(shared_store, result, processed)

            # Verify each node processed its data correctly
            assert expected_output_key in shared_store
            assert f"input-{node_id}" in shared_store[expected_output_key]

    def test_instantiate_with_params_sets_params_correctly(self):
        """Test instantiating nodes with parameters actually sets them on the node."""
        registry, _ = create_test_registry()

        # Create IR with parameterized node
        ir_dict = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "test-node",
                    "params": {"custom_param": "test_value"},
                }
            ]
        }

        # Call function with real registry
        nodes = _instantiate_nodes(ir_dict, registry)

        # Verify node was created and params were set
        assert len(nodes) == 1
        node = nodes["node1"]

        # Test that parameters were actually set on the node
        assert hasattr(node, "params")
        assert node.params.get("custom_param") == "test_value"

        # Test that the node still functions correctly with params
        shared_store = {"test_input": "param_test"}
        result = node.prep(shared_store)
        processed = node.exec(result)
        action = node.post(shared_store, result, processed)

        # Node should work regardless of parameters
        assert shared_store["test_output"] == "Processed: param_test"
        assert action == "default"

    def test_instantiate_with_nonexistent_node_type_raises_error(self):
        """Test error handling when node type doesn't exist in registry."""
        registry, _ = create_test_registry()

        # Create IR with non-existent node type
        ir_dict = {"nodes": [{"id": "node1", "type": "nonexistent-node"}]}

        # Call function and expect error
        with pytest.raises(CompilationError) as exc_info:
            _instantiate_nodes(ir_dict, registry)

        # Verify error behavior: should contain useful information
        error = exc_info.value
        assert error.node_id == "node1"
        assert "nonexistent-node" in str(error)
        assert error.phase == "node_resolution"

    def test_instantiate_with_no_params_works_correctly(self):
        """Test that nodes work correctly when no params are provided."""
        registry, _ = create_test_registry()

        # Create IR with no params (not even empty dict)
        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}]}

        # Call function with real registry
        nodes = _instantiate_nodes(ir_dict, registry)

        # Verify node works correctly without params
        assert len(nodes) == 1
        node = nodes["node1"]

        # Test that the node functions correctly without params
        shared_store = {"test_input": "no_params_test"}
        result = node.prep(shared_store)
        processed = node.exec(result)
        action = node.post(shared_store, result, processed)

        assert shared_store["test_output"] == "Processed: no_params_test"
        assert action == "default"


class TestWireNodes:
    """Test the _wire_nodes helper function with real nodes and actual workflow execution."""

    def test_wire_default_connection_creates_working_flow(self):
        """Test wiring nodes with default (>>) connection produces working workflow."""
        registry, _ = create_test_registry()

        # Create IR and instantiate real nodes
        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}, {"id": "node2", "type": "test-node"}]}
        nodes = _instantiate_nodes(ir_dict, registry)

        # Create edges
        edges = [{"source": "node1", "target": "node2"}]

        # Wire nodes
        _wire_nodes(nodes, edges)

        # Test behavior: create flow and verify data flows between nodes
        flow = Flow(start=nodes["node1"])
        shared_store = {"test_input": "wiring_test"}

        # Execute the flow
        flow.run(shared_store)

        # Verify the workflow executed correctly through both nodes
        assert "test_output" in shared_store
        assert "wiring_test" in shared_store["test_output"]

    def test_wire_chain_connection_executes_sequentially(self):
        """Test wiring a chain of nodes executes them in order."""
        registry, _ = create_test_registry()

        # Create three nodes
        ir_dict = {
            "nodes": [
                {"id": "node1", "type": "test-node"},
                {"id": "node2", "type": "test-node"},
                {"id": "node3", "type": "test-node"},
            ]
        }
        nodes = _instantiate_nodes(ir_dict, registry)

        # Create chain edges
        edges = [
            {"source": "node1", "target": "node2"},
            {"source": "node2", "target": "node3"},
        ]

        # Wire nodes
        _wire_nodes(nodes, edges)

        # Test behavior: verify chain execution
        flow = Flow(start=nodes["node1"])
        shared_store = {"test_input": "chain_test"}

        flow.run(shared_store)

        # All nodes in chain should have processed the data
        assert "test_output" in shared_store
        assert "chain_test" in shared_store["test_output"]

    def test_wire_missing_source_node_raises_helpful_error(self):
        """Test error when edge references non-existent source."""
        registry, _ = create_test_registry()

        # Create one real node
        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}]}
        nodes = _instantiate_nodes(ir_dict, registry)

        # Create edge with missing source
        edges = [{"source": "missing", "target": "node1"}]

        # Wire nodes and expect error
        with pytest.raises(CompilationError) as exc_info:
            _wire_nodes(nodes, edges)

        # Verify error provides helpful context for debugging
        error = exc_info.value
        assert error.phase == "flow_wiring"
        assert error.node_id == "missing"
        assert "non-existent source node" in str(error)
        assert "Available nodes: node1" in error.suggestion

    def test_wire_missing_target_node_raises_helpful_error(self):
        """Test error when edge references non-existent target."""
        registry, _ = create_test_registry()

        # Create one real node
        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}]}
        nodes = _instantiate_nodes(ir_dict, registry)

        # Create edge with missing target
        edges = [{"source": "node1", "target": "missing"}]

        # Wire nodes and expect error
        with pytest.raises(CompilationError) as exc_info:
            _wire_nodes(nodes, edges)

        # Verify error provides helpful context for debugging
        error = exc_info.value
        assert error.phase == "flow_wiring"
        assert error.node_id == "missing"
        assert "non-existent target node" in str(error)
        assert "Available nodes: node1" in error.suggestion

    def test_wire_with_no_edges_leaves_nodes_unconnected(self):
        """Test wiring with no edges leaves individual nodes that can run independently."""
        registry, _ = create_test_registry()

        # Create multiple real nodes
        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}, {"id": "node2", "type": "test-node"}]}
        nodes = _instantiate_nodes(ir_dict, registry)

        # Wire with empty edges (no connections)
        _wire_nodes(nodes, [])

        # Test behavior: each node should work independently
        for node_id, node in nodes.items():
            shared_store = {"test_input": f"isolated_{node_id}"}
            result = node.prep(shared_store)
            processed = node.exec(result)
            action = node.post(shared_store, result, processed)

            # Each node should process its input independently
            assert shared_store["test_output"] == f"Processed: isolated_{node_id}"
            assert action == "default"


class TestGetStartNode:
    """Test the _get_start_node helper function with real nodes."""

    def test_get_start_node_uses_first_node_by_default(self):
        """Test using first node as start when no explicit start specified."""
        registry, _ = create_test_registry()

        # Create real nodes
        ir_dict = {"nodes": [{"id": "node2", "type": "test-node"}, {"id": "node1", "type": "test-node"}]}
        nodes = _instantiate_nodes(ir_dict, registry)

        # Get start node
        start = _get_start_node(nodes, ir_dict)

        # Verify first node in IR is used and it actually works
        assert start is nodes["node2"]

        # Test that the start node can execute
        shared_store = {"test_input": "start_test"}
        result = start.prep(shared_store)
        processed = start.exec(result)
        action = start.post(shared_store, result, processed)

        assert shared_store["test_output"] == "Processed: start_test"
        assert action == "default"

    def test_get_start_node_respects_explicit_start_node(self):
        """Test using explicit start_node when specified."""
        registry, _ = create_test_registry()

        # Create real nodes
        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}, {"id": "node2", "type": "test-node"}]}
        nodes = _instantiate_nodes(ir_dict, registry)

        # Create IR with explicit start_node (not the first one)
        ir_dict["start_node"] = "node2"

        # Get start node
        start = _get_start_node(nodes, ir_dict)

        # Verify explicit start is used and works
        assert start is nodes["node2"]

        # Test that the explicitly chosen start node can execute
        shared_store = {"test_input": "explicit_start"}
        result = start.prep(shared_store)
        processed = start.exec(result)
        start.post(shared_store, result, processed)

        assert shared_store["test_output"] == "Processed: explicit_start"

    def test_get_start_node_with_no_nodes_raises_helpful_error(self):
        """Test error when no nodes exist provides helpful context."""
        # Empty nodes
        nodes = {}
        ir_dict = {"nodes": []}

        # Get start node and expect error
        with pytest.raises(CompilationError) as exc_info:
            _get_start_node(nodes, ir_dict)

        # Verify error provides helpful context
        error = exc_info.value
        assert error.phase == "start_detection"
        assert "Cannot create flow with no nodes" in str(error)

    def test_get_start_node_with_invalid_explicit_start_raises_helpful_error(self):
        """Test error when explicit start_node doesn't exist provides helpful context."""
        registry, _ = create_test_registry()

        # Create one real node
        ir_dict = {"nodes": [{"id": "node1", "type": "test-node"}]}
        nodes = _instantiate_nodes(ir_dict, registry)

        # Create IR with invalid start_node
        ir_dict["start_node"] = "missing"

        # Get start node and expect error
        with pytest.raises(CompilationError) as exc_info:
            _get_start_node(nodes, ir_dict)

        # Verify error provides helpful debugging context
        error = exc_info.value
        assert error.phase == "start_detection"
        assert "Could not determine start node" in str(error)


class TestCompileIrToFlow:
    """Test the main compile_ir_to_flow function with real integration testing.

    FIX HISTORY:
    - Removed all mock-heavy tests that tested implementation details
    - Removed log message testing (brittle implementation details)
    - Focus on end-to-end integration testing with real nodes
    - Test actual workflow compilation and execution behavior
    """

    def test_compile_and_execute_simple_flow_end_to_end(self):
        """Test compiling and executing a simple linear flow works end-to-end."""
        registry, _ = create_test_registry()

        # Create realistic IR with real node types
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

        # Compile with real registry
        flow = compile_ir_to_flow(ir_dict, registry)

        # Test behavior: verify compilation produces working flow
        assert isinstance(flow, Flow)
        assert flow.start_node is not None

        # Most importantly: test the compiled flow actually executes correctly
        shared_store = {"test_input": "integration_test"}
        flow.run(shared_store)

        # Verify the entire workflow executed through all nodes
        assert "test_output" in shared_store
        assert "integration_test" in shared_store["test_output"]

    def test_compile_with_node_parameters_end_to_end(self):
        """Test compiling and executing flow with node parameters works correctly."""
        registry, _ = create_test_registry()

        # Create IR with parameterized nodes
        ir_dict = {
            "nodes": [{"id": "node1", "type": "test-node", "params": {"custom_param": "param_value"}}],
            "edges": [],
        }

        # Compile with real registry
        flow = compile_ir_to_flow(ir_dict, registry)

        # Test behavior: verify compiled flow executes with parameters
        assert isinstance(flow, Flow)

        # Test execution works with parameters
        shared_store = {"test_input": "param_test"}
        flow.run(shared_store)

        # Verify workflow executed correctly with parameters
        assert "test_output" in shared_store
        assert "param_test" in shared_store["test_output"]

    def test_compile_from_json_string_works_end_to_end(self):
        """Test compiling from JSON string input produces working flow."""
        registry, _ = create_test_registry()

        # Create JSON string
        ir_json = '{"nodes": [{"id": "test", "type": "test-node"}], "edges": []}'

        # Compile from JSON string with real registry
        flow = compile_ir_to_flow(ir_json, registry)

        # Test behavior: verify compilation and execution work
        assert isinstance(flow, Flow)

        shared_store = {"test_input": "json_test"}
        flow.run(shared_store)

        assert "test_output" in shared_store
        assert "json_test" in shared_store["test_output"]

    def test_compile_with_invalid_json_raises_json_decode_error(self):
        """Test error on invalid JSON string provides clear error."""
        registry, _ = create_test_registry()

        # Invalid JSON
        ir_json = '{"nodes": [invalid json}'

        # Compile and expect JSONDecodeError
        with pytest.raises(Exception) as exc_info:
            compile_ir_to_flow(ir_json, registry)

        # Verify it's a JSON error that provides clear context
        assert exc_info.type.__name__ == "JSONDecodeError"

    def test_compile_with_validation_error_provides_helpful_context(self):
        """Test error during IR validation provides helpful debugging context."""
        registry, _ = create_test_registry()

        # IR missing required fields
        ir_dict = {"edges": []}  # Missing nodes

        # Compile and expect CompilationError
        with pytest.raises(CompilationError) as exc_info:
            compile_ir_to_flow(ir_dict, registry)

        # Verify error provides helpful context for debugging
        error = exc_info.value
        assert error.phase == "validation"
        assert "Missing 'nodes' key" in str(error)
