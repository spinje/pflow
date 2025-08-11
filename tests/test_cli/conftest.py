"""Shared fixtures and utilities for CLI tests."""

from tests.shared.mocks import get_autouse_planner_mock

# Apply the planner mock to all CLI tests automatically
# This prevents actual LLM calls during tests and ensures predictable behavior
mock_planner_for_tests = get_autouse_planner_mock()
