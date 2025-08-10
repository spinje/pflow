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

    # Generate workflow → validate
    # WorkflowGeneratorNode returns "validate" so we wire that action
    workflow_generator - "validate" >> validator

    # ============================================================
    # Validation and Retry Loop (Path B only)
    # ============================================================
    # CRITICAL: This retry loop works correctly with 3-attempt limit
    # ValidatorNode tracks generation_attempts and prevents infinite loops

    # Validation succeeds → generate metadata
    validator - "metadata_generation" >> metadata_generation

    # Validation fails but can retry (attempts < 3) → retry generation
    # The validator stores validation_errors for the generator to use
    validator - "retry" >> workflow_generator

    # Validation fails after max attempts (attempts >= 3) → end with failure
    validator - "failed" >> result_preparation

    # Metadata generation complete → converge at parameter mapping
    # MetadataGenerationNode returns "" (empty string) so we use default
    metadata_generation >> parameter_mapping

    # ============================================================
    # Convergence Point: Both paths meet at ParameterMappingNode
    # ============================================================
    # This is the critical verification gate that ensures all required
    # parameters are available before execution

    # All parameters available → prepare for execution
    parameter_mapping - "params_complete" >> parameter_preparation

    # Missing required parameters → end with incomplete params
    parameter_mapping - "params_incomplete" >> result_preparation

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
