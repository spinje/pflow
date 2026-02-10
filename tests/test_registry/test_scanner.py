"""
Tests for the node discovery scanner.

REFACTOR HISTORY:
- 2024-01-30: Removed private function tests (camel_to_kebab, get_node_name, etc.)
- 2024-01-30: Simplified complex mock setups - focus on real behavior
- 2024-01-30: Removed security tests that modify global state
- 2024-01-30: Focus on public API behavior and integration scenarios
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pflow.registry.scanner import (
    _calculate_module_path,
    extract_metadata,
    scan_for_nodes,
    temporary_syspath,
)


class TestScannerBehavior:
    """Test scanner behavior that users can observe."""

    def test_scans_real_project_nodes(self):
        """Test scanning actual pflow project nodes."""
        # Get path to our actual project nodes
        project_root = Path(__file__).parent.parent
        nodes_dir = project_root / "src" / "pflow" / "nodes"

        if nodes_dir.exists():
            results = scan_for_nodes([nodes_dir])

            # Should find our real nodes
            # Should contain expected test nodes (these exist in our project)
            assert len(results) > 0

            # Check metadata structure for all found nodes
            for node in results:
                assert "module" in node
                assert "class_name" in node
                assert "name" in node
                assert "docstring" in node
                assert "file_path" in node
                assert node["module"].startswith("pflow.nodes.")
                assert isinstance(node["name"], str)
                assert len(node["name"]) > 0

    def test_handles_nonexistent_directories_gracefully(self):
        """Test that scanning non-existent directories returns empty results."""
        results = scan_for_nodes([Path("/nonexistent/directory")])
        assert results == []

    def test_handles_empty_directories_gracefully(self):
        """Test that scanning empty directories returns empty results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = scan_for_nodes([Path(tmpdir)])
            assert results == []

    def test_ignores_pycache_directories(self):
        """Test that __pycache__ directories are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create __pycache__ directory with file
            pycache = Path(tmpdir) / "__pycache__"
            pycache.mkdir()
            (pycache / "test.py").write_text("class TestNode: pass")

            results = scan_for_nodes([Path(tmpdir)])
            assert results == []

    def test_finds_nodes_with_different_inheritance_patterns(self):
        """Test that both direct and indirect BaseNode subclasses are found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create file with Node import
            node_file = base_dir / "node_based.py"
            node_file.write_text('''
from pflow.pocketflow import Node

class NodeBasedClass(Node):
    """This inherits from Node."""
    def exec(self, shared):
        pass
''')

            # Create file with BaseNode import
            basenode_file = base_dir / "basenode_based.py"
            basenode_file.write_text('''
from pflow.pocketflow import BaseNode

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
            class_names = [node["class_name"] for node in results]
            assert "BaseNodeClass" in class_names
            assert "NodeBasedClass" in class_names

    def test_handles_import_errors_gracefully(self):
        """Test that files with import errors are skipped gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create file with import error
            import_err_file = base_dir / "import_error.py"
            import_err_file.write_text("""
import nonexistent_module

from pflow.pocketflow import BaseNode

class WontLoad(BaseNode):
    def exec(self, shared):
        pass
""")

            # Should handle import error gracefully
            results = scan_for_nodes([base_dir])

            # The file with import error should be skipped
            assert len(results) == 0

    def test_handles_syntax_errors_gracefully(self):
        """Test that files with syntax errors are skipped gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create file with syntax error
            syntax_file = base_dir / "syntax_error.py"
            syntax_file.write_text("""
# Intentional syntax error
def broken(:
    pass
""")

            # Should skip this file without crashing
            results = scan_for_nodes([base_dir])
            assert len(results) == 0

    def test_finds_nodes_with_custom_names(self):
        """Test that nodes with custom name attributes are found correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create node with custom name
            custom_file = base_dir / "custom.py"
            custom_file.write_text('''
from pflow.pocketflow import BaseNode

class CustomNode(BaseNode):
    """Node with custom name."""
    name = "special-custom-name"

    def exec(self, shared):
        shared["custom"] = True
''')

            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            with temporary_syspath([project_root, pocketflow_path, base_dir]):
                results = scan_for_nodes([base_dir])

            # Should find the node with its custom name
            assert len(results) == 1
            assert results[0]["name"] == "special-custom-name"
            assert results[0]["class_name"] == "CustomNode"

    def test_finds_nodes_with_multiple_inheritance(self):
        """Test that nodes with multiple inheritance are detected correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            multi_file = base_dir / "multi_inherit.py"
            multi_file.write_text('''
from pflow.pocketflow import BaseNode

class Mixin:
    def mixin_method(self):
        return "mixin"

class MultiInheritNode(BaseNode, Mixin):
    """Multiple inheritance with BaseNode first."""
    name = "multi-inherit"

    def exec(self, shared):
        shared["mixin"] = self.mixin_method()
''')

            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            with temporary_syspath([project_root, pocketflow_path, base_dir]):
                results = scan_for_nodes([base_dir])

            # Should find the multiple inheritance node
            assert len(results) == 1
            assert results[0]["name"] == "multi-inherit"
            assert results[0]["class_name"] == "MultiInheritNode"

    def test_finds_nodes_with_indirect_inheritance(self):
        """Test that nodes inheriting from BaseNode indirectly are found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            indirect_file = base_dir / "indirect.py"
            indirect_file.write_text('''
from pflow.pocketflow import BaseNode

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

    def test_handles_deeply_nested_packages(self):
        """Test scanning deeply nested package structures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            deep_path = Path(tmpdir) / "a" / "b" / "c" / "d"
            deep_path.mkdir(parents=True)

            # Add init files for proper package structure
            for p in [Path(tmpdir) / "a", Path(tmpdir) / "a" / "b", Path(tmpdir) / "a" / "b" / "c", deep_path]:
                (p / "__init__.py").write_text("")

            # Add a node in the deepest directory
            node_content = '''
from pflow.pocketflow import BaseNode

class DeepNode(BaseNode):
    """A deeply nested node."""
    def exec(self, shared):
        pass
'''
            (deep_path / "deep_node.py").write_text(node_content)

            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            with temporary_syspath([project_root, pocketflow_path, Path(tmpdir)]):
                results = scan_for_nodes([Path(tmpdir)])

            # Should find the deeply nested node
            assert len(results) == 1
            assert results[0]["name"] == "deep"

    def test_handles_special_python_files(self):
        """Test that special Python files are handled without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)

            # Create various special files
            (directory / "__init__.py").write_text("")
            (directory / "setup.py").write_text("# Setup file")
            (directory / "conftest.py").write_text("# Pytest config")

            # Should handle these files without crashing
            results = scan_for_nodes([directory])

            # No nodes expected in these special files
            assert len(results) == 0


