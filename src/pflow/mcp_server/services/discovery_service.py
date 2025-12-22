"""Discovery service for MCP server.

This service wraps the planning nodes (WorkflowDiscoveryNode and
ComponentBrowsingNode) to provide intelligent discovery capabilities.
"""

import logging
from datetime import datetime

from .base_service import BaseService, ensure_stateless

logger = logging.getLogger(__name__)


class DiscoveryService(BaseService):
    """Service for workflow and component discovery.

    Uses planning nodes directly for LLM-powered intelligent discovery.
    Maintains stateless pattern with fresh instances per request.
    """

    @classmethod
    @ensure_stateless
    def discover_workflows(cls, query: str) -> str:
        """Discover existing workflows matching a query.

        Uses WorkflowDiscoveryNode for intelligent LLM-based matching.

        Args:
            query: Natural language description of desired workflow

        Returns:
            Markdown formatted string with discovery results (same as CLI)
        """
        from pflow.core.llm_config import get_model_for_feature
        from pflow.core.workflow_manager import WorkflowManager
        from pflow.planning.nodes import WorkflowDiscoveryNode

        # Create fresh instances (CRITICAL for stateless pattern)
        node = WorkflowDiscoveryNode()
        workflow_manager = WorkflowManager()

        # Set model via params (PocketFlow convention)
        discovery_model = get_model_for_feature("discovery")
        node.params["model"] = discovery_model

        # Build context for discovery node
        shared = {
            "user_input": query,
            "workflow_manager": workflow_manager,
        }

        # Run discovery
        logger.debug(f"Running workflow discovery for: {query} with model: {discovery_model}")
        action = node.run(shared)

        # Extract results from shared store
        result = shared.get("discovery_result")
        workflow = shared.get("found_workflow")

        # Format using shared formatter (same as CLI)
        if action == "found_existing" and workflow and result:
            from pflow.execution.formatters.discovery_formatter import format_discovery_result

            # Type narrow for formatter
            if not isinstance(result, dict) or not isinstance(workflow, dict):
                raise TypeError("Invalid discovery result format")

            logger.info("Workflow discovery found a match")
            formatted = format_discovery_result(result, workflow)
            return formatted
        else:
            # No match found - show available workflows as suggestions
            from pflow.execution.formatters.discovery_formatter import format_no_matches_with_suggestions

            logger.info("Workflow discovery found no matches")
            all_workflows = workflow_manager.list_all()

            # Get reasoning from discovery result if available
            reasoning: str | None = None
            if result and isinstance(result, dict):
                reasoning_value = result.get("reasoning")
                if reasoning_value is not None and not isinstance(reasoning_value, str):
                    raise TypeError(f"Expected reasoning to be str, got {type(reasoning_value)}")
                reasoning = reasoning_value

            formatted = format_no_matches_with_suggestions(all_workflows, query, reasoning=reasoning)
            return formatted

    @classmethod
    @ensure_stateless
    def discover_components(cls, task: str) -> str:
        """Discover components (nodes) for building workflows.

        Uses ComponentBrowsingNode for intelligent LLM-based selection.

        Args:
            task: Description of what needs to be built

        Returns:
            Markdown formatted string with selected components (same as CLI)
        """
        from pflow.core.llm_config import get_model_for_feature
        from pflow.core.workflow_manager import WorkflowManager
        from pflow.planning.nodes import ComponentBrowsingNode

        # Create fresh instances
        node = ComponentBrowsingNode()
        workflow_manager = WorkflowManager()

        # Set model via params (PocketFlow convention)
        discovery_model = get_model_for_feature("discovery")
        node.params["model"] = discovery_model

        # Build context for browsing node
        shared = {
            "user_input": task,
            "workflow_manager": workflow_manager,
            "current_date": datetime.now().strftime("%Y-%m-%d"),
            "cache_planner": False,  # Disable caching for MCP
        }

        # Run component discovery
        logger.debug(f"Running component discovery for: {task} with model: {discovery_model}")
        action = node.run(shared)

        # Extract planning context (markdown formatted)
        planning_context = shared.get("planning_context", "")

        # Type narrow to ensure it's a string
        if not isinstance(planning_context, str):
            raise TypeError(f"Expected planning_context to be str, got {type(planning_context)}")

        logger.info(f"Component discovery completed with action: {action}")

        # Return markdown directly (same as CLI: click.echo(shared["planning_context"]))
        return planning_context
