"""Integration tests for trace event capture through real wrapper chains.

These tests verify the integration seams between wrappers, trace collectors,
and batch processing — areas where silent data loss occurs when wrapper
chain traversal or attribute delegation breaks.
"""

from typing import Any

from pflow.pocketflow import Node
from pflow.runtime.workflow_trace import WorkflowTraceCollector
from pflow.runtime.wrappers.batch_node import PflowBatchNode
from pflow.runtime.wrappers.instrumented_wrapper import InstrumentedNodeWrapper
from pflow.runtime.wrappers.namespaced_wrapper import NamespacedNodeWrapper
from pflow.runtime.wrappers.template_wrapper import TemplateAwareNodeWrapper


class EchoNode(Node):
    """Minimal test node: writes prompt param to namespaced output."""

    def prep(self, shared: dict[str, Any]) -> str:
        return self.params.get("prompt", "")

    def exec(self, prep_res: str) -> str:
        return prep_res

    def post(self, shared: dict[str, Any], prep_res: str, exec_res: str) -> str:
        shared["response"] = exec_res
        return "default"


class ItemProcessorNode(Node):
    """Minimal test node for batch: reads 'item' from shared, writes result."""

    def prep(self, shared: dict[str, Any]) -> Any:
        return shared.get("item")

    def exec(self, prep_res: Any) -> str:
        return f"processed-{prep_res}"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["result"] = exec_res
        return "default"


class TestWrapperChainTraceWithTemplateResolutions:
    """Test 1: Wrapper chain -> trace event with template_resolutions.

    Verifies the full pipeline: TemplateAwareNodeWrapper resolves templates,
    stores last_resolutions, NamespacedNodeWrapper delegates attribute access
    via __getattr__, and InstrumentedNodeWrapper's _find_template_wrapper()
    traverses through the proxy to read template_resolutions into the trace event.

    If the chain shape changes or NamespacedNodeWrapper's __getattr__ delegation
    breaks, template_resolutions silently becomes {} — no error, just data loss.
    """

    def test_template_resolutions_propagate_through_wrapper_chain(self) -> None:
        """When a template param is resolved, the trace event captures
        the before/after mapping via wrapper chain traversal."""
        # Build wrapper chain inside-out (matching compiler.py order):
        # actual -> TemplateAwareNodeWrapper -> NamespacedNodeWrapper -> InstrumentedNodeWrapper
        node_id = "echo"
        actual_node = EchoNode()

        template_wrapper = TemplateAwareNodeWrapper(
            inner_node=actual_node,
            node_id=node_id,
        )

        namespace_wrapper = NamespacedNodeWrapper(
            inner_node=template_wrapper,
            node_id=node_id,
        )

        collector = WorkflowTraceCollector("test-workflow")
        # Disable LLM interception to avoid importing llm in tests
        collector.enable_llm_interception = False

        instrumented = InstrumentedNodeWrapper(
            inner_node=namespace_wrapper,
            node_id=node_id,
            trace_collector=collector,
        )

        # set_params flows through: InstrumentedNodeWrapper -> NamespacedNodeWrapper
        # (via __getattr__) -> TemplateAwareNodeWrapper.set_params()
        instrumented.set_params({"prompt": "Hello ${name}", "__node_id__": node_id})

        shared: dict[str, Any] = {"name": "World"}
        instrumented._run(shared)

        # -- Assert trace event captured template resolutions --
        assert len(collector.events) == 1
        event = collector.events[0]

        assert event["success"] is True
        assert event["node_type"] == "EchoNode"

        # Template resolutions: the critical integration seam.
        # _find_template_wrapper() traverses NamespacedNodeWrapper -> TemplateAwareNodeWrapper
        # via hasattr(current, "last_resolutions") which works through __getattr__ delegation.
        assert "template_resolutions" in event, (
            "template_resolutions missing from trace event — "
            "_find_template_wrapper() traversal through NamespacedNodeWrapper may be broken"
        )
        resolutions = event["template_resolutions"]
        assert "prompt" in resolutions
        assert resolutions["prompt"]["template"] == "Hello ${name}"
        assert resolutions["prompt"]["resolved"] == "Hello World"

        # Node output: namespaced under node_id in shared store,
        # read by InstrumentedNodeWrapper._record_trace() via shared.get(node_id)
        assert "node_output" in event
        assert event["node_output"]["response"] == "Hello World"

        # Mutations: node_id key was added to shared store by NamespacedNodeWrapper
        assert "mutations" in event
        assert node_id in event["mutations"]["added"]


