"""Test JSON parsing in MCP text content blocks."""

from unittest.mock import MagicMock

from pflow.nodes.mcp.node import MCPNode
from pflow.runtime.template_resolver import TemplateResolver


class TestJSONTextContentParsing:
    """Test automatic JSON parsing of text content blocks."""

    def test_valid_json_object_is_parsed(self):
        """Test that valid JSON object is parsed into dict."""
        node = MCPNode()
        node.params = {"__mcp_server__": "test", "__mcp_tool__": "test"}

        # Simulate MCP result with JSON text content
        mock_result = MagicMock()
        mock_result.structuredContent = None
        mock_result.isError = False
        mock_content = MagicMock()
        mock_content.text = '{"channels": [{"id": "C123", "name": "general"}]}'
        mock_result.content = [mock_content]

        result = node._extract_result(mock_result)

        # Should be parsed as dict, not string
        assert isinstance(result, dict)
        assert result["channels"][0]["id"] == "C123"
        assert result["channels"][0]["name"] == "general"

    def test_valid_json_array_is_parsed(self):
        """Test that valid JSON array is parsed into list."""
        node = MCPNode()

        mock_content = MagicMock()
        mock_content.text = '[1, 2, 3, {"nested": "value"}]'

        result = node._extract_text_content(mock_content)

        assert isinstance(result, list)
        assert len(result) == 4
        assert result[3]["nested"] == "value"

    def test_malformed_json_returns_string(self):
        """Test that malformed JSON returns original string."""
        node = MCPNode()

        mock_content = MagicMock()
        mock_content.text = '{"incomplete": '

        result = node._extract_text_content(mock_content)

        # Should return as string, not raise exception
        assert isinstance(result, str)
        assert result == '{"incomplete": '

    def test_plain_text_returns_string(self):
        """Test that plain text (non-JSON) returns as string."""
        node = MCPNode()

        mock_content = MagicMock()
        mock_content.text = "Hello, this is just plain text!"

        result = node._extract_text_content(mock_content)

        assert isinstance(result, str)
        assert result == "Hello, this is just plain text!"

    def test_nested_template_access_with_parsed_json(self):
        """Test that nested templates work after JSON parsing."""
        # Simulate parsed MCP result in shared store
        shared = {
            "mcp-node": {
                "result": {  # This was parsed from JSON string
                    "data": {"channels": [{"id": "C123", "name": "general"}]}
                }
            }
        }

        # Test nested template access (simple template - type preserved)
        template = "${mcp-node.result.data.channels[0].id}"
        resolved = TemplateResolver.resolve_template(template, shared)

        assert resolved == "C123"

    def test_json_primitives_are_parsed(self):
        """Test that JSON primitives (null, true, false, numbers) are parsed."""
        node = MCPNode()

        test_cases = [
            ("null", None),
            ("true", True),
            ("false", False),
            ("42", 42),
            ("3.14", 3.14),
            ('"string"', "string"),
        ]

        for json_text, expected in test_cases:
            mock_content = MagicMock()
            mock_content.text = json_text
            result = node._extract_text_content(mock_content)
            assert result == expected, f"Failed for {json_text}"


class TestTemplateSerialization:
    """Test that dict/list values serialize to valid JSON in complex templates."""

    def test_simple_template_preserves_dict_type(self):
        """Test that simple templates preserve dict type (new behavior)."""
        context = {"config": {"channels": ["C123", "C456"], "enabled": True}}

        # Simple template - type preserved
        template = "${config}"
        result = TemplateResolver.resolve_template(template, context)

        # Should return the actual dict, not a JSON string
        assert isinstance(result, dict)
        assert result["channels"] == ["C123", "C456"]
        assert result["enabled"] is True

    def test_complex_template_serializes_dict_to_json(self):
        """Test that dicts in complex templates produce valid JSON (not Python repr)."""
        context = {"config": {"channels": ["C123", "C456"], "enabled": True}}

        # Complex template - dict is serialized to JSON string
        template = "Config: ${config}"
        result = TemplateResolver.resolve_template(template, context)

        # Should be a string with valid JSON embedded
        assert isinstance(result, str)
        assert '"channels"' in result  # JSON uses double quotes
        assert "'channels'" not in result  # Not Python repr

    def test_simple_template_preserves_list_type(self):
        """Test that simple templates preserve list type (new behavior)."""
        context = {"items": [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]}

        # Simple template - type preserved
        template = "${items}"
        result = TemplateResolver.resolve_template(template, context)

        # Should return the actual list, not a JSON string
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "first"

    def test_complex_template_serializes_list_to_json(self):
        """Test that lists in complex templates produce valid JSON."""
        context = {"items": [{"id": 1, "name": "first"}, {"id": 2, "name": "second"}]}

        # Complex template - list is serialized to JSON string
        template = "Items: ${items}"
        result = TemplateResolver.resolve_template(template, context)

        # Should be a string with valid JSON embedded
        assert isinstance(result, str)
        assert "Items: [" in result


