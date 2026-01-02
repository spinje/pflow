"""End-to-end tests for JSON auto-parsing in inline objects.

These tests verify the full workflow: shell node outputs JSON string,
which is then auto-parsed when used in an inline object for another node's stdin.
"""

import pytest

from pflow.runtime.compiler import compile_ir_to_flow
from tests.shared.registry_utils import ensure_test_registry


@pytest.fixture
def registry():
    """Provide a registry with shell node available."""
    return ensure_test_registry()


class TestInlineObjectParsingE2E:
    """E2E tests for inline object JSON parsing."""

    def test_shell_stdin_with_json_template(self, registry):
        """Full workflow: shell outputs JSON, passed via inline stdin object."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "get-data",
                    "type": "shell",
                    "params": {"command": 'echo \'{"items": [1, 2, 3], "count": 3}\''},
                },
                {
                    "id": "process",
                    "type": "shell",
                    "params": {
                        "stdin": {"data": "${get-data.stdout}"},
                        "command": "jq '.data.count'",
                    },
                },
            ],
            "edges": [{"from": "get-data", "to": "process"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        # jq should have been able to access .data.count
        assert "3" in shared["process"]["stdout"]

    def test_multiple_sources_combined(self, registry):
        """Combine multiple JSON sources into one stdin object."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "source-a",
                    "type": "shell",
                    "params": {"command": "echo '{\"a\": 1}'"},
                },
                {
                    "id": "source-b",
                    "type": "shell",
                    "params": {"command": "echo '{\"b\": 2}'"},
                },
                {
                    "id": "combine",
                    "type": "shell",
                    "params": {
                        "stdin": {
                            "first": "${source-a.stdout}",
                            "second": "${source-b.stdout}",
                        },
                        "command": "jq '.first.a + .second.b'",
                    },
                },
            ],
            # Both sources must run before combine
            "edges": [
                {"from": "source-a", "to": "source-b"},
                {"from": "source-b", "to": "combine"},
            ],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        # 1 + 2 = 3
        assert "3" in shared["combine"]["stdout"]

    def test_json_array_in_stdin(self, registry):
        """JSON array output is correctly parsed in stdin object."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "get-items",
                    "type": "shell",
                    "params": {"command": 'echo \'[{"id": 1}, {"id": 2}]\''},
                },
                {
                    "id": "count",
                    "type": "shell",
                    "params": {
                        "stdin": {"items": "${get-items.stdout}"},
                        "command": "jq '.items | length'",
                    },
                },
            ],
            "edges": [{"from": "get-items", "to": "count"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        # Array has 2 items
        assert "2" in shared["count"]["stdout"]

    def test_complex_template_preserves_raw_string(self, registry):
        """Complex template (with prefix) keeps JSON as raw string."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "get-data",
                    "type": "shell",
                    "params": {"command": "echo '{\"value\": 42}'"},
                },
                {
                    "id": "show-raw",
                    "type": "shell",
                    "params": {
                        # Complex template - should stay as string
                        "stdin": "Raw JSON: ${get-data.stdout}",
                        "command": "cat",
                    },
                },
            ],
            "edges": [{"from": "get-data", "to": "show-raw"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        # Should be the raw string with prefix, not parsed
        assert 'Raw JSON: {"value": 42}' in shared["show-raw"]["stdout"]

    def test_nested_inline_object(self, registry):
        """JSON parsing works in deeply nested inline objects."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "get-config",
                    "type": "shell",
                    "params": {"command": "echo '{\"debug\": true}'"},
                },
                {
                    "id": "use-config",
                    "type": "shell",
                    "params": {
                        "stdin": {"outer": {"inner": {"config": "${get-config.stdout}"}}},
                        "command": "jq '.outer.inner.config.debug'",
                    },
                },
            ],
            "edges": [{"from": "get-config", "to": "use-config"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        # Should access the boolean value
        assert "true" in shared["use-config"]["stdout"]

    def test_mixed_json_and_static_values(self, registry):
        """Mix of parsed JSON and static values in same object."""
        workflow_ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "get-data",
                    "type": "shell",
                    "params": {"command": "echo '{\"items\": [1, 2, 3]}'"},
                },
                {
                    "id": "process",
                    "type": "shell",
                    "params": {
                        "stdin": {
                            "dynamic": "${get-data.stdout}",
                            "static": {"fixed": "value"},
                            "number": 42,
                        },
                        "command": "jq '.dynamic.items[0] + .number'",
                    },
                },
            ],
            "edges": [{"from": "get-data", "to": "process"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        # 1 (from items[0]) + 42 = 43
        assert "43" in shared["process"]["stdout"]
