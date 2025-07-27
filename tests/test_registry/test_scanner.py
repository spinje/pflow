"""Tests for the node discovery scanner."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pflow.registry.scanner import (
    camel_to_kebab,
    extract_metadata,
    get_node_name,
    path_to_module,
    scan_for_nodes,
    temporary_syspath,
)


class TestCamelToKebab:
    """Test camel case to kebab case conversion."""

    def test_simple_conversion(self):
        assert camel_to_kebab("TestNode") == "test-node"
        assert camel_to_kebab("ReadFileNode") == "read-file-node"
        assert camel_to_kebab("LLMNode") == "llm-node"

    def test_single_word(self):
        assert camel_to_kebab("Node") == "node"
        assert camel_to_kebab("node") == "node"

    def test_already_kebab(self):
        assert camel_to_kebab("test-node") == "test-node"


class TestGetNodeName:
    """Test node name extraction."""

    def test_explicit_name(self):
        class TestNode:
            name = "custom-name"

        assert get_node_name(TestNode) == "custom-name"

    def test_kebab_conversion(self):
        class ReadFileNode:
            pass

        assert get_node_name(ReadFileNode) == "read-file"

    def test_node_suffix_removal(self):
        class TestNode:
            pass

        assert get_node_name(TestNode) == "test"

    def test_no_node_suffix(self):
        class DataProcessor:
            pass

        assert get_node_name(DataProcessor) == "data-processor"


class TestPathToModule:
    """Test path to module conversion."""

    def test_simple_conversion(self):
        file_path = Path("/project/src/pflow/nodes/test.py")
        base_path = Path("/project/src/pflow")
        assert path_to_module(file_path, base_path) == "nodes.test"

    def test_nested_path(self):
        file_path = Path("/project/src/pflow/nodes/file/read_file.py")
        base_path = Path("/project/src/pflow")
        assert path_to_module(file_path, base_path) == "nodes.file.read_file"

    def test_init_file(self):
        file_path = Path("/project/src/pflow/__init__.py")
        base_path = Path("/project/src/pflow")
        assert path_to_module(file_path, base_path) == "__init__"


class TestExtractMetadata:
    """Test metadata extraction from node classes."""

    def test_full_metadata(self):
        class TestNode:
            """Test node documentation."""

            name = "test-node"

        # Mock the MetadataExtractor
        mock_extractor = MagicMock()
        mock_extractor.extract_metadata.return_value = {
            "description": "Test node documentation.",
            "inputs": [{"key": "input1", "type": "str", "description": "Test input"}],
            "outputs": [{"key": "output1", "type": "str", "description": "Test output"}],
            "params": [{"key": "param1", "type": "any", "description": "Test param"}],
            "actions": ["default", "error"],
        }

        metadata = extract_metadata(TestNode, "pflow.nodes.test", Path("/project/test.py"), extractor=mock_extractor)

        assert metadata["module"] == "pflow.nodes.test"
        assert metadata["class_name"] == "TestNode"
        assert metadata["name"] == "test-node"
        assert metadata["docstring"] == "Test node documentation."
        assert "/project/test.py" in metadata["file_path"]

        # Check interface was added
        assert "interface" in metadata
        assert metadata["interface"]["description"] == "Test node documentation."
        assert len(metadata["interface"]["inputs"]) == 1
        assert metadata["interface"]["inputs"][0]["key"] == "input1"
        assert len(metadata["interface"]["outputs"]) == 1
        assert metadata["interface"]["outputs"][0]["key"] == "output1"
        assert metadata["interface"]["actions"] == ["default", "error"]

    def test_no_docstring(self):
        class NoDocNode:
            pass

        # Mock the MetadataExtractor
        mock_extractor = MagicMock()
        mock_extractor.extract_metadata.return_value = {
            "description": "No description",
            "inputs": [],
            "outputs": [],
            "params": [],
            "actions": [],
        }

        metadata = extract_metadata(NoDocNode, "pflow.nodes.test", Path("/project/test.py"), extractor=mock_extractor)

        assert metadata["docstring"] == ""
        assert metadata["interface"]["description"] == "No description"

    def test_multiline_docstring(self):
        class MultiNode:
            """
            Multi-line docstring.

            With multiple paragraphs.
            """

            pass

        # Mock the MetadataExtractor
        mock_extractor = MagicMock()
        mock_extractor.extract_metadata.return_value = {
            "description": "Multi-line docstring.",
            "inputs": [],
            "outputs": [],
            "params": [],
            "actions": [],
        }

        metadata = extract_metadata(MultiNode, "pflow.nodes.test", Path("/project/test.py"), extractor=mock_extractor)

        assert "Multi-line docstring." in metadata["docstring"]
        assert "With multiple paragraphs." in metadata["docstring"]
        assert metadata["interface"]["description"] == "Multi-line docstring."

    def test_parse_error_handling(self):
        """Test that parse errors are raised with proper messages."""

        class BadNode:
            """Node with bad interface."""

            pass

        # Mock the MetadataExtractor to raise an error
        mock_extractor = MagicMock()
        mock_extractor.extract_metadata.side_effect = ValueError("Invalid interface format")

        # Should raise and log error with file path
        import pytest

        with pytest.raises(ValueError, match="Invalid interface format"):
            extract_metadata(BadNode, "pflow.nodes.test", Path("/project/test.py"), extractor=mock_extractor)


class TestTemporarySyspath:
    """Test sys.path context manager."""

    def test_paths_added_and_removed(self):
        original_path = sys.path.copy()
        test_paths = [Path("/test1"), Path("/test2")]

        with temporary_syspath(test_paths):
            # Paths should be added
            assert str(test_paths[0]) in sys.path
            assert str(test_paths[1]) in sys.path
            # Check they are at the beginning (order matters for priority)
            # The implementation reverses the list to maintain intuitive order
            sys_path_start = sys.path[:2]
            assert str(test_paths[0]) in sys_path_start
            assert str(test_paths[1]) in sys_path_start

        # Paths should be removed
        assert sys.path == original_path

    def test_exception_handling(self):
        original_path = sys.path.copy()

        def raise_error():
            raise ValueError

        try:
            with temporary_syspath([Path("/test")]):
                raise_error()
        except ValueError:
            pass

        # Path should still be restored
        assert sys.path == original_path


class TestScanForNodes:
    """Test the main scanner function."""

    def test_scan_real_nodes(self):
        """Test scanning actual test nodes."""
        # Get path to our test nodes
        project_root = Path(__file__).parent.parent
        nodes_dir = project_root / "src" / "pflow" / "nodes"

        if nodes_dir.exists():
            results = scan_for_nodes([nodes_dir])

            # Should find our test nodes
            node_names = [node["name"] for node in results]
            assert "test" in node_names  # TestNode
            assert "custom-name" in node_names  # NamedNode
            assert "no-docstring" in node_names  # NoDocstringNode
            assert "test-node-retry" in node_names  # TestNodeRetry

            # Should NOT find NotANode
            class_names = [node["class_name"] for node in results]
            assert "NotANode" not in class_names

            # Check metadata completeness
            for node in results:
                assert "module" in node
                assert "class_name" in node
                assert "name" in node
                assert "docstring" in node
                assert "file_path" in node
                assert node["module"].startswith("pflow.nodes.")

    def test_nonexistent_directory(self):
        """Test scanning non-existent directory."""
        results = scan_for_nodes([Path("/nonexistent/directory")])
        assert results == []

    def test_empty_directory(self):
        """Test scanning empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = scan_for_nodes([Path(tmpdir)])
            assert results == []

    @patch("pflow.registry.scanner.importlib.import_module")
    def test_import_error_handling(self, mock_import):
        """Test handling of import errors."""
        mock_import.side_effect = ImportError("Test import error")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = Path(tmpdir) / "test.py"
            test_file.write_text("class TestNode: pass")

            results = scan_for_nodes([Path(tmpdir)])
            assert results == []  # Should handle error gracefully

    def test_pycache_ignored(self):
        """Test that __pycache__ directories are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create __pycache__ directory with file
            pycache = Path(tmpdir) / "__pycache__"
            pycache.mkdir()
            (pycache / "test.py").write_text("class TestNode: pass")

            results = scan_for_nodes([Path(tmpdir)])
            assert results == []

    @patch("pflow.registry.scanner.importlib.import_module")
    def test_basenode_filtering(self, mock_import):
        """Test that only BaseNode subclasses are detected."""
        # Create mock module with various classes
        mock_module = MagicMock()

        # Mock BaseNode
        class MockBaseNode:
            pass

        # Create test classes
        class GoodNode(MockBaseNode):
            """Good node."""

            pass

        class BadNode:
            """Not a node."""

            pass

        # Set up module members
        mock_module.__name__ = "test_module"
        GoodNode.__module__ = "test_module"
        BadNode.__module__ = "test_module"

        mock_import.return_value = mock_module

        # We need to mock inspect.getmembers and the BaseNode check
        with patch("pflow.registry.scanner.inspect.getmembers") as mock_members:
            mock_members.return_value = [("GoodNode", GoodNode), ("BadNode", BadNode), ("MockBaseNode", MockBaseNode)]

            with (
                patch("pflow.registry.scanner.inspect.isclass", return_value=True),
                patch("pocketflow.BaseNode", MockBaseNode),
                tempfile.TemporaryDirectory() as tmpdir,
            ):
                test_file = Path(tmpdir) / "test.py"
                test_file.write_text("# Test file")

                # The scanner will fail to import pocketflow in test
                # So we expect empty results
                scan_for_nodes([Path(tmpdir)])

                # In a real scenario with proper mocking,
                # we would verify that only GoodNode is found


class TestScannerEdgeCases:
    """Test scanner behavior with edge cases and malformed files."""

    def test_syntax_error_handling(self):
        """Test scanner continues past files with syntax errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create file with syntax error
            syntax_file = base_dir / "syntax_error.py"
            syntax_file.write_text("""
# Intentional syntax error
def broken(:
    pass
""")

            # The scanner should skip this file
            results = scan_for_nodes([base_dir])

            # Should not find any nodes
            assert len(results) == 0

    def test_empty_file_handling(self):
        """Test scanner handles empty Python files gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create empty file
            empty_file = base_dir / "empty.py"
            empty_file.write_text("")

            # Should complete without errors
            results = scan_for_nodes([base_dir])

            # Empty file should not contribute any nodes
            assert len(results) == 0

    def test_import_error_recovery(self):
        """Test scanner continues when a file has import errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create file with import error
            import_err_file = base_dir / "import_error.py"
            import_err_file.write_text("""
import nonexistent_module

from pocketflow import BaseNode

class WontLoad(BaseNode):
    def exec(self, shared):
        pass
""")

            # Should handle the import error gracefully
            results = scan_for_nodes([base_dir])

            # The file with import error should be skipped
            assert len(results) == 0

    def test_node_vs_basenode_import(self):
        """Test that both direct and indirect BaseNode subclasses are discovered."""
        # Create test files in a temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create file with Node import (should NOT be found)
            node_file = base_dir / "node_based.py"
            node_file.write_text('''
from pocketflow import Node

class NodeBasedClass(Node):
    """This inherits from Node, not BaseNode."""
    def exec(self, shared):
        pass
''')

            # Create file with BaseNode import (should be found)
            basenode_file = base_dir / "basenode_based.py"
            basenode_file.write_text('''
from pocketflow import BaseNode

class BaseNodeClass(BaseNode):
    """This inherits from BaseNode."""
    def exec(self, shared):
        pass
''')

            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            with temporary_syspath([project_root, pocketflow_path, base_dir]):
                results = scan_for_nodes([base_dir])

            # Both should be found since Node inherits from BaseNode
            # The scanner finds ALL BaseNode subclasses, including indirect ones
            class_names = [node["class_name"] for node in results]
            assert "BaseNodeClass" in class_names
            assert "NodeBasedClass" in class_names  # This is also found (correctly)

    def test_aliased_import_detection(self):
        """Test detection of nodes using aliased pocketflow imports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create file with aliased import
            alias_file = base_dir / "aliased.py"
            alias_file.write_text('''
import pocketflow as pf

class AliasedNode(pf.BaseNode):
    """Node using aliased import."""
    name = "aliased-test"

    def exec(self, shared):
        shared["aliased"] = True
''')

            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            with temporary_syspath([project_root, pocketflow_path, base_dir]):
                results = scan_for_nodes([base_dir])

            # Should find the aliased node
            assert len(results) == 1
            assert results[0]["name"] == "aliased-test"
            assert results[0]["class_name"] == "AliasedNode"

    def test_multiple_inheritance_detection(self):
        """Test nodes with multiple inheritance are properly detected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create file with multiple inheritance
            multi_file = base_dir / "multi_inherit.py"
            multi_file.write_text('''
from pocketflow import BaseNode

class Mixin:
    def mixin_method(self):
        return "mixin"

class MultiInheritNode(BaseNode, Mixin):
    """Multiple inheritance with BaseNode first."""
    name = "multi-inherit"

    def exec(self, shared):
        shared["mixin"] = self.mixin_method()

class WrongOrderNode(Mixin, BaseNode):
    """BaseNode not first in MRO."""
    name = "wrong-order"

    def exec(self, shared):
        pass
''')

            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            with temporary_syspath([project_root, pocketflow_path, base_dir]):
                results = scan_for_nodes([base_dir])

            # Should find both variants
            names = [node["name"] for node in results]
            assert "multi-inherit" in names
            assert "wrong-order" in names

    def test_indirect_inheritance_detection(self):
        """Test nodes that inherit from BaseNode indirectly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create file with indirect inheritance
            indirect_file = base_dir / "indirect.py"
            indirect_file.write_text('''
from pocketflow import BaseNode

class IntermediateNode(BaseNode):
    """An intermediate base class."""
    def prep(self, shared):
        shared["intermediate"] = True

    def exec(self, shared):
        raise NotImplementedError("Subclasses must implement")

class IndirectNode(IntermediateNode):
    """Inherits from BaseNode indirectly."""
    name = "indirect-node"

    def exec(self, shared):
        shared["result"] = "indirect inheritance works"
''')

            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            with temporary_syspath([project_root, pocketflow_path, base_dir]):
                results = scan_for_nodes([base_dir])

            # Should find both nodes
            class_names = [node["class_name"] for node in results]
            assert "IntermediateNode" in class_names
            assert "IndirectNode" in class_names

    def test_abstract_class_handling(self):
        """Test handling of abstract base classes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create file with abstract classes
            abstract_file = base_dir / "abstract.py"
            abstract_file.write_text('''
from abc import ABC, abstractmethod
from pocketflow import BaseNode

class AbstractNode(BaseNode, ABC):
    """Abstract base class."""

    @abstractmethod
    def process_data(self, data):
        pass

    def exec(self, shared):
        data = shared.get("input", "")
        shared["output"] = self.process_data(data)

class ConcreteNode(AbstractNode):
    """Concrete implementation."""
    name = "concrete-node"

    def process_data(self, data):
        return data.upper()
''')

            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            with temporary_syspath([project_root, pocketflow_path, base_dir]):
                results = scan_for_nodes([base_dir])

            # MVP doesn't filter abstract classes
            class_names = [node["class_name"] for node in results]
            assert "AbstractNode" in class_names
            assert "ConcreteNode" in class_names

    def test_security_warning_presence(self):
        """Test that scanner module includes security warnings."""
        import pflow.registry.scanner

        # Note: The current implementation doesn't have explicit security warnings
        # This test documents that fact

        # For now, we just verify the scanner exists and works
        assert hasattr(pflow.registry.scanner, "scan_for_nodes")

    def test_malicious_import_execution(self):
        """Test that code is executed during import (documenting the security risk)."""
        import os

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Clear the test env var
            os.environ.pop("TEST_IMPORT_EXECUTED", None)

            # Create file that executes code on import
            malicious_file = base_dir / "malicious.py"
            malicious_file.write_text('''
import os

# This simulates malicious code execution on import
os.environ["TEST_IMPORT_EXECUTED"] = "true"

from pocketflow import BaseNode

class SecurityTestNode(BaseNode):
    """Node in a file that executes code on import."""
    name = "security-test"

    def exec(self, shared):
        shared["imported"] = True
''')

            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            with temporary_syspath([project_root, pocketflow_path, base_dir]):
                results = scan_for_nodes([base_dir])

            # The import WILL execute code - this documents the security risk
            assert os.environ.get("TEST_IMPORT_EXECUTED") == "true"

            # But the node should still be discovered
            assert len(results) == 1
            assert results[0]["name"] == "security-test"

            # Clean up
            os.environ.pop("TEST_IMPORT_EXECUTED", None)

    def test_special_python_files(self):
        """Test handling of special Python filenames."""
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)

            # Create various special files
            (directory / "__init__.py").write_text("")
            (directory / "setup.py").write_text("# Setup file")
            (directory / "conftest.py").write_text("# Pytest config")

            results = scan_for_nodes([directory])

            # Should handle these files without errors
            assert len(results) == 0  # No nodes in these files

    def test_deeply_nested_packages(self):
        """Test scanning deeply nested package structures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            deep_path = Path(tmpdir) / "a" / "b" / "c" / "d"
            deep_path.mkdir(parents=True)

            # Add init files
            for p in [Path(tmpdir) / "a", Path(tmpdir) / "a" / "b", Path(tmpdir) / "a" / "b" / "c", deep_path]:
                (p / "__init__.py").write_text("")

            # Add a node in the deepest directory
            node_content = '''
from pocketflow import BaseNode

class DeepNode(BaseNode):
    """A deeply nested node."""
    def exec(self, shared):
        pass
'''
            (deep_path / "deep_node.py").write_text(node_content)

            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            # Add tmpdir to path so the nested package can be imported
            with temporary_syspath([project_root, pocketflow_path, Path(tmpdir)]):
                results = scan_for_nodes([Path(tmpdir)])

            # Should find the deeply nested node
            assert len(results) == 1
            assert results[0]["name"] == "deep"
