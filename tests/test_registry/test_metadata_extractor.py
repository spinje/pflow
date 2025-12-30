"""
Test the metadata extractor for pflow nodes.

REFACTOR HISTORY:
- 2024-01-30: Consolidated 40+ implementation detail tests into 12 behavior-focused tests
- 2024-01-30: Removed exact dictionary structure tests, now test actual behavior
- 2024-01-30: Focus on what users can observe, not internal parser mechanics
"""

import pytest

import pocketflow
from pflow.registry.metadata_extractor import PflowMetadataExtractor


class TestMetadataExtractorBehavior:
    """Test metadata extraction behavior that users can observe."""

    def setup_method(self):
        """Set up test fixtures."""
        self.extractor = PflowMetadataExtractor()

    def test_extracts_description_from_docstring(self):
        """Test that node descriptions are extracted from docstrings."""

        class DocumentedNode(pocketflow.Node):
            """This is a test node for validation."""

            pass

        result = self.extractor.extract_metadata(DocumentedNode)

        # Test actual behavior - description extraction
        assert "test node" in result["description"].lower()
        assert result["description"] != "No description"

    def test_handles_missing_docstring_gracefully(self):
        """Test that nodes without docstrings are handled gracefully."""

        class UndocumentedNode(pocketflow.Node):
            pass

        result = self.extractor.extract_metadata(UndocumentedNode)

        # Should provide default description
        assert result["description"] == "No description"
        # Should still have all required fields
        assert "inputs" in result
        assert "outputs" in result
        assert "params" in result
        assert "actions" in result

    def test_extracts_interface_components_from_docstring(self):
        """Test that Interface sections are parsed into structured data."""

        class InterfaceNode(pocketflow.Node):
            """
            Node with complete Interface section.

            Interface:
            - Reads: shared["input_data"], shared["config"]
            - Writes: shared["output"], shared["status"]
            - Params: mode, verbose
            - Actions: default, retry, error
            """

            pass

        result = self.extractor.extract_metadata(InterfaceNode)

        # Test that interface components are extracted
        assert len(result["inputs"]) == 2
        assert any(inp["key"] == "input_data" for inp in result["inputs"])
        assert any(inp["key"] == "config" for inp in result["inputs"])

        assert len(result["outputs"]) == 2
        assert any(out["key"] == "output" for out in result["outputs"])
        assert any(out["key"] == "status" for out in result["outputs"])

        assert len(result["params"]) == 2
        assert any(param["key"] == "mode" for param in result["params"])
        assert any(param["key"] == "verbose" for param in result["params"])

        assert result["actions"] == ["default", "retry", "error"]

    def test_extracts_type_information_from_enhanced_format(self):
        """Test that enhanced format with types is correctly parsed."""

        class EnhancedNode(pocketflow.Node):
            """
            Node with enhanced Interface format.

            Interface:
            - Reads: shared["file_path"]: str  # Path to the file
            - Writes: shared["content"]: str  # File contents
            - Params: encoding: str  # File encoding
            - Actions: default, error
            """

            pass

        result = self.extractor.extract_metadata(EnhancedNode)

        # Test that type information is extracted
        input_item = next(inp for inp in result["inputs"] if inp["key"] == "file_path")
        assert input_item["type"] == "str"
        assert "path" in input_item["description"].lower()

        output_item = next(out for out in result["outputs"] if out["key"] == "content")
        assert output_item["type"] == "str"

        param_item = next(param for param in result["params"] if param["key"] == "encoding")
        assert param_item["type"] == "str"

    def test_handles_complex_nested_structures(self):
        """Test that complex nested structures are parsed correctly."""

        class StructuredNode(pocketflow.Node):
            """
            Node with nested structure.

            Interface:
            - Writes: shared["user_data"]: dict
                - name: str  # User name
                - profile: dict  # User profile
                  - age: int  # User age
                  - email: str  # User email
            - Actions: default
            """

            pass

        result = self.extractor.extract_metadata(StructuredNode)

        # Test that nested structure is extracted
        output_item = next(out for out in result["outputs"] if out["key"] == "user_data")
        assert output_item["type"] == "dict"
        assert "structure" in output_item

        # Test nested structure content
        structure = output_item["structure"]
        assert "name" in structure
        assert structure["name"]["type"] == "str"
        assert "profile" in structure
        assert structure["profile"]["type"] == "dict"
        assert "structure" in structure["profile"]

    def test_works_with_real_node_implementations(self):
        """Test extraction from actual pflow node implementations."""
        from src.pflow.nodes.file.read_file import ReadFileNode

        result = self.extractor.extract_metadata(ReadFileNode)

        # Test that real nodes are handled correctly
        assert result["description"] != "No description"
        # All inputs are now params (no more Reads: shared["key"] pattern)
        assert len(result["params"]) > 0

        # Should have file_path param
        assert any(p["key"] == "file_path" for p in result["params"])

        # Should have type information (enhanced format)
        file_path_param = next(p for p in result["params"] if p["key"] == "file_path")
        assert file_path_param["type"] == "str"

    def test_backward_compatibility_with_simple_format(self):
        """Test that simple format is converted to rich format."""

        class SimpleNode(pocketflow.Node):
            """
            Node with simple Interface format.

            Interface:
            - Reads: shared["input1"], shared["input2"]
            - Writes: shared["output1"], shared["output2"]
            - Actions: default
            """

            pass

        result = self.extractor.extract_metadata(SimpleNode)

        # Test that simple format is normalized to rich format
        assert all(isinstance(inp, dict) for inp in result["inputs"])
        assert all("key" in inp and "type" in inp and "description" in inp for inp in result["inputs"])

        # Should have default type and empty description
        for inp in result["inputs"]:
            assert inp["type"] == "any"
            assert inp["description"] == ""

    def test_validates_node_class_inheritance(self):
        """Test that only valid node classes are accepted."""

        class NotANode:
            """Regular class, not a node."""

            pass

        with pytest.raises(ValueError, match="does not inherit from pocketflow.BaseNode"):
            self.extractor.extract_metadata(NotANode)

    def test_validates_input_is_class(self):
        """Test that non-class inputs are rejected."""

        with pytest.raises(ValueError, match="Expected a class"):
            self.extractor.extract_metadata("not a class")

        with pytest.raises(ValueError, match="Expected a class"):
            self.extractor.extract_metadata(42)

    def test_handles_malformed_interface_gracefully(self):
        """Test that malformed Interface sections don't crash the extractor."""

        class MalformedNode(pocketflow.Node):
            """Node with malformed Interface.

            Interface:
            - Reads shared["input"] (missing colon)
            - Writes: shared["output"
            - Actions default, error (missing colon)
            """

            pass

        # Should not raise an exception
        result = self.extractor.extract_metadata(MalformedNode)

        # Should still return a valid structure
        assert isinstance(result, dict)
        assert "inputs" in result
        assert "outputs" in result
        assert "params" in result
        assert "actions" in result

    def test_handles_unicode_content(self):
        """Test that unicode in docstrings is handled correctly."""

        class UnicodeNode(pocketflow.Node):
            """
            Node with unicode → symbols.

            Interface:
            - Actions: default
            """

            pass

        result = self.extractor.extract_metadata(UnicodeNode)

        # Should handle unicode in descriptions
        assert "→" in result["description"]
        assert isinstance(result["description"], str)

    def test_extracts_from_basenode_subclasses(self):
        """Test that BaseNode subclasses are handled correctly."""

        class TestBaseNode(pocketflow.BaseNode):
            """BaseNode test implementation."""

            def prep(self):
                pass

            def exec(self):
                pass

            def post(self):
                pass

        result = self.extractor.extract_metadata(TestBaseNode)

        # Should work the same as Node subclasses
        assert result["description"] == "BaseNode test implementation."
        assert "inputs" in result
        assert "outputs" in result
        assert "params" in result
        assert "actions" in result
