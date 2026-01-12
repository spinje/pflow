"""MCP tool registration for pflow registry."""

import logging
from typing import Any, Optional

from pflow.registry import Registry

from .discovery import MCPDiscovery
from .manager import MCPServerManager

logger = logging.getLogger(__name__)


class MCPRegistrar:
    """Updates pflow registry with virtual MCP node entries.

    This class bridges MCP tool discovery with the pflow registry,
    creating virtual node entries that all point to the MCPNode class.
    """

    def __init__(
        self,
        registry: Optional[Registry] = None,
        manager: Optional[MCPServerManager] = None,
        discovery: Optional[MCPDiscovery] = None,
    ):
        """Initialize MCPRegistrar.

        Args:
            registry: Pflow registry instance. Creates default if not provided.
            manager: MCP server manager instance. Creates default if not provided.
            discovery: MCP discovery instance. Creates default if not provided.
        """
        self.registry = registry or Registry()
        self.manager = manager or MCPServerManager()
        self.discovery = discovery or MCPDiscovery(self.manager)
        self._settings_manager: Optional[Any] = None

    @property
    def settings_manager(self) -> Any:
        """Lazy load SettingsManager to avoid circular imports."""
        if self._settings_manager is None:
            from pflow.core.settings import SettingsManager

            self._settings_manager = SettingsManager()
        return self._settings_manager

    def register_tools(self, server_name: str, tools: list[dict[str, Any]]) -> None:
        """Register discovered tools in the registry.

        This is the method called by auto-discovery to register tools
        without re-discovering them.

        Args:
            server_name: Name of the MCP server
            tools: List of tool definitions discovered from the server
        """
        # Load complete registry (unfiltered) to avoid persisting a filtered subset
        nodes = self.registry.load(include_filtered=True)

        registered_count = 0
        filtered_count = 0

        for tool in tools:
            # Create node name following mcp-{server}-{tool} pattern
            node_name = f"mcp-{server_name}-{tool['name']}"

            # Check if node should be included based on settings
            if not self.settings_manager.should_include_node(node_name):
                filtered_count += 1
                logger.debug(f"Filtering out MCP tool '{node_name}' based on settings")
                # Remove from registry if it was previously registered
                if node_name in nodes:
                    del nodes[node_name]
                continue

            # Check if already exists
            if node_name in nodes:
                logger.debug(f"Updating existing registry entry for {node_name}")
            else:
                logger.debug(f"Creating new registry entry for {node_name}")

            # Create virtual registry entry
            nodes[node_name] = self._create_registry_entry(server_name, tool)
            registered_count += 1

        # Save updated registry
        self.registry.save(nodes)

        if filtered_count > 0:
            logger.info(f"Registered {registered_count} tools from {server_name} ({filtered_count} filtered out)")
        else:
            logger.info(f"Registered {registered_count} tools from {server_name}")

    def sync_server(self, server_name: str) -> dict[str, Any]:
        """Sync tools from an MCP server to the registry.

        This discovers all tools from the specified server and creates
        virtual registry entries for each one.

        Args:
            server_name: Name of the configured MCP server

        Returns:
            Summary of sync operation with counts
        """
        logger.info(f"Syncing MCP server '{server_name}'...")

        # Discover tools from server
        try:
            # Don't show server output during sync (not verbose)
            tools = self.discovery.discover_tools(server_name, verbose=False)
        except Exception as e:
            logger.exception("Failed to discover tools")
            return {"server": server_name, "tools_discovered": 0, "tools_registered": 0, "error": str(e)}

        # Load complete registry (unfiltered) to avoid persisting a filtered subset
        nodes = self.registry.load(include_filtered=True)

        registered_count = 0
        filtered_count = 0

        for tool in tools:
            # Create node name following mcp-{server}-{tool} pattern
            node_name = f"mcp-{server_name}-{tool['name']}"

            # Check if node should be included based on settings
            if not self.settings_manager.should_include_node(node_name):
                filtered_count += 1
                logger.debug(f"Filtering out MCP tool '{node_name}' based on settings")
                # Remove from registry if it was previously registered
                if node_name in nodes:
                    del nodes[node_name]
                continue

            # Check if already exists
            if node_name in nodes:
                logger.debug(f"Updating existing registry entry for {node_name}")
            else:
                logger.debug(f"Creating new registry entry for {node_name}")

            # Create virtual registry entry
            nodes[node_name] = self._create_registry_entry(server_name, tool)
            registered_count += 1

        # Save updated registry
        self.registry.save(nodes)

        if filtered_count > 0:
            logger.info(f"Registered {registered_count} tools from {server_name} ({filtered_count} filtered out)")
        else:
            logger.info(f"Registered {registered_count} tools from {server_name}")

        return {
            "server": server_name,
            "tools_discovered": len(tools),
            "tools_registered": registered_count,
            "tools_filtered": filtered_count,
        }

    def sync_all_servers(self) -> list[dict[str, Any]]:
        """Sync tools from all configured MCP servers.

        Returns:
            List of sync summaries for each server
        """
        results = []
        servers = self.manager.list_servers()

        logger.info(f"Syncing {len(servers)} MCP servers...")

        for server_name in servers:
            result = self.sync_server(server_name)
            results.append(result)

        total_registered = sum(r["tools_registered"] for r in results)
        logger.info(f"Sync complete: registered {total_registered} tools from {len(servers)} servers")

        return results

    def remove_server_tools(self, server_name: str) -> int:
        """Remove all registry entries for a specific MCP server.

        Args:
            server_name: Name of the MCP server

        Returns:
            Number of entries removed
        """
        # Load complete registry (unfiltered) to ensure removal even if tools are filtered
        nodes = self.registry.load(include_filtered=True)
        prefix = f"mcp-{server_name}-"

        # Find all nodes for this server
        to_remove = [node_name for node_name in nodes if node_name.startswith(prefix)]

        # Remove them
        for node_name in to_remove:
            del nodes[node_name]
            logger.debug(f"Removed registry entry: {node_name}")

        if to_remove:
            self.registry.save(nodes)
            logger.info(f"Removed {len(to_remove)} tools for server '{server_name}'")

        return len(to_remove)

    def _create_registry_entry(self, server_name: str, tool: dict[str, Any]) -> dict[str, Any]:
        """Create a registry entry for an MCP tool.

        Args:
            server_name: Name of the MCP server
            tool: Tool definition from discovery

        Returns:
            Registry entry dictionary
        """
        # Convert JSON Schema to pflow params
        params = []
        if "inputSchema" in tool:
            params = self.discovery.convert_to_pflow_params(tool["inputSchema"])

        # Create outputs if available
        outputs = []
        if "outputSchema" in tool:
            outputs = self.discovery.convert_to_pflow_params(tool["outputSchema"])

        # If no specific outputs, use generic result
        if not outputs:
            outputs = [
                {
                    "key": "result",  # Changed from "name" to "key" to match pflow convention
                    "type": "any",
                    "description": "Tool execution result",
                }
            ]

        # Create registry entry pointing to MCPNode
        entry = {
            "class_name": "MCPNode",
            "module": "pflow.nodes.mcp.node",
            "file_path": "virtual://mcp",  # Virtual path for MCP nodes
            "interface": {
                "description": tool.get("description", f"MCP tool from {server_name}"),
                "inputs": [],  # MCP tools don't read from shared store, only from params
                "params": params,
                "outputs": outputs,
                "actions": ["default"],  # Only default action (error handling via shared store)
                "mcp_metadata": {
                    "server": server_name,
                    "tool": tool["name"],
                    "original_schema": tool.get("inputSchema", {}),
                },
            },
        }

        return entry

    def list_registered_tools(self, server_name: Optional[str] = None) -> list[str]:
        """List all registered MCP tools in the registry.

        Args:
            server_name: Optional server name to filter by

        Returns:
            List of registered tool node names
        """
        nodes = self.registry.load()

        if server_name:
            prefix = f"mcp-{server_name}-"
            return [node_name for node_name in nodes if node_name.startswith(prefix)]
        else:
            # All MCP nodes
            return [node_name for node_name in nodes if node_name.startswith("mcp-")]

    def get_tool_info(self, node_name: str) -> Optional[dict[str, Any]]:
        """Get detailed information about a registered MCP tool.

        Args:
            node_name: Registry node name (e.g., "mcp-github-create-issue")

        Returns:
            Tool information or None if not found
        """
        nodes = self.registry.load()

        if node_name not in nodes:
            return None

        entry = nodes[node_name]

        # Extract server and tool from node name
        parts = node_name.split("-", 2)
        if len(parts) >= 3:
            server = parts[1]
            tool = "-".join(parts[2:])
        else:
            server = "unknown"
            tool = node_name

        return {
            "node_name": node_name,
            "server": server,
            "tool": tool,
            "description": entry.get("interface", {}).get("description", ""),
            "params": entry.get("interface", {}).get("params", []),
            "outputs": entry.get("interface", {}).get("outputs", []),
            "module": entry.get("module", ""),
            "class_name": entry.get("class_name", ""),
        }
