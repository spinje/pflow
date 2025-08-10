"""Flow orchestration for the Natural Language Planner.

This module creates the complete planner meta-workflow that transforms
natural language into executable workflows using a two-path architecture:

Path A (Workflow Reuse): Discovery → Parameter Mapping → Result
Path B (Workflow Generation): Discovery → Browse → Generate → Validate → Metadata → Parameter Mapping → Result

Both paths converge at ParameterMappingNode - the critical verification gate.
"""

import logging

from pflow.planning.nodes import (
    ComponentBrowsingNode,
    MetadataGenerationNode,
    ParameterDiscoveryNode,
    ParameterMappingNode,
    ParameterPreparationNode,
    ResultPreparationNode,
    ValidatorNode,
    WorkflowDiscoveryNode,
    WorkflowGeneratorNode,
)
from pocketflow import Flow

logger = logging.getLogger(__name__)


def create_planner_flow() -> Flow:
    """Create the complete planner meta-workflow.

    This flow implements the sophisticated two-path architecture:
    - Path A: Reuse existing workflows (fast, 10x performance)
    - Path B: Generate new workflows (creative, LLM-powered)

    Key features:
    - Convergence at ParameterMappingNode for both paths
    - Retry mechanism with 3-attempt limit for generation
    - Three entry points to ResultPreparationNode
    - Template variable preservation for workflow reusability

    Returns:
        The complete planner flow ready for execution
    """
    logger.debug("Creating planner flow with 9 nodes")

    # Create all nodes
    discovery_node = WorkflowDiscoveryNode()
    component_browsing = ComponentBrowsingNode()
    parameter_discovery = ParameterDiscoveryNode()
    parameter_mapping = ParameterMappingNode()
    parameter_preparation = ParameterPreparationNode()
    workflow_generator = WorkflowGeneratorNode()
    validator = ValidatorNode()
    metadata_generation = MetadataGenerationNode()
    result_preparation = ResultPreparationNode()

    # Create flow with start node
    flow = Flow(start=discovery_node)

    # ============================================================
    # Path A: Workflow Reuse (found existing workflow)
    # ============================================================
    # Discovery finds existing workflow → directly to parameter mapping
    discovery_node - "found_existing" >> parameter_mapping

    # Path A: Parameters complete → skip validation, go to preparation
    parameter_mapping - "params_complete" >> parameter_preparation

    # ============================================================
    # Path B: Workflow Generation (no existing workflow found)
    # ============================================================
    # Discovery doesn't find workflow → browse for components
    discovery_node - "not_found" >> component_browsing

    # Browse components → discover parameters from natural language
    # ComponentBrowsingNode returns "generate" so we wire that action
    component_browsing - "generate" >> parameter_discovery

    # Discover parameters → generate workflow
    # ParameterDiscoveryNode returns "" (empty string) so we use default
    parameter_discovery >> workflow_generator

    # Generate workflow → extract parameters FIRST (VALIDATION REDESIGN FIX)
    # WorkflowGeneratorNode returns "validate" but we route to parameter mapping first
    # This ensures template validation happens WITH extracted parameter values
    workflow_generator - "validate" >> parameter_mapping

    # ============================================================
    # Parameter Extraction Before Validation (FIXED FLOW)
    # ============================================================
    # Extract parameters from user input BEFORE validating templates
    # This fixes the critical flaw where validation failed with empty {}

    # Path B now converges at ParameterMappingNode BEFORE validation
    # If parameters complete → validate with actual values
    parameter_mapping - "params_complete_validate" >> validator

    # If parameters incomplete → skip validation, go to result
    parameter_mapping - "params_incomplete" >> result_preparation

    # ============================================================
    # Validation and Retry Loop (Path B only)
    # ============================================================
    # CRITICAL: This retry loop works correctly with 3-attempt limit
    # ValidatorNode tracks generation_attempts and prevents infinite loops
    # NOW validates with extracted parameters instead of empty {}

    # Validation succeeds → generate metadata
    validator - "metadata_generation" >> metadata_generation

    # Validation fails but can retry (attempts < 3) → retry generation
    # The validator stores validation_errors for the generator to use
    validator - "retry" >> workflow_generator

    # Validation fails after max attempts (attempts >= 3) → end with failure
    validator - "failed" >> result_preparation

    # Metadata generation complete → continue to preparation
    # MetadataGenerationNode returns "" (empty string) so we use default
    # (Path B now goes directly to preparation since params already extracted)
    metadata_generation >> parameter_preparation

    # ============================================================
    # Both Paths Converge at ParameterMappingNode
    # ============================================================
    # This is the critical verification gate that extracts parameters from user input
    #
    # Path routing from ParameterMappingNode:
    # - Path A (found_workflow): "params_complete" → ParameterPreparation
    # - Path B (generated_workflow): "params_complete_validate" → Validator
    # - Both paths: "params_incomplete" → ResultPreparation
    #
    # All connections are already wired above

    # ============================================================
    # Final Preparation and Result
    # ============================================================
    # Parameter preparation complete → package result
    # ParameterPreparationNode returns "" (empty string) so we use default
    parameter_preparation >> result_preparation

    # ResultPreparationNode returns None to terminate the flow
    # It has THREE entry points:
    # 1. From ParameterPreparationNode - Success (both paths)
    # 2. From ParameterMappingNode - Missing parameters
    # 3. From ValidatorNode - Generation failed after 3 attempts

    logger.info("Planner flow created with 9 nodes: 2-path architecture with convergence at ParameterMappingNode")

    return flow
