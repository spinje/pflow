#!/usr/bin/env python3
"""
Simple MCP HTTP test server for validating pflow's HTTP transport.

Run with: python test-mcp-http-server.py
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict

from aiohttp import web

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Store active sessions
sessions = {}


class MCPTestServer:
    """Simple MCP HTTP server for testing."""

    def __init__(self):
        self.app = web.Application()
        self.setup_routes()

    def setup_routes(self):
        """Setup HTTP routes for MCP protocol."""
        self.app.router.add_post("/mcp", self.handle_mcp_post)
        self.app.router.add_get("/mcp", self.handle_mcp_get)
        self.app.router.add_delete("/mcp", self.handle_mcp_delete)

    async def handle_mcp_post(self, request: web.Request) -> web.Response:
        """Handle POST requests (JSON-RPC messages)."""
        try:
            # Get session ID from headers
            session_id = request.headers.get("Mcp-Session-Id")

            # Parse JSON-RPC request
            data = await request.json()
            logger.info(f"Received request: {data}")

            method = data.get("method")
            params = data.get("params", {})
            request_id = data.get("id")

            # Handle different methods
            if method == "initialize":
                # Create new session
                if not session_id:
                    session_id = str(uuid.uuid4())
                    sessions[session_id] = {"created": datetime.utcnow().isoformat()}

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "serverInfo": {"name": "test-mcp-server", "version": "1.0.0"},
                    },
                }

                return web.json_response(response, headers={"Mcp-Session-Id": session_id})

            elif method == "tools/list":
                # Return available tools
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": "echo",
                                "description": "Echoes back the input message",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {"message": {"type": "string", "description": "Message to echo"}},
                                    "required": ["message"],
                                },
                            },
                            {
                                "name": "get_time",
                                "description": "Returns the current server time",
                                "inputSchema": {"type": "object", "properties": {}},
                            },
                            {
                                "name": "add_numbers",
                                "description": "Adds two numbers together",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "a": {"type": "number", "description": "First number"},
                                        "b": {"type": "number", "description": "Second number"},
                                    },
                                    "required": ["a", "b"],
                                },
                            },
                        ]
                    },
                }

                return web.json_response(response, headers={"Mcp-Session-Id": session_id} if session_id else {})

            elif method == "tools/call":
                # Execute a tool
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})

                result = await self.execute_tool(tool_name, tool_args)

                response = {"jsonrpc": "2.0", "id": request_id, "result": result}

                return web.json_response(response, headers={"Mcp-Session-Id": session_id} if session_id else {})

            elif method == "notifications/initialized":
                # Client notification that initialization is complete
                return web.Response(status=202)  # Accepted

            else:
                # Unknown method
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
                return web.json_response(response, status=400)

        except Exception as e:
            logger.exception("Error handling request")
            return web.json_response(
                {"jsonrpc": "2.0", "error": {"code": -32603, "message": f"Internal error: {e!s}"}}, status=500
            )

    async def handle_mcp_get(self, request: web.Request) -> web.Response:
        """Handle GET requests (SSE stream)."""
        # For simplicity, we won't implement SSE in this test server
        return web.Response(text="SSE not implemented in test server", status=501)

    async def handle_mcp_delete(self, request: web.Request) -> web.Response:
        """Handle DELETE requests (session termination)."""
        session_id = request.headers.get("Mcp-Session-Id")
        if session_id and session_id in sessions:
            del sessions[session_id]
            logger.info(f"Terminated session: {session_id}")
        return web.Response(status=200)

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool and return results."""
        if tool_name == "echo":
            message = arguments.get("message", "")
            return {"content": [{"type": "text", "text": f"Echo: {message}"}]}

        elif tool_name == "get_time":
            current_time = datetime.utcnow().isoformat()
            return {"content": [{"type": "text", "text": f"Current server time: {current_time}"}]}

        elif tool_name == "add_numbers":
            a = arguments.get("a", 0)
            b = arguments.get("b", 0)
            result = a + b
            return {"content": [{"type": "text", "text": f"Result: {a} + {b} = {result}"}]}

        else:
            return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}]}

    def run(self, host: str = "127.0.0.1", port: int = 8080):
        """Run the server."""
        logger.info(f"Starting MCP test server on http://{host}:{port}/mcp")
        logger.info("Press Ctrl+C to stop")
        web.run_app(self.app, host=host, port=port)


if __name__ == "__main__":
    server = MCPTestServer()
    server.run()
