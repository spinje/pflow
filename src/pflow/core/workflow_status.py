"""Workflow execution status types."""

from enum import Enum


class WorkflowStatus(str, Enum):
    """Tri-state workflow execution status.

    Distinguishes between perfect success, degraded completion, and failure.

    - SUCCESS: All nodes completed successfully without warnings
    - DEGRADED: Workflow completed but some nodes had warnings or non-fatal issues
    - FAILED: Workflow failed to complete due to errors

    This tri-state model provides better observability than binary success/failure,
    allowing users to distinguish between "all perfect" and "completed with issues".
    """

    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
