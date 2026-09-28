"""`result_format: json_block` — parse the single fenced ```json block of a text-only MCP result.

Tools shaped for an LLM (e.g. chrome-devtools `evaluate_script`) wrap their payload in prose:
"Script ran on page and returned:\\n```json\\n{...}\\n```". The opt-in param makes the parsed
block the node's `result`; zero or several blocks are an error, never a guess (GH #625).

Results are real `mcp.types` objects; only the transport (the connection pool) is a stub.
"""

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent

from pflow.nodes.mcp.node import MCPNode, MCPResultFormatError

PROSE_WRAPPED = 'Script ran on page and returned:\n```json\n{"a": 1, "b": "two"}\n```'


class _StubPool:
    """Stands in for MCPConnectionPool: returns a fixed tool result, records the call."""

    def __init__(self, result: CallToolResult) -> None:
        self.result = result
        self.arguments: dict[str, Any] | None = None

    def call_tool(self, **kwargs: Any) -> CallToolResult:
        self.arguments = kwargs["arguments"]
        return self.result


def _text_result(*texts: str, structured: dict[str, Any] | None = None, is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=t) for t in texts],
        structuredContent=structured,
        isError=is_error,
    )


def _run(result: CallToolResult, **params: Any) -> tuple[str | None, dict[str, Any], _StubPool]:
    node = MCPNode()
    node.set_params({"__mcp_server__": "srv", "__mcp_tool__": "evaluate", **params})
    pool = _StubPool(result)
    shared: dict[str, Any] = {"__mcp_pool__": pool}
    with patch.object(node, "_load_server_config", return_value={"command": "unused"}):
        action = node.run(shared)
    return action, shared, pool


def test_single_fenced_block_becomes_structured_result() -> None:
    action, shared, pool = _run(_text_result(PROSE_WRAPPED), result_format="json_block", expression="x")

    assert action == "default"
    assert shared["result"] == {"a": 1, "b": "two"}
    # result_format is pflow's, not the tool's: it never reaches the server.
    assert pool.arguments == {"expression": "x"}


def test_param_absent_keeps_prose_string_unchanged() -> None:
    action, shared, _ = _run(_text_result(PROSE_WRAPPED))

    assert action == "default"
    assert shared["result"] == PROSE_WRAPPED


@pytest.mark.parametrize(
    ("texts", "found"),
    [
        (["Script ran on page and returned: undefined"], 0),
        # An unlabelled or non-json fence is not a json block.
        (['Here:\n```\n{"a": 1}\n```\nand\n```python\nx = 1\n```'], 0),
        (['First:\n```json\n{"a": 1}\n```\nSecond:\n```json\n{"b": 2}\n```'], 2),
        # Blocks are counted across every text content block of the result.
        (['```json\n{"a": 1}\n```', 'more:\n```json\n{"b": 2}\n```'], 2),
    ],
)
def test_block_count_other_than_one_is_an_error(texts: list[str], found: int) -> None:
    action, shared, _ = _run(_text_result(*texts), result_format="json_block")

    assert action == "error"
    assert "result" not in shared
    assert f"exactly one fenced ```json block in the tool's text result, found {found}" in shared["error"]
    # The tool call succeeded; the message must not blame the server.
    assert not shared["error"].startswith("MCP tool failed")


def test_invalid_json_in_block_is_an_error() -> None:
    action, shared, _ = _run(_text_result("Result:\n```json\n{not json}\n```"), result_format="json_block")

    assert action == "error"
    assert "the fenced ```json block is not valid JSON" in shared["error"]
    assert "{not json}" in shared["error"]


def test_structured_content_keeps_precedence_over_text_block() -> None:
    structured = {"source": "structuredContent"}
    action, shared, _ = _run(
        _text_result('```json\n{"source": "text"}\n```', structured=structured), result_format="json_block"
    )

    assert action == "default"
    assert shared["result"] == structured


def test_tool_error_flag_keeps_precedence_over_text_block() -> None:
    action, shared, _ = _run(_text_result(PROSE_WRAPPED, is_error=True), result_format="json_block")

    assert action == "error"
    assert shared["error"] == PROSE_WRAPPED
    assert shared["error_details"]["is_tool_error"] is True


def test_non_text_content_is_ignored_when_one_block_exists() -> None:
    result = CallToolResult(
        content=[
            ImageContent(type="image", data="aGk=", mimeType="image/png"),
            TextContent(type="text", text=PROSE_WRAPPED),
        ]
    )
    action, shared, _ = _run(result, result_format="json_block")

    assert action == "default"
    assert shared["result"] == {"a": 1, "b": "two"}


def test_unknown_result_format_value_is_rejected_before_the_call() -> None:
    node = MCPNode()
    node.set_params({"__mcp_server__": "srv", "__mcp_tool__": "evaluate", "result_format": "text"})
    pool = _StubPool(_text_result(PROSE_WRAPPED))

    with (
        patch.object(node, "_load_server_config", return_value={"command": "unused"}),
        pytest.raises(MCPResultFormatError, match="The only supported value is 'json_block'"),
    ):
        node.run({"__mcp_pool__": pool})
    assert pool.arguments is None


_FENCED_SERVER = """
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("fenced")


@mcp.tool(structured_output=False)
def evaluate() -> str:
    return 'Script ran on page and returned:\\n```json\\n{"count": 42}\\n```'


@mcp.tool(structured_output=False)
def two_blocks() -> str:
    return '```json\\n{"a": 1}\\n```\\n```json\\n{"b": 2}\\n```'


mcp.run()
"""


@pytest.mark.e2e
@pytest.mark.parametrize(
    ("tool", "expected_action"),
    [("evaluate", "default"), ("two_blocks", "error")],
)
def test_real_stdio_server(tmp_path: Path, tool: str, expected_action: str) -> None:
    """Through the SDK's stdio transport, where node errors surface wrapped in anyio task groups."""
    server = tmp_path / "fenced_server.py"
    server.write_text(_FENCED_SERVER, encoding="utf-8")
    node = MCPNode()
    node.set_params({"__mcp_server__": "fenced", "__mcp_tool__": tool, "result_format": "json_block"})
    shared: dict[str, Any] = {}

    with patch.object(node, "_load_server_config", return_value={"command": sys.executable, "args": [str(server)]}):
        action = node.run(shared)

    assert action == expected_action
    if expected_action == "default":
        assert shared["result"] == {"count": 42}
    else:
        assert shared["error"].startswith("result_format 'json_block' needs exactly one fenced ```json block")
        assert "found 2" in shared["error"]
