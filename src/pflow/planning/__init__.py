"""Natural Language Planner.

This module implements a meta-workflow that transforms natural language
into executable pflow workflows. It follows PocketFlow patterns where
the shared store is initialized by the caller (CLI) at runtime.

Expected shared store keys (initialized by CLI):
- user_input: Natural language request from user
- stdin_data: Optional data from stdin pipe
- current_date: ISO timestamp for context

Keys written during execution:
- discovery_context, discovery_result, browsed_components
- discovered_params, planning_context, generation_attempts
- validation_errors, generated_workflow, found_workflow
- workflow_metadata, extracted_params, verified_params
- execution_params, planner_output

See individual node docstrings for detailed key usage.
"""

import logging

from pflow.planning.flow import create_planner_flow

# Configure logging at module level
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Export the main planner flow factory

__all__ = ["create_planner_flow"]
