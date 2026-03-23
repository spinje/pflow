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
