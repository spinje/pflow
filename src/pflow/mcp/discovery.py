"""MCP tool discovery for pflow."""

import asyncio
import logging
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .manager import MCPServerManager

logger = logging.getLogger(__name__)


class MCPDiscovery:
    """Discovers tools from MCP servers.

    This class connects to MCP servers and discovers their available tools,
    converting them to a format suitable for the pflow registry.
    """

    def __init__(self, manager: Optional[MCPServerManager] = None):
        """Initialize MCPDiscovery.

        Args:
            manager: MCP server manager instance. Creates default if not provided.
        """
        self.manager = manager or MCPServerManager()

    def discover_tools(self, server_name: str) -> list[dict[str, Any]]:
        """Discover tools from an MCP server (synchronous wrapper).

        Args:
            server_name: Name of the configured MCP server

        Returns:
            List of tool definitions with metadata

        Raises:
            ValueError: If server not found in configuration
            RuntimeError: If discovery fails
        """
        server_config = self.manager.get_server(server_name)

        if not server_config:
            available = ", ".join(self.manager.list_servers()) or "none"
            raise ValueError(f"MCP server '{server_name}' not found. Available servers: {available}")

        try:
            # Run async discovery in sync context
            return asyncio.run(self._discover_async(server_name, server_config))
        except Exception as e:
            logger.exception(f"Failed to discover tools from {server_name}")
            raise RuntimeError(f"Tool discovery failed for {server_name}: {e}") from e

    async def _discover_async(self, server_name: str, server_config: dict[str, Any]) -> list[dict[str, Any]]:
        """Async implementation of tool discovery with transport routing.

        Args:
            server_name: Name of the server
            server_config: Server configuration dictionary

        Returns:
            List of tool definitions
        """
        transport = server_config.get("transport", "stdio")

        if transport == "http":
            return await self._discover_async_http(server_name, server_config)
        elif transport == "stdio":
            return await self._discover_async_stdio(server_name, server_config)
        else:
            raise ValueError(f"Unsupported transport: {transport}")

    async def _discover_async_stdio(self, server_name: str, server_config: dict[str, Any]) -> list[dict[str, Any]]:
        """Stdio transport discovery implementation.

        Args:
            server_name: Name of the server
            server_config: Server configuration dictionary

        Returns:
            List of tool definitions
        """
        # Expand environment variables
        env_raw = self._expand_env_vars(server_config.get("env", {}))
        # Type assertion - we know env will be a dict after expansion
        env = env_raw if isinstance(env_raw, dict) else {}

        # Prepare server parameters
        params = StdioServerParameters(
            command=server_config["command"], args=server_config.get("args", []), env=env if env else None
        )

        logger.info(f"Connecting to MCP server '{server_name}'...")

        tools_list = []

        try:
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                # Initialize handshake
                await session.initialize()
                logger.debug(f"Initialized connection to {server_name}")

                # List available tools
                tools_response = await session.list_tools()

                for tool in tools_response.tools:
                    tool_def: dict[str, Any] = {
                        "name": tool.name,
                        "description": tool.description or f"MCP tool from {server_name}",
                        "server": server_name,
                    }

                    # Extract input schema
                    if hasattr(tool, "inputSchema") and tool.inputSchema:
                        schema = tool.inputSchema
                        if hasattr(schema, "model_dump"):
                            schema = schema.model_dump()
                        tool_def["inputSchema"] = dict(schema)
                    else:
                        tool_def["inputSchema"] = {"type": "object", "properties": {}, "required": []}

                    # Extract output schema if available
                    if hasattr(tool, "outputSchema") and tool.outputSchema:
                        schema = tool.outputSchema
                        if hasattr(schema, "model_dump"):
                            schema = schema.model_dump()
                        tool_def["outputSchema"] = dict(schema)

                    tools_list.append(tool_def)

                logger.info(f"Discovered {len(tools_list)} tools from {server_name}")

        except Exception:
            logger.exception("Error during tool discovery")
            raise

        return tools_list

    async def _discover_async_http(self, server_name: str, server_config: dict[str, Any]) -> list[dict[str, Any]]:
        """HTTP transport discovery implementation.

        Args:
            server_name: Name of the server
            server_config: Server configuration dictionary

        Returns:
            List of tool definitions
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        url = server_config.get("url")
        if not url:
            raise ValueError(f"HTTP transport requires 'url' in config for server {server_name}")

        # Build authentication headers
        headers = self._build_auth_headers(server_config)

        # Get timeout settings
        timeout = server_config.get("timeout", 30)
        sse_timeout = server_config.get("sse_timeout", 300)

        logger.info(f"Connecting to HTTP MCP server '{server_name}' at {url}...")

        tools_list = []

        try:
            async with (
                streamablehttp_client(url=url, headers=headers, timeout=timeout, sse_read_timeout=sse_timeout) as (
                    read,
                    write,
                    get_session_id,
                ),
                ClientSession(read, write) as session,
            ):
                # Initialize handshake
                await session.initialize()

                session_id = get_session_id()
                logger.debug(f"Initialized HTTP connection to {server_name}, session: {session_id}")

                # List available tools (same as stdio)
                tools_response = await session.list_tools()

                for tool in tools_response.tools:
                    tool_def: dict[str, Any] = {
                        "name": tool.name,
                        "description": tool.description or f"MCP tool from {server_name}",
                        "server": server_name,
                    }

                    # Extract input schema (same as stdio)
                    if hasattr(tool, "inputSchema") and tool.inputSchema:
                        schema = tool.inputSchema
                        if hasattr(schema, "model_dump"):
                            schema = schema.model_dump()
                        tool_def["inputSchema"] = dict(schema)
                    else:
                        tool_def["inputSchema"] = {"type": "object", "properties": {}, "required": []}

                    # Extract output schema if available (same as stdio)
                    if hasattr(tool, "outputSchema") and tool.outputSchema:
                        schema = tool.outputSchema
                        if hasattr(schema, "model_dump"):
                            schema = schema.model_dump()
                        tool_def["outputSchema"] = dict(schema)

                    tools_list.append(tool_def)

                logger.info(f"Discovered {len(tools_list)} tools from HTTP server {server_name}")

        except Exception:
            logger.exception(f"Error during HTTP discovery for {server_name}")
            raise

        return tools_list

    def _build_auth_headers(self, config: dict[str, Any]) -> dict[str, str]:
        """Build authentication headers from configuration.

        Args:
            config: Server configuration dictionary

        Returns:
            Dictionary of HTTP headers including authentication
        """
        from pflow.mcp.auth_utils import build_auth_headers

        return build_auth_headers(config)

    def discover_all_servers(self) -> dict[str, list[dict[str, Any]]]:
        """Discover tools from all configured MCP servers.

        Returns:
            Dictionary mapping server names to their tool lists
        """
        all_tools = {}
        servers = self.manager.list_servers()

        for server_name in servers:
            try:
                tools = self.discover_tools(server_name)
                all_tools[server_name] = tools
                logger.info(f"Discovered {len(tools)} tools from {server_name}")
            except Exception:
                logger.exception(f"Failed to discover tools from {server_name}")
                all_tools[server_name] = []  # Empty list for failed servers

        return all_tools

    def _expand_env_vars(self, data: dict | list | str | Any) -> dict | list | str | Any:
        """Expand environment variables in configuration recursively.

        Supports ${VAR} syntax for environment variable expansion.
        Now handles nested dictionaries and lists.

        Args:
            data: Any data structure potentially containing ${VAR} references

        Returns:
            Data with expanded environment variables
        """
        from pflow.mcp.auth_utils import expand_env_vars_nested

        return expand_env_vars_nested(data)

    def convert_to_pflow_params(self, json_schema: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert JSON Schema to pflow parameter format.

        Args:
            json_schema: JSON Schema from MCP tool

        Returns:
            List of parameter definitions for pflow registry
        """
        params: list[dict[str, Any]] = []

        if json_schema.get("type") != "object":
            return params

        properties = json_schema.get("properties", {})
        required = json_schema.get("required", [])

        for prop_name, prop_schema in properties.items():
            param = {
                "key": prop_name,  # Changed from "name" to "key" to match pflow convention
                "type": self._json_type_to_python(prop_schema.get("type", "str")),
                "required": prop_name in required,
            }

            # Add description if available
            if "description" in prop_schema:
                param["description"] = prop_schema["description"]

            # Add default if available
            if "default" in prop_schema:
                param["default"] = prop_schema["default"]

            # Add enum values if available
            if "enum" in prop_schema:
                param["enum"] = prop_schema["enum"]

            params.append(param)

        return params

    def _json_type_to_python(self, json_type: str | list[str]) -> str:
        """Convert JSON Schema type to Python type string.

        Args:
            json_type: JSON Schema type (can be string or list for union types)

        Returns:
            Python type string for pflow
        """
        type_map = {
            "string": "str",
            "number": "float",
            "integer": "int",
            "boolean": "bool",
            "array": "list",
            "object": "dict",
            "null": "None",
        }

        # Handle union types (e.g., ["string", "null"])
        if isinstance(json_type, list):
            # Filter out 'null' and take the first non-null type
            non_null_types = [t for t in json_type if t != "null"]
            if non_null_types:
                json_type = non_null_types[0]
            else:
                # All null, treat as optional
                return "None"

        return type_map.get(json_type, "str")
