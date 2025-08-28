"""MCP tool discovery for pflow."""

import asyncio
import logging
import os
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
        """Async implementation of tool discovery.

        Args:
            server_name: Name of the server
            server_config: Server configuration dictionary

        Returns:
            List of tool definitions
        """
        # Expand environment variables
        env = self._expand_env_vars(server_config.get("env", {}))

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

    def _expand_env_vars(self, env_dict: dict[str, str]) -> dict[str, str]:
        """Expand environment variables in configuration.

        Supports ${VAR} syntax for environment variable expansion.

        Args:
            env_dict: Dictionary with potential ${VAR} references

        Returns:
            Dictionary with expanded environment variables
        """
        import re

        expanded = {}
        pattern = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

        for key, value in env_dict.items():
            if isinstance(value, str):
                # Replace ${VAR} with environment variable value
                def replacer(match: Any) -> str:
                    env_var = match.group(1)
                    env_value = os.environ.get(env_var, "")
                    if not env_value:
                        logger.warning(f"Environment variable {env_var} not found, using empty string")
                    return env_value

                expanded[key] = pattern.sub(replacer, value)
            else:
                expanded[key] = value

        return expanded

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

    def _json_type_to_python(self, json_type: str) -> str:
        """Convert JSON Schema type to Python type string.

        Args:
            json_type: JSON Schema type

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

        return type_map.get(json_type, "str")
