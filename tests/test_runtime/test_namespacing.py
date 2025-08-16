"""Tests for automatic namespacing functionality."""

from pflow.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow
from pocketflow import Node


class SimpleOutputNode(Node):
    """Test node that writes to shared store."""

    def prep(self, shared):
        return self.params.get("value", "test_value")

    def exec(self, prep_res):
        return prep_res

    def post(self, shared, prep_res, exec_res):
        shared["output"] = exec_res
        return "default"


class SimpleReaderNode(Node):
    """Test node that reads from shared store."""

    def prep(self, shared):
        # Use fallback pattern
        return shared.get("output") or self.params.get("output")

    def exec(self, prep_res):
        return f"Read: {prep_res}"

    def post(self, shared, prep_res, exec_res):
        shared["result"] = exec_res
        return "default"


def test_namespacing_prevents_collisions(tmp_path):
    """Test that namespacing prevents output collisions between nodes."""
    # Create a simple registry with test nodes
    registry_path = tmp_path / "test_registry.json"
    registry = Registry(registry_path)

    # Save test nodes to registry
    nodes_data = {
        "test-output": {
            "module": "test",
            "class": "SimpleOutputNode",
            "metadata": {
                "inputs": [],
                "outputs": [{"name": "output", "type": "str"}],
            },
        },
        "test-reader": {
            "module": "test",
            "class": "SimpleReaderNode",
            "metadata": {
                "inputs": [{"name": "output", "type": "str"}],
                "outputs": [{"name": "result", "type": "str"}],
            },
        },
    }
    registry.save(nodes_data)

    # Mock the import to return our test classes
    import pflow.runtime.compiler as compiler_module

    original_import = compiler_module.import_node_class

    def mock_import(node_type, registry):
        if node_type == "test-output":
            return SimpleOutputNode
        elif node_type == "test-reader":
            return SimpleReaderNode
        return original_import(node_type, registry)

    compiler_module.import_node_class = mock_import

    try:
        # Create workflow with namespacing enabled
        workflow_ir = {
            "ir_version": "0.1.0",
            "enable_namespacing": True,  # Enable namespacing
            "nodes": [
                {"id": "node1", "type": "test-output", "params": {"value": "first"}},
                {"id": "node2", "type": "test-output", "params": {"value": "second"}},
                {"id": "reader", "type": "test-reader", "params": {"output": "${node1.output}"}},
            ],
            "edges": [
                {"from": "node1", "to": "node2"},
                {"from": "node2", "to": "reader"},
            ],
        }

        # Compile the workflow
        flow = compile_ir_to_flow(workflow_ir, registry, validate=False)

        # Execute the workflow
        shared = {}
        flow.run(shared)

        # With namespacing, outputs should be isolated
        assert "node1" in shared, "Node1 namespace should exist"
        assert "node2" in shared, "Node2 namespace should exist"
        assert "reader" in shared, "Reader namespace should exist"

        # Check that each node's output is in its namespace
        assert shared["node1"]["output"] == "first", "Node1 output should be 'first'"
        assert shared["node2"]["output"] == "second", "Node2 output should be 'second'"
        assert shared["reader"]["result"] == "Read: first", "Reader should read node1's output via template"

        # Root level should not have 'output' key (no collision)
        assert "output" not in shared, "Root level should not have 'output' key"

    finally:
        # Restore original import
        compiler_module.import_node_class = original_import


def test_namespacing_enabled_by_default(tmp_path):
    """Test that namespacing is enabled by default."""
    # Create registry with test nodes
    registry_path = tmp_path / "test_registry.json"
    registry = Registry(registry_path)

    # Save test node to registry
    nodes_data = {
        "test-output": {
            "module": "test",
            "class": "SimpleOutputNode",
            "metadata": {
                "inputs": [],
                "outputs": [{"name": "output", "type": "str"}],
            },
        }
    }
    registry.save(nodes_data)

    # Mock the import
    import pflow.runtime.compiler as compiler_module

    original_import = compiler_module.import_node_class

    def mock_import(node_type, registry):
        if node_type == "test-output":
            return SimpleOutputNode
        return original_import(node_type, registry)

    compiler_module.import_node_class = mock_import

    try:
        # Create workflow WITHOUT namespacing
        workflow_ir = {
            "ir_version": "0.1.0",
            # enable_namespacing not set, defaults to False
            "nodes": [
                {"id": "node1", "type": "test-output", "params": {"value": "first"}},
                {"id": "node2", "type": "test-output", "params": {"value": "second"}},
            ],
            "edges": [
                {"from": "node1", "to": "node2"},
            ],
        }

        # Compile and run
        flow = compile_ir_to_flow(workflow_ir, registry, validate=False)
        shared = {}
        flow.run(shared)

        # With namespacing enabled by default, outputs are isolated
        assert "node1" in shared, "Node1 namespace should exist"
        assert "node2" in shared, "Node2 namespace should exist"
        assert shared["node1"]["output"] == "first", "Node1 output should be preserved"
        assert shared["node2"]["output"] == "second", "Node2 output should be preserved"

        # Root level should not have 'output' key (no collision)
        assert "output" not in shared, "Root level should not have 'output' key"

    finally:
        compiler_module.import_node_class = original_import


def test_namespacing_with_cli_inputs(tmp_path):
    """Test that CLI inputs at root level are still accessible with namespacing."""
    # Create registry with test node
    registry_path = tmp_path / "test_registry.json"
    registry = Registry(registry_path)

    # Save test node to registry
    nodes_data = {
        "test-reader": {
            "module": "test",
            "class": "SimpleReaderNode",
            "metadata": {
                "inputs": [{"name": "output", "type": "str"}],
                "outputs": [{"name": "result", "type": "str"}],
            },
        }
    }
    registry.save(nodes_data)

    # Mock import
    import pflow.runtime.compiler as compiler_module

    original_import = compiler_module.import_node_class

    def mock_import(node_type, registry):
        if node_type == "test-reader":
            return SimpleReaderNode
        return original_import(node_type, registry)

    compiler_module.import_node_class = mock_import

    try:
        workflow_ir = {
            "ir_version": "0.1.0",
            "enable_namespacing": True,
            "nodes": [
                {"id": "reader", "type": "test-reader"},  # No params, will read from shared
            ],
            "edges": [],  # Empty edges array required
        }

        flow = compile_ir_to_flow(workflow_ir, registry, validate=False)

        # Simulate CLI putting data at root level
        shared = {"output": "cli_data"}
        flow.run(shared)

        # Reader should be able to read CLI input from root
        assert shared["reader"]["result"] == "Read: cli_data", "Should read CLI data from root"

    finally:
        compiler_module.import_node_class = original_import