class TestExtractMetadataBehavior:
    """Test metadata extraction from node classes."""

    def test_extracts_complete_metadata_from_node(self):
        """Test that complete metadata is extracted from node classes."""

        class TestNode:
            """Test node documentation."""

            name = "test-node"

        # Mock the MetadataExtractor to focus on the integration
        mock_extractor = MagicMock()
        mock_extractor.extract_metadata.return_value = {
            "description": "Test node documentation.",
            "inputs": [{"key": "input1", "type": "str", "description": "Test input"}],
            "outputs": [{"key": "output1", "type": "str", "description": "Test output"}],
            "params": [{"key": "param1", "type": "any", "description": "Test param"}],
            "actions": ["default", "error"],
        }

        metadata = extract_metadata(TestNode, "pflow.nodes.test", Path("/project/test.py"), extractor=mock_extractor)

        # Test that metadata contains expected fields
        assert metadata["module"] == "pflow.nodes.test"
        assert metadata["class_name"] == "TestNode"
        assert metadata["name"] == "test-node"
        assert metadata["docstring"] == "Test node documentation."
        assert "/project/test.py" in metadata["file_path"]

        # Test that interface was integrated
        assert "interface" in metadata
        assert metadata["interface"]["description"] == "Test node documentation."
        assert len(metadata["interface"]["inputs"]) == 1
        assert metadata["interface"]["inputs"][0]["key"] == "input1"

    def test_handles_nodes_without_docstrings(self):
        """Test metadata extraction from nodes without docstrings."""

        class NoDocNode:
            pass

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

    def test_handles_metadata_extraction_errors(self):
        """Test that metadata extraction errors are properly raised."""

        class BadNode:
            """Node that will cause extraction error."""

            pass

        mock_extractor = MagicMock()
        mock_extractor.extract_metadata.side_effect = ValueError("Invalid interface format")

        import pytest

        with pytest.raises(ValueError, match="Invalid interface format"):
            extract_metadata(BadNode, "pflow.nodes.test", Path("/project/test.py"), extractor=mock_extractor)


