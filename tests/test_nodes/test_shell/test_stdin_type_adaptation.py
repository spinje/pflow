"""Test shell node stdin type adaptation.

The shell node should intelligently adapt any Python type to string for stdin,
since subprocess.run() requires string or None for input.
"""

from src.pflow.nodes.shell.shell import ShellNode
from src.pflow.runtime.node_wrapper import TemplateAwareNodeWrapper


class TestDictListToJSON:
    """Test dict and list are serialized to JSON."""

    def test_dict_stdin_serialized_to_json(self):
        """Dict in stdin should be JSON serialized."""
        node = ShellNode()
        node.set_params({"command": "jq -r '.key'", "stdin": {"key": "value"}})
        shared = {}

        action = node.run(shared)

        assert action == "default"
        assert shared["stdout"].strip() == "value"

    def test_list_stdin_serialized_to_json(self):
        """List in stdin should be JSON serialized."""
        node = ShellNode()
        node.set_params({"command": "jq -r '.[0]'", "stdin": [1, 2, 3]})
        shared = {}

        action = node.run(shared)

        assert action == "default"
        assert shared["stdout"].strip() == "1"

    def test_nested_dict_stdin(self):
        """Complex nested structures should serialize correctly."""
        data = {"user": {"name": "John", "age": 30}, "items": [{"id": 1}, {"id": 2}]}
        node = ShellNode()
        node.set_params({"command": "jq -r '.user.name'", "stdin": data})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"].strip() == "John"

    def test_empty_dict_stdin(self):
        """Empty dict should serialize to '{}'."""
        node = ShellNode()
        node.set_params({"command": "cat", "stdin": {}})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"].strip() == "{}"

    def test_empty_list_stdin(self):
        """Empty list should serialize to '[]'."""
        node = ShellNode()
        node.set_params({"command": "cat", "stdin": []})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"].strip() == "[]"

    def test_dict_with_special_chars(self):
        """Dict with quotes and special chars should serialize correctly."""
        data = {"text": "He said \"hello\" and 'goodbye'"}
        node = ShellNode()
        node.set_params({"command": "jq -r '.text'", "stdin": data})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert "hello" in shared["stdout"]
        assert "goodbye" in shared["stdout"]


class TestPrimitiveTypes:
    """Test primitive types are converted to strings."""

    def test_int_stdin_converted_to_string(self):
        """Integer should be converted to string."""
        node = ShellNode()
        node.set_params({"command": "cat", "stdin": 42})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"] == "42"

    def test_bool_true_stdin_converted_to_string(self):
        """Boolean True should be converted to lowercase 'true' for CLI compatibility."""
        node = ShellNode()
        node.set_params({"command": "cat", "stdin": True})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"] == "true"

    def test_bool_false_stdin_converted_to_string(self):
        """Boolean False should be converted to lowercase 'false' for CLI compatibility."""
        node = ShellNode()
        node.set_params({"command": "cat", "stdin": False})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"] == "false"

    def test_float_stdin_converted_to_string(self):
        """Float should be converted to string."""
        node = ShellNode()
        node.set_params({"command": "cat", "stdin": 3.14})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"] == "3.14"

    def test_zero_stdin_converted_to_string(self):
        """Zero should be converted to '0', not empty."""
        node = ShellNode()
        node.set_params({"command": "cat", "stdin": 0})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"] == "0"


class TestNoneAndString:
    """Test None and string behavior (existing behavior preserved)."""

    def test_none_stdin_means_no_input(self):
        """None should remain None (no input to command)."""
        node = ShellNode()
        node.set_params({"command": "cat", "stdin": None})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"] == ""

    def test_string_stdin_unchanged(self):
        """String should pass through unchanged."""
        node = ShellNode()
        node.set_params({"command": "cat", "stdin": "hello world"})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"] == "hello world"

    def test_empty_string_stdin(self):
        """Empty string should be preserved."""
        node = ShellNode()
        node.set_params({"command": "wc -c", "stdin": ""})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"].strip() == "0"


