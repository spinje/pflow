"""Shared fixtures and utilities for CLI tests."""

from tests.shared.planner_block import create_planner_block_fixture

# Block the planner import to test CLI fallback behavior
# This makes the CLI show "Collected workflow from..." messages
# instead of running the planner
block_planner = create_planner_block_fixture()
