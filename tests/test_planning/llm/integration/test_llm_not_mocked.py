"""Verify that real LLM is used in llm/ directories (not mocked).

This test ensures that our LLM mocking boundaries are correct - tests in llm/
directories should use real LLM API calls, not mocks.

WHEN TO RUN: Only when RUN_LLM_TESTS=1 environment variable is set.

Run with: RUN_LLM_TESTS=1 pytest tests/test_planning/llm/integration/test_llm_not_mocked.py -v
"""

import os

import llm
import pytest

# Skip unless LLM tests are enabled
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="Real LLM tests disabled. Set RUN_LLM_TESTS=1 to run"
)


class TestLLMNotMocked:
    """Verify that LLM is not mocked in llm/ test directories."""

    def test_real_llm_is_accessible(self):
        """Verify that real LLM is accessible and not mocked."""
        # This should get the real llm.get_model, not our mock
        model = llm.get_model("anthropic/claude-3-haiku-20240307")

        # Verify it's the real model, not our mock
        assert not hasattr(model, "_mock_get_model"), "Model should be real, not mocked"
        assert hasattr(model, "prompt"), "Real model should have prompt method"

        # The real model's class name should be from llm library
        assert "MockLLMModel" not in str(type(model))

        # Try a simple prompt to verify it's real
        try:
            response = model.prompt("Say 'hello' in one word")
            # Real response will have different structure than our mock
            assert hasattr(response, "text") or hasattr(response, "content")
        except Exception as e:
            # API errors are fine - we're just verifying it's trying to use real API
            if "API" in str(e) or "key" in str(e).lower() or "rate" in str(e).lower():
                pass  # Expected - real API call attempted
            else:
                raise

    def test_mock_fixture_not_applied(self):
        """Verify that our mock fixture is not applied to this test."""
        # Import the function directly
        from llm import get_model

        # Get a model
        model = get_model("anthropic/claude-3-haiku-20240307")

        # Our mock would have _mock_get_model attribute
        assert not hasattr(model, "_mock_get_model"), "Mock should not be applied"

        # Our mock class is MockLLMModel
        assert "MockLLMModel" not in str(type(model)), "Should not be mock class"
