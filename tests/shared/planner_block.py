"""Simple planner blocking fixture for CLI and integration tests.

This module provides a clean way to block the planner function to trigger
fallback behavior in CLI tests.
"""

import pytest


def create_planner_block_fixture():
    """Create a fixture that blocks planner to trigger fallback behavior.

    This factory creates a fixture that makes create_planner_flow raise ImportError,
    causing the CLI to show "Collected workflow from..." messages instead
    of running the planner.

    Returns:
        A pytest fixture that blocks the planner.
    """

    @pytest.fixture(autouse=True)
    def block_planner(monkeypatch):
        """Block planner to trigger CLI fallback behavior."""

        # Instead of manipulating sys.modules, we patch the actual function
        # to raise ImportError when accessed
        def mock_import(name, globals_dict=None, locals_dict=None, fromlist=(), level=0):
            """Mock __import__ that fails for create_planner_flow."""
            # Check if trying to import create_planner_flow from pflow.planning
            if name == "pflow.planning" and fromlist and "create_planner_flow" in fromlist:
                # Create a mock module that raises ImportError for create_planner_flow
                class MockModule:
                    def __getattr__(self, attr):
                        if attr == "create_planner_flow":
                            raise ImportError("Planning module blocked for testing")
                        raise AttributeError(f"module 'pflow.planning' has no attribute '{attr}'")

                return MockModule()

            # For all other imports, use the real import
            return real_import(name, globals_dict, locals_dict, fromlist, level)

        # Store the real import function
        import builtins

        real_import = builtins.__import__

        # Patch __import__
        monkeypatch.setattr(builtins, "__import__", mock_import)

        yield

        # Cleanup happens automatically with monkeypatch

    return block_planner
