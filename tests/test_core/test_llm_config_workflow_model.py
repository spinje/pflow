"""Test get_default_workflow_model, get_model_for_feature, and related functions."""

from unittest.mock import MagicMock, patch

from pflow.core.llm_config import (
    get_default_workflow_model,
    get_model_for_feature,
    get_model_not_configured_help,
)


class TestGetDefaultWorkflowModel:
    """Test workflow model resolution."""

    def test_returns_settings_default_model(self):
        """Returns settings.llm.default_model when configured."""
        mock_settings = MagicMock()
        mock_settings.llm.default_model = "gpt-5.2"

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            result = get_default_workflow_model()

            assert result == "gpt-5.2"

    def test_falls_back_to_auto_detect(self):
        """Falls back to auto-detect when settings not configured."""
        mock_settings = MagicMock()
        mock_settings.llm.default_model = None

        with (
            patch("pflow.core.llm_config.SettingsManager") as MockManager,
            patch(
                "pflow.core.llm_config.get_default_llm_model",
                return_value="anthropic/claude-sonnet-4-5",
            ),
        ):
            MockManager.return_value.load.return_value = mock_settings

            result = get_default_workflow_model()

            assert result == "anthropic/claude-sonnet-4-5"

    def test_returns_none_when_nothing_configured(self):
        """Returns None when settings and auto-detect both return None."""
        mock_settings = MagicMock()
        mock_settings.llm.default_model = None

        with (
            patch("pflow.core.llm_config.SettingsManager") as MockManager,
            patch(
                "pflow.core.llm_config.get_default_llm_model",
                return_value=None,
            ),
        ):
            MockManager.return_value.load.return_value = mock_settings

            result = get_default_workflow_model()

            assert result is None

    def test_settings_takes_priority_over_auto_detect(self):
        """Settings default_model takes priority over auto-detection."""
        mock_settings = MagicMock()
        mock_settings.llm.default_model = "settings-model"

        with (
            patch("pflow.core.llm_config.SettingsManager") as MockManager,
            patch(
                "pflow.core.llm_config.get_default_llm_model",
                return_value="auto-detected-model",
            ),
        ):
            MockManager.return_value.load.return_value = mock_settings

            result = get_default_workflow_model()

            # Settings wins over auto-detect
            assert result == "settings-model"

    def test_handles_settings_load_failure(self):
        """Falls back to auto-detect if settings fail to load."""
        with (
            patch("pflow.core.llm_config.SettingsManager") as MockManager,
            patch(
                "pflow.core.llm_config.get_default_llm_model",
                return_value="fallback-model",
            ),
        ):
            MockManager.return_value.load.side_effect = Exception("Settings error")

            result = get_default_workflow_model()

            assert result == "fallback-model"


class TestGetModelNotConfiguredHelp:
    """Test help message generation."""

    def test_includes_node_id(self):
        """Help message includes the node ID."""
        help_text = get_model_not_configured_help("my-custom-llm")
        assert "my-custom-llm" in help_text

    def test_mentions_auto_detect_failure(self):
        """Help message explains that auto-detection was tried."""
        help_text = get_model_not_configured_help("test-node")

        assert "no default could be detected" in help_text
        assert "pflow tried to auto-detect" in help_text
        assert "no API keys were found" in help_text

    def test_api_key_setup_is_first_option(self):
        """Help message shows API key setup as first option."""
        help_text = get_model_not_configured_help("test-node")

        # Check API key setup is option 1
        assert "1. Set an API key" in help_text
        assert "pflow settings set-env OPENAI_API_KEY" in help_text
        assert "pflow settings set-env ANTHROPIC_API_KEY" in help_text
        assert "pflow settings set-env GEMINI_API_KEY" in help_text

    def test_includes_pflow_native_configuration_methods(self):
        """Help message shows the pflow-native configuration methods."""
        help_text = get_model_not_configured_help("test-node")

        assert "Set an API key" in help_text  # Method 1: API key
        assert "model" in help_text  # Method 2: workflow param
        assert "set-default" in help_text  # Method 3: pflow settings llm set-default
        # Should NOT reference Simon Willison's `llm` CLI any more
        assert "llm models default" not in help_text
        assert "llm models list" not in help_text
        assert "llm keys list" not in help_text

    def test_includes_pflow_settings_show_pointer(self):
        """Help message tells the user how to view configured pflow models."""
        help_text = get_model_not_configured_help("test-node")

        assert "pflow settings llm show" in help_text

    def test_formats_workflow_examples_correctly(self):
        """Help message has properly formatted markdown workflow examples."""
        help_text = get_model_not_configured_help("my-node")

        # Check that the markdown example includes the node ID and a
        # provider-prefixed model (LiteLLM rejects bare names).
        assert "### my-node" in help_text
        assert "- model: openai/gpt-5.2" in help_text


