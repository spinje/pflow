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
from pflow.runtime import compile_workflow
from pflow.runtime.compilation.compiler import CompilationError
from pflow.runtime.engine import WorkflowEngine
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

    @pytest.fixture
    def mock_registry(self, tmp_path):
        """Registry with test node and workflow executor for integration tests."""
        registry_path = tmp_path / "test_registry.json"
        registry = Registry(registry_path)
        registry_data = {
            "pflow.nodes.test_node": {
                "module": "pflow.nodes.test_node",
                "class_name": "ExampleNode",
                "docstring": "Test node for testing",
                "file_path": "/mock/path/test_node.py",
                "interface": {
                    "inputs": [],
                    "outputs": [{"key": "test_output", "type": "string"}],
                    "parameters": [],
                },
            },
            "pflow.runtime.workflow_executor": {
                "module": "pflow.runtime.workflow_executor",
                "class_name": "WorkflowExecutor",
                "docstring": "Runtime executor for nested workflow execution",
                "file_path": "/mock/path/workflow_executor.py",
                "interface": {
                    "inputs": [],
                    "outputs": [],
                    "parameters": [
                        {"key": "workflow", "type": "string", "required": False},
                        {"key": "workflow_ir", "type": "dict", "required": False},
                        {"key": "storage_mode", "type": "string", "required": False},
                        {"key": "max_depth", "type": "integer", "required": False},
                        {"key": "error_action", "type": "string", "required": False},
                    ],
                },
            },
        }
        registry.save(registry_data)
        return registry

    def _setup_mock_imports(self, mock_test_node_class=None):
        """Setup mock imports for integration tests (mirrors test_integration.py)."""
        if mock_test_node_class is None:

            class MockExampleNode(BaseNode):
                def prep(self, shared):
                    return shared.get("test_input", "no input")

                def exec(self, prep_res):
                    return f"Processed: {prep_res}"

                def post(self, shared, prep_res, exec_res):
                    shared["test_output"] = exec_res
                    return "default"

            mock_test_node_class = MockExampleNode

        mock_module = Mock()
        mock_module.ExampleNode = mock_test_node_class
        mock_module.WorkflowExecutor = WorkflowExecutor

        def side_effect(module_path):
            if module_path == "pflow.nodes.test_node":
                return mock_module
            elif module_path == "pflow.runtime.workflow_executor":
                import pflow.runtime.workflow_executor

                return pflow.runtime.workflow_executor
            else:
                return mock_module

        return patch("importlib.import_module", side_effect=side_effect)

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

    # --- Test 9: template resolution via compiled pipeline ---

    def test_template_resolution(self, mock_registry):
        """Template params are resolved by the wrapper chain before child receives them."""
        child_workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "pflow.nodes.test_node", "params": {}}],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": child_workflow_ir,
                        "simple": "${value}",
                        "nested": "${obj.field}",
                        "static": "literal",
                    },
                }
            ],
            "edges": [],
        }

        child_snapshot: dict = {}

        class CaptureNode(BaseNode):
            def prep(self, shared):
                nonlocal child_snapshot
                child_snapshot = {
                    k: v for k, v in shared.items() if not k.startswith("_pflow_") and not k.startswith("__")
                }
                return None

            def exec(self, prep_res):
                return None

            def post(self, shared, prep_res, exec_res):
                return "default"

        with self._setup_mock_imports(CaptureNode):
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["value"] = "resolved"
            shared["obj"] = {"field": "nested_value"}
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            engine.run(workflow, shared)

        assert child_snapshot["simple"] == "resolved"
        assert child_snapshot["nested"] == "nested_value"
        assert child_snapshot["static"] == "literal"

    # --- Test 9b: template resolution in dict/list child inputs via compiled pipeline ---

    def test_template_resolution_dict_and_list_inputs(self, mock_registry):
        """Dict/list params with nested templates are resolved by wrapper chain."""
        child_workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "pflow.nodes.test_node", "params": {}}],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": child_workflow_ir,
                        "config": {"endpoint": "${api.url}", "retries": 3},
                        "tags": ["${category}", "static-tag"],
                        "nested": {"items": [{"name": "${user.name}"}]},
                    },
                }
            ],
            "edges": [],
        }

        child_snapshot: dict = {}

        class CaptureNode(BaseNode):
            def prep(self, shared):
                nonlocal child_snapshot
                child_snapshot = {
                    k: v for k, v in shared.items() if not k.startswith("_pflow_") and not k.startswith("__")
                }
                return None

            def exec(self, prep_res):
                return None

            def post(self, shared, prep_res, exec_res):
                return "default"

        with self._setup_mock_imports(CaptureNode):
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["api"] = {"url": "https://example.com"}
            shared["category"] = "production"
            shared["user"] = {"name": "Alice"}
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            engine.run(workflow, shared)

        assert child_snapshot["config"] == {"endpoint": "https://example.com", "retries": 3}
        assert child_snapshot["tags"] == ["production", "static-tag"]
        assert child_snapshot["nested"] == {"items": [{"name": "Alice"}]}

    # --- Test 9c: no template injection from upstream output ---

    def test_no_template_injection_from_upstream_output(self, mock_registry):
        """Upstream output containing literal ${...} must NOT be re-resolved.

        Regression test for the _resolve_child_inputs removal. The old double-
        resolution would attempt to resolve ${SECRET} from the shared store,
        leaking parent data into the child. The wrapper resolves ${producer.data}
        once (getting the literal string), and WorkflowExecutor passes it through
        without a second resolution pass.
        """
        child_workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "pflow.nodes.test_node", "params": {}}],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "producer",
                    "type": "pflow.nodes.test_node",
                    "params": {},
                },
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": child_workflow_ir,
                        "payload": "${producer.data}",
                    },
                },
            ],
            "edges": [{"from": "producer", "to": "sub"}],
        }

        child_snapshot: dict = {}

        class ProducerNode(BaseNode):
            """Produces output containing a literal ${...} string."""

            def prep(self, shared):
                return None

            def exec(self, prep_res):
                return None

            def post(self, shared, prep_res, exec_res):
                # Output contains a literal template-like string
                shared["data"] = "config: ${SECRET}/path"
                return "default"

        class CaptureNode(BaseNode):
            def prep(self, shared):
                nonlocal child_snapshot
                child_snapshot = {
                    k: v for k, v in shared.items() if not k.startswith("_pflow_") and not k.startswith("__")
                }
                return None

            def exec(self, prep_res):
                return None

            def post(self, shared, prep_res, exec_res):
                return "default"

        # The shared store has a "SECRET" key — if double-resolution occurred,
        # ${SECRET} would resolve to "leaked" instead of staying literal.
        mock_module = Mock()
        mock_module.WorkflowExecutor = WorkflowExecutor

        call_count = {"n": 0}

        def side_effect(module_path):
            if module_path == "pflow.runtime.workflow_executor":
                import pflow.runtime.workflow_executor

                return pflow.runtime.workflow_executor
            # First import is for "producer" node, second for "test" node inside child
            mock = Mock()
            if call_count["n"] == 0:
                mock.ExampleNode = ProducerNode
                call_count["n"] += 1
            else:
                mock.ExampleNode = CaptureNode
            return mock

        with patch("importlib.import_module", side_effect=side_effect):
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["SECRET"] = "leaked"  # noqa: S105 — intentional test value for injection check
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()
            engine.run(workflow, shared)

        # The child must see the LITERAL string, not the resolved "leaked" value
        assert child_snapshot["payload"] == "config: ${SECRET}/path"
        assert "leaked" not in child_snapshot.get("payload", "")

    # --- Test 10: storage_mode "mapped" ---

    def test_storage_mode_mapped(self, simple_workflow_ir):
        """Test mapped storage mode: child sees only mapped params."""
        node = WorkflowExecutor()
        node.set_params({
            "workflow_ir": simple_workflow_ir,
            "allowed": "mapped_value",
            "storage_mode": "mapped",
        })

        parent_shared = {"other": "should_not_see"}

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
        with patch("pflow.runtime.workflow_executor.compile_workflow") as mock_compile:
            mock_compile.side_effect = CompilationError("Compilation failed", phase="test")
            with pytest.raises(CompilationError, match="Compilation failed"):
                node.exec(prep_res)

        # Other exceptions are wrapped in CompilationError
        with patch("pflow.runtime.workflow_executor.compile_workflow") as mock_compile:
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

    # --- Test 20: unresolved template raises in production pipeline ---

    def test_unresolved_template_in_input(self, mock_registry):
        """In production, the engine raises ValueError for unresolved templates."""
        child_workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "test", "type": "pflow.nodes.test_node", "params": {}}],
            "edges": [],
        }

        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "sub",
                    "type": "pflow.runtime.workflow_executor",
                    "params": {
                        "workflow_ir": child_workflow_ir,
                        "exists": "${present}",
                        "missing": "${not_there}",
                    },
                }
            ],
            "edges": [],
        }

        with self._setup_mock_imports():
            workflow = compile_workflow(parent_ir, registry=mock_registry)
            shared = dict(workflow.resolved_defaults)
            shared["present"] = "value"
            shared["__registry__"] = mock_registry
            engine = WorkflowEngine()

            with pytest.raises(ValueError, match="not_there"):
                engine.run(workflow, shared)

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
        """_pflow_workflow_file in params flows to shared store via Runner."""
        from pflow.execution.result import RunnerConfig
        from pflow.execution.runner import WorkflowRunner

        workflow_ir = {
            "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo hi"}}],
            "edges": [],
        }
        params = {"_pflow_workflow_file": "/path/to/workflow.pflow.md"}

        result = WorkflowRunner().run(workflow_ir, params, RunnerConfig())

        assert result.shared_after["_pflow_workflow_file"] == "/path/to/workflow.pflow.md"

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

        The 'inputs' param is consumed by the engine's template resolution to inject
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
    in execute_batch / _execute_batch_item ensures CompilationError is always
    re-raised (never retried, never swallowed).

    Tests use execute_batch() from pflow.runtime.engine.batch_executor directly,
    with a mock execute_single_fn callback that raises CompilationError. This
    validates the batch executor's error propagation without needing the full
    wrapper chain (removed in the engine redesign).
    """

    @pytest.fixture
    def batch_node_and_config(self):
        """Create a bare node and NodeConfig with batch config for testing.

        Returns a factory function that accepts error_handling, parallel, and
        max_retries to customize the batch config.
        """
        from pflow.runtime.engine.types import BatchConfig, NodeConfig

        def _make(
            error_handling: str = "continue",
            parallel: bool = False,
            max_retries: int = 1,
        ) -> tuple:
            node = BaseNode()
            node.node_id = "fetch-sources"

            config = NodeConfig(
                node_id="fetch-sources",
                node_type_name="WorkflowExecutor",
                template_config=None,
                batch_config=BatchConfig(
                    items_template="${sources}",
                    item_alias="item",
                    error_handling=error_handling,
                    parallel=parallel,
                    max_retries=max_retries,
                    retry_wait=0.0,
                ),
                namespaced=True,
                interface_metadata=None,
            )

            shared: dict = {"sources": ["item_a", "item_b", "item_c"]}
            return node, config, shared

        return _make

    def test_compilation_error_propagates_through_sequential_batch_with_continue(self, batch_node_and_config):
        """When execute_single_fn raises CompilationError, sequential batch must propagate it
        even with error_handling: continue. Compilation errors mean the workflow definition
        is broken — data-level error handling must not swallow them."""
        from pflow.runtime.engine.batch_executor import execute_batch

        node, config, shared = batch_node_and_config(error_handling="continue", parallel=False)

        def raise_compilation_error(n, c, item_shared):
            raise CompilationError("Unknown node type 'fetch-rss'", phase="node_loading")

        with pytest.raises(CompilationError, match="Unknown node type"):
            execute_batch(node, config, shared, raise_compilation_error)

    def test_compilation_error_propagates_through_sequential_batch_with_fail_fast(self, batch_node_and_config):
        """CompilationError propagates with fail_fast too (sanity check)."""
        from pflow.runtime.engine.batch_executor import execute_batch

        node, config, shared = batch_node_and_config(error_handling="fail_fast", parallel=False)

        def raise_compilation_error(n, c, item_shared):
            raise CompilationError("Missing required node", phase="validation")

        with pytest.raises(CompilationError, match="Missing required node"):
            execute_batch(node, config, shared, raise_compilation_error)

    def test_wrapped_compilation_error_propagates_through_batch(self, batch_node_and_config):
        """When a generic exception is wrapped in CompilationError (as WorkflowExecutor does
        for non-CompilationError failures during compile), the wrapped error must also
        propagate through batch — it's still a CompilationError."""
        from pflow.runtime.engine.batch_executor import execute_batch

        node, config, shared = batch_node_and_config(error_handling="continue", parallel=False)

        def raise_wrapped_compilation_error(n, c, item_shared):
            # Simulates WorkflowExecutor._compile_sub_workflow wrapping a ValueError
            try:
                raise ValueError("Bad IR structure")
            except ValueError as e:
                raise CompilationError(
                    "Failed to compile sub-workflow: Bad IR structure",
                    phase="sub_workflow_compilation",
                ) from e

        with pytest.raises(CompilationError, match="Failed to compile sub-workflow"):
            execute_batch(node, config, shared, raise_wrapped_compilation_error)

    def test_compilation_error_propagates_through_parallel_batch_with_continue(self, batch_node_and_config):
        """When execute_single_fn raises CompilationError, parallel batch must propagate it
        even with error_handling: continue. The error escapes the thread via future.result()
        and is re-raised by _collect_parallel_results."""
        from pflow.runtime.engine.batch_executor import execute_batch

        node, config, shared = batch_node_and_config(error_handling="continue", parallel=True)

        def raise_compilation_error(n, c, item_shared):
            raise CompilationError("Unknown node type 'fetch-rss'", phase="node_loading")

        with pytest.raises(CompilationError, match="Unknown node type"):
            execute_batch(node, config, shared, raise_compilation_error)

    def test_compilation_error_propagates_through_single_batch_item(self, batch_node_and_config):
        """Test _execute_batch_item directly: CompilationError is raised, not returned
        as an error tuple."""
        from pflow.runtime.engine.batch_executor import _execute_batch_item

        node, config, shared = batch_node_and_config(error_handling="continue", parallel=False)

        def raise_compilation_error(n, c, item_shared):
            raise CompilationError("Node type not found", phase="node_loading")

        with pytest.raises(CompilationError, match="Node type not found"):
            _execute_batch_item(
                idx=0,
                item="item_a",
                node=node,
                config=config,
                parent_shared=shared,
                execute_single_fn=raise_compilation_error,
                batch_config=config.batch_config,
            )

    def test_compilation_error_not_retried(self, batch_node_and_config):
        """CompilationError must not trigger retry logic — retrying a broken workflow
        definition would just fail again."""
        from pflow.runtime.engine.batch_executor import _execute_batch_item

        node, config, shared = batch_node_and_config(error_handling="continue", parallel=False, max_retries=3)

        call_count = 0

        def raise_compilation_error(n, c, item_shared):
            nonlocal call_count
            call_count += 1
            raise CompilationError("Broken workflow", phase="test")

        with pytest.raises(CompilationError):
            _execute_batch_item(
                idx=0,
                item="item_a",
                node=node,
                config=config,
                parent_shared=shared,
                execute_single_fn=raise_compilation_error,
                batch_config=config.batch_config,
            )

        # CompilationError should cause immediate raise — callback called only once
        assert call_count == 1
