"""Workflow execution status types."""

from enum import Enum


class WorkflowStatus(str, Enum):
    """Workflow execution status.

    Distinguishes between perfect success, degraded completion, failure, and a
    human denial at an approval Gate.

    - SUCCESS: All nodes completed successfully without warnings
    - DEGRADED: Workflow completed but some nodes had warnings or non-fatal issues
    - FAILED: Workflow failed to complete due to errors
    - DENIED: A human denied an approval Gate (Task 125) — the run stopped cleanly
      BEFORE the gated node ran. A human verdict, not a failure: nothing broke.
      CLI exit code 3 (vs 1 for FAILED); trace trailer ``final_status: "denied"``.

    This model provides better observability than binary success/failure,
    allowing users to distinguish between "all perfect" and "completed with issues".
    """

    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
    DENIED = "denied"
