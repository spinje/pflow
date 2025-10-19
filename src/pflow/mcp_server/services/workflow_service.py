"""Workflow service for MCP server.

Provides workflow listing and metadata retrieval.
All operations are stateless with fresh WorkflowManager instances.
"""

import logging

from pflow.core.workflow_manager import WorkflowManager

from .base_service import BaseService, ensure_stateless

logger = logging.getLogger(__name__)


class WorkflowService(BaseService):
    """Service for workflow management operations.

    Provides workflow listing and metadata retrieval.
    All operations are stateless with fresh WorkflowManager instances.
    """

    @classmethod
    @ensure_stateless
    def list_workflows(cls, filter_pattern: str | None = None) -> str:
        """List saved workflows with optional filtering.

        Returns formatted markdown text (CLI parity) instead of raw JSON.

        Args:
            filter_pattern: Optional pattern to filter workflows

        Returns:
            Formatted markdown string with workflow list
        """
        manager = WorkflowManager()  # Fresh instance
        all_workflows = manager.list_all()

        # Track original count for better messaging
        total_count = len(all_workflows)

        # Apply filter if provided (and if it's a string)
        if filter_pattern and isinstance(filter_pattern, str):
            # Split filter into keywords and check that ALL keywords match (AND logic)
            keywords = [k.strip().lower() for k in filter_pattern.split() if k.strip()]
            workflows = [
                w
                for w in all_workflows
                if all(
                    keyword in w.get("name", "").lower() or keyword in w.get("description", "").lower()
                    for keyword in keywords
                )
            ]

            # Custom message when filter excludes everything but workflows exist
            if not workflows and total_count > 0:
                plural = "workflow" if total_count == 1 else "workflows"
                return f"""No workflows match filter: '{filter_pattern}'

Found {total_count} total {plural}. Try:
  - Broader keywords: Remove some filter terms
  - Discovery: Use workflow_discover for intelligent search (Recommended)
  - List all: Remove filter_pattern parameter
"""
        else:
            workflows = all_workflows

        # Format using shared formatter (CLI's text mode)
        from pflow.execution.formatters.workflow_list_formatter import format_workflow_list

        return format_workflow_list(workflows)

    @classmethod
    @ensure_stateless
    def describe_workflow(cls, name: str) -> str:
        """Get workflow interface specification.

        Returns formatted markdown text showing workflow interface
        (inputs, outputs, example usage). Uses shared formatter for
        perfect CLI parity.

        Args:
            name: Workflow name

        Returns:
            Formatted interface specification

        Raises:
            ValueError: If workflow not found (includes suggestions)
        """
        manager = WorkflowManager()  # Fresh instance

        # Check if workflow exists
        if not manager.exists(name):
            # Get suggestions for similar workflows
            all_workflows = manager.list_all()
            all_names = [w["name"] for w in all_workflows]

            from pflow.core.suggestion_utils import format_did_you_mean

            suggestion = format_did_you_mean(name, all_names, item_type="workflow")
            error_msg = f"Workflow '{name}' not found."
            if suggestion:
                error_msg += f"\n{suggestion}"
            raise ValueError(error_msg)

        # Load workflow metadata
        metadata = manager.load(name)

        # Format using shared formatter (same as CLI)
        from pflow.execution.formatters.workflow_describe_formatter import format_workflow_interface

        return format_workflow_interface(name, metadata)
