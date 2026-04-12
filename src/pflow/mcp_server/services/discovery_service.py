"""Discovery service for MCP server.

This service wraps the discovery functions to provide intelligent
workflow and component discovery capabilities.
"""

import logging

from .base_service import BaseService, ensure_stateless

logger = logging.getLogger(__name__)


class DiscoveryService(BaseService):
    """Service for workflow and component discovery.

    Uses discovery functions for LLM-powered intelligent discovery.
    Maintains stateless pattern with fresh instances per request.
    """

    @classmethod
    @ensure_stateless
    def discover_workflows(cls, query: str) -> str:
        """Discover existing workflows matching a query.

        Args:
            query: Natural language description of desired workflow

        Returns:
            Markdown formatted string with discovery results (same as CLI)
        """
        from pflow.core.workflow.discovery import find_workflow
        from pflow.core.workflow.manager import WorkflowManager

        # Fresh instance (CRITICAL for stateless pattern) — reused for both calls
        workflow_manager = WorkflowManager()
        result = find_workflow(query, workflow_manager=workflow_manager)

        # Format using shared formatter (same as CLI)
        if result.found and result.workflow:
            from pflow.execution.formatters.discovery_formatter import format_discovery_result

            result_dict = {
                "workflow_name": result.workflow_name,
                "confidence": result.confidence,
                "reasoning": result.reasoning,
            }
            logger.info("Workflow discovery found a match")
            return format_discovery_result(result_dict, result.workflow)
        else:
            from pflow.execution.formatters.discovery_formatter import format_no_matches_with_suggestions

            logger.info("Workflow discovery found no matches")
            all_workflows = workflow_manager.list_all()
            return format_no_matches_with_suggestions(all_workflows, query, reasoning=result.reasoning)

    @classmethod
    @ensure_stateless
    def discover_components(cls, task: str) -> str:
        """Discover components (nodes) for building workflows.

        Args:
            task: Description of what needs to be built

        Returns:
            Markdown formatted string with selected components (same as CLI)
        """
        from pflow.registry.discovery import find_components

        # Run component discovery
        logger.debug(f"Running component discovery for: {task}")
        result = find_components(task)

        logger.info(f"Component discovery completed, selected {len(result.node_ids)} nodes")

        # Return markdown directly (same as CLI)
        return result.component_context
