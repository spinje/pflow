"""Tests for per-item parameter overrides in batch nodes via template references.

Verifies that when a batch node's params reference item fields via templates
(e.g., `config: ${item.config_value}`), the template wrapper resolves them
correctly per-item. This is the mechanism that would enable per-item LLM
config overrides like `reasoning_effort: ${item.reasoning_effort}`.

The critical behavior being tested:
1. PflowBatchNode._exec_single() injects `item_shared[self.item_alias] = current_item`
2. TemplateAwareNodeWrapper._run() builds context from shared store (which now includes item)
3. Template params referencing ${item.field} resolve to the current item's field value

Tests use the compiler to build the full wrapper chain
(Instrumented > Batch > Namespace > Template > ActualNode) to verify the
integration works end-to-end, not just in isolation.

Verification strategy: ParamCaptureNode writes its resolved params to
shared["captured_params"] during post(). The batch wrapper collects these
per-item results into shared[node_id]["results"], where each result dict
contains the captured_params. Tests inspect these results to verify that
each batch item received independently resolved param values.
"""

import tempfile
from pathlib import Path
from typing import Any

import pytest

from pflow.pocketflow import Node
from pflow.registry.registry import Registry
from pflow.runtime import compile_ir_to_flow


class ParamCaptureNode(Node):
    """Test node that captures its resolved params during execution.

    Instead of doing real work, this node records `self.params` at execution
    time into the shared store. The batch wrapper then collects these into
    per-item results, letting tests verify per-item template resolution.

    Interface:
    - Params: primary_input: any, config_param: any
    - Writes: shared["captured_params"]: dict  # Copy of self.params at exec time
    """

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        # Capture a snapshot of params as they exist at prep time
        # (after TemplateAwareNodeWrapper has resolved templates)
        return dict(self.params)

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        return prep_res

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        # Store to shared (namespace wrapper writes this to shared[node_id]["captured_params"])
        shared["captured_params"] = exec_res
        return "default"


class ValueProducerNode(Node):
    """Simple node that puts a configured value into shared store.

    Interface:
    - Params: value: Any  # Value to produce
    - Writes: shared["result"]: Any
    """

    def prep(self, shared: dict[str, Any]) -> Any:
        return self.params.get("value")

    def exec(self, prep_res: Any) -> Any:
        return prep_res

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["result"] = exec_res
        return "default"


def _make_registry(node_types: dict[str, dict[str, Any]]) -> Registry:
    """Create a temporary registry with given node types.

    Args:
        node_types: Dict of node_type_name -> metadata dict

    Returns:
        Registry instance with nodes registered
    """
    tmpdir = tempfile.mkdtemp()
    registry_path = Path(tmpdir) / "test_registry.json"
    registry = Registry(registry_path)
    registry.save(node_types)
    return registry


@pytest.fixture
def param_capture_registry() -> Registry:
    """Create a temp registry with the ParamCaptureNode registered."""
    return _make_registry({
        "param-capture": {
            "module": "tests.test_runtime.test_batch_param_override",
            "class_name": "ParamCaptureNode",
            "docstring": "Test node that captures resolved params",
            "file_path": str(Path(__file__)),
            "type": "core",
            "interface": {
                "params": [
                    {"name": "primary_input", "type": "any"},
                    {"name": "config_param", "type": "any"},
                ],
                "outputs": [{"name": "captured_params", "type": "any"}],
            },
        }
    })


@pytest.fixture
def two_node_registry() -> Registry:
    """Registry with both ParamCaptureNode and ValueProducerNode."""
    return _make_registry({
        "param-capture": {
            "module": "tests.test_runtime.test_batch_param_override",
            "class_name": "ParamCaptureNode",
            "docstring": "Test node that captures resolved params",
            "file_path": str(Path(__file__)),
            "type": "core",
            "interface": {
                "params": [
                    {"name": "primary_input", "type": "any"},
                    {"name": "config_param", "type": "any"},
                ],
                "outputs": [{"name": "captured_params", "type": "any"}],
            },
        },
        "value-producer": {
            "module": "tests.test_runtime.test_batch_param_override",
            "class_name": "ValueProducerNode",
            "docstring": "Produces a configured value into shared store",
            "file_path": str(Path(__file__)),
            "type": "core",
            "interface": {
                "params": [{"name": "value", "type": "any"}],
                "outputs": [{"name": "result", "type": "any"}],
            },
        },
    })


def _get_captured_params(shared: dict[str, Any], node_id: str) -> list[dict[str, Any]]:
    """Extract per-item captured_params from batch results.

    Each batch result contains the outputs written by the inner node to
    the shared store. ParamCaptureNode writes its resolved params as
    "captured_params", which the batch wrapper includes in results.

    Args:
        shared: The shared store after workflow execution
        node_id: The batch node's ID

    Returns:
        List of captured param dicts, one per batch item, in execution order
    """
    results = shared[node_id]["results"]
    return [r["captured_params"] for r in results]


