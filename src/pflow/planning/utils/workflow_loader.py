"""Thin wrapper for WorkflowManager."""

from pflow.core.workflow_manager import WorkflowManager


def load_workflow(name: str) -> dict:
    """Load workflow metadata from disk by name.

    Thin wrapper around WorkflowManager - delegates all functionality.

    Args:
        name: Workflow name (kebab-case)

    Returns:
        Full workflow metadata dict including ir

    Raises:
        ValueError: If name is empty
        WorkflowNotFoundError: If workflow doesn't exist
    """
    if not name or not name.strip():
        raise ValueError("Workflow name cannot be empty")

    manager = WorkflowManager()
    return manager.load(name)  # Raises WorkflowNotFoundError if not found


def list_all_workflows() -> list[dict]:
    """List all available workflows.

    Returns:
        List of workflow metadata dicts
    """
    manager = WorkflowManager()
    return manager.list_all()