class TestBatchNodeTraceEvents:
    """Test 2: Batch node -> per-item trace events in parent trace event.

    Verifies the full batch trace pipeline:
    1. PflowBatchNode.prep() initializes _batch_trace accumulator in shared store
    2. _exec_single() calls _capture_item_trace() after each item execution
    3. post() copies _batch_trace[node_id] to self._trace_items
    4. InstrumentedNodeWrapper._find_batch_or_workflow_node() traverses the
       wrapper chain to find PflowBatchNode and reads its _trace_items
    5. _record_trace() passes batch_items to the collector

    Four handoff points, each using a different mechanism. If any link breaks,
    batch items silently disappear from traces.
    """

    def test_batch_items_appear_in_trace_event(self) -> None:
        """When a batch node processes items, per-item trace data appears
        nested inside the parent trace event."""
        node_id = "processor"
        inner_node = ItemProcessorNode()

        # Wrap inner node with namespace (batch sits outside namespace)
        namespace_wrapper = NamespacedNodeWrapper(
            inner_node=inner_node,
            node_id=node_id,
        )

        batch_node = PflowBatchNode(
            inner_node=namespace_wrapper,
            node_id=node_id,
            batch_config={"items": "${data}"},
        )

        collector = WorkflowTraceCollector("test-batch")
        collector.enable_llm_interception = False

        instrumented = InstrumentedNodeWrapper(
            inner_node=batch_node,
            node_id=node_id,
            trace_collector=collector,
        )

        shared: dict[str, Any] = {"data": ["a", "b", "c"]}
        instrumented._run(shared)

        # -- Assert trace event structure --
        assert len(collector.events) == 1, f"Expected 1 trace event (the batch node), got {len(collector.events)}"
        event = collector.events[0]

        assert event["success"] is True
        assert event["node_type"] == "ItemProcessorNode"

        # Batch items: the critical integration seam.
        # _find_batch_or_workflow_node() must find PflowBatchNode via wrapper chain,
        # and its _trace_items must have been populated by post() from _batch_trace.
        assert "batch_items" in event, (
            "batch_items missing from trace event — "
            "either _capture_item_trace didn't run, post() didn't set _trace_items, "
            "or _find_batch_or_workflow_node() traversal is broken"
        )
        batch_items = event["batch_items"]
        assert len(batch_items) == 3

        # Verify per-item structure
        for i, expected_item in enumerate(["a", "b", "c"]):
            item_trace = batch_items[i]
            assert item_trace["index"] == i
            assert item_trace["item"] == expected_item
            assert item_trace["success"] is True
            assert "duration_ms" in item_trace
            assert isinstance(item_trace["duration_ms"], (int, float))

            # Per-item node output captured from isolated item context
            assert "node_output" in item_trace
            assert item_trace["node_output"]["result"] == f"processed-{expected_item}"


class TemplatedItemNode(Node):
    """Batch node with template param: reads item, uses template command."""

    def prep(self, shared: dict[str, Any]) -> str:
        return self.params.get("command", "")

    def exec(self, prep_res: str) -> str:
        return f"ran: {prep_res}"

    def post(self, shared: dict[str, Any], prep_res: str, exec_res: str) -> str:
        shared["stdout"] = exec_res
        return "default"


class FailingNode(Node):
    """Node that fails on certain inputs."""

    def prep(self, shared: dict[str, Any]) -> Any:
        return shared.get("item")

    def exec(self, prep_res: Any) -> str:
        if prep_res == "bad":
            raise ValueError("Item processing failed: bad input")
        return f"ok-{prep_res}"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["result"] = exec_res
        return "default"


