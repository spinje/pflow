"""Result types for workflow execution and validation."""

from dataclasses import dataclass, field
from typing import Any, Optional

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
    only_node: Optional[str] = None


@dataclass(frozen=True)
class ResolvedWorkflow:
    """Result of workflow resolution.

    Returned by resolve_workflow(). The Runner reads file_path
    for _inject_workflow_file_path() -- callers never set this.
    """

    ir: dict[str, Any]
    source: str  # "file", "library", "content", "direct"
    file_path: Optional[str] = None  # Absolute path for file/library, None for content/direct


@dataclass
class ValidationResult:
    """Result of runner.validate()."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    # warnings shape: {"node_id": str, "message": str, "template": str | None}


@dataclass
class ExecutionResult:
    """Result of workflow execution."""

    success: bool
    status: WorkflowStatus = WorkflowStatus.SUCCESS
    shared_after: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    validation_warnings: list[dict[str, Any]] = field(default_factory=list)
    trace: Optional[Any] = None  # WorkflowTraceCollector | None
    metrics: Optional[Any] = None  # MetricsCollector | None
