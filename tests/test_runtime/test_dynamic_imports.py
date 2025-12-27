"""Tests for dynamic node import functionality in the compiler module."""

from unittest.mock import Mock, patch

import pytest

from pflow.registry import Registry
from pflow.runtime.compiler import CompilationError, import_node_class
from pocketflow import BaseNode


class MockValidNode(BaseNode):
    """A mock node that inherits from BaseNode for testing."""

    pass


class MockInvalidNode:
    """A mock class that doesn't inherit from BaseNode."""

    pass


def test_import_node_class_success():
    """Test successful import of a valid node class."""
    # Create mock registry with node metadata
    mock_registry = Mock(spec=Registry)
    mock_registry.load.return_value = {
        "test-node": {
            "module": "test.module",
            "class_name": "ExampleNode",
            "docstring": "Test node",
            "file_path": "/path/to/test.py",
        }
    }

    # Mock the import process
    with patch("pflow.runtime.compiler.importlib.import_module") as mock_import:
        mock_module = Mock()
        mock_module.ExampleNode = MockValidNode
        mock_import.return_value = mock_module

        # Call the function
        result = import_node_class("test-node", mock_registry)

        # Verify results
        assert result is MockValidNode
        mock_registry.load.assert_called_once()
        mock_import.assert_called_once_with("test.module")


def test_import_node_class_not_in_registry():
    """Test error when node type is not found in registry."""
    # Create mock registry without the requested node
    mock_registry = Mock(spec=Registry)
    mock_registry.load.return_value = {"other-node": {"module": "other.module", "class_name": "OtherNode"}}

    # Call the function and expect CompilationError
    with pytest.raises(CompilationError) as exc_info:
        import_node_class("missing-node", mock_registry)

    # Verify error details
    error = exc_info.value
    assert error.phase == "node_resolution"
    assert error.node_type == "missing-node"
    assert "other-node" in error.details["available_nodes"]
    assert "Available node types: other-node" in error.suggestion


def test_import_node_class_module_not_found():
    """Test error when module cannot be imported."""
    # Create mock registry with node metadata
    mock_registry = Mock(spec=Registry)
    mock_registry.load.return_value = {
        "test-node": {
            "module": "non.existent.module",
            "class_name": "ExampleNode",
        }
    }

    # Mock import failure
    with patch("pflow.runtime.compiler.importlib.import_module") as mock_import:
        mock_import.side_effect = ImportError("No module named 'non.existent.module'")

        # Call the function and expect CompilationError
        with pytest.raises(CompilationError) as exc_info:
            import_node_class("test-node", mock_registry)

        # Verify error details
        error = exc_info.value
        assert error.phase == "node_import"
        assert error.node_type == "test-node"
        assert error.details["module_path"] == "non.existent.module"
        assert "No module named" in error.details["import_error"]
        assert "Ensure the module 'non.existent.module' exists" in error.suggestion


def test_import_node_class_class_not_found():
    """Test error when class is not found in module."""
    # Create mock registry with node metadata
    mock_registry = Mock(spec=Registry)
    mock_registry.load.return_value = {
        "test-node": {
            "module": "test.module",
            "class_name": "MissingClass",
        }
    }

    # Mock successful import but missing class
    with patch("pflow.runtime.compiler.importlib.import_module") as mock_import:
        mock_module = Mock(spec=[])  # Module without the expected class
        mock_import.return_value = mock_module

        # Call the function and expect CompilationError
        with pytest.raises(CompilationError) as exc_info:
            import_node_class("test-node", mock_registry)

        # Verify error details
        error = exc_info.value
        assert error.phase == "node_import"
        assert error.node_type == "test-node"
        assert error.details["class_name"] == "MissingClass"
        assert error.details["module_path"] == "test.module"
        assert "Check that 'MissingClass' is defined" in error.suggestion


def test_import_node_class_invalid_inheritance():
    """Test error when class doesn't inherit from BaseNode."""
    # Create mock registry with node metadata
    mock_registry = Mock(spec=Registry)
    mock_registry.load.return_value = {
        "test-node": {
            "module": "test.module",
            "class_name": "InvalidNode",
        }
    }

    # Mock import with invalid node class
    with patch("pflow.runtime.compiler.importlib.import_module") as mock_import:
        mock_module = Mock()
        mock_module.InvalidNode = MockInvalidNode
        mock_import.return_value = mock_module

        # Call the function and expect CompilationError
        with pytest.raises(CompilationError) as exc_info:
            import_node_class("test-node", mock_registry)

        # Verify error details
        error = exc_info.value
        assert error.phase == "node_validation"
        assert error.node_type == "test-node"
        assert error.details["class_name"] == "InvalidNode"
        assert "object" in error.details["actual_bases"]  # MockInvalidNode inherits from object
        assert "Ensure 'InvalidNode' inherits from pocketflow.BaseNode" in error.suggestion


def test_import_node_class_not_a_class():
    """Test error when the attribute is not a class."""
    # Create mock registry with node metadata
    mock_registry = Mock(spec=Registry)
    mock_registry.load.return_value = {
        "test-node": {
            "module": "test.module",
            "class_name": "NotAClass",
        }
    }

    # Mock import with non-class attribute
    with patch("pflow.runtime.compiler.importlib.import_module") as mock_import:
        mock_module = Mock()
        mock_module.NotAClass = "I am a string, not a class"
        mock_import.return_value = mock_module

        # Call the function and expect CompilationError
        with pytest.raises(CompilationError) as exc_info:
            import_node_class("test-node", mock_registry)

        # Verify error details
        error = exc_info.value
        assert error.phase == "node_validation"
        assert error.node_type == "test-node"
        assert error.details["class_name"] == "NotAClass"
        assert error.details["actual_type"] == "str"
        assert "Ensure 'NotAClass' is a class definition" in error.suggestion


def test_import_node_class_with_logging(caplog):
    """Test that structured logging works correctly."""
    # Create mock registry with node metadata
    mock_registry = Mock(spec=Registry)
    mock_registry.load.return_value = {
        "test-node": {
            "module": "test.module",
            "class_name": "ExampleNode",
        }
    }

    # Mock successful import
    with patch("pflow.runtime.compiler.importlib.import_module") as mock_import:
        mock_module = Mock()
        mock_module.ExampleNode = MockValidNode
        mock_import.return_value = mock_module

        # Enable debug logging
        caplog.set_level("DEBUG")

        # Call the function
        import_node_class("test-node", mock_registry)

        # Verify logging
        log_messages = [record.message for record in caplog.records]
        assert "Looking up node in registry" in log_messages
        assert "Found node metadata" in log_messages
        assert "Importing module" in log_messages
        assert "Extracting class from module" in log_messages
        assert "Validating node inheritance" in log_messages
        assert "Node class imported successfully" in log_messages

        # Check phase tracking
        phases = [record.__dict__.get("phase") for record in caplog.records]
        assert "node_resolution" in phases
        assert "node_import" in phases
        assert "node_validation" in phases


# Integration test with real node
def test_import_node_class_real_node():
    """Test importing an actual node from the codebase."""
    # Create real registry instance
    registry = Registry()

    # Use the echo node which is the designated test node in src/pflow/nodes/test/echo.py
    nodes = registry.load()
    if "echo" in nodes:
        # Import the real echo node
        result = import_node_class("echo", registry)

        # Verify it's a proper class
        assert isinstance(result, type)
        assert issubclass(result, BaseNode)
        assert result.__name__ == "EchoNode"
    else:
        # Skip test if registry doesn't have test nodes
        pytest.skip("Echo node not found in registry")
