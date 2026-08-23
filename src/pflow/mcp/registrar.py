"""MCP tool registration for pflow registry."""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from pflow.core.diagnostic import Diagnostic
from pflow.registry import Registry
from pflow.registry.constants import MCP_CANONICAL_OUTPUT

from .discovery import DEFAULT_DISCOVERY_TIMEOUT_SECONDS, MCPDiscovery
from .errors import describe_mcp_error
from .manager import MCPServerManager
from .sync_state import MCP_SERVER_FINGERPRINTS_KEY, fingerprint_server_configs, load_server_fingerprints

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServerSyncResult:
    """Outcome of one server discovery within a reconciliation batch."""

    server: str
    tools_discovered: int = 0
    tools_registered: int = 0
    tools_filtered: int = 0
    error: str | None = None
    diagnostic: Diagnostic | None = None


@dataclass(frozen=True)
class SyncBatchResult:
    """Outcome of one coherent MCP reconciliation attempt."""

    servers: list[ServerSyncResult]
    aborted_reason: str | None = None
    config_missing: bool = False


class MCPRegistrar:
    """Updates pflow registry with virtual MCP node entries.

    This class bridges MCP tool discovery with the pflow registry,
    creating virtual node entries that all point to the MCPNode class.
    """

    def __init__(
        self,
        registry: Registry | None = None,
        manager: MCPServerManager | None = None,
        discovery: MCPDiscovery | None = None,
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
        self._settings_manager: Any | None = None

    @property
    def settings_manager(self) -> Any:
        """Lazy load SettingsManager to avoid circular imports."""
        if self._settings_manager is None:
            from pflow.core.settings import SettingsManager

            self._settings_manager = SettingsManager()
        return self._settings_manager

    @staticmethod
    def get_server_owner(entry: dict[str, Any]) -> str | None:
        """Return an entry's exact canonical MCP server owner, if valid."""
        interface = entry.get("interface")
        if not isinstance(interface, dict):
            return None
        metadata = interface.get("mcp_metadata")
        if not isinstance(metadata, dict):
            return None
        owner = metadata.get("server")
        if not isinstance(owner, str) or not owner.strip():
            return None
        return owner

    @staticmethod
    def is_mcp_entry(node_name: str, entry: dict[str, Any]) -> bool:
        """Return whether an entry occupies the reserved MCP namespace."""
        return entry.get("type") == "mcp" or node_name.startswith("mcp-")

    @classmethod
    def full_reconciliation_removals(
        cls,
        nodes: dict[str, dict[str, Any]],
        configured_servers: set[str],
    ) -> list[str]:
        """Identify absent owners and unsupported entries for full reconciliation."""
        removals = []
        for node_name, entry in nodes.items():
            owner = cls.get_server_owner(entry)
            if (cls.is_mcp_entry(node_name, entry) and owner is None) or (
                owner is not None and owner not in configured_servers
            ):
                removals.append(node_name)
        return removals

    def _replace_server_tools(
        self,
        nodes: dict[str, dict[str, Any]],
        server_name: str,
        tools: list[dict[str, Any]],
    ) -> tuple[int, int]:
        """Replace one server's exact owned entries in an in-memory snapshot."""
        registered_count = 0
        filtered_count = 0
        replacements: dict[str, dict[str, Any]] = {}
        for tool in tools:
            node_name = f"mcp-{server_name}-{tool['name']}"
            if not self.settings_manager.should_include_node(node_name):
                filtered_count += 1
                logger.debug(f"Filtering out MCP tool '{node_name}' based on settings")
                continue
            replacements[node_name] = self._create_registry_entry(server_name, tool)
            registered_count += 1

        for node_name, entry in list(nodes.items()):
            if self.get_server_owner(entry) == server_name:
                del nodes[node_name]
        nodes.update(replacements)

        return registered_count, filtered_count

    def _discover_targets(
        self,
        targets: list[str],
        configs: dict[str, dict[str, Any]],
        *,
        verbose: bool,
        on_server_start: Callable[[str], None] | None,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[ServerSyncResult]]:
        """Discover targets without reading or writing registry state."""
        discovered_tools: dict[str, list[dict[str, Any]]] = {}
        results: list[ServerSyncResult] = []
        for server_name in targets:
            server_config = configs.get(server_name)
            if server_config is None:
                results.append(ServerSyncResult(server=server_name, error="Server is not configured"))
                continue
            if on_server_start:
                on_server_start(server_name)
            try:
                tools = self.discovery.discover_tools(
                    server_name,
                    verbose=verbose,
                    server_config=server_config,
                )
                discovered_tools[server_name] = tools
                results.append(ServerSyncResult(server=server_name, tools_discovered=len(tools)))
            except Exception as error:
                original = error.__cause__ if error.__cause__ else error
                diagnostic = describe_mcp_error(
                    original,
                    timeout=server_config.get("timeout", DEFAULT_DISCOVERY_TIMEOUT_SECONDS),
                )
                results.append(
                    ServerSyncResult(
                        server=server_name,
                        error=diagnostic.message,
                        diagnostic=diagnostic,
                    )
                )
        return discovered_tools, results

    @staticmethod
    def _configuration_changed(
        initial: dict[str, str],
        latest: dict[str, str],
        targets: list[str],
        *,
        reconcile_all: bool,
    ) -> bool:
        if reconcile_all:
            return latest != initial
        return any(latest.get(name) != initial.get(name) for name in targets)

    def _clean_full_reconciliation(
        self,
        nodes: dict[str, dict[str, Any]],
        configured_servers: set[str],
    ) -> None:
        """Remove absent canonical owners and unsupported reserved MCP entries."""
        for node_name in self.full_reconciliation_removals(nodes, configured_servers):
            del nodes[node_name]

    def _apply_successful_replacements(
        self,
        nodes: dict[str, dict[str, Any]],
        results: list[ServerSyncResult],
        discovered_tools: dict[str, list[dict[str, Any]]],
        fingerprints: dict[str, Any],
        initial_fingerprints: dict[str, str],
    ) -> list[ServerSyncResult]:
        """Apply successful server replacements to one in-memory snapshot."""
        final_results: list[ServerSyncResult] = []
        for result in results:
            tools = discovered_tools.get(result.server)
            if tools is None:
                final_results.append(result)
                continue
            try:
                # Build every replacement before removing the server's working entries.
                registered, filtered = self._replace_server_tools(nodes, result.server, tools)
            except Exception as error:
                diagnostic = describe_mcp_error(error)
                diagnostic.message = f"Could not build registry entries for '{result.server}': {diagnostic.message}"
                final_results.append(
                    ServerSyncResult(
                        server=result.server,
                        tools_discovered=len(tools),
                        error=diagnostic.message,
                        diagnostic=diagnostic,
                    )
                )
                continue
            fingerprints[result.server] = initial_fingerprints[result.server]
            final_results.append(
                ServerSyncResult(
                    server=result.server,
                    tools_discovered=len(tools),
                    tools_registered=registered,
                    tools_filtered=filtered,
                )
            )
        return final_results

    def sync_servers(
        self,
        server_names: Iterable[str] | None,
        *,
        reconcile_all: bool,
        verbose: bool = False,
        on_server_start: Callable[[str], None] | None = None,
    ) -> SyncBatchResult:
        """Discover target servers, then publish one coherent reconciliation."""
        initial_configs = self.manager.get_all_servers_if_configured()
        if initial_configs is None:
            return SyncBatchResult([], config_missing=True)
        targets = list(initial_configs) if server_names is None else list(server_names)
        initial_fingerprints = fingerprint_server_configs(initial_configs)
        discovered_tools, results = self._discover_targets(
            targets,
            initial_configs,
            verbose=verbose,
            on_server_start=on_server_start,
        )

        latest_configs = self.manager.get_all_servers_if_configured()
        if latest_configs is None:
            return SyncBatchResult(
                servers=results,
                aborted_reason="MCP configuration was removed during discovery; no registry updates were published.",
                config_missing=True,
            )
        latest_fingerprints = fingerprint_server_configs(latest_configs)
        if self._configuration_changed(
            initial_fingerprints,
            latest_fingerprints,
            targets,
            reconcile_all=reconcile_all,
        ):
            return SyncBatchResult(
                servers=results,
                aborted_reason="MCP configuration changed during discovery; no registry updates were published. Retry sync.",
            )

        nodes = self.registry.load(include_filtered=True)
        original_nodes = dict(nodes)
        stored_fingerprints, fingerprints_valid = load_server_fingerprints(self.registry)
        final_fingerprints = dict(stored_fingerprints)

        if reconcile_all:
            configured_servers = set(latest_configs)
            self._clean_full_reconciliation(nodes, configured_servers)
            final_fingerprints = {
                name: fingerprint for name, fingerprint in final_fingerprints.items() if name in configured_servers
            }

        final_results = self._apply_successful_replacements(
            nodes,
            results,
            discovered_tools,
            final_fingerprints,
            initial_fingerprints,
        )

        metadata_changed = not fingerprints_valid or final_fingerprints != stored_fingerprints
        registry_updated = nodes != original_nodes or metadata_changed
        if registry_updated:
            self.registry.save(
                nodes,
                metadata_updates={MCP_SERVER_FINGERPRINTS_KEY: final_fingerprints},
            )

        return SyncBatchResult(servers=final_results)

    def remove_server_tools(self, server_name: str) -> int:
        """Remove all registry entries for a specific MCP server.

        Args:
            server_name: Name of the MCP server

        Returns:
            Number of entries removed
        """
        nodes = self.registry.load(include_filtered=True)
        to_remove = [node_name for node_name, entry in nodes.items() if self.get_server_owner(entry) == server_name]
        for node_name in to_remove:
            del nodes[node_name]
            logger.debug(f"Removed registry entry: {node_name}")

        fingerprints, _ = load_server_fingerprints(self.registry)
        fingerprint_removed = server_name in fingerprints
        fingerprints.pop(server_name, None)

        if to_remove or fingerprint_removed:
            self.registry.save(nodes, metadata_updates={MCP_SERVER_FINGERPRINTS_KEY: fingerprints})
        if to_remove:
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

        # Add pflow-level MCPNode params (not part of tool's inputSchema).
        # MCPNode.prep() strips timeout from tool_args before calling the server.
        params.append({
            "key": "timeout",
            "type": "int",
            "required": False,
            "description": "Timeout in seconds for tool execution (default: 30)",
        })

        # MCPNode stores every successful tool response under one canonical
        # ``result`` output. Keep it open-ended even when outputSchema exists:
        # server schemas may be absent or shallow, while probe can inspect the
        # actual response and advertise every path that really resolves.
        outputs = [MCP_CANONICAL_OUTPUT.copy()]

        # Create registry entry pointing to MCPNode
        entry = {
            "class_name": "MCPNode",
            "module": "pflow.nodes.mcp.node",
            "file_path": "virtual://mcp",  # Virtual path for MCP nodes
            "type": "mcp",  # Mirrors core/user nodes — keeps the data self-describing
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
                    "output_schema": tool.get("outputSchema", {}),
                },
            },
        }

        return entry

    def list_registered_tools(
        self,
        server_name: str | None = None,
        *,
        include_filtered: bool = False,
    ) -> list[str]:
        """List all registered MCP tools in the registry.

        Args:
            server_name: Optional server name to filter by
            include_filtered: Include settings-filtered persisted entries.

        Returns:
            List of registered tool node names
        """
        nodes = self.registry.load(include_filtered=include_filtered)

        if server_name is not None:
            return [node_name for node_name, entry in nodes.items() if self.get_server_owner(entry) == server_name]
        return [node_name for node_name, entry in nodes.items() if self.get_server_owner(entry) is not None]

    def get_tool_info(self, node_name: str) -> dict[str, Any] | None:
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
        interface = entry.get("interface", {})
        mcp_metadata = interface.get("mcp_metadata", {})

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
            "description": interface.get("description", ""),
            "params": interface.get("params", []),
            "outputs": interface.get("outputs", []),
            "output_schema": mcp_metadata.get("output_schema", {}),
            "module": entry.get("module", ""),
            "class_name": entry.get("class_name", ""),
        }
