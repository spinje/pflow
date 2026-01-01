"""Integration test for shell stdin type preservation (Task 103).

This tests the primary use case: passing multiple structured data sources
to a shell command via stdin without double-serialization.

Before the fix:
  stdin: {"a": "${data-a}", "b": "${data-b}"}
  Would produce: {"a": "{\"key\": \"value\"}", "b": "{\"items\": [1,2,3]}"}
  (Inner objects double-serialized as JSON strings)

After the fix:
  stdin: {"a": "${data-a}", "b": "${data-b}"}
  Produces: {"a": {"key": "value"}, "b": {"items": [1,2,3]}}
  (Proper nested JSON structure)
"""

import json

from pflow.registry.registry import Registry
from pflow.runtime.compiler import compile_ir_to_flow


class TestShellStdinTypePreservation:
    """Test shell node receives properly structured data via stdin."""

    def test_shell_stdin_inline_object_not_double_encoded(self):
        """THE USE CASE: Multiple data sources combined in stdin.

        This is the exact scenario from Task 103 that motivated the fix.
        Users want to pass multiple upstream results to jq/python for processing.
        """
        workflow_ir = {
            "inputs": {
                "config": {"type": "object", "required": True},
                "data": {"type": "object", "required": True},
            },
            "nodes": [
                {
                    "id": "process",
                    "type": "shell",
                    "params": {
                        "stdin": {"config": "${config}", "data": "${data}"},
                        "command": "cat",  # Echo stdin to verify structure
                    },
                }
            ],
            "edges": [],
            "outputs": {},
        }

        registry = Registry()
        flow = compile_ir_to_flow(
            workflow_ir,
            registry=registry,
            initial_params={
                "config": {"name": "MyApp", "version": "1.0"},
                "data": {"items": [1, 2, 3], "count": 3},
            },
            validate=False,
        )

        shared = {}
        flow.run(shared)

        # Parse the shell output
        stdout = shared.get("process", {}).get("stdout", "")
        parsed = json.loads(stdout)

        # CRITICAL: Inner values must be proper nested objects, not strings
        assert isinstance(parsed["config"], dict), "config should be nested dict, not JSON string"
        assert isinstance(parsed["data"], dict), "data should be nested dict, not JSON string"

        # Verify exact values
        assert parsed["config"] == {"name": "MyApp", "version": "1.0"}
        assert parsed["data"] == {"items": [1, 2, 3], "count": 3}

    def test_shell_stdin_mixed_types_preserved(self):
        """Inline object can contain mixed types, all preserved correctly."""
        workflow_ir = {
            "inputs": {
                "text": {"type": "string", "required": True},
                "number": {"type": "number", "required": True},
                "flag": {"type": "boolean", "required": True},
                "items": {"type": "array", "required": True},
            },
            "nodes": [
                {
                    "id": "echo",
                    "type": "shell",
                    "params": {
                        "stdin": {
                            "text": "${text}",
                            "number": "${number}",
                            "flag": "${flag}",
                            "items": "${items}",
                        },
                        "command": "cat",
                    },
                }
            ],
            "edges": [],
            "outputs": {},
        }

        registry = Registry()
        flow = compile_ir_to_flow(
            workflow_ir,
            registry=registry,
            initial_params={
                "text": "hello",
                "number": 42,
                "flag": True,
                "items": ["a", "b", "c"],
            },
            validate=False,
        )

        shared = {}
        flow.run(shared)

        parsed = json.loads(shared["echo"]["stdout"])

        # All types should be preserved in the JSON
        assert parsed["text"] == "hello"
        assert parsed["number"] == 42
        assert parsed["flag"] is True
        assert parsed["items"] == ["a", "b", "c"]

    def test_shell_stdin_with_jq_processing(self):
        """Real-world: Use jq to process combined data sources."""
        workflow_ir = {
            "inputs": {
                "user": {"type": "object", "required": True},
                "settings": {"type": "object", "required": True},
            },
            "nodes": [
                {
                    "id": "merge",
                    "type": "shell",
                    "params": {
                        "stdin": {"user": "${user}", "settings": "${settings}"},
                        # jq merges user and settings objects
                        "command": "jq -c '.user + .settings'",
                    },
                }
            ],
            "edges": [],
            "outputs": {},
        }

        registry = Registry()
        flow = compile_ir_to_flow(
            workflow_ir,
            registry=registry,
            initial_params={
                "user": {"name": "Alice", "email": "alice@example.com"},
                "settings": {"theme": "dark", "notifications": True},
            },
            validate=False,
        )

        shared = {}
        flow.run(shared)

        # jq should successfully merge the objects
        result = json.loads(shared["merge"]["stdout"])

        assert result["name"] == "Alice"
        assert result["email"] == "alice@example.com"
        assert result["theme"] == "dark"
        assert result["notifications"] is True

    def test_complex_template_in_stdin_still_stringifies(self):
        """Complex templates (text + variable) should still become strings."""
        workflow_ir = {
            "inputs": {
                "name": {"type": "string", "required": True},
                "data": {"type": "object", "required": True},
            },
            "nodes": [
                {
                    "id": "echo",
                    "type": "shell",
                    "params": {
                        "stdin": {
                            "greeting": "Hello ${name}!",  # Complex - becomes string
                            "payload": "${data}",  # Simple - preserved as dict
                        },
                        "command": "cat",
                    },
                }
            ],
            "edges": [],
            "outputs": {},
        }

        registry = Registry()
        flow = compile_ir_to_flow(
            workflow_ir,
            registry=registry,
            initial_params={
                "name": "World",
                "data": {"key": "value"},
            },
            validate=False,
        )

        shared = {}
        flow.run(shared)

        parsed = json.loads(shared["echo"]["stdout"])

        # Complex template becomes interpolated string
        assert parsed["greeting"] == "Hello World!"
        assert isinstance(parsed["greeting"], str)

        # Simple template preserves dict
        assert parsed["payload"] == {"key": "value"}
        assert isinstance(parsed["payload"], dict)
