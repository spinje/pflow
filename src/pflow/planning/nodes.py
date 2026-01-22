"""Discovery nodes for the Natural Language Planner meta-workflow.

This module implements the entry point and routing logic for the planner's
two-path architecture (Path A: reuse, Path B: generate).

PocketFlow Node Best Practices Applied:
- Configurable retry parameters in constructors
- Input validation with fallback pattern (shared -> params)
- Clear separation of concerns (prep/exec/post)
- Structured error handling with exec_fallback
- Descriptive action strings for workflow branching
"""

import logging
import re
from typing import Any, Optional

import llm
from pydantic import BaseModel, Field

from pflow.core.exceptions import WorkflowNotFoundError
from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.context_blocks import PlannerContextBuilder
from pflow.planning.context_builder import (
    _build_node_flow,
    build_nodes_context,
    build_planning_context,
    build_workflows_context,
)
from pflow.planning.error_handler import create_fallback_response
from pflow.planning.utils.llm_helpers import parse_structured_response
from pflow.registry import Registry
from pocketflow import Node

logger = logging.getLogger(__name__)


def _is_anthropic_model(model_name: str) -> bool:
    """Check if model is Anthropic (accepts cache_blocks=None)."""
    return model_name.startswith("anthropic/") or model_name.startswith("claude-") or "claude" in model_name.lower()


def _adjust_temperature_for_model(model_name: str, temperature: float) -> float:
    """Adjust temperature for models with specific requirements.

    Some models (like gpt-5 family) only support temperature=1.0 (default).

    Args:
        model_name: Model identifier
        temperature: Requested temperature

    Returns:
        Adjusted temperature value compatible with the model
    """
    # gpt-5 models only support temperature=1.0
    if "gpt-5" in model_name.lower():
        if temperature != 1.0:
            logger.debug(f"Adjusting temperature from {temperature} to 1.0 for {model_name}")
        return 1.0

    return temperature


