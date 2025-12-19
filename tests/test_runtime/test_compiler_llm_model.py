"""Test LLM model injection and validation in compiler."""

from unittest.mock import MagicMock, patch

import pytest

from pflow.runtime.compiler import CompilationError, _create_single_node


class TestLLMModelInjection:
    """Test LLM node model injection at compile time."""

    @pytest.fixture
    def mock_registry(self):
        """Create mock registry with LLM node."""
        registry = MagicMock()
        registry.load.return_value = {
            "llm": {
                "module": "pflow.nodes.llm.llm",
                "class_name": "LLMNode",
                "type": "core",
                "interface": {"params": [{"name": "model"}, {"name": "prompt"}]},
            }
        }
        return registry

    @pytest.fixture
    def mock_read_file_registry(self):
        """Create mock registry with read-file node."""
        registry = MagicMock()
        registry.load.return_value = {
            "read-file": {
                "module": "pflow.nodes.file.read_file",
                "class_name": "ReadFileNode",
                "type": "core",
                "interface": {},
            }
        }
        return registry

    def test_uses_explicit_model_from_ir(self, mock_registry):
        """Model specified in IR is used, not overridden."""
        node_data = {"id": "my-llm", "type": "llm", "params": {"model": "gpt-5.2", "prompt": "Hi"}}

        with patch("pflow.core.llm_config.get_default_workflow_model") as mock_get:
            mock_get.return_value = "different-model"

            with patch("pflow.runtime.compiler.import_node_class") as mock_import:
                mock_node = MagicMock()
                mock_import.return_value = lambda: mock_node

                _create_single_node(node_data, mock_registry, {}, False, "strict")

                # get_default_workflow_model should NOT be called since model is specified
                mock_get.assert_not_called()

    def test_injects_settings_default_model(self, mock_registry):
        """Uses configured default when no model in IR."""
        node_data = {"id": "my-llm", "type": "llm", "params": {"prompt": "Hi"}}

        with patch("pflow.core.llm_config.get_default_workflow_model") as mock_get:
            mock_get.return_value = "gpt-5.2"

            with patch("pflow.runtime.compiler.import_node_class") as mock_import:
                mock_node = MagicMock()
                mock_import.return_value = lambda: mock_node

                _create_single_node(node_data, mock_registry, {}, False, "strict")

                # Verify get_default_workflow_model was called
                mock_get.assert_called_once()

    def test_fails_when_no_model_configured(self, mock_registry):
        """Raises CompilationError when no model configured anywhere."""
        node_data = {"id": "my-llm", "type": "llm", "params": {"prompt": "Hi"}}

        with patch("pflow.core.llm_config.get_default_workflow_model") as mock_get:
            mock_get.return_value = None  # Nothing configured

            with pytest.raises(CompilationError) as exc_info:
                _create_single_node(node_data, mock_registry, {}, False, "strict")

            error = exc_info.value
            assert "my-llm" in str(error)
            assert "No model configured" in str(error)
            assert "settings.json" in error.suggestion
            assert "llm models default" in error.suggestion

    def test_non_llm_nodes_not_affected(self, mock_read_file_registry):
        """Non-LLM nodes don't trigger model injection."""
        node_data = {"id": "reader", "type": "read-file", "params": {"path": "./test.txt"}}

        with patch("pflow.core.llm_config.get_default_workflow_model") as mock_get:
            mock_get.return_value = "some-model"

            with patch("pflow.runtime.compiler.import_node_class") as mock_import:
                mock_node = MagicMock()
                mock_import.return_value = lambda: mock_node

                _create_single_node(node_data, mock_read_file_registry, {}, False, "strict")

                # Should not call get_default_workflow_model for non-llm nodes
                mock_get.assert_not_called()

    def test_does_not_mutate_original_ir(self, mock_registry):
        """Model injection creates new dict, doesn't mutate IR."""
        original_params = {"prompt": "Hi"}
        node_data = {"id": "my-llm", "type": "llm", "params": original_params}

        with patch("pflow.core.llm_config.get_default_workflow_model") as mock_get:
            mock_get.return_value = "gpt-5.2"

            with patch("pflow.runtime.compiler.import_node_class") as mock_import:
                mock_node = MagicMock()
                mock_import.return_value = lambda: mock_node

                _create_single_node(node_data, mock_registry, {}, False, "strict")

                # Original params should NOT be mutated
                assert "model" not in original_params

    def test_error_message_includes_helpful_suggestions(self, mock_registry):
        """Error message includes all three configuration methods."""
        node_data = {"id": "test-llm", "type": "llm", "params": {"prompt": "Test"}}

        with patch("pflow.core.llm_config.get_default_workflow_model") as mock_get:
            mock_get.return_value = None

            with pytest.raises(CompilationError) as exc_info:
                _create_single_node(node_data, mock_registry, {}, False, "strict")

            suggestion = exc_info.value.suggestion

            # All three methods should be mentioned
            assert "workflow" in suggestion.lower()  # Method 1
            assert "settings.json" in suggestion  # Method 2
            assert "llm models default" in suggestion  # Method 3

            # Helpful commands should be included
            assert "llm models list" in suggestion
            assert "llm keys list" in suggestion
