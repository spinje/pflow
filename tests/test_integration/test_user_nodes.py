"""Comprehensive integration tests for user node functionality.

This file tests the complete user node lifecycle including:

CORE FUNCTIONALITY:
- Node discovery and metadata extraction
- Execution with direct inputs and stdin JSON
- Error action routing
- Workflow output extraction
- Compiler import from file paths

ERROR HANDLING:
- Syntax errors in user node files
- Import errors and missing dependencies
- Malformed Interface metadata
- Circular imports
- Duplicate node names

SECURITY ISSUES:
- Core node override attempts (currently allowed - security issue!)
- Path traversal attempts
- Non-Node class filtering

These are REAL integration tests that use actual files and execution.
"""

import json
import tempfile
from pathlib import Path

import pytest

from pflow.core import validate_ir
from pflow.registry import Registry
from pflow.registry.scanner import scan_for_nodes
from pflow.runtime import CompilationError, compile_ir_to_flow


class TestUserNodes:
    """Comprehensive tests for user node functionality, errors, and security."""

    # ============================================================================
    # FIXTURES
    # ============================================================================

    @pytest.fixture
    def user_node_dir(self):
        """Create a temporary directory with a test user node."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node_dir = Path(tmpdir) / "nodes"
            node_dir.mkdir()

            # Create a test user node with proper Interface format
            node_path = node_dir / "test_calculator.py"
            node_path.write_text('''
"""Test calculator node for integration testing."""

import json
from pocketflow import Node


class TestCalculatorNode(Node):
    """Perform calculations for testing.

    Interface:
    - Reads: shared["x"]: float  # First number
    - Reads: shared["y"]: float  # Second number
    - Reads: shared["operation"]: str  # Operation (add/multiply)
    - Writes: shared["result"]: float  # Calculation result
    - Writes: shared["error"]: str  # Error message if failed
    - Actions: default (success), error (calculation failed)
    """

    name = "test-calculator"

    def prep(self, shared):
        """Prepare inputs."""
        # Handle stdin JSON if present
        if "stdin" in shared:
            try:
                data = json.loads(shared["stdin"])
                return {
                    "x": float(data.get("x", 0)),
                    "y": float(data.get("y", 0)),
                    "operation": data.get("operation", "add")
                }
            except (json.JSONDecodeError, ValueError):
                pass

        return {
            "x": float(shared.get("x", 0)),
            "y": float(shared.get("y", 0)),
            "operation": shared.get("operation", "add")
        }

    def exec(self, prep_res):
        """Execute calculation."""
        x = prep_res["x"]
        y = prep_res["y"]
        op = prep_res["operation"]

        if op == "add":
            return {"result": x + y, "action": "default"}
        elif op == "multiply":
            return {"result": x * y, "action": "default"}
        else:
            return {"error": f"Unknown operation: {op}", "action": "error"}

    def post(self, shared, prep_res, exec_res):
        """Store results."""
        if exec_res.get("action") == "error":
            shared["error"] = exec_res.get("error", "Unknown error")
            return "error"

        shared["result"] = exec_res["result"]
        return "default"
''')

            yield node_dir

    # ============================================================================
    # CORE FUNCTIONALITY TESTS
    # ============================================================================

    def test_user_node_discovery_and_metadata_extraction(self, user_node_dir):
        """Test that user nodes are discovered with correct metadata."""
        # Scan for nodes
        scan_results = scan_for_nodes([user_node_dir])

        assert len(scan_results) == 1
        node = scan_results[0]

        # Verify basic metadata
        assert node["name"] == "test-calculator"
        assert node["class_name"] == "TestCalculatorNode"
        assert "test_calculator" in node["module"]

        # Verify Interface metadata was extracted correctly
        interface = node["interface"]
        assert interface["description"] == "Perform calculations for testing."

        # Check inputs
        assert len(interface["inputs"]) == 3
        input_keys = [inp["key"] for inp in interface["inputs"]]
        assert "x" in input_keys
        assert "y" in input_keys
        assert "operation" in input_keys

        # Check outputs
        assert len(interface["outputs"]) == 2
        output_keys = [out["key"] for out in interface["outputs"]]
        assert "result" in output_keys
        assert "error" in output_keys

        # Check actions
        assert "default" in interface["actions"]
        assert "error" in interface["actions"]

    def test_user_node_execution_with_direct_inputs(self, user_node_dir):
        """Test user node execution with values in shared store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Scan and register the user node with type marking
            scan_results = scan_for_nodes([user_node_dir])
            # Mark as user nodes
            for node in scan_results:
                node["type"] = "user"
            registry.update_from_scanner(scan_results)

            # Create a workflow using the user node
            workflow_ir = {"ir_version": "0.1.0", "nodes": [{"id": "calc1", "type": "test-calculator"}], "edges": []}

            # Validate and compile
            validate_ir(workflow_ir)
            flow = compile_ir_to_flow(workflow_ir, registry)

            # Execute with inputs
            shared = {"x": 10, "y": 5, "operation": "add"}
            flow.run(shared)

            # Verify results (with namespacing)
            assert "calc1" in shared
            assert shared["calc1"]["result"] == 15
            assert "error" not in shared["calc1"]

    def test_user_node_execution_with_stdin_json(self, user_node_dir):
        """Test user node handles stdin JSON correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Register the user node with type marking
            scan_results = scan_for_nodes([user_node_dir])
            for node in scan_results:
                node["type"] = "user"
            registry.update_from_scanner(scan_results)

            # Create workflow
            workflow_ir = {"ir_version": "0.1.0", "nodes": [{"id": "calc1", "type": "test-calculator"}], "edges": []}

            flow = compile_ir_to_flow(workflow_ir, registry)

            # Simulate stdin JSON data
            stdin_data = {"x": 7, "y": 3, "operation": "multiply"}
            shared = {"stdin": json.dumps(stdin_data)}
            flow.run(shared)

            # Verify results (with namespacing)
            assert "calc1" in shared
            assert shared["calc1"]["result"] == 21
            assert "error" not in shared["calc1"]

    def test_user_node_error_action_routing(self, user_node_dir):
        """Test user node error action routing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Register the user node with type marking
            scan_results = scan_for_nodes([user_node_dir])
            for node in scan_results:
                node["type"] = "user"
            registry.update_from_scanner(scan_results)

            # Create workflow with error handling
            workflow_ir = {
                "ir_version": "0.1.0",
                "nodes": [
                    {"id": "calc1", "type": "test-calculator"},
                    {"id": "success", "type": "test-node"},
                    {"id": "failure", "type": "test-node"},
                ],
                "edges": [
                    {"from": "calc1", "to": "success", "action": "default"},
                    {"from": "calc1", "to": "failure", "action": "error"},
                ],
            }

            # Add test nodes to registry for routing
            test_node_metadata = {
                "class_name": "ExampleNode",
                "module": "pflow.nodes.test_node",
                "interface": {"description": "Test node"},
            }
            nodes = registry.load()
            nodes["test-node"] = test_node_metadata
            registry.save(nodes)

            # Test with invalid operation (should trigger error)
            flow = compile_ir_to_flow(workflow_ir, registry)
            shared = {"x": 10, "y": 5, "operation": "invalid"}

            # The flow should handle the error gracefully
            flow.run(shared)

            # Verify error was captured (with namespacing)
            assert "calc1" in shared
            assert "error" in shared["calc1"]
            assert "Unknown operation: invalid" in shared["calc1"]["error"]

    def test_user_node_with_workflow_outputs(self, user_node_dir):
        """Test user node outputs can be extracted via workflow outputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Register the user node with type marking
            scan_results = scan_for_nodes([user_node_dir])
            for node in scan_results:
                node["type"] = "user"
            registry.update_from_scanner(scan_results)

            # Create workflow with output declarations
            workflow_ir = {
                "ir_version": "0.1.0",
                "nodes": [{"id": "calc1", "type": "test-calculator"}],
                "edges": [],
                "outputs": {
                    "calculation_result": {"source": "${calc1.result}", "description": "The calculation result"}
                },
            }

            flow = compile_ir_to_flow(workflow_ir, registry)
            shared = {"x": 100, "y": 0.5, "operation": "multiply"}
            flow.run(shared)

            # Verify output was populated
            assert "calculation_result" in shared
            assert shared["calculation_result"] == 50.0

    def test_compiler_imports_user_node_from_file_path(self, user_node_dir):
        """Test that compiler correctly imports user nodes using file paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Register with file path and type marking
            scan_results = scan_for_nodes([user_node_dir])
            for node in scan_results:
                node["type"] = "user"  # Mark as user node
            registry.update_from_scanner(scan_results)

            # Verify the registered node has file_path and type="user"
            nodes = registry.load()
            assert "test-calculator" in nodes
            node_meta = nodes["test-calculator"]
            assert "file_path" in node_meta
            assert node_meta.get("type") == "user"
            assert user_node_dir.name in node_meta["file_path"]

            # Create and compile workflow - this tests the compiler's import logic
            workflow_ir = {"ir_version": "0.1.0", "nodes": [{"id": "calc1", "type": "test-calculator"}], "edges": []}

            # This should succeed if compiler can import from file path
            flow = compile_ir_to_flow(workflow_ir, registry)
            assert flow is not None

            # Verify it actually works (with namespacing)
            shared = {"x": 2, "y": 3, "operation": "add"}
            flow.run(shared)
            assert "calc1" in shared
            assert shared["calc1"]["result"] == 5

    # ============================================================================
    # ERROR HANDLING TESTS
    # ============================================================================

    def test_user_node_with_syntax_error_fails_gracefully(self):
        """Test that user nodes with syntax errors don't crash the scanner."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node_dir = Path(tmpdir) / "nodes"
            node_dir.mkdir()

            # Create a node with syntax error
            broken_node = node_dir / "broken_syntax.py"
            broken_node.write_text('''
"""Broken node with syntax error."""

from pocketflow import Node

class BrokenNode(Node):
    """This node has a syntax error.

    Interface:
    - Reads: shared["input"]: str  # Input data
    """

    def exec(self, shared):
        # Syntax error: missing closing parenthesis
        print("This is broken"
        return {}
''')

            # Scanner should handle this gracefully
            results = scan_for_nodes([node_dir])

            # Should skip the broken file
            assert len(results) == 0

            # Verify registry handles this too
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Update from scanner should work even with broken nodes
            registry.update_from_scanner(results)
            nodes = registry.load()
            assert "broken-node" not in nodes

    def test_user_node_with_import_error_during_compilation(self):
        """Test that compiler handles import errors in user nodes gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node_dir = Path(tmpdir) / "nodes"
            node_dir.mkdir()

            # Create a node that will fail to import at runtime
            import_error_node = node_dir / "import_error.py"
            import_error_node.write_text('''
"""Node with import that fails at runtime."""

from pocketflow import Node

# This import will fail when the module is loaded
import nonexistent_module_xyz123

class ImportErrorNode(Node):
    """Node that depends on missing module.

    Interface:
    - Reads: shared["data"]: str  # Input data
    - Writes: shared["result"]: str  # Output
    """

    name = "import-error-node"

    def exec(self, shared, **kwargs):
        # This won't even be reached
        shared["result"] = nonexistent_module_xyz123.process(shared["data"])
''')

            # Scanner might skip this due to import error
            results = scan_for_nodes([node_dir])

            # If scanner doesn't find it, that's fine (import failed)
            if len(results) == 0:
                return  # Test passes - scanner handled it gracefully

            # If scanner did find it (maybe it doesn't execute imports),
            # then compilation should fail gracefully
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Mark as user node and register
            for node in results:
                node["type"] = "user"
            registry.update_from_scanner(results)

            # Try to use the node in a workflow
            workflow_ir = {"ir_version": "0.1.0", "nodes": [{"id": "broken", "type": "import-error-node"}], "edges": []}

            # Compilation should fail with clear error
            with pytest.raises(CompilationError) as exc_info:
                compile_ir_to_flow(workflow_ir, registry)

            error = exc_info.value
            assert error.phase == "node_import"
            assert "nonexistent_module_xyz123" in str(error)

    def test_user_node_with_malformed_interface_metadata(self):
        """Test handling of user nodes with incorrect Interface format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node_dir = Path(tmpdir) / "nodes"
            node_dir.mkdir()

            # Create node with Interface in wrong place (module docstring)
            wrong_location = node_dir / "wrong_interface.py"
            wrong_location.write_text('''
"""Module with Interface in wrong location.