class TestComposioScenario:
    """Test the real-world Composio Google Sheets scenario."""

    def test_composio_googlesheets_nested_access(self):
        """Test that Google Sheets Composio results support nested access."""
        node = MCPNode()
        node.params = {"__mcp_server__": "composio", "__mcp_tool__": "googlesheets"}

        # Simulate Composio returning JSON as text (the actual behavior)
        mock_result = MagicMock()
        mock_result.structuredContent = None
        mock_result.isError = False
        mock_content = MagicMock()
        mock_content.text = '{"data": {"valueRanges": [{"values": [["A1", "B1"], ["A2", "B2"]]}]}}'
        mock_result.content = [mock_content]

        result = node._extract_result(mock_result)

        # Should be parsed as dict
        assert isinstance(result, dict)
        assert "data" in result
        assert "valueRanges" in result["data"]

        # Test nested access
        first_cell = result["data"]["valueRanges"][0]["values"][0][0]
        assert first_cell == "A1"

    def test_composio_with_template_resolver(self):
        """Test end-to-end with template resolver (simulating workflow outputs)."""
        # Simulate what happens in a real workflow with namespacing
        shared = {
            "get-sheet-data": {
                "result": {  # This was parsed from JSON string
                    "data": {"valueRanges": [{"values": [["A1", "B1"], ["A2", "B2"]]}]}
                }
            }
        }

        # Test accessing nested data with single array index
        # Simple templates now preserve type (list in this case)
        template1 = "${get-sheet-data.result.data.valueRanges[0].values}"
        resolved1 = TemplateResolver.resolve_template(template1, shared)

        # With type preservation, we get the actual list, not a JSON string
        assert isinstance(resolved1, list)
        assert resolved1 == [["A1", "B1"], ["A2", "B2"]]

        # Test direct access to first range object
        template2 = "${get-sheet-data.result.data.valueRanges[0]}"
        resolved2 = TemplateResolver.resolve_template(template2, shared)

        # With type preservation, we get the actual dict, not a JSON string
        assert isinstance(resolved2, dict)
        assert "values" in resolved2


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_string_returns_empty(self):
        """Test that empty string returns empty string."""
        node = MCPNode()

        mock_content = MagicMock()
        mock_content.text = ""

        result = node._extract_text_content(mock_content)
        assert result == ""

    def test_whitespace_only_returns_original(self):
        """Test that whitespace-only text returns original."""
        node = MCPNode()

        mock_content = MagicMock()
        mock_content.text = "   \n\t   "

        result = node._extract_text_content(mock_content)
        assert result == "   \n\t   "

    def test_json_with_leading_whitespace_is_parsed(self):
        """Test that JSON with leading/trailing whitespace is still parsed."""
        node = MCPNode()

        mock_content = MagicMock()
        mock_content.text = '  \n  {"key": "value"}  \n  '

        result = node._extract_text_content(mock_content)

        # Should be parsed despite whitespace
        assert isinstance(result, dict)
        assert result["key"] == "value"

    def test_multiline_json_is_parsed(self):
        """Test that multiline JSON is parsed correctly."""
        node = MCPNode()

        mock_content = MagicMock()
        mock_content.text = """{
            "channels": [
                {
                    "id": "C123",
                    "name": "general"
                }
            ]
        }"""

        result = node._extract_text_content(mock_content)

        assert isinstance(result, dict)
        assert result["channels"][0]["id"] == "C123"

    def test_unicode_in_json_is_preserved(self):
        """Test that Unicode characters in JSON are preserved."""
        node = MCPNode()

        mock_content = MagicMock()
        mock_content.text = '{"message": "Hello 世界! 🎉"}'

        result = node._extract_text_content(mock_content)

        assert isinstance(result, dict)
        assert result["message"] == "Hello 世界! 🎉"

    def test_nested_quotes_in_json_are_handled(self):
        """Test that nested quotes in JSON strings are handled correctly."""
        node = MCPNode()

        mock_content = MagicMock()
        mock_content.text = r'{"quote": "He said \"hello\" to me"}'

        result = node._extract_text_content(mock_content)

        assert isinstance(result, dict)
        assert result["quote"] == 'He said "hello" to me'
