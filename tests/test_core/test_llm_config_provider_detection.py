"""Tests for multi-source provider detection and environment injection.

These tests verify that:
1. API keys from pflow settings are injected into os.environ
2. Provider detection checks env vars, settings, and llm CLI in order
3. Priority is respected (env > settings > llm CLI)
"""

import os
from unittest.mock import MagicMock, patch


class TestInjectSettingsEnvVars:
    """Test inject_settings_env_vars() function."""

    def test_injects_keys_from_settings(self, monkeypatch):
        """Keys from settings.env are injected into os.environ."""
        monkeypatch.delenv("TEST_API_KEY", raising=False)

        mock_manager = MagicMock()
        mock_manager.list_env.return_value = {"TEST_API_KEY": "injected-value"}

        # Patch at source module since we use lazy imports
        with (
            patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}, clear=False),
            patch("pflow.core.settings.SettingsManager", return_value=mock_manager),
        ):
            del os.environ["PYTEST_CURRENT_TEST"]

            from pflow.core.llm_config import inject_settings_env_vars

            inject_settings_env_vars()

            assert os.environ.get("TEST_API_KEY") == "injected-value"
            os.environ.pop("TEST_API_KEY", None)

    def test_does_not_override_existing_env_vars(self, monkeypatch):
        """Existing env vars take priority over settings."""
        monkeypatch.setenv("PRIORITY_KEY", "from-environment")

        mock_manager = MagicMock()
        mock_manager.list_env.return_value = {"PRIORITY_KEY": "from-settings"}

        with (
            patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}, clear=False),
            patch("pflow.core.settings.SettingsManager", return_value=mock_manager),
        ):
            del os.environ["PYTEST_CURRENT_TEST"]

            from pflow.core.llm_config import inject_settings_env_vars

            inject_settings_env_vars()

        assert os.environ.get("PRIORITY_KEY") == "from-environment"

    def test_handles_missing_settings_gracefully(self):
        """Missing settings file doesn't raise errors."""
        with (
            patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}, clear=False),
            patch("pflow.core.settings.SettingsManager") as MockManager,
        ):
            del os.environ["PYTEST_CURRENT_TEST"]
            MockManager.side_effect = FileNotFoundError("No settings")

            from pflow.core.llm_config import inject_settings_env_vars

            # Should not raise
            inject_settings_env_vars()

    def test_skips_empty_values(self, monkeypatch):
        """Empty or whitespace-only values are not injected."""
        monkeypatch.delenv("EMPTY_KEY", raising=False)

        mock_manager = MagicMock()
        mock_manager.list_env.return_value = {"EMPTY_KEY": "   "}

        with (
            patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}, clear=False),
            patch("pflow.core.settings.SettingsManager", return_value=mock_manager),
        ):
            del os.environ["PYTEST_CURRENT_TEST"]

            from pflow.core.llm_config import inject_settings_env_vars

            inject_settings_env_vars()

        assert "EMPTY_KEY" not in os.environ

    def test_skipped_in_pytest_environment(self):
        """Injection is skipped when PYTEST_CURRENT_TEST is set."""
        mock_manager = MagicMock()
        mock_manager.list_env.return_value = {"SHOULD_NOT_INJECT": "value"}

        # Don't remove PYTEST_CURRENT_TEST - let the guard trigger
        with patch("pflow.core.settings.SettingsManager", return_value=mock_manager):
            from pflow.core.llm_config import inject_settings_env_vars

            inject_settings_env_vars()

        # Manager should never be instantiated (guard returns early)
        mock_manager.list_env.assert_not_called()
        assert "SHOULD_NOT_INJECT" not in os.environ


class TestHasProviderKey:
    """Test _has_provider_key() multi-source detection."""

    def test_detects_env_var(self, monkeypatch):
        """Finds key in environment variable."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        from pflow.core.llm_config import _has_provider_key

        assert _has_provider_key("anthropic") is True

    def test_detects_settings_key(self, monkeypatch):
        """Finds key in pflow settings when not in env."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        mock_manager = MagicMock()
        mock_manager.get_env.return_value = "settings-key"

        with patch("pflow.core.settings.SettingsManager", return_value=mock_manager):
            from pflow.core.llm_config import _has_provider_key

            assert _has_provider_key("openai") is True

    def test_falls_back_to_llm_cli(self, monkeypatch):
        """Falls back to llm CLI when env and settings empty."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        mock_manager = MagicMock()
        mock_manager.get_env.return_value = None

        with (
            patch("pflow.core.settings.SettingsManager", return_value=mock_manager),
            patch("pflow.core.llm_config._has_llm_key", return_value=True) as mock_llm,
        ):
            from pflow.core.llm_config import _has_provider_key

            assert _has_provider_key("gemini") is True
            mock_llm.assert_called_once_with("gemini")

    def test_env_var_checked_before_settings(self, monkeypatch):
        """Env var is found without checking settings."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")

        with patch("pflow.core.settings.SettingsManager") as MockManager:
            from pflow.core.llm_config import _has_provider_key

            result = _has_provider_key("anthropic")

            assert result is True
            MockManager.assert_not_called()  # Settings not checked

    def test_empty_env_var_continues_to_settings(self, monkeypatch):
        """Empty env var doesn't count - continues to check settings."""
        monkeypatch.setenv("OPENAI_API_KEY", "")

        mock_manager = MagicMock()
        mock_manager.get_env.return_value = "settings-key"

        with patch("pflow.core.settings.SettingsManager", return_value=mock_manager):
            from pflow.core.llm_config import _has_provider_key

            assert _has_provider_key("openai") is True

    def test_rejects_unknown_provider(self):
        """Unknown providers return False."""
        from pflow.core.llm_config import _has_provider_key

        assert _has_provider_key("unknown-provider") is False

    def test_gemini_accepts_google_api_key(self, monkeypatch):
        """Gemini provider accepts GOOGLE_API_KEY as alternative."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "google-key")

        from pflow.core.llm_config import _has_provider_key

        assert _has_provider_key("gemini") is True


class TestDetectDefaultModel:
    """Test _detect_default_model() uses _has_provider_key()."""

    def test_priority_order(self):
        """Anthropic > Gemini > OpenAI priority."""
        with (
            patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}, clear=False),
            patch("pflow.core.llm_config._has_provider_key") as mock_has_key,
        ):
            del os.environ["PYTEST_CURRENT_TEST"]
            mock_has_key.return_value = True

            from pflow.core.llm_config import _detect_default_model, clear_model_cache

            clear_model_cache()
            result = _detect_default_model()

            # Should return Anthropic (first in priority)
            assert result == "anthropic/claude-sonnet-4-5"
            # Should have checked Anthropic first
            assert mock_has_key.call_args_list[0][0][0] == "anthropic"

    def test_skips_to_next_when_no_key(self):
        """Skips provider without key, uses next available."""
        with (
            patch.dict(os.environ, {"PYTEST_CURRENT_TEST": ""}, clear=False),
            patch("pflow.core.llm_config._has_provider_key") as mock_has_key,
        ):
            del os.environ["PYTEST_CURRENT_TEST"]
            mock_has_key.side_effect = lambda p: p == "openai"

            from pflow.core.llm_config import _detect_default_model, clear_model_cache

            clear_model_cache()
            result = _detect_default_model()

            assert result == "gpt-5.2"