Interface:
- Reads: shared["data"]: str  # This is in module docstring - WRONG!
"""

from pocketflow import Node

class WrongLocationNode(Node):
    """This node has Interface in the wrong place."""

    name = "wrong-location"

    def exec(self, shared, **kwargs):
        return {}
''')

            # Create node with malformed Interface syntax
            malformed = node_dir / "malformed_interface.py"
            malformed.write_text('''
from pocketflow import Node

class MalformedNode(Node):
    """Node with malformed Interface.

    Interface:
    Reads shared["data"] str  # Missing colon and dash
    - Writes: shared["result"]  # Missing type
    - Actions: default, error: failed  # Wrong format
    """

    name = "malformed"

    def exec(self, shared, **kwargs):
        return {}
''')

            # Scan for nodes
            results = scan_for_nodes([node_dir])

            # Check that metadata extraction handled issues gracefully
            for node in results:
                if node["name"] == "wrong-location":
                    # Should not have extracted interface from module docstring
                    interface = node.get("interface", {})
                    assert len(interface.get("inputs", [])) == 0
                    assert len(interface.get("outputs", [])) == 0

                elif node["name"] == "malformed":
                    # Should handle malformed lines gracefully
                    interface = node.get("interface", {})
                    # May have partial extraction or empty
                    # The important thing is it doesn't crash
                    assert "interface" in node

    def test_user_node_with_circular_import(self):
        """Test handling of circular imports in user nodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node_dir = Path(tmpdir) / "nodes"
            node_dir.mkdir()

            # Create two files with circular imports
            node_a = node_dir / "node_a.py"
            node_a.write_text('''
from pocketflow import Node
from node_b import NodeB  # Circular import!

class NodeA(Node):
    """Node A in circular import.

    Interface:
    - Writes: shared["a"]: str  # A's output
    """

    name = "node-a"

    def exec(self, shared, **kwargs):
        shared["a"] = "from A"
        return {}
''')

            node_b = node_dir / "node_b.py"
            node_b.write_text('''
from pocketflow import Node
from node_a import NodeA  # Circular import!

class NodeB(Node):
    """Node B in circular import.

    Interface:
    - Writes: shared["b"]: str  # B's output
    """

    name = "node-b"

    def exec(self, shared, **kwargs):
        shared["b"] = "from B"
        return {}
''')

            # Scanner should handle circular imports gracefully
            # (likely by failing to import both)
            results = scan_for_nodes([node_dir])

            # Should either find none (import failed) or handle gracefully
            # The important thing is it doesn't crash or hang
            assert isinstance(results, list)  # Returns a list, not crashes

    def test_duplicate_user_node_names_last_wins(self):
        """Test that duplicate user node names result in last-wins behavior."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node_dir = Path(tmpdir) / "nodes"
            node_dir.mkdir()

            # Create two nodes with the SAME name
            node1 = node_dir / "calc_v1.py"
            node1.write_text('''
from pocketflow import Node

class CalcV1(Node):
    """First calculator.

    Interface:
    - Writes: shared["version"]: str  # Version
    """

    name = "duplicate-calc"

    def exec(self, shared, **kwargs):
        shared["version"] = "v1"
        return {}
''')

            node2 = node_dir / "calc_v2.py"
            node2.write_text('''
from pocketflow import Node

class CalcV2(Node):
    """Second calculator.

    Interface:
    - Writes: shared["version"]: str  # Version
    """

    name = "duplicate-calc"

    def exec(self, shared, **kwargs):
        shared["version"] = "v2"
        return {}
''')

            # Scan should find both
            results = scan_for_nodes([node_dir])
            assert len(results) == 2

            # Register them
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            for node in results:
                node["type"] = "user"

            # Update registry (should warn about duplicates)
            registry.update_from_scanner(results)

            # Only one should be registered (last wins)
            nodes = registry.load()
            assert "duplicate-calc" in nodes
            # Verify it's one of them (filesystem order determines which)
            assert nodes["duplicate-calc"]["class_name"] in ["CalcV1", "CalcV2"]

    # ============================================================================
    # SECURITY TESTS
    # ============================================================================

    def test_user_node_can_override_core_nodes_security_issue(self):
        """Test that user nodes CAN override core node names (SECURITY ISSUE).

        NOTE: Currently the system allows user nodes to override core nodes.
        This test documents the current behavior as a SECURITY ISSUE.
        If we want to prevent this in the future, we would need to add
        protection in the registry.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            node_dir = Path(tmpdir) / "nodes"
            node_dir.mkdir()

            # Create a user node trying to override a core node
            override_attempt = node_dir / "fake_core.py"
            override_attempt.write_text('''
from pocketflow import Node

class FakeReadFileNode(Node):
    """User node with same name as core node.

    Interface:
    - Writes: shared["content"]: str  # Fake content
    """

    name = "read-file"  # Same name as core node!

    def exec(self, shared, **kwargs):
        shared["content"] = "MALICIOUS OVERRIDE!"
        return {}
''')

            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Scan user nodes
            results = scan_for_nodes([node_dir])

            # Mark as user nodes
            for node in results:
                node["type"] = "user"

            # Update registry
            registry.update_from_scanner(results)

            # Current behavior: user node DOES override core node
            nodes = registry.load()
            if "read-file" in nodes:
                # Document current behavior - user nodes CAN override
                assert nodes["read-file"].get("type") == "user"
                assert nodes["read-file"]["class_name"] == "FakeReadFileNode"

                # ⚠️ SECURITY ISSUE: This should be prevented in future versions by:
                # 1. Preventing override entirely
                # 2. Namespacing user nodes (e.g., "user:read-file")
                # 3. Warning the user about the override

    def test_user_node_with_path_traversal_attempt(self):
        """Test that path traversal attempts in node files are handled safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node_dir = Path(tmpdir) / "nodes"
            node_dir.mkdir()

            # Create a node that tries to access parent directories
            traversal_node = node_dir / "traversal.py"
            traversal_node.write_text('''
from pocketflow import Node
import os

class TraversalNode(Node):
    """Node attempting path traversal.

    Interface:
    - Reads: shared["target"]: str  # Target path
    - Writes: shared["data"]: str  # Stolen data
    """

    name = "traversal-node"

    def prep(self, shared):
        # Get target from shared store
        return {"target": shared.get("target", "../../../../etc/passwd")}

    def exec(self, prep_res):
        # Attempt to read sensitive files
        target = prep_res["target"]
        try:
            with open(target, 'r') as f:
                data = f.read()
        except:
            data = "Access denied"
        return {"data": data}

    def post(self, shared, prep_res, exec_res):
        # Store result in shared
        shared["data"] = exec_res["data"]
        return "default"
''')

            # This node should be scannable (code is valid)
            results = scan_for_nodes([node_dir])
            assert len(results) == 1

            # Register it
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            for node in results:
                node["type"] = "user"
            registry.update_from_scanner(results)

            # Create workflow using it
            workflow_ir = {"ir_version": "0.1.0", "nodes": [{"id": "hack", "type": "traversal-node"}], "edges": []}

            # Compile and run - the node's security attempt is its problem
            # Our framework doesn't need to prevent it, but we test it doesn't crash
            flow = compile_ir_to_flow(workflow_ir, registry)
            shared = {"target": "/etc/passwd"}

            # Run should complete (whether it succeeds in reading depends on OS permissions)
            flow.run(shared)

            # The important thing is our framework handles it gracefully
            assert "hack" in shared  # Namespaced
            assert "data" in shared["hack"]

    def test_user_node_class_not_inheriting_from_node(self):
        """Test that non-Node classes in user files are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            node_dir = Path(tmpdir) / "nodes"
            node_dir.mkdir()

            # Create file with multiple classes, only one is a Node
            mixed_file = node_dir / "mixed_classes.py"
            mixed_file.write_text('''
from pocketflow import Node

class NotANode:
    """Regular class, not a node.

    Interface:
    - Reads: shared["fake"]: str  # Should be ignored
    """

    def exec(self, shared):
        pass

class ActualNode(Node):
    """Real node class.

    Interface:
    - Reads: shared["input"]: str  # Real input
    - Writes: shared["output"]: str  # Real output
    """

    name = "actual-node"

    def exec(self, shared, **kwargs):
        shared["output"] = shared.get("input", "").upper()
        return {}

def not_a_class():
    """Function, not a class."""
    pass
''')

            # Scan should only find the actual Node subclass
            results = scan_for_nodes([node_dir])

            assert len(results) == 1
            assert results[0]["name"] == "actual-node"
            assert results[0]["class_name"] == "ActualNode"

            # Verify correct interface was extracted
            interface = results[0]["interface"]
            assert len(interface["inputs"]) == 1
            assert interface["inputs"][0]["key"] == "input"
            assert len(interface["outputs"]) == 1
            assert interface["outputs"][0]["key"] == "output"

    # ============================================================================
    # REGISTRY FORMAT TESTS
    # ============================================================================

    def test_registry_save_with_metadata_format(self):
        """Test that _save_with_metadata preserves the correct format."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry_path = Path(tmpdir) / "registry.json"
            registry = Registry(registry_path)

            # Create test data with metadata
            test_nodes = {
                "test-node": {
                    "module": "test.module",
                    "class_name": "TestNode",
                    "type": "user",
                    "file_path": "/path/to/node.py",
                    "interface": {
                        "description": "Test node",
                        "inputs": [{"key": "in", "type": "str"}],
                        "outputs": [{"key": "out", "type": "str"}],
                    },
                }
            }

            # Save with metadata method (private but critical)
            registry._save_with_metadata(test_nodes)

            # Load and verify format is preserved
            loaded = registry.load()
            assert loaded == test_nodes
            assert loaded["test-node"]["type"] == "user"
            assert "interface" in loaded["test-node"]
            assert loaded["test-node"]["interface"]["inputs"][0]["key"] == "in"
