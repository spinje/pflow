"""Result types for workflow execution and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pflow.core.diagnostic import Diagnostic, Severity
from pflow.core.workflow.status import WorkflowStatus


@dataclass(frozen=True)
class RunnerConfig:
    """Immutable configuration for WorkflowRunner.run().

    Only execution-affecting parameters. Presentation concerns
    (output_format, logging) belong with the caller.
    """

    trace_enabled: bool = True
    cache_enabled: bool = True
    verbose: bool = False
    only_node: str | None = None
    # Task 175: force the run's execution_id instead of minting a fresh UUID. Set ONLY by a `pflow ui`
    # ▶ launch (server mints the id, threads it via PFLOW_EXECUTION_ID → the CLI run command → here) so
    # the browser can PIN the overlay to the exact run it spawned. None (every other path) → mint.
    execution_id: str | None = None
    # When True (default), WorkflowRunner.run finalizes the streamed trace it opened, so ANY caller —
    # including a library caller that just inspects the result and never saves — gets a COMPLETE, closed
    # trace file instead of an open handle + a trailer-less "incomplete" file. The CLI sets this False
    # because it alone mutates the trace AFTER the run (set_json_output) and finalizes itself afterward.
    finalize_trace: bool = True


@dataclass(frozen=True)
class ResolvedWorkflow:
    """Result of workflow resolution — IR ready for any downstream consumer.

    The IR is fully resolved at this boundary:

    - **External file references inlined** (e.g. ``- prompt: ./file.prompt.md``
      becomes the file's content). Resolution happens for ``source="file"``
      and ``source="library"`` (when path exists on disk). For ``source="content"``
      / ``source="direct"`` (inline workflows), file references are rejected
      pre-resolution because there is no base directory to resolve them against.

    Future resolution steps (sub-workflow pre-compile per #334, output exposure
    rules per #321) will land at this same boundary. Consumers should never
    re-resolve. If you find yourself calling ``resolve_file_references`` /
    compiling sub-workflows / etc. on a ``ResolvedWorkflow.ir``, that's a bug —
    file an issue against this boundary instead of duplicating resolution
    downstream. See ``execution/workflow_resolver.py`` module docstring for
    the architectural rationale.

    Returned by ``resolve_workflow()``. The Runner reads ``file_path`` for
    ``_inject_workflow_file_path()`` — callers never set this.
    """

    ir: dict[str, Any]
    source: str  # "file", "library", "content", "direct"
    file_path: str | None = None  # Absolute path for file/library, None for content/direct
    title: str | None = None  # H1 title from .pflow.md (None for dict/content sources)
    description: str | None = None  # H1 prose from .pflow.md (None for dict/content sources)
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass
class ValidationResult:
    """Result of runner.validate()."""

    valid: bool
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        """Validation errors as diagnostics."""
        return [d for d in self.diagnostics if d.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        """Validation warnings as diagnostics."""
        return [d for d in self.diagnostics if d.severity == Severity.WARNING]


@dataclass
class ExecutionResult:
    """Result of workflow execution."""

    success: bool
    status: WorkflowStatus = WorkflowStatus.SUCCESS
    shared_after: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    trace: Any | None = None  # WorkflowTraceCollector | None
    metrics: Any | None = None  # MetricsCollector | None

    @property
    def errors(self) -> list[Diagnostic]:
        """Execution errors as diagnostics."""
        return [d for d in self.diagnostics if d.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        """Execution warnings as diagnostics."""
        return [d for d in self.diagnostics if d.severity == Severity.WARNING]

    @property
    def is_durable_pause(self) -> bool:
        """True when a PAUSED run's trailer actually reached disk (Task 171).

        A gate can stamp PAUSED in memory (``gate_outcome == "paused"``) while
        the streamed trace dies mid-run — a full or read-only ``~/.pflow/debug``
        sets ``_stream_failed`` and ``finalize()`` writes no ``run.complete``
        trailer. The resume token would then never resolve. BOTH the CLI and MCP
        paused branches gate on this so neither advertises an unanswerable token;
        a non-durable pause falls through to the failure path (the gate's
        remediation ladder). ``--no-trace`` never reaches here — the runner maps
        it to FAILED (the stream is never opened, so ``_stream_failed`` stays
        False; the ``trace_enabled`` conjunct in ``_exception_to_result`` is that
        path's guard). One durability rule, one home, two surfaces.
        """
        return (
            self.status is WorkflowStatus.PAUSED
            and self.trace is not None
            and not getattr(self.trace, "_stream_failed", False)
        )


@dataclass(frozen=True)
class PlanEntry:
    """One node in an execution plan (--dry-run output)."""

    node_id: str
    node_type: str
    status: Literal["cached", "execute", "sub_workflow", "opaque", "routing_error"]
    cause: Literal[
        "hash_match",
        "no_cache_match",
        "downstream",
        "cache_disabled",
        "template_error",
        "dynamic",
        "downstream_batch",
        "routing_error",
    ]
    # Predicted cache_key from the planner's plan_node call. None when this
    # entry has no concrete node cache state (routing errors, opaque
    # sub-workflows, aggregate batch entries).
    cache_key: str | None = None
    action: str | None = None
    age_sec: float | None = None
    last_cost_usd: float | None = None
    last_duration_ms: float | None = None
    last_run_age_sec: float | None = None
    sub_plan: Plan | None = None
    diagnostic: Diagnostic | None = None
    batch_count: int | None = None
    batch_parallel: bool = False
    batch_items_cached: int | None = None
    batch_items_total: int | None = None
    # issue #445: for a ``loop:`` node, the resolved max_iterations upper bound.
    # The planner plans the body once and the summary multiplies this entry's
    # single-pass cost/duration (and its sub_plan rollup) by this factor.
    loop_iterations: int | None = None
    # Task 125: this node declares `approval: required` — the run pauses for a
    # human before it executes. Stamped from NodeConfig in the planner's shared
    # annotate funnel (covers standard AND sub-workflow entries); dry-run is the
    # agent's gate-discovery surface, so plan-says-pause ⟺ engine-pauses is
    # drift-suite pinned.
    approval: bool = False


@dataclass(frozen=True)
class PlanSummary:
    """Aggregate counts for a single plan level.

    `estimated_cost_usd` is LLM-only (matches the domain: only LLM-family
    nodes have `cost_usd`). `estimated_duration_ms` is all-node (any node
    with prior execution has a recorded duration in its cache entry). The
    two `nodes_without_*_history` counters reflect the same distinction —
    `nodes_without_history` counts LLM would-execute with no cost data,
    `nodes_without_duration_history` counts any would-execute with no
    duration data.

    `opaque_count` counts entries with `status="opaque"` — sub-workflows
    the planner couldn't resolve (`workflow: ${var}`) and whose cost/
    duration are therefore absent from the totals. Agents cost-gating
    should treat `opaque_count > 0` as a "refuse-to-proceed" signal:
    the summary cost is an under-estimate by a potentially unbounded
    amount. Exposing this separately from `nodes_without_history`
    preserves the "nodes_without_history = LLM nodes with no cost
    record" semantic and avoids retasking an existing field.
    """

    total: int
    cached_count: int
    execute_count: int
    cache_boundary: str | None
    execute_by_type: dict[str, int]
    estimated_cost_usd: float
    nodes_without_history: int
    estimated_duration_ms: float = 0.0
    nodes_without_duration_history: int = 0
    opaque_count: int = 0
    cost_basis: Literal["upper_bound", "exact"] = "upper_bound"
    total_including_nested: int | None = None
    cached_including_nested: int | None = None
    execute_including_nested: int | None = None
    execute_by_type_including_nested: dict[str, int] | None = None
    estimated_cost_usd_including_nested: float | None = None
    nodes_without_history_including_nested: int | None = None
    estimated_duration_ms_including_nested: float | None = None
    nodes_without_duration_history_including_nested: int | None = None
    opaque_count_including_nested: int | None = None


@dataclass(frozen=True)
class ResumePlanInfo:
    """Resume context for a ``--dry-run`` of a resumed run (Task 164, Decision 2).

    A resumed plan starts AT the failed step K (upstream is restored, not planned),
    so the plan's entries + cost cover K onward ONLY. This carries the honesty
    surface the formatter renders: the entry node K, the upstream node ids restored
    from the source trace, and the source ``execution_id`` the tail resumes from.
    """

    entry_node: str
    restored_nodes: list[str]
    execution_id: str


@dataclass(frozen=True)
class Plan:
    """Execution plan for a workflow -- the result of --dry-run."""

    workflow: str
    entries: list[PlanEntry]
    summary: PlanSummary
    diagnostics: list[Diagnostic] = field(default_factory=list)
    workflow_path: str | None = None
    resume: ResumePlanInfo | None = None
