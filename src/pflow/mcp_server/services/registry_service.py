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
    def search_nodes(cls, pattern: str) -> str:
        """Search for nodes by pattern.

        Returns formatted text table (CLI parity) instead of raw JSON.
        Uses same search algorithm as CLI for consistent ordering and scoring.

        Args:
            pattern: Search pattern

        Returns:
            Formatted markdown string with search results
        """
        registry = Registry()  # Fresh instance

        # Use Registry's search method (same as CLI) for consistency
        results = registry.search(pattern)

        # Transform results for shared formatter
        # Registry.search returns: list of (name, data, score) tuples
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

        # Format using shared formatter (CLI's text mode)
        from pflow.execution.formatters.registry_search_formatter import format_search_results

        return format_search_results(pattern, matches)

    @classmethod
    @ensure_stateless
    def list_all_nodes(cls) -> str:
        """List all available nodes.

        Returns formatted markdown text (CLI parity) instead of raw JSON.

        Returns:
            Formatted markdown string with nodes grouped by package
        """
        registry = Registry()  # Fresh instance
        nodes_data = registry.load()

        # Format using shared formatter (CLI's text mode)
        from pflow.execution.formatters.registry_list_formatter import format_registry_list

        return format_registry_list(nodes_data)
