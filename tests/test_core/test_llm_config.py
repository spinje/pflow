"""Tests for llm_config module."""

import os
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

    def test_pytest_environment_skips_detection(self):
        """Test that PYTEST_CURRENT_TEST environment variable skips detection."""
        clear_model_cache()

        # Ensure PYTEST_CURRENT_TEST is set (it should be during tests)
        assert os.environ.get("PYTEST_CURRENT_TEST") is not None

        # Should return None without calling subprocess
        with mock.patch("pflow.core.llm_config._has_llm_key") as mock_has_key:
            result = get_default_llm_model()
            assert result is None
            # _has_llm_key should never be called in test environment
            assert mock_has_key.call_count == 0
