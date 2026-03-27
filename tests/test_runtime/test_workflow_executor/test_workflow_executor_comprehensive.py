"""Comprehensive unit tests for WorkflowExecutor covering the new API.

API changes from the old version:
- workflow_ref/workflow_name → workflow (file path or saved name)
- param_mapping → pass child params directly as non-reserved params
- output_mapping → removed (auto-outputs via namespace)
- isolated/scoped storage modes → removed (only mapped and shared)
- Reserved params: workflow, workflow_ir, storage_mode, max_depth, error_action, __registry__
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pflow.pocketflow import BaseNode
from pflow.registry import Registry
from pflow.runtime.compilation.compiler import CompilationError
from pflow.runtime.workflow_executor import WorkflowExecutor
from tests.shared.markdown_utils import write_workflow_file


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
    """Comprehensive tests covering the WorkflowExecutor API."""

    @pytest.fixture
    def simple_workflow_ir(self):
        """Basic workflow IR for testing."""
        return {
            "nodes": [{"id": "test_node", "type": "echo", "params": {"message": "test"}}],
            "edges": [],
        }

    # --- Test 1: workflow file reference loads and parses correctly ---

    def test_workflow_file_reference(self, simple_workflow_ir, tmp_path):
        """Test loading and executing workflow from file path."""
        workflow_file = tmp_path / "test_workflow.pflow.md"
        write_workflow_file(simple_workflow_ir, workflow_file)

        node = WorkflowExecutor()
        node.set_params({"workflow": str(workflow_file)})

        shared = {}
        prep_res = node.prep(shared)

        loaded_ir = prep_res["workflow_ir"]
        assert loaded_ir["nodes"][0]["id"] == simple_workflow_ir["nodes"][0]["id"]
        assert loaded_ir["nodes"][0]["type"] == simple_workflow_ir["nodes"][0]["type"]
        assert loaded_ir["nodes"][0]["params"] == simple_workflow_ir["nodes"][0]["params"]
        assert prep_res["workflow_path"] == str(workflow_file)

    # --- Test 2: workflow_ir only provided ---

    def test_workflow_ir_only(self, simple_workflow_ir):
        """Test executing inline workflow."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir})

        shared = {}
        prep_res = node.prep(shared)

        assert prep_res["workflow_ir"] == simple_workflow_ir
        assert prep_res["workflow_path"] == "<inline>"

    # --- Test 3: neither parameter provided ---

    def test_neither_parameter_provided(self):
        """Test error when neither workflow nor workflow_ir provided."""
        node = WorkflowExecutor()
        node.set_params({})

        shared = {}
        with pytest.raises(ValueError, match="requires either 'workflow' or 'workflow_ir'"):
            node.prep(shared)

    # --- Test 4: both parameters provided ---

    def test_both_parameters_provided(self, simple_workflow_ir, tmp_path):
        """Test error when both workflow and workflow_ir provided."""
        workflow_file = tmp_path / "test.pflow.md"
        write_workflow_file(simple_workflow_ir, workflow_file)

        node = WorkflowExecutor()
        node.set_params({"workflow": str(workflow_file), "workflow_ir": simple_workflow_ir})

        shared = {}
        with pytest.raises(ValueError, match="Only one of 'workflow' or 'workflow_ir'"):
            node.prep(shared)

    # --- Test 5: depth at max_depth ---

    def test_max_depth_exceeded(self, simple_workflow_ir):
        """Test error when maximum nesting depth exceeded."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir, "max_depth": 5})

        shared = {"_pflow_depth": 5}
        with pytest.raises(RecursionError, match="Maximum workflow nesting depth"):
            node.prep(shared)

    # --- Test 6: circular dependency detection ---

    def test_circular_dependency_simple(self, simple_workflow_ir, tmp_path):
        """Test circular dependency detection for file references."""
        workflow_file = tmp_path / "workflow.pflow.md"
        write_workflow_file(simple_workflow_ir, workflow_file)

        node = WorkflowExecutor()
        node.set_params({"workflow": str(workflow_file)})

        shared = {"_pflow_stack": [str(workflow_file)]}

        with pytest.raises(ValueError, match="Circular workflow reference"):
            node.prep(shared)

    # --- Test 7: workflow file missing ---

    def test_workflow_file_missing(self):
        """Test error when workflow file doesn't exist."""
        node = WorkflowExecutor()
        node.set_params({"workflow": "/non/existent/file.pflow.md"})

        shared = {}
        with pytest.raises(FileNotFoundError, match="Workflow file not found"):
            node.prep(shared)

    # --- Test 8: malformed workflow file ---

    def test_malformed_workflow(self, tmp_path):
        """Test error when workflow file is malformed."""
        workflow_file = tmp_path / "malformed.pflow.md"
        workflow_file.write_text("# Bad Workflow\n\nJust some text, no steps.\n")

        node = WorkflowExecutor()
        node.set_params({"workflow": str(workflow_file)})

        shared = {}
        with pytest.raises(ValueError):
            node.prep(shared)

    # --- Test 9: template resolution in direct params ---

    def test_template_resolution(self, simple_workflow_ir):
        """Test template resolution in params passed directly as child inputs."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "simple": "${value}",
            "nested": "${obj.field}",
            "static": "literal",
        })

        shared = {"value": "resolved", "obj": {"field": "nested_value"}}

        prep_res = node.prep(shared)
        assert prep_res["child_params"]["simple"] == "resolved"
        assert prep_res["child_params"]["nested"] == "nested_value"
        assert prep_res["child_params"]["static"] == "literal"

    # --- Test 10: storage_mode "mapped" ---

    def test_storage_mode_mapped(self, simple_workflow_ir):
        """Test mapped storage mode: child sees only mapped params."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "allowed": "${value}",
            "storage_mode": "mapped",
        })

        parent_shared = {"value": "mapped_value", "other": "should_not_see"}

        prep_res = node.prep(parent_shared)
        child_storage = node._create_child_storage(parent_shared, "mapped", prep_res)

        assert child_storage["allowed"] == "mapped_value"
        assert "other" not in child_storage
        assert "_pflow_depth" in child_storage

    # --- Test 13: storage_mode "shared" ---

    def test_storage_mode_shared(self, simple_workflow_ir):
        """Test shared storage mode: child uses same storage as parent."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir, "storage_mode": "shared"})

        parent_shared = {"data": "shared_data"}
        prep_res = node.prep(parent_shared)
        child_storage = node._create_child_storage(parent_shared, "shared", prep_res)

        assert child_storage is parent_shared

    # --- Test 14: compilation error ---

    def test_compilation_error(self, simple_workflow_ir):
        """Test that compilation errors propagate as CompilationError (never swallowed)."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "__registry__": None,
        })

        prep_res = {
            "workflow_ir": {"invalid": "ir"},
            "workflow_path": "test.json",
            "child_params": {},
            "storage_mode": "mapped",
        }

        # CompilationError propagates directly
        with patch("pflow.runtime.workflow_executor.compile_ir_to_flow") as mock_compile:
            mock_compile.side_effect = CompilationError("Compilation failed", phase="test")
            with pytest.raises(CompilationError, match="Compilation failed"):
                node.exec(prep_res)

        # Other exceptions are wrapped in CompilationError
        with patch("pflow.runtime.workflow_executor.compile_ir_to_flow") as mock_compile:
            mock_compile.side_effect = ValueError("Bad IR structure")
            with pytest.raises(CompilationError, match="Failed to compile sub-workflow"):
                node.exec(prep_res)

    # --- Test 15: execution error ---

    def test_execution_error(self, tmp_path):
        """Test handling of execution errors."""
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

        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "fail", "type": "failing_node", "params": {}}],
            "edges": [],
        }

        node = WorkflowExecutor()
        node.set_params({"workflow_ir": workflow_ir, "__registry__": registry})

        shared = {}
        prep_res = node.prep(shared)
        exec_res = node.exec(prep_res)

        assert exec_res["success"] is False
        assert "Sub-workflow execution failed" in exec_res["error"]
        assert "Execution failed as expected" in exec_res["error"]

    # --- Test 16: auto-outputs with declared outputs ---

    def test_auto_outputs_declared(self, simple_workflow_ir):
        """When child IR has outputs declarations, only those are exposed to parent."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir})

        shared = {}
        # Simulate IR with declared outputs
        prep_res = {
            "workflow_ir": {
                "nodes": [],
                "outputs": {"result": {"description": "The result"}, "score": {"description": "Score"}},
            },
            "child_params": {},
        }
        exec_res = {
            "success": True,
            "result": "default",
            "child_storage": {
                "result": "child_value",
                "score": 95,
                "internal": "should_not_be_exposed",
                "_pflow_depth": 1,
            },
            "storage_mode": "mapped",
        }

        action = node.post(shared, prep_res, exec_res)

        assert shared["result"] == "child_value"
        assert shared["score"] == 95
        assert "internal" not in shared
        assert "_pflow_depth" not in shared
        assert action == "default"

    # --- Test 17: custom action return ---

    def test_custom_action_return(self, simple_workflow_ir):
        """Test propagation of custom action from child."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir})

        shared = {}
        prep_res = node.prep(shared)
        exec_res = {"success": True, "result": "custom_action", "child_storage": {}, "storage_mode": "mapped"}

        action = node.post(shared, prep_res, exec_res)
        assert action == "custom_action"

    # --- Test 18: None return defaults to "default" ---

    def test_none_return_default(self, simple_workflow_ir):
        """Test default action when child returns None."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir})

        shared = {}
        prep_res = node.prep(shared)
        exec_res = {"success": True, "result": None, "child_storage": {}, "storage_mode": "mapped"}

        action = node.post(shared, prep_res, exec_res)
        assert action == "default"

    # --- Test 19: relative path resolution ---

    def test_relative_path_resolution(self, simple_workflow_ir, tmp_path):
        """Test relative path resolution from parent workflow directory."""
        parent_dir = tmp_path / "parent"
        parent_dir.mkdir()
        child_dir = tmp_path / "child"
        child_dir.mkdir()

        child_file = child_dir / "child.pflow.md"
        write_workflow_file(simple_workflow_ir, child_file)

        node = WorkflowExecutor()
        node.set_params({"workflow": "../child/child.pflow.md"})

        shared = {"_pflow_workflow_file": str(parent_dir / "parent.pflow.md")}

        prep_res = node.prep(shared)
        assert prep_res["workflow_path"] == str(child_file.resolve())

    # --- Test 20: unresolved template in input ---

    def test_unresolved_template_in_input(self, simple_workflow_ir):
        """Test that unresolved templates are preserved in child inputs."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "exists": "${present}",
            "missing": "${not_there}",
        })

        shared = {"present": "value"}
        prep_res = node.prep(shared)

        assert prep_res["child_params"]["exists"] == "value"
        # Unresolved templates are preserved as-is
        assert prep_res["child_params"]["missing"] == "${not_there}"

    # --- Test 23: invalid storage_mode ---

    def test_invalid_storage_mode(self, simple_workflow_ir):
        """Test error on invalid storage mode with helpful message."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir, "storage_mode": "invalid_mode"})

        parent_shared = {}
        prep_res = node.prep(parent_shared)

        with pytest.raises(ValueError, match="Use 'mapped' \\(default\\) or 'shared'"):
            node._create_child_storage(parent_shared, "invalid_mode", prep_res)

    # --- Test 24: multi-level circular dependency ---

    def test_multilevel_circular_dependency(self, simple_workflow_ir, tmp_path):
        """Test detection of multi-level circular dependencies."""
        workflow_file = tmp_path / "workflow.pflow.md"
        write_workflow_file(simple_workflow_ir, workflow_file)

        node = WorkflowExecutor()
        node.set_params({"workflow": str(workflow_file)})

        shared = {
            "_pflow_stack": [
                "/workflow1.pflow.md",
                "/workflow2.pflow.md",
                str(workflow_file),
            ]
        }

        with pytest.raises(ValueError) as exc_info:
            node.prep(shared)

        assert "Circular workflow reference" in str(exc_info.value)
        assert "/workflow1.pflow.md" in str(exc_info.value)

    # --- Test 25: malformed child IR context ---

    def test_malformed_child_ir_context(self):
        """Test error context for malformed child IR."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": {"missing": "nodes"},
            "__registry__": Mock(),
        })

        # Malformed IR (no 'nodes' key) is caught early in prep()
        with pytest.raises(ValueError, match="must contain 'nodes'"):
            node.prep({})

    # --- Test 26: reserved key isolation ---

    def test_reserved_key_isolation(self, simple_workflow_ir):
        """Test that reserved keys are isolated between parent and child."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir, "storage_mode": "mapped"})

        parent_shared = {"_pflow_depth": 1}
        prep_res = node.prep(parent_shared)
        child_storage = node._create_child_storage(parent_shared, "mapped", prep_res)

        assert child_storage["_pflow_depth"] == 2
        assert parent_shared["_pflow_depth"] == 1

    # --- Test 27: concurrent execution independence ---

    def test_concurrent_execution_independence(self, simple_workflow_ir):
        """Test that concurrent executions are independent."""
        node1 = WorkflowExecutor()
        node2 = WorkflowExecutor()

        node1.set_params({"workflow_ir": simple_workflow_ir, "data": "value1"})
        node2.set_params({"workflow_ir": simple_workflow_ir, "data": "value2"})

        shared1 = {}
        shared2 = {}

        prep_res1 = node1.prep(shared1)
        prep_res2 = node2.prep(shared2)

        assert prep_res1["child_params"]["data"] == "value1"
        assert prep_res2["child_params"]["data"] == "value2"

        # Modify one shouldn't affect the other
        prep_res1["child_params"]["data"] = "modified"
        assert prep_res2["child_params"]["data"] == "value2"

    # --- Test 28: missing required child input gives actionable error ---

    def test_missing_required_child_input_gives_actionable_error(self):
        """Missing required child input raises error with provided vs expected."""
        ir_with_inputs = {
            "ir_version": "0.1.0",
            "inputs": {
                "text": {"type": "string", "description": "The text to process"},
                "mode": {"type": "string", "default": "upper"},
            },
            "nodes": [{"id": "n1", "type": "test", "params": {}}],
            "edges": [],
        }

        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": ir_with_inputs,
            "wrong_name": "hello",
        })

        with pytest.raises(ValueError, match="missing required inputs") as exc_info:
            node.prep({})

        error_msg = str(exc_info.value)
        assert "text" in error_msg  # Shows which input is missing
        assert "wrong_name" in error_msg  # Shows what was provided
        # mode has default, should not appear as missing
        assert "mode" not in error_msg.split("missing required inputs")[0]

    # --- Test 29: all required inputs provided passes ---

    def test_all_required_inputs_provided_passes(self):
        """No error when all required inputs are provided."""
        ir_with_inputs = {
            "ir_version": "0.1.0",
            "inputs": {
                "text": {"type": "string", "description": "The text to process"},
                "mode": {"type": "string", "default": "upper"},
            },
            "nodes": [{"id": "n1", "type": "test", "params": {}}],
            "edges": [],
        }

        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": ir_with_inputs,
            "text": "hello",
        })

        # Should not raise — text is provided, mode has a default
        prep_res = node.prep({})
        assert prep_res["child_params"]["text"] == "hello"

    # --- Test 30: no declared inputs skips validation ---

    def test_no_declared_inputs_skips_validation(self, simple_workflow_ir):
        """Workflows without declared inputs skip param validation."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "anything": "goes",
        })

        # Should not raise — no declared inputs to validate against
        prep_res = node.prep({})
        assert prep_res["child_params"]["anything"] == "goes"

    # --- Test 31: relative path falls back to cwd ---

    def test_relative_path_falls_back_to_cwd(self):
        """When _pflow_workflow_file is not set, relative paths resolve from CWD."""
        node = WorkflowExecutor()
        resolved = node._resolve_safe_path("./some/relative.pflow.md", {})
        assert resolved == (Path.cwd() / "some" / "relative.pflow.md").resolve()

    # --- Test 32: _pflow_workflow_file flows to shared store ---

    def test_pflow_workflow_file_flows_to_shared_store(self):
        """_pflow_workflow_file in execution_params flows to shared store."""
        from pflow.execution.executor_service import WorkflowExecutorService

        service = WorkflowExecutorService()
        shared = service._initialize_shared_store(
            shared_store=None,
            execution_params={"_pflow_workflow_file": "/path/to/workflow.pflow.md"},
            stdin_data=None,
            metrics_collector=None,
        )
        assert shared["_pflow_workflow_file"] == "/path/to/workflow.pflow.md"

    # --- NEW: test_params_as_inputs_basic ---

    def test_params_as_inputs_basic(self, simple_workflow_ir):
        """Non-reserved params become child inputs; reserved params are excluded."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "text": "hello",
            "count": 5,
            "storage_mode": "mapped",
        })

        prep_res = node.prep({})

        assert prep_res["child_params"] == {"text": "hello", "count": 5}
        # storage_mode is reserved, not passed as child input
        assert "storage_mode" not in prep_res["child_params"]

    # --- NEW: test_auto_outputs_undeclared ---

    def test_auto_outputs_undeclared(self, simple_workflow_ir):
        """When child has no declared outputs, all non-internal root keys are exposed."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir})

        shared = {}
        prep_res = {
            "workflow_ir": {"nodes": []},  # No outputs in IR
            "child_params": {},
        }
        exec_res = {
            "success": True,
            "result": "default",
            "child_storage": {
                "node1": {"stdout": "hello"},
                "some_key": "value",
                "_pflow_depth": 1,
                "__execution__": {},
            },
            "storage_mode": "mapped",
        }

        action = node.post(shared, prep_res, exec_res)

        assert shared["node1"] == {"stdout": "hello"}
        assert shared["some_key"] == "value"
        assert "_pflow_depth" not in shared
        assert "__execution__" not in shared
        assert action == "default"

    # --- NEW: test_auto_outputs_skip_child_inputs ---

    def test_auto_outputs_skip_child_inputs(self, simple_workflow_ir):
        """When no declared outputs, child input params are NOT re-exposed."""
        node = WorkflowExecutor()
        node.set_params({"workflow_ir": simple_workflow_ir})

        shared = {}
        prep_res = {
            "workflow_ir": {"nodes": []},  # No declared outputs
            "child_params": {"text": "hello", "mode": "upper"},
        }
        exec_res = {
            "success": True,
            "result": "default",
            "child_storage": {
                "text": "hello",  # Same as child input — should be skipped
                "mode": "upper",  # Same as child input — should be skipped
                "result": "HELLO",  # New output — should be exposed
            },
            "storage_mode": "mapped",
        }

        action = node.post(shared, prep_res, exec_res)

        # Input params should NOT be re-exposed
        assert "text" not in shared
        assert "mode" not in shared
        # New output should be exposed
        assert shared["result"] == "HELLO"
        assert action == "default"

    # --- NEW: test_reserved_params_not_passed_as_inputs ---

    def test_reserved_params_not_passed_as_inputs(self, simple_workflow_ir):
        """Verify reserved params are NOT included in child_params."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "storage_mode": "mapped",
            "max_depth": 10,
            "error_action": "error",
            "__registry__": Mock(),
            "user_input": "this should be passed",
        })

        prep_res = node.prep({})

        # Only user_input should be in child_params
        assert prep_res["child_params"] == {"user_input": "this should be passed"}
        for reserved in ("workflow_ir", "storage_mode", "max_depth", "error_action", "__registry__"):
            assert reserved not in prep_res["child_params"]

    # --- NEW: test_is_file_reference ---

    def test_is_file_reference(self):
        """Test file reference classification logic."""
        # File references (contain / or \, start with ., or end with .pflow.md)
        assert WorkflowExecutor._is_file_reference("./child.pflow.md") is True
        assert WorkflowExecutor._is_file_reference("/absolute/path.pflow.md") is True
        assert WorkflowExecutor._is_file_reference("path/to/child.pflow.md") is True
        assert WorkflowExecutor._is_file_reference("..\\windows\\path.pflow.md") is True
        assert WorkflowExecutor._is_file_reference("child.pflow.md") is True  # ends with .pflow.md
        assert WorkflowExecutor._is_file_reference("./relative") is True  # starts with .

        # Saved names (no path separators, no dots prefix, no .pflow.md suffix)
        assert WorkflowExecutor._is_file_reference("my-workflow") is False
        assert WorkflowExecutor._is_file_reference("simple") is False

    # --- Test 33: 'inputs' key excluded from child inputs ---

    def test_inputs_not_passed_as_child_input(self):
        """Verify 'inputs' framework key is excluded from child inputs.

        The 'inputs' param is consumed by TemplateAwareNodeWrapper to inject
        additional template context. It must NOT leak through to child workflow
        inputs — it is a framework-level concern, not a user param.
        """
        executor = WorkflowExecutor()
        executor.params = {
            "workflow": "./child.pflow.md",
            "inputs": {"api_key": "xxx"},  # Framework key, not a child input
            "text": "hello",
            "count": 5,
        }
        child_inputs = executor._extract_child_inputs()
        assert "inputs" not in child_inputs
        assert "workflow" not in child_inputs  # Also reserved
        assert child_inputs == {"text": "hello", "count": 5}

    # --- Test 34: required: false with no default is not rejected ---

    def test_required_false_no_default_not_rejected(self, tmp_path):
        """Child input with required: false and no default should not raise.

        When a child workflow declares an input as optional (required: false),
        the parent should be able to omit it without triggering a validation error,
        even if no default value is specified.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "step", "type": "shell", "params": {"command": "echo hi"}}],
            "edges": [],
            "inputs": {
                "text": {"type": "string", "required": True},
                "optional_param": {"type": "string", "required": False},
            },
        }
        executor = WorkflowExecutor()
        # Only provide "text", not "optional_param"
        child_params = {"text": "hello"}
        # Should NOT raise
        executor._validate_child_params(workflow_ir, child_params, str(tmp_path / "child.pflow.md"))

    # --- Test 35: required: true with no default IS rejected ---

    def test_required_true_no_default_rejected(self, tmp_path):
        """Child input with required: true and no default should raise.

        This is the counterpart to test_required_false_no_default_not_rejected:
        when required is explicitly true (or implicitly true via the default),
        omitting the input must produce an actionable validation error.
        """
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "step", "type": "shell", "params": {"command": "echo hi"}}],
            "edges": [],
            "inputs": {
                "text": {"type": "string", "required": True},
                "count": {"type": "integer", "required": True},
            },
        }
        executor = WorkflowExecutor()
        child_params = {"text": "hello"}
        with pytest.raises(ValueError, match="missing required inputs"):
            executor._validate_child_params(workflow_ir, child_params, str(tmp_path / "child.pflow.md"))


