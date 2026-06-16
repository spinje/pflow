"""Unit tests for WorkflowEngine behaviors not covered by integration tests.

These test specific engine behaviors that are hard to trigger or verify
through the full compilation pipeline, and where a silent regression
would leave users with no diagnostic information.

Covers: unmatched action warnings, --only + output resolution, custom error_action,
batch template error propagation.
"""

from pflow.core.diagnostic import normalize_runtime_warning
from pflow.core.node import BaseNode
from pflow.runtime.engine.engine import WorkflowEngine
from pflow.runtime.engine.types import BatchConfig, CompiledWorkflow, NodeConfig, TemplateConfig


class _ActionNode(BaseNode):
    """Test node that returns a configurable action from post()."""

    def post(self, shared, prep_res, exec_res):
        return self.params.get("action", "default")


class _OutputNode(BaseNode):
    """Test node that writes a value to shared and returns a configurable action."""

    def post(self, shared, prep_res, exec_res):
        shared["result"] = self.params.get("output_value", "hello")
        return self.params.get("action", "default")


class _FlakyLoopNode(BaseNode):
    """Fails on first visit, succeeds on second, writing namespaced output."""

    def post(self, shared, prep_res, exec_res):
        visits = shared["__execution__"]["node_visit_counts"].get(self.node_id, 0)
        if visits == 1:
            shared["command"] = "flaky command"
            shared["exit_code"] = 1
            shared["error"] = "first attempt failed"
            return "error"

        shared["stdout"] = "recovered"
        return "default"


class _CaptureNode(BaseNode):
    """Captures an upstream value into its own namespace for assertions."""

    def prep(self, shared):
        return shared["flaky"]["stdout"]

    def post(self, shared, prep_res, exec_res):
        shared["seen"] = prep_res
        return "default"


class _McpApiWarningNode(BaseNode):
    """Writes a canonical MCP result payload that self-reports API failure."""

    def post(self, shared, prep_res, exec_res):
        shared["result"] = {"status": "error", "error": "expired auth"}
        return "default"


