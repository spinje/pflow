"""
Test the metadata extractor for pflow nodes.
"""

import pytest

import pocketflow
from pflow.registry.metadata_extractor import PflowMetadataExtractor


class TestPflowMetadataExtractor:
    """Test metadata extraction functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.extractor = PflowMetadataExtractor()

    def test_extract_metadata_with_valid_node(self):
        """Test extraction with a valid Node subclass."""

        class TestNode(pocketflow.Node):
            """Test node for validation."""

            pass

        result = self.extractor.extract_metadata(TestNode)

        assert result == {
            "description": "Test node for validation.",
            "inputs": [],
            "outputs": [],
            "params": [],
            "actions": [],
        }

    def test_extract_metadata_with_basenode(self):
        """Test extraction with a BaseNode subclass."""

        class TestBaseNode(pocketflow.BaseNode):
            """BaseNode test implementation."""

            def prep(self):
                pass

            def exec(self):
                pass

            def post(self):
                pass

        result = self.extractor.extract_metadata(TestBaseNode)

        assert result == {
            "description": "BaseNode test implementation.",
            "inputs": [],
            "outputs": [],
            "params": [],
            "actions": [],
        }

    def test_extract_metadata_with_multiline_docstring(self):
        """Test extraction with multiline docstring."""

        class MultilineNode(pocketflow.Node):
            """
            First line is the description.

            This is additional detail that should be ignored in 7.1.
            """

            pass

        result = self.extractor.extract_metadata(MultilineNode)

        assert result["description"] == "First line is the description."

    def test_extract_metadata_without_docstring(self):
        """Test extraction when node has no docstring."""

        class NoDocstringNode(pocketflow.Node):
            pass

        result = self.extractor.extract_metadata(NoDocstringNode)

        assert result["description"] == "No description"

    def test_extract_metadata_with_empty_docstring(self):
        """Test extraction with empty docstring."""

        class EmptyDocstringNode(pocketflow.Node):
            """ """

            pass

        result = self.extractor.extract_metadata(EmptyDocstringNode)

        assert result["description"] == "No description"

    def test_extract_metadata_with_non_node_class(self):
        """Test that non-node classes raise ValueError."""

        class NotANode:
            """Regular class, not a node."""

            pass

        with pytest.raises(ValueError) as exc_info:
            self.extractor.extract_metadata(NotANode)

        assert "does not inherit from pocketflow.BaseNode" in str(exc_info.value)

    def test_extract_metadata_with_instance(self):
        """Test that passing an instance raises ValueError."""

        class TestNode(pocketflow.Node):
            pass

        instance = TestNode()

        with pytest.raises(ValueError) as exc_info:
            self.extractor.extract_metadata(instance)

        assert "Expected a class" in str(exc_info.value)

    def test_extract_metadata_with_none(self):
        """Test that None input raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            self.extractor.extract_metadata(None)

        assert "Expected a class" in str(exc_info.value)

    def test_extract_metadata_with_string(self):
        """Test that string input raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            self.extractor.extract_metadata("NotAClass")

        assert "Expected a class" in str(exc_info.value)

    def test_extract_metadata_error_prefix(self):
        """Test that errors have the correct namespace prefix."""
        with pytest.raises(ValueError) as exc_info:
            self.extractor.extract_metadata(None)

        assert str(exc_info.value).startswith("metadata_extractor:")


class TestRealNodeIntegration:
    """Test with real nodes from the codebase."""

    def setup_method(self):
        """Set up test fixtures."""
        self.extractor = PflowMetadataExtractor()

    def test_extract_from_read_file_node(self):
        """Test extraction from the real ReadFileNode."""
        from src.pflow.nodes.file.read_file import ReadFileNode

        result = self.extractor.extract_metadata(ReadFileNode)

        # The actual first line from the docstring
        assert result["description"] == "Read content from a file and add line numbers for display."
        assert result["inputs"] == ["file_path", "encoding"]
        assert result["outputs"] == ["content", "error"]
        assert result["params"] == ["file_path", "encoding"]
        assert result["actions"] == ["default", "error"]

    def test_extract_from_write_file_node(self):
        """Test extraction from the real WriteFileNode."""
        from src.pflow.nodes.file.write_file import WriteFileNode

        result = self.extractor.extract_metadata(WriteFileNode)

        # The actual first line from the docstring
        assert result["description"] == "Write content to a file with automatic directory creation."
        assert isinstance(result["inputs"], list)
        assert isinstance(result["outputs"], list)
        assert isinstance(result["params"], list)
        assert isinstance(result["actions"], list)


class TestInterfaceParsing:
    """Test Interface section parsing functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.extractor = PflowMetadataExtractor()

    def test_parse_complete_interface(self):
        """Test parsing a complete Interface section."""

        class CompleteNode(pocketflow.Node):
            """Test node with complete Interface.

            Interface:
            - Reads: shared["input1"] (required), shared["input2"] (optional)
            - Writes: shared["output"] on success, shared["error"] on failure
            - Params: param1, param2 (as fallbacks if not in shared)
            - Actions: default (success), error (failure)
            """

            pass

        result = self.extractor.extract_metadata(CompleteNode)

        assert result["inputs"] == ["input1", "input2"]
        assert result["outputs"] == ["output", "error"]
        assert result["params"] == ["param1", "param2"]
        assert result["actions"] == ["default", "error"]

    def test_parse_multiline_interface(self):
        """Test parsing Interface with multi-line continuations."""

        class MultilineNode(pocketflow.Node):
            """Test node with multi-line Interface.

            Interface:
            - Reads: shared["key1"] (required), shared["key2"] (optional),
                    shared["key3"] (optional)
            - Writes: shared["result"] on success, shared["error"] on failure,
                     shared["warning"] on partial success
            - Params: param1, param2, param3 (as fallbacks if not in shared)
            - Actions: default (success), error (failure), retry
            """

            pass

        result = self.extractor.extract_metadata(MultilineNode)

        assert result["inputs"] == ["key1", "key2", "key3"]
        assert result["outputs"] == ["result", "error", "warning"]
        assert result["params"] == ["param1", "param2", "param3"]
        assert result["actions"] == ["default", "error", "retry"]

    def test_missing_interface_section(self):
        """Test node without Interface section returns empty lists."""

        class NoInterfaceNode(pocketflow.Node):
            """Test node without Interface section.

            This node has a docstring but no Interface section.
            """

            pass

        result = self.extractor.extract_metadata(NoInterfaceNode)

        assert result["description"] == "Test node without Interface section."
        assert result["inputs"] == []
        assert result["outputs"] == []
        assert result["params"] == []
        assert result["actions"] == []

    def test_partial_interface_section(self):
        """Test Interface with only some components."""

        class PartialNode(pocketflow.Node):
            """Test node with partial Interface.

            Interface:
            - Reads: shared["data"] (required)
            - Actions: default
            """

            pass

        result = self.extractor.extract_metadata(PartialNode)

        assert result["inputs"] == ["data"]
        assert result["outputs"] == []  # Missing Writes
        assert result["params"] == []  # Missing Params
        assert result["actions"] == ["default"]

    def test_empty_interface_components(self):
        """Test Interface with some empty component values."""

        class SomeEmptyComponentsNode(pocketflow.Node):
            """Test node with some empty Interface components.

            Interface:
            - Reads: shared["input"]
            - Writes: shared["output"]
            - Params: None
            - Actions: default
            """

            pass

        result = self.extractor.extract_metadata(SomeEmptyComponentsNode)

        assert result["inputs"] == ["input"]
        assert result["outputs"] == ["output"]
        assert result["params"] == ["None"]  # Will be treated as a param name
        assert result["actions"] == ["default"]

    def test_complex_param_descriptions(self):
        """Test parsing params with various description formats."""

        class ComplexParamsNode(pocketflow.Node):
            """Test node with complex param descriptions.

            Interface:
            - Reads: shared["input"]
            - Writes: shared["output"]
            - Params: simple, with_default (default: 10), complex (as fallbacks if not in shared)
            - Actions: default
            """

            pass

        result = self.extractor.extract_metadata(ComplexParamsNode)

        # Should extract just the param names
        assert result["params"] == ["simple", "with_default", "complex"]

    def test_actions_with_descriptions(self):
        """Test parsing actions with various description formats."""

        class ActionsNode(pocketflow.Node):
            """Test node with described actions.

            Interface:
            - Reads: shared["input"]
            - Writes: shared["output"]
            - Params: param
            - Actions: default (success), error (failure), retry_failed, custom
            """

            pass

        result = self.extractor.extract_metadata(ActionsNode)

        # Should extract just the action names
        assert result["actions"] == ["default", "error", "retry_failed", "custom"]

    def test_real_read_file_node_interface(self):
        """Test parsing the real ReadFileNode Interface."""
        from src.pflow.nodes.file.read_file import ReadFileNode

        result = self.extractor.extract_metadata(ReadFileNode)

        assert result["description"] == "Read content from a file and add line numbers for display."
        assert result["inputs"] == ["file_path", "encoding"]
        assert result["outputs"] == ["content", "error"]
        assert result["params"] == ["file_path", "encoding"]
        assert result["actions"] == ["default", "error"]

    def test_real_write_file_node_interface(self):
        """Test parsing the real WriteFileNode Interface."""
        from src.pflow.nodes.file.write_file import WriteFileNode

        result = self.extractor.extract_metadata(WriteFileNode)

        assert result["description"] == "Write content to a file with automatic directory creation."
        # WriteFileNode has multi-line Reads section
        assert "content" in result["inputs"]
        assert "file_path" in result["inputs"]
        assert "encoding" in result["inputs"]
        assert "written" in result["outputs"]
        assert "error" in result["outputs"]
        assert result["actions"] == ["default", "error"]

    def test_real_copy_file_node_interface(self):
        """Test parsing the real CopyFileNode Interface."""
        from src.pflow.nodes.file.copy_file import CopyFileNode

        result = self.extractor.extract_metadata(CopyFileNode)

        assert result["description"] == "Copy a file to a new location with automatic directory creation."
        assert "source_path" in result["inputs"]
        assert "dest_path" in result["inputs"]
        assert "overwrite" in result["inputs"]
        assert "copied" in result["outputs"]
        assert result["actions"] == ["default", "error"]

    def test_real_move_file_node_interface(self):
        """Test parsing the real MoveFileNode Interface with multi-line Writes."""
        from src.pflow.nodes.file.move_file import MoveFileNode

        result = self.extractor.extract_metadata(MoveFileNode)

        assert result["description"] == "Move a file to a new location with automatic directory creation."
        assert result["inputs"] == ["source_path", "dest_path", "overwrite"]
        # MoveFileNode has a 3-line Writes section
        assert result["outputs"] == ["moved", "error", "warning"]
        assert result["params"] == ["source_path", "dest_path", "overwrite"]
        assert result["actions"] == ["default", "error"]

    def test_real_delete_file_node_interface(self):
        """Test parsing the real DeleteFileNode Interface with safety notes."""
        from src.pflow.nodes.file.delete_file import DeleteFileNode

        result = self.extractor.extract_metadata(DeleteFileNode)

        assert result["description"] == "Delete a file from the filesystem with safety confirmation."
        assert result["inputs"] == ["file_path", "confirm_delete"]
        assert result["outputs"] == ["deleted", "error"]
        assert result["params"] == ["file_path"]  # Note: confirm_delete is NOT a param
        assert result["actions"] == ["default", "error"]

    def test_no_docstring_node_from_codebase(self):
        """Test parsing NoDocstringNode from the actual codebase."""
        from src.pflow.nodes.test_node import NoDocstringNode

        result = self.extractor.extract_metadata(NoDocstringNode)

        assert result["description"] == "No description"
        assert result["inputs"] == []
        assert result["outputs"] == []
        assert result["params"] == []
        assert result["actions"] == []

    def test_named_node_from_codebase(self):
        """Test parsing NamedNode which has a name but no Interface."""
        from src.pflow.nodes.test_node import NamedNode

        result = self.extractor.extract_metadata(NamedNode)

        assert result["description"] == "Node with explicit name attribute."
        assert result["inputs"] == []
        assert result["outputs"] == []
        assert result["params"] == []
        assert result["actions"] == []

    def test_non_english_characters_in_docstring(self):
        """Test parsing node with non-English characters (Japanese, emoji)."""

        class UnicodeNode(pocketflow.Node):
            """ユニコード対応ノード 🎯 Unicode-enabled node.

            このノードは日本語を含みます。

            Interface:
            - Reads: shared["入力"] (必須), shared["データ"]
            - Writes: shared["結果"] on success ✅, shared["エラー"] on failure ❌
            - Params: パラメータ, encoding (default: utf-8)
            - Actions: default (成功), error (失敗)
            """

            pass

        result = self.extractor.extract_metadata(UnicodeNode)

        assert result["description"] == "ユニコード対応ノード 🎯 Unicode-enabled node."
        assert result["inputs"] == ["入力", "データ"]
        assert result["outputs"] == ["結果", "エラー"]
        assert result["params"] == ["パラメータ", "encoding"]
        assert result["actions"] == ["default", "error"]

    def test_extremely_long_docstring(self):
        """Test parsing node with extremely long docstring (1000+ lines)."""

        # Generate a very long docstring programmatically
        long_description = "Node with extremely long documentation."
        additional_lines = [
            f"Line {i}: This is additional documentation that makes the docstring very long." for i in range(1000)
        ]

        docstring_parts = [
            long_description,
            "",
            *additional_lines,
            "",
            "Interface:",
            '- Reads: shared["input"]',
            '- Writes: shared["output"]',
            "- Params: param",
            "- Actions: default",
        ]
        docstring = "\n".join(docstring_parts)

        class LongDocstringNode(pocketflow.Node):
            pass

        # Manually set the docstring
        LongDocstringNode.__doc__ = docstring

        result = self.extractor.extract_metadata(LongDocstringNode)

        assert result["description"] == long_description
        assert result["inputs"] == ["input"]
        assert result["outputs"] == ["output"]
        assert result["params"] == ["param"]
        assert result["actions"] == ["default"]

    def test_malformed_interface_section(self):
        """Test parsing node with malformed Interface section."""

        class MalformedNode(pocketflow.Node):
            """Node with malformed Interface.

            Interface:
            - Reads shared["input"] (missing colon)
            - Writes: shared["output"
            - Params: param1, param2,, param3 (double comma)
            - Actions default, error (missing colon)
            - Unknown: some value (unknown component)
            """

            pass

        result = self.extractor.extract_metadata(MalformedNode)

        # Should handle gracefully and extract what it can
        assert result["description"] == "Node with malformed Interface."
        # Reads line is malformed (no colon), so won't be parsed
        assert result["inputs"] == []
        # Writes line has unclosed bracket but pattern should still match
        assert result["outputs"] == []  # Malformed shared key
        # Params should handle double comma gracefully
        assert result["params"] == ["param1", "param2", "param3"]
        # Actions line is malformed (no colon)
        assert result["actions"] == []
