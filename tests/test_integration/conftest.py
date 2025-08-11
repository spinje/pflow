"""Shared fixtures and utilities for integration tests."""

from tests.shared.mocks import get_autouse_planner_mock

# Apply the planner mock to all integration tests automatically
# This prevents actual LLM calls during tests and ensures predictable behavior
# Integration tests should test workflow execution, not LLM planning
mock_planner_for_tests = get_autouse_planner_mock()