class TestTraceToReportFormatCompatibility:
    """Verify the trace collector's output is readable by the report generator.

    Both sides have unit tests with synthetic data. This test catches format
    drift: if a field name changes in _record_trace() but not in the report
    generator (or vice versa), reports silently produce empty content.

    Uses a real wrapper chain → real trace → real report generation.
    """

    def test_batch_trace_produces_valid_report(self, tmp_path: "Any") -> None:
        """Run a batch through real wrappers, save trace, generate report,
        verify the report has real content from execution."""
        import json

        node_id = "processor"
        inner_node = ItemProcessorNode()

        namespace_wrapper = NamespacedNodeWrapper(
            inner_node=inner_node,
            node_id=node_id,
        )

        batch_node = PflowBatchNode(
            inner_node=namespace_wrapper,
            node_id=node_id,
            batch_config={"items": "${data}"},
        )

        collector = WorkflowTraceCollector("format-compat-test")
        collector.enable_llm_interception = False

        instrumented = InstrumentedNodeWrapper(
            inner_node=batch_node,
            node_id=node_id,
            trace_collector=collector,
        )

        shared: dict[str, Any] = {"data": ["alpha", "beta"]}
        instrumented._run(shared)

        # Build trace dict from REAL collector data (same structure as save_to_file)
        trace_data = {
            "format_version": "2.0.0",
            "execution_id": collector.execution_id,
            "workflow_name": collector.workflow_name,
            "start_time": collector.start_time.isoformat(),
            "end_time": collector.start_time.isoformat(),
            "duration_ms": 100.0,
            "final_status": "success",
            "nodes_executed": len(collector.events),
            "nodes_failed": 0,
            "nodes": collector.events,  # The REAL events from execution
        }
        trace_path = tmp_path / "trace.json"
        trace_path.write_text(json.dumps(trace_data, default=str))

        # Generate report from the real trace
        from pflow.core.trace_report import generate_report

        report_dir = generate_report(str(trace_path), str(tmp_path / "report"))

        assert report_dir is not None, "Report generation failed on real trace data"
        assert (report_dir / "summary.md").exists()

        # Batch node should create a directory (not a flat file)
        batch_dir = report_dir / "01-processor"
        assert batch_dir.is_dir(), "Batch node should produce a directory, not a file"
        assert (batch_dir / "summary.md").exists()
        assert (batch_dir / "item-0.md").exists()
        assert (batch_dir / "item-1.md").exists()

        # Verify REAL execution data appears in the report (not empty/placeholder)
        item0_md = (batch_dir / "item-0.md").read_text()
        assert "processed-alpha" in item0_md, (
            "Report item file doesn't contain real node output — "
            "trace format may have diverged from report generator expectations"
        )

        item1_md = (batch_dir / "item-1.md").read_text()
        assert "processed-beta" in item1_md

        # Summary should reference the batch
        summary_md = (report_dir / "summary.md").read_text()
        assert "processor" in summary_md


class TestParallelBatchTraceCapture:
    """D2: Verify parallel batch items capture template_resolutions correctly.

    The parallel path deep-copies the node chain per thread. Each copy's
    TemplateAwareNodeWrapper must independently store last_resolutions
    that are read back before the thread returns.
    """

    def test_parallel_batch_captures_per_item_template_resolutions(self) -> None:
        node_id = "greeter"
        inner_node = TemplatedItemNode()

        template_wrapper = TemplateAwareNodeWrapper(
            inner_node=inner_node,
            node_id=node_id,
        )

        namespace_wrapper = NamespacedNodeWrapper(
            inner_node=template_wrapper,
            node_id=node_id,
        )

        batch_node = PflowBatchNode(
            inner_node=namespace_wrapper,
            node_id=node_id,
            batch_config={"items": "${data}", "parallel": True},
        )

        collector = WorkflowTraceCollector("test-parallel-batch")
        collector.enable_llm_interception = False

        instrumented = InstrumentedNodeWrapper(
            inner_node=batch_node,
            node_id=node_id,
            trace_collector=collector,
        )

        instrumented.set_params({"command": "echo ${item}", "__node_id__": node_id})

        shared: dict[str, Any] = {"data": ["alice", "bob"]}
        instrumented._run(shared)

        assert len(collector.events) == 1
        event = collector.events[0]
        assert "batch_items" in event
        batch_items = event["batch_items"]
        assert len(batch_items) == 2

        for i, name in enumerate(["alice", "bob"]):
            item = batch_items[i]
            assert item["success"] is True
            # Template resolutions captured from deep-copied chain
            resolutions = item.get("template_resolutions", {})
            assert "command" in resolutions, (
                f"Item {i}: template_resolutions missing 'command' — "
                "deep-copied TemplateAwareNodeWrapper may not preserve last_resolutions"
            )
            assert resolutions["command"]["resolved"] == f"echo {name}"