class _McpProtocolErrorNode(BaseNode):
    """Mimics MCPNode.post() after exec_fallback reported a transport failure."""

    def post(self, shared, prep_res, exec_res):
        shared["error"] = self.params.get("error_message", "MCP tool failed: connection refused")
        shared["error_details"] = {
            "server": "notebooklm",
            "tool": "studio_create",
            "timeout": False,
        }
        return "error"


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

    def test_unmatched_action_archives_routing_failure(self):
        """Routing failures must roll back completion bookkeeping and archive to __failures__."""
        from pflow.runtime.node_state import get_node_failure

        node_a = _ActionNode()
        node_a.node_id = "router"
        node_a.set_params({"action": "success"})

        node_b = _ActionNode()
        node_b.node_id = "target"

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
        result = engine.run(workflow, shared)

        assert result == "error"
        assert "router" not in shared["__execution__"]["completed_nodes"]
        assert "router" not in shared["__execution__"]["node_actions"]
        failure = get_node_failure(shared, "router")
        assert failure is not None
        assert failure["category"] == "routing_error"
        assert "router" in shared["__warnings__"]

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
    """Under snapshot --only (issue #443) the engine seeds every non-target node
    from the prior full run, then runs only the target. Output resolution
    populates declared outputs whose source resolves — the target's OWN output OR
    a RESTORED node — and silently skips sources absent from the snapshot (branch
    divergence) rather than raising OutputResolutionError. This is critical for
    -o and batch sub-workflow results.
    """

    @staticmethod
    def _snapshot(node_id: str, output: dict) -> list[dict]:
        """One synthetic full-run trace event — enough to seed shared[node_id]."""
        return [{"node_id": node_id, "node_output": output}]

    def test_only_node_populates_resolvable_outputs(self):
        """--only populates a declared output sourced from the target's own output."""
        node_a = _OutputNode()
        node_a.node_id = "first"
        node_a.set_params({"action": "default", "output_value": "hello"})

        node_b = _ActionNode()
        node_b.node_id = "second"
        node_b.set_params({"action": "default"})

        node_a >> node_b

        configs = {
            "first": NodeConfig(
                node_id="first",
                node_type_name="OutputNode",
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
            # Output from the TARGET node — resolvable from its own fresh output.
            outputs={"output": {"source": "${first.result}"}},
        )

        shared: dict = {}
        engine = WorkflowEngine(
            only_node="first",
            snapshot_events=self._snapshot("second", {"action": "default"}),
        )
        result = engine.run(workflow, shared)

        assert result == "default"
        assert shared["__execution__"]["only_node"] == "first"
        # Output SHOULD be populated — source resolves from the target node
        assert shared["output"] == "hello"
        # 'second' was restored from the snapshot, not executed this run.
        assert shared["__execution__"]["restored_nodes"] == ["second"]

    def test_only_node_populates_restored_upstream_output(self):
        """--only resolves a declared output sourced from a RESTORED upstream node.

        Snapshot semantics: the target runs against frozen upstream, so an output
        referencing that upstream resolves from the seeded value. (Under the old
        re-walk-and-stop behavior this resolved only because upstream re-ran —
        and re-fired its side effects, the #443 bug.)
        """
        node_a = _ActionNode()
        node_a.node_id = "first"
        node_a.set_params({"action": "default"})

        node_b = _ActionNode()
        node_b.node_id = "second"  # target
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
            outputs={"upstream": {"source": "${first.value}"}},
        )

        shared: dict = {}
        engine = WorkflowEngine(
            only_node="second",
            snapshot_events=self._snapshot("first", {"value": "frozen-upstream"}),
        )
        result = engine.run(workflow, shared)

        assert result == "default"
        # Output resolves from the RESTORED upstream node, never re-executed.
        assert shared["upstream"] == "frozen-upstream"
        assert shared["__execution__"]["restored_nodes"] == ["first"]

    def test_only_node_skips_unresolvable_output(self):
        """--only silently skips a declared output whose source is absent from the snapshot."""
        node_a = _ActionNode()
        node_a.node_id = "first"  # target
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
            # 'second' is downstream of the target AND absent from the snapshot
            # below (branch divergence) — so its source can't resolve.
            outputs={"result": {"source": "${second.action}"}},
        )

        shared: dict = {}
        engine = WorkflowEngine(
            only_node="first",
            # Snapshot restores an unrelated node, NOT 'second'.
            snapshot_events=self._snapshot("other", {"x": 1}),
        )
        # This should NOT raise OutputResolutionError.
        result = engine.run(workflow, shared)

        assert result == "default"
        assert shared["__execution__"]["only_node"] == "first"
        # "result" output should NOT be in shared (source 'second' absent from snapshot)
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
        assert "failing" in shared.get("__failures__", {})

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
        assert "failing" in shared.get("__failures__", {})


