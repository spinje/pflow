"""Comprehensive unit tests for WorkflowExecutor covering all 26 test criteria."""

import json
from unittest.mock import Mock, patch

import pytest

from pflow.registry import Registry
from pflow.runtime.workflow_executor import WorkflowExecutor
from pocketflow import BaseNode


# Test node that fails during execution
class FailingExampleNode(BaseNode):
    """A test node that fails during execution."""

    def prep(self, shared):
        return {}

    def exec(self, prep_res):
        raise RuntimeError("Execution failed as expected")

    def post(self, shared, prep_res, exec_res):
        return "default"


class TestWorkflowExecutorComprehensive:
    """Comprehensive tests covering all 26 test criteria from spec."""

    @pytest.fixture
    def simple_workflow_ir(self):
        """Basic workflow IR for testing."""
        return {"nodes": [{"id": "test_node", "type": "echo", "params": {"message": "test"}}], "edges": []}

    @pytest.fixture
    def mock_registry(self, tmp_path):
        """Mock registry for testing."""
        registry_path = tmp_path / "test_registry.json"
        registry = Registry(registry_path)

        # Create minimal registry data
        registry_data = {
            "echo": {
                "module": "test.module",
                "class_name": "ExampleNode",
                "docstring": "Test node",
                "file_path": "/test/path.py",
            }
        }

        registry.save(registry_data)
        return registry

    # Test Criteria 1: workflow_ref only provided → loads and executes workflow
    def test_workflow_ref_only(self, simple_workflow_ir, tmp_path):
        """Test loading and executing workflow from file."""
        # Create temporary workflow file
        workflow_file = tmp_path / "test_workflow.json"
        with open(workflow_file, "w") as f:
            json.dump(simple_workflow_ir, f)

        node = WorkflowExecutor()
        node.set_params({"workflow_ref": str(workflow_file)})

        shared = {}
        prep_res = node.prep(shared)

        assert prep_res["workflow_ir"] == simple_workflow_ir
        assert prep_res["workflow_path"] == str(workflow_file)

    # Test Criteria 2: workflow_ir only provided → executes inline workflow
    def test_workflow_ir_only(self, simple_workflow_ir):
        """Test executing inline workflow."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir})

        shared = {}
        prep_res = node.prep(shared)

        assert prep_res["workflow_ir"] == simple_workflow_ir
        assert prep_res["workflow_path"] == "<inline>"

    # Test Criteria 3: neither parameter provided → raises ValueError
    def test_neither_parameter_provided(self):
        """Test error when neither workflow_ref nor workflow_ir provided."""
        node = WorkflowExecutor()
        node.set_params({})

        shared = {}
        with pytest.raises(ValueError, match="WorkflowExecutor requires either"):
            node.prep(shared)

    # Test Criteria 4: both parameters provided → raises ValueError
    def test_both_parameters_provided(self, simple_workflow_ir):
        """Test error when both workflow_ref and workflow_ir provided."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ref": "test.json", "workflow_ir": simple_workflow_ir})

        shared = {}
        with pytest.raises(ValueError, match="Only one of"):
            node.prep(shared)

    # Test Criteria 5: depth at max_depth → raises RecursionError
    def test_max_depth_exceeded(self, simple_workflow_ir):
        """Test error when maximum nesting depth exceeded."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir, "max_depth": 5})

        shared = {"_pflow_depth": 5}  # Already at max
        with pytest.raises(RecursionError, match="Maximum workflow nesting depth"):
            node.prep(shared)

    # Test Criteria 6: workflow in execution stack → raises ValueError with cycle
    def test_circular_dependency_simple(self, simple_workflow_ir, tmp_path):
        """Test circular dependency detection."""
        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(simple_workflow_ir))

        node = WorkflowExecutor()
        node.set_params({"workflow_ref": str(workflow_file)})

        shared = {
            "_pflow_stack": [str(workflow_file)]  # Already in stack
        }

        with pytest.raises(ValueError, match="Circular workflow reference"):
            node.prep(shared)

    # Test Criteria 7: workflow file missing → raises FileNotFoundError
    def test_workflow_file_missing(self):
        """Test error when workflow file doesn't exist."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ref": "/non/existent/file.json"})

        shared = {}
        with pytest.raises(FileNotFoundError, match="Workflow file not found"):
            node.prep(shared)

    # Test Criteria 8: workflow JSON malformed → raises ValueError
    def test_malformed_json(self, tmp_path):
        """Test error when workflow JSON is malformed."""
        workflow_file = tmp_path / "malformed.json"
        workflow_file.write_text("{invalid json")

        node = WorkflowExecutor()
        node.set_params({"workflow_ref": str(workflow_file)})

        shared = {}
        with pytest.raises(ValueError, match="Invalid JSON"):
            node.prep(shared)

    # Test Criteria 9: param_mapping with template → resolves correctly
    def test_template_resolution(self, simple_workflow_ir):
        """Test template resolution in parameter mapping."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "param_mapping": {"simple": "$value", "nested": "$obj.field", "static": "literal"},
        })

        shared = {"value": "resolved", "obj": {"field": "nested_value"}}

        prep_res = node.prep(shared)
        assert prep_res["child_params"]["simple"] == "resolved"
        assert prep_res["child_params"]["nested"] == "nested_value"
        assert prep_res["child_params"]["static"] == "literal"

    # Test Criteria 10: storage_mode "mapped" → child sees only mapped params
    def test_storage_mode_mapped(self, simple_workflow_ir):
        """Test mapped storage mode isolation."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "param_mapping": {"allowed": "$value"},
            "storage_mode": "mapped",
        })

        parent_shared = {"value": "mapped_value", "other": "should_not_see"}

        prep_res = node.prep(parent_shared)
        child_storage = node._create_child_storage(parent_shared, "mapped", prep_res)

        assert child_storage["allowed"] == "mapped_value"
        assert "other" not in child_storage
        assert "_pflow_depth" in child_storage  # System keys preserved

    # Test Criteria 11: storage_mode "isolated" → child sees empty storage
    def test_storage_mode_isolated(self, simple_workflow_ir):
        """Test isolated storage mode."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir, "storage_mode": "isolated"})

        parent_shared = {"data": "parent_data"}
        prep_res = node.prep(parent_shared)
        child_storage = node._create_child_storage(parent_shared, "isolated", prep_res)

        # Should only have system keys
        user_keys = [k for k in child_storage if not k.startswith("_pflow_")]
        assert len(user_keys) == 0

    # Test Criteria 12: storage_mode "scoped" → child sees filtered storage
    def test_storage_mode_scoped(self, simple_workflow_ir):
        """Test scoped storage mode."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir, "storage_mode": "scoped", "scope_prefix": "child_"})

        parent_shared = {"child_data": "visible", "parent_data": "hidden", "child_nested": {"key": "value"}}

        prep_res = node.prep(parent_shared)
        child_storage = node._create_child_storage(parent_shared, "scoped", prep_res)

        assert child_storage["data"] == "visible"
        assert child_storage["nested"] == {"key": "value"}
        assert "parent_data" not in child_storage

    # Test Criteria 13: storage_mode "shared" → child uses parent storage
    def test_storage_mode_shared(self, simple_workflow_ir):
        """Test shared storage mode."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir, "storage_mode": "shared"})

        parent_shared = {"data": "shared_data"}
        prep_res = node.prep(parent_shared)
        child_storage = node._create_child_storage(parent_shared, "shared", prep_res)

        assert child_storage is parent_shared  # Same object reference

    # Test Criteria 14: child compilation error → returns error result
    def test_compilation_error(self, simple_workflow_ir):
        """Test handling of compilation errors."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "__registry__": None,  # Will cause compilation to fail
        })

        prep_res = {
            "workflow_ir": {"invalid": "ir"},  # Invalid IR
            "workflow_path": "test.json",
            "child_params": {},
            "storage_mode": "mapped",
        }

        with patch("pflow.runtime.compile_ir_to_flow") as mock_compile:
            mock_compile.side_effect = Exception("Compilation failed")
            exec_res = node.exec(prep_res)

        assert exec_res["success"] is False
        assert "Failed to compile" in exec_res["error"]

    # Test Criteria 15: child execution error → returns error result
    def test_execution_error(self, tmp_path):
        """Test handling of execution errors."""
        # Create a registry with our failing test node
        registry_path = tmp_path / "test_registry.json"
        registry = Registry(registry_path)

        registry_data = {
            "failing_node": {
                "module": "tests.test_runtime.test_workflow_executor.test_workflow_executor_comprehensive",
                "class_name": "FailingExampleNode",
                "docstring": "A test node that fails during execution",
                "file_path": __file__,
            }
        }
        registry.save(registry_data)

        # Create workflow that uses the failing node
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "fail", "type": "failing_node", "params": {}}],
            "edges": [],
        }

        node = WorkflowExecutor()
        node.set_params({"workflow_ir": workflow_ir, "__registry__": registry})

        # Prepare and execute
        shared = {}
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)

        assert exec_res["success"] is False
        assert "Sub-workflow execution failed" in exec_res["error"]
        assert "Execution failed as expected" in exec_res["error"]

    # Test Criteria 16: successful execution → applies output mapping
    def test_output_mapping(self, simple_workflow_ir):
        """Test output mapping after successful execution."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "output_mapping": {"result": "parent_result", "score": "analysis_score"},
        })

        shared = {}
        prep_res = node.prep(shared)
        exec_res = {
            "success": True,
            "result": "default",
            "child_storage": {"result": "child_value", "score": 95, "internal": "ignored"},
            "storage_mode": "mapped",
        }

        action = node.post(shared, prep_res, exec_res)

        assert shared["parent_result"] == "child_value"
        assert shared["analysis_score"] == 95
        assert "internal" not in shared
        assert action == "default"

    # Test Criteria 17: child returns "custom_action" → returns "custom_action"
    def test_custom_action_return(self, simple_workflow_ir):
        """Test propagation of custom action from child."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir})

        shared = {}
        prep_res = node.prep(shared)
        exec_res = {"success": True, "result": "custom_action", "child_storage": {}, "storage_mode": "mapped"}

        action = node.post(shared, prep_res, exec_res)
        assert action == "custom_action"

    # Test Criteria 18: child returns None → returns "default"
    def test_none_return_default(self, simple_workflow_ir):
        """Test default action when child returns None."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir})

        shared = {}
        prep_res = node.prep(shared)
        exec_res = {"success": True, "result": None, "child_storage": {}, "storage_mode": "mapped"}

        action = node.post(shared, prep_res, exec_res)
        assert action == "default"

    # Test Criteria 19: relative workflow_ref → resolves from parent directory
    def test_relative_path_resolution(self, simple_workflow_ir, tmp_path):
        """Test relative path resolution."""
        # Create parent and child workflow files
        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        child_dir = tmp_path / "child"
        child_dir.mkdir()

        child_file = child_dir / "child.json"
        child_file.write_text(json.dumps(simple_workflow_ir))

        node = WorkflowExecutor()
        node.set_params({
            "workflow_ref": "../child/child.json"  # Relative path
        })

        shared = {"_pflow_workflow_file": str(parent_dir / "parent.json")}

        prep_res = node.prep(shared)
        assert prep_res["workflow_path"] == str(child_file.resolve())

    # Test Criteria 20: missing param in mapping → handles gracefully
    def test_missing_param_mapping(self, simple_workflow_ir):
        """Test handling of missing parameters in mapping."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "param_mapping": {"exists": "$present", "missing": "$not_there"},
        })

        shared = {"present": "value"}
        prep_res = node.prep(shared)

        assert prep_res["child_params"]["exists"] == "value"
        assert prep_res["child_params"]["missing"] == "$not_there"  # Templates preserve unresolved variables

    # Test Criteria 21: missing output key → skips mapping
    def test_missing_output_key(self, simple_workflow_ir):
        """Test handling of missing output keys."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "output_mapping": {"exists": "target1", "missing": "target2"},
        })

        shared = {}
        prep_res = node.prep(shared)
        exec_res = {
            "success": True,
            "result": "default",
            "child_storage": {"exists": "value"},
            "storage_mode": "mapped",
        }

        node.post(shared, prep_res, exec_res)

        assert shared["target1"] == "value"
        assert "target2" not in shared  # Skipped due to missing key

    # Test Criteria 22: invalid storage_mode → raises ValueError
    def test_invalid_storage_mode(self, simple_workflow_ir):
        """Test error on invalid storage mode."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir, "storage_mode": "invalid_mode"})

        parent_shared = {}
        prep_res = node.prep(parent_shared)

        with pytest.raises(ValueError, match="Invalid storage_mode"):
            node._create_child_storage(parent_shared, "invalid_mode", prep_res)

    # Test Criteria 23: multi-level circular dependency → detects cycle
    def test_multilevel_circular_dependency(self, simple_workflow_ir, tmp_path):
        """Test detection of multi-level circular dependencies."""
        workflow_file = tmp_path / "workflow.json"
        workflow_file.write_text(json.dumps(simple_workflow_ir))

        node = WorkflowExecutor()
        node.set_params({"workflow_ref": str(workflow_file)})

        shared = {
            "_pflow_stack": [
                "/workflow1.json",
                "/workflow2.json",
                str(workflow_file),  # Creates cycle
            ]
        }

        with pytest.raises(ValueError) as exc_info:
            node.prep(shared)

        assert "Circular workflow reference" in str(exc_info.value)
        assert "/workflow1.json" in str(exc_info.value)

    # Test Criteria 24: malformed child IR → wraps error with context
    def test_malformed_child_ir_context(self):
        """Test error context for malformed child IR."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": {"missing": "nodes"},  # Invalid IR
            "__registry__": Mock(),
        })

        prep_res = node.prep({})

        with patch("pflow.runtime.compile_ir_to_flow") as mock_compile:
            mock_compile.side_effect = ValueError("Invalid IR structure")
            exec_res = node.exec(prep_res)

        assert exec_res["success"] is False
        assert "Failed to compile" in exec_res["error"]
        assert exec_res["workflow_path"] == "<inline>"

    # Test Criteria 25: reserved key modification → isolated to child
    def test_reserved_key_isolation(self, simple_workflow_ir):
        """Test that reserved keys are isolated to child."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir, "storage_mode": "mapped"})

        parent_shared = {"_pflow_depth": 1}
        prep_res = node.prep(parent_shared)
        child_storage = node._create_child_storage(parent_shared, "mapped", prep_res)

        # Child should have incremented depth
        assert child_storage["_pflow_depth"] == 2
        # Parent should remain unchanged
        assert parent_shared["_pflow_depth"] == 1

    # Test Criteria 26: concurrent execution → independent instances
    def test_concurrent_execution_independence(self, simple_workflow_ir):
        """Test that concurrent executions are independent."""
        node1 = WorkflowExecutor()
        node2 = WorkflowExecutor()

        node1.set_params({"workflow_ir": simple_workflow_ir, "param_mapping": {"data": "value1"}})
        node2.set_params({"workflow_ir": simple_workflow_ir, "param_mapping": {"data": "value2"}})

        shared1 = {}
        shared2 = {}

        prep_res1 = node1.prep(shared1)
        prep_res2 = node2.prep(shared2)

        # Ensure parameters are independent
        assert prep_res1["child_params"]["data"] == "value1"
        assert prep_res2["child_params"]["data"] == "value2"

        # Modify one shouldn't affect the other
        prep_res1["child_params"]["data"] = "modified"
        assert prep_res2["child_params"]["data"] == "value2"
