"""How each MCP SDK content block becomes the node's `result` (GH #636).

Text blocks keep the text path (JSON-parsed when the text is JSON). Every other block type
arrives as its MCP wire JSON, so `${node.result.data}` / `${node.result.uri}` resolve and the
store never holds a pydantic repr string or an `AnyUrl` object.

Blocks are real `mcp.types` objects — a hand-rolled fake carrying guessed attributes is how the
original bug hid; only the transport (the connection pool) is a stub.
"""

import json
from typing import Any
from unittest.mock import patch

from mcp.types import (
    AudioContent,
    BlobResourceContents,
    CallToolResult,
    ContentBlock,
    EmbeddedResource,
    ImageContent,
    ResourceLink,
    TextContent,
    TextResourceContents,
)

from pflow.nodes.mcp.node import MCPNode


class _StubPool:
    """Stands in for MCPConnectionPool: returns a fixed tool result."""

    def __init__(self, result: CallToolResult) -> None:
        self.result = result

    def call_tool(self, **kwargs: Any) -> CallToolResult:
        return self.result


def _run(*blocks: ContentBlock) -> Any:
    node = MCPNode()
    node.set_params({"__mcp_server__": "srv", "__mcp_tool__": "tool"})
    shared: dict[str, Any] = {"__mcp_pool__": _StubPool(CallToolResult(content=list(blocks)))}
    with patch.object(node, "_load_server_config", return_value={"command": "unused"}):
        action = node.run(shared)
    assert action == "default"
    # The result is stored, traced and templated — it must be plain JSON.
    json.dumps(shared["result"])
    return shared["result"]


def test_text_block_is_parsed_as_before() -> None:
    assert _run(TextContent(type="text", text='{"a": 1}')) == {"a": 1}
    assert _run(TextContent(type="text", text="plain words")) == "plain words"


def test_image_block_exposes_data_and_mime_type() -> None:
    # `_meta` pins the wire alias: the SDK's Python field is `meta`.
    result = _run(ImageContent(type="image", data="aGk=", mimeType="image/png", _meta={"page": 2}))

    assert result == {"type": "image", "data": "aGk=", "mimeType": "image/png", "_meta": {"page": 2}}


def test_audio_block_exposes_data_and_mime_type() -> None:
    result = _run(AudioContent(type="audio", data="UklGRg==", mimeType="audio/wav"))

    assert result == {"type": "audio", "data": "UklGRg==", "mimeType": "audio/wav"}


def test_resource_link_exposes_uri_as_string() -> None:
    link = ResourceLink(type="resource_link", uri="file:///tmp/report.csv", name="report.csv", mimeType="text/csv")

    assert _run(link) == {
        "type": "resource_link",
        "uri": "file:///tmp/report.csv",
        "name": "report.csv",
        "mimeType": "text/csv",
    }


def test_embedded_text_resource_keeps_its_text() -> None:
    block = EmbeddedResource(
        type="resource",
        resource=TextResourceContents(uri="file:///tmp/notes.md", mimeType="text/markdown", text="# Notes"),
    )

    assert _run(block) == {
        "type": "resource",
        "resource": {"uri": "file:///tmp/notes.md", "mimeType": "text/markdown", "text": "# Notes"},
    }


def test_embedded_blob_resource_keeps_its_blob() -> None:
    block = EmbeddedResource(type="resource", resource=BlobResourceContents(uri="file:///tmp/a.bin", blob="AAE="))

    assert _run(block) == {"type": "resource", "resource": {"uri": "file:///tmp/a.bin", "blob": "AAE="}}


def test_mixed_blocks_become_a_list_in_order() -> None:
    result = _run(
        TextContent(type="text", text="Screenshot taken"),
        ImageContent(type="image", data="aGk=", mimeType="image/png"),
        ResourceLink(type="resource_link", uri="file:///tmp/shot.png", name="shot.png"),
    )

    assert result == [
        "Screenshot taken",
        {"type": "image", "data": "aGk=", "mimeType": "image/png"},
        {"type": "resource_link", "uri": "file:///tmp/shot.png", "name": "shot.png"},
    ]
