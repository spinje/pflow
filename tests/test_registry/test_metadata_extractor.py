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

        # Updated to expect rich format
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
        # Now expecting enhanced format with types and descriptions
        assert len(result["inputs"]) == 2
        assert result["inputs"][0] == {"key": "file_path", "type": "str", "description": "Path to the file to read"}
        # Check second input with fixed parser
        assert result["inputs"][1] == {
            "key": "encoding",
            "type": "str",
            "description": "File encoding (optional, default: utf-8)",
        }
        assert result["outputs"] == [
            {"key": "content", "type": "str", "description": "File contents with line numbers"},
            {"key": "error", "type": "str", "description": "Error message if operation failed"},
        ]
        # Check params - with exclusive params pattern, should be empty
        assert result["params"] == []  # All params are automatic fallbacks from Reads!
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

        assert result["inputs"] == [
            {"key": "input1", "type": "any", "description": ""},
            {"key": "input2", "type": "any", "description": ""},
        ]
        assert result["outputs"] == [
            {"key": "output", "type": "any", "description": ""},
            {"key": "error", "type": "any", "description": ""},
        ]
        assert result["params"] == [
            {"key": "param1", "type": "any", "description": ""},
            {"key": "param2", "type": "any", "description": ""},
        ]
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

        assert result["inputs"] == [
            {"key": "key1", "type": "any", "description": ""},
            {"key": "key2", "type": "any", "description": ""},
            {"key": "key3", "type": "any", "description": ""},
        ]
        assert result["outputs"] == [
            {"key": "result", "type": "any", "description": ""},
            {"key": "error", "type": "any", "description": ""},
            {"key": "warning", "type": "any", "description": ""},
        ]
        assert result["params"] == [
            {"key": "param1", "type": "any", "description": ""},
            {"key": "param2", "type": "any", "description": ""},
            {"key": "param3", "type": "any", "description": ""},
        ]
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

        assert result["inputs"] == [{"key": "data", "type": "any", "description": ""}]
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

        assert result["inputs"] == [{"key": "input", "type": "any", "description": ""}]
        assert result["outputs"] == [{"key": "output", "type": "any", "description": ""}]
        assert result["params"] == [
            {"key": "None", "type": "any", "description": ""}
        ]  # Will be treated as a param name
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
        assert result["params"] == [
            {"key": "simple", "type": "any", "description": ""},
            {"key": "with_default", "type": "any", "description": ""},
            {"key": "complex", "type": "any", "description": ""},
        ]

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
        # Now using enhanced format
        assert len(result["inputs"]) == 2
        assert result["inputs"][0]["key"] == "file_path"
        assert result["inputs"][0]["type"] == "str"
        assert result["inputs"][1]["key"] == "encoding"
        assert result["inputs"][1]["type"] == "str"
        # Check outputs use enhanced format too
        assert len(result["outputs"]) == 2
        assert result["outputs"][0]["key"] == "content"
        assert result["outputs"][0]["type"] == "str"
        assert result["outputs"][1]["key"] == "error"
        assert result["outputs"][1]["type"] == "str"
        # Check params - with exclusive params pattern, should be empty
        assert result["params"] == []  # All params are automatic fallbacks from Reads!
        assert result["actions"] == ["default", "error"]

    def test_real_write_file_node_interface(self):
        """Test parsing the real WriteFileNode Interface."""
        from src.pflow.nodes.file.write_file import WriteFileNode

        result = self.extractor.extract_metadata(WriteFileNode)

        assert result["description"] == "Write content to a file with automatic directory creation."
        # WriteFileNode has multi-line Reads section - check keys exist
        input_keys = [item["key"] for item in result["inputs"]]
        assert "content" in input_keys
        assert "file_path" in input_keys
        assert "encoding" in input_keys

        output_keys = [item["key"] for item in result["outputs"]]
        assert "written" in output_keys
        assert "error" in output_keys

        assert result["actions"] == ["default", "error"]

    def test_real_copy_file_node_interface(self):
        """Test parsing the real CopyFileNode Interface."""
        from src.pflow.nodes.file.copy_file import CopyFileNode

        result = self.extractor.extract_metadata(CopyFileNode)

        assert result["description"] == "Copy a file to a new location with automatic directory creation."
        # Extract keys from rich format
        input_keys = [item["key"] for item in result["inputs"]]
        assert "source_path" in input_keys
        assert "dest_path" in input_keys
        assert "overwrite" in input_keys
        output_keys = [item["key"] for item in result["outputs"]]
        assert "copied" in output_keys
        assert result["actions"] == ["default", "error"]

    def test_real_move_file_node_interface(self):
        """Test parsing the real MoveFileNode Interface with multi-line Writes."""
        from src.pflow.nodes.file.move_file import MoveFileNode

        result = self.extractor.extract_metadata(MoveFileNode)

        assert result["description"] == "Move a file to a new location with automatic directory creation."
        # Check inputs in rich format
        input_keys = [item["key"] for item in result["inputs"]]
        assert input_keys == ["source_path", "dest_path", "overwrite"]
        # MoveFileNode has a 3-line Writes section
        output_keys = [item["key"] for item in result["outputs"]]
        assert output_keys == ["moved", "error", "warning"]
        # Check params - with exclusive params pattern, should be empty
        assert result["params"] == []  # All params are automatic fallbacks from Reads!
        assert result["actions"] == ["default", "error"]

    def test_real_delete_file_node_interface(self):
        """Test parsing the real DeleteFileNode Interface with safety notes."""
        from src.pflow.nodes.file.delete_file import DeleteFileNode

        result = self.extractor.extract_metadata(DeleteFileNode)

        assert result["description"] == "Delete a file from the filesystem with safety confirmation."
        # Check inputs in rich format
        input_keys = [item["key"] for item in result["inputs"]]
        assert input_keys == ["file_path", "confirm_delete"]
        # Check outputs in rich format
        output_keys = [item["key"] for item in result["outputs"]]
        assert output_keys == ["deleted", "error"]
        # Check params in rich format
        param_keys = [item["key"] for item in result["params"]]
        assert param_keys == []  # All params are automatic fallbacks from Reads!
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
        # Check in rich format
        input_keys = [item["key"] for item in result["inputs"]]
        assert input_keys == ["入力", "データ"]
        output_keys = [item["key"] for item in result["outputs"]]
        assert output_keys == ["結果", "エラー"]
        param_keys = [item["key"] for item in result["params"]]
        assert param_keys == ["パラメータ", "encoding"]
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
        # Check in rich format
        assert [item["key"] for item in result["inputs"]] == ["input"]
        assert [item["key"] for item in result["outputs"]] == ["output"]
        assert [item["key"] for item in result["params"]] == ["param"]
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
        param_keys = [item["key"] for item in result["params"]]
        assert param_keys == ["param1", "param2", "param3"]
        # Actions line is malformed (no colon)
        assert result["actions"] == []

    def test_extract_metadata_with_enhanced_format(self):
        """Test extraction with enhanced format including types and descriptions."""

        class EnhancedNode(pocketflow.Node):
            """
            Node with enhanced Interface format.

            Interface:
            - Reads: shared["file_path"]: str  # Path to the file
            - Writes: shared["content"]: str, shared["error"]: str  # File contents or error message
            - Params: encoding: str  # File encoding (default: utf-8)
            - Actions: default (success), error (failure)
            """

            pass

        result = self.extractor.extract_metadata(EnhancedNode)

        assert result["description"] == "Node with enhanced Interface format."

        # Check inputs are in rich format
        assert result["inputs"] == [{"key": "file_path", "type": "str", "description": "Path to the file"}]

        # Check outputs are in rich format
        assert result["outputs"] == [
            {"key": "content", "type": "str", "description": "File contents or error message"},
            {"key": "error", "type": "str", "description": "File contents or error message"},
        ]

        # Check params are in rich format
        assert result["params"] == [{"key": "encoding", "type": "str", "description": "File encoding (default: utf-8)"}]

        # Actions remain as simple list
        assert result["actions"] == ["default", "error"]

    def test_enhanced_format_with_nested_structure(self):
        """Test extraction with nested dict structure."""

        class StructuredNode(pocketflow.Node):
            """
            Node with nested structure in Interface.

            Interface:
            - Reads: shared["repo"]: str  # Repository name
            - Writes: shared["issue_data"]: dict
                - number: int  # Issue number
                - user: dict  # Author info
                  - login: str  # GitHub username
                  - id: int  # User ID
                - labels: list  # Issue labels
            - Params: token: str  # GitHub token
            - Actions: default, error
            """

            pass

        result = self.extractor.extract_metadata(StructuredNode)

        assert result["description"] == "Node with nested structure in Interface."

        # Check input
        assert result["inputs"] == [{"key": "repo", "type": "str", "description": "Repository name"}]

        # Check output with structure
        assert len(result["outputs"]) == 1
        output = result["outputs"][0]
        assert output["key"] == "issue_data"
        assert output["type"] == "dict"
        assert output["description"] == ""

        # Check nested structure
        assert "structure" in output
        structure = output["structure"]

        # Check first level fields
        assert structure["number"] == {"type": "int", "description": "Issue number"}
        assert structure["labels"] == {"type": "list", "description": "Issue labels"}

        # Check nested user dict
        assert "user" in structure
        assert structure["user"]["type"] == "dict"
        assert structure["user"]["description"] == "Author info"
        assert "structure" in structure["user"]

        # Check nested user fields
        user_structure = structure["user"]["structure"]
        assert user_structure["login"] == {"type": "str", "description": "GitHub username"}
        assert user_structure["id"] == {"type": "int", "description": "User ID"}

    def test_backward_compatibility_simple_format(self):
        """Test that simple format is converted to rich format with defaults."""

        class SimpleNode(pocketflow.Node):
            """
            Node with simple Interface format.

            Interface:
            - Reads: shared["input1"], shared["input2"]
            - Writes: shared["output1"], shared["output2"]
            - Params: param1, param2
            - Actions: default
            """

            pass

        result = self.extractor.extract_metadata(SimpleNode)

        assert result["description"] == "Node with simple Interface format."

        # Simple format should be converted to rich format with defaults
        assert result["inputs"] == [
            {"key": "input1", "type": "any", "description": ""},
            {"key": "input2", "type": "any", "description": ""},
        ]

        assert result["outputs"] == [
            {"key": "output1", "type": "any", "description": ""},
            {"key": "output2", "type": "any", "description": ""},
        ]

        assert result["params"] == [
            {"key": "param1", "type": "any", "description": ""},
            {"key": "param2", "type": "any", "description": ""},
        ]

        assert result["actions"] == ["default"]
