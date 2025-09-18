"""Type definitions for MCP integration."""

from typing import Any, Literal, Optional, TypedDict


class AuthConfig(TypedDict, total=False):
    """Authentication configuration for HTTP transport."""

    type: Literal["bearer", "api_key", "basic"]
    token: Optional[str]
    key: Optional[str]
    header: Optional[str]
    username: Optional[str]
    password: Optional[str]


class StdioServerConfig(TypedDict):
    """Configuration for stdio transport servers."""

    transport: Literal["stdio"]
    command: str
    args: list[str]
    env: dict[str, str]
    created_at: str
    updated_at: str


class HTTPServerConfig(TypedDict, total=False):
    """Configuration for HTTP transport servers."""

    transport: Literal["http"]
    url: str
    auth: Optional[AuthConfig]
    headers: Optional[dict[str, str]]
    timeout: Optional[int]
    sse_timeout: Optional[int]
    env: Optional[dict[str, str]]
    created_at: str
    updated_at: str


# Union type for any server config
ServerConfig = StdioServerConfig | HTTPServerConfig


class ToolSchema(TypedDict, total=False):
    """MCP tool schema from discovery."""

    name: str
    description: Optional[str]
    server: str
    inputSchema: dict[str, Any]
    outputSchema: Optional[dict[str, Any]]


class ParamSchema(TypedDict, total=False):
    """Parameter schema for pflow registry."""

    key: str
    type: str
    required: bool
    description: Optional[str]
    default: Any
    enum: Optional[list[Any]]


class InterfaceSchema(TypedDict, total=False):
    """Interface schema for registry entries."""

    description: str
    inputs: list[Any]
    params: list[ParamSchema]
    outputs: list[dict[str, Any]]
    actions: list[str]
    mcp_metadata: dict[str, Any]


class RegistryEntry(TypedDict):
    """Registry entry for MCP nodes."""

    class_name: str
    module: str
    file_path: str
    interface: InterfaceSchema


# JSON Schema types
JSONSchemaType = str | list[str]  # Can be string or union type like ["string", "null"]
JSONSchemaValue = None | bool | int | float | str | list | dict[str, Any]


# Type guards for runtime checking
def is_union_type(json_type: JSONSchemaType) -> bool:
    """Check if a JSON schema type is a union type."""
    return isinstance(json_type, list)