class TestPerItemParamOverride:
    """Tests that node params referencing item fields resolve per-item in batch."""

    def test_multiple_params_resolve_per_item(self, param_capture_registry: Registry) -> None:
        """When multiple params use ${item.field}, each batch item gets different resolved values.

        This is the core test: both primary_input and config_param should resolve
        independently per item, proving that template resolution happens fresh
        for each batch item's context.
        """
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "param-capture",
                    "params": {
                        "primary_input": "${item.prompt}",
                        "config_param": "${item.effort}",
                    },
                    "batch": {
                        "items": [
                            {"prompt": "Explain quantum physics", "effort": "high"},
                            {"prompt": "What is 2+2?", "effort": "low"},
                            {"prompt": "Summarize this paper", "effort": "medium"},
                        ],
                        "as": "item",
                    },
                }
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(ir, registry=param_capture_registry)
        shared: dict[str, Any] = {}
        flow.run(shared)

        # Verify batch completed successfully
        assert shared["batch_node"]["count"] == 3
        assert shared["batch_node"]["success_count"] == 3
        assert shared["batch_node"]["error_count"] == 0

        # Verify per-item param resolution through batch results
        captured = _get_captured_params(shared, "batch_node")
        assert len(captured) == 3

        # Item 0: prompt="Explain quantum physics", effort="high"
        assert captured[0]["primary_input"] == "Explain quantum physics"
        assert captured[0]["config_param"] == "high"

        # Item 1: prompt="What is 2+2?", effort="low"
        assert captured[1]["primary_input"] == "What is 2+2?"
        assert captured[1]["config_param"] == "low"

        # Item 2: prompt="Summarize this paper", effort="medium"
        assert captured[2]["primary_input"] == "Summarize this paper"
        assert captured[2]["config_param"] == "medium"

    def test_config_param_varies_while_primary_is_fixed(self, param_capture_registry: Registry) -> None:
        """A fixed primary param with a per-item config param still resolves correctly.

        This simulates the real-world case: same prompt template but different
        reasoning_effort/temperature per item.
        """
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "param-capture",
                    "params": {
                        "primary_input": "fixed prompt for all items",
                        "config_param": "${item.temperature}",
                    },
                    "batch": {
                        "items": [
                            {"temperature": "0.1"},
                            {"temperature": "0.5"},
                            {"temperature": "0.9"},
                        ],
                        "as": "item",
                    },
                }
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(ir, registry=param_capture_registry)
        shared: dict[str, Any] = {}
        flow.run(shared)

        assert shared["batch_node"]["count"] == 3
        assert shared["batch_node"]["success_count"] == 3

        captured = _get_captured_params(shared, "batch_node")
        assert len(captured) == 3

        # Primary input should be the same for all items (static, not templated)
        for params in captured:
            assert params["primary_input"] == "fixed prompt for all items"

        # Config param should vary per item
        assert captured[0]["config_param"] == "0.1"
        assert captured[1]["config_param"] == "0.5"
        assert captured[2]["config_param"] == "0.9"

    def test_nested_item_field_in_config_param(self, param_capture_registry: Registry) -> None:
        """Deeply nested item fields resolve correctly for config params.

        Verifies ${item.config.level} with nested dict access.
        """
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "param-capture",
                    "params": {
                        "primary_input": "${item.data}",
                        "config_param": "${item.config.level}",
                    },
                    "batch": {
                        "items": [
                            {"data": "text A", "config": {"level": "debug"}},
                            {"data": "text B", "config": {"level": "info"}},
                        ],
                        "as": "item",
                    },
                }
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(ir, registry=param_capture_registry)
        shared: dict[str, Any] = {}
        flow.run(shared)

        assert shared["batch_node"]["count"] == 2
        assert shared["batch_node"]["success_count"] == 2

        captured = _get_captured_params(shared, "batch_node")
        assert len(captured) == 2
        assert captured[0]["primary_input"] == "text A"
        assert captured[0]["config_param"] == "debug"
        assert captured[1]["primary_input"] == "text B"
        assert captured[1]["config_param"] == "info"

    def test_custom_item_alias_resolves_config_params(self, param_capture_registry: Registry) -> None:
        """Per-item param override works with custom alias (not default 'item').

        Uses 'record' instead of 'item' as the batch alias.
        """
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "param-capture",
                    "params": {
                        "primary_input": "${record.value}",
                        "config_param": "${record.mode}",
                    },
                    "batch": {
                        "items": [
                            {"value": "alpha", "mode": "fast"},
                            {"value": "beta", "mode": "thorough"},
                        ],
                        "as": "record",
                    },
                }
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(ir, registry=param_capture_registry)
        shared: dict[str, Any] = {}
        flow.run(shared)

        assert shared["batch_node"]["count"] == 2
        assert shared["batch_node"]["success_count"] == 2

        captured = _get_captured_params(shared, "batch_node")
        assert len(captured) == 2
        assert captured[0]["primary_input"] == "alpha"
        assert captured[0]["config_param"] == "fast"
        assert captured[1]["primary_input"] == "beta"
        assert captured[1]["config_param"] == "thorough"


