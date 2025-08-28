"""
Proposed fix for MCPNode to handle structuredContent from MCP servers.

This shows what needs to be implemented to support servers that provide
output schemas and return structured data.
"""

from typing import Any


def _extract_result(self, mcp_result: Any) -> Any:
    """Extract usable result from MCP tool response.

    MCP can return results in two ways:
    1. structuredContent: Typed JSON data matching outputSchema (preferred)
    2. content blocks: Text, image, etc. (fallback/legacy)

    Per spec: "For backwards compatibility, servers should also include
    a JSON serialization of structuredContent in a text content block."

    Args:
        mcp_result: Raw result from MCP SDK (CallToolResult)

    Returns:
        Extracted result (structured data, string, or dict)
    """
    if not mcp_result:
        return None

    # PRIORITY 1: Check for structuredContent (new, typed approach)
    if hasattr(mcp_result, "structuredContent") and mcp_result.structuredContent is not None:
        # This is validated against outputSchema by the server
        # Return it directly as structured data
        return mcp_result.structuredContent

    # PRIORITY 2: Check for error flag
    if hasattr(mcp_result, "isError") and mcp_result.isError:
        # Tool execution failed (distinct from protocol errors)
        error_msg = "Tool execution failed"
        # Try to extract error details from content blocks
        if hasattr(mcp_result, "content"):
            for content in mcp_result.content or []:
                if hasattr(content, "text"):
                    error_msg = content.text
                    break
        return {"error": error_msg, "is_tool_error": True}

    # PRIORITY 3: Fall back to content blocks (legacy/unstructured)
    if hasattr(mcp_result, "content"):
        contents = []
        for content in mcp_result.content or []:
            if hasattr(content, "text"):
                # Text content block
                contents.append(content.text)
            elif hasattr(content, "image"):
                # Image content block (base64 encoded)
                contents.append({
                    "type": "image",
                    "data": content.image.data if hasattr(content.image, "data") else str(content.image),
                    "mime_type": content.image.mime_type if hasattr(content.image, "mime_type") else "image/png",
                })
            elif hasattr(content, "resource_link"):
                # Resource link (URI + metadata)
                contents.append({
                    "type": "resource_link",
                    "uri": content.resource_link.uri,
                    "metadata": getattr(content.resource_link, "metadata", {}),
                })
            elif hasattr(content, "resource"):
                # Embedded resource (URI + inline contents)
                contents.append({
                    "type": "resource",
                    "uri": content.resource.uri,
                    "contents": getattr(content.resource, "contents", None),
                })
            else:
                # Unknown content type, try to serialize
                contents.append(str(content))

        # Return single item if only one, otherwise list
        if len(contents) == 1:
            return contents[0]
        return contents

    # Fallback: convert to string
    return str(mcp_result)


# Also need to update post() to handle structured outputs properly:


def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
    """Store results in shared store and determine next action.

    With structured content support, we need to handle:
    1. Structured data from servers with outputSchema
    2. Tool errors (isError flag)
    3. Legacy unstructured results
    """
    result = exec_res.get("result")

    # Check for tool-level errors (not protocol errors)
    if isinstance(result, dict) and result.get("is_tool_error"):
        shared["error"] = result.get("error", "Tool execution failed")
        shared["error_details"] = {"server": prep_res["server"], "tool": prep_res["tool"], "is_tool_error": True}
        return "default"  # Still using default due to planner limitation

    # Store successful result
    shared["result"] = result

    # For structured data, also extract specific fields if the registry
    # declared them in the outputs
    if isinstance(result, dict) and not result.get("error"):
        # If we have structured data, make fields directly accessible
        # e.g., if output schema defined "temperature", "humidity"
        # make them available as shared["temperature"], shared["humidity"]
        for key, value in result.items():
            if not key.startswith("_"):  # Skip private fields
                shared[key] = value

    # Also store with server-specific key
    result_key = f"{prep_res['server']}_{prep_res['tool']}_result"
    shared[result_key] = result

    return "default"
