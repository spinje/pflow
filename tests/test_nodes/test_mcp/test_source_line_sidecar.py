"""Regression test for issue #497.

A node param supplied via a fenced code block (```lang <param>) gets a
`_<param>_source_line` sidecar key injected into the node's params (for error-line
mapping). The MCP node forwards its params wholesale to the tool call, so the sidecar
must be stripped before the call — otherwise the server rejects it
(e.g. `Unknown argument "_function_source_line"`).
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from pflow.core.markdown_parser import parse_markdown
from pflow.mcp import MCPServerManager
from pflow.nodes.mcp.node import MCPNode
from pflow.registry import Registry
from pflow.runtime.compilation.compiler import compile_workflow


class TestSourceLineSidecarFiltering:
    """The `_*_source_line` sidecar must never reach the MCP tool call arguments."""

    def _prep_arguments(self, params: dict) -> dict:
        node = MCPNode()
        node.params = params
        with patch.object(node, "_load_server_config", return_value={"command": "test", "args": []}):
            return node.prep({})["arguments"]

    def test_source_line_sidecar_excluded_from_tool_args(self):
        """A `_<param>_source_line` param is dropped; the real param is forwarded."""
        arguments = self._prep_arguments({
            "__mcp_server__": "chrome-devtools",
            "__mcp_tool__": "evaluate_script",
            "function": "async () => { return 'hi'; }",
            "_function_source_line": 5,
        })

        # The real param survives; the sidecar does not.
        assert arguments == {"function": "async () => { return 'hi'; }"}
        assert "_function_source_line" not in arguments

    def test_only_source_line_suffix_is_stripped(self):
        """A user param that merely starts with `_` is preserved — only the suffix is internal."""
        arguments = self._prep_arguments({
            "__mcp_server__": "srv",
            "__mcp_tool__": "tool",
            "_leading_underscore": "keep-me",
            "_arg_source_line": 3,
        })

        assert arguments == {"_leading_underscore": "keep-me"}


# A fenced-block param supplied to an MCP node, driven through the REAL parser + compiler.
# Single-word server name ("browser") so mcp-<server>-<tool> splits unambiguously.
_FENCED_MCP_WORKFLOW = """# Fenced MCP test

## Steps

### settle

Run a script in the browser to settle the page.

- type: mcp-browser-evaluate

```javascript function
async () => { return "hi"; }
```
"""


class TestFencedBlockParamEndToEnd:
    """Parse → compile → prep: the fenced-block sidecar the compiler injects is stripped."""

    def test_fenced_block_param_does_not_leak_sidecar_to_tool_args(self):
        """The repro from issue #497, exercised through the real parse/compile stack.

        A fenced ```` ```javascript function ```` block supplies the `function` param. The
        parser records its line in `_source_lines`; the compiler flattens that into a
        `_function_source_line` param. Without the fix that key reaches `tool_args` and the
        MCP server rejects it. This asserts the compiler DOES inject the sidecar (so the test
        would go silently vacuous if that ever changed) and that prep strips it back out.
        """
        with tempfile.TemporaryDirectory() as tmp:
            # Configure the MCP server the compiler resolves the node type against. Patch the
            # default-config manager the compiler instantiates so this stays hermetic (no
            # dependency on the machine's ~/.pflow config).
            manager = MCPServerManager(config_path=Path(tmp) / "mcp-servers.json")
            manager.add_server(name="browser", transport="stdio", command="true", args=[])

            registry = Registry(registry_path=Path(tmp) / "registry.json")
            nodes = registry.load()
            nodes["mcp-browser-evaluate"] = {
                "class_name": "MCPNode",
                "module": "pflow.nodes.mcp.node",
                "file_path": "virtual://mcp",
                "interface": {
                    "description": "Evaluate a script in the page",
                    "inputs": [],  # MCP nodes declare no inputs
                    "params": [{"name": "function", "type": "str", "description": "JS to run"}],
                    "outputs": [{"key": "result", "type": "str", "description": "result"}],
                    "actions": ["default"],
                },
            }
            registry.save(nodes)

            ir = parse_markdown(_FENCED_MCP_WORKFLOW).ir
            with patch("pflow.mcp.manager.MCPServerManager", return_value=manager):
                compiled = compile_workflow(ir, registry)
            node = compiled.start_node

            # Precondition: the compiler really does inject the sidecar (guards against the
            # test silently passing if that mechanism moves).
            assert node.params["_function_source_line"] == 12

            with patch.object(node, "_load_server_config", return_value={"command": "test", "args": []}):
                arguments = node.prep({})["arguments"]

            assert arguments == {"function": 'async () => { return "hi"; }'}