class TestLoopReentryFailureRecovery:
    """A node that fails then succeeds on loop re-entry must end in succeeded state."""

    def test_failed_then_succeeded_reentry_clears_failure_record(self):
        from pflow.runtime.node_state import get_node_failure

        flaky = _FlakyLoopNode()
        flaky.node_id = "flaky"
        sink = _CaptureNode()
        sink.node_id = "sink"

        flaky >> sink
        flaky - "error" >> flaky

        configs = {
            "flaky": NodeConfig(
                node_id="flaky",
                node_type_name="FlakyLoopNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
            "sink": NodeConfig(
                node_id="sink",
                node_type_name="CaptureNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
        }

        workflow = CompiledWorkflow(start_node=flaky, node_configs=configs)
        shared: dict = {}
        engine = WorkflowEngine()
        result = engine.run(workflow, shared)

        assert result == "default"
        assert get_node_failure(shared, "flaky") is None
        assert shared["flaky"]["stdout"] == "recovered"
        assert shared["sink"]["seen"] == "recovered"
        assert "flaky" in shared["__execution__"]["completed_nodes"]


class TestApiWarningRecovery:
    """API warnings with on-error successors should be marked recovered."""

    def test_mcp_result_api_warning_with_error_successor_marks_warning_recovered(self):
        api = _McpApiWarningNode()
        api.node_id = "api"
        recover = _OutputNode()
        recover.node_id = "recover"
        recover.set_params({"output_value": "handled"})

        api - "error" >> recover

        configs = {
            "api": NodeConfig(
                node_id="api",
                node_type_name="MCPNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
            "recover": NodeConfig(
                node_id="recover",
                node_type_name="OutputNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
        }

        workflow = CompiledWorkflow(start_node=api, node_configs=configs)
        shared: dict = {}
        result = WorkflowEngine().run(workflow, shared)

        assert result == "default"
        assert shared["recover"]["result"] == "handled"
        message, context = normalize_runtime_warning(shared["__warnings__"]["api"])
        assert message == "API error: expired auth"
        assert context["type"] == "api_warning"
        assert context["recovered"] is True


class TestMcpProtocolErrorRouting:
    """MCP protocol/transport errors should fail at the MCP node."""

    def test_unhandled_mcp_protocol_error_stops_before_default_successor(self):
        from pflow.runtime.node_state import get_node_failure

        api = _McpProtocolErrorNode()
        api.node_id = "create_audio"
        downstream = _OutputNode()
        downstream.node_id = "poll"
        downstream.set_params({"output_value": "should not run"})

        api >> downstream

        configs = {
            "create_audio": NodeConfig(
                node_id="create_audio",
                node_type_name="MCPNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
            "poll": NodeConfig(
                node_id="poll",
                node_type_name="OutputNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
        }

        workflow = CompiledWorkflow(start_node=api, node_configs=configs)
        shared: dict = {}
        result = WorkflowEngine().run(workflow, shared)

        assert result == "error"
        assert "poll" not in shared

        failure = get_node_failure(shared, "create_audio")
        assert failure is not None
        # An MCP error action always archives as mcp_failure — the detector defers to
        # the node's verdict, so the category no longer depends on the error wording.
        assert failure["category"] == "mcp_failure"
        assert failure["error"] == "MCP tool failed: connection refused"
        assert failure["data"]["error"] == "MCP tool failed: connection refused"
        assert failure["data"]["error_details"] == {
            "server": "notebooklm",
            "tool": "studio_create",
            "timeout": False,
        }

    def test_mcp_protocol_resource_message_routes_as_plain_failure(self):
        """An MCP error action is the node's deliberate verdict — the detector defers.

        Pre-fix, a "repository not found" error text was hijacked by the api_warning
        detector into an ``api_warning`` failure (while "connection refused" stayed
        ``mcp_failure``). After action-gating the detector (GH #474), BOTH route as a
        plain ``mcp_failure`` — the failure category no longer depends on whether the
        error wording happens to match a resource pattern.
        """
        from pflow.runtime.node_state import get_node_failure

        api = _McpProtocolErrorNode()
        api.node_id = "create_audio"
        api.set_params({"error_message": "MCP tool failed: repository not found"})
        downstream = _OutputNode()
        downstream.node_id = "poll"
        downstream.set_params({"output_value": "should not run"})

        api >> downstream

        configs = {
            "create_audio": NodeConfig(
                node_id="create_audio",
                node_type_name="MCPNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
            "poll": NodeConfig(
                node_id="poll",
                node_type_name="OutputNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
        }

        workflow = CompiledWorkflow(start_node=api, node_configs=configs)
        shared: dict = {}
        result = WorkflowEngine().run(workflow, shared)

        assert result == "error"
        assert "poll" not in shared

        failure = get_node_failure(shared, "create_audio")
        assert failure is not None
        assert failure["category"] == "mcp_failure"
        assert failure["error"] == "MCP tool failed: repository not found"
        assert failure["data"]["error"] == "MCP tool failed: repository not found"
        assert failure["data"]["error_details"] == {
            "server": "notebooklm",
            "tool": "studio_create",
            "timeout": False,
        }

    def test_handled_mcp_protocol_error_routes_to_on_error_handler(self):
        from pflow.runtime.node_state import get_node_failure

        api = _McpProtocolErrorNode()
        api.node_id = "create_audio"
        recover = _OutputNode()
        recover.node_id = "recover"
        recover.set_params({"output_value": "handled"})

        api - "error" >> recover

        configs = {
            "create_audio": NodeConfig(
                node_id="create_audio",
                node_type_name="MCPNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
            "recover": NodeConfig(
                node_id="recover",
                node_type_name="OutputNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
        }

        workflow = CompiledWorkflow(start_node=api, node_configs=configs)
        shared: dict = {}
        result = WorkflowEngine().run(workflow, shared)

        assert result == "default"
        assert shared["recover"]["result"] == "handled"

        failure = get_node_failure(shared, "create_audio")
        assert failure is not None
        assert failure["category"] == "mcp_failure"
        assert failure["error"] == "MCP tool failed: connection refused"

        message, context = normalize_runtime_warning(shared["__warnings__"]["create_audio"])
        assert message == "Node 'create_audio' failed — on-error → 'recover'"
        assert context["type"] == "on_error_recovery"
        assert context["category"] == "mcp_failure"


class TestBatchTemplateErrorPropagation:
    """When a batch node uses permissive template resolution, template errors
    written to each item's shallow-copied shared store must propagate back
    to the parent shared store.

    Before the fix (GitHub #189), _execute_single_node used
    shared.setdefault("__template_errors__", {}) on a shallow copy of
    parent shared, which created a new dict in the copy instead of
    writing to the parent. The errors were silently lost when the copy
    was discarded.

    The fix: execute_batch() now initializes shared["__template_errors__"]
    before the batch loop, so shallow copies share the reference.
    """

    def test_permissive_batch_template_errors_propagate_to_parent(self):
        """Batch items with unresolved templates in permissive mode must
        write errors to parent shared["__template_errors__"], not a lost copy."""
        node = _ActionNode()
        node.node_id = "batch_node"
        node.set_params({"action": "default", "message": "${nonexistent.value}"})

        configs = {
            "batch_node": NodeConfig(
                node_id="batch_node",
                node_type_name="ActionNode",
                template_config=TemplateConfig(
                    template_params={"message": "${nonexistent.value}"},
                    static_params={"action": "default"},
                    expected_types={},
                    resolution_mode="permissive",
                ),
                batch_config=BatchConfig(
                    items_template=["a", "b"],
                ),
                namespaced=False,
                interface_metadata=None,
            ),
        }

        workflow = CompiledWorkflow(start_node=node, node_configs=configs)
        shared: dict = {}
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # The core assertion: template errors must be in the parent shared store.
        # Before the fix, this dict was empty because errors were written to
        # a shallow copy's independent dict, then discarded.
        assert "__template_errors__" in shared, "__template_errors__ key missing from shared store"
        assert "batch_node" in shared["__template_errors__"], (
            f"Expected 'batch_node' in __template_errors__, got keys: {list(shared['__template_errors__'].keys())}"
        )


class TestRoutingFailureTraceEventSync:
    """GH #250 — when a node returns a custom non-error action that has no
    matching successor, _handle_no_successor archives it as a routing failure.
    The trace event (recorded at step 16 with success=True because the action
    didn't start with "error") must be flipped to success=False so the trace
    agrees with __failures__.
    """

    def test_custom_action_routing_failure_flips_trace_event(self):
        """Router returns 'custom_route' with no matching edge → trace event shows failed."""
        from pflow.runtime.node_state import get_node_failure
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        router = _ActionNode()
        router.node_id = "router"
        router.set_params({"action": "custom_route"})

        # A default-edge target exists, so is_clean_termination returns False
        # and _handle_no_successor surfaces as a routing failure (not clean term).
        unreachable = _ActionNode()
        unreachable.node_id = "unreachable"
        router >> unreachable

        configs = {
            "router": NodeConfig(
                node_id="router",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
            "unreachable": NodeConfig(
                node_id="unreachable",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
        }
        workflow = CompiledWorkflow(start_node=router, node_configs=configs)
        shared: dict = {}
        collector = WorkflowTraceCollector("test")
        engine = WorkflowEngine(trace_collector=collector)
        engine.run(workflow, shared)

        # Runtime invariant: node is archived as routing failure
        failure = get_node_failure(shared, "router")
        assert failure is not None
        assert failure["category"] == "routing_error"

        # Trace invariant: event agrees with __failures__ — success=False with
        # routing-mention in error (not success=True silently disagreeing)
        router_events = [e for e in collector.events if e.get("node_id") == "router"]
        assert len(router_events) == 1
        event = router_events[0]
        assert event["success"] is False
        assert "custom_route" in event.get("error", "")
        assert "no successor edge matches" in event.get("error", "")

    def test_error_action_routing_does_not_double_mark_trace(self):
        """Error-action routing is handled by the get_node_failure guard at engine.py:182
        — mark_last_event_failed is NOT called.

        Regression guard for Task 148 Fix #2: step 17.5 archives the error-action
        node with the real category (shell_failure/http_error/etc) and data. The
        error-action branch of _handle_no_successor then hits the
        `get_node_failure is not None` guard and returns without re-archiving.
        If mark_last_event_failed were called here, it would overwrite the
        richer error text on the trace event (which step 16 already set via
        trace_error read from node data).

        Setup: node returns 'error' action, has a non-error successor (so
        _handle_no_successor is reached, not clean-terminated) with no
        matching 'error' edge.
        """
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        class _ErrorShellNode(BaseNode):
            """Mimics a shell node failing with exit_code: pre-populates shared store."""

            def post(self, shared, prep_res, exec_res):
                shared["failing"] = {"exit_code": 9, "stderr": "shell died", "error": "exit 9"}
                return "error"

        failing = _ErrorShellNode()
        failing.node_id = "failing"

        # Non-error successor so is_clean_termination returns False → routing path runs
        downstream = _ActionNode()
        downstream.node_id = "downstream"
        failing >> downstream

        configs = {
            "failing": NodeConfig(
                node_id="failing",
                node_type_name="ShellNode",  # routes to FAILURE_CATEGORY_SHELL in step 17.5
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
            "downstream": NodeConfig(
                node_id="downstream",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
        }
        workflow = CompiledWorkflow(start_node=failing, node_configs=configs)
        shared: dict = {}
        collector = WorkflowTraceCollector("test")
        engine = WorkflowEngine(trace_collector=collector)
        engine.run(workflow, shared)

        events = [e for e in collector.events if e.get("node_id") == "failing"]
        assert len(events) == 1
        event = events[0]
        # Step 16 recorded success=False (is_error_action=True) with the
        # node's own error text.
        assert event["success"] is False
        # Trace event anti-regression: error text must be the shell's error,
        # NOT the generic routing warning (which would indicate mark_last_event_failed
        # fired and overwrote it).
        assert "no successor edge matches" not in (event.get("error") or "")
        assert "exit 9" in (event.get("error") or "")
        # Failure-record anti-regression: the `get_node_failure` guard must
        # preserve the rich shell_failure data (category + exit_code) that
        # step 17.5 archived. Without the guard, a second mark_node_failed
        # call would overwrite with an empty routing_error record.
        from pflow.runtime.node_state import get_node_failure

        failure = get_node_failure(shared, "failing")
        assert failure is not None
        assert failure["category"] == "shell_failure"
        assert failure["data"]["exit_code"] == 9
        assert failure["data"]["stderr"] == "shell died"

    def test_only_mode_with_unmatched_action_does_not_flip_trace(self):
        """Snapshot --only never runs successor routing, so it can't flip the trace.

        Pins expected behavior: with --only=router, the engine executes ONLY the
        target via _run_only_snapshot — it never reaches the walk's
        _handle_no_successor. So even when the router returns a custom action with
        no matching edge, mark_last_event_failed is NOT called; the trace event
        retains success=True (the node's execution genuinely succeeded — the
        routing concern doesn't apply in --only mode).
        """
        from pflow.runtime.node_state import get_node_failure
        from pflow.runtime.workflow_trace import WorkflowTraceCollector

        router = _ActionNode()
        router.node_id = "router"
        router.set_params({"action": "custom_route"})

        # A non-error successor so is_clean_termination would return False
        # IF the snapshot path ever reached the successor lookup (it doesn't).
        downstream = _ActionNode()
        downstream.node_id = "downstream"
        router >> downstream

        configs = {
            "router": NodeConfig(
                node_id="router",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
            "downstream": NodeConfig(
                node_id="downstream",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
        }
        workflow = CompiledWorkflow(start_node=router, node_configs=configs)
        shared: dict = {}
        collector = WorkflowTraceCollector("test")
        engine = WorkflowEngine(
            trace_collector=collector,
            only_node="router",
            snapshot_events=[{"node_id": "downstream", "node_output": {"action": "default"}}],
        )
        engine.run(workflow, shared)

        # Runtime: no routing failure record — snapshot path never routes
        assert get_node_failure(shared, "router") is None
        # Trace event preserves the successful execution result — success=True
        router_events = [e for e in collector.events if e.get("node_id") == "router"]
        assert len(router_events) == 1
        assert router_events[0]["success"] is True
        assert "error" not in router_events[0] or router_events[0]["error"] is None


class TestNoSuccessorHintSuppression:
    """GH #437 — _handle_no_successor must not emit a generic routing hint for a
    node that already FAILED (action="error"). The real failure record stands on
    its own; a "add on-error" hint would visually outrank the real fix. A genuine
    routing bug (a custom non-error action with no matching edge) STILL surfaces.
    """

    def test_error_action_no_successor_writes_no_routing_hint(self):
        """An error-action node with a non-error successor → no __warnings__ hint."""
        from pflow.runtime.node_state import get_node_failure

        api = _McpProtocolErrorNode()
        api.node_id = "create_audio"
        downstream = _OutputNode()
        downstream.node_id = "poll"
        downstream.set_params({"output_value": "should not run"})

        api >> downstream

        configs = {
            "create_audio": NodeConfig(
                node_id="create_audio",
                node_type_name="MCPNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
            "poll": NodeConfig(
                node_id="poll",
                node_type_name="OutputNode",
                template_config=None,
                batch_config=None,
                namespaced=True,
                interface_metadata=None,
            ),
        }

        workflow = CompiledWorkflow(start_node=api, node_configs=configs)
        shared: dict = {}
        result = WorkflowEngine().run(workflow, shared)

        assert result == "error"
        # No routing hint for the failed node — the real failure is authoritative.
        warnings = shared.get("__warnings__", {})
        assert "create_audio" not in warnings, (
            f"Error-action node should not emit a routing hint, got: {warnings.get('create_audio')!r}"
        )
        # The real error still lives in the failure record.
        failure = get_node_failure(shared, "create_audio")
        assert failure is not None
        assert failure["error"] == "MCP tool failed: connection refused"

    def test_custom_action_no_successor_still_surfaces_routing_hint(self):
        """A custom (non-error) action with no matching edge IS a routing bug → hint."""
        from pflow.runtime.node_state import get_node_failure

        router = _ActionNode()
        router.node_id = "router"
        router.set_params({"action": "custom_route"})

        # Non-error successor so is_clean_termination is False → routing path runs.
        unreachable = _ActionNode()
        unreachable.node_id = "unreachable"
        router >> unreachable

        configs = {
            "router": NodeConfig(
                node_id="router",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
            "unreachable": NodeConfig(
                node_id="unreachable",
                node_type_name="ActionNode",
                template_config=None,
                batch_config=None,
                namespaced=False,
                interface_metadata=None,
            ),
        }
        workflow = CompiledWorkflow(start_node=router, node_configs=configs)
        shared: dict = {}
        WorkflowEngine().run(workflow, shared)

        failure = get_node_failure(shared, "router")
        assert failure is not None
        assert failure["category"] == "routing_error"
        # The genuine routing bug still gets a hint with the intentional-termination remedy.
        warning = shared["__warnings__"]["router"]
        assert "no successor edge matches" in warning
        assert 'Use next: str = "end"' in warning
