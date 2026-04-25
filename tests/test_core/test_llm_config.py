"""Tests for llm_config module."""

from unittest import mock

from pflow.core.llm_config import clear_model_cache, get_default_llm_model


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
