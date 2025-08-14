"""Integration tests for automatic namespacing with templates."""

from pflow.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow


def test_namespacing_with_workflow_inputs(tmp_path):
    """Test that workflow inputs work correctly with namespacing enabled by default."""
    # Create registry
    registry_path = tmp_path / "test_registry.json"
    registry = Registry(registry_path)

    # Create a workflow with inputs and template variables
    workflow = {
        "ir_version": "0.1.0",
        # namespacing is now enabled by default
        "nodes": [
            {"id": "process1", "type": "echo", "params": {"data": "$input_data"}},
            {
                "id": "process2",
                "type": "echo",
                "params": {
                    "data": "$process1.data"  # Reference first node's output
                },
            },
        ],
        "edges": [{"from": "process1", "to": "process2"}],
        "inputs": {"input_data": {"description": "Input data to process", "required": False, "default": "test_value"}},
    }

    # Mock the echo node
    from pocketflow import Node

    class EchoNode(Node):
        """Simple echo node for testing."""

        def prep(self, shared):
            data = shared.get("data") or self.params.get("data", "no_data")
            return data

        def exec(self, prep_res):
            return prep_res

        def post(self, shared, prep_res, exec_res):
            shared["data"] = exec_res
            return "default"

    # Mock import
    import pflow.runtime.compiler as compiler_module

    original_import = compiler_module.import_node_class

    def mock_import(node_type, registry):
        if node_type == "echo":
            return EchoNode
        return original_import(node_type, registry)

    compiler_module.import_node_class = mock_import

    try:
        # Compile with initial params
        flow = compile_ir_to_flow(workflow, registry, initial_params={"input_data": "custom_value"}, validate=False)

        # Execute
        shared = {}
        flow.run(shared)

        # With namespacing, each node's output is in its namespace
        assert "process1" in shared, "First node namespace should exist"
        assert "process2" in shared, "Second node namespace should exist"

        # Check that data flowed correctly with custom value
        assert shared["process1"]["data"] == "custom_value", "First node should use input param"
        assert shared["process2"]["data"] == "custom_value", "Second node should get first node's output"

        # Now test with default value
        flow = compile_ir_to_flow(
            workflow,
            registry,
            initial_params={},  # No params, should use default
            validate=False,
        )

        shared = {}
        flow.run(shared)

        assert shared["process1"]["data"] == "test_value", "Should use default value"
        assert shared["process2"]["data"] == "test_value", "Should pass through default"

    finally:
        compiler_module.import_node_class = original_import


def test_namespacing_prevents_collisions_with_templates(tmp_path):
    """Test that multiple nodes of same type work with templates."""
    registry = Registry(tmp_path / "test_registry.json")

    workflow = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "api1", "type": "api-call", "params": {"url": "$url1"}},
            {"id": "api2", "type": "api-call", "params": {"url": "$url2"}},
            {"id": "combine", "type": "combine", "params": {"data1": "$api1.response", "data2": "$api2.response"}},
        ],
        "edges": [{"from": "api1", "to": "api2"}, {"from": "api2", "to": "combine"}],
        "inputs": {
            "url1": {"required": False, "default": "http://api1.example.com"},
            "url2": {"required": False, "default": "http://api2.example.com"},
        },
    }

    from pocketflow import Node

    class ApiCallNode(Node):
        def prep(self, shared):
            url = shared.get("url") or self.params.get("url")
            return url

        def exec(self, prep_res):
            # Simulate API response
            return f"Response from {prep_res}"

        def post(self, shared, prep_res, exec_res):
            shared["response"] = exec_res
            return "default"

    class CombineNode(Node):
        def prep(self, shared):
            data1 = shared.get("data1") or self.params.get("data1")
            data2 = shared.get("data2") or self.params.get("data2")
            return (data1, data2)

        def exec(self, prep_res):
            data1, data2 = prep_res
            return f"Combined: {data1} + {data2}"

        def post(self, shared, prep_res, exec_res):
            shared["result"] = exec_res
            return "default"

    import pflow.runtime.compiler as compiler_module

    original_import = compiler_module.import_node_class

    def mock_import(node_type, registry):
        if node_type == "api-call":
            return ApiCallNode
        elif node_type == "combine":
            return CombineNode
        return original_import(node_type, registry)

    compiler_module.import_node_class = mock_import

    try:
        flow = compile_ir_to_flow(workflow, registry, validate=False)
        shared = {}
        flow.run(shared)

        # Check namespaces exist
        assert "api1" in shared
        assert "api2" in shared
        assert "combine" in shared

        # Check both API responses are preserved (no collision)
        assert shared["api1"]["response"] == "Response from http://api1.example.com"
        assert shared["api2"]["response"] == "Response from http://api2.example.com"

        # Check combination worked
        expected = "Combined: Response from http://api1.example.com + Response from http://api2.example.com"
        assert shared["combine"]["result"] == expected

    finally:
        compiler_module.import_node_class = original_import
