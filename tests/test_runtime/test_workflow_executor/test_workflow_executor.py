"""Unit tests for WorkflowExecutor."""

from unittest.mock import MagicMock, patch

import pytest

from pflow.runtime.workflow_executor import WorkflowExecutor


class TestWorkflowExecutor:
    """Test WorkflowExecutor functionality."""

    def test_node_creation(self):
        """Test basic node instantiation."""
        node = WorkflowExecutor()
        assert node is not None
        assert hasattr(node, "prep")
        assert hasattr(node, "exec")
        assert hasattr(node, "post")

    def test_parameter_validation(self):
        """Test parameter validation in prep phase."""
        node = WorkflowExecutor()
        shared: dict = {}

        # No parameters should raise error
        node.set_params({})
        with pytest.raises(ValueError, match="requires either 'workflow' or 'workflow_ir'"):
            node.prep(shared)

        # Both parameters should raise error
        node.set_params({"workflow": "test.json", "workflow_ir": {"nodes": []}})
        with pytest.raises(ValueError, match="Only one of 'workflow' or 'workflow_ir'"):
            node.prep(shared)

    def test_circular_dependency_detection(self):
        """Test circular dependency detection."""
        node = WorkflowExecutor()

        # Set up circular reference — /path/to/workflow1.json is already in the stack
        shared = {"_pflow_stack": ["/path/to/workflow1.json", "/path/to/workflow2.json"]}

        node.set_params({
            "workflow": "/path/to/workflow1.json"  # Already in stack
        })

        with pytest.raises(ValueError, match="Circular workflow reference"):
            node.prep(shared)

    def test_max_depth_enforcement(self):
        """Test maximum nesting depth."""
        node = WorkflowExecutor()

        shared = {
            "_pflow_depth": 10  # Already at max depth
        }

        node.set_params({"workflow_ir": {"nodes": []}, "max_depth": 10})

        with pytest.raises(RecursionError, match="Maximum workflow nesting depth"):
            node.prep(shared)

    def test_parameter_mapping(self):
        """Test that non-reserved params are extracted as child inputs."""
        node = WorkflowExecutor()

        # Static values only — template resolution is tested via compiled pipeline
        node.set_params({
            "workflow_ir": {"nodes": []},
            "data": "test_value",
            "key": "secret",
            "static": "fixed_value",
        })

        prep_res = node.prep({})

        assert prep_res["child_params"]["data"] == "test_value"
        assert prep_res["child_params"]["key"] == "secret"
        assert prep_res["child_params"]["static"] == "fixed_value"

    def test_reserved_params_excluded_from_child_inputs(self):
        """Test that reserved params (workflow_ir, storage_mode, etc.) are not passed to child."""
        node = WorkflowExecutor()
        shared: dict = {}

        node.set_params({
            "workflow_ir": {"nodes": []},
            "storage_mode": "mapped",
            "max_depth": 5,
            "error_action": "fail",
            "user_param": "should_pass",
        })

        prep_res = node.prep(shared)

        # Only non-reserved params should appear in child_params
        assert "user_param" in prep_res["child_params"]
        assert prep_res["child_params"]["user_param"] == "should_pass"
        assert "workflow_ir" not in prep_res["child_params"]
        assert "storage_mode" not in prep_res["child_params"]
        assert "max_depth" not in prep_res["child_params"]
        assert "error_action" not in prep_res["child_params"]

    def test_storage_modes(self):
        """Test mapped and shared storage isolation modes."""
        node = WorkflowExecutor()
        parent_shared = {"parent_data": "value", "_pflow_internal": "reserved"}

        prep_res = {
            "child_params": {"param": "value"},
            "current_depth": 0,
            "execution_stack": [],
            "workflow_path": "test.json",
        }

        # Test mapped mode — child gets only child_params (plus pflow internals)
        storage = node._create_child_storage(parent_shared, "mapped", prep_res)
        assert storage["param"] == "value"
        assert "parent_data" not in storage
        # Execution context is always injected
        assert storage["_pflow_depth"] == 1
        assert storage["_pflow_stack"] == ["test.json"]
        assert storage["_pflow_workflow_file"] == "test.json"

        # Test shared mode — child gets the exact same reference as parent
        storage = node._create_child_storage(parent_shared, "shared", prep_res)
        assert storage is parent_shared  # Same reference

        # Test invalid mode — should raise ValueError
        with pytest.raises(ValueError, match="Invalid storage_mode"):
            node._create_child_storage(parent_shared, "isolated", prep_res)


