"""Manages all workflow execution display operations."""

from dataclasses import dataclass
from typing import Optional

from pflow.core.workflow.status import WorkflowStatus

from .output_interface import OutputInterface


@dataclass
class DisplayManager:
    """Manages all workflow execution display operations.

    This class encapsulates all UX logic for displaying workflow execution
    progress, results, and errors. It uses the OutputInterface to remain
    display-backend agnostic.
    """

    output: OutputInterface

    def show_execution_start(self, node_count: int) -> None:
        """Show workflow execution starting.

        Args:
            node_count: Number of nodes in the workflow
        """
        self.output.show_progress(f"Executing workflow ({node_count} nodes):")

    def show_node_progress(self, node_id: str, status: str, duration: float = 0) -> None:
        """Show individual node progress.

        Args:
            node_id: The ID of the node
            status: Status of the node ("cached", "success", "error")
            duration: Execution duration in seconds
        """
        if status == "cached":
            self.output.show_progress(f"  {node_id}... ↻ cached")
        elif status == "success":
            self.output.show_progress(f"  {node_id}... ✓ {duration:.1f}s")
        elif status == "error":
            self.output.show_progress(f"  {node_id}... ✗ Failed", is_error=True)

    def show_execution_result(
        self, success: bool, status: Optional[WorkflowStatus] = None, data: Optional[str] = None
    ) -> None:
        """Show final execution result with tri-state status.

        Args:
            success: Whether the execution was successful (backward compatibility)
            status: Optional tri-state workflow status (SUCCESS/DEGRADED/FAILED)
            data: Optional output data to display (unused - handlers display data)
        """
        # Use status if provided, otherwise fall back to boolean success
        if status == WorkflowStatus.SUCCESS:
            self.output.show_success("Workflow executed successfully")
        elif status == WorkflowStatus.DEGRADED:
            self.output.show_warning("Workflow completed with warnings")
        elif status == WorkflowStatus.FAILED:
            self.output.show_error("Workflow execution failed")
        else:
            # Fallback to boolean success for backward compatibility
            if success:
                self.output.show_success("Workflow executed successfully")
            else:
                self.output.show_error("Workflow execution failed")
        # Note: data output is handled by CLI handlers, not here

    def show_progress(self, message: str) -> None:
        """Show general progress message.

        Args:
            message: Progress message to display
        """
        self.output.show_progress(message)
