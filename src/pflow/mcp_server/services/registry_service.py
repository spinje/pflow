"""Registry service for MCP server.

Provides node discovery, search, and description capabilities.
All operations are stateless with fresh Registry instances.
"""

import logging

from pflow.registry import Registry

from .base_service import BaseService, ensure_stateless

logger = logging.getLogger(__name__)


class RegistryService(BaseService):
    """Service for registry operations.

    Provides node discovery, search, and description capabilities.
    All operations are stateless with fresh Registry instances.
    """

    @classmethod
    @ensure_stateless
    def describe_nodes(cls, node_ids: list[str]) -> str:
        """Get detailed specs for specific nodes.

        Returns formatted markdown with structure examples and template paths
        (same as CLI's registry describe command).

        Args:
            node_ids: List of node IDs to describe

        Returns:
            Formatted markdown description with structure and available paths
        """
        from pflow.planning.context_builder import build_planning_context

        # Load registry
        registry = Registry()  # Fresh instance
        registry_metadata = registry.load()

        # Validate all node IDs exist
        missing = [nid for nid in node_ids if nid not in registry_metadata]
        if missing:
            return f"Error: Nodes not found: {', '.join(missing)}"

        # Use same function as CLI for perfect parity
        try:
            context = build_planning_context(
                selected_node_ids=node_ids,
                selected_workflow_names=[],
                registry_metadata=registry_metadata,
            )
            # Handle error dict return (when nodes are missing)
            if isinstance(context, dict):
                error_msg = context.get("error", "Unknown error")
                return f"Error: {error_msg}"
            return context
        except Exception as e:
            return f"Error building node details: {e}"

    @classmethod
    @ensure_stateless
    def list_all_nodes(cls, filter_pattern: str | None = None) -> str:
        """List available nodes, optionally filtered by pattern.

        Without filter: Returns all nodes grouped by package.
        With filter: Returns matching nodes sorted by relevance.

        Args:
            filter_pattern: Optional filter pattern (space-separated keywords use AND logic)

        Returns:
            Formatted markdown string with nodes (grouped or filtered)
        """
        registry = Registry()  # Fresh instance

        # If filter provided, use search (relevance-sorted)
        if filter_pattern:
            results = registry.search(filter_pattern)

            # Transform results for shared formatter (same as CLI)
            matches = []
            for name, data, score in results:
                # Determine match type from score (same logic as CLI)
                if score == 100:
                    match_type = "exact"
                elif score == 90:
                    match_type = "prefix"
                elif score >= 70:
                    match_type = "node_id"
                else:
                    match_type = "description"

                matches.append({
                    "node_id": name,
                    "description": data.get("interface", {}).get("description", ""),
                    "match_type": match_type,
                    "metadata": data,
                })

            # Format using shared search formatter
            from pflow.execution.formatters.registry_search_formatter import format_search_results

            return format_search_results(filter_pattern, matches)
        else:
            # No filter - show all grouped by package (current behavior)
            nodes_data = registry.load()

            # Format using shared list formatter
            from pflow.execution.formatters.registry_list_formatter import format_registry_list

            return format_registry_list(nodes_data)
