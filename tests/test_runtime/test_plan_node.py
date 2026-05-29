"""Focused tests for the shared runtime.engine.plan_node primitive."""

from __future__ import annotations

from pflow.runtime.cache import MemoizationCache
from pflow.runtime.engine import NodeConfig, TemplateConfig
from pflow.runtime.engine.plan_node import plan_node


class DummyNode:
    """Minimal node stub for plan_node tests."""

    def __init__(self, params: dict[str, object]):
        self.params = params


def test_plan_node_returns_cache_disabled() -> None:
    """cache_enabled=False bypasses memo cache reads."""
    node = DummyNode({"prompt": "hello"})
    config = NodeConfig(
        node_id="node-a",
        node_type_name="LLMNode",
        template_config=None,
        batch_config=None,
        namespaced=False,
        interface_metadata=None,
        cache_enabled=False,
    )

    plan = plan_node(node, config, {"__execution__": {"node_visit_counts": {}}})

    assert plan.status == "cache_disabled"
    assert plan.cache_key is None


def test_plan_node_returns_miss_with_cache_key(tmp_path) -> None:
    """Fresh planning returns status='miss' and a memo cache key."""
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    node = DummyNode({"prompt": "hello"})
    config = NodeConfig(
        node_id="node-a",
        node_type_name="LLMNode",
        template_config=None,
        batch_config=None,
        namespaced=False,
        interface_metadata=None,
        cache_enabled=True,
    )
    shared = {"__execution__": {"node_visit_counts": {}}, "__memoization_cache__": cache}

    plan = plan_node(node, config, shared)

    assert plan.status == "miss"
    assert plan.cache_key is not None


def test_plan_node_returns_cached_memo(tmp_path) -> None:
    """Memoized cache hit returns cached_memo with cached payload."""
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    node = DummyNode({"prompt": "hello"})
    config = NodeConfig(
        node_id="node-a",
        node_type_name="LLMNode",
        template_config=None,
        batch_config=None,
        namespaced=False,
        interface_metadata=None,
        cache_enabled=True,
    )
    shared = {"__execution__": {"node_visit_counts": {}}, "__memoization_cache__": cache}

    first = plan_node(node, config, shared)
    assert first.cache_key is not None
    cache.put(first.cache_key, "node-a", "/wf.pflow.md", "default", {"response": "cached"})

    second = plan_node(node, config, shared)

    assert second.status == "cached_memo"
    assert second.cache_key == first.cache_key
    assert second.cached_action == "default"
    assert second.cached_output == {"response": "cached"}


def test_plan_node_returns_cached_in_process() -> None:
    """Matching in-process checkpoint returns cached_in_process."""
    node = DummyNode({"prompt": "hello"})
    config = NodeConfig(
        node_id="node-a",
        node_type_name="LLMNode",
        template_config=None,
        batch_config=None,
        namespaced=False,
        interface_metadata=None,
        cache_enabled=True,
    )
    shared = {"__execution__": {"node_visit_counts": {}}}
    fresh = plan_node(node, config, shared)
    shared = {
        "__execution__": {
            "completed_nodes": ["node-a"],
            "node_actions": {"node-a": "default"},
            "node_hashes": {"node-a": fresh.config_hash},
            "node_visit_counts": {},
        }
    }

    cached_plan = plan_node(node, config, shared)

    assert cached_plan.status == "cached_in_process"
    assert cached_plan.cached_action == "default"


def test_plan_node_returns_template_exception_for_strict_unresolved_template() -> None:
    """Strict unresolved templates return a miss-shaped plan with template_exception."""
    node = DummyNode({"prompt": "${missing.value}"})
    config = NodeConfig(
        node_id="node-a",
        node_type_name="LLMNode",
        template_config=TemplateConfig(
            template_params={"prompt": "${missing.value}"},
            static_params={},
            expected_types={"prompt": "str"},
            resolution_mode="strict",
        ),
        batch_config=None,
        namespaced=False,
        interface_metadata=None,
    )

    plan = plan_node(node, config, {"__execution__": {"node_visit_counts": {}}})

    assert plan.status == "miss"
    assert plan.template_exception is not None
    assert plan.cache_key is None


def test_plan_node_does_not_mutate_shared_on_cache_hit(tmp_path) -> None:
    """plan_node() must not apply cache-hit side effects to shared."""
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    node = DummyNode({"prompt": "hello"})
    config = NodeConfig(
        node_id="node-a",
        node_type_name="LLMNode",
        template_config=None,
        batch_config=None,
        namespaced=False,
        interface_metadata=None,
        cache_enabled=True,
    )
    shared = {"__execution__": {"node_visit_counts": {}}, "__memoization_cache__": cache}

    fresh = plan_node(node, config, shared)
    assert fresh.cache_key is not None
    cache.put(fresh.cache_key, "node-a", "/wf.pflow.md", "default", {"response": "cached"})
    snapshot_execution = {"node_visit_counts": dict(shared["__execution__"]["node_visit_counts"])}
    snapshot_cache = shared["__memoization_cache__"]

    cached_plan = plan_node(node, config, shared)

    assert cached_plan.status == "cached_memo"
    assert shared["__execution__"] == snapshot_execution
    assert shared["__memoization_cache__"] is snapshot_cache


def test_plan_node_uses_node_params_without_template_config() -> None:
    """When template_config is absent, plan_node hashes node.params directly."""
    node = DummyNode({"prompt": "hello"})
    config = NodeConfig(
        node_id="node-a",
        node_type_name="LLMNode",
        template_config=None,
        batch_config=None,
        namespaced=False,
        interface_metadata=None,
    )

    plan = plan_node(node, config, {"__execution__": {"node_visit_counts": {}}})

    assert plan.resolved_params is None
    assert plan.config_hash
