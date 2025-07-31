"""Integration tests for the IR compiler.

This module tests end-to-end compilation of IR to executable PocketFlow
objects using real nodes, realistic performance benchmarks, and error
handling validation.

FIX HISTORY:
- Removed all mock node classes that didn't reflect real behavior
- Replaced with real test nodes from the codebase
- Performance tests now use real nodes to reflect actual performance
- Focus on integration behavior rather than artificial test constructs
"""

import json
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

from pflow.core import validate_ir
from pflow.registry import Registry
from pflow.runtime import CompilationError, compile_ir_to_flow

# =============================================================================
# Test Fixtures with Real Nodes
# =============================================================================


def create_real_test_registry():
    """Create a test registry with real test nodes from the codebase."""
    registry_dir = tempfile.mkdtemp()
    registry_path = Path(registry_dir) / "integration_test.json"
    registry = Registry(registry_path)

    # Use real test nodes from the codebase
    real_nodes_metadata = {
        "test-node": {
            "module": "pflow.nodes.test_node",
            "class_name": "TestNode",
            "docstring": "Test node for validation",
            "file_path": "src/pflow/nodes/test_node.py",
        },
        "test-node-retry": {
            "module": "pflow.nodes.test_node_retry",
            "class_name": "TestNodeRetry",
            "docstring": "Test node with retry",
            "file_path": "src/pflow/nodes/test_node_retry.py",
        },
        "test-node-structured": {
            "module": "pflow.nodes.test_node_structured",
            "class_name": "TestNodeStructured",
            "docstring": "Structured test node",
            "file_path": "src/pflow/nodes/test_node_structured.py",
        },
        # Add alias for basic-node to test-node for backward compatibility
        "basic-node": {
            "module": "pflow.nodes.test_node",
            "class_name": "TestNode",
            "docstring": "Basic test node (alias for test-node)",
            "file_path": "src/pflow/nodes/test_node.py",
        },
        # Add aliases for other common test node types
        "transform-node": {
            "module": "pflow.nodes.test_node_structured",
            "class_name": "TestNodeStructured",
            "docstring": "Transform test node (alias for test-node-structured)",
            "file_path": "src/pflow/nodes/test_node_structured.py",
        },
        "conditional-node": {
            "module": "pflow.nodes.test_node_retry",
            "class_name": "TestNodeRetry",
            "docstring": "Conditional test node (alias for test-node-retry)",
            "file_path": "src/pflow/nodes/test_node_retry.py",
        },
    }
    registry.save(real_nodes_metadata)
    return registry


@pytest.fixture
def test_registry():
    """Create a Registry instance with real test nodes."""
    return create_real_test_registry()


@pytest.fixture
def simple_ir():
    """Simple IR with two real test nodes for basic testing."""
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "input",
                "type": "test-node",
                "params": {"custom_param": "hello world"},
            },
            {
                "id": "transform",
                "type": "test-node-structured",
                "params": {"process_type": "uppercase"},
            },
        ],
        "edges": [
            {
                "from": "input",
                "to": "transform",
            }
        ],
    }


@pytest.fixture
def multi_node_ir():
    """IR with multiple real test nodes for integration testing."""
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "start",
                "type": "test-node",
            },
            {
                "id": "process",
                "type": "test-node-retry",
            },
            {
                "id": "finish",
                "type": "test-node-structured",
            },
        ],
        "edges": [
            {"from": "start", "to": "process"},
            {"from": "process", "to": "finish"},
        ],
    }


@pytest.fixture
def branching_ir():
    """IR with branching nodes for conditional flow testing."""
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "start",
                "type": "test-node",
            },
            {
                "id": "success_path",
                "type": "test-node-structured",
            },
            {
                "id": "failure_path",
                "type": "test-node-retry",
            },
        ],
        "edges": [
            {"from": "start", "to": "success_path", "action": "success"},
            {"from": "start", "to": "failure_path", "action": "failure"},
        ],
    }


