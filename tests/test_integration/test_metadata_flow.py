"""
Test the full metadata flow from docstring to context builder output.

This tests the integration between:
1. Node docstring with enhanced format
2. Metadata extractor parsing
3. Context builder formatting
"""

import pocketflow
from pflow.planning.context_builder import _format_node_section_enhanced
from pflow.registry.metadata_extractor import PflowMetadataExtractor


class TestMetadataFlow:
    """Test the complete metadata flow through the system."""

    def test_enhanced_format_flow_simple_types(self):
        """Test flow with simple type annotations."""

        class ReadFileNode(pocketflow.Node):
            """
            Read content from a file.

            Interface:
            - Reads: shared["file_path"]: str  # Path to the file to read
            - Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
            - Writes: shared["content"]: str  # File contents
            - Writes: shared["error"]: str  # Error message if operation failed
            - Actions: default (success), error (failure)
            """

            def exec(self, prep_res):
                return "test"

        # Extract metadata
        extractor = PflowMetadataExtractor()
        metadata = extractor.extract_metadata(ReadFileNode)

        # Verify metadata has types
        assert len(metadata["inputs"]) == 2
        assert metadata["inputs"][0]["key"] == "file_path"
        assert metadata["inputs"][0]["type"] == "str"
        assert "Path to the file" in metadata["inputs"][0]["description"]

        assert len(metadata["outputs"]) == 2
        assert metadata["outputs"][0]["key"] == "content"
        assert metadata["outputs"][0]["type"] == "str"

        # Format node section as context builder would
        node_data = {
            "description": metadata["description"],
            "inputs": metadata["inputs"],
            "outputs": metadata["outputs"],
            "params": metadata["params"],
            "actions": metadata["actions"],
        }

        formatted = _format_node_section_enhanced("read-file", node_data)

        # Verify formatted output includes type information
        assert "### read-file" in formatted
        assert "`file_path: str`" in formatted
        assert "Path to the file to read" in formatted
        assert "`content: str`" in formatted
        assert "File contents" in formatted

    def test_enhanced_format_flow_complex_structure(self):
        """Test flow with complex nested structures."""

        class GitHubGetIssueNode(pocketflow.Node):
            """
            Get GitHub issue details.

            Interface:
            - Reads: shared["issue_number"]: int  # Issue number to fetch
            - Reads: shared["repo"]: str  # Repository name (owner/repo)
            - Writes: shared["issue_data"]: dict  # Complete issue information
            - Writes: shared["error"]: str  # Error message if failed
            - Params: token: str  # GitHub API token
            - Actions: default (success), error (failure)
            """

            def exec(self, prep_res):
                return {"number": 123}

        # Extract metadata
        extractor = PflowMetadataExtractor()
        metadata = extractor.extract_metadata(GitHubGetIssueNode)

        # Verify complex type detected
        issue_data = next(out for out in metadata["outputs"] if out["key"] == "issue_data")
        assert issue_data["type"] == "dict"

        # Format node section
        node_data = {
            "description": metadata["description"],
            "inputs": metadata["inputs"],
            "outputs": metadata["outputs"],
            "params": metadata["params"],
            "actions": metadata["actions"],
        }

        formatted = _format_node_section_enhanced("github-get-issue", node_data)

        # Verify context shows dict type
        assert "`issue_data: dict`" in formatted
        assert "Complete issue information" in formatted
        assert "`token: str`" in formatted  # Exclusive param shown

    def test_exclusive_params_in_flow(self):
        """Test that exclusive params pattern works through the flow."""

        class WriteFileNode(pocketflow.Node):
            """
            Write content to a file.

            Interface:
            - Reads: shared["file_path"]: str  # Path to the file
            - Reads: shared["content"]: str  # Content to write
            - Writes: shared["success"]: bool  # True if written successfully
            - Params: append: bool  # Append mode (default: false)
            - Actions: default
            """

            def exec(self, prep_res):
                return True

        # Extract metadata
        extractor = PflowMetadataExtractor()
        metadata = extractor.extract_metadata(WriteFileNode)

        # Verify params extracted
        assert len(metadata["params"]) == 1
        assert metadata["params"][0]["key"] == "append"

        # Format node section
        node_data = {
            "description": metadata["description"],
            "inputs": metadata["inputs"],
            "outputs": metadata["outputs"],
            "params": metadata["params"],
            "actions": metadata["actions"],
        }

        formatted = _format_node_section_enhanced("write-file", node_data)

        # Verify params shown correctly with new format
        assert "**Parameters**:" in formatted
        assert "- `append: bool`" in formatted
        assert "Append mode" in formatted
        # With new format, ALL params (including former inputs) are in Parameters section
        assert "`file_path: str`" in formatted
        assert "`content: str`" in formatted

    def test_backward_compatibility_flow(self):
        """Test that old format still works through the flow."""

        class OldNode(pocketflow.Node):
            """
            Old style node.

            Interface:
            - Reads: shared["input1"], shared["input2"]
            - Writes: shared["output"]
            - Params: param1, param2
            - Actions: default
            """

            def exec(self, prep_res):
                return "test"

        # Extract metadata
        extractor = PflowMetadataExtractor()
        metadata = extractor.extract_metadata(OldNode)

        # Old format should be converted to rich format
        assert len(metadata["inputs"]) == 2
        assert metadata["inputs"][0]["key"] == "input1"
        assert metadata["inputs"][0]["type"] == "any"  # Default type
        assert metadata["inputs"][0]["description"] == ""  # No description

        # Format node section
        node_data = {
            "description": metadata["description"],
            "inputs": metadata["inputs"],
            "outputs": metadata["outputs"],
            "params": metadata["params"],
            "actions": metadata["actions"],
        }

        formatted = _format_node_section_enhanced("old-node", node_data)

        # Old format should still display (with explicit types even if "any")
        assert "`input1: any`" in formatted
        assert "`output: any`" in formatted

    def test_multi_line_format_flow(self):
        """Test multi-line enhanced format through the flow."""

        class MultiLineNode(pocketflow.Node):
            """
            Node using multi-line format.

            Interface:
            - Reads: shared["config"]: dict  # Configuration object
            - Reads: shared["data"]: list  # Data array to process
            - Reads: shared["mode"]: str  # Processing mode
            - Writes: shared["results"]: list  # Processed results
            - Writes: shared["stats"]: dict  # Processing statistics
            - Writes: shared["error"]: str  # Error if any
            - Actions: default, error
            """

            def exec(self, prep_res):
                return []

        # Extract metadata
        extractor = PflowMetadataExtractor()
        metadata = extractor.extract_metadata(MultiLineNode)

        # Verify all lines extracted
        assert len(metadata["inputs"]) == 3
        assert len(metadata["outputs"]) == 3

        # Verify types and descriptions preserved
        config = next(inp for inp in metadata["inputs"] if inp["key"] == "config")
        assert config["type"] == "dict"
        assert "Configuration object" in config["description"]

        # Format node section
        node_data = {
            "description": metadata["description"],
            "inputs": metadata["inputs"],
            "outputs": metadata["outputs"],
            "params": metadata["params"],
            "actions": metadata["actions"],
        }

        formatted = _format_node_section_enhanced("multi-line-node", node_data)

        # Verify all inputs/outputs shown with types
        assert "`config: dict`" in formatted
        assert "`data: list`" in formatted
        assert "`results: list`" in formatted
        assert "Configuration object" in formatted
        assert "Processed results" in formatted

    def test_punctuation_in_descriptions(self):
        """Test that complex punctuation in descriptions is preserved."""

        class PunctuationNode(pocketflow.Node):
            """
            Node with complex punctuation.

            Interface:
            - Reads: shared["file"]: str  # File path (required, no default)
            - Reads: shared["options"]: dict  # Options: mode='r', encoding='utf-8'
            - Writes: shared["data"]: str  # Data: formatted as "key: value" pairs
            - Params: validate: bool  # Validate input (default: true, recommended)
            - Actions: default
            """

            def exec(self, prep_res):
                return ""

        # Extract metadata
        extractor = PflowMetadataExtractor()
        metadata = extractor.extract_metadata(PunctuationNode)

        # Verify punctuation preserved
        file_input = metadata["inputs"][0]
        assert "(required, no default)" in file_input["description"]

        options_input = metadata["inputs"][1]
        assert "mode='r', encoding='utf-8'" in options_input["description"]

        data_output = metadata["outputs"][0]
        assert '"key: value"' in data_output["description"]

        validate_param = metadata["params"][0]
        assert "(default: true, recommended)" in validate_param["description"]
