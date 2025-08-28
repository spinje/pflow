"""Universal MCP node that executes any MCP tool via virtual registry entries."""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from pocketflow import Node

logger = logging.getLogger(__name__)


class MCPNode(Node):
    """Universal MCP node that executes any MCP tool.

    This node is instantiated for all MCP tools discovered via `pflow mcp sync`.
    The specific server and tool are injected via special parameters by the compiler.

    ## Implementation Details

    The MCPNode works with virtual registry entries - multiple registry entries
    all point to this same MCPNode class, with the compiler injecting metadata
    to identify which specific MCP tool to execute.

    ## Special Parameters

    The compiler injects these special parameters:
    - `__mcp_server__`: Name of the MCP server (e.g., "github")
    - `__mcp_tool__`: Name of the tool to execute (e.g., "create-issue")

    ## Async-to-Sync Wrapper

    The MCP SDK is async-only, but pflow nodes are synchronous. This node uses
    `asyncio.run()` to bridge this gap, creating a new event loop for each execution.

    ## Example

    Registry entry for `mcp-github-create-issue`:
    ```json
    {
        "mcp-github-create-issue": {
            "class_name": "MCPNode",
            "module": "pflow.nodes.mcp.node",
            "file_path": "virtual://mcp",
            "interface": {
                "description": "Create a GitHub issue",
                "params": [...],
                "outputs": [...]
            }
        }
    }
    ```

    When executed, the compiler injects:
    - `__mcp_server__`: "github"
    - `__mcp_tool__`: "create-issue"
    """

    def __init__(self) -> None:
        """Initialize MCPNode with retry capability."""
        # CRITICAL: Only ONE attempt (max_retries=1) because each retry
        # starts a NEW MCP server subprocess, causing:
        # 1. Multiple server processes running simultaneously
        # 2. Resource conflicts and race conditions
        # 3. "unhandled errors in a TaskGroup" exceptions
        # Note: max_retries=1 means 1 total attempt (no retries)
        # TODO: Future improvement would be to cache and reuse server connections
        super().__init__(max_retries=1, wait=0)
        self._server_config: Optional[dict[str, Any]] = None
        self._timeout: int = 60  # Increased timeout for slow servers like Slack

    def prep(self, shared: dict) -> dict:
        """Prepare MCP tool execution.

        Args:
            shared: Shared store for inter-node communication

        Returns:
            Preparation results containing server, tool, config, and arguments
        """
        # Get server and tool from compiler-injected special parameters
        server = self.params.get("__mcp_server__")
        tool = self.params.get("__mcp_tool__")

        if not server or not tool:
            raise ValueError(
                f"MCP node requires __mcp_server__ and __mcp_tool__ parameters. "
                f"Got server={server}, tool={tool}. "
                f"These should be injected by the compiler for virtual MCP nodes."
            )

        # Load server configuration
        config = self._load_server_config(server)

        # Extract user parameters (exclude special __ parameters)
        # IMPORTANT: MCPNode is universal and server-agnostic!
        # It passes parameters directly to ANY MCP server without modification.
        # Never add server-specific logic here - this node must work with:
        # - filesystem servers (with their path restrictions)
        # - GitHub servers (no paths at all)
        # - Slack servers (channel IDs instead of paths)
        # - Any future MCP server without code changes
        tool_args = {k: v for k, v in self.params.items() if not k.startswith("__")}

        # Get optional timeout from params
        self._timeout = self.params.get("timeout", 30)

        logger.debug(
            "Preparing MCP tool execution", extra={"mcp_server": server, "mcp_tool": tool, "tool_args": tool_args}
        )

        return {"server": server, "tool": tool, "config": config, "arguments": tool_args}

    def exec(self, prep_res: dict) -> dict:
        """Execute MCP tool using async-to-sync wrapper.

        Args:
            prep_res: Preparation results from prep()

        Returns:
            Execution results with tool output or error
        """
        logger.info(
            f"Executing MCP tool: {prep_res['server']}:{prep_res['tool']}",
            extra={"tool_arguments": prep_res["arguments"]},
        )

        # NO try/except here - let exceptions bubble up for PocketFlow retry mechanism!
        # Run async code in sync context using asyncio.run()
        # This creates a new event loop for each execution
        result = asyncio.run(self._exec_async(prep_res), debug=False)
        return result

    async def _exec_async(self, prep_res: dict) -> dict:
        """Async implementation using MCP SDK.

        Args:
            prep_res: Preparation results containing server, tool, config, arguments

        Returns:
            Tool execution results
        """
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        config = prep_res["config"]

        # Expand environment variables in config
        env = self._expand_env_vars(config.get("env", {}))

        # Prepare server parameters
        params = StdioServerParameters(command=config["command"], args=config.get("args", []), env=env if env else None)

        # Execute with timeout
        async with asyncio.timeout(self._timeout):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    # Initialize handshake (required by MCP protocol)
                    await session.initialize()

                    # Call the tool
                    logger.debug(f"Calling MCP tool: {prep_res['tool']} with args: {prep_res['arguments']}")
                    result = await session.call_tool(prep_res["tool"], prep_res["arguments"])

                    # Extract content from result
                    # MCP returns results as content blocks (text, image, etc.)
                    extracted_result = self._extract_result(result)

                    return {"result": extracted_result}

    def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        """Store results in shared store and determine next action.

        With structured content support, this method handles:
        1. Protocol errors (exec_res["error"])
        2. Tool errors (result with is_tool_error flag)
        3. Structured data (dict results from outputSchema)
        4. Legacy unstructured results (strings, lists)

        Args:
            shared: Shared store for inter-node communication
            prep_res: Preparation results
            exec_res: Execution results

        Returns:
            Action string for workflow transition (always "default" for now)
        """
        # Check for protocol/execution errors
        if "error" in exec_res:
            # Store error in shared store
            shared["error"] = exec_res["error"]
            shared["error_details"] = {
                "server": prep_res["server"],
                "tool": prep_res["tool"],
                "timeout": exec_res.get("timeout", False),
            }
            logger.error(f"MCP tool failed: {exec_res['error']}", extra=shared["error_details"])
            # WORKAROUND: Return "default" instead of "error" because the planner
            # doesn't generate error handling edges in workflows. This prevents
            # "Flow ends: 'error' not found" crashes. The error is still stored
            # in shared["error"] for downstream nodes to handle.
            return "default"

        # Get the result
        result = exec_res.get("result")

        # Check for tool-level errors (from isError flag)
        if isinstance(result, dict) and result.get("is_tool_error"):
            shared["error"] = result.get("error", "Tool execution failed")
            shared["error_details"] = {"server": prep_res["server"], "tool": prep_res["tool"], "is_tool_error": True}
            logger.warning(f"MCP tool returned error: {shared['error']}", extra=shared["error_details"])
            # Still return "default" due to planner limitation
            return "default"

        # Store successful result
        shared["result"] = result

        # For structured data from outputSchema, extract top-level fields
        # This makes individual fields directly accessible in the shared store
        if isinstance(result, dict) and not result.get("error"):
            # Extract non-private fields to shared store for easier access
            extracted_fields = []
            for key, value in result.items():
                if not key.startswith("_") and not key.startswith("is_"):
                    # Skip private fields and internal flags
                    shared[key] = value
                    extracted_fields.append(key)

            if extracted_fields:
                logger.debug(
                    "Extracted structured fields to shared store",
                    extra={"fields": extracted_fields, "server": prep_res["server"], "tool": prep_res["tool"]},
                )

        # Store result with server-specific key
        # This allows multiple MCP tools in same workflow
        result_key = f"{prep_res['server']}_{prep_res['tool']}_result"
        shared[result_key] = result

        logger.info(
            "MCP tool completed successfully",
            extra={
                "server": prep_res["server"],
                "tool": prep_res["tool"],
                "result_type": type(result).__name__,
                "is_structured": isinstance(result, dict),
                "result_keys": ["result", result_key],
            },
        )

        return "default"

    def exec_fallback(self, prep_res: dict, exc: Exception) -> dict:
        """Handle execution failures gracefully after all retries exhausted.

        Args:
            prep_res: Preparation results
            exc: Exception that occurred during execution

        Returns:
            Error information dictionary
        """
        # Extract the actual error from nested ExceptionGroups if present
        actual_error = str(exc)
        exc_str = str(exc)

        # Handle ExceptionGroup wrapping
        if "ExceptionGroup" in str(type(exc)) or "unhandled errors in a TaskGroup" in exc_str:
            # Try to extract the actual MCP error message
            if "users cache is not ready yet" in exc_str:
                actual_error = "Slack server is still initializing its user cache (this can take 10-20 seconds). Please wait and try again."
            elif "McpError:" in exc_str:
                # Extract the actual error message from the MCP error
                import re

                match = re.search(r"McpError: (.+?)(?:\n|$)", exc_str)
                if match:
                    actual_error = match.group(1)
            else:
                # Try to find any meaningful error message in the exception
                import re

                # Look for common error patterns
                patterns = [
                    r'error": "([^"]+)"',  # JSON error field
                    r'message": "([^"]+)"',  # JSON message field
                    r"McpError: (.+?)(?:\n|$)",  # MCP error
                ]
                for pattern in patterns:
                    match = re.search(pattern, exc_str)
                    if match:
                        actual_error = match.group(1)
                        break
        elif isinstance(exc, asyncio.TimeoutError):
            actual_error = f"MCP tool timed out after {self._timeout} seconds"

        error_msg = f"MCP tool failed: {actual_error}"
        logger.error(
            error_msg,
            extra={
                "server": prep_res.get("server"),
                "tool": prep_res.get("tool"),
                "exception_type": type(exc).__name__,
                "full_exception": exc_str[:500],  # Log first 500 chars for debugging
            },
            exc_info=True,  # This will log the full traceback
        )

        return {"error": error_msg, "exception_type": type(exc).__name__}

    def _load_server_config(self, server_name: str) -> dict:
        """Load MCP server configuration from ~/.pflow/mcp-servers.json.

        Args:
            server_name: Name of the MCP server

        Returns:
            Server configuration dictionary

        Raises:
            FileNotFoundError: If configuration file doesn't exist
            KeyError: If server not found in configuration
        """
        config_path = Path("~/.pflow/mcp-servers.json").expanduser()

        if not config_path.exists():
            raise FileNotFoundError(
                f"MCP server configuration not found at {config_path}. "
                f"Run 'pflow mcp add {server_name}' to configure the server."
            )

        with open(config_path) as f:
            config = json.load(f)

        servers = config.get("servers", {})

        if server_name not in servers:
            available = ", ".join(servers.keys()) if servers else "none"
            raise KeyError(
                f"MCP server '{server_name}' not found in configuration. "
                f"Available servers: {available}. "
                f"Run 'pflow mcp add {server_name}' to configure it."
            )

        return dict(servers[server_name])

    def _expand_env_vars(self, env_dict: dict) -> dict:
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

    def _extract_text_content(self, content: Any) -> str:
        """Extract text from text content block."""
        return str(content.text)

    def _extract_image_content(self, content: Any) -> dict[str, Any]:
        """Extract image data from image content block."""
        return {
            "type": "image",
            "data": content.image.data if hasattr(content.image, "data") else str(content.image),
            "mime_type": content.image.mime_type if hasattr(content.image, "mime_type") else "image/png",
        }

    def _extract_resource_link_content(self, content: Any) -> dict[str, Any]:
        """Extract resource link from content block."""
        return {
            "type": "resource_link",
            "uri": content.resource_link.uri if hasattr(content.resource_link, "uri") else str(content.resource_link),
            "metadata": getattr(content.resource_link, "metadata", {}),
        }

    def _extract_resource_content(self, content: Any) -> dict[str, Any]:
        """Extract embedded resource from content block."""
        return {
            "type": "resource",
            "uri": content.resource.uri if hasattr(content.resource, "uri") else str(content.resource),
            "contents": getattr(content.resource, "contents", None),
            "metadata": getattr(content.resource, "metadata", {}),
        }

    def _extract_unknown_content(self, content: Any) -> str:
        """Extract unknown content as string."""
        return str(content)

    def _extract_error_message(self, mcp_result: Any) -> str:
        """Extract error message from content blocks."""
        if hasattr(mcp_result, "content"):
            for content in mcp_result.content or []:
                if hasattr(content, "text"):
                    return str(content.text)
        return "Tool execution failed"

    def _process_content_blocks(self, mcp_result: Any) -> Any:
        """Process content blocks and extract results."""
        # Map content types to their handlers
        content_handlers = {
            "text": self._extract_text_content,
            "image": self._extract_image_content,
            "resource_link": self._extract_resource_link_content,
            "resource": self._extract_resource_content,
        }

        contents = []
        for content in mcp_result.content or []:
            # Determine content type by checking attributes
            content_type = None
            if hasattr(content, "text"):
                content_type = "text"
            elif hasattr(content, "image"):
                content_type = "image"
            elif hasattr(content, "resource_link"):
                content_type = "resource_link"
            elif hasattr(content, "resource"):
                content_type = "resource"

            # Apply appropriate handler
            if content_type in content_handlers:
                extracted = content_handlers[content_type](content)
                contents.append(extracted)
            else:
                # Unknown content type, use fallback
                contents.append(self._extract_unknown_content(content))

        # Return single item if only one, otherwise list
        if len(contents) == 1:
            return contents[0]
        return contents

    def _extract_result(self, mcp_result: Any) -> Any:
        """Extract usable result from MCP tool response.

        MCP can return results in multiple ways (in priority order):
        1. structuredContent: Typed JSON data matching outputSchema (preferred)
        2. isError flag: Tool execution failed (distinct from protocol errors)
        3. content blocks: Text, image, resource, etc. (fallback/legacy)

        Per MCP spec: "For backwards compatibility, servers should also include
        a JSON serialization of structuredContent in a text content block."

        Args:
            mcp_result: Raw result from MCP SDK (CallToolResult)

        Returns:
            Extracted result (structured data, string, dict, or error)
        """
        if not mcp_result:
            return None

        # PRIORITY 1: Check for structuredContent (new, typed approach)
        # This is validated against outputSchema by the server
        if hasattr(mcp_result, "structuredContent") and mcp_result.structuredContent is not None:
            logger.debug(f"MCP tool returned structured content: {type(mcp_result.structuredContent)}")
            return mcp_result.structuredContent

        # PRIORITY 2: Check for error flag (tool-level errors, not protocol errors)
        if hasattr(mcp_result, "isError") and mcp_result.isError:
            error_msg = self._extract_error_message(mcp_result)
            logger.debug(f"MCP tool returned error: {error_msg}")
            return {"error": error_msg, "is_tool_error": True}

        # PRIORITY 3: Fall back to content blocks (legacy/unstructured)
        if hasattr(mcp_result, "content"):
            return self._process_content_blocks(mcp_result)

        # Fallback: convert to string
        return str(mcp_result)