class TestPerItemParamOverrideParallel:
    """Same tests but with parallel=True to verify thread safety of per-item param resolution.

    In parallel mode, PflowBatchNode deep-copies the inner node chain per thread.
    This ensures TemplateAwareNodeWrapper instances don't share state across threads,
    so per-item param resolution is isolated.
    """

    def test_parallel_multiple_params_resolve_per_item(self, param_capture_registry: Registry) -> None:
        """Parallel batch: multiple params with ${item.field} resolve correctly per item.

        Deep copy of the node chain should ensure each thread resolves templates
        independently without race conditions.
        """
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "param-capture",
                    "params": {
                        "primary_input": "${item.prompt}",
                        "config_param": "${item.effort}",
                    },
                    "batch": {
                        "items": [
                            {"prompt": "Task A", "effort": "high"},
                            {"prompt": "Task B", "effort": "low"},
                            {"prompt": "Task C", "effort": "medium"},
                            {"prompt": "Task D", "effort": "high"},
                        ],
                        "as": "item",
                        "parallel": True,
                        "max_concurrent": 4,
                    },
                }
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(ir, registry=param_capture_registry)
        shared: dict[str, Any] = {}
        flow.run(shared)

        # Verify batch completed successfully
        assert shared["batch_node"]["count"] == 4
        assert shared["batch_node"]["success_count"] == 4
        assert shared["batch_node"]["error_count"] == 0

        # Batch results preserve input order even in parallel mode
        captured = _get_captured_params(shared, "batch_node")
        assert len(captured) == 4

        assert captured[0]["primary_input"] == "Task A"
        assert captured[0]["config_param"] == "high"

        assert captured[1]["primary_input"] == "Task B"
        assert captured[1]["config_param"] == "low"

        assert captured[2]["primary_input"] == "Task C"
        assert captured[2]["config_param"] == "medium"

        assert captured[3]["primary_input"] == "Task D"
        assert captured[3]["config_param"] == "high"

    def test_parallel_no_cross_contamination(self, param_capture_registry: Registry) -> None:
        """Parallel batch: verify no cross-contamination between items' config params.

        Each captured param set should have internally consistent values
        (prompt and effort from the SAME item, never mixed).
        """
        # Use items with unique, easily verifiable prompt-effort pairs
        items = [{"prompt": f"prompt_{i}", "effort": f"effort_{i}"} for i in range(8)]

        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "batch_node",
                    "type": "param-capture",
                    "params": {
                        "primary_input": "${item.prompt}",
                        "config_param": "${item.effort}",
                    },
                    "batch": {
                        "items": items,
                        "as": "item",
                        "parallel": True,
                        "max_concurrent": 4,
                    },
                }
            ],
            "edges": [],
        }

        flow = compile_ir_to_flow(ir, registry=param_capture_registry)
        shared: dict[str, Any] = {}
        flow.run(shared)

        assert shared["batch_node"]["count"] == 8
        assert shared["batch_node"]["success_count"] == 8

        # The critical check: for each result, the index suffix of
        # primary_input and config_param must match (no cross-contamination)
        captured = _get_captured_params(shared, "batch_node")
        assert len(captured) == 8
        for params in captured:
            prompt_idx = params["primary_input"].split("_")[1]
            effort_idx = params["config_param"].split("_")[1]
            assert prompt_idx == effort_idx, (
                f"Cross-contamination detected: primary_input={params['primary_input']} "
                f"but config_param={params['config_param']}"
            )


class TestPerItemParamOverrideWithUpstreamData:
    """Tests for per-item param override when items come from upstream node output."""

    def test_upstream_items_with_per_item_config(self, two_node_registry: Registry) -> None:
        """Items from an upstream node's output still get per-item param resolution.

        This tests the full pipeline: upstream node produces items, batch node
        consumes them with per-item template resolution on multiple params.
        """
        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source",
                    "type": "value-producer",
                    "params": {
                        "value": [
                            {"text": "Hello", "lang": "en"},
                            {"text": "Bonjour", "lang": "fr"},
                            {"text": "Hola", "lang": "es"},
                        ]
                    },
                },
                {
                    "id": "processor",
                    "type": "param-capture",
                    "params": {
                        "primary_input": "${item.text}",
                        "config_param": "${item.lang}",
                    },
                    "batch": {
                        "items": "${source.result}",
                        "as": "item",
                    },
                },
            ],
            "edges": [{"from": "source", "to": "processor"}],
        }

        flow = compile_ir_to_flow(ir, registry=two_node_registry)
        shared: dict[str, Any] = {}
        flow.run(shared)

        # Verify source produced items
        assert shared["source"]["result"] == [
            {"text": "Hello", "lang": "en"},
            {"text": "Bonjour", "lang": "fr"},
            {"text": "Hola", "lang": "es"},
        ]

        # Verify batch processed all items
        assert shared["processor"]["count"] == 3
        assert shared["processor"]["success_count"] == 3

        # Verify per-item param resolution
        captured = _get_captured_params(shared, "processor")
        assert len(captured) == 3
        assert captured[0]["primary_input"] == "Hello"
        assert captured[0]["config_param"] == "en"
        assert captured[1]["primary_input"] == "Bonjour"
        assert captured[1]["config_param"] == "fr"
        assert captured[2]["primary_input"] == "Hola"
        assert captured[2]["config_param"] == "es"