class TestTemporarySyspathBehavior:
    """Test sys.path context manager behavior."""

    def test_adds_and_removes_paths_correctly(self):
        """Test that paths are added and properly removed from sys.path."""
        original_path = sys.path.copy()
        test_paths = [Path("/test1"), Path("/test2")]

        with temporary_syspath(test_paths):
            # Paths should be added
            assert str(test_paths[0]) in sys.path
            assert str(test_paths[1]) in sys.path

        # Paths should be removed after context
        assert sys.path == original_path

    def test_restores_path_after_exception(self):
        """Test that sys.path is restored even when exceptions occur."""
        original_path = sys.path.copy()

        def raise_error():
            raise ValueError("Test error")

        try:
            with temporary_syspath([Path("/test")]):
                raise_error()
        except ValueError:
            pass

        # Path should still be restored
        assert sys.path == original_path


class TestScannerIntegrationScenarios:
    """Test scanner behavior in realistic integration scenarios."""

    def test_mixed_valid_and_invalid_files(self):
        """Test scanning directory with mix of valid nodes and problem files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            # Create valid node
            valid_file = base_dir / "valid.py"
            valid_file.write_text('''
from pflow.pocketflow import BaseNode

class ValidNode(BaseNode):
    """A valid node among errors."""
    def exec(self, shared):
        pass
''')

            # Create file with syntax error
            (base_dir / "syntax_error.py").write_text("def broken(: pass")

            # Create file with import error
            (base_dir / "import_error.py").write_text("""
import nonexistent
from pflow.pocketflow import BaseNode
class BadNode(BaseNode):
    def exec(self, shared): pass
""")

            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            with temporary_syspath([project_root, pocketflow_path, base_dir]):
                results = scan_for_nodes([base_dir])

            # Should find only the valid node
            assert len(results) == 1
            assert results[0]["name"] == "valid"
            assert results[0]["class_name"] == "ValidNode"

    def test_scans_multiple_directories(self):
        """Test scanning multiple directories at once."""
        with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
            # Create node in first directory
            (Path(tmpdir1) / "node1.py").write_text('''
from pflow.pocketflow import BaseNode
class Node1(BaseNode):
    """First test node."""
    def exec(self, shared): pass
''')

            # Create node in second directory
            (Path(tmpdir2) / "node2.py").write_text('''
from pflow.pocketflow import BaseNode
class Node2(BaseNode):
    """Second test node."""
    def exec(self, shared): pass
''')

            project_root = Path(__file__).parent.parent
            pocketflow_path = project_root / "pocketflow"

            with temporary_syspath([project_root, pocketflow_path, Path(tmpdir1), Path(tmpdir2)]):
                results = scan_for_nodes([Path(tmpdir1), Path(tmpdir2)])

            # Should find nodes from both directories
            class_names = [node["class_name"] for node in results]
            assert "Node1" in class_names
            assert "Node2" in class_names
            assert len(results) == 2


class TestCalculateModulePath:
    """Test _calculate_module_path for source, installed, and non-pflow paths.

    FIX HISTORY:
    - 2025-02-10: Added to verify fix for installed-package module path
      calculation. The old implementation searched upward for a 'src' directory,
      which broke when pflow was pip-installed (site-packages has no 'src').
      The new implementation scans path parts in reverse for the 'pflow'
      package root, working for both source trees and site-packages.
    """

    def test_source_path_produces_full_module(self):
        """A file under src/pflow/ should produce a dotted pflow.* module path."""
        py_file = Path("/Users/x/projects/pflow/src/pflow/nodes/shell/shell.py")
        directory = Path("/Users/x/projects/pflow/src/pflow/nodes/shell")

        result = _calculate_module_path(py_file, directory)

        assert result == "pflow.nodes.shell.shell"

    def test_site_packages_path_produces_full_module(self):
        """A file under site-packages/pflow/ should also produce a dotted pflow.* module path.

        This is the key scenario the fix addresses: installed packages have no
        'src' parent, so the old implementation fell through to the fallback
        and produced an incorrect relative module path.
        """
        py_file = Path("/Users/x/.local/lib/python3.13/site-packages/pflow/nodes/shell/shell.py")
        directory = Path("/Users/x/.local/lib/python3.13/site-packages/pflow/nodes/shell")

        result = _calculate_module_path(py_file, directory)

        assert result == "pflow.nodes.shell.shell"

    def test_non_pflow_path_uses_fallback(self):
        """A file outside any pflow package should fall back to path_to_module."""
        py_file = Path("/home/user/custom_nodes/my_node.py")
        directory = Path("/home/user/custom_nodes")

        result = _calculate_module_path(py_file, directory)

        assert result == "my_node"

    def test_nested_pflow_node_path(self):
        """A nested pflow node file should produce the correct dotted module path."""
        py_file = Path("/some/path/pflow/nodes/file/read_file.py")
        directory = Path("/some/path/pflow/nodes/file")

        result = _calculate_module_path(py_file, directory)

        assert result == "pflow.nodes.file.read_file"
