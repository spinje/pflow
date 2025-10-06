"""Integration test for MCP → Shell → jq workflow.

This tests the complete fix for the shell stdin template variable issue,
simulating the exact user scenario that was failing.

The tests verify that dict/list/int values from MCP-like nodes (simulated
using the echo node) are correctly converted to JSON/strings when passed
as stdin to shell commands.
"""

from pflow.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow


class TestMCPShellIntegration:
    """Test MCP dict output → shell stdin → jq processing."""

    def test_mcp_dict_to_shell_with_jq(self):
        """Test that MCP dict can be piped to jq via shell stdin.

        This was the original failing scenario:
        - Echo node (simulating MCP) stores dict in shared["data"]
        - Template ${mock-mcp.data} resolves to dict
        - Shell node receives dict in stdin param
        - Type adaptation converts dict → JSON string
        - jq processes the JSON from stdin
        """
        # Workflow IR simulating user's scenario
        workflow_ir = {
            "nodes": [
                {
                    "id": "mock-mcp",
                    "type": "echo",
                    "params": {
                        # Echo node will store this dict in shared
                        "data": {
                            "successful": True,
                            "data": {
                                "valueRanges": [
                                    {
                                        "values": [
                                            ["https://open.spotify.com/track/abc"],
                                            ["Some text"],
                                            ["https://open.spotify.com/track/xyz"],
                                        ]
                                    }
                                ]
                            },
                        }
                    },
                },
                {
                    "id": "extract-url",
                    "type": "shell",
                    "params": {
                        "stdin": "${mock-mcp.data}",  # This is a dict!
                        "command": "jq -r '.data.valueRanges[0].values | map(.[0]) | .[-1]'",
                    },
                },
            ],
            "edges": [{"from": "mock-mcp", "to": "extract-url"}],
        }

        # Compile and run
        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared = {}

        action = flow.run(shared)

        # Verify success
        assert action == "default"

        # Verify jq extracted the last URL
        assert "https://open.spotify.com/track/xyz" in shared["extract-url"]["stdout"]

    def test_mcp_nested_dict_extraction(self):
        """Test extracting nested data from MCP dict via jq."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "mock-mcp",
                    "type": "echo",
                    "params": {"data": {"user": {"profile": {"name": "John Doe", "email": "john@example.com"}}}},
                },
                {
                    "id": "extract-email",
                    "type": "shell",
                    "params": {"stdin": "${mock-mcp.data}", "command": "jq -r '.user.profile.email'"},
                },
            ],
            "edges": [{"from": "mock-mcp", "to": "extract-email"}],
        }

        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared = {}

        action = flow.run(shared)

        assert action == "default"
        assert "john@example.com" in shared["extract-email"]["stdout"]

    def test_mcp_list_to_shell(self):
        """Test that MCP list can be processed via shell stdin."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "mock-mcp",
                    "type": "echo",
                    "params": {
                        "data": [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}, {"id": 3, "name": "third"}]
                    },
                },
                {
                    "id": "extract-second",
                    "type": "shell",
                    "params": {"stdin": "${mock-mcp.data}", "command": "jq -r '.[1].name'"},
                },
            ],
            "edges": [{"from": "mock-mcp", "to": "extract-second"}],
        }

        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared = {}

        action = flow.run(shared)

        assert action == "default"
        assert "second" in shared["extract-second"]["stdout"]

    def test_int_from_mcp_to_shell(self):
        """Test that integer from MCP can be used in shell."""
        workflow_ir = {
            "nodes": [
                {"id": "mock-mcp", "type": "echo", "params": {"data": 42}},
                {
                    "id": "process-number",
                    "type": "shell",
                    "params": {"stdin": "${mock-mcp.data}", "command": "awk '{print $1 * 2}'"},
                },
            ],
            "edges": [{"from": "mock-mcp", "to": "process-number"}],
        }

        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared = {}

        action = flow.run(shared)

        assert action == "default"
        assert "84" in shared["process-number"]["stdout"]

    def test_original_failing_scenario(self):
        """Reproduce the exact error scenario and verify it's fixed.

        Original error: 'dict' object has no attribute 'encode'
        This happened when ${var} resolved to dict and was passed to subprocess stdin.
        """
        # Exact structure from user's Google Sheets MCP response
        google_sheets_response = {
            "successful": True,
            "error": None,
            "data": {
                "spreadsheetId": "1vON91vaoXqf4ITjHJd_yyMLLNK0R4FXVSfzGsi1o9_Y",
                "valueRanges": [
                    {
                        "range": "G:G",
                        "values": [
                            ["Previous entry"],
                            ["https://open.spotify.com/track/TRACK_ID"],
                            ["Latest Spotify URL: https://open.spotify.com/track/LATEST"],
                        ],
                    }
                ],
            },
        }

        workflow_ir = {
            "nodes": [
                {"id": "sheets-data", "type": "echo", "params": {"data": google_sheets_response}},
                {
                    "id": "extract-spotify-url",
                    "type": "shell",
                    "params": {
                        "stdin": "${sheets-data.data}",
                        # Simplified command that just extracts the last URL using jq
                        "command": "jq -r '.data.valueRanges[0].values | map(.[0]) | map(select(contains(\"spotify.com\"))) | .[-1]'",
                    },
                },
            ],
            "edges": [{"from": "sheets-data", "to": "extract-spotify-url"}],
        }

        registry = Registry()
        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared = {}

        # This would have crashed before with:
        # AttributeError: 'dict' object has no attribute 'encode'
        action = flow.run(shared)

        # Now it should work!
        assert action == "default"

        # Verify the URL was extracted successfully
        # The output includes the full text "Latest Spotify URL: https://..."
        assert "https://open.spotify.com/track/LATEST" in shared["extract-spotify-url"]["stdout"]
