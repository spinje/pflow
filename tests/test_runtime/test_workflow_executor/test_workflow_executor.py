"""Unit tests for WorkflowExecutor."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pflow.core.diagnostic import Severity
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
        """Missing workflow ref: prep() captures the failure into _prep_error
        marker so exec()/post() dispatch it through error_action (GH #284).
        """
        node = WorkflowExecutor()
        shared: dict = {}

        # No workflow reference — marker returned instead of raising
        node.set_params({})
        prep_res = node.prep(shared)
        assert "_prep_error" in prep_res
        assert "requires a 'workflow' parameter" in prep_res["_prep_error"]

    def test_circular_dependency_detection(self, tmp_path):
        """Test circular dependency detection."""
        from tests.shared.markdown_utils import write_workflow_file

        # Create a real workflow file so the resolver can load it
        workflow_file = tmp_path / "workflow1.pflow.md"
        write_workflow_file(
            {"nodes": [{"id": "step", "type": "shell", "params": {"command": "echo hi"}}], "edges": []},
            workflow_file,
        )

        node = WorkflowExecutor()

        # Set up circular reference — workflow1 is already in the stack
        shared = {"_pflow_stack": [str(workflow_file), "/path/to/workflow2.json"]}

        node.set_params({
            "workflow": str(workflow_file),  # Already in stack
        })

        # Cycle detection now routes through error_action (GH #284)
        prep_res = node.prep(shared)
        assert "_prep_error" in prep_res
        assert "Circular workflow reference" in prep_res["_prep_error"]

    def test_max_depth_enforcement(self, tmp_path):
        """Test maximum nesting depth."""
        from tests.shared.markdown_utils import write_workflow_file

        child_file = tmp_path / "max_depth_child.pflow.md"
        write_workflow_file(
            {"nodes": [{"id": "step", "type": "shell", "params": {"command": "echo hi"}}], "edges": []},
            child_file,
        )

        node = WorkflowExecutor()
        shared = {"_pflow_depth": 10}  # Already at max depth
        node.set_params({"workflow": str(child_file), "max_depth": 10})

        # Max depth routes through error_action (GH #284)
        prep_res = node.prep(shared)
        assert "_prep_error" in prep_res
        assert "Maximum workflow nesting depth" in prep_res["_prep_error"]

    def test_parameter_mapping(self, tmp_path):
        """Test that values in the ``inputs:`` dict are extracted as child inputs."""
        from tests.shared.markdown_utils import write_workflow_file

        child_file = tmp_path / "param_map_child.pflow.md"
        write_workflow_file(
            {
                "inputs": {
                    "data": {"type": "string"},
                    "key": {"type": "string"},
                    "static": {"type": "string"},
                },
                "nodes": [{"id": "step", "type": "shell", "params": {"command": "echo hi"}}],
                "edges": [],
            },
            child_file,
        )

        node = WorkflowExecutor()
        node.set_params({
            "workflow": str(child_file),
            "inputs": {
                "data": "test_value",
                "key": "secret",
                "static": "fixed_value",
            },
        })

        prep_res = node.prep({})

        assert prep_res["child_params"]["data"] == "test_value"
        assert prep_res["child_params"]["key"] == "secret"
        assert prep_res["child_params"]["static"] == "fixed_value"

    def test_reserved_params_excluded_from_child_inputs(self, tmp_path):
        """Test that reserved params are not passed to child as inputs."""
        from tests.shared.markdown_utils import write_workflow_file

        child_file = tmp_path / "reserved_excluded_child.pflow.md"
        write_workflow_file(
            {
                "inputs": {"user_param": {"type": "string"}},
                "nodes": [{"id": "step", "type": "shell", "params": {"command": "echo hi"}}],
                "edges": [],
            },
            child_file,
        )

        node = WorkflowExecutor()
        shared: dict = {}

        node.set_params({
            "workflow": str(child_file),
            "storage_mode": "mapped",
            "max_depth": 5,
            "error_action": "fail",
            "inputs": {"user_param": "should_pass"},
        })

        prep_res = node.prep(shared)

        # Only the value inside `inputs:` should appear in child_params
        assert "user_param" in prep_res["child_params"]
        assert prep_res["child_params"]["user_param"] == "should_pass"
        assert "workflow" not in prep_res["child_params"]
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

    def test_prep_preserves_child_parser_warnings_when_input_validation_fails(
        self,
        tmp_path: Path,
    ) -> None:
        """Child parser warnings should propagate even if prep fails before post()."""
        child_workflow = tmp_path / "child.pflow.md"
        child_workflow.write_text(
            "# Child\n\n"
            "## Input\n\n"
            "Typo section heading.\n\n"
            "## Inputs\n\n"
            "### required_value\n\n"
            "Required input.\n\n"
            "- type: string\n"
            "- required: true\n\n"
            "## Steps\n\n"
            "### run\n\n"
            "Use the input.\n\n"
            "- type: shell\n"
            "- cache: false\n"
            "- command: echo ${required_value}\n",
            encoding="utf-8",
        )

        node = WorkflowExecutor()
        node.set_params({"workflow": str(child_workflow)})
        shared: dict[str, object] = {"__parser_diagnostics__": []}

        # Input-shape error routes through error_action marker (GH #284).
        # Parser warnings must still propagate to shared even on the error path.
        prep_res = node.prep(shared)
        assert "_prep_error" in prep_res
        assert "missing required inputs" in prep_res["_prep_error"]

        parser_diagnostics = shared["__parser_diagnostics__"]
        assert isinstance(parser_diagnostics, list)
        assert len(parser_diagnostics) == 1
        diagnostic = parser_diagnostics[0]
        assert diagnostic.severity == Severity.WARNING
        assert diagnostic.source == "parser"
        assert "## Input" in diagnostic.message


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
            "child_ir": {"nodes": [{"id": "step1", "type": "shell"}]},
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
        node.set_params({"workflow": "dummy.pflow.md"})

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
        node.set_params({"workflow": "dummy.pflow.md"})

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
        node.set_params({"workflow": "dummy.pflow.md"})

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
        node.set_params({"workflow": "dummy.pflow.md"})

        prep_res = self._make_prep_res()
        result = node.exec(prep_res)

        assert result["success"] is True
        assert result["result"] is None

    def test_extract_child_error_with_failed_node(self):
        """When __execution__['failed_node'] exists and has an error, include it in the message."""
        from pflow.runtime.node_state import FAILURE_CATEGORY_EXCEPTION, mark_node_failed

        child_storage = {
            "__execution__": {"failed_node": "api_call"},
            "api_call": {"error": "HTTP 503 Service Unavailable"},
        }
        mark_node_failed(
            child_storage,
            "api_call",
            category=FAILURE_CATEGORY_EXCEPTION,
            error="HTTP 503 Service Unavailable",
        )
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
        from pflow.runtime.node_state import FAILURE_CATEGORY_EXCEPTION, mark_node_failed

        child_storage = {
            "__execution__": {"failed_node": "step1"},
            "step1": {"stdout": "some output", "exit_code": 1},
        }
        mark_node_failed(child_storage, "step1", category=FAILURE_CATEGORY_EXCEPTION)
        msg = WorkflowExecutor._extract_child_error(child_storage, "build.pflow.md")

        assert "returned error action" in msg
        assert "build.pflow.md" in msg

    def test_extract_child_error_from_warnings(self):
        """When failed_node has no 'error' key but __warnings__ has an entry, use it."""
        from pflow.runtime.node_state import FAILURE_CATEGORY_ROUTING, mark_node_failed

        child_storage = {
            "__execution__": {"failed_node": "router"},
            "router": {"result": "some_value"},
            "__warnings__": {"router": "Node 'router' returned action 'banana' but no successor edge matches."},
        }
        mark_node_failed(
            child_storage,
            "router",
            category=FAILURE_CATEGORY_ROUTING,
            warning="Node 'router' returned action 'banana' but no successor edge matches.",
        )
        msg = WorkflowExecutor._extract_child_error(child_storage, "child.pflow.md")

        assert "banana" in msg
        assert "no successor edge matches" in msg
        assert "child.pflow.md" in msg

    def test_extract_child_error_from_diagnostic_warning_uses_message(self):
        """Diagnostic-shaped child warnings render the human message, not a dataclass repr."""
        from pflow.core.diagnostic import Diagnostic, Severity
        from pflow.runtime.node_state import FAILURE_CATEGORY_ROUTING, mark_node_failed

        child_storage = {
            "__execution__": {"failed_node": "router"},
            "router": {"result": "some_value"},
            "__warnings__": {
                "router": Diagnostic(
                    severity=Severity.WARNING,
                    source="cache_analyzer",
                    id="cache.below-min-tokens",
                    message="router: declared cache did not fire",
                )
            },
        }
        mark_node_failed(child_storage, "router", category=FAILURE_CATEGORY_ROUTING)

        msg = WorkflowExecutor._extract_child_error(child_storage, "child.pflow.md")

        assert "router: declared cache did not fire" in msg
        assert "Diagnostic(" not in msg


class TestTemplateRefSubWorkflowValidation:
    """Pin the invariant that every IR reaching compile_workflow has been validated.

    Template-referenced children (``workflow: ${var}``) skip the parent's recursive
    validation because the resolver can't resolve the reference statically. Previously
    this meant child IRs with Python aliases (``type: str``) silently normalized via
    a defense-in-depth map. Now ``_compile_sub_workflow`` runs ``validate_ir`` itself,
    so the contract ``"Python aliases are hard errors"`` holds on every path.
    """

    def test_compile_rejects_python_alias_in_child_ir(self):
        """A child IR declaring ``type: str`` must fail at the validation step.

        ``_compile_sub_workflow`` wraps the underlying ``SchemaValidationError``
        in ``CompilationError`` so parent-side error handling is consistent
        regardless of whether the failure is structural, schematic, or
        compiler-internal.
        """
        from pflow.core.exceptions import CompilationError

        node = WorkflowExecutor()
        node.set_params({})

        child_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "step", "type": "shell", "params": {"command": "echo hi"}}],
            "inputs": {"x": {"type": "str", "required": True}},
        }

        with pytest.raises(CompilationError) as exc_info:
            node._compile_sub_workflow(child_ir, "<inline>", {"x": "hello"})

        assert "Use 'string' instead of 'str'" in str(exc_info.value)

    def test_compile_accepts_canonical_type_in_child_ir(self):
        """A child IR declaring ``type: string`` compiles successfully."""
        node = WorkflowExecutor()
        node.set_params({})

        child_ir = {
            "ir_version": "0.1.0",
            "nodes": [{"id": "step", "type": "shell", "params": {"command": "echo hi"}}],
            "inputs": {"x": {"type": "string", "required": True}},
        }

        compiled = node._compile_sub_workflow(child_ir, "<inline>", {"x": "hello"})
        assert compiled is not None

    def test_template_ref_bypass_close_end_to_end_through_runner(self, tmp_path):
        """End-to-end: parent with ``workflow: ${child_ref}`` pointing to a child
        with a Python alias must fail with the canonical suggestion.

        The direct ``_compile_sub_workflow`` tests above prove the function
        validates. This test proves the full dispatch chain — parent validator
        skips template refs → runtime resolver loads child → compile path
        routes through ``_compile_sub_workflow`` → ``normalize_ir`` +
        ``validate_ir`` reject → ``CompilationError`` propagates.

        Two regressions this catches that the unit tests miss:
        1. Runtime refactor that bypasses ``_compile_sub_workflow`` (unit
           tests still pass; real pipeline breaks).
        2. Removal of ``normalize_ir(workflow_ir)`` call (unit tests use IRs
           that include ``ir_version`` explicitly; parsed-markdown children
           don't — the markdown parser does not inject it).
        """
        from pflow.execution.result import RunnerConfig
        from pflow.execution.runner import WorkflowRunner
        from tests.shared.markdown_utils import write_workflow_file

        child_path = tmp_path / "child.pflow.md"
        write_workflow_file(
            {
                "nodes": [{"id": "echo", "type": "shell", "params": {"command": "echo ${message}"}}],
                "inputs": {"message": {"type": "str", "required": True}},
                "outputs": {"out": {"source": "${echo.stdout}"}},
            },
            child_path,
        )

        parent_ir = {
            "nodes": [
                {
                    "id": "call_child",
                    "type": "workflow",
                    "params": {
                        "workflow": "${child_path}",
                        "inputs": {"message": "hello"},
                    },
                }
            ],
            "inputs": {"child_path": {"type": "string", "required": True}},
        }

        result = WorkflowRunner().run(
            parent_ir,
            {"child_path": str(child_path)},
            RunnerConfig(),
        )

        assert result.success is False

        # Structured context from SchemaValidationError must survive the
        # CompilationError wrap (wrapped_diagnostics carries the rich fields),
        # and sub_workflow_path must be merged in by CompilationError.to_diagnostics.
        # Without this, a prior regression flattened the structured context into the
        # exception's string message — passing a substring assertion while losing
        # the "Did you mean / Available types" rendering blocks agents rely on.
        vocab_diag = next(
            (d for d in result.diagnostics if d.context.get("path") == "inputs.message.type"),
            None,
        )
        assert vocab_diag is not None, (
            "expected a diagnostic for the child IR's inputs.message.type vocab error; "
            f"got: {[d.context for d in result.diagnostics]}"
        )
        # Rich "Available types" rendering block survives.
        assert vocab_diag.context["available_fields"] == [
            "string",
            "number",
            "integer",
            "boolean",
            "array",
            "object",
            "any",
        ]
        assert vocab_diag.context["available_fields_label"] == "types"
        # Container context (sub_workflow_path) is merged in by CompilationError.to_diagnostics.
        assert vocab_diag.context["sub_workflow_path"] == str(child_path)
        # Opinionated canonical fix survives as a structured suggestion,
        # not a flattened substring in .message.
        assert vocab_diag.suggestions == ["Use 'string' instead of 'str'"]