class TestBytesHandling:
    """Test bytes are decoded to strings."""

    def test_bytes_stdin_decoded_to_utf8(self):
        """Bytes should be decoded to UTF-8."""
        node = ShellNode()
        node.set_params({"command": "cat", "stdin": b"hello bytes"})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"] == "hello bytes"

    def test_bytes_with_utf8_chars(self):
        """UTF-8 encoded bytes should decode correctly."""
        node = ShellNode()
        text = "Hello 世界"
        node.set_params({"command": "cat", "stdin": text.encode("utf-8")})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"] == text


class TestTemplateIntegration:
    """Test type adaptation works with template variables."""

    def test_dict_from_template_variable(self):
        """Dict from template variable should work."""
        inner_node = ShellNode()
        node = TemplateAwareNodeWrapper(inner_node, "test")

        node.set_params({"command": "jq -r '.data.url'", "stdin": "${mcp.result}"})

        shared = {"mcp": {"result": {"data": {"url": "https://example.com"}}}}

        action = node._run(shared)
        assert action == "default"
        assert "https://example.com" in shared["stdout"]

    def test_list_from_template_variable(self):
        """List from template variable should work."""
        inner_node = ShellNode()
        node = TemplateAwareNodeWrapper(inner_node, "test")

        node.set_params({"command": "jq -r '.[1]'", "stdin": "${items}"})

        shared = {"items": ["first", "second", "third"]}

        action = node._run(shared)
        assert action == "default"
        assert "second" in shared["stdout"]

    def test_int_from_template_variable(self):
        """Integer from template variable should work."""
        inner_node = ShellNode()
        node = TemplateAwareNodeWrapper(inner_node, "test")

        node.set_params({"command": "cat", "stdin": "${count}"})

        shared = {"count": 42}

        action = node._run(shared)
        assert action == "default"
        assert shared["stdout"] == "42"

    def test_mcp_json_response(self):
        """Simulates real MCP response (dict) being piped to jq."""
        inner_node = ShellNode()
        node = TemplateAwareNodeWrapper(inner_node, "process-mcp")

        # Simulated MCP response structure
        mcp_result = {
            "successful": True,
            "data": {"valueRanges": [{"values": [["https://open.spotify.com/track/xyz"]]}]},
        }

        node.set_params({"stdin": "${mcp.result}", "command": "jq -r '.data.valueRanges[0].values[0][0]'"})

        shared = {"mcp": {"result": mcp_result}}

        action = node._run(shared)

        # Should extract the Spotify URL
        assert action == "default"
        assert "https://open.spotify.com/track/xyz" in shared["stdout"]


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_unserializable_object_fallback(self):
        """Objects that can't be JSON serialized should fall back to str()."""

        class CustomObject:
            def __str__(self):
                return "custom_string_repr"

        node = ShellNode()
        node.set_params({"command": "cat", "stdin": CustomObject()})
        shared = {}

        # Should not crash, should fall back to str()
        action = node.run(shared)
        assert action == "default"
        assert "custom_string_repr" in shared["stdout"]

    def test_dict_with_none_values(self):
        """Dict with None values should serialize correctly."""
        data = {"key": None, "other": "value"}
        node = ShellNode()
        node.set_params({"command": "jq -r '.other'", "stdin": data})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"].strip() == "value"

    def test_nested_list_of_dicts(self):
        """Nested lists of dicts should serialize correctly."""
        data = [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]
        node = ShellNode()
        node.set_params({"command": "jq -r '.[1].name'", "stdin": data})
        shared = {}

        action = node.run(shared)
        assert action == "default"
        assert shared["stdout"].strip() == "second"


class TestLogging:
    """Test that type conversions are logged appropriately."""

    def test_dict_conversion_logged(self, caplog):
        """Dict to JSON conversion should be logged at INFO level."""
        import logging

        caplog.set_level(logging.INFO)

        node = ShellNode()
        node.set_params({"command": "cat", "stdin": {"key": "value"}})
        shared = {}

        node.run(shared)

        # Check for INFO log about serialization
        assert any("Serialized" in rec.message and "JSON" in rec.message for rec in caplog.records)

    def test_int_conversion_logged(self, caplog):
        """Int to string conversion should be logged at DEBUG level."""
        import logging

        caplog.set_level(logging.DEBUG)

        node = ShellNode()
        node.set_params({"command": "cat", "stdin": 42})
        shared = {}

        node.run(shared)

        # Check for DEBUG log about conversion
        assert any("Converted" in rec.message and "string" in rec.message for rec in caplog.records)
