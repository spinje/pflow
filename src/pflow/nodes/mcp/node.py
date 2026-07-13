"""Universal MCP node that executes any MCP tool via virtual registry entries."""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from pflow.core.node import Node
from pflow.mcp.auth_utils import build_auth_headers, expand_env_vars_nested

logger = logging.getLogger(__name__)

_SOURCE_LINE_SUFFIX = "_source_line"


def _is_source_line_sidecar(key: str, params: dict[str, Any]) -> bool:
    """True iff ``key`` is a compiler-generated ``_<param>_source_line`` sidecar.

    Fenced-block params carry a ``_source_lines`` sidecar that the compiler flattens into
    ``f"_{base}_source_line"`` for each real param ``base`` (compiler.py). This is
    pflow-internal error-line metadata that must never reach an MCP tool call. Requiring
    ``base`` to be a live param keeps the strip precise: a genuine tool argument that merely
    ends in ``_source_line`` (e.g. ``data_source_line``, or ``_x_source_line`` with no ``x``
    param) has no matching base and is forwarded intact.
    """
    if not (key.startswith("_") and key.endswith(_SOURCE_LINE_SUFFIX)):
        return False
    base = key[1 : -len(_SOURCE_LINE_SUFFIX)]
    return bool(base) and base in params


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

    ## Connection Pooling

    When executed as part of a workflow, MCPNode uses an ``MCPConnectionPool``
    (injected into shared store as ``__mcp_pool__``) to keep server sessions
    alive between steps. This enables stateful MCP servers (Playwright, databases)
    to maintain state across multiple workflow nodes.

    ## Async-to-Sync Wrapper

    When no pool is available (e.g. ``pflow probe``), the node falls back
    to ``asyncio.run()`` which creates a new event loop for each execution.

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
        # Connection reuse is handled by MCPConnectionPool (see pool.py)
        super().__init__(max_retries=1, wait=0)
        self._server_config: dict[str, Any] | None = None
        self._timeout: int = 30  # Default timeout in seconds

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
            # Check if any MCP tools are registered to provide better guidance
            from pflow.core.user_errors import MCPError
            from pflow.registry import Registry

            try:
                registry = Registry()
                mcp_nodes = [n for n in registry.list_nodes() if n.startswith("mcp-")]

                if not mcp_nodes:
                    # No MCP tools in registry - user needs to sync
                    raise MCPError(
                        title="MCP tools not available",
                        explanation=(
                            "The workflow tried to use MCP tools that aren't registered.\n"
                            "This usually happens when MCP servers haven't been synced."
                        ),
                        technical_details=f"Debug: server={server}, tool={tool}",
                    )
                else:
                    # MCP tools exist but parameters missing - likely a workflow issue
                    raise MCPError(
                        title="MCP tool configuration error",
                        explanation=(
                            f"The workflow is trying to use an MCP tool but it wasn't properly configured.\n"
                            f"This might indicate the workflow file is corrupted or was manually edited.\n\n"
                            f"Available MCP tools: {', '.join(mcp_nodes[:3])}"
                            f"{f' (and {len(mcp_nodes) - 3} more)' if len(mcp_nodes) > 3 else ''}"
                        ),
                        suggestions=[
                            "Regenerate the workflow using natural language",
                            "Check the workflow file for manual edits",
                            "Run: pflow mcp list",
                        ],
                        technical_details=f"Debug: server={server}, tool={tool}, registry_count={len(mcp_nodes)}",
                    )
            except ImportError:
                # Fallback if Registry can't be imported
                from pflow.core.user_errors import MCPError

                raise MCPError(technical_details=f"Debug: server={server}, tool={tool}") from None

        # Load server configuration and expand env vars (checks os.environ and settings.json)
        config = self._load_server_config(server)
        config = expand_env_vars_nested(
            config,
            include_settings=True,
            raise_on_missing=True,
        )

        # Extract user parameters (exclude special __ parameters)
        # IMPORTANT: MCPNode is universal and server-agnostic!
        # It passes parameters directly to ANY MCP server without modification.
        # Never add server-specific logic here - this node must work with:
        # - filesystem servers (with their path restrictions)
        # - GitHub servers (no paths at all)
        # - Slack servers (channel IDs instead of paths)
        # - Any future MCP server without code changes
        # Strip the compiler's `_<param>_source_line` sidecar (fenced-block error-line metadata)
        # so it never reaches the tool call, while preserving any real arg that merely ends in
        # `_source_line` — see `_is_source_line_sidecar`.
        tool_args = {
            k: v
            for k, v in self.params.items()
            if not k.startswith("__") and k != "timeout" and not _is_source_line_sidecar(k, self.params)
        }

        # Get optional timeout from params (validate as positive integer seconds)
        timeout_param = self.params.get("timeout", 30)
        try:
            timeout_value = int(timeout_param)
            if timeout_value <= 0:
                raise ValueError
            self._timeout = timeout_value
        except Exception:
            raise ValueError(
                f"Invalid 'timeout' parameter: {timeout_param!r}. Must be a positive integer (seconds)."
            ) from None

        logger.debug(
            "Preparing MCP tool execution", extra={"mcp_server": server, "mcp_tool": tool, "tool_args": tool_args}
        )

        # Get verbose flag from shared store (defaults to False if not set)
        verbose = shared.get("__verbose__", False)
        logger.debug(f"MCP Node prep: verbose={verbose}, __verbose__ in shared={shared.get('__verbose__')}")

        # Get connection pool from shared store (injected by executor_service)
        pool = shared.get("__mcp_pool__")

        return {
            "server": server,
            "tool": tool,
            "config": config,
            "arguments": tool_args,
            "verbose": verbose,
            "pool": pool,
        }

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
        pool = prep_res.get("pool")
        if pool is not None:
            # Use connection pool — keeps server alive between workflow steps
            raw_result = pool.call_tool(
                server_name=prep_res["server"],
                tool=prep_res["tool"],
                arguments=prep_res["arguments"],
                config=prep_res["config"],
                verbose=prep_res["verbose"],
                timeout=self._timeout,
            )
            return {"result": self._extract_result(raw_result)}

        # Fallback: standalone execution (pflow probe, no pool)
        result = asyncio.run(self._exec_async(prep_res), debug=False)
        return result

    async def _exec_async(self, prep_res: dict) -> dict:
        """Route to appropriate transport implementation.

        Args:
            prep_res: Preparation results containing server, tool, config, arguments

        Returns:
            Tool execution results
        """
        config = prep_res["config"]
        # Standard format: use "type" field, default to stdio if not present
        transport_type = config.get("type", "stdio")

        if transport_type == "http":
            return await self._exec_async_http(prep_res)
        elif transport_type == "stdio" or transport_type is None:
            return await self._exec_async_stdio(prep_res)
        else:
            raise ValueError(f"Unsupported transport type: {transport_type}")

    async def _exec_async_stdio(self, prep_res: dict) -> dict:
        """Stdio transport implementation using MCP SDK.

        Args:
            prep_res: Preparation results containing server, tool, config, arguments

        Returns:
            Tool execution results
        """
        import contextlib
        import sys
        from typing import TextIO

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        config = prep_res["config"]
        verbose = prep_res.get("verbose", False)

        # Get env vars (already expanded in prep)
        env = config.get("env", {})
        if not isinstance(env, dict):
            env = {}

        # Prepare server parameters
        params = StdioServerParameters(command=config["command"], args=config.get("args", []), env=env if env else None)

        # Use ExitStack to properly manage the devnull file context
        with contextlib.ExitStack() as stack:
            # Determine where to send MCP server stderr output
            if verbose:
                errlog: TextIO = sys.stderr
            else:
                # Open os.devnull as a file to get a proper TextIO object
                # ExitStack will ensure it's properly closed
                errlog = stack.enter_context(open(os.devnull, "w", encoding="utf-8"))

            # Execute with timeout (Py3.11+ uses asyncio.timeout; Py3.10 falls back to wait_for)
            async def _run_session() -> dict:
                # Pass errlog to suppress stderr in non-verbose mode
                async with stdio_client(params, errlog=errlog) as (read, write), ClientSession(read, write) as session:
                    # Initialize handshake (required by MCP protocol)
                    await session.initialize()

                    # Call the tool
                    logger.debug(f"Calling MCP tool: {prep_res['tool']} with args: {prep_res['arguments']}")
                    result = await session.call_tool(prep_res["tool"], prep_res["arguments"])

                    # Extract content from result
                    # MCP returns results as content blocks (text, image, etc.)
                    extracted_result = self._extract_result(result)

                    return {"result": extracted_result}

            timeout_context = getattr(asyncio, "timeout", None)
            if timeout_context is not None:
                # Python 3.11+
                async with timeout_context(self._timeout):
                    return await _run_session()
            else:
                # Python 3.10 fallback
                return await asyncio.wait_for(_run_session(), timeout=self._timeout)

    async def _exec_async_http(self, prep_res: dict) -> dict:
        """HTTP transport implementation using Streamable HTTP.

        Args:
            prep_res: Preparation results containing server, tool, config, arguments

        Returns:
            Tool execution results
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        config = prep_res["config"]
        url = config.get("url")

        if not url:
            raise ValueError(f"HTTP transport requires 'url' in config for server {prep_res['server']}")

        # Build authentication headers
        headers = self._build_auth_headers(config)

        # Get timeout settings
        timeout = config.get("timeout", 30)
        sse_timeout = config.get("sse_timeout", 300)

        logger.debug(f"Connecting to HTTP MCP server at {url}")

        # Execute with timeout handling
        async def _run_session() -> dict:
            async with (
                streamablehttp_client(
                    url=url, headers=headers, timeout=timeout, sse_read_timeout=sse_timeout, terminate_on_close=True
                ) as (read, write, get_session_id),
                ClientSession(read, write) as session,
            ):
                # Initialize handshake (same as stdio)
                await session.initialize()

                # Get session ID for debugging
                session_id = get_session_id()
                if session_id:
                    logger.debug(f"HTTP session established: {session_id}")

                # Call the tool (same as stdio)
                logger.debug(f"Calling MCP tool: {prep_res['tool']} with args: {prep_res['arguments']}")
                result = await session.call_tool(prep_res["tool"], prep_res["arguments"])

                # Extract content from result (same as stdio)
                extracted_result = self._extract_result(result)

                return {"result": extracted_result}

        # Use same timeout pattern as stdio
        timeout_context = getattr(asyncio, "timeout", None)
        if timeout_context is not None:
            # Python 3.11+
            async with timeout_context(self._timeout):
                return await _run_session()
        else:
            # Python 3.10 fallback
            return await asyncio.wait_for(_run_session(), timeout=self._timeout)

    def _build_auth_headers(self, config: dict) -> dict:
        """Build authentication headers from configuration.

        Supports bearer token, API key, and basic auth.

        Args:
            config: Server configuration dictionary

        Returns:
            Dictionary of HTTP headers including authentication
        """
        return build_auth_headers(config)

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
            Action string: "error" on protocol/tool failure, "default" on success.
        """
        # Check for protocol/execution errors
        if "error" in exec_res:
            shared["error"] = exec_res["error"]
            shared["error_details"] = {
                "server": prep_res["server"],
                "tool": prep_res["tool"],
                "timeout": exec_res.get("timeout", False),
            }
            logger.debug(exec_res["error"], extra=shared["error_details"])
            return "error"

        # Get the result
        result = exec_res.get("result")

        # Check for tool-level errors (from isError flag)
        if isinstance(result, dict) and result.get("is_tool_error"):
            shared["error"] = result.get("error", "Tool execution failed")
            shared["error_details"] = {"server": prep_res["server"], "tool": prep_res["tool"], "is_tool_error": True}
            logger.debug(f"MCP tool returned error: {shared['error']}", extra=shared["error_details"])
            # Return "error" so workflow error handling can respond. (A tool error is a
            # deliberate failure verdict — the engine's api_warning detector defers to it
            # and routes/records it as a normal mcp_failure; it is not relabeled "API
            # error". See engine _CLEAN_SUCCESS_ACTIONS / GH #474.)
            return "error"

        # Store successful result. MCP tools expose one canonical output shape:
        # downstream workflows read fields through ${node.result.field}.
        shared["result"] = result

        logger.info(
            "MCP tool completed successfully",
            extra={
                "server": prep_res["server"],
                "tool": prep_res["tool"],
                "result_type": type(result).__name__,
                "is_structured": isinstance(result, dict),
                "result_keys": ["result"],
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
        from pflow.mcp.errors import describe_mcp_error

        diagnostic = describe_mcp_error(exc, timeout=self._timeout)
        error_msg = f"MCP tool failed: {diagnostic.message}"
        if diagnostic.suggestions:
            error_msg += f" {diagnostic.suggestions[0]}"
        logger.debug(
            error_msg,
            exc_info=exc,
            extra={
                "server": prep_res.get("server"),
                "tool": prep_res.get("tool"),
                "exception_type": type(exc).__name__,
            },
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

        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        # Use standard MCP format key
        servers = config.get("mcpServers", {})

        if server_name not in servers:
            available = ", ".join(servers.keys()) if servers else "none"
            raise KeyError(
                f"MCP server '{server_name}' not found in configuration. "
                f"Available servers: {available}. "
                f"Run 'pflow mcp add {server_name}' to configure it."
            )

        return dict(servers[server_name])

    def _safe_parse_json(self, text: str) -> Any:
        """Attempt to parse JSON or Python literal, return original string on failure.

        This allows MCP text content blocks containing JSON to be
        automatically parsed into Python objects, enabling nested
        template access like ${node.result.data.channels[0]}.

        Some MCP servers incorrectly return Python repr format (single quotes)
        instead of valid JSON (double quotes). We handle this by falling back
        to ast.literal_eval() for dict/list-like strings that fail JSON parsing.

        For non-JSON text (plain strings, logs, etc.), returns the
        original string unchanged.

        Args:
            text: Text content that may or may not be JSON

        Returns:
            Parsed JSON object (dict/list/primitive) or original string
        """
        text_stripped = text.strip()

        # Quick rejection: empty or doesn't start with JSON indicators
        if not text_stripped:
            return text

        first_char = text_stripped[0]
        # JSON can start with: { [ " t(rue) f(alse) n(ull) - or digit
        if first_char not in ("{", "[", '"', "t", "f", "n", "-", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"):
            # Doesn't look like JSON - save CPU cycles
            return text

        # Attempt to parse as JSON first (preferred)
        try:
            parsed = json.loads(text_stripped)
            logger.debug(
                "Successfully parsed JSON from text content block",
                extra={"type": type(parsed).__name__, "text_preview": text_stripped[:100]},
            )
            return parsed
        except (json.JSONDecodeError, ValueError) as json_error:
            # JSON parsing failed - check if it might be Python repr format
            # Some MCP servers incorrectly return str(dict) instead of json.dumps(dict)
            if first_char in ("{", "["):
                try:
                    import ast

                    # SECURITY: ast.literal_eval() is safe for untrusted input - it only
                    # evaluates Python literals (strings, numbers, tuples, lists, dicts,
                    # bools, None) and never executes arbitrary code. This is the
                    # recommended way to parse Python repr format from non-compliant
                    # MCP servers that return str(dict) instead of json.dumps(dict).
                    parsed = ast.literal_eval(text_stripped)
                    if isinstance(parsed, (dict, list)):
                        logger.warning(
                            "MCP server returned Python repr instead of JSON - "
                            "parsed with ast.literal_eval(). "
                            "Consider reporting this to the MCP server maintainer.",
                            extra={"type": type(parsed).__name__, "text_preview": text_stripped[:100]},
                        )
                        return parsed
                except (ValueError, SyntaxError):
                    # Not valid Python literal either
                    pass

            # Not valid JSON or Python literal - return as plain text
            logger.debug(f"Text content is not valid JSON, returning as string: {json_error}")
            return text

    def _extract_text_content(self, content: Any) -> Any:
        """Extract text from text content block, parsing JSON if present.

        For backwards compatibility with MCP servers that return JSON as text
        (e.g., Composio), this method attempts to parse the text as JSON.

        Args:
            content: Content block with text attribute

        Returns:
            Parsed JSON object (dict/list/primitive) if text is valid JSON,
            otherwise returns the original text string unchanged.

        Examples::

            # JSON text gets parsed into Python objects:
            content.text = '{"key": "value"}'
            self._extract_text_content(content)  # -> {"key": "value"} (dict)

            # Plain text remains a string:
            content.text = "plain text message"
            self._extract_text_content(content)  # -> "plain text message" (str)

            # A pre-parsed dict from the MCP SDK is preserved unchanged:
            content.text = {"key": "value"}
            self._extract_text_content(content)  # -> {"key": "value"} (dict)

        Note:
            This enables nested template access like ${node.result.data.field}
            without requiring jq workarounds for MCP servers that return JSON
            as text content.

            Some MCP SDKs may pre-parse JSON content into Python dicts/lists
            before returning. We detect this and preserve the structured data
            rather than converting to string (which would produce Python repr
            format with single quotes, breaking JSON tools like jq).
        """
        # If content.text is already structured data (MCP SDK may pre-parse),
        # return it directly without string conversion
        if isinstance(content.text, (dict, list)):
            logger.debug(
                f"Content text already structured: {type(content.text).__name__}",
                extra={"type": type(content.text).__name__},
            )
            return content.text

        text = str(content.text)
        return self._safe_parse_json(text)

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

    def _extract_unknown_content(self, content: Any) -> Any:
        """Extract unknown content, preserving structured data.

        If the content is already a dict or list, return it directly
        to avoid converting to Python repr format (single quotes)
        which breaks JSON tools.
        """
        if isinstance(content, (dict, list)):
            return content
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

        # Fallback: preserve structured data, otherwise convert to string
        # This avoids Python repr format (single quotes) which breaks JSON tools
        if isinstance(mcp_result, (dict, list)):
            return mcp_result
        return str(mcp_result)
