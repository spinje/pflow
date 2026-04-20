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


@dataclass(frozen=True)
class ResolvedWorkflow:
    """Result of workflow resolution.

    Returned by resolve_workflow(). The Runner reads file_path
    for _inject_workflow_file_path() -- callers never set this.
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
        "routing_error",
    ]
    action: str | None = None
    age_sec: float | None = None
    last_cost_usd: float | None = None
    last_duration_ms: float | None = None
    last_run_age_sec: float | None = None
    sub_plan: Plan | None = None
    diagnostic: Diagnostic | None = None


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
class Plan:
    """Execution plan for a workflow -- the result of --dry-run."""

    workflow: str
    entries: list[PlanEntry]
    summary: PlanSummary
    diagnostics: list[Diagnostic] = field(default_factory=list)