class TestExecErrorActionDetection:
    """Tests for exec() detecting error action strings from sub-workflow runs.

    When sub_flow.run() returns an "error" action string (not an exception),
    exec() must return {"success": False} instead of wrapping it as success.
    """

    def _make_prep_res(
        self,
        workflow_path: str = "child.pflow.md",
        child_params: dict | None = None,
        storage_mode: str = "mapped",
    ) -> dict:
        """Build a minimal prep_res dict for exec()."""
        return {
            "workflow_ir": {"nodes": [{"id": "step1", "type": "shell"}]},
            "workflow_path": workflow_path,
            "workflow_source": "ref:child.pflow.md",
            "child_params": child_params or {},
            "storage_mode": storage_mode,
            "current_depth": 0,
            "execution_stack": [],
            "parent_shared": {},
        }

    @patch("pflow.runtime.engine.WorkflowEngine")
    @patch("pflow.runtime.workflow_executor.compile_workflow")
    def test_exec_detects_error_action_from_sub_flow(self, mock_compile, MockEngine):
        """When engine.run() returns 'error', exec() should return success=False."""
        mock_compiled = MagicMock(resolved_defaults={})
        mock_compile.return_value = mock_compiled

        mock_engine = MagicMock()
        mock_engine.run.return_value = "error"
        MockEngine.return_value = mock_engine

        node = WorkflowExecutor()
        node.set_params({"workflow_ir": {"nodes": []}})

        prep_res = self._make_prep_res()
        result = node.exec(prep_res)

        assert result["success"] is False
        assert "error" in result
        assert "child.pflow.md" in result["error"]
        assert result["workflow_path"] == "child.pflow.md"
        assert "child_storage" in result

    @patch("pflow.runtime.engine.WorkflowEngine")
    @patch("pflow.runtime.workflow_executor.compile_workflow")
    def test_exec_extracts_error_from_child_storage(self, mock_compile, MockEngine):
        """When engine.run() returns 'error' and child_storage has execution tracking
        with a failed_node and namespaced error, the error message should include it."""
        mock_compiled = MagicMock(resolved_defaults={})
        mock_compile.return_value = mock_compiled

        # Set up an engine whose run() populates child_storage with error info, then returns "error"
        child_storage_state = {
            "__execution__": {"failed_node": "step1"},
            "step1": {"error": "Connection refused on port 8080"},
        }

        def fake_run(compiled, storage):
            storage.update(child_storage_state)
            return "error"

        mock_engine = MagicMock()
        mock_engine.run.side_effect = fake_run
        MockEngine.return_value = mock_engine

        node = WorkflowExecutor()
        node.set_params({"workflow_ir": {"nodes": []}})

        prep_res = self._make_prep_res()
        result = node.exec(prep_res)

        assert result["success"] is False
        assert "Connection refused on port 8080" in result["error"]
        assert "child.pflow.md" in result["error"]

    @patch("pflow.runtime.engine.WorkflowEngine")
    @patch("pflow.runtime.workflow_executor.compile_workflow")
    def test_exec_success_when_default_action(self, mock_compile, MockEngine):
        """When engine.run() returns 'default', exec() should return success=True."""
        mock_compiled = MagicMock(resolved_defaults={})
        mock_compile.return_value = mock_compiled

        mock_engine = MagicMock()
        mock_engine.run.return_value = "default"
        MockEngine.return_value = mock_engine

        node = WorkflowExecutor()
        node.set_params({"workflow_ir": {"nodes": []}})

        prep_res = self._make_prep_res()
        result = node.exec(prep_res)

        assert result["success"] is True
        assert result["result"] == "default"

    @patch("pflow.runtime.engine.WorkflowEngine")
    @patch("pflow.runtime.workflow_executor.compile_workflow")
    def test_exec_success_when_none_action(self, mock_compile, MockEngine):
        """When engine.run() returns None, exec() should return success=True."""
        mock_compiled = MagicMock(resolved_defaults={})
        mock_compile.return_value = mock_compiled

        mock_engine = MagicMock()
        mock_engine.run.return_value = None
        MockEngine.return_value = mock_engine

        node = WorkflowExecutor()
        node.set_params({"workflow_ir": {"nodes": []}})

        prep_res = self._make_prep_res()
        result = node.exec(prep_res)

        assert result["success"] is True
        assert result["result"] is None

    def test_extract_child_error_with_failed_node(self):
        """When __execution__['failed_node'] exists and has an error, include it in the message."""
        child_storage = {
            "__execution__": {"failed_node": "api_call"},
            "api_call": {"error": "HTTP 503 Service Unavailable"},
        }
        msg = WorkflowExecutor._extract_child_error(child_storage, "deploy.pflow.md")

        assert "HTTP 503 Service Unavailable" in msg
        assert "deploy.pflow.md" in msg

    def test_extract_child_error_without_failed_node(self):
        """When __execution__ has no failed_node, return generic fallback message."""
        child_storage: dict = {"__execution__": {}}
        msg = WorkflowExecutor._extract_child_error(child_storage, "deploy.pflow.md")

        assert "returned error action" in msg
        assert "deploy.pflow.md" in msg

    def test_extract_child_error_with_failed_node_no_error_key(self):
        """When failed_node exists but its data has no 'error' key, return fallback message."""
        child_storage = {
            "__execution__": {"failed_node": "step1"},
            "step1": {"stdout": "some output", "exit_code": 1},
        }
        msg = WorkflowExecutor._extract_child_error(child_storage, "build.pflow.md")

        assert "returned error action" in msg
        assert "build.pflow.md" in msg

    def test_extract_child_error_from_warnings(self):
        """When failed_node has no 'error' key but __warnings__ has an entry, use it."""
        child_storage = {
            "__execution__": {"failed_node": "router"},
            "router": {"result": "some_value"},
            "__warnings__": {"router": "Node 'router' returned action 'banana' but no successor edge matches."},
        }
        msg = WorkflowExecutor._extract_child_error(child_storage, "child.pflow.md")

        assert "banana" in msg
        assert "no successor edge matches" in msg
        assert "child.pflow.md" in msg