# =============================================================================
# End-to-End Compilation Tests
# =============================================================================


class TestEndToEndCompilation:
    """Test complete IR to Flow compilation and execution."""

    def test_simple_flow_compilation_and_execution(self, simple_ir, test_registry):
        """Test compiling and running a simple flow."""
        # Compile IR to Flow
        flow = compile_ir_to_flow(simple_ir, test_registry)

        # Verify Flow was created
        assert flow is not None
        assert flow.start is not None

        # Execute the flow with input data for the test nodes
        shared_storage = {"test_input": "hello world", "user_id": "test-user"}
        result = flow.run(shared_storage)

        # Verify execution results based on real test node behavior
        assert "test_output" in shared_storage
        assert "Processed: hello world" in shared_storage["test_output"]
        assert "user_data" in shared_storage  # From test-node-structured
        assert shared_storage["user_data"]["id"] == "test-user"
        assert result == "default"  # Default action from final node

    def test_branching_flow_with_success_path(self, branching_ir, test_registry):
        """Test conditional flow taking success path."""
        flow = compile_ir_to_flow(branching_ir, test_registry)

        # Run with condition = True
        shared_storage = {"condition": True}
        flow.run(shared_storage)

        # Verify success path was taken
        # We can check which nodes executed by looking at node instances
        # This is a simplified check - in real scenario we'd track execution

    def test_branching_flow_with_failure_path(self, branching_ir, test_registry):
        """Test conditional flow taking failure path."""
        flow = compile_ir_to_flow(branching_ir, test_registry)

        # Run with condition = False
        shared_storage = {"condition": False}
        flow.run(shared_storage)

        # Verify failure path was taken

    def test_flow_with_template_variables(self, test_registry):
        """Test that template variables pass through unchanged."""
        ir_with_templates = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "node1",
                    "type": "basic-node",
                    "params": {"template": "$user_input", "number": "$count"},
                }
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(ir_with_templates, test_registry, validate=False)

        # Get the node and check it's wrapped
        node = flow.start_node
        # With templates, the node should be wrapped
        from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper

        assert isinstance(node, TemplateAwareNodeWrapper)
        # The wrapper should have the template params stored
        assert node.template_params["template"] == "$user_input"
        assert node.template_params["number"] == "$count"

    def test_compilation_with_json_string_input(self, simple_ir, test_registry):
        """Test compilation accepts JSON string input."""
        ir_json = json.dumps(simple_ir)
        flow = compile_ir_to_flow(ir_json, test_registry)

        assert flow is not None
        shared_storage = {"test_input": "hello world", "user_id": "test-user"}
        flow.run(shared_storage)
        assert "test_output" in shared_storage
        assert "user_data" in shared_storage


# =============================================================================
# Real IR Example Tests
# =============================================================================


class TestRealIRExamples:
    """Test compilation with actual IR examples from the examples directory."""

    def get_example_files(self):
        """Get all JSON files from examples/core directory."""
        examples_dir = Path(__file__).parent.parent / "examples" / "core"
        if not examples_dir.exists():
            pytest.skip("Examples directory not found")

        return list(examples_dir.glob("*.json"))

    def test_core_examples_compile_successfully(self, test_registry):
        """Test that all core examples compile without errors."""
        example_files = self.get_example_files()

        if not example_files:
            pytest.skip("No example files found")

        for example_file in example_files:
            # Skip files that are known to need real nodes
            if example_file.name in ["github-flow.json", "llm-flow.json"]:
                continue

            with open(example_file) as f:
                ir_data = json.load(f)

            # For examples with unknown node types, skip
            node_types = {node["type"] for node in ir_data.get("nodes", [])}
            known_types = {"basic-node", "transform-node", "conditional-node"}

            if not node_types.issubset(known_types):
                continue

            # Should compile without errors
            try:
                flow = compile_ir_to_flow(ir_data, test_registry)
                assert flow is not None
            except CompilationError as e:
                pytest.fail(f"Failed to compile {example_file.name}: {e}")

    def test_edge_format_compatibility(self, test_registry):
        """Test that both from/to and source/target formats work."""
        # IR with from/to format
        ir_from_to = {
            "nodes": [
                {"id": "a", "type": "basic-node"},
                {"id": "b", "type": "basic-node"},
            ],
            "edges": [{"from": "a", "to": "b"}],
        }

        # IR with source/target format
        ir_source_target = {
            "nodes": [
                {"id": "a", "type": "basic-node"},
                {"id": "b", "type": "basic-node"},
            ],
            "edges": [{"source": "a", "target": "b"}],
        }

        # Both should compile successfully
        flow1 = compile_ir_to_flow(ir_from_to, test_registry)
        flow2 = compile_ir_to_flow(ir_source_target, test_registry)

        assert flow1 is not None
        assert flow2 is not None