class TestBatchCompilationErrorPropagation:
    """Verify CompilationError propagates through batch regardless of error_handling.

    Bug context: error_handling: continue was swallowing CompilationError from
    sub-workflows, causing the pipeline to continue on empty data. The fix
    ensures CompilationError is always re-raised (never retried, never swallowed).
    """

    @pytest.fixture
    def child_workflow_ir(self):
        """A valid-looking child workflow IR for WorkflowExecutor."""
        return {
            "ir_version": "0.1.0",
            "nodes": [{"id": "step1", "type": "echo", "params": {"message": "hello"}}],
            "edges": [],
        }

    @pytest.fixture
    def mock_registry(self, tmp_path):
        """A mock registry for WorkflowExecutor."""
        registry = Mock(spec=Registry)
        return registry

    def _build_batch_over_workflow_executor(
        self,
        child_workflow_ir: dict,
        mock_registry: Mock,
        error_handling: str = "continue",
        parallel: bool = False,
    ) -> tuple:
        """Build a PflowBatchNode wrapping NamespacedNodeWrapper wrapping WorkflowExecutor.

        Returns:
            (batch_node, shared_store) ready for execution.
        """
        from pflow.runtime.wrappers.batch_node import PflowBatchNode
        from pflow.runtime.wrappers.namespaced_wrapper import NamespacedNodeWrapper

        executor = WorkflowExecutor()
        executor.set_params({
            "workflow_ir": child_workflow_ir,
            "__registry__": mock_registry,
        })

        namespaced = NamespacedNodeWrapper(executor, "fetch-sources")
        batch = PflowBatchNode(
            inner_node=namespaced,
            node_id="fetch-sources",
            batch_config={
                "items": "${sources}",
                "error_handling": error_handling,
                "parallel": parallel,
                "max_retries": 1,
                "retry_wait": 0,
            },
        )

        shared = {"sources": ["item_a", "item_b", "item_c"]}
        return batch, shared

    def test_compilation_error_propagates_through_sequential_batch_with_continue(
        self, child_workflow_ir, mock_registry
    ):
        """When compile_ir_to_flow raises CompilationError, sequential batch must propagate it
        even with error_handling: continue. Compilation errors mean the workflow definition
        is broken — data-level error handling must not swallow them."""

        batch, shared = self._build_batch_over_workflow_executor(
            child_workflow_ir, mock_registry, error_handling="continue", parallel=False
        )

        # prep() resolves items from shared store
        items = batch.prep(shared)
        assert len(items) == 3

        with patch("pflow.runtime.workflow_executor.compile_ir_to_flow") as mock_compile:
            mock_compile.side_effect = CompilationError("Unknown node type 'fetch-rss'", phase="node_loading")
            with pytest.raises(CompilationError, match="Unknown node type"):
                batch._exec(items)

    def test_compilation_error_propagates_through_sequential_batch_with_fail_fast(
        self, child_workflow_ir, mock_registry
    ):
        """CompilationError propagates with fail_fast too (sanity check)."""
        batch, shared = self._build_batch_over_workflow_executor(
            child_workflow_ir, mock_registry, error_handling="fail_fast", parallel=False
        )

        items = batch.prep(shared)

        with patch("pflow.runtime.workflow_executor.compile_ir_to_flow") as mock_compile:
            mock_compile.side_effect = CompilationError("Missing required node", phase="validation")
            with pytest.raises(CompilationError, match="Missing required node"):
                batch._exec(items)

    def test_generic_exception_wrapped_as_compilation_error_propagates(self, child_workflow_ir, mock_registry):
        """When compile_ir_to_flow raises a generic Exception, WorkflowExecutor wraps
        it in CompilationError. This wrapped error must also propagate through batch."""
        batch, shared = self._build_batch_over_workflow_executor(
            child_workflow_ir, mock_registry, error_handling="continue", parallel=False
        )

        items = batch.prep(shared)

        with patch("pflow.runtime.workflow_executor.compile_ir_to_flow") as mock_compile:
            mock_compile.side_effect = ValueError("Bad IR structure")
            with pytest.raises(CompilationError, match="Failed to compile sub-workflow"):
                batch._exec(items)

    def test_compilation_error_propagates_through_parallel_batch_with_continue(self, child_workflow_ir, mock_registry):
        """When compile_ir_to_flow raises CompilationError, parallel batch must propagate it
        even with error_handling: continue. The error escapes the thread via future.result()."""
        batch, shared = self._build_batch_over_workflow_executor(
            child_workflow_ir, mock_registry, error_handling="continue", parallel=True
        )

        items = batch.prep(shared)

        with patch("pflow.runtime.workflow_executor.compile_ir_to_flow") as mock_compile:
            mock_compile.side_effect = CompilationError("Unknown node type 'fetch-rss'", phase="node_loading")
            # CompilationError propagates through the future and is re-raised
            # by _collect_parallel_results — never swallowed by error_handling
            with pytest.raises(CompilationError, match="Unknown node type"):
                batch._exec(items)

    def test_compilation_error_propagates_through_exec_single_directly(self, child_workflow_ir, mock_registry):
        """Test _exec_single directly: CompilationError is raised, not returned as error tuple."""
        batch, shared = self._build_batch_over_workflow_executor(
            child_workflow_ir, mock_registry, error_handling="continue", parallel=False
        )

        # prep() sets batch._shared
        batch.prep(shared)

        with patch("pflow.runtime.workflow_executor.compile_ir_to_flow") as mock_compile:
            mock_compile.side_effect = CompilationError("Node type not found", phase="node_loading")
            # _exec_single must raise CompilationError, not return it as an error tuple
            with pytest.raises(CompilationError, match="Node type not found"):
                batch._exec_single(0, "item_a")

    def test_compilation_error_not_retried(self, child_workflow_ir, mock_registry):
        """CompilationError must not trigger retry logic — retrying a broken workflow
        definition would just fail again."""

        batch, shared = self._build_batch_over_workflow_executor(
            child_workflow_ir, mock_registry, error_handling="continue", parallel=False
        )
        # Set max_retries to 3 — if CompilationError triggered retries,
        # compile_ir_to_flow would be called 3 times instead of 1
        batch.max_retries = 3

        batch.prep(shared)

        with patch("pflow.runtime.workflow_executor.compile_ir_to_flow") as mock_compile:
            mock_compile.side_effect = CompilationError("Broken workflow", phase="test")
            with pytest.raises(CompilationError):
                batch._exec_single(0, "item_a")

            # CompilationError should cause immediate raise — compile called only once
            assert mock_compile.call_count == 1
