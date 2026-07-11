"""Compiler and runtime coverage for top-level node ``retry:`` config."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from pflow.core.exceptions import CompilationError
from pflow.core.node import BaseNode, Node
from pflow.registry import Registry
from pflow.runtime.cache import MemoizationCache
from pflow.runtime.compilation.compiler import compile_workflow
from pflow.runtime.engine import WorkflowEngine


class RetryProbeNode(Node):
    def __init__(self) -> None:
        super().__init__(max_retries=4, wait=1.25)

    def prep(self, shared: dict[str, Any]) -> Any:
        return self.params.get("value")

    def exec(self, prep_res: Any) -> Any:
        return prep_res

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["result"] = exec_res
        return "default"


class RetryOnceNode(Node):
    def __init__(self) -> None:
        super().__init__(max_retries=1, wait=0)
        self.attempts = 0

    def prep(self, shared: dict[str, Any]) -> Any:
        return self.params.get("value")

    def exec(self, prep_res: Any) -> Any:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("transient")
        return prep_res

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["result"] = exec_res
        shared["attempts"] = self.attempts
        return "default"


class ValueNode(Node):
    def prep(self, shared: dict[str, Any]) -> Any:
        return self.params.get("value")

    def exec(self, prep_res: Any) -> Any:
        return prep_res

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["result"] = exec_res
        return "default"


class BaseOnlyNode(BaseNode):
    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        shared["result"] = exec_res
        return "default"


@pytest.fixture
def retry_registry() -> Registry:
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = Registry(Path(tmpdir) / "registry.json")
        module = "tests.test_runtime.test_retry_config"
        registry.save({
            "retry-probe": {
                "module": module,
                "class_name": "RetryProbeNode",
                "type": "core",
                "interface": {
                    "params": [{"name": "value", "type": "any"}],
                    "outputs": [{"name": "result", "type": "any"}],
                },
            },
            "retry-once": {
                "module": module,
                "class_name": "RetryOnceNode",
                "type": "core",
                "interface": {
                    "params": [{"name": "value", "type": "any"}],
                    "outputs": [{"name": "result", "type": "any"}, {"name": "attempts", "type": "integer"}],
                },
            },
            "value-node": {
                "module": module,
                "class_name": "ValueNode",
                "type": "core",
                "interface": {
                    "params": [{"name": "value", "type": "any"}],
                    "outputs": [{"name": "result", "type": "any"}],
                },
            },
            "base-only": {
                "module": module,
                "class_name": "BaseOnlyNode",
                "type": "core",
                "interface": {
                    "params": [{"name": "value", "type": "any"}],
                    "outputs": [{"name": "result", "type": "any"}],
                },
            },
        })
        yield registry


def _single_node_ir(*, retry: Any | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"id": "step", "type": "retry-probe", "params": {"value": "ok"}}
    if retry is not None:
        node["retry"] = retry
    return {"ir_version": "0.1.0", "nodes": [node], "edges": []}


def test_retry_overrides_node_type_default(retry_registry: Registry) -> None:
    compiled = compile_workflow(
        _single_node_ir(retry={"max": 2, "wait": 0.5, "backoff": "exponential"}), retry_registry
    )
    node = compiled.start_node

    assert node.__class__.__name__ == "RetryProbeNode"
    assert node.max_retries == 2
    assert node.wait == 0.5
    assert node.backoff == "exponential"


def test_omitted_retry_preserves_node_type_default(retry_registry: Registry) -> None:
    compiled = compile_workflow(_single_node_ir(), retry_registry)
    node = compiled.start_node

    assert node.__class__.__name__ == "RetryProbeNode"
    assert node.max_retries == 4
    assert node.wait == 1.25
    assert node.backoff == "fixed"


def test_retry_backoff_only_preserves_default_budget(retry_registry: Registry) -> None:
    compiled = compile_workflow(_single_node_ir(retry={"backoff": "exponential"}), retry_registry)
    node = compiled.start_node

    assert node.__class__.__name__ == "RetryProbeNode"
    assert node.max_retries == 4
    assert node.wait == 1.25
    assert node.backoff == "exponential"


def test_retry_on_non_node_instance_compiles_without_mutating(retry_registry: Registry) -> None:
    ir = {
        "ir_version": "0.1.0",
        "nodes": [{"id": "step", "type": "base-only", "params": {"value": "ok"}, "retry": {"max": 3}}],
        "edges": [],
    }

    compiled = compile_workflow(ir, retry_registry)

    assert compiled.start_node.__class__.__name__ == "BaseOnlyNode"
    assert not hasattr(compiled.start_node, "max_retries")


@pytest.mark.parametrize(
    "retry",
    [
        [],
        {"max": 0},
        {"max": 11},
        {"max": 1.9},
        {"max": "2"},
        {"max": True},
        {"wait": -0.1},
        {"wait": True},
        {"wait": float("inf")},
        {"wait": float("nan")},
        {"backoff": "linear"},
        {"max": 2, "jitter": True},
    ],
)
def test_invalid_retry_config_rejected_on_direct_compile(retry_registry: Registry, retry: Any) -> None:
    with pytest.raises(CompilationError, match="retry"):
        compile_workflow(_single_node_ir(retry=retry), retry_registry)


def test_invalid_retry_config_rejected_on_non_node_instance(retry_registry: Registry) -> None:
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "step",
                "type": "base-only",
                "params": {"value": "ok"},
                "retry": {"max": 0, "backoff": "linear", "jitter": True},
            }
        ],
        "edges": [],
    }

    with pytest.raises(CompilationError, match="retry"):
        compile_workflow(ir, retry_registry)


def test_retry_on_workflow_node_compiles_without_mutating(retry_registry: Registry) -> None:
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "child", "type": "workflow", "params": {"workflow": "child-flow"}, "retry": {"max": 3}},
        ],
        "edges": [],
    }

    compiled = compile_workflow(ir, retry_registry)

    assert compiled.start_node.__class__.__name__ == "WorkflowExecutor"
    assert not hasattr(compiled.start_node, "max_retries")


def test_invalid_retry_config_rejected_on_workflow_node(retry_registry: Registry) -> None:
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "child", "type": "workflow", "params": {"workflow": "child-flow"}, "retry": {"backoff": "linear"}},
        ],
        "edges": [],
    }

    with pytest.raises(CompilationError, match="retry"):
        compile_workflow(ir, retry_registry)


def test_retry_config_does_not_change_memo_cache_key(tmp_path: Path) -> None:
    cache = MemoizationCache(db_path=tmp_path / "cache.db")
    tracking_file = tmp_path / "attempts.txt"

    def ir_with_retry(retry: dict[str, Any]) -> dict[str, Any]:
        return {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "tracked",
                    "type": "shell",
                    "cache": True,
                    "params": {"command": f"echo executed >> {tracking_file}"},
                    "retry": retry,
                },
            ],
            "edges": [],
        }

    registry = Registry()
    first = compile_workflow(ir_with_retry({"max": 1}), registry)
    first_shared: dict[str, Any] = {"__memoization_cache__": cache}
    first_shared.update(first.resolved_defaults)
    WorkflowEngine().run(first, first_shared)

    assert tracking_file.read_text(encoding="utf-8").count("executed") == 1

    second = compile_workflow(ir_with_retry({"max": 3, "wait": 0.25, "backoff": "exponential"}), registry)
    second_shared: dict[str, Any] = {"__memoization_cache__": cache}
    second_shared.update(second.resolved_defaults)
    WorkflowEngine().run(second, second_shared)

    assert tracking_file.read_text(encoding="utf-8").count("executed") == 1
    assert second_shared["tracked"] == first_shared["tracked"]


def test_parallel_batch_workers_inherit_retry_budget(retry_registry: Registry) -> None:
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {"id": "source", "type": "value-node", "params": {"value": [1, 2, 3]}},
            {
                "id": "batch",
                "type": "retry-once",
                "params": {"value": "${item}"},
                "retry": {"max": 2},
                "batch": {"items": "${source.result}", "parallel": True, "max_concurrent": 3},
            },
        ],
        "edges": [{"from": "source", "to": "batch"}],
    }
    compiled = compile_workflow(ir, retry_registry)
    shared: dict[str, Any] = dict(compiled.resolved_defaults)

    WorkflowEngine().run(compiled, shared)

    assert shared["batch"]["success_count"] == 3
    assert [result["attempts"] for result in shared["batch"]["results"]] == [2, 2, 2]
    assert [result["result"] for result in shared["batch"]["results"]] == [1, 2, 3]