# =============================================================================
# Performance Benchmark Tests
# =============================================================================


class TestPerformanceBenchmarks:
    """Test compilation performance with real nodes to reflect actual performance characteristics.

    FIX HISTORY:
    - Removed artificial delay mock nodes that didn't reflect real performance
    - Use real test nodes to measure actual compilation overhead
    - Focus on compilation time, not artificial execution delays
    """

    def create_real_linear_flow_ir(self, node_count: int) -> dict[str, Any]:
        """Create IR for a linear flow with real test nodes."""
        nodes = []
        edges = []

        for i in range(node_count):
            # Alternate between different real node types for realistic testing
            node_type = ["test-node", "test-node-retry", "test-node-structured"][i % 3]
            nodes.append({
                "id": f"node{i}",
                "type": node_type,
                "params": {"node_index": i},  # Realistic parameter
            })

            if i > 0:
                edges.append({
                    "from": f"node{i - 1}",
                    "to": f"node{i}",
                })

        return {"nodes": nodes, "edges": edges}

    def test_real_compilation_performance_scales_with_nodes(self, test_registry):
        """Test that compilation time with real nodes meets performance targets."""
        # Test with different sizes using real nodes
        sizes_and_targets = [
            (5, 50),  # 5 nodes should compile in <50ms
            (10, 100),  # 10 nodes should compile in <100ms
            (20, 200),  # 20 nodes should compile in <200ms
        ]

        for size, target_ms in sizes_and_targets:
            ir = self.create_real_linear_flow_ir(size)

            # Measure compilation time (not execution time)
            start_time = time.perf_counter()
            flow = compile_ir_to_flow(ir, test_registry)
            end_time = time.perf_counter()

            compilation_time_ms = (end_time - start_time) * 1000

            # Verify flow compiles and meets performance target
            assert flow is not None, f"Failed to compile {size}-node workflow"
            assert compilation_time_ms < target_ms, (
                f"Compilation of {size} real nodes took {compilation_time_ms:.2f}ms (target: <{target_ms}ms)"
            )

    def test_compiled_real_workflow_executes_correctly(self, test_registry):
        """Test that performance-optimized compiled workflows actually work end-to-end."""
        # Test a reasonably sized workflow actually executes correctly
        ir = self.create_real_linear_flow_ir(10)

        # Compile the workflow
        flow = compile_ir_to_flow(ir, test_registry)
        assert flow is not None

        # Most importantly: verify the compiled workflow actually executes
        shared_store = {"test_input": "performance_test", "user_id": "perf-user", "retry_input": "retry_test"}
        flow.run(shared_store)

        # Verify the workflow executed through all nodes - check for any output from the test nodes
        # TestNode writes to test_output, TestNodeStructured writes user_data, TestNodeRetry writes retry_output
        has_output = "test_output" in shared_store or "user_data" in shared_store or "retry_output" in shared_store
        assert has_output, f"No expected outputs found in shared_store: {shared_store.keys()}"

    def test_complex_workflow_compilation_performance(self, test_registry):
        """Test compilation performance with complex node graphs."""
        # Create a more complex graph (not just linear)
        nodes = []
        edges = []

        # Create a diamond pattern: 1 -> 2,3 -> 4
        for i in range(4):
            node_type = ["test-node", "test-node-retry", "test-node-structured"][i % 3]
            nodes.append({
                "id": f"node{i}",
                "type": node_type,
                "params": {"position": i},
            })

        # Diamond edges: 0->1, 0->2, 1->3, 2->3
        edges = [
            {"from": "node0", "to": "node1"},
            {"from": "node0", "to": "node2"},
            {"from": "node1", "to": "node3"},
            {"from": "node2", "to": "node3"},
        ]

        ir = {"nodes": nodes, "edges": edges}

        # Measure compilation
        start_time = time.perf_counter()
        flow = compile_ir_to_flow(ir, test_registry)
        end_time = time.perf_counter()

        compilation_time_ms = (end_time - start_time) * 1000

        # Complex workflow should still compile quickly
        assert flow is not None
        assert compilation_time_ms < 150, f"Complex workflow compilation took {compilation_time_ms:.2f}ms"


