"""Flow orchestration for the Natural Language Planner.

This module creates the complete planner meta-workflow that transforms
natural language into executable workflows using a two-path architecture:

Path A (Workflow Reuse): Discovery → Parameter Mapping → Result
Path B (Workflow Generation): Discovery → Browse → Generate → Validate → Metadata → Parameter Mapping → Result

Both paths converge at ParameterMappingNode - the critical verification gate.
"""

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pflow.planning.debug import DebugContext

from pflow.planning.nodes import (
    ComponentBrowsingNode,
    MetadataGenerationNode,
    ParameterDiscoveryNode,
    ParameterMappingNode,
    ParameterPreparationNode,
    PlanningNode,
    RequirementsAnalysisNode,
    ResultPreparationNode,
    ValidatorNode,
    WorkflowDiscoveryNode,
    WorkflowGeneratorNode,
)
from pocketflow import Flow, Node

logger = logging.getLogger(__name__)


def _create_llm_node(
    node_class: type[Node],
    model: str,
    wait: int = 1,
    **extra_params: str | int | float | bool,
) -> Node:
    """Create LLM-powered planning node with consistent configuration.

    This factory function ensures all LLM nodes in the planner have consistent
    model configuration while following PocketFlow's principle of using params
    for node configuration (not shared store).

    Args:
        node_class: The node class to instantiate (e.g., WorkflowDiscoveryNode)
        model: LLM model name (e.g., "anthropic/claude-sonnet-4-5")
        wait: Retry wait time in seconds (default: 1)
        **extra_params: Additional node params like temperature, max_tokens, etc.

    Returns:
        Configured node instance with model and params set

    Example:
        >>> node = _create_llm_node(WorkflowDiscoveryNode, "gemini-2.0-flash-lite", wait=1)
        >>> node.params["model"]
        'gemini-2.0-flash-lite'
    """
    # Nodes that don't accept wait parameter in __init__
    no_wait_nodes = {ValidatorNode, ParameterPreparationNode, ResultPreparationNode}

    # Create node with or without wait parameter
    node = node_class() if node_class in no_wait_nodes else node_class(wait=wait)

    # Set model and any extra params (like temperature, max_tokens)
    node.params = {"model": model, **extra_params}

    return node