class TestGetModelForFeature:
    """Test get_model_for_feature resolution chain."""

    def test_returns_feature_specific_model_when_set(self):
        """Returns discovery_model when explicitly configured."""
        mock_settings = MagicMock()
        mock_settings.llm.discovery_model = "discovery-specific-model"
        mock_settings.llm.default_model = "default-model"

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            result = get_model_for_feature("discovery")

            assert result == "discovery-specific-model"

    def test_falls_back_to_default_model(self):
        """Falls back to default_model when feature-specific not set."""
        mock_settings = MagicMock()
        mock_settings.llm.discovery_model = None
        mock_settings.llm.default_model = "shared-default-model"

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            result = get_model_for_feature("discovery")

            assert result == "shared-default-model"

    def test_falls_back_to_auto_detect_when_no_default(self):
        """Falls back to auto-detect when neither feature nor default set."""
        mock_settings = MagicMock()
        mock_settings.llm.filtering_model = None
        mock_settings.llm.default_model = None

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            with patch(
                "pflow.core.llm_config.get_default_llm_model",
                return_value="auto-detected-model",
            ):
                result = get_model_for_feature("filtering")

                assert result == "auto-detected-model"

    def test_falls_back_to_hardcoded_fallback(self):
        """Falls back to hardcoded value when nothing else available."""
        mock_settings = MagicMock()
        mock_settings.llm.discovery_model = None
        mock_settings.llm.default_model = None

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            with patch(
                "pflow.core.llm_config.get_default_llm_model",
                return_value=None,
            ):
                result = get_model_for_feature("discovery")

                assert result == "anthropic/claude-sonnet-5"

    def test_feature_specific_takes_priority_over_default(self):
        """Feature-specific model takes priority over default_model."""
        mock_settings = MagicMock()
        mock_settings.llm.filtering_model = "filtering-specific"
        mock_settings.llm.default_model = "default-model"

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            result = get_model_for_feature("filtering")

            # Feature-specific wins
            assert result == "filtering-specific"

    def test_default_model_takes_priority_over_auto_detect(self):
        """default_model takes priority over auto-detection."""
        mock_settings = MagicMock()
        mock_settings.llm.discovery_model = None
        mock_settings.llm.default_model = "user-default"

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            # Auto-detect would return something different
            with patch(
                "pflow.core.llm_config.get_default_llm_model",
                return_value="auto-detected-model",
            ):
                result = get_model_for_feature("discovery")

                # default_model wins over auto-detect
                assert result == "user-default"

    def test_raises_on_invalid_feature(self):
        """Raises ValueError for unknown feature names."""
        import pytest

        with pytest.raises(ValueError, match="Unknown feature"):
            get_model_for_feature("invalid-feature")

    def test_handles_settings_load_failure(self):
        """Falls back gracefully when settings fail to load."""
        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.side_effect = Exception("Settings error")

            with patch(
                "pflow.core.llm_config.get_default_llm_model",
                return_value="fallback-model",
            ):
                result = get_model_for_feature("discovery")

                assert result == "fallback-model"
