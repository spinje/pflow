"""Root-level test configuration and fixtures."""

import os

import pytest

from tests.shared.llm_mock import create_mock_get_model


@pytest.fixture(autouse=True, scope="function")
def mock_llm_calls(monkeypatch, request):
    """Auto-applied fixture that mocks all LLM calls to prevent API usage.

    This fixture is automatically applied to ALL tests except those in llm/ directories
    which are meant to test real LLM behavior when RUN_LLM_TESTS=1 is set.
    """
    # Skip mocking for tests in llm/ directories
    test_path = str(request.fspath)
    if "/llm/" in test_path or "\\llm\\" in test_path:
        # These tests should use real LLM when RUN_LLM_TESTS=1
        yield
        return

    # Create and apply the mock
    mock_get_model = create_mock_get_model()
    monkeypatch.setattr("llm.get_model", mock_get_model)

    # Make the mock available to tests that want to configure it
    request.node.mock_llm = mock_get_model

    yield mock_get_model

    # Clean up after test
    mock_get_model.reset()


@pytest.fixture
def mock_llm_responses(request):
    """Fixture to configure LLM mock responses for specific tests.

    Usage:
        def test_something(mock_llm_responses):
            mock_llm_responses.set_response(
                "anthropic/claude-sonnet-4-0",
                WorkflowDecision,
                {"found": True, "workflow_name": "test"}
            )
    """
    # Get the auto-applied mock from the node
    if hasattr(request.node, "mock_llm"):
        return request.node.mock_llm

    # Fallback if not using auto-mock (shouldn't happen)
    return create_mock_get_model()


@pytest.fixture(autouse=True, scope="session")
def enable_test_nodes():
    """Enable test nodes for all test runs.

    This ensures that test nodes like 'echo' are available during testing,
    even though they're hidden from users by default.
    """
    # Store original value
    original = os.environ.get("PFLOW_INCLUDE_TEST_NODES")

    # Enable test nodes for all tests
    os.environ["PFLOW_INCLUDE_TEST_NODES"] = "true"

    yield

    # Restore original value after tests
    if original is None:
        os.environ.pop("PFLOW_INCLUDE_TEST_NODES", None)
    else:
        os.environ["PFLOW_INCLUDE_TEST_NODES"] = original
