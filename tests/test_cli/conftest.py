"""Shared fixtures and utilities for CLI tests."""

import sys

import pytest


@pytest.fixture(autouse=True)
def mock_planner_for_tests():
    """Mock the planner to prevent actual LLM calls during tests.

    This fixture automatically applies to all tests in the test_cli directory.
    It makes the planning module raise ImportError on attribute access.

    FIX HISTORY:
    - 2025-01: Added after planner integration to prevent tests from hanging
    - Tests expect old behavior where natural language shows "Collected workflow from args"
    - Create a mock module that raises ImportError for create_planner_flow

    LESSONS LEARNED:
    - main.py has duplicate imports causing UnboundLocalError
    - Line 668: from pflow.core.workflow_manager import WorkflowManager (duplicate)
    - Line 669: from pflow.planning import create_planner_flow
    - When second import fails, WorkflowManager becomes unbound local variable
    - Solution: Make create_planner_flow attribute access raise ImportError
    - The "from X import Y" statement calls getattr on the module
    """

    # Create a mock planning module that raises ImportError for create_planner_flow
    class MockPlanningModule:
        def __getattr__(self, name):
            # Raise ImportError for create_planner_flow to trigger fallback
            raise ImportError(f"Mocked planning module - {name} not available for tests")

    # Store the original module
    original_module = sys.modules.get("pflow.planning")

    # Replace with our mock
    sys.modules["pflow.planning"] = MockPlanningModule()

    yield

    # Restore the original module
    if original_module is not None:
        sys.modules["pflow.planning"] = original_module
    else:
        sys.modules.pop("pflow.planning", None)
