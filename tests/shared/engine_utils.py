"""Shared helper for compiling and running workflows in tests.

Provides compile_and_run() — the standard pattern for tests that need to
compile IR, seed the shared store, and execute via WorkflowEngine. This
matches the production path in WorkflowRunner._compile_and_execute().

Usage:
    from tests.shared.engine_utils import compile_and_run

    shared = compile_and_run(ir, initial_params={"text": "hello"})
    assert shared["echo"]["stdout"] == "hello"

    # With trace collector:
    collector = WorkflowTraceCollector("test")
    shared = compile_and_run(ir, trace_collector=collector)
    assert len(collector.events) == 1
"""

from typing import Any, Optional

from pflow.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine


def compile_and_run(
    ir: dict[str, Any],
    registry: Optional[Registry] = None,
    initial_params: Optional[dict[str, Any]] = None,
    shared: Optional[dict[str, Any]] = None,
    *,
    metrics_collector: Any = None,
    trace_collector: Any = None,
    only_node: Optional[str] = None,
) -> dict[str, Any]:
    """Compile IR, seed shared store, run engine, return shared.

    Mirrors the production path: compile_workflow() + seed resolved_defaults +
    seed user params (filtered) + WorkflowEngine.run().

    Args:
        ir: Workflow IR dict (must have "nodes" and "edges").
        registry: Node registry. Creates a fresh one if None.
        initial_params: User-provided params (CLI args). Passed to both
            compile_workflow (for validation/defaults) and seeded into shared
            store (for runtime template resolution). Keys starting with "__"
            are filtered from the shared store (compilation artifacts).
        shared: Pre-built shared store. Created empty if None.
        metrics_collector: Optional MetricsCollector for cost tracking.
        trace_collector: Optional WorkflowTraceCollector for debugging.
        only_node: Stop execution after this node (--only flag).

    Returns:
        The shared store dict after execution.
    """
    if registry is None:
        registry = Registry()

    params = initial_params or {}
    workflow = compile_workflow(ir, registry, initial_params=params)

    if shared is None:
        shared = {}
    if params:
        shared.update({k: v for k, v in params.items() if not k.startswith("__")})
    shared.update(workflow.resolved_defaults)

    engine = WorkflowEngine(
        metrics_collector=metrics_collector,
        trace_collector=trace_collector,
        only_node=only_node,
    )
    engine.run(workflow, shared)
    return shared