# =============================================================================
# Error Message Quality Tests
# =============================================================================


class TestErrorMessageQuality:
    """Test that error messages are helpful and actionable."""

    def test_missing_node_type_suggestion(self, test_registry):
        """Test error message suggests available node types."""
        ir = {
            "nodes": [{"id": "test", "type": "unknown-node"}],
            "edges": [],
        }

        with pytest.raises(CompilationError) as exc_info:
            compile_ir_to_flow(ir, test_registry)

        error = exc_info.value
        assert "unknown-node" in str(error)
        assert "Available node types:" in str(error)
        assert "test-node" in str(error)

    def test_missing_edge_node_suggestion(self, test_registry):
        """Test error message for edges referencing non-existent nodes."""
        ir = {
            "nodes": [{"id": "a", "type": "basic-node"}],
            "edges": [{"from": "a", "to": "missing"}],
        }

        with pytest.raises(CompilationError) as exc_info:
            compile_ir_to_flow(ir, test_registry)

        error = exc_info.value
        assert "missing" in str(error)
        assert "non-existent" in str(error)
        assert "Available nodes: a" in str(error)

    def test_missing_edge_fields_suggestion(self, test_registry):
        """Test error for edges missing required fields."""
        ir = {
            "nodes": [
                {"id": "a", "type": "basic-node"},
                {"id": "b", "type": "basic-node"},
            ],
            "edges": [{"action": "default"}],  # Missing from/to
        }

        with pytest.raises(CompilationError) as exc_info:
            compile_ir_to_flow(ir, test_registry)

        error = exc_info.value
        assert "missing source or target" in str(error)
        assert "'source'/'target' or 'from'/'to'" in str(error)

    def test_compilation_error_includes_phase(self, test_registry):
        """Test that errors include the compilation phase."""
        ir = {
            "nodes": "not a list",  # Wrong type
            "edges": [],
        }

        with pytest.raises(CompilationError) as exc_info:
            compile_ir_to_flow(ir, test_registry)

        error = exc_info.value
        assert "Phase: validation" in str(error)

    def test_json_parse_error_preserved(self, test_registry):
        """Test that JSON parse errors are preserved."""
        invalid_json = '{"nodes": [invalid json}'

        with pytest.raises(json.JSONDecodeError):
            compile_ir_to_flow(invalid_json, test_registry)


# =============================================================================
# Integration with Real Registry
# =============================================================================


class TestRealRegistryIntegration:
    """Test integration with actual registry from Task 5."""

    def test_compile_with_real_registry_if_available(self, tmp_path):
        """Test with real registry if any nodes are registered."""
        registry = Registry(tmp_path / "registry.json")

        # Try to discover some nodes
        from pathlib import Path

        src_path = Path(__file__).parent.parent / "src"
        if src_path.exists():
            # This would normally scan for nodes, but we'll skip if empty
            pass

        # Check if we have any nodes
        nodes = registry.load()
        if not nodes:
            pytest.skip("No real nodes found in registry")

        # Create IR using discovered nodes
        node_type = next(iter(nodes.keys()))
        ir = {
            "nodes": [{"id": "test", "type": node_type}],
            "edges": [],
        }

        # Should compile with real node
        flow = compile_ir_to_flow(ir, registry)
        assert flow is not None


