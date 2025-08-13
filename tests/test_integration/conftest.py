"""Shared fixtures and utilities for integration tests."""

from tests.shared.planner_block import create_planner_block_fixture

# Block the planner import to test integration without planner
# This ensures integration tests focus on workflow execution,
# not LLM-based planning
block_planner = create_planner_block_fixture()
