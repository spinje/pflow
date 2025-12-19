"""Test get_default_workflow_model and related functions."""

import subprocess
from unittest.mock import MagicMock, patch

from pflow.core.llm_config import (
    get_default_workflow_model,
    get_llm_cli_default_model,
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

    def test_falls_back_to_llm_cli_default(self):
        """Falls back to llm CLI default when settings not configured."""
        mock_settings = MagicMock()
        mock_settings.llm.default_model = None

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            with patch(
                "pflow.core.llm_config.get_llm_cli_default_model",
                return_value="claude-3-sonnet",
            ):
                result = get_default_workflow_model()

                assert result == "claude-3-sonnet"

    def test_returns_none_when_nothing_configured(self):
        """Returns None when nothing is configured."""
        mock_settings = MagicMock()
        mock_settings.llm.default_model = None

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            with patch(
                "pflow.core.llm_config.get_llm_cli_default_model",
                return_value=None,
            ):
                result = get_default_workflow_model()

                assert result is None

    def test_settings_takes_priority_over_llm_cli(self):
        """Settings default_model takes priority over llm CLI default."""
        mock_settings = MagicMock()
        mock_settings.llm.default_model = "settings-model"

        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.return_value = mock_settings

            # llm CLI should not even be checked since settings is configured
            result = get_default_workflow_model()

            # Settings wins
            assert result == "settings-model"

    def test_handles_settings_load_failure(self):
        """Falls back to llm CLI if settings fail to load."""
        with patch("pflow.core.llm_config.SettingsManager") as MockManager:
            MockManager.return_value.load.side_effect = Exception("Settings error")

            with patch(
                "pflow.core.llm_config.get_llm_cli_default_model",
                return_value="fallback-model",
            ):
                result = get_default_workflow_model()

                assert result == "fallback-model"


class TestGetLlmCliDefaultModel:
    """Test llm CLI default model detection."""

    def test_returns_model_when_configured(self):
        """Returns model name when llm has default configured."""
        with patch("pflow.core.llm_config._get_validated_llm_path") as mock_path:
            mock_path.return_value = "/usr/bin/llm"

            with patch("pflow.core.llm_config.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="gpt-4o\n")

                # Clear test environment check
                with patch.dict("os.environ", {}, clear=True):
                    result = get_llm_cli_default_model()

                assert result == "gpt-4o"

    def test_returns_none_when_no_default(self):
        """Returns None when llm has no default configured."""
        with patch("pflow.core.llm_config._get_validated_llm_path") as mock_path:
            mock_path.return_value = "/usr/bin/llm"

            with patch("pflow.core.llm_config.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="")

                with patch.dict("os.environ", {}, clear=True):
                    result = get_llm_cli_default_model()

                assert result is None

    def test_returns_none_when_llm_not_installed(self):
        """Returns None when llm CLI not found."""
        with patch("pflow.core.llm_config._get_validated_llm_path") as mock_path:
            mock_path.return_value = None

            with patch.dict("os.environ", {}, clear=True):
                result = get_llm_cli_default_model()

            assert result is None

    def test_returns_none_on_timeout(self):
        """Returns None on subprocess timeout."""
        with patch("pflow.core.llm_config._get_validated_llm_path") as mock_path:
            mock_path.return_value = "/usr/bin/llm"

            with patch("pflow.core.llm_config.subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired("llm", 2)

                with patch.dict("os.environ", {}, clear=True):
                    result = get_llm_cli_default_model()

                assert result is None

    def test_returns_none_on_nonzero_exit(self):
        """Returns None when llm command fails."""
        with patch("pflow.core.llm_config._get_validated_llm_path") as mock_path:
            mock_path.return_value = "/usr/bin/llm"

            with patch("pflow.core.llm_config.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")

                with patch.dict("os.environ", {}, clear=True):
                    result = get_llm_cli_default_model()

                assert result is None

    def test_skipped_in_test_environment(self):
        """Returns None when PYTEST_CURRENT_TEST is set."""
        # This test itself sets PYTEST_CURRENT_TEST, so we expect None
        result = get_llm_cli_default_model()
        assert result is None


class TestGetModelNotConfiguredHelp:
    """Test help message generation."""

    def test_includes_node_id(self):
        """Help message includes the node ID."""
        help_text = get_model_not_configured_help("my-custom-llm")
        assert "my-custom-llm" in help_text

    def test_includes_all_configuration_methods(self):
        """Help message shows all three configuration methods."""
        help_text = get_model_not_configured_help("test-node")

        assert "params" in help_text  # Method 1: IR params
        assert "settings.json" in help_text  # Method 2: pflow settings
        assert "llm models default" in help_text  # Method 3: llm CLI

    def test_includes_discovery_commands(self):
        """Help message includes helpful discovery commands."""
        help_text = get_model_not_configured_help("test-node")

        assert "llm models list" in help_text
        assert "llm keys list" in help_text

    def test_formats_json_examples_correctly(self):
        """Help message has properly formatted JSON examples."""
        help_text = get_model_not_configured_help("my-node")

        # Check that the JSON example includes the node ID
        assert '"id": "my-node"' in help_text
        assert '"model": "gpt-5.2"' in help_text