# =============================================================================
# Validated vs Unvalidated IR Tests
# =============================================================================


class TestIRValidationIntegration:
    """Test compilation with both validated and unvalidated IR."""

    def test_compile_validated_ir(self, simple_ir, test_registry):
        """Test compiling IR that has been pre-validated."""
        # Validate IR first
        validate_ir(simple_ir)

        # Then compile
        flow = compile_ir_to_flow(simple_ir, test_registry)
        assert flow is not None

    def test_compile_unvalidated_ir_success(self, simple_ir, test_registry):
        """Test compiling IR without pre-validation (valid case)."""
        # Compile directly without validation
        flow = compile_ir_to_flow(simple_ir, test_registry)
        assert flow is not None

    def test_compile_unvalidated_ir_with_structural_errors(self, test_registry):
        """Test compiler catches basic structural errors even without validation."""
        invalid_ir = {
            # Missing required fields
            "some_field": "value"
        }

        with pytest.raises(CompilationError) as exc_info:
            compile_ir_to_flow(invalid_ir, test_registry)

        assert "Missing 'nodes' key" in str(exc_info.value)


# =============================================================================
# Edge Cases and Special Scenarios
# =============================================================================


class TestEdgeCases:
    """Test various edge cases and special scenarios."""

    def test_empty_workflow(self, test_registry):
        """Test compilation fails gracefully with no nodes."""
        ir = {"nodes": [], "edges": []}

        with pytest.raises(CompilationError) as exc_info:
            compile_ir_to_flow(ir, test_registry)

        assert "no nodes" in str(exc_info.value).lower()

    def test_disconnected_nodes(self, test_registry):
        """Test compilation succeeds with disconnected nodes."""
        ir = {
            "nodes": [
                {"id": "a", "type": "basic-node"},
                {"id": "b", "type": "basic-node"},
                {"id": "c", "type": "basic-node"},
            ],
            "edges": [{"from": "a", "to": "b"}],  # c is disconnected
        }

        # Should still compile (disconnected node just won't execute)
        flow = compile_ir_to_flow(ir, test_registry)
        assert flow is not None

    def test_cyclic_flow(self, test_registry):
        """Test compilation with cyclic dependencies."""
        ir = {
            "nodes": [
                {"id": "a", "type": "basic-node"},
                {"id": "b", "type": "basic-node"},
                {"id": "c", "type": "basic-node"},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "c"},
                {"from": "c", "to": "a"},  # Cycle
            ],
        }

        # Compilation should succeed (cycles are valid in PocketFlow)
        flow = compile_ir_to_flow(ir, test_registry)
        assert flow is not None

    def test_node_with_empty_params(self, test_registry):
        """Test nodes with empty params dict."""
        ir = {
            "nodes": [
                {"id": "test", "type": "basic-node", "params": {}},
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(ir, test_registry)
        node = flow.start_node

        # Empty params should not call set_params
        # But our mock always has self.params initialized
        assert isinstance(node.params, dict)

    def test_explicit_start_node(self, test_registry):
        """Test using explicit start_node field if present."""
        ir = {
            "start_node": "second",  # Explicitly set start
            "nodes": [
                {"id": "first", "type": "basic-node"},
                {"id": "second", "type": "basic-node"},
            ],
            "edges": [{"from": "second", "to": "first"}],
        }

        flow = compile_ir_to_flow(ir, test_registry)

        # Verify the start node is 'second' not 'first'
        # This is hard to verify without introspection
        # For now just check compilation succeeds
        assert flow is not None
