"""Unit tests for WorkflowEngine behaviors not covered by integration tests.

These test specific engine behaviors that are hard to trigger or verify
through the full compilation pipeline, and where a silent regression
would leave users with no diagnostic information.

Covers: unmatched action warnings, --only + output resolution, custom error_action.
"""

from pflow.core.node import BaseNode
from pflow.runtime.engine.engine import WorkflowEngine
from pflow.runtime.engine.types import CompiledWorkflow, NodeConfig


class _ActionNode(BaseNode):
    """Test node that returns a configurable action from post()."""

    def post(self, shared, prep_res, exec_res):
        return self.params.get("action", "default")


class TestUnmatchedActionWarning:
    """When a node returns an action that doesn't match any successor edge,
    the engine should write a warning to __warnings__ and stop traversal.

    Without this, workflows with mismatched action/edge names silently
    stop with no explanation — the most confusing failure mode possible.
    """

    def test_unmatched_action_writes_warning(self):
        """Node returns 'success' but only has a 'default' edge → warning."""
        node_a = _ActionNode()
        node_a.node_id = "router"
        node_a.set_params({"action": "success"})

        node_b = _ActionNode()
        node_b.node_id = "target"

        # Wire: router -default-> target (but router returns "success", not "default")
        node_a >> node_b

        configs = {
            "router": NodeConfig(
                node_id="router",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
            "target": NodeConfig(
                node_id="target",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
        }

        workflow = CompiledWorkflow(start_node=node_a, node_configs=configs)
        shared: dict = {}
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # Engine should have written a warning
        assert "__warnings__" in shared
        assert "router" in shared["__warnings__"]
        assert "success" in shared["__warnings__"]["router"]
        assert "default" in shared["__warnings__"]["router"]

        # Target should NOT have executed
        assert "target" not in shared.get("__execution__", {}).get("node_actions", {})

    def test_matching_action_follows_edge(self):
        """Node returns 'default' with a 'default' edge → no warning, target runs."""
        node_a = _ActionNode()
        node_a.node_id = "first"
        node_a.set_params({"action": "default"})

        node_b = _ActionNode()
        node_b.node_id = "second"
        node_b.set_params({"action": "default"})

        node_a >> node_b

        configs = {
            "first": NodeConfig(
                node_id="first",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
            "second": NodeConfig(
                node_id="second",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
        }

        workflow = CompiledWorkflow(start_node=node_a, node_configs=configs)
        shared: dict = {}
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # No warnings
        assert "__warnings__" not in shared or "first" not in shared.get("__warnings__", {})

        # Both nodes should have executed
        actions = shared["__execution__"]["node_actions"]
        assert "first" in actions
        assert "second" in actions


class TestOnlyNodeWithOutputs:
    """When --only is set, output resolution must be skipped even if
    the workflow declares outputs. Without this gate, OutputResolutionError
    would fire for outputs depending on nodes that were skipped.
    """

    def test_only_node_skips_output_resolution(self):
        """--only with declared outputs does NOT attempt to resolve them."""
        node_a = _ActionNode()
        node_a.node_id = "first"
        node_a.set_params({"action": "default"})

        node_b = _ActionNode()
        node_b.node_id = "second"
        node_b.set_params({"action": "default"})

        node_a >> node_b

        configs = {
            "first": NodeConfig(
                node_id="first",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
            "second": NodeConfig(
                node_id="second",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
        }

        workflow = CompiledWorkflow(
            start_node=node_a,
            node_configs=configs,
            # Declare output from second node — which won't execute with --only=first
            outputs={"result": {"source": "${second.action}"}},
        )

        shared: dict = {}
        engine = WorkflowEngine(only_node="first")
        # This should NOT raise OutputResolutionError
        result = engine.run(workflow, shared)

        assert result == "default"
        assert shared["__execution__"]["only_node"] == "first"
        # "result" output should NOT be in shared (resolution was skipped)
        assert "result" not in shared


class TestCustomErrorAction:
    """When a node returns a custom error action (e.g., 'error_child' instead of
    'error'), all bookkeeping must treat it as a failure consistently.

    The engine uses startswith("error") everywhere. Before this was fixed,
    some sites used == "error" which would miss custom error actions — the
    workflow would be marked failed but the node would appear successful in
    trace, cache, and progress output.
    """

    def test_custom_error_action_marks_node_as_failed(self):
        """Node returning 'error_child' sets failed_node and is NOT cached as completed."""
        node = _ActionNode()
        node.node_id = "failing"
        node.set_params({"action": "error_child"})

        configs = {
            "failing": NodeConfig(
                node_id="failing",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
        }

        workflow = CompiledWorkflow(start_node=node, node_configs=configs)
        shared: dict = {}
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

        # Workflow should report failure (startswith("error"))
        assert result.startswith("error"), f"Expected error result, got: {result}"

        # Node must be recorded as failed, not completed
        execution = shared["__execution__"]
        assert execution["failed_node"] == "failing", (
            f"Expected failed_node='failing', got: {execution.get('failed_node')}"
        )
        assert "failing" not in execution["completed_nodes"], "Custom error action should NOT record node as completed"

    def test_exact_error_also_works(self):
        """Sanity check: the standard 'error' action still works correctly."""
        node = _ActionNode()
        node.node_id = "failing"
        node.set_params({"action": "error"})

        configs = {
            "failing": NodeConfig(
                node_id="failing",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
        }

        workflow = CompiledWorkflow(start_node=node, node_configs=configs)
        shared: dict = {}
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

        assert result == "error"
        assert shared["__execution__"]["failed_node"] == "failing"
        assert "failing" not in shared["__execution__"]["completed_nodes"]
