"""Integration tests for passing MCP-shaped data through shell stdin.

This tests the complete fix for the shell stdin template variable issue,
simulating the exact user scenario that was failing.

The tests verify that dict/list/int values from MCP-like nodes (simulated
using a code node that outputs structured data) are correctly converted to
JSON/strings when passed as stdin to shell commands.
"""

from pflow.registry import Registry
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine
from tests.shared.shell_command_utils import python_json_command


class TestMCPShellIntegration:
    """Test MCP dict output → shell stdin → JSON processing."""

    def test_mcp_dict_to_shell_json_processing(self):
        """Test that an MCP dict can be processed via shell stdin.

        This was the original failing scenario:
        - Upstream node stores dict in shared store
        - Template ${mock-mcp.result} resolves to dict
        - Shell node receives dict in stdin param
        - Type adaptation converts dict → JSON string
        - A command processes the JSON from stdin
        """
        # Pre-seed mock MCP data into shared store, then use shell to extract
        mcp_data = {
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

        workflow_ir = {
            "nodes": [
                {
                    "id": "extract-url",
                    "type": "shell",
                    "params": {
                        "stdin": "${mock_mcp_data}",  # This is a dict!
                        "command": python_json_command('data["data"]["valueRanges"][0]["values"][-1][0]'),
                    },
                },
            ],
            "edges": [],
        }

        # Compile and run with pre-seeded data
        registry = Registry()
        workflow = compile_workflow(workflow_ir, registry=registry)
        shared = dict(workflow.resolved_defaults)
        shared["mock_mcp_data"] = mcp_data
        engine = WorkflowEngine()
        action = engine.run(workflow, shared)

        # Verify success
        assert action == "default"

        # Verify the command extracted the last URL.
        assert "https://open.spotify.com/track/xyz" in shared["extract-url"]["stdout"]

    def test_mcp_nested_dict_extraction(self):
        """Test extracting nested data from an MCP dict as JSON."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "extract-email",
                    "type": "shell",
                    "params": {
                        "stdin": "${mock_mcp_data}",
                        "command": python_json_command('data["user"]["profile"]["email"]'),
                    },
                },
            ],
            "edges": [],
        }

        registry = Registry()
        workflow = compile_workflow(workflow_ir, registry=registry)
        shared = dict(workflow.resolved_defaults)
        shared["mock_mcp_data"] = {"user": {"profile": {"name": "John Doe", "email": "john@example.com"}}}
        engine = WorkflowEngine()
        action = engine.run(workflow, shared)

        assert action == "default"
        assert "john@example.com" in shared["extract-email"]["stdout"]

    def test_mcp_list_to_shell(self):
        """Test that MCP list can be processed via shell stdin."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "extract-second",
                    "type": "shell",
                    "params": {
                        "stdin": "${mock_mcp_data}",
                        "command": python_json_command('data[1]["name"]'),
                    },
                },
            ],
            "edges": [],
        }

        registry = Registry()
        workflow = compile_workflow(workflow_ir, registry=registry)
        shared = dict(workflow.resolved_defaults)
        shared["mock_mcp_data"] = [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}, {"id": 3, "name": "third"}]
        engine = WorkflowEngine()
        action = engine.run(workflow, shared)

        assert action == "default"
        assert "second" in shared["extract-second"]["stdout"]

    def test_int_from_mcp_to_shell(self):
        """Test that integer from MCP can be used in shell."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "process-number",
                    "type": "shell",
                    "params": {"stdin": "${mock_mcp_data}", "command": "awk '{print $1 * 2}'"},
                },
            ],
            "edges": [],
        }

        registry = Registry()
        workflow = compile_workflow(workflow_ir, registry=registry)
        shared = dict(workflow.resolved_defaults)
        shared["mock_mcp_data"] = 42
        engine = WorkflowEngine()
        action = engine.run(workflow, shared)

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
                {
                    "id": "extract-spotify-url",
                    "type": "shell",
                    "params": {
                        "stdin": "${sheets_data}",
                        # Extract the last value containing a Spotify URL.
                        "command": python_json_command(
                            '[value[0] for value in data["data"]["valueRanges"][0]["values"] '
                            'if "spotify.com" in value[0]][-1]'
                        ),
                    },
                },
            ],
            "edges": [],
        }

        registry = Registry()
        workflow = compile_workflow(workflow_ir, registry=registry)
        shared = dict(workflow.resolved_defaults)
        shared["sheets_data"] = google_sheets_response
        engine = WorkflowEngine()

        # This would have crashed before with:
        # AttributeError: 'dict' object has no attribute 'encode'
        action = engine.run(workflow, shared)

        # Now it should work!
        assert action == "default"

        # Verify the URL was extracted successfully
        # The output includes the full text "Latest Spotify URL: https://..."
        assert "https://open.spotify.com/track/LATEST" in shared["extract-spotify-url"]["stdout"]