class TestFailedBatchItemsInTrace:
    """D4: Verify failed batch items appear with error data in trace."""

    def test_failed_item_has_error_in_trace(self) -> None:
        node_id = "processor"
        inner_node = FailingNode()

        namespace_wrapper = NamespacedNodeWrapper(
            inner_node=inner_node,
            node_id=node_id,
        )

        batch_node = PflowBatchNode(
            inner_node=namespace_wrapper,
            node_id=node_id,
            batch_config={"items": "${data}", "error_handling": "continue"},
        )

        collector = WorkflowTraceCollector("test-failed-batch")
        collector.enable_llm_interception = False

        instrumented = InstrumentedNodeWrapper(
            inner_node=batch_node,
            node_id=node_id,
            trace_collector=collector,
        )

        shared: dict[str, Any] = {"data": ["good", "bad", "good"]}
        instrumented._run(shared)

        assert len(collector.events) == 1
        event = collector.events[0]
        batch_items = event["batch_items"]
        assert len(batch_items) == 3

        # Item 0: success
        assert batch_items[0]["success"] is True
        assert batch_items[0]["item"] == "good"

        # Item 1: failure
        assert batch_items[1]["success"] is False
        assert batch_items[1]["item"] == "bad"
        assert "error" in batch_items[1]
        assert "bad input" in batch_items[1]["error"]

        # Item 2: success
        assert batch_items[2]["success"] is True


class TestSubWorkflowTraceTree:
    """D3: Verify sub-workflow internal nodes appear as sub_workflow_events.

    Uses compile_ir_to_flow to build a real parent workflow with a child
    sub-workflow. The child's nodes should appear nested in the parent's
    trace event under sub_workflow_events.
    """

    def test_sub_workflow_events_in_parent_trace(self, tmp_path: "Any") -> None:
        from tests.shared.markdown_utils import write_workflow_file

        # Create child workflow: single shell node
        child_ir = {
            "nodes": [
                {
                    "id": "inner-step",
                    "type": "shell",
                    "params": {"command": "echo hello"},
                    "purpose": "Simple inner step for sub-workflow test",
                },
            ],
        }
        child_path = tmp_path / "child.pflow.md"
        write_workflow_file(child_ir, child_path)

        # Create parent workflow: calls child sub-workflow
        parent_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "call-child",
                    "type": "workflow",
                    "params": {"workflow": str(child_path)},
                    "purpose": "Call child sub-workflow for trace test",
                },
            ],
            "edges": [],
        }

        from pflow.registry import Registry
        from pflow.runtime import compile_ir_to_flow

        collector = WorkflowTraceCollector("test-sub-workflow")
        collector.enable_llm_interception = False

        registry = Registry()
        flow = compile_ir_to_flow(
            ir_json=parent_ir,
            registry=registry,
            validate=False,
            trace_collector=collector,
        )

        shared: dict[str, Any] = {"_trace_collector": collector}
        flow.run(shared)

        # Parent trace should have one event (call-child)
        assert len(collector.events) >= 1
        parent_event = collector.events[0]
        assert parent_event["node_id"] == "call-child"

        # That event should contain sub_workflow_events from the child
        sub_events = parent_event.get("sub_workflow_events")
        assert sub_events is not None, (
            "sub_workflow_events missing — child trace collector may not be created "
            "or _child_trace_events may not be read by InstrumentedNodeWrapper"
        )
        assert len(sub_events) >= 1

        # Child's inner-step should be present
        child_node_ids = [e["node_id"] for e in sub_events]
        assert "inner-step" in child_node_ids