def create_planner_flow(
    debug_context: Optional["DebugContext"] = None,
    wait: int = 1,
    model: Optional[str] = None,
) -> "Flow":
    """Create the complete planner meta-workflow.

    This flow implements the sophisticated two-path architecture:
    - Path A: Reuse existing workflows (fast, 10x performance)
    - Path B: Generate new workflows (creative, LLM-powered)

    Key features:
    - Convergence at ParameterMappingNode for both paths
    - Retry mechanism with 3-attempt limit for generation
    - Three entry points to ResultPreparationNode
    - Template variable preservation for workflow reusability

    Args:
        debug_context: Optional DebugContext for debugging capabilities
        wait: Wait time between retries in seconds (default 1, use 0 for tests)
        model: LLM model for all planning nodes. If None, auto-detects based on
               available API keys (Anthropic > Gemini > OpenAI), with fallback
               to claude-sonnet-4-5 for library usage. Supports any model from
               llm library: Anthropic, OpenAI, Gemini, etc.

    Returns:
        The complete planner flow ready for execution

    Note:
        CLI should detect model and error before calling this function.
        The fallback ensures library usage works without CLI.
    """
    from pflow.core.llm_config import get_default_llm_model

    # Auto-detect model if not provided, with fallback for library usage
    if model is None:
        model = get_default_llm_model() or "anthropic/claude-sonnet-4-5"

    # TEMPORARY: Only Anthropic models supported due to llm-gemini library limitations
    # The llm-gemini plugin uses the old response_schema API which doesn't support
    # complex schemas with $ref/$defs that Pydantic generates for nested models.
    #
    # Gemini 2.5 itself DOES support these via the newer responseJsonSchema API,
    # but llm-gemini hasn't been updated to use it yet.
    #
    # TODO: When llm-gemini is updated to use responseJsonSchema:
    #   1. Remove this check
    #   2. Test all planner nodes with Gemini
    #   3. Verify nested Pydantic models work correctly
    #   4. Update documentation to list Gemini as supported
    #
    # Related: https://github.com/simonw/llm-gemini (check for responseJsonSchema support)
    # Block Gemini models - they have issues with Pydantic schemas
    if "gemini" in model.lower():
        raise ValueError(
            f"The planner currently doesn't support Gemini models due to llm-gemini library limitations.\n"
            f"You specified: {model}\n\n"
            f"Supported models:\n"
            f"  - Anthropic: anthropic/claude-sonnet-4-0, claude-opus-4-0, etc.\n"
            f"  - OpenAI: gpt-4o, gpt-4o-mini, etc.\n\n"
            f"Technical details: The llm-gemini plugin uses the old response_schema API\n"
            f"which doesn't support complex schemas. Gemini 2.5 itself supports these via\n"
            f"responseJsonSchema, but the plugin hasn't been updated yet."
        )

    logger.debug(f"Creating planner flow with 11 nodes (model: {model})")

    # Create LLM-powered nodes with factory (ensures consistent model configuration)
    discovery_node: Node = _create_llm_node(WorkflowDiscoveryNode, model, wait)
    component_browsing: Node = _create_llm_node(ComponentBrowsingNode, model, wait)
    parameter_discovery: Node = _create_llm_node(ParameterDiscoveryNode, model, wait)
    requirements_analysis: Node = _create_llm_node(RequirementsAnalysisNode, model, wait)
    planning: Node = _create_llm_node(PlanningNode, model, wait)
    parameter_mapping: Node = _create_llm_node(ParameterMappingNode, model, wait)
    workflow_generator: Node = _create_llm_node(WorkflowGeneratorNode, model, wait)
    metadata_generation: Node = _create_llm_node(MetadataGenerationNode, model, wait)

    # Create non-LLM nodes (no model parameter needed)
    parameter_preparation: Node = ParameterPreparationNode()
    validator: Node = ValidatorNode()
    result_preparation: Node = ResultPreparationNode()

    # If debugging context provided, wrap all nodes
    if debug_context:
        from pflow.planning.debug import DebugWrapper

        # Wrap all nodes with debugging
        # Note: This changes the type but DebugWrapper delegates all Node methods
        discovery_node = DebugWrapper(discovery_node, debug_context)  # type: ignore[assignment]
        component_browsing = DebugWrapper(component_browsing, debug_context)  # type: ignore[assignment]
        parameter_discovery = DebugWrapper(parameter_discovery, debug_context)  # type: ignore[assignment]
        requirements_analysis = DebugWrapper(requirements_analysis, debug_context)  # type: ignore[assignment]
        planning = DebugWrapper(planning, debug_context)  # type: ignore[assignment]
        parameter_mapping = DebugWrapper(parameter_mapping, debug_context)  # type: ignore[assignment]
        parameter_preparation = DebugWrapper(parameter_preparation, debug_context)  # type: ignore[assignment]
        workflow_generator = DebugWrapper(workflow_generator, debug_context)  # type: ignore[assignment]
        validator = DebugWrapper(validator, debug_context)  # type: ignore[assignment]
        metadata_generation = DebugWrapper(metadata_generation, debug_context)  # type: ignore[assignment]
        result_preparation = DebugWrapper(result_preparation, debug_context)  # type: ignore[assignment]

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
    # UPDATED ROUTING FOR TASK 52:
    # Discovery → Parameter Discovery (MOVED) → Requirements → Component Browsing → Planning → Generator

    # Discovery doesn't find workflow → discover parameters first (MOVED HERE)
    discovery_node - "not_found" >> parameter_discovery

    # Parameter discovery → requirements analysis (NEW)
    parameter_discovery >> requirements_analysis
    # Requirements analysis → component browsing
    requirements_analysis >> component_browsing
    # Requirements too vague → result with clarification (NEW ERROR ROUTE)
    requirements_analysis - "clarification_needed" >> result_preparation

    # Component browsing → planning (NEW)
    component_browsing - "generate" >> planning
    # Planning → workflow generator (only for FEASIBLE)
    planning >> workflow_generator
    # Planning determines impossible → result with explanation (NEW ERROR ROUTE)
    planning - "impossible_requirements" >> result_preparation
    # Planning determines partial solution → abort with explanation of missing capabilities
    # Users should know what's missing before attempting generation
    planning - "partial_solution" >> result_preparation
    # TODO: Future enhancement - PARTIAL could retry component_browsing with expanded search
    # This would allow finding alternative components when first selection is insufficient
    # DO NOT implement now - requires careful design to avoid infinite loops

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

    # Validation succeeds → metadata generation
    validator - "metadata_generation" >> metadata_generation

    # Validation fails but can retry (attempts < 3) → retry generation
    # The validator stores validation_errors for the generator to use
    validator - "retry" >> workflow_generator

    # Validation fails after max attempts (attempts >= 3) → end with failure
    validator - "failed" >> result_preparation

    # ============================================================
    # Metadata Generation (Path B only - after validation)
    # ============================================================
    # Metadata generation complete → parameter preparation
    # MetadataGenerationNode returns "" (empty string) so we use default
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

    logger.info("Planner flow created with 11 nodes: 2-path architecture with Requirements/Planning enhancement")

    return flow
