"""Tests for llm_config module."""

from unittest import mock

import pytest

from pflow.core.llm_config import clear_model_cache, get_default_llm_model, resolve_provider_api_key


class TestLLMConfig:
    """Test LLM configuration and caching."""

    def test_cache_works_correctly_with_none_result(self):
        """Test that cache works even when detection returns None."""
        # Clear any existing cache
        clear_model_cache()

        # Mock _detect_default_model to return None
        with mock.patch("pflow.core.llm_config._detect_default_model") as mock_detect:
            mock_detect.return_value = None

            # First call should trigger detection
            result1 = get_default_llm_model()
            assert result1 is None
            assert mock_detect.call_count == 1

            # Second call should use cache (not call detect again)
            result2 = get_default_llm_model()
            assert result2 is None
            assert mock_detect.call_count == 1  # Still 1, not 2!

            # Third call should also use cache
            result3 = get_default_llm_model()
            assert result3 is None
            assert mock_detect.call_count == 1  # Still 1!

    def test_cache_works_with_valid_model(self):
        """Test that cache works when a model is detected."""
        clear_model_cache()

        with mock.patch("pflow.core.llm_config._detect_default_model") as mock_detect:
            mock_detect.return_value = "anthropic/claude-sonnet-4-5"

            # First call
            result1 = get_default_llm_model()
            assert result1 == "anthropic/claude-sonnet-4-5"
            assert mock_detect.call_count == 1

            # Should use cache
            result2 = get_default_llm_model()
            assert result2 == "anthropic/claude-sonnet-4-5"
            assert mock_detect.call_count == 1  # Not called again

    def test_clear_cache_resets_detection(self):
        """Test that clearing cache allows re-detection."""
        clear_model_cache()

        with mock.patch("pflow.core.llm_config._detect_default_model") as mock_detect:
            mock_detect.return_value = "model-1"

            # First detection
            result1 = get_default_llm_model()
            assert result1 == "model-1"
            assert mock_detect.call_count == 1

            # Clear cache
            clear_model_cache()
            mock_detect.return_value = "model-2"

            # Should detect again
            result2 = get_default_llm_model()
            assert result2 == "model-2"
            assert mock_detect.call_count == 2

    def test_detection_only_uses_env_and_settings(self, monkeypatch):
        """Detection only consults env vars and pflow settings (no subprocess)."""
        clear_model_cache()
        # Clear any provider keys so detection has nothing to find
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(var, raising=False)

        # Mock SettingsManager so settings lookup also finds nothing
        mock_manager = mock.MagicMock()
        mock_manager.get_env.return_value = None
        with mock.patch("pflow.core.settings.SettingsManager", return_value=mock_manager):
            result = get_default_llm_model()
        assert result is None


class TestResolveProviderApiKey:
    """resolve_provider_api_key walks env vars canonical-first, env then settings."""

    @pytest.fixture(autouse=True)
    def _clean_provider_env(self, monkeypatch):
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(var, raising=False)

    def test_canonical_env_var_wins_over_alias(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "canonical-value")
        monkeypatch.setenv("GOOGLE_API_KEY", "alias-value")
        assert resolve_provider_api_key("gemini") == "canonical-value"

    def test_alias_env_var_used_as_fallback(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "alias-value")
        assert resolve_provider_api_key("gemini") == "alias-value"

    def test_settings_fallback_strips_whitespace(self):
        from pflow.core.settings import SettingsManager

        SettingsManager().set_env("GEMINI_API_KEY", "  padded-key  ")
        assert resolve_provider_api_key("gemini") == "padded-key"

    def test_env_var_wins_over_settings(self, monkeypatch):
        from pflow.core.settings import SettingsManager

        SettingsManager().set_env("GEMINI_API_KEY", "settings-key")
        monkeypatch.setenv("GEMINI_API_KEY", "env-key")
        assert resolve_provider_api_key("gemini") == "env-key"

    def test_no_sources_returns_none(self):
        assert resolve_provider_api_key("gemini") is None

    def test_unknown_provider_returns_none(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "value")
        assert resolve_provider_api_key("mystery") is None


class TestEnvAliasPrecedenceAcrossInjection:
    """A genuinely exported alias beats a settings-injected canonical var.

    inject_settings_env_vars() copies settings keys into os.environ, which
    would otherwise make a stale settings GEMINI_API_KEY indistinguishable
    from a real one — and canonical-first order would pick it over a live
    shell-exported GOOGLE_API_KEY. Provenance tracking restores the
    documented environment-over-settings precedence across aliases.
    """

    @pytest.fixture(autouse=True)
    def _clean_provider_env(self, monkeypatch):
        import pflow.core.llm_config as llm_config

        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr(llm_config, "_settings_injected_env_vars", set())

    def test_real_env_alias_beats_settings_injected_canonical(self, monkeypatch):
        import pflow.core.llm_config as llm_config

        monkeypatch.setenv("GEMINI_API_KEY", "stale-settings-key")
        monkeypatch.setenv("GOOGLE_API_KEY", "live-shell-key")
        monkeypatch.setattr(llm_config, "_settings_injected_env_vars", {"GEMINI_API_KEY"})

        assert resolve_provider_api_key("gemini") == "live-shell-key"

    def test_settings_injected_value_used_when_no_real_env(self, monkeypatch):
        import pflow.core.llm_config as llm_config

        monkeypatch.setenv("GEMINI_API_KEY", "settings-injected-key")
        monkeypatch.setattr(llm_config, "_settings_injected_env_vars", {"GEMINI_API_KEY"})

        assert resolve_provider_api_key("gemini") == "settings-injected-key"

    def test_inject_records_provenance(self, monkeypatch):
        import os

        import pflow.core.llm_config as llm_config
        from pflow.core.settings import SettingsManager

        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        SettingsManager().set_env("GEMINI_API_KEY", "from-settings")
        try:
            llm_config.inject_settings_env_vars()

            assert "GEMINI_API_KEY" in llm_config._settings_injected_env_vars
            assert os.environ["GEMINI_API_KEY"] == "from-settings"
        finally:
            os.environ.pop("GEMINI_API_KEY", None)

    def test_clear_model_cache_resets_provenance(self):
        import pflow.core.llm_config as llm_config

        llm_config._settings_injected_env_vars.add("GEMINI_API_KEY")
        clear_model_cache()
        assert not llm_config._settings_injected_env_vars


class TestGeminiAutoDetectDefault:
    def test_gemini_default_is_flash_lite(self):
        with mock.patch("pflow.core.llm_config._has_provider_key") as mock_has:
            mock_has.side_effect = lambda p: p == "gemini"

            from pflow.core.llm_config import _detect_default_model

            clear_model_cache()
            assert _detect_default_model() == "gemini/gemini-3.5-flash-lite"
