"""Shared mock fixtures for testing.

This module provides reusable mock fixtures that can be imported
and used across different test suites to avoid code duplication.
"""

import sys
from collections.abc import Generator
from typing import Any

import pytest


def create_planner_mock_fixture(autouse: bool = False) -> Any:
    """Create a planner mock fixture that can be reused across test suites.

    This factory function creates a pytest fixture that mocks the planning module
    to prevent actual LLM calls during tests. The mock makes the planning module
    raise ImportError on attribute access, triggering fallback behavior in the CLI.

    Args:
        autouse: Whether the fixture should be automatically applied to all tests.
                 Default is False to allow explicit control.

    Returns:
        A pytest fixture that can be used in conftest.py files.

    Usage:
        In your conftest.py:
        ```python
        from tests.shared.mocks import create_planner_mock_fixture

        # Create an autouse fixture for all tests in the directory
        mock_planner_for_tests = create_planner_mock_fixture(autouse=True)
        ```

    FIX HISTORY:
    - 2025-01: Created to share planner mock between test_cli and test_integration
    - Prevents tests from hanging by avoiding actual LLM calls
    - Tests expect old behavior where natural language shows "Collected workflow from args/file"

    IMPLEMENTATION NOTES:
    - The mock module raises ImportError for create_planner_flow
    - This triggers fallback behavior in main.py CLI implementation
    - The "from X import Y" statement calls getattr on the module
    """

    @pytest.fixture(autouse=autouse)
    def mock_planner_fixture() -> Generator[None, None, None]:
        """Mock the planner to prevent actual LLM calls during tests.

        This fixture replaces the pflow.planning module with a mock that
        raises ImportError for any attribute access, effectively disabling
        the planner functionality during tests.
        """

        class MockPlanningModule:
            """Mock planning module that raises ImportError for specific attributes.

            This mock allows submodules like context_builder to work normally,
            but prevents importing the main planner flow components that would
            trigger actual LLM calls.
            """

            def __init__(self, original_module: Any):
                self._original = original_module

            def __getattr__(self, name: str) -> Any:
                # Block only the specific imports that trigger LLM calls
                blocked_attributes = {
                    "create_planner_flow",  # Main entry point that creates the planner
                    "PlannerNode",  # The main planner node
                    "DiscoveryNode",  # Discovery node that uses LLM
                    "GeneratorNode",  # Generator node that uses LLM
                    "ParameterMappingNode",  # Parameter mapping that might use LLM
                    "ValidationNode",  # Validation that might use LLM
                }

                if name in blocked_attributes:
                    # Raise ImportError for blocked attributes to trigger fallback
                    raise ImportError(f"Mocked planning module - {name} not available for tests")

                # For all other attributes, delegate to the original module if it exists
                if self._original and hasattr(self._original, name):
                    return getattr(self._original, name)

                # If original doesn't have it either, raise AttributeError
                raise AttributeError(f"module 'pflow.planning' has no attribute '{name}'")

        # Store the original module
        original_module = sys.modules.get("pflow.planning")

        # Replace with our mock that wraps the original
        sys.modules["pflow.planning"] = MockPlanningModule(original_module)  # type: ignore[assignment]

        yield

        # Restore the original module
        if original_module is not None:
            sys.modules["pflow.planning"] = original_module
        else:
            sys.modules.pop("pflow.planning", None)

    return mock_planner_fixture


# Pre-configured fixtures for common use cases


def get_autouse_planner_mock() -> Any:
    """Get an autouse planner mock fixture.

    This is a convenience function that returns a planner mock fixture
    with autouse=True, suitable for test directories where all tests
    should have the planner disabled.

    Returns:
        An autouse pytest fixture that mocks the planner.

    Usage:
        In your conftest.py:
        ```python
        from tests.shared.mocks import get_autouse_planner_mock

        mock_planner_for_tests = get_autouse_planner_mock()
        ```
    """
    return create_planner_mock_fixture(autouse=True)


def get_manual_planner_mock() -> Any:
    """Get a manual planner mock fixture.

    This is a convenience function that returns a planner mock fixture
    with autouse=False, suitable for tests that need explicit control
    over when the planner is mocked.

    Returns:
        A pytest fixture that mocks the planner (requires explicit use).

    Usage:
        In your conftest.py:
        ```python
        from tests.shared.mocks import get_manual_planner_mock

        mock_planner = get_manual_planner_mock()
        ```

        In your test:
        ```python
        def test_something(mock_planner):
            # Test with planner mocked
            pass
        ```
    """
    return create_planner_mock_fixture(autouse=False)
