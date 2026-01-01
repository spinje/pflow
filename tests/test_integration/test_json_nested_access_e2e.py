"""End-to-end tests for JSON auto-parsing during nested template access.

These tests verify the complete flow from workflow IR to execution,
ensuring ${node.stdout.field} works when stdout contains JSON.

The validator allows nested access on string types (with a warning about
JSON auto-parsing at runtime), so validation is enabled by default.
"""

import pytest

from pflow.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow


@pytest.fixture
def registry():
    """Create a fresh registry for tests."""
    return Registry()


class TestJsonNestedAccessE2E:
    """E2E tests verifying JSON auto-parsing in real workflow execution."""

    def test_shell_json_output_nested_access(self, registry):
        """Original feature request scenario: ${shell.stdout.field} works."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "output-json",
                    "type": "shell",
                    "params": {"command": 'echo \'{"iso": "2026-01-01", "month": "January"}\''},
                },
                {
                    "id": "test-nested",
                    "type": "shell",
                    "params": {"command": "echo 'iso value: ${output-json.stdout.iso}'"},
                },
            ],
            "edges": [{"from": "output-json", "to": "test-nested"}],
        }

        # Validation enabled - nested access on str allowed with warning
        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        # Verify the nested access worked
        assert "iso value: 2026-01-01" in shared["test-nested"]["stdout"]

    def test_deep_nested_json_access(self, registry):
        """Deep nesting: ${node.stdout.a.b.c} works."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "deep-json",
                    "type": "shell",
                    "params": {"command": 'echo \'{"data": {"user": {"name": "Alice"}}}\''},
                },
                {
                    "id": "use-deep",
                    "type": "shell",
                    "params": {"command": "echo 'Name: ${deep-json.stdout.data.user.name}'"},
                },
            ],
            "edges": [{"from": "deep-json", "to": "use-deep"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        assert "Name: Alice" in shared["use-deep"]["stdout"]

    def test_json_array_access(self, registry):
        """Array access: ${node.stdout[0].id} works."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "array-json",
                    "type": "shell",
                    "params": {"command": 'echo \'[{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]\''},
                },
                {
                    "id": "use-array",
                    "type": "shell",
                    "params": {"command": "echo 'First ID: ${array-json.stdout[0].id}'"},
                },
            ],
            "edges": [{"from": "array-json", "to": "use-array"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        assert "First ID: 1" in shared["use-array"]["stdout"]

    def test_mixed_object_array_access(self, registry):
        """Mixed access: ${node.stdout.items[0].name} works."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "mixed-json",
                    "type": "shell",
                    "params": {"command": 'echo \'{"items": [{"name": "Alice"}, {"name": "Bob"}], "count": 2}\''},
                },
                {
                    "id": "use-mixed",
                    "type": "shell",
                    "params": {
                        "command": "echo 'First: ${mixed-json.stdout.items[0].name}, Count: ${mixed-json.stdout.count}'"
                    },
                },
            ],
            "edges": [{"from": "mixed-json", "to": "use-mixed"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        assert "First: Alice" in shared["use-mixed"]["stdout"]
        assert "Count: 2" in shared["use-mixed"]["stdout"]

    def test_terminal_access_returns_raw_string(self, registry):
        """${node.stdout} without path returns raw string, not parsed."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "json-output",
                    "type": "shell",
                    "params": {"command": 'echo \'{"field": "value"}\''},
                },
                {
                    "id": "use-raw",
                    "type": "shell",
                    "params": {"command": "echo 'Raw: ${json-output.stdout}'"},
                },
            ],
            "edges": [{"from": "json-output", "to": "use-raw"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        # Raw string includes the JSON as-is
        assert '{"field": "value"}' in shared["use-raw"]["stdout"]

    def test_invalid_json_graceful_fallback(self, registry):
        """Invalid JSON leaves template unresolved (doesn't crash)."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "not-json",
                    "type": "shell",
                    "params": {"command": "echo 'this is not json'"},
                },
                {
                    "id": "try-access",
                    "type": "shell",
                    # This template won't resolve - the ${...} stays as-is
                    "params": {"command": "echo 'Value: ${not-json.stdout.field}'"},
                },
            ],
            "edges": [{"from": "not-json", "to": "try-access"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}

        # The flow will fail because the template can't be resolved at runtime
        # (the string is not valid JSON, so JSON auto-parsing fails)
        with pytest.raises(ValueError, match="Unresolved variables"):
            flow.run(shared)


class TestRealWorldPatterns:
    """Tests simulating real-world usage patterns."""

    def test_curl_api_pattern(self, registry):
        """Simulate curl API response pattern."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "api-call",
                    "type": "shell",
                    "params": {"command": 'echo \'{"status": "ok", "data": {"user_id": 123, "name": "Alice"}}\''},
                },
                {
                    "id": "process-response",
                    "type": "shell",
                    "params": {
                        "command": "echo 'User ${api-call.stdout.data.name} (ID: ${api-call.stdout.data.user_id}) - Status: ${api-call.stdout.status}'"
                    },
                },
            ],
            "edges": [{"from": "api-call", "to": "process-response"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        output = shared["process-response"]["stdout"]
        assert "User Alice" in output
        assert "ID: 123" in output
        assert "Status: ok" in output

    def test_jq_output_pattern(self, registry):
        """Simulate jq formatted output pattern."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "jq-format",
                    "type": "shell",
                    "params": {
                        # jq typically outputs with newlines
                        "command": 'printf \'{\\n  "date": "2026-01-01",\\n  "items": ["a", "b"]\\n}\''
                    },
                },
                {
                    "id": "use-jq",
                    "type": "shell",
                    "params": {"command": "echo 'Date: ${jq-format.stdout.date}'"},
                },
            ],
            "edges": [{"from": "jq-format", "to": "use-jq"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        assert "Date: 2026-01-01" in shared["use-jq"]["stdout"]

    def test_recursive_json_parsing(self, registry):
        """JSON-in-JSON: nested JSON strings are also parsed."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "nested-json",
                    "type": "shell",
                    "params": {
                        # Outer JSON contains inner JSON as a string value
                        "command": 'echo \'{"wrapper": "{\\\\"inner\\\\": \\\\"deep value\\\\"}"}\''
                    },
                },
                {
                    "id": "access-deep",
                    "type": "shell",
                    "params": {"command": "echo 'Inner: ${nested-json.stdout.wrapper.inner}'"},
                },
            ],
            "edges": [{"from": "nested-json", "to": "access-deep"}],
        }

        flow = compile_ir_to_flow(workflow_ir, registry=registry)
        shared: dict = {}
        flow.run(shared)

        assert "Inner: deep value" in shared["access-deep"]["stdout"]