def _strip_cache_control(cache_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove cache_control markers from cache blocks.

    Used when caching is disabled but we still need the context.

    Args:
        cache_blocks: List of cache blocks with cache_control markers

    Returns:
        List of blocks with cache_control markers removed
    """
    if not cache_blocks:
        return cache_blocks

    return [{"text": block["text"]} for block in cache_blocks if "text" in block]


def _flatten_cache_blocks(cache_blocks: list[dict[str, Any]], prompt: str) -> str:
    """Flatten cache blocks into a single prompt for non-Anthropic models.

    Args:
        cache_blocks: List of cache blocks with 'text' fields
        prompt: The main prompt/instructions

    Returns:
        Combined prompt with all cache block content + instructions
    """
    if not cache_blocks:
        return prompt

    # Extract text from each cache block
    block_texts = [block.get("text", "") for block in cache_blocks if "text" in block]

    # Combine: cache blocks first (context), then instructions
    combined = "\n\n".join(block_texts)
    if prompt:
        combined = combined + "\n\n" + prompt

    return combined


def _build_llm_kwargs(
    model_name: str,
    cache_planner: bool,
    cache_blocks: Optional[list[dict[str, Any]]],
    prompt: str,
    **kwargs: Any,
) -> tuple[str, dict[str, Any]]:
    """Build kwargs and prompt for model.prompt() with proper cache_blocks handling.

    Anthropic models accept cache_blocks=None (handled by our monkey-patch),
    but OpenAI/Gemini reject it (Pydantic extra='forbid'). For non-Anthropic models,
    we flatten cache_blocks into the prompt itself.

    Args:
        model_name: Model identifier (to detect Anthropic vs others)
        cache_planner: Whether caching is enabled
        cache_blocks: Cache blocks to use
        prompt: The main prompt/instructions
        **kwargs: Other parameters (schema, temperature, etc.)

    Returns:
        Tuple of (modified_prompt, kwargs_dict)
    """
    llm_kwargs = dict(kwargs)
    final_prompt = prompt

    # Adjust temperature for model compatibility
    if "temperature" in llm_kwargs:
        llm_kwargs["temperature"] = _adjust_temperature_for_model(model_name, llm_kwargs["temperature"])

    if _is_anthropic_model(model_name):
        # Anthropic: only set cache_blocks if we have actual blocks (not None or [])
        # Empty list causes "list index out of range" in cached path
        if cache_blocks:  # Truthy check excludes both None and []
            if cache_planner:
                llm_kwargs["cache_blocks"] = cache_blocks
            else:
                # Strip cache_control markers when caching disabled
                llm_kwargs["cache_blocks"] = _strip_cache_control(cache_blocks)
        # else: Don't set cache_blocks key at all (avoids passing [] or None)
    else:
        # Non-Anthropic models (OpenAI, Gemini, etc.)
        # Flatten cache_blocks into the prompt since they don't support multi-block caching
        if cache_blocks:
            final_prompt = _flatten_cache_blocks(cache_blocks, prompt)
        # Disable streaming for non-Anthropic to avoid response parsing issues
        llm_kwargs["stream"] = False

    return final_prompt, llm_kwargs


# Pydantic models for structured LLM output
class WorkflowDecision(BaseModel):
    """Decision structure for workflow discovery."""

    found: bool = Field(description="True if complete workflow match exists")
    workflow_name: Optional[str] = Field(None, description="Name of matched workflow (if found)")
    confidence: float = Field(description="Match confidence 0.0-1.0")
    reasoning: str = Field(description="LLM reasoning for decision")


class ComponentSelection(BaseModel):
    """Selection structure for component browsing."""

    node_ids: list[str] = Field(description="Selected node type identifiers")
    workflow_names: list[str] = Field(description="Selected workflow names as building blocks")
    reasoning: str = Field(description="Selection rationale")


class RequirementsSchema(BaseModel):
    """Schema for requirements analysis output."""

    is_clear: bool = Field(description="True if requirements can be extracted")
    clarification_needed: Optional[str] = Field(None, description="Message if input too vague")
    steps: list[str] = Field(default_factory=list, description="Abstract operational requirements")
    estimated_nodes: int = Field(0, description="Estimated number of nodes needed")
    required_capabilities: list[str] = Field(default_factory=list, description="Services/capabilities needed")
    complexity_indicators: dict[str, Any] = Field(default_factory=dict, description="Complexity analysis")


class WorkflowDiscoveryNode(Node):
    """Entry point node that routes between workflow reuse (Path A) and generation (Path B).

    Makes a binary decision: complete workflow match exists ("found_existing") or not ("not_found").
    This single decision determines whether to reuse an existing workflow or generate a new one.

    Interface:
    - Reads: user_input (str), stdin_data (Any, optional), current_date (str, optional)
    - Writes: discovery_context (str), discovery_result (dict), found_workflow (dict, Path A only)
    - Actions: found_existing (Path A), not_found (Path B)
    """

    name = "workflow-discovery"  # For registry discovery

    def __init__(self, max_retries: int = 2, wait: float = 1.0) -> None:
        """Initialize with retry support for LLM operations.

        Args:
            max_retries: Number of retries on LLM failure (default 2)
            wait: Wait time between retries in seconds (default 1.0)
        """
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare discovery context for semantic matching.

        Args:
            shared: PocketFlow shared store

        Returns:
            Dict with user_input and discovery_context

        Raises:
            ValueError: If required user_input is missing
        """
        logger.debug("WorkflowDiscoveryNode: Preparing discovery context", extra={"phase": "prep"})

        # Data flow: shared store first, then params fallback
        user_input = shared.get("user_input") or self.params.get("user_input", "")
        if not user_input:
            raise ValueError("Missing required 'user_input' in shared store or params")

        # Configuration from params with defaults
        model_name = self.params.get("model", "anthropic/claude-sonnet-4-5")
        temperature = self.params.get("temperature", 0.0)

        # Get WorkflowManager from shared store if available
        workflow_manager = shared.get("workflow_manager")

        # Load workflows context for discovery (no nodes needed for reuse decisions)
        try:
            discovery_context = build_workflows_context(
                workflow_names=None,  # All workflows
                workflow_manager=workflow_manager,  # Pass from shared store
            )
        except Exception as e:
            logger.exception("Failed to build discovery context", extra={"phase": "prep", "error": str(e)})
            raise ValueError(f"Context preparation failed: {e}") from e

        # Get cache_planner flag from shared store
        cache_planner = shared.get("cache_planner", False)

        return {
            "user_input": user_input,
            "discovery_context": discovery_context,
            "model_name": model_name,
            "temperature": temperature,
            "cache_planner": cache_planner,
        }

    def _build_cache_blocks(
        self, discovery_context: str, user_input: str, cache_planner: bool
    ) -> tuple[list[dict], str]:
        """Build cache blocks for discovery node with special context handling.

        Args:
            discovery_context: The workflow descriptions to potentially cache
            user_input: The user's request
            cache_planner: Whether caching is enabled

        Returns:
            Tuple of (cache_blocks, formatted_prompt)
        """

        # If caching is disabled, return full formatted prompt with no cache blocks
        if not cache_planner:
            from pflow.planning.prompts.loader import format_prompt, load_prompt

            prompt_template = load_prompt("discovery")
            formatted_prompt = format_prompt(
                prompt_template, {"discovery_context": discovery_context, "user_input": user_input}
            )
            # Return empty cache blocks and full formatted prompt
            return [], formatted_prompt

        # Special caching logic for discovery context
        from pflow.planning.prompts.loader import load_prompt

        prompt_template = load_prompt("discovery")
        cache_blocks = []

        if "## Context" in prompt_template:
            instructions, _ = prompt_template.split("## Context", 1)

            # Always cache instructions when they exist
            instructions = instructions.strip()
            if instructions:
                cache_blocks.append({"text": instructions, "cache_control": {"type": "ephemeral", "ttl": "1h"}})

            # Build and cache the discovery context
            # Always include as cache block for consistent structure, even if empty
            context_block = f"""## Context

<existing_workflows>
{discovery_context if discovery_context else "No existing workflows found."}
</existing_workflows>"""

            # Always add context as cache block when caching is enabled
            # This ensures consistent structure whether workflows exist or not
            cache_blocks.append({"text": context_block, "cache_control": {"type": "ephemeral", "ttl": "1h"}})

            # Return dynamic part only
            formatted_prompt = f"""## Inputs

<user_request>
{user_input}
</user_request>"""
        else:
            # Fallback if template structure is unexpected
            from pflow.planning.prompts.loader import format_prompt

            formatted_prompt = format_prompt(
                prompt_template, {"discovery_context": discovery_context, "user_input": user_input}
            )

        return cache_blocks, formatted_prompt

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute semantic matching against existing workflows.

        Args:
            prep_res: Prepared data with user_input and discovery_context

        Returns:
            WorkflowDecision dict with found, workflow_name, confidence, reasoning
        """
        logger.debug(f"WorkflowDiscoveryNode: Matching request: {prep_res['user_input'][:100]}...")

        # Early return if no workflows exist - skip expensive LLM call
        if not prep_res["discovery_context"]:  # Empty string when no workflows
            logger.info(
                "WorkflowDiscoveryNode: No workflows exist, skipping LLM call",
                extra={"phase": "exec", "optimization": "zero_workflows"},
            )
            return {
                "found": False,
                "workflow_name": None,
                "confidence": 1.0,
                "reasoning": "No existing workflows in the system to match against",
            }

        # Check if caching is enabled for cache_control markers
        cache_planner = prep_res.get("cache_planner", False)

        # Lazy-load model at execution time (PocketFlow best practice)
        model = llm.get_model(prep_res["model_name"])

        # Build cache blocks using node-specific logic
        cache_blocks, formatted_prompt = self._build_cache_blocks(
            prep_res["discovery_context"], prep_res["user_input"], cache_planner
        )

        # Build kwargs with proper cache_blocks handling for different model types
        final_prompt, kwargs = _build_llm_kwargs(
            prep_res["model_name"],
            cache_planner,
            cache_blocks,
            formatted_prompt,
            schema=WorkflowDecision,
            temperature=prep_res["temperature"],
        )

        response = model.prompt(final_prompt, **kwargs)

        result = parse_structured_response(response, WorkflowDecision)

        logger.info(
            f"WorkflowDiscoveryNode: Decision - found={result['found']}, "
            f"workflow={result.get('workflow_name')}, confidence={result['confidence']}",
            extra={"phase": "exec", "found": result["found"], "confidence": result["confidence"]},
        )

        return result

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store discovery results and route to appropriate path.

        Args:
            shared: PocketFlow shared store
            prep_res: Prepared data
            exec_res: Execution result (WorkflowDecision)

        Returns:
            "found_existing" for Path A or "not_found" for Path B
        """
        # Store discovery results
        shared["discovery_result"] = exec_res
        shared["discovery_context"] = prep_res["discovery_context"]

        # If found, load the complete workflow metadata
        if exec_res["found"] and exec_res.get("workflow_name"):
            # Get WorkflowManager from shared store or create default
            workflow_manager = shared.get("workflow_manager", WorkflowManager())
            try:
                # load() returns full metadata wrapper with keys:
                # name, description, ir, created_at, updated_at, version
                shared["found_workflow"] = workflow_manager.load(exec_res["workflow_name"])
                logger.info(
                    f"WorkflowDiscoveryNode: Found existing workflow '{exec_res['workflow_name']}' - routing to Path A",
                    extra={"phase": "post", "action": "found_existing", "workflow": exec_res["workflow_name"]},
                )
                return "found_existing"
            except WorkflowNotFoundError:
                logger.warning(
                    f"WorkflowDiscoveryNode: Workflow '{exec_res['workflow_name']}' not found on disk",
                    extra={"phase": "post", "workflow": exec_res["workflow_name"]},
                )

        logger.info(
            "WorkflowDiscoveryNode: No complete workflow match - routing to Path B for generation",
            extra={"phase": "post", "action": "not_found"},
        )
        return "not_found"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """WorkflowDiscoveryNode is critical - abort on LLM failure.

        Args:
            prep_res: Prepared data
            exc: Exception that occurred

        Raises:
            CriticalPlanningError: Always, as this node is critical for workflow routing
        """
        from pflow.core.exceptions import CriticalPlanningError
        from pflow.planning.error_handler import classify_error

        # Classify the error for better user messaging
        planner_error = classify_error(exc, context="WorkflowDiscoveryNode")

        # WorkflowDiscoveryNode is critical - we cannot route between paths without
        # determining if a workflow exists. Abort the flow with a clear error message.
        raise CriticalPlanningError(
            node_name="WorkflowDiscoveryNode",
            reason=f"Cannot determine workflow routing: {planner_error.message}. {planner_error.user_action}",
            original_error=exc,
        )


class ComponentBrowsingNode(Node):
    """Browse available components for workflow generation (Path B only).

    Selects nodes and workflows as building blocks for the generator.
    Uses over-inclusive selection to avoid missing critical components.

    Interface:
    - Reads: user_input (str), stdin_data (Any, optional), current_date (str, optional)
    - Writes: browsed_components (dict), planning_context (str or empty), registry_metadata (dict)
    - Actions: generate (always, continues Path B to ParameterDiscoveryNode)
    """

    name = "component-browsing"  # For registry discovery

    def __init__(self, max_retries: int = 2, wait: float = 1.0) -> None:
        """Initialize with retry support for LLM operations.

        Args:
            max_retries: Number of retries on LLM failure (default 2)
            wait: Wait time between retries in seconds (default 1.0)
        """
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare discovery context and load registry metadata.

        Args:
            shared: PocketFlow shared store

        Returns:
            Dict with user_input, discovery_context, and registry_metadata

        Raises:
            ValueError: If required user_input is missing or registry fails to load
        """
        logger.debug("ComponentBrowsingNode: Loading registry and preparing context", extra={"phase": "prep"})

        # Data flow: shared store first, then params fallback
        user_input = shared.get("user_input") or self.params.get("user_input", "")
        if not user_input:
            raise ValueError("Missing required 'user_input' in shared store or params")

        # Configuration from params with defaults
        model_name = self.params.get("model", "anthropic/claude-sonnet-4-5")
        temperature = self.params.get("temperature", 0.0)

        # Instantiate Registry directly (PocketFlow pattern)
        try:
            registry = Registry()
            registry_metadata = registry.load()  # Now returns filtered nodes by default
            if not registry_metadata:
                logger.warning("Registry returned empty metadata, using empty dict", extra={"phase": "prep"})
                registry_metadata = {}
        except Exception as e:
            logger.exception("Failed to load registry", extra={"phase": "prep", "error": str(e)})
            # Continue with empty registry rather than failing
            registry_metadata = {}

        # Get WorkflowManager from shared store if available
        workflow_manager = shared.get("workflow_manager")

        # Build separate contexts for nodes and workflows
        try:
            nodes_context = build_nodes_context(
                node_ids=None,  # All nodes
                registry_metadata=registry_metadata,
            )
            workflows_context = build_workflows_context(
                workflow_names=None,  # All workflows
                workflow_manager=workflow_manager,  # Pass from shared store
            )
        except Exception as e:
            logger.exception("Failed to build browsing contexts", extra={"phase": "prep", "error": str(e)})
            raise ValueError(f"Context preparation failed: {e}") from e

        # NEW: Get requirements if available (from RequirementsAnalysisNode)
        requirements_result = shared.get("requirements_result", {})

        # Get cache_planner flag from shared store
        cache_planner = shared.get("cache_planner", False)

        return {
            "user_input": user_input,
            "nodes_context": nodes_context,
            "workflows_context": workflows_context,
            "registry_metadata": registry_metadata,
            "requirements_result": requirements_result,  # NEW
            "model_name": model_name,
            "temperature": temperature,
            "cache_planner": cache_planner,
        }

    def _build_cache_blocks(
        self, nodes_context: str, workflows_context: str, user_input: str, requirements: str, cache_planner: bool
    ) -> tuple[list[dict], str]:
        """Build cache blocks for component browsing with special documentation handling.

        Args:
            nodes_context: Node documentation to potentially cache
            workflows_context: Workflow documentation to potentially cache
            user_input: The user's request
            requirements: Extracted requirements
            cache_planner: Whether caching is enabled

        Returns:
            Tuple of (cache_blocks, formatted_prompt)
        """
        from pflow.planning.utils.prompt_cache_helper import build_cached_prompt

        # If caching is disabled, use the standard helper without caching
        if not cache_planner:
            return build_cached_prompt(
                "component_browsing",
                all_variables={
                    "nodes_context": nodes_context,
                    "workflows_context": workflows_context,
                    "user_input": user_input,
                    "requirements": requirements,
                },
                enable_caching=False,  # Don't create cache blocks
            )

        # Special caching logic for node/workflow documentation
        from pflow.planning.prompts.loader import load_prompt

        prompt_template = load_prompt("component_browsing")
        cache_blocks = []

        if "## Context" in prompt_template:
            instructions, _ = prompt_template.split("## Context", 1)

            # Always cache instructions when they exist
            instructions = instructions.strip()
            if instructions:
                cache_blocks.append({"text": instructions, "cache_control": {"type": "ephemeral", "ttl": "1h"}})

            # Build context with cacheable documentation
            context_parts = ["## Context"]

            # Always add documentation to cache when it exists
            if nodes_context:
                context_parts.append(f"\n<available_nodes>\n{nodes_context}\n</available_nodes>")

            if workflows_context:
                # TODO: Uncomment this when nested workflows are supported
                # context_parts.append(f"\n<available_workflows>\n{workflows_context}\n</available_workflows>")
                pass

            # Cache context if we have substantial documentation
            if len(context_parts) > 1:
                cache_blocks.append({
                    "text": "".join(context_parts),
                    "cache_control": {"type": "ephemeral", "ttl": "1h"},
                })

            # Return dynamic part only
            formatted_prompt = f"""## Inputs

<user_request>
{user_input}
</user_request>

<extracted_requirements>
{requirements}
</extracted_requirements>"""
        else:
            # Fallback if template structure is unexpected
            from pflow.planning.prompts.loader import format_prompt

            formatted_prompt = format_prompt(
                prompt_template,
                {
                    "nodes_context": nodes_context,
                    "workflows_context": workflows_context,
                    "user_input": user_input,
                    "requirements": requirements,
                },
            )

        return cache_blocks, formatted_prompt

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Select components with over-inclusive approach.

        Args:
            prep_res: Prepared data with user_input, nodes_context, workflows_context, registry_metadata

        Returns:
            ComponentSelection dict with node_ids, workflow_names, reasoning
        """
        logger.debug(f"ComponentBrowsingNode: Browsing components for: {prep_res['user_input'][:1000]}...")

        # Build requirements context if available
        requirements_text = "None"
        if prep_res.get("requirements_result") and prep_res["requirements_result"].get("steps"):
            steps = prep_res["requirements_result"]["steps"]
            requirements_text = "\n".join(f"- {step}" for step in steps)

        # Check if caching is enabled for cache_control markers
        cache_planner = prep_res.get("cache_planner", False)

        # Lazy-load model at execution time (PocketFlow best practice)
        model = llm.get_model(prep_res["model_name"])

        # Build cache blocks using node-specific logic
        cache_blocks, formatted_prompt = self._build_cache_blocks(
            prep_res["nodes_context"],
            prep_res["workflows_context"],
            prep_res["user_input"],
            requirements_text,
            cache_planner,
        )

        # Build kwargs with proper cache_blocks handling for different model types
        final_prompt, kwargs = _build_llm_kwargs(
            prep_res["model_name"],
            cache_planner,
            cache_blocks,
            formatted_prompt,
            schema=ComponentSelection,
            temperature=prep_res["temperature"],
        )

        response = model.prompt(final_prompt, **kwargs)

        result = parse_structured_response(response, ComponentSelection)

        # IMPORTANT: Clear workflow_names to prevent confusion
        # Until nested workflow execution is supported (Task 59), we can't use workflows as nodes
        if result.get("workflow_names"):
            logger.info(
                f"ComponentBrowsingNode: Ignoring {len(result['workflow_names'])} workflows "
                "(nested workflows not supported yet)",
                extra={"phase": "exec", "ignored_workflows": result["workflow_names"]},
            )
            result["workflow_names"] = []  # Clear workflows

        logger.info(
            f"ComponentBrowsingNode: Selected {len(result['node_ids'])} nodes",
            extra={
                "phase": "exec",
                "node_count": len(result["node_ids"]),
            },
        )

        return result

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store browsing results and prepare planning context.

        Args:
            shared: PocketFlow shared store
            prep_res: Prepared data
            exec_res: Execution result (ComponentSelection)

        Returns:
            Always "generate" to continue Path B
        """
        logger.debug(
            "ComponentBrowsingNode: Building planning context for selected components", extra={"phase": "post"}
        )

        # Store browsing results
        shared["browsed_components"] = exec_res
        shared["registry_metadata"] = prep_res["registry_metadata"]

        # Get WorkflowManager from shared store if available
        workflow_manager = shared.get("workflow_manager")

        # Get detailed planning context for selected components
        # IMPORTANT: We pass empty workflow_names to prevent the LLM from trying
        # to use workflows as nodes (which would fail at runtime).
        # Until nested workflow execution is supported (Task 59), we only provide nodes.
        planning_context = build_planning_context(
            selected_node_ids=exec_res["node_ids"],
            selected_workflow_names=[],  # Disabled until nested workflows supported
            registry_metadata=prep_res["registry_metadata"],
            saved_workflows=None,  # Will load automatically
            workflow_manager=workflow_manager,  # Pass from shared store
        )

        # Check if planning_context is error dict
        if isinstance(planning_context, dict) and "error" in planning_context:
            logger.warning(
                f"ComponentBrowsingNode: Planning context error - {planning_context['error']}",
                extra={
                    "phase": "post",
                    "error": planning_context["error"],
                    "missing_nodes": planning_context.get("missing_nodes", []),
                    "missing_workflows": planning_context.get("missing_workflows", []),
                },
            )
            shared["planning_context"] = ""  # Empty context on error
        else:
            shared["planning_context"] = planning_context
            logger.debug(
                f"ComponentBrowsingNode: Planning context prepared ({len(planning_context)} chars)",
                extra={"phase": "post", "context_size": len(planning_context)},
            )

        # Always route to generation (Path B continues)
        logger.info(
            "ComponentBrowsingNode: Routing to parameter discovery and generation",
            extra={"phase": "post", "action": "generate"},
        )
        return "generate"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """ComponentBrowsingNode is critical - abort on LLM failure.

        Args:
            prep_res: Prepared data
            exc: Exception that occurred

        Raises:
            CriticalPlanningError: Always, as this node is critical for workflow generation
        """
        from pflow.core.exceptions import CriticalPlanningError
        from pflow.planning.error_handler import classify_error

        # Classify the error for better user messaging
        planner_error = classify_error(exc, context="ComponentBrowsingNode")

        # ComponentBrowsingNode is critical - we cannot generate workflows without knowing
        # what components are available. Abort the flow with a clear error message.
        raise CriticalPlanningError(
            node_name="ComponentBrowsingNode",
            reason=f"Cannot select workflow components: {planner_error.message}. {planner_error.user_action}",
            original_error=exc,
        )


# Pydantic models for parameter management
class ParameterDiscovery(BaseModel):
    """Structure for discovered parameters from natural language."""

    parameters: dict[str, Any] = Field(description="Named parameters extracted from user input")
    stdin_type: Optional[str] = Field(None, description="Type of stdin data if present (text/binary/file)")
    reasoning: str = Field(description="Explanation of parameter extraction")


class ParameterExtraction(BaseModel):
    """Structure for parameter mapping to workflow inputs."""

    extracted: dict[str, Any] = Field(description="Parameters mapped to workflow inputs")
    missing: list[str] = Field(description="List of missing required parameters")
    confidence: float = Field(description="Confidence in extraction 0.0-1.0")
    reasoning: str = Field(description="Explanation of mapping decisions")


class ParameterDiscoveryNode(Node):
    """Extract named parameters from natural language (Path B only).

    Analyzes user input to discover parameter hints BEFORE generation.
    These hints provide context to help the generator create appropriate final inputs for the workflow.

    Interface:
    - Reads: user_input (str), stdin (optional), planning_context (str or empty), browsed_components (dict)
    - Writes: discovered_params (dict), stdin metadata
    - Actions: Returns to continue Path B to generation
    """

    name = "parameter-discovery"  # For registry discovery

    def __init__(self, max_retries: int = 2, wait: float = 1.0) -> None:
        """Initialize with retry support for LLM operations.

        Args:
            max_retries: Number of retries on LLM failure (default 2)
            wait: Wait time between retries in seconds (default 1.0)
        """
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare context for parameter discovery.

        Args:
            shared: PocketFlow shared store

        Returns:
            Dict with user_input, stdin info, and planning context

        Raises:
            ValueError: If required user_input is missing
        """
        logger.debug("ParameterDiscoveryNode: Preparing for parameter discovery", extra={"phase": "prep"})

        # Data flow: shared store first, then params fallback
        user_input = shared.get("user_input") or self.params.get("user_input", "")
        if not user_input:
            raise ValueError("Missing required 'user_input' in shared store or params")

        # Configuration from params with defaults
        model_name = self.params.get("model", "anthropic/claude-sonnet-4-5")
        temperature = self.params.get("temperature", 0.0)

        # Note: stdin data is now routed to workflow inputs via stdin: true
        # in the workflow IR, handled by the CLI. The planner no longer needs
        # to know about stdin content.
        stdin_info = None

        # Get planning context (might be empty string on error)
        planning_context = shared.get("planning_context", "")
        browsed_components = shared.get("browsed_components", {})

        # Get cache_planner flag from shared store
        cache_planner = shared.get("cache_planner", False)

        return {
            "user_input": user_input,
            "stdin_info": stdin_info,
            "planning_context": planning_context,
            "browsed_components": browsed_components,
            "model_name": model_name,
            "temperature": temperature,
            "cache_planner": cache_planner,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Extract named parameters from natural language.

        Args:
            prep_res: Prepared data with user_input and context

        Returns:
            ParameterDiscovery dict with parameters, stdin_type, reasoning
        """
        logger.debug(f"ParameterDiscoveryNode: Discovering parameters from: {prep_res['user_input'][:1000]}...")

        # Load prompt from markdown file
        from pflow.planning.utils.prompt_cache_helper import build_cached_prompt

        # Prepare stdin info for the prompt
        stdin_info = prep_res.get("stdin_info", "None") or "None"

        # Check if caching is enabled for cache_control markers
        cache_planner = prep_res.get("cache_planner", False)

        # Lazy-load model at execution time (PocketFlow best practice)
        model = llm.get_model(prep_res["model_name"])

        # Prepare only the variables actually used by the prompt
        # Note: planning_context, selected_nodes, selected_workflows are removed
        # as they're always empty at this stage (this node runs before ComponentBrowsingNode)
        all_vars = {
            "user_input": prep_res["user_input"],
            "stdin_info": stdin_info,
        }

        # Build cache blocks based on cache_planner flag
        cache_blocks, formatted_prompt = build_cached_prompt(
            "parameter_discovery",
            all_variables=all_vars,
            cacheable_variables=None,  # No cacheable context for this node
            enable_caching=cache_planner,
        )

        # Build kwargs with proper cache_blocks handling for different model types
        final_prompt, kwargs = _build_llm_kwargs(
            prep_res["model_name"],
            cache_planner,
            cache_blocks,
            formatted_prompt,
            schema=ParameterDiscovery,
            temperature=prep_res["temperature"],
        )

        response = model.prompt(final_prompt, **kwargs)

        result = parse_structured_response(response, ParameterDiscovery)

        # Create templatized version of user input
        templatized_input = self._templatize_user_input(prep_res["user_input"], result["parameters"])

        # Add templatized input to result
        result["templatized_input"] = templatized_input

        logger.info(
            f"ParameterDiscoveryNode: Discovered {len(result['parameters'])} parameters",
            extra={"phase": "exec", "param_count": len(result["parameters"]), "stdin": result.get("stdin_type")},
        )

        return result

    def _templatize_user_input(self, user_input: str, params: dict) -> str:
        """Replace parameter values in user input with ${param_name} placeholders.

        Args:
            user_input: Original user request
            params: Discovered parameters from LLM

        Returns:
            User input with values replaced by ${param_name}
        """
        if not params:
            return user_input

        transformed = user_input

        # Sort by value length (longest first) to avoid partial replacements
        # e.g., replace "2024-01-01" before "2024"
        sorted_params = sorted(params.items(), key=lambda x: len(str(x[1])) if x[1] is not None else 0, reverse=True)

        for param_name, param_value in sorted_params:
            if param_value is None or param_value == "":
                continue

            # Convert to string for replacement
            value_str = str(param_value)

            # Replace all occurrences with template variable
            if value_str in transformed:
                # Use ${} syntax to match our template system
                transformed = transformed.replace(value_str, f"${{{param_name}}}")

        return transformed

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store discovered parameters and continue Path B.

        Args:
            shared: PocketFlow shared store
            prep_res: Prepared data
            exec_res: Execution result (ParameterDiscovery)

        Returns:
            Always returns to continue Path B (no action string needed)
        """
        # Store discovered parameters
        shared["discovered_params"] = exec_res["parameters"]

        # Store templatized user input
        shared["templatized_input"] = exec_res.get("templatized_input", shared.get("user_input", ""))

        # Store error info separately if present (for error extraction)
        if "_error" in exec_res:
            shared["_discovered_params_error"] = exec_res["_error"]

        logger.info(
            f"ParameterDiscoveryNode: Stored {len(exec_res['parameters'])} discovered parameters",
            extra={"phase": "post", "parameters": list(exec_res["parameters"].keys())},
        )

        # Path B continues to generation
        return ""  # No action string needed for simple continuation

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle LLM failures gracefully with intelligent error classification.

        Args:
            prep_res: Prepared data
            exc: Exception that occurred

        Returns:
            Safe default ParameterDiscovery matching exec() return type
        """
        safe_response, planner_error = create_fallback_response("ParameterDiscoveryNode", exc, prep_res)

        # Note: We cannot store the error in shared store from exec_fallback
        # as shared store is not accessible here in PocketFlow architecture.
        # The error is embedded in the response for later processing.

        return safe_response


class RequirementsAnalysisNode(Node):
    """Extract abstract operational requirements from templatized input (Path B only).

    Takes templatized input from ParameterDiscoveryNode and extracts WHAT needs to be done
    without implementation details. Abstracts values but keeps services explicit.

    Also calculates complexity score and allocates thinking tokens for downstream nodes.

    Interface:
    - Reads: templatized_input (str), user_input (str fallback)
    - Writes: requirements_result (dict), complexity_analysis (dict)
    - Actions: "" (success) or "clarification_needed"
    """

    name = "requirements-analysis"  # For registry discovery

    def __init__(self, max_retries: int = 2, wait: float = 1.0) -> None:
        """Initialize with retry support for LLM operations.

        Args:
            max_retries: Number of retries on LLM failure (default 2)
            wait: Wait time between retries in seconds (default 1.0)
        """
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare context for requirements extraction.

        Args:
            shared: PocketFlow shared store

        Returns:
            Dict with templatized_input and model configuration

        Raises:
            ValueError: If no input is available
        """
        logger.debug("RequirementsAnalysisNode: Preparing for requirements extraction", extra={"phase": "prep"})

        # Get templatized input from ParameterDiscoveryNode (preferred)
        # Falls back to user_input if templatization didn't happen
        templatized_input = shared.get("templatized_input")
        user_input = shared.get("user_input") or self.params.get("user_input", "")

        input_text = templatized_input or user_input
        if not input_text:
            raise ValueError("Missing required input (templatized_input or user_input)")

        # Configuration from params with defaults
        model_name = self.params.get("model", "anthropic/claude-sonnet-4-5")
        temperature = self.params.get("temperature", 0.0)

        # Get cache_planner flag from shared store
        cache_planner = shared.get("cache_planner", False)

        return {
            "input_text": input_text,
            "is_templatized": bool(templatized_input),
            "model_name": model_name,
            "temperature": temperature,
            "cache_planner": cache_planner,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Extract abstract requirements using LLM.

        Args:
            prep_res: Prepared data with input_text and model config

        Returns:
            RequirementsSchema dict with extraction results
        """
        logger.debug(f"RequirementsAnalysisNode: Extracting requirements from: {prep_res['input_text'][:100]}...")

        # Load prompt from markdown file
        from pflow.planning.utils.prompt_cache_helper import build_cached_prompt

        # Check if caching is enabled for cache_control markers
        cache_planner = prep_res.get("cache_planner", False)

        # Load model
        model = llm.get_model(prep_res["model_name"])

        # Prepare all variables for the prompt template
        all_vars = {
            "input_text": prep_res["input_text"],
        }

        # Build cache blocks based on cache_planner flag
        cache_blocks, formatted_prompt = build_cached_prompt(
            "requirements_analysis",
            all_variables=all_vars,
            cacheable_variables=None,  # No cacheable context for this node
            enable_caching=cache_planner,
        )

        # Build kwargs with proper cache_blocks handling for different model types
        final_prompt, kwargs = _build_llm_kwargs(
            prep_res["model_name"],
            cache_planner,
            cache_blocks,
            formatted_prompt,
            schema=RequirementsSchema,
            temperature=prep_res["temperature"],
        )

        response = model.prompt(final_prompt, **kwargs)
        result = parse_structured_response(response, RequirementsSchema)

        logger.info(
            f"RequirementsAnalysisNode: Extracted {len(result.get('steps', []))} requirements, "
            f"is_clear={result.get('is_clear', False)}",
            extra={
                "phase": "exec",
                "is_clear": result.get("is_clear", False),
                "steps_count": len(result.get("steps", [])),
                "capabilities": result.get("required_capabilities", []),
            },
        )

        return result

    def _calculate_complexity_score(self, requirements: dict[str, Any]) -> float:
        """Calculate workflow complexity score based on requirements.

        Improved linear scoring for better predictability:
        - Each node contributes 2.5 points
        - Each capability contributes 4 points
        - Operation patterns add fixed points
        - Binary indicators have higher weights

        Args:
            requirements: Requirements analysis result

        Returns:
            Complexity score (typically 0-150, uncapped)
        """
        score = 0.0

        # 1. Linear node contribution (2.5 points per node)
        # More predictable than buckets, scales naturally
        estimated_nodes = requirements.get("estimated_nodes", 0)
        score += estimated_nodes * 2.5

        # 2. Linear capability contribution (4 points per capability)
        # No artificial cap - complex workflows with many services score appropriately
        capabilities = requirements.get("required_capabilities", [])
        score += len(capabilities) * 4

        # 3. Operation complexity from steps (0-25 points)
        # Keep existing scoring - it works well
        steps = requirements.get("steps", [])
        score += self._score_operation_complexity(steps)

        # 4. Binary complexity indicators with higher weights
        indicators = requirements.get("complexity_indicators", {})
        if indicators.get("has_conditional"):
            score += 10  # Conditionals add significant complexity
        if indicators.get("has_iteration"):
            score += 12  # Loops are even more complex
        if indicators.get("has_external_services"):
            # Each external service adds complexity
            external_services = indicators.get("external_services", [])
            score += len(external_services) * 5

        # 5. Multipliers for special complexity patterns
        # Error handling adds 20% complexity
        if any("error" in step.lower() or "fallback" in step.lower() for step in requirements.get("steps", [])):
            score = score * 1.2

        # State management adds complexity (rare but important)
        if any("state" in step.lower() or "memory" in step.lower() for step in requirements.get("steps", [])):
            score = score * 1.15

        return float(score)

    def _score_operation_complexity(self, steps: list[str]) -> float:
        """Score complexity based on operation patterns in steps.

        Args:
            steps: List of operational requirement steps

        Returns:
            Operation complexity score (0-25 points)
        """
        score = 0
        complexity_patterns = {
            # Pattern: (keywords, points)
            "conditional": (["if", "when", "based on", "depending", "otherwise"], 5),
            "iteration": (["for each", "iterate", "loop", "batch", "all items"], 5),
            "aggregation": (["combine", "merge", "aggregate", "collect", "gather"], 4),
            "transformation": (["transform", "convert", "parse", "extract", "process"], 3),
            "analysis": (["analyze", "evaluate", "assess", "determine", "calculate"], 4),
            "orchestration": (["coordinate", "orchestrate", "sequence", "pipeline"], 4),
        }

        for _, (keywords, points) in complexity_patterns.items():
            for step in steps:
                if any(keyword in step.lower() for keyword in keywords):
                    score += points
                    break  # Only count each pattern once

        return min(25, score)

    def _calculate_thinking_budget(self, complexity_score: float) -> int:
        """Calculate thinking token budget based on complexity score.

        Three-tier system optimized for cache sharing:
        - Most workflows use 4096 tokens (same cache pool)
        - Only truly trivial workflows use 0
        - Complex workflows get 16384 or 32768

        CRITICAL: Returns same budget for BOTH Planning and Generator nodes
        to preserve cache sharing optimization across different user queries.

        Args:
            complexity_score: Calculated complexity score

        Returns:
            Number of thinking tokens to allocate
        """
        if complexity_score < 40:
            # Only trivial workflows
            # ~40% of workflows
            return 0
        elif complexity_score < 70:
            # Standard workflows - the majority (~40%)
            # This creates a large cache pool that most workflows share
            return 4096
        elif complexity_score < 100:
            # Complex multi-step pipelines (~15%)
            return 16384
        else:
            # Extreme complexity - rare but important (~1-5%)
            return 32768

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store requirements and route based on clarity.

        Args:
            shared: PocketFlow shared store
            prep_res: Prepared data
            exec_res: Execution result (RequirementsSchema)

        Returns:
            "" for success or "clarification_needed" for vague input
        """
        # Calculate complexity score and thinking budget
        complexity_score = self._calculate_complexity_score(exec_res)
        thinking_budget = self._calculate_thinking_budget(complexity_score)

        # Store complexity analysis in shared store
        shared["complexity_analysis"] = {
            "score": complexity_score,
            "thinking_budget": thinking_budget,  # SAME for both Planning and Generator
            "reasoning": f"Complexity {complexity_score:.1f} based on {exec_res.get('estimated_nodes', 0)} nodes, "
            f"{len(exec_res.get('steps', []))} steps, {len(exec_res.get('required_capabilities', []))} capabilities",
        }

        # Log complexity decision
        if thinking_budget > 0:
            logger.info(
                f"RequirementsAnalysisNode: Complexity {complexity_score:.1f} → {thinking_budget} thinking tokens for BOTH nodes",
                extra={
                    "phase": "post",
                    "complexity_score": complexity_score,
                    "thinking_budget": thinking_budget,
                },
            )
        else:
            logger.debug(
                f"RequirementsAnalysisNode: Complexity {complexity_score:.1f} → standard generation (no thinking)",
                extra={
                    "phase": "post",
                    "complexity_score": complexity_score,
                    "thinking_budget": 0,
                },
            )

        # Store requirements result with potential error embedded
        shared["requirements_result"] = exec_res

        # Check if input was too vague
        if not exec_res.get("is_clear", False):
            clarification_msg = exec_res.get(
                "clarification_needed", "Please specify what needs to be processed and what operations to perform"
            )

            # Create a PlannerError for vague input
            from pflow.planning.error_handler import ErrorCategory, PlannerError

            planner_error = PlannerError(
                category=ErrorCategory.INVALID_INPUT,
                message="Request is too vague to create a workflow",
                user_action=clarification_msg,
                technical_details="Requirements extraction failed due to insufficient clarity",
                retry_suggestion=False,
            )

            # Embed the error in the requirements result for ResultPreparationNode to extract
            exec_res["_error"] = planner_error.to_dict()
            shared["requirements_result"] = exec_res  # Update with embedded error

            logger.warning(
                f"RequirementsAnalysisNode: Input too vague - {clarification_msg}",
                extra={"phase": "post", "action": "clarification_needed"},
            )
            return "clarification_needed"

        logger.info(
            "RequirementsAnalysisNode: Requirements extracted successfully",
            extra={
                "phase": "post",
                "action": "success",
                "requirements": exec_res.get("steps", [])[:3],  # Log first 3 for debugging
            },
        )

        # Continue to component browsing
        return ""  # Empty string for default routing

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle LLM failures with safe defaults.

        Args:
            prep_res: Prepared data
            exc: Exception that occurred

        Returns:
            Safe default RequirementsSchema matching exec() return type
        """
        safe_response, planner_error = create_fallback_response("RequirementsAnalysisNode", exc, prep_res)

        # Return a valid RequirementsSchema-like dict
        return safe_response or {
            "is_clear": False,
            "clarification_needed": f"Failed to analyze requirements: {exc!s}",
            "steps": [],
            "estimated_nodes": 0,
            "required_capabilities": [],
            "complexity_indicators": {},
        }


class PlanningNode(Node):
    """Create execution plan using available components (Path B only).

    STARTS a multi-turn conversation that will be continued by WorkflowGenerator.
    Outputs markdown with parseable Status and Node Chain. Critical for the
    multi-turn conversation architecture that enables context caching.

    Interface:
    - Reads: requirements_result, browsed_components, planning_context
    - Writes: planning_result, planner_conversation (CRITICAL!)
    - Actions: "" (continue), "impossible_requirements", "partial_solution"
    """

    name = "planning"  # For registry discovery

    def __init__(self, max_retries: int = 2, wait: float = 1.0) -> None:
        """Initialize with retry support for LLM operations.

        Args:
            max_retries: Number of retries on LLM failure (default 2)
            wait: Wait time between retries in seconds (default 1.0)
        """
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare context for planning.

        Args:
            shared: PocketFlow shared store

        Returns:
            Dict with requirements, components, and model config

        Raises:
            ValueError: If critical inputs are missing
        """
        logger.debug("PlanningNode: Preparing for execution planning", extra={"phase": "prep"})

        # Get requirements from RequirementsAnalysisNode
        requirements_result = shared.get("requirements_result", {})
        if not requirements_result:
            logger.warning("PlanningNode: No requirements_result found", extra={"phase": "prep"})

        # Get browsed components from ComponentBrowsingNode
        browsed_components = shared.get("browsed_components", {})
        if not browsed_components:
            raise ValueError("Missing required 'browsed_components' in shared store")

        # Get planning context (detailed component info)
        planning_context = shared.get("planning_context", "")

        # Get the user's request (prefer templatized version)
        templatized_input = shared.get("templatized_input")
        user_input = shared.get("user_input", "")
        user_request = templatized_input or user_input

        # Get discovered parameters for context
        discovered_params = shared.get("discovered_params")

        # Configuration from params with defaults
        model_name = self.params.get("model", "anthropic/claude-sonnet-4-5")
        base_temperature = self.params.get("temperature", 0.3)  # Default for creative planning

        # Get complexity analysis from RequirementsAnalysisNode
        complexity_analysis = shared.get("complexity_analysis", {})
        thinking_budget = complexity_analysis.get("thinking_budget", 0)

        # Adjust temperature based on thinking mode
        # When thinking is enabled, temperature MUST be 1.0 (Anthropic API requirement)
        temperature = 1.0 if thinking_budget > 0 else base_temperature

        # Get cache_planner flag from shared store
        cache_planner = shared.get("cache_planner", False)

        return {
            "requirements_result": requirements_result,
            "browsed_components": browsed_components,
            "planning_context": planning_context,
            "user_request": user_request,
            "discovered_params": discovered_params,
            "model_name": model_name,
            "temperature": temperature,
            "thinking_budget": thinking_budget,
            "cache_planner": cache_planner,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Create execution plan using cache-optimized context blocks.

        Args:
            prep_res: Prepared data with requirements and components

        Returns:
            Dict with plan_markdown, status, node_chain, and context blocks
        """
        logger.debug("PlanningNode: Creating execution plan with cache-optimized context")

        # Build base blocks [A, B, C] for cache optimization
        base_blocks = PlannerContextBuilder.build_base_blocks(
            user_request=prep_res["user_request"],
            requirements_result=prep_res["requirements_result"],
            browsed_components=prep_res["browsed_components"],
            planning_context=prep_res["planning_context"],
            discovered_params=prep_res.get("discovered_params"),
        )

        # Log metrics
        total_chars = sum(len(block["text"]) for block in base_blocks)
        estimated_tokens = total_chars // 4  # Rough estimate
        logger.info(
            f"PlanningNode: Base context built - ~{estimated_tokens} tokens, {len(base_blocks)} blocks (1 static, 1 dynamic)",
            extra={"phase": "exec", "cache_blocks": len(base_blocks)},
        )

        # Load planning instructions (not cached - goes in user message)
        from pflow.planning.prompts.loader import load_prompt

        planning_instructions = load_prompt("planning_instructions")

        # Get model and generate plan with cache blocks
        model = llm.get_model(prep_res["model_name"])

        # CRITICAL: Use exact same thinking budget as WorkflowGeneratorNode for cache sharing
        thinking_budget = prep_res.get("thinking_budget", 0)
        cache_planner = prep_res.get("cache_planner", False)

        # Log thinking usage if enabled
        if thinking_budget > 0:
            logger.info(
                f"PlanningNode: Using {thinking_budget} thinking tokens for complexity analysis",
                extra={"phase": "exec", "thinking_budget": thinking_budget},
            )

        # Build prompt and kwargs for different model types
        temperature = _adjust_temperature_for_model(prep_res["model_name"], prep_res["temperature"])

        kwargs: dict[str, Any]
        if _is_anthropic_model(prep_res["model_name"]):
            # Anthropic models - use cache_blocks directly
            # Always pass blocks (even when caching disabled) - they contain the context!
            # Strip cache_control markers if caching is disabled
            final_prompt = planning_instructions
            blocks_to_use = base_blocks if cache_planner else _strip_cache_control(base_blocks)
            kwargs = {"temperature": temperature, "cache_blocks": blocks_to_use}
            if thinking_budget > 0:
                kwargs["thinking_budget"] = thinking_budget
        else:
            # Non-Anthropic models - flatten cache_blocks into prompt
            final_prompt = _flatten_cache_blocks(base_blocks, planning_instructions)
            kwargs = {"temperature": temperature, "stream": False}

        response = model.prompt(final_prompt, **kwargs)

        # Extract text from response
        plan_markdown = response.text() if hasattr(response, "text") else str(response)

        # Parse the structured ending
        parsed = self._parse_plan_assessment(plan_markdown)

        # Create extended blocks [A, B, C, D] by appending plan output
        extended_blocks = PlannerContextBuilder.append_planning_block(base_blocks, plan_markdown, parsed)

        # Log extended context metrics
        total_chars = sum(len(block["text"]) for block in extended_blocks)
        estimated_tokens = total_chars // 4  # Rough estimate
        logger.info(
            f"PlanningNode: Extended context created - ~{estimated_tokens} tokens, {len(extended_blocks)} cache blocks",
            extra={
                "phase": "exec",
                "status": parsed["status"],
                "has_node_chain": bool(parsed["node_chain"]),
                "cache_blocks": len(extended_blocks),
            },
        )

        return {
            "plan_markdown": plan_markdown,
            "status": parsed["status"],
            "node_chain": parsed["node_chain"],
            "missing_capabilities": parsed.get("missing_capabilities", []),
            "base_blocks": base_blocks,
            "extended_blocks": extended_blocks,
        }

    def _parse_plan_assessment(self, markdown: str) -> dict[str, Any]:
        """Extract Status and Node Chain from markdown output.

        Args:
            markdown: The planning markdown to parse

        Returns:
            Dict with status, node_chain, and missing_capabilities
        """
        import re

        # Default values
        status = "FEASIBLE"
        node_chain = ""
        missing_capabilities = []

        # Extract Status (FEASIBLE/PARTIAL/IMPOSSIBLE)
        if match := re.search(r"\*\*Status\*\*:\s*(\w+)", markdown, re.IGNORECASE):
            status = match.group(1).upper()

        # Extract Node Chain
        if match := re.search(r"\*\*Node Chain\*\*:\s*([^\n]+)", markdown, re.IGNORECASE):
            node_chain = match.group(1).strip()

        # Extract Missing Capabilities (if any)
        if match := re.search(r"\*\*Missing Capabilities\*\*:\s*([^\n]+)", markdown, re.IGNORECASE):
            caps = match.group(1).strip()
            if caps and caps.lower() != "none":
                missing_capabilities = [c.strip() for c in caps.split(",")]

        return {
            "status": status,
            "node_chain": node_chain,
            "missing_capabilities": missing_capabilities,
        }

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store planning results and context narrative, then route.

        Args:
            shared: PocketFlow shared store
            prep_res: Prepared data
            exec_res: Execution result with plan and context narrative

        Returns:
            Action string based on feasibility status
        """
        # Store planning result
        shared["planning_result"] = {
            "plan_markdown": exec_res["plan_markdown"],
            "status": exec_res["status"],
            "node_chain": exec_res["node_chain"],
            "missing_capabilities": exec_res.get("missing_capabilities", []),
        }

        # Store cache blocks for WorkflowGeneratorNode
        if "base_blocks" in exec_res:
            shared["planner_base_blocks"] = exec_res["base_blocks"]
        if "extended_blocks" in exec_res:
            shared["planner_extended_blocks"] = exec_res["extended_blocks"]
            logger.info(
                f"PlanningNode: Stored {len(exec_res['extended_blocks'])} cache blocks for generator",
                extra={"phase": "post", "cache_blocks": len(exec_res.get("extended_blocks", []))},
            )

        # Route based on status
        status = exec_res["status"]

        if status == "IMPOSSIBLE":
            # Create a PlannerError for impossible requirements
            from pflow.planning.error_handler import ErrorCategory, PlannerError

            missing_caps = exec_res.get("missing_capabilities", [])
            capabilities_text = ", ".join(missing_caps) if missing_caps else "required capabilities"

            planner_error = PlannerError(
                category=ErrorCategory.MISSING_RESOURCE,
                message="Cannot create workflow with available components",
                user_action=f"This workflow requires capabilities not currently available: {capabilities_text}. Consider breaking down the request into smaller parts or using different approaches.",
                technical_details=f"Missing nodes/capabilities: {capabilities_text}",
                retry_suggestion=False,
            )

            # Embed the error in the planning result for ResultPreparationNode to extract
            exec_res["_error"] = planner_error.to_dict()
            shared["planning_result"]["_error"] = planner_error.to_dict()  # Also embed in planning_result

            logger.warning(
                f"PlanningNode: Impossible requirements - missing {capabilities_text}",
                extra={"phase": "post", "action": "impossible_requirements"},
            )
            return "impossible_requirements"

        elif status == "PARTIAL":
            # Create an error for partial solution (routes to result_preparation, not continuing)
            from pflow.planning.error_handler import ErrorCategory, PlannerError

            missing_caps = exec_res.get("missing_capabilities", [])
            if missing_caps:
                capabilities_text = ", ".join(missing_caps)

                planner_error = PlannerError(
                    category=ErrorCategory.MISSING_RESOURCE,
                    message="Cannot create complete workflow - missing capabilities",
                    user_action=f"This request requires capabilities not currently available: {capabilities_text}. You can either install the missing components or modify your request to work with available tools.",
                    technical_details=f"Unavailable capabilities: {capabilities_text}",
                    retry_suggestion=False,
                )

                # Embed as error since we're aborting (routing to result_preparation)
                exec_res["_error"] = planner_error.to_dict()
                shared["planning_result"]["_error"] = planner_error.to_dict()

            logger.info(
                "PlanningNode: Partial solution - aborting with explanation",
                extra={"phase": "post", "action": "partial_solution"},
            )
            return "partial_solution"

        # FEASIBLE or default
        logger.info(
            "PlanningNode: Plan feasible, continuing to generation",
            extra={"phase": "post", "action": "continue"},
        )
        return ""  # Empty string for default routing to workflow generator

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Planning is critical - abort on LLM failure.

        Args:
            prep_res: Prepared data
            exc: Exception that occurred

        Raises:
            CriticalPlanningError: Always, as planning is critical
        """
        from pflow.core.exceptions import CriticalPlanningError
        from pflow.planning.error_handler import classify_error

        # Classify the error for better user messaging
        planner_error = classify_error(exc, context="PlanningNode")

        # Planning is critical - we cannot generate workflows without a plan
        raise CriticalPlanningError(
            node_name="PlanningNode",
            reason=f"Cannot create execution plan: {planner_error.message}. {planner_error.user_action}",
            original_error=exc,
        )


class ParameterMappingNode(Node):
    """Extract and validate parameters for workflow execution (convergence point).

    This is THE critical verification gate where both paths converge.
    Performs INDEPENDENT extraction to verify the workflow can execute with user's input.

    Interface:
    - Reads: user_input (str), stdin (optional), found_workflow or generated_workflow
    - Writes: extracted_params (dict), missing_params (list, if incomplete)
    - Actions: params_complete or params_incomplete
    """

    name = "parameter-mapping"  # For registry discovery

    def __init__(self, max_retries: int = 2, wait: float = 1.0) -> None:
        """Initialize with retry support for LLM operations.

        Args:
            max_retries: Number of retries on LLM failure (default 2)
            wait: Wait time between retries in seconds (default 1.0)
        """
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare for parameter extraction and validation.

        Args:
            shared: PocketFlow shared store

        Returns:
            Dict with user_input, workflow_ir, and stdin data

        Raises:
            ValueError: If required inputs are missing
        """
        logger.debug("ParameterMappingNode: Preparing for parameter mapping", extra={"phase": "prep"})

        # Data flow: shared store first, then params fallback
        user_input = shared.get("user_input") or self.params.get("user_input", "")
        if not user_input:
            raise ValueError("Missing required 'user_input' in shared store or params")

        # Get workflow IR from either path
        workflow_ir = None
        if shared.get("found_workflow"):  # Path A
            workflow_ir = shared["found_workflow"].get("ir")
            logger.debug("ParameterMappingNode: Using found_workflow from Path A", extra={"phase": "prep"})
        elif shared.get("generated_workflow"):  # Path B
            workflow_ir = shared["generated_workflow"]
            logger.debug("ParameterMappingNode: Using generated_workflow from Path B", extra={"phase": "prep"})

        if not workflow_ir:
            logger.warning("ParameterMappingNode: No workflow IR available", extra={"phase": "prep"})

        # Configuration from params with defaults
        model_name = self.params.get("model", "anthropic/claude-sonnet-4-5")
        temperature = self.params.get("temperature", 0.0)

        # Get stdin as fallback parameter source
        stdin_data = shared.get("stdin", "")

        # Get cache_planner flag from shared store
        cache_planner = shared.get("cache_planner", False)

        return {
            "user_input": user_input,
            "workflow_ir": workflow_ir,
            "stdin_data": stdin_data,
            "model_name": model_name,
            "temperature": temperature,
            "cache_planner": cache_planner,
        }

    def _build_parameter_description(self, param_name: str, param_spec: Any) -> str:
        """Build description string for a single parameter.

        Args:
            param_name: Name of the parameter
            param_spec: Parameter specification (string or dict)

        Returns:
            Formatted parameter description
        """
        if isinstance(param_spec, str):
            # Simple string format from LLM generation
            required = True
            param_type = "string"
            description = param_spec
            default = None
        elif isinstance(param_spec, dict):
            # Structured format with metadata
            required = param_spec.get("required", True)
            param_type = param_spec.get("type", "string")
            description = param_spec.get("description", "")
            default = param_spec.get("default")
        else:
            # Fallback for unexpected formats
            required = True
            param_type = "string"
            description = f"Input parameter: {param_name}"
            default = None

        status = "required" if required else f"optional (default: {default})"
        return f"- {param_name} ({param_type}, {status}): {description}"

    def _extract_parameters_from_llm(self, inputs_description_text: str, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Call LLM to extract parameters from user input.

        Args:
            inputs_description_text: Formatted description of inputs
            prep_res: Prepared resources with user_input, stdin_data, etc.

        Returns:
            Parsed ParameterExtraction result
        """
        from pflow.planning.utils.prompt_cache_helper import build_cached_prompt

        # Prepare stdin data - truncate if too long, use "None" if empty
        stdin_data = prep_res.get("stdin_data", "")[:500] if prep_res.get("stdin_data") else "None"

        # Check if caching is enabled for cache_control markers
        cache_planner = prep_res.get("cache_planner", False)

        # Lazy-load model at execution time (PocketFlow best practice)
        model = llm.get_model(prep_res["model_name"])

        # Prepare all variables for the prompt template
        all_vars = {
            "inputs_description": inputs_description_text,
            "user_input": prep_res["user_input"],
            "stdin_data": stdin_data,
        }

        # Build cache blocks based on cache_planner flag
        cache_blocks, formatted_prompt = build_cached_prompt(
            "parameter_mapping",
            all_variables=all_vars,
            cacheable_variables=None,  # No cacheable context for this node
            enable_caching=cache_planner,
        )

        # Build kwargs with proper cache_blocks handling for different model types
        final_prompt, kwargs = _build_llm_kwargs(
            prep_res["model_name"],
            cache_planner,
            cache_blocks,
            formatted_prompt,
            schema=ParameterExtraction,
            temperature=prep_res["temperature"],
        )

        response = model.prompt(final_prompt, **kwargs)

        return parse_structured_response(response, ParameterExtraction)

    def _apply_defaults_and_validate(
        self, result: dict[str, Any], inputs_spec: dict[str, Any]
    ) -> tuple[list[str], float]:
        """Apply default values and validate required parameters.

        Args:
            result: Extraction result from LLM
            inputs_spec: Workflow inputs specification

        Returns:
            Tuple of (missing_params_list, confidence_score)
        """
        final_missing = []

        for param_name, param_spec in inputs_spec.items():
            # Check if parameter is missing from extraction
            if param_name not in result["extracted"]:
                # Handle both string and dict formats
                if isinstance(param_spec, str):
                    # Simple string format - no defaults, always required
                    final_missing.append(param_name)
                elif isinstance(param_spec, dict):
                    # Structured format - check for defaults
                    if "default" in param_spec:
                        logger.info(
                            f"ParameterMappingNode: Using default value for {param_name}: {param_spec['default']}"
                        )
                        result["extracted"][param_name] = param_spec["default"]
                    # Only mark as missing if it's required AND has no default
                    elif param_spec.get("required", True):
                        final_missing.append(param_name)
                else:
                    # Fallback - treat as required
                    final_missing.append(param_name)

        # Calculate confidence based on missing parameters
        confidence = 0.0 if final_missing else max(result.get("confidence", 0.5), 0.5)
        return final_missing, confidence

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Extract parameters independently and validate against workflow inputs.

        Args:
            prep_res: Prepared data with user_input and workflow_ir

        Returns:
            ParameterExtraction dict with extracted, missing, confidence, reasoning
        """
        logger.debug("ParameterMappingNode: Extracting parameters for workflow execution")

        # Handle missing workflow gracefully
        if not prep_res["workflow_ir"]:
            return {
                "extracted": {},
                "missing": [],
                "confidence": 0.0,
                "reasoning": "No workflow provided for parameter mapping",
            }

        # Get workflow inputs specification
        inputs_spec = prep_res["workflow_ir"].get("inputs", {})
        if not inputs_spec:
            # No inputs required - workflow can execute without parameters
            return {
                "extracted": {},
                "missing": [],
                "confidence": 1.0,
                "reasoning": "Workflow has no input parameters defined",
            }

        # Build inputs description for LLM
        inputs_description = [
            self._build_parameter_description(param_name, param_spec) for param_name, param_spec in inputs_spec.items()
        ]
        inputs_description_text = "\n".join(inputs_description) if inputs_description else "None"

        # Extract parameters using LLM
        result = self._extract_parameters_from_llm(inputs_description_text, prep_res)

        # Validate and apply defaults
        final_missing, confidence = self._apply_defaults_and_validate(result, inputs_spec)

        # Update result with validated values
        result["missing"] = final_missing
        result["confidence"] = confidence

        logger.info(
            f"ParameterMappingNode: Extracted {len(result['extracted'])} parameters, {len(result['missing'])} missing",
            extra={
                "phase": "exec",
                "extracted_count": len(result["extracted"]),
                "missing_count": len(result["missing"]),
                "confidence": result["confidence"],
            },
        )

        return result

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store extraction results and route based on completeness and path.

        Args:
            shared: PocketFlow shared store
            prep_res: Prepared data
            exec_res: Execution result (ParameterExtraction)

        Returns:
            - "params_complete" for Path A (found workflow, skip validation)
            - "params_complete_validate" for Path B (generated workflow, needs validation)
            - "params_incomplete" if required parameters are missing (both paths)
        """
        # Store extraction results
        shared["extracted_params"] = exec_res["extracted"]

        # Determine routing based on missing parameters
        if exec_res["missing"]:
            shared["missing_params"] = exec_res["missing"]
            logger.warning(
                f"ParameterMappingNode: Missing required parameters: {exec_res['missing']}",
                extra={"phase": "post", "action": "params_incomplete", "missing": exec_res["missing"]},
            )
            return "params_incomplete"

        # VALIDATION REDESIGN FIX: Route differently based on path
        # Path B (generated workflow) needs validation with extracted params
        # Path A (found workflow) skips validation, goes directly to preparation
        if shared.get("generated_workflow"):
            logger.info(
                "ParameterMappingNode: Parameters complete for generated workflow - proceeding to validation",
                extra={
                    "phase": "post",
                    "action": "params_complete_validate",
                    "params": list(exec_res["extracted"].keys()),
                },
            )
            return "params_complete_validate"  # Path B → Validator
        else:
            logger.info(
                "ParameterMappingNode: Parameters complete for found workflow - proceeding to preparation",
                extra={"phase": "post", "action": "params_complete", "params": list(exec_res["extracted"].keys())},
            )
            return "params_complete"  # Path A → ParameterPreparation

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """ParameterMappingNode is critical - abort on LLM failure.

        Args:
            prep_res: Prepared data
            exc: Exception that occurred

        Raises:
            CriticalPlanningError: Always, as this node is critical for parameter extraction
        """
        from pflow.core.exceptions import CriticalPlanningError
        from pflow.planning.error_handler import classify_error

        # Classify the error for better user messaging
        planner_error = classify_error(exc, context="ParameterMappingNode")

        # ParameterMappingNode is critical - we cannot extract required parameters without LLM.
        # Abort the flow with a clear error message.
        raise CriticalPlanningError(
            node_name="ParameterMappingNode",
            reason=f"Cannot extract workflow parameters: {planner_error.message}. {planner_error.user_action}",
            original_error=exc,
        )


class ParameterPreparationNode(Node):
    """Format extracted parameters for workflow execution.

    Currently a pass-through in MVP, but prepares for future transformations
    like type conversion, validation, and complex mappings.

    Interface:
    - Reads: extracted_params (dict)
    - Writes: execution_params (dict)
    - Actions: Returns to result preparation
    """

    name = "parameter-preparation"  # For registry discovery

    def __init__(self) -> None:
        """Initialize parameter preparation node."""
        super().__init__()

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare extracted parameters for formatting.

        Args:
            shared: PocketFlow shared store

        Returns:
            Dict with extracted_params

        Raises:
            ValueError: If extracted_params is missing
        """
        logger.debug("ParameterPreparationNode: Preparing parameters for execution", extra={"phase": "prep"})

        extracted_params = shared.get("extracted_params")
        if extracted_params is None:
            raise ValueError("Missing required 'extracted_params' in shared store")

        return {"extracted_params": extracted_params}

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Format parameters for execution (pass-through in MVP).

        Args:
            prep_res: Prepared data with extracted_params

        Returns:
            Dict with execution_params
        """
        logger.debug("ParameterPreparationNode: Formatting parameters for execution", extra={"phase": "exec"})

        # In MVP, this is a simple pass-through
        # Future versions will handle type conversion, validation, etc.
        execution_params = prep_res["extracted_params"].copy()

        logger.info(
            f"ParameterPreparationNode: Prepared {len(execution_params)} parameters for execution",
            extra={"phase": "exec", "param_count": len(execution_params)},
        )

        return {"execution_params": execution_params}

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store execution parameters and continue to result.

        Args:
            shared: PocketFlow shared store
            prep_res: Prepared data
            exec_res: Execution result with execution_params

        Returns:
            Empty string to continue flow
        """
        # Store final execution parameters
        shared["execution_params"] = exec_res["execution_params"]

        logger.info(
            "ParameterPreparationNode: Execution parameters ready",
            extra={"phase": "post", "params": list(exec_res["execution_params"].keys())},
        )

        # Continue to result preparation
        return ""  # No action string needed for simple continuation


class WorkflowGeneratorNode(Node):
    """Generates workflows using LLM with structured output.

    Path B only: Transforms browsed components and parameter hints into
    executable workflows with template variables and proper input specifications.
    """

    name = "generator"  # Class attribute for registry discovery

    def __init__(self, max_retries: int = 3, wait: float = 1.0) -> None:
        """Initialize generator with retry configuration.

        Args:
            max_retries: Maximum number of retry attempts
            wait: Wait time between retries in seconds
        """
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare data for workflow generation.

        Args:
            shared: PocketFlow shared store

        Returns:
            Dict with all data needed for generation
        """
        # Get complexity analysis from RequirementsAnalysisNode
        complexity_analysis = shared.get("complexity_analysis", {})
        thinking_budget = complexity_analysis.get("thinking_budget", 0)

        # Adjust temperature based on thinking mode
        # When thinking is enabled, temperature MUST be 1.0 (Anthropic API requirement)
        base_temperature = self.params.get("temperature", 0.0)
        temperature = 1.0 if thinking_budget > 0 else base_temperature

        # Get cache_planner flag from shared store
        cache_planner = shared.get("cache_planner", False)

        return {
            "model_name": self.params.get("model", "anthropic/claude-sonnet-4-5"),
            "temperature": temperature,
            "planning_context": shared.get(
                "planning_context", ""
            ),  # Still used by RequirementsAnalysisNode and PlanningNode
            "user_input": shared.get("templatized_input", shared.get("user_input", "")),
            "discovered_params": shared.get("discovered_params"),
            "browsed_components": shared.get("browsed_components", {}),
            "validation_errors": shared.get("validation_errors", []),
            "runtime_errors": shared.get(
                "runtime_errors", []
            ),  # Legacy: Was used by RuntimeValidationNode (now removed)
            "generation_attempts": shared.get("generation_attempts", 0),
            "planner_extended_blocks": shared.get("planner_extended_blocks"),  # Cache blocks from PlanningNode
            "planner_accumulated_blocks": shared.get("planner_accumulated_blocks"),  # Cache blocks for retries
            "thinking_budget": thinking_budget,  # MUST be same as PlanningNode for cache sharing
            "cache_planner": cache_planner,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:  # noqa: C901
        """Generate workflow using cache-optimized context blocks.

        Args:
            prep_res: Prepared data including extended context or accumulated context

        Returns:
            Dict with generated workflow and attempt count

        Raises:
            ValueError: If no context is available or response parsing fails
        """
        logger.debug(f"Generating workflow for: {prep_res['user_input'][:100]}...")

        # Import FlowIR here to avoid circular imports
        from pflow.planning.ir_models import FlowIR
        from pflow.planning.prompts.loader import load_prompt

        # Determine if this is a retry (either validation errors or runtime errors)
        is_retry = prep_res.get("generation_attempts", 0) > 0 and (
            prep_res.get("validation_errors") or prep_res.get("runtime_errors")
        )

        # Determine which blocks to use (prefer blocks over strings)
        blocks = None

        if is_retry and prep_res.get("planner_accumulated_blocks"):
            # Use accumulated blocks from previous attempt(s)
            blocks = prep_res["planner_accumulated_blocks"]

            # Add validation errors as new block
            if prep_res.get("validation_errors"):
                blocks = PlannerContextBuilder.append_errors_block(blocks, prep_res["validation_errors"])

            # Add runtime errors as new block
            if prep_res.get("runtime_errors"):
                # Format runtime errors for the generator
                formatted_errors = []
                for error in prep_res.get("runtime_errors", []):
                    error_msg = error.get("message", "Runtime error")
                    if error.get("attempted"):
                        error_msg += f" - Attempted: {error['attempted']}"
                    if error.get("available"):
                        error_msg += f" - Available: {error['available']}"
                    formatted_errors.append(error_msg)

                blocks = PlannerContextBuilder.append_errors_block(blocks, formatted_errors)

            logger.info(
                f"WorkflowGeneratorNode: Using {len(blocks)} accumulated cache blocks for retry (attempt {prep_res['generation_attempts'] + 1})",
                extra={"phase": "exec", "is_retry": True, "cache_blocks": len(blocks)},
            )
        elif prep_res.get("planner_extended_blocks"):
            # First attempt - use extended blocks from planning [A, B, C]
            blocks = prep_res["planner_extended_blocks"]
            logger.info(
                f"WorkflowGeneratorNode: Using {len(blocks)} extended cache blocks from planning",
                extra={"phase": "exec", "is_retry": False, "cache_blocks": len(blocks)},
            )
        else:
            # No blocks available - this should not happen in normal flow
            raise ValueError(
                "WorkflowGeneratorNode requires planner_extended_blocks "
                "or planner_accumulated_blocks from PlanningNode. "
                "The workflow must go through RequirementsAnalysisNode and PlanningNode first. "
                "Direct usage of WorkflowGeneratorNode is no longer supported."
            )

        # Log metrics
        total_chars = sum(len(block["text"]) for block in blocks)
        estimated_tokens = total_chars // 4  # Rough estimate
        logger.info(
            f"WorkflowGeneratorNode: Using {len(blocks)} cache blocks, ~{estimated_tokens} tokens",
            extra={"phase": "exec", "cache_blocks": len(blocks)},
        )

        # Load appropriate instructions (not cached - goes in user message)
        if is_retry:
            generation_instructions = load_prompt("workflow_generator_retry")
        else:
            generation_instructions = load_prompt("workflow_generator_instructions")

        # Generate workflow with cache blocks
        model = llm.get_model(prep_res["model_name"])

        # CRITICAL: Use exact same thinking budget as PlanningNode for cache sharing
        thinking_budget = prep_res.get("thinking_budget", 0)
        cache_planner = prep_res.get("cache_planner", False)

        # Log thinking usage if enabled
        if thinking_budget > 0:
            logger.info(
                f"WorkflowGeneratorNode: Using {thinking_budget} thinking tokens (same as PlanningNode)",
                extra={"phase": "exec", "thinking_budget": thinking_budget},
            )

        # Build prompt and kwargs for different model types
        temperature = _adjust_temperature_for_model(prep_res["model_name"], prep_res["temperature"])

        kwargs: dict[str, Any]
        if _is_anthropic_model(prep_res["model_name"]):
            # Anthropic models - use cache_blocks directly
            # Always pass blocks (even when caching disabled) - they contain the context!
            # Strip cache_control markers if caching is disabled
            final_prompt = generation_instructions
            blocks_to_use = blocks if cache_planner else _strip_cache_control(blocks)
            kwargs = {"schema": FlowIR, "temperature": temperature, "cache_blocks": blocks_to_use}
            if thinking_budget > 0:
                kwargs["thinking_budget"] = thinking_budget
        else:
            # Non-Anthropic models - flatten cache_blocks into prompt
            final_prompt = _flatten_cache_blocks(blocks, generation_instructions)
            kwargs = {"schema": FlowIR, "temperature": temperature, "stream": False}

        response = model.prompt(final_prompt, **kwargs)

        # Parse nested Anthropic response
        # parse_structured_response handles validation and alias conversion
        workflow = parse_structured_response(response, FlowIR)

        # Post-process to add system fields that don't need LLM generation
        workflow = self._post_process_workflow(workflow)

        logger.debug(f"Generated {len(workflow.get('nodes', []))} nodes")

        return {
            "workflow": workflow,
            "attempt": prep_res["generation_attempts"] + 1,
            "blocks": blocks,  # Pass blocks for potential retry accumulation
        }

    def _post_process_workflow(self, workflow: dict) -> dict:
        """Post-process the generated workflow to fix structural issues.

        Handles:
        - Adding ir_version (always)
        - Removing unused inputs (cleanup)
        - Adding empty edges for single-node workflows

        Args:
            workflow: The LLM-generated workflow dict

        Returns:
            The workflow with system fields added and structural issues fixed
        """
        if not workflow:
            return workflow

        # Always set IR version to current version
        # This is pure boilerplate that the LLM doesn't need to generate
        # Note: Must be semantic version (X.Y.Z) per IR schema
        workflow["ir_version"] = "1.0.0"

        # Remove unused inputs to avoid unnecessary validation errors
        workflow = self._remove_unused_inputs(workflow)

        # Add empty edges for single-node workflows (they don't need edges)
        workflow = self._fix_missing_edges(workflow)

        # Note: We don't need to handle start_node here because:
        # 1. It's optional in the IR schema
        # 2. The compiler automatically uses the first node if missing
        # 3. This follows the "principle of least surprise" design

        return workflow

    def _remove_unused_inputs(self, workflow: dict) -> dict:
        """Remove declared inputs that are never used in templates.

        This prevents validation errors for inputs the LLM declared but never referenced.
        These are harmless structural issues that don't affect functionality.

        Args:
            workflow: The workflow dict

        Returns:
            The workflow with unused inputs removed
        """
        if "inputs" not in workflow:
            return workflow

        # If inputs is empty, remove it
        if not workflow["inputs"]:
            del workflow["inputs"]
            return workflow

        # Find all template variables used in the workflow
        used_vars = self._find_used_template_variables(workflow)

        # Find unused inputs
        declared_inputs = set(workflow["inputs"].keys())
        unused = declared_inputs - used_vars

        # Remove unused inputs
        if unused:
            logger.debug(f"Auto-removing unused inputs: {', '.join(sorted(unused))}")
            for input_name in unused:
                del workflow["inputs"][input_name]

            # Remove inputs key entirely if now empty
            if not workflow["inputs"]:
                del workflow["inputs"]

        return workflow

    def _find_used_template_variables(self, workflow: dict) -> set[str]:
        """Find all template variables used in the workflow.

        Args:
            workflow: The workflow dict

        Returns:
            Set of variable names used in templates
        """
        used_vars: set[str] = set()
        template_pattern = re.compile(r"\$\{([^}]+)\}")

        # Search through all node parameters
        for node in workflow.get("nodes", []):
            params = node.get("params", {})
            self._find_templates_in_value(params, template_pattern, used_vars)

        # Check workflow outputs too
        outputs = workflow.get("outputs") or {}
        for _output_name, output_spec in outputs.items():
            if isinstance(output_spec, dict):
                # Could have templates in the spec
                self._find_templates_in_value(output_spec, template_pattern, used_vars)
            elif isinstance(output_spec, str):
                # Direct string output might be a template
                matches = template_pattern.findall(output_spec)
                for match in matches:
                    # Extract base variable (before any dots)
                    base_var = match.split(".")[0]
                    used_vars.add(base_var)

        return used_vars

    def _find_templates_in_value(self, value: Any, pattern: re.Pattern, used_vars: set[str]) -> None:
        """Recursively find template variables in a value.

        Args:
            value: The value to search (could be str, dict, list, etc.)
            pattern: Compiled regex pattern for templates
            used_vars: Set to add found variables to
        """
        if isinstance(value, str):
            matches = pattern.findall(value)
            for match in matches:
                # Extract base variable (before any dots or paths)
                # This handles both ${var} and ${var.field}
                base_var = match.split(".")[0]

                # We track all base variables here.
                # Later we'll filter to only those that are declared inputs.
                # This way we don't incorrectly treat node IDs as inputs.
                used_vars.add(base_var)
        elif isinstance(value, dict):
            for v in value.values():
                self._find_templates_in_value(v, pattern, used_vars)
        elif isinstance(value, list):
            for item in value:
                self._find_templates_in_value(item, pattern, used_vars)

    def _fix_missing_edges(self, workflow: dict) -> dict:
        """Add empty edges array for single-node workflows.

        Single-node workflows don't need edges, but validation requires the key.
        Only auto-fix for single nodes - multi-node workflows without edges are likely errors.

        Args:
            workflow: The workflow dict

        Returns:
            The workflow with edges added if appropriate
        """
        # Only auto-fix if there's exactly one node
        nodes = workflow.get("nodes", [])
        if len(nodes) == 1 and "edges" not in workflow:
            logger.debug("Auto-adding empty edges array for single-node workflow")
            workflow["edges"] = []

        return workflow

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store generated workflow and accumulate context for potential retry.

        Args:
            shared: PocketFlow shared store
            prep_res: Prepared data
            exec_res: Execution result with workflow

        Returns:
            Action string "validate" to route to ValidatorNode
        """
        logger.debug(f"Generated {len(exec_res['workflow'].get('nodes', []))} nodes")

        # Store generated workflow for validation
        shared["generated_workflow"] = exec_res["workflow"]
        shared["generation_attempts"] = exec_res["attempt"]

        # CRITICAL: Accumulate context for potential retry
        if exec_res.get("blocks") and exec_res.get("workflow"):
            # Accumulate cache blocks [A, B, C, D, E]
            accumulated_blocks = PlannerContextBuilder.append_workflow_block(
                exec_res["blocks"], exec_res["workflow"], exec_res["attempt"]
            )
            shared["planner_accumulated_blocks"] = accumulated_blocks

            # Log accumulated block metrics
            total_chars = sum(len(block["text"]) for block in accumulated_blocks)
            estimated_tokens = total_chars // 4  # Rough estimate
            logger.info(
                f"WorkflowGeneratorNode: Accumulated {len(accumulated_blocks)} cache blocks for retry - ~{estimated_tokens} tokens",
                extra={
                    "phase": "post",
                    "attempt": exec_res["attempt"],
                    "cache_blocks": len(accumulated_blocks),
                },
            )

        # CRITICAL: Always route to validation
        return "validate"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """WorkflowGeneratorNode is critical - abort on LLM failure.

        Args:
            prep_res: Prepared data that caused the failure
            exc: Exception that occurred

        Raises:
            CriticalPlanningError: Always, as this node is critical for workflow generation
        """
        from pflow.core.exceptions import CriticalPlanningError
        from pflow.planning.error_handler import classify_error

        # Classify the error for better user messaging
        planner_error = classify_error(exc, context="WorkflowGeneratorNode")

        # WorkflowGeneratorNode is critical - we cannot create workflows without LLM.
        # Abort the flow with a clear error message.
        raise CriticalPlanningError(
            node_name="WorkflowGeneratorNode",
            reason=f"Cannot generate workflow: {planner_error.message}. {planner_error.user_action}",
            original_error=exc,
        )


class ValidatorNode(Node):
    """Orchestrates validation checks for generated workflows.

    Path B only: Validates structure, templates, and node types.
    Routes to retry (< 3 attempts), metadata_generation (valid), or failed (>= 3 attempts).
    """

    def __init__(self, wait: int = 0) -> None:
        """Initialize validator with direct registry instantiation."""
        super().__init__(wait=wait)
        self.registry = Registry()  # Direct instantiation per PocketFlow pattern

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Extract workflow, attempt count, and extracted params from shared store.

        Args:
            shared: PocketFlow shared store

        Returns:
            Dict with workflow, generation_attempts, and extracted_params
        """
        return {
            "workflow": shared.get("generated_workflow"),
            "generation_attempts": shared.get("generation_attempts", 0),
            "extracted_params": shared.get("extracted_params", {}),  # VALIDATION REDESIGN FIX
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Orchestrate validation checks using WorkflowValidator.

        Uses the unified WorkflowValidator which performs:
        1. Structural validation (IR schema compliance)
        2. Data flow validation (execution order and dependencies)
        3. Template validation (variable resolution)
        4. Node type validation (registry verification)

        Args:
            prep_res: Contains workflow and extracted_params

        Returns:
            Dict with errors list (empty if valid)
        """
        from pflow.core.workflow_validator import WorkflowValidator

        workflow = prep_res.get("workflow")
        if not workflow:
            logger.error("No workflow provided for validation")
            return {"errors": ["No workflow provided for validation"]}

        # Use unified WorkflowValidator for all validation
        errors, warnings = WorkflowValidator.validate(
            workflow,
            extracted_params=prep_res.get("extracted_params", {}),
            registry=self.registry,
            skip_node_types=False,  # Always validate node types in production
        )
        # Currently ignoring warnings - could be enhanced to include in error messages

        # Return top 3 most actionable errors
        if errors:
            logger.info(f"Validation found {len(errors)} total errors, returning top 3")
        else:
            logger.info("All validation checks passed")

        return {"errors": errors[:3]}  # Limit to top 3 for LLM retry

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Route based on validation results and retry count.

        Args:
            shared: PocketFlow shared store
            prep_res: Prepared data with generation_attempts
            exec_res: Execution result with errors list

        Returns:
            Action string: "retry", "metadata_generation", or "failed"
        """
        errors = exec_res.get("errors", [])
        attempts = prep_res.get("generation_attempts", 0)

        if not errors:
            # All validations passed
            logger.info("Workflow validated successfully, proceeding to metadata generation")
            shared["workflow_metadata"] = {}  # Prepare for metadata node
            shared.pop("validation_errors", None)  # Clear any previous validation errors
            return "metadata_generation"

        # Check retry limit
        if attempts >= 3:
            logger.warning(f"Validation failed after {attempts} attempts, giving up")
            shared["validation_errors"] = errors  # Store for result preparation
            return "failed"

        # Store errors for retry
        logger.info(f"Validation failed on attempt {attempts}, retrying with errors")
        shared["validation_errors"] = errors
        return "retry"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Fallback for unexpected validation failures.

        Args:
            prep_res: Prepared data
            exc: The exception that triggered the fallback

        Returns:
            Dict with critical error
        """
        logger.error(f"ValidatorNode exec_fallback triggered: {exc}")
        return {"errors": ["Critical validation failure - unable to validate workflow"]}


class MetadataGenerationNode(Node):
    """Generates high-quality metadata using LLM analysis.

    Path B only: Creates searchable metadata that enables Path A reuse.
    Critical for workflow discoverability and the two-path architecture.
    """

    def __init__(self, wait: int = 0) -> None:
        """Initialize metadata generator."""
        super().__init__(wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Gather data needed for LLM metadata generation.

        Args:
            shared: PocketFlow shared store

        Returns:
            Dict with workflow, user_input, and LLM config
        """
        # Get cache_planner flag from shared store
        cache_planner = shared.get("cache_planner", False)

        return {
            "workflow": shared.get("generated_workflow", {}),
            "user_input": shared.get("user_input", ""),
            "templatized_input": shared.get(
                "templatized_input", shared.get("user_input", "")
            ),  # Use pre-computed templatized input
            "planning_context": shared.get("planning_context", ""),
            "discovered_params": shared.get("discovered_params", {}),
            "extracted_params": shared.get("extracted_params", {}),  # Add extracted params from ParameterMappingNode
            "model_name": self.params.get("model", "anthropic/claude-sonnet-4-5"),
            "temperature": self.params.get("temperature", 0.3),  # Lower for consistency
            "cache_planner": cache_planner,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Use LLM to generate high-quality searchable metadata.

        Args:
            prep_res: Contains workflow and context for analysis

        Returns:
            Dict with rich metadata fields for discovery
        """
        workflow = prep_res.get("workflow", {})
        extracted_params = prep_res.get("extracted_params", {})

        # Log entry and workflow details
        logger.info(
            "MetadataGenerationNode: Starting exec with workflow containing %d nodes",
            len(workflow.get("nodes", [])),
            extra={
                "phase": "exec_start",
                "has_workflow": bool(workflow),
                "has_extracted_params": bool(extracted_params),
                "cache_planner": prep_res.get("cache_planner", False),
                "model_name": prep_res.get("model_name", "unknown"),
            },
        )

        # 1. Get LLM model
        model = self._get_llm_model(prep_res["model_name"])

        # 2. Build workflow description
        node_flow, workflow_stages = self._build_workflow_description(workflow)

        # 3. Prepare prompt variables and build cache blocks
        cache_blocks, formatted_prompt = self._prepare_prompt_variables(prep_res, workflow, node_flow, workflow_stages)

        # 4. Call LLM for metadata
        response = self._call_llm_for_metadata(model, formatted_prompt, cache_blocks, prep_res)

        # 5. Parse response and prepare result
        return self._prepare_metadata_result(response, workflow)

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store metadata and continue flow.

        Args:
            shared: PocketFlow shared store
            prep_res: Prepared data
            exec_res: Execution result with metadata

        Returns:
            Empty string to continue flow
        """
        # Store metadata exactly as produced by exec()
        shared["workflow_metadata"] = exec_res
        logger.info("Metadata extracted: %s", exec_res.get("suggested_name"))

        # Return empty string to continue flow to ParameterMappingNode
        return ""

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Fallback with basic metadata using simple extraction and error classification.

        Args:
            prep_res: Prepared data
            exc: The exception that triggered the fallback

        Returns:
            Dict with basic metadata
        """
        # Log the fallback trigger with detailed error information
        logger.warning(
            "MetadataGenerationNode: Falling back to static metadata due to error: %s",
            str(exc),
            extra={
                "phase": "exec_fallback",
                "error": str(exc),
                "error_type": type(exc).__name__,
                "has_workflow": bool(prep_res.get("workflow")),
                "cache_planner": prep_res.get("cache_planner", False),
                "model_name": prep_res.get("model_name", "unknown"),
            },
            exc_info=True,  # Include full traceback
        )

        safe_response, planner_error = create_fallback_response("MetadataGenerationNode", exc, prep_res)

        # Log what fallback metadata is being generated
        logger.info(
            "MetadataGenerationNode: Generated fallback metadata - name='%s'",
            safe_response.get("suggested_name", "unknown"),
            extra={
                "phase": "fallback_complete",
                "metadata_name": safe_response.get("suggested_name"),
                "has_keywords": bool(safe_response.get("search_keywords")),
                "has_capabilities": bool(safe_response.get("capabilities")),
                "error_category": planner_error.category.value if planner_error else "unknown",
            },
        )

        # Note: We cannot store the error in shared store from exec_fallback
        # as shared store is not accessible here in PocketFlow architecture.
        # The error is embedded in the response for later processing.

        return safe_response

    def _get_llm_model(self, model_name: str) -> Any:
        """Retrieve the LLM model instance.

        Args:
            model_name: Name of the model to retrieve

        Returns:
            LLM model instance

        Raises:
            Exception: If model retrieval fails
        """
        try:
            model = llm.get_model(model_name)
            logger.debug("MetadataGenerationNode: Successfully retrieved model %s", model_name)
            return model
        except Exception as e:
            logger.exception(
                "MetadataGenerationNode: Failed to get model %s",
                model_name,
                extra={"phase": "model_init", "error": str(e)},
            )
            raise

    def _build_workflow_description(self, workflow: dict[str, Any]) -> tuple[str, str]:
        """Build node flow and workflow stages descriptions.

        Args:
            workflow: Workflow dictionary

        Returns:
            Tuple of (node_flow, workflow_stages)
        """
        # Build node flow
        try:
            node_flow = _build_node_flow(workflow)
            if not node_flow:
                node_flow = "empty workflow"
            logger.debug("MetadataGenerationNode: Built node flow: %s", node_flow[:100])
        except Exception as e:
            logger.exception(
                "MetadataGenerationNode: Failed to build node flow",
                extra={"phase": "node_flow", "error": str(e)},
            )
            node_flow = "empty workflow"

        # Build workflow stages
        try:
            workflow_stages = self._build_workflow_stages(workflow)
            if not workflow_stages:
                workflow_stages = "No stages defined"
            logger.debug("MetadataGenerationNode: Built workflow stages")
        except Exception as e:
            logger.exception(
                "MetadataGenerationNode: Failed to build workflow stages",
                extra={"phase": "workflow_stages", "error": str(e)},
            )
            workflow_stages = "No stages defined"

        return node_flow, workflow_stages

    def _prepare_prompt_variables(
        self, prep_res: dict[str, Any], workflow: dict[str, Any], node_flow: str, workflow_stages: str
    ) -> tuple[list[dict] | None, str]:
        """Prepare variables for the prompt template and build cache blocks.

        Args:
            prep_res: Prepared data from prep()
            workflow: Workflow dictionary
            node_flow: Node flow description
            workflow_stages: Workflow stages description

        Returns:
            Tuple of (cache_blocks, formatted_prompt)

        Raises:
            Exception: If prompt building fails
        """
        import json

        from pflow.planning.utils.prompt_cache_helper import build_cached_prompt

        # Format workflow inputs
        workflow_inputs = json.dumps(workflow.get("inputs", {}), indent=2)

        # Use templatized input if available
        user_input = prep_res.get("templatized_input", prep_res.get("user_input", ""))

        # Prepare all variables for the prompt template
        all_vars = {
            "user_input": user_input,
            "node_flow": node_flow,
            "workflow_stages": workflow_stages,
            "workflow_inputs": workflow_inputs,
            "parameter_bindings": json.dumps(prep_res.get("extracted_params", {}) or {}, indent=2),
        }

        # Build cache blocks based on cache_planner flag
        try:
            cache_blocks, formatted_prompt = build_cached_prompt(
                "metadata_generation",
                all_variables=all_vars,
                cacheable_variables=None,  # No cacheable context for this node
                enable_caching=prep_res.get("cache_planner", False),
            )
            logger.debug(
                "MetadataGenerationNode: Built prompt structure, %d blocks, prompt length %d",
                len(cache_blocks) if cache_blocks else 0,
                len(formatted_prompt),
            )
            return cache_blocks, formatted_prompt
        except Exception as e:
            logger.exception(
                "MetadataGenerationNode: Failed to build prompt",
                extra={"phase": "build_prompt", "error": str(e)},
            )
            raise

    def _call_llm_for_metadata(
        self,
        model: Any,
        formatted_prompt: str,
        cache_blocks: list[dict] | None,
        prep_res: dict[str, Any],
    ) -> Any:
        """Call LLM with model-specific configuration.

        Args:
            model: LLM model instance
            formatted_prompt: Formatted prompt string
            cache_blocks: Optional cache blocks for Anthropic models
            prep_res: Prepared data with model config

        Returns:
            LLM response

        Raises:
            Exception: If LLM call fails
        """
        from pflow.planning.ir_models import WorkflowMetadata

        logger.info("MetadataGenerationNode: Making LLM call")
        try:
            # Adjust temperature for model compatibility
            temperature = _adjust_temperature_for_model(prep_res["model_name"], prep_res["temperature"])

            # Build kwargs and prompt for different model types
            if _is_anthropic_model(prep_res["model_name"]):
                # Anthropic models
                final_prompt = formatted_prompt
                llm_kwargs: dict[str, Any] = {
                    "schema": WorkflowMetadata,
                    "temperature": temperature,
                }
                # Only add cache_blocks if caching is enabled
                if prep_res.get("cache_planner", False) and cache_blocks:
                    llm_kwargs["cache_blocks"] = cache_blocks
            else:
                # Non-Anthropic models - flatten cache_blocks into prompt
                final_prompt = (
                    _flatten_cache_blocks(cache_blocks, formatted_prompt) if cache_blocks else formatted_prompt
                )
                llm_kwargs = {
                    "schema": WorkflowMetadata,
                    "temperature": temperature,
                    "stream": False,
                }

            # Make LLM call
            response = model.prompt(final_prompt, **llm_kwargs)
            logger.debug("MetadataGenerationNode: LLM call successful")
            return response
        except Exception as e:
            logger.exception(
                "MetadataGenerationNode: LLM call failed",
                extra={"phase": "llm_call", "error": str(e), "error_type": type(e).__name__},
            )
            raise

    def _prepare_metadata_result(self, response: Any, workflow: dict[str, Any]) -> dict[str, Any]:
        """Parse LLM response and prepare final metadata result.

        Args:
            response: LLM response
            workflow: Workflow dictionary

        Returns:
            Dictionary with metadata fields

        Raises:
            Exception: If parsing fails
        """
        from pflow.planning.ir_models import WorkflowMetadata
        from pflow.planning.utils.llm_helpers import parse_structured_response

        # Parse the structured response
        try:
            metadata = parse_structured_response(response, WorkflowMetadata)
            logger.debug("MetadataGenerationNode: Successfully parsed structured response")
        except Exception as e:
            logger.exception(
                "MetadataGenerationNode: Failed to parse structured response",
                extra={"phase": "parse_response", "error": str(e)},
            )
            raise

        # Convert to plain dict for uniform downstream handling
        metadata_dict = metadata.model_dump() if hasattr(metadata, "model_dump") else dict(metadata)

        logger.debug(
            "Generated rich metadata: name=%s, keywords=%s",
            metadata_dict.get("suggested_name"),
            len(metadata_dict.get("search_keywords", [])),
        )

        # Return comprehensive metadata (keep keys as produced by schema/tests)
        result = {
            "suggested_name": metadata_dict.get("suggested_name"),
            "description": metadata_dict.get("description"),
            "search_keywords": metadata_dict.get("search_keywords", []),
            "capabilities": metadata_dict.get("capabilities", []),
            "typical_use_cases": metadata_dict.get("typical_use_cases", []),
            "declared_inputs": list(workflow.get("inputs", {}).keys()),
            "declared_outputs": self._extract_outputs(workflow),
        }

        # Log successful completion
        logger.info(
            "MetadataGenerationNode: Successfully generated metadata - name='%s', keywords=%d, capabilities=%d",
            result.get("suggested_name"),
            len(result.get("search_keywords", [])),
            len(result.get("capabilities", [])),
            extra={
                "phase": "exec_complete",
                "success": True,
                "metadata_name": result.get("suggested_name"),
                "keyword_count": len(result.get("search_keywords", [])),
                "capability_count": len(result.get("capabilities", [])),
            },
        )

        return result

    def _summarize_nodes(self, nodes: list) -> str:
        """Summarize the types of nodes used in the workflow.

        Args:
            nodes: List of nodes in the workflow

        Returns:
            Comma-separated list of unique node types
        """
        node_types = [node.get("type", "unknown") for node in nodes]
        unique_types = list(dict.fromkeys(node_types))  # Preserve order, remove duplicates
        return ", ".join(unique_types[:5]) if unique_types else "none"  # Limit to first 5 for brevity

    def _extract_outputs(self, workflow: dict[str, Any]) -> list[str]:
        """Extract output keys from workflow.

        Simple approach: Look for outputs field or common output patterns.

        Args:
            workflow: Workflow IR

        Returns:
            List of output keys
        """
        # Check if workflow has explicit outputs field
        if "outputs" in workflow:
            return list(workflow["outputs"].keys())

        # Otherwise, return empty list (can be enhanced later)
        return []

    def _extract_templates_from_params(self, params: dict[str, Any]) -> set[str]:
        """Recursively extract all template variables from node parameters.

        Args:
            params: Node parameters dictionary (can have nested dicts)

        Returns:
            Set of all template variable names found
        """
        from pflow.runtime.template_resolver import TemplateResolver

        templates = set()

        def _scan_value(value: Any) -> None:
            if isinstance(value, str):
                # Extract templates from string
                templates.update(TemplateResolver.extract_variables(value))
            elif isinstance(value, dict):
                # Recursively scan dictionary
                for v in value.values():
                    _scan_value(v)
            elif isinstance(value, list):
                # Recursively scan list
                for item in value:
                    _scan_value(item)

        _scan_value(params)
        return templates

    def _build_parameter_usage_map(self, workflow: dict) -> dict[str, list[str]]:
        """Build a map of which parameters are used by which nodes.

        Returns:
            Dict mapping parameter names to list of node types that use them
        """
        param_usage: dict[str, list[str]] = {}

        for node in workflow.get("nodes", []):
            node_type = node.get("type", "unknown")
            params = node.get("params", {})

            # Extract all templates from this node's params
            templates = self._extract_templates_from_params(params)

            for template in templates:
                # Extract base variable name (before any dots)
                base_var = template.split(".")[0]

                # Skip if this is a node output reference (contains dot and starts with node id)
                if "." in template:
                    # Check if it's a node output reference
                    possible_node_id = base_var
                    is_node_ref = any(n.get("id") == possible_node_id for n in workflow.get("nodes", []))
                    if is_node_ref:
                        continue

                if base_var not in param_usage:
                    param_usage[base_var] = []
                if node_type not in param_usage[base_var]:
                    param_usage[base_var].append(node_type)

        return param_usage

    def _format_workflow_inputs(self, inputs: dict) -> str:
        """Format workflow inputs with full details.

        Args:
            inputs: Workflow inputs dictionary

        Returns:
            Formatted string with input details
        """
        if not inputs:
            return "none"

        lines = []
        for name, spec in inputs.items():
            input_type = spec.get("type", "string")
            required = spec.get("required", True)
            default = spec.get("default")
            description = spec.get("description", "")

            req_text = "required" if required else "optional"
            default_text = f", default={default}" if default is not None else ""

            lines.append(f"• {name} [{input_type}, {req_text}{default_text}]")
            if description:
                lines.append(f"  {description}")
            lines.append("")  # Empty line for spacing

        return "\n".join(lines).strip()

    def _build_workflow_stages(self, workflow: dict) -> str:
        """Build workflow stages with purposes.

        Args:
            workflow: Workflow IR

        Returns:
            Formatted string with workflow stages and purposes
        """
        nodes = workflow.get("nodes", [])
        if not nodes:
            return "No stages defined"

        lines = []
        for i, node in enumerate(nodes, 1):
            node_type = node.get("type", "unknown")
            purpose = node.get("purpose", "No purpose specified")
            lines.append(f"{i}. {node_type}: {purpose}")

        return "\n".join(lines)

    def _format_parameter_bindings(self, param_usage: dict[str, list[str]]) -> str:
        """Format parameter bindings for display.

        Args:
            param_usage: Dict mapping parameters to node types

        Returns:
            Formatted string with parameter bindings
        """
        if not param_usage:
            return "No parameter bindings"

        lines = []
        for param, nodes in sorted(param_usage.items()):
            nodes_str = ", ".join(nodes)
            lines.append(f"• {param} → {nodes_str}")

        return "\n".join(lines)


class ResultPreparationNode(Node):
    """Final node that packages the planner output for CLI consumption.

    This node has THREE entry points:
    1. From ParameterPreparationNode ("") - Success path (both Path A & B)
    2. From ParameterMappingNode ("params_incomplete") - Missing parameters
    3. From ValidatorNode ("failed") - Generation failed after 3 attempts

    It determines success/failure and packages all data into a structured
    output that the CLI can use for execution or error reporting.
    """

    def __init__(self) -> None:
        """Initialize the result preparation node."""
        super().__init__()
        self.name = "result-preparation"

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Gather all potential inputs from shared store.

        Args:
            shared: The shared store containing workflow data and state

        Returns:
            Dictionary with all relevant data for result preparation
        """
        # Core workflow data - check both Path A and Path B sources
        workflow_ir = None
        if shared.get("found_workflow"):
            # Path A: Use the found workflow's IR
            workflow_ir = shared["found_workflow"].get("ir")
        elif shared.get("generated_workflow"):
            # Path B: Use the generated workflow
            workflow_ir = shared["generated_workflow"]

        return {
            "workflow_ir": workflow_ir,
            "execution_params": shared.get("execution_params"),
            "missing_params": shared.get("missing_params", []),
            "validation_errors": shared.get("validation_errors", []),
            "runtime_errors": shared.get("runtime_errors", []),
            "generation_attempts": shared.get("generation_attempts", 0),
            "workflow_metadata": shared.get("workflow_metadata", {}),
            "discovery_result": shared.get("discovery_result"),
            "planner_error": self._extract_planner_error(shared),
        }

    def _extract_planner_error(self, shared: dict[str, Any]) -> dict[str, Any] | None:
        """Extract error details from any node responses that contain them.

        Args:
            shared: The shared store

        Returns:
            Error details dict if found, None otherwise
        """
        # Check various sources for error information
        # These are embedded in the responses when exec_fallback is called

        # First check for directly stored error (from ParameterDiscoveryNode)
        if "_discovered_params_error" in shared:
            error = shared["_discovered_params_error"]
            if isinstance(error, dict):
                return error

        # List of keys to check in the shared store for error information
        error_sources = [
            "discovery_result",
            "browsed_components",
            "requirements_result",  # Added for RequirementsAnalysisNode
            "planning_result",  # Added for PlanningNode
            "generated_workflow",
            "discovered_params",
            "extracted_params",
            "workflow_metadata",
        ]

        for source_key in error_sources:
            source_data = shared.get(source_key, {})
            if isinstance(source_data, dict) and "_error" in source_data:
                error = source_data["_error"]
                if isinstance(error, dict):
                    return error

        return None

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Determine success/failure and package the output.

        Args:
            prep_res: Data gathered from prep()

        Returns:
            Structured output for the planner
        """
        # Determine success criteria
        success = bool(
            prep_res["workflow_ir"]
            and prep_res["execution_params"] is not None
            and not prep_res["missing_params"]
            and not prep_res["validation_errors"]
            and not prep_res.get("runtime_errors")
        )

        # Build error message if not successful
        error = None
        if not success:
            # Build generic error message
            error_parts = []

            if not prep_res["workflow_ir"]:
                if prep_res["generation_attempts"] >= 3:
                    error_parts.append(f"Workflow generation failed after {prep_res['generation_attempts']} attempts")
                else:
                    error_parts.append("No workflow found or generated")

            if prep_res["missing_params"]:
                params_str = ", ".join(prep_res["missing_params"])
                error_parts.append(f"Missing required parameters: {params_str}")

            if prep_res["validation_errors"]:
                errors_str = "; ".join(prep_res["validation_errors"][:3])  # Top 3 errors
                error_parts.append(f"Validation errors: {errors_str}")

            if prep_res.get("runtime_errors"):
                runtime_errors_str = "; ".join([
                    e.get("message", "Runtime error") for e in prep_res["runtime_errors"][:3]
                ])
                error_parts.append(f"Runtime errors: {runtime_errors_str}")

            error = ". ".join(error_parts) if error_parts else "Unknown error occurred"

        # Package the output
        planner_output = {
            "success": success,
            "workflow_ir": prep_res["workflow_ir"] if success else None,
            "execution_params": prep_res["execution_params"] if success else None,
            "missing_params": prep_res["missing_params"] if prep_res["missing_params"] else None,
            "error": error,
            "workflow_metadata": prep_res["workflow_metadata"] if prep_res["workflow_metadata"] else None,
            "workflow_source": prep_res.get("discovery_result"),  # Pass through discovery result
            "error_details": prep_res.get("planner_error"),  # Include structured error details
        }

        return planner_output

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> None:
        """Store the planner output and return None to end the flow.

        Args:
            shared: The shared store
            prep_res: Data from prep()
            exec_res: The planner output from exec()

        Returns:
            None to terminate the flow (standard PocketFlow pattern for final nodes)
        """
        # Store the final output in shared store for CLI consumption
        shared["planner_output"] = exec_res

        # Log the outcome for debugging
        if exec_res["success"]:
            logger.info("Planner completed successfully")
            # Use workflow_source from exec_res for consistency
            workflow_source = exec_res.get("workflow_source")
            if workflow_source and workflow_source.get("found"):
                logger.info(f"Reused existing workflow: {workflow_source.get('workflow_name')}")
            else:
                logger.info("Generated new workflow")
        else:
            logger.warning(f"Planner failed: {exec_res['error']}")

        # Return None to terminate the flow
        return None
