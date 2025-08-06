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
from typing import Any, Optional

import llm
from pydantic import BaseModel, Field

from pflow.core.exceptions import WorkflowNotFoundError
from pflow.core.workflow_manager import WorkflowManager
from pflow.planning.context_builder import build_discovery_context, build_planning_context
from pflow.registry import Registry
from pocketflow import Node

logger = logging.getLogger(__name__)


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
        model_name = self.params.get("model", "anthropic/claude-sonnet-4-0")
        temperature = self.params.get("temperature", 0.0)

        # Load discovery context with all nodes and workflows
        try:
            discovery_context = build_discovery_context(
                node_ids=None,  # All nodes
                workflow_names=None,  # All workflows
                registry_metadata=None,  # Will load from default registry
            )
        except Exception as e:
            logger.exception("Failed to build discovery context", extra={"phase": "prep", "error": str(e)})
            raise ValueError(f"Context preparation failed: {e}") from e

        return {
            "user_input": user_input,
            "discovery_context": discovery_context,
            "model_name": model_name,
            "temperature": temperature,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute semantic matching against existing workflows.

        Args:
            prep_res: Prepared data with user_input and discovery_context

        Returns:
            WorkflowDecision dict with found, workflow_name, confidence, reasoning
        """
        logger.debug(f"WorkflowDiscoveryNode: Matching request: {prep_res['user_input'][:100]}...")

        prompt = f"""You are a workflow discovery system that determines if an existing workflow completely satisfies a user request.

Available workflows and nodes:
{prep_res["discovery_context"]}

User request: {prep_res["user_input"]}

Analyze whether any existing workflow COMPLETELY satisfies this request. A complete match means the workflow does everything the user wants without modification.

Return found=true ONLY if:
1. An existing workflow handles ALL aspects of the request
2. No additional nodes or modifications would be needed
3. The workflow's purpose directly aligns with the user's intent

If any part of the request isn't covered, return found=false to trigger workflow generation.

Be strict - partial matches should return found=false."""

        # Lazy-load model at execution time (PocketFlow best practice)
        model = llm.get_model(prep_res["model_name"])
        response = model.prompt(prompt, schema=WorkflowDecision, temperature=prep_res["temperature"])
        result = self._parse_structured_response(response, WorkflowDecision)

        logger.info(
            f"WorkflowDiscoveryNode: Decision - found={result['found']}, "
            f"workflow={result.get('workflow_name')}, confidence={result['confidence']}",
            extra={"phase": "exec", "found": result["found"], "confidence": result["confidence"]},
        )

        return result

    def _parse_structured_response(self, response: Any, expected_type: type) -> dict[str, Any]:
        """Parse structured LLM response with Anthropic's nested format.

        Args:
            response: LLM response object
            expected_type: Expected Pydantic model type for validation

        Returns:
            Parsed response as dict

        Raises:
            ValueError: If response cannot be parsed
        """
        try:
            response_data = response.json()
            if response_data is None:
                raise ValueError("LLM returned None response")

            # CRITICAL: Structured data is nested in content[0]['input'] for Anthropic
            content = response_data.get("content")
            if not content or not isinstance(content, list) or len(content) == 0:
                raise ValueError("Invalid LLM response structure")

            return dict(content[0]["input"])
        except Exception as e:
            raise ValueError(f"Failed to parse {expected_type.__name__} from LLM response: {e}") from e

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
            workflow_manager = WorkflowManager()
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
        """Handle LLM failures gracefully.

        Args:
            prep_res: Prepared data
            exc: Exception that occurred

        Returns:
            Safe default WorkflowDecision matching exec() return type
        """
        logger.error(
            f"WorkflowDiscoveryNode: Discovery failed after retries - {exc}",
            extra={"phase": "fallback", "error": str(exc), "user_input": prep_res.get("user_input", "")[:100]},
        )

        # Provide specific error messages for common failure modes
        error_str = str(exc).lower()
        if "api key" in error_str or "unauthorized" in error_str:
            reasoning = f"LLM API authentication failed: {exc!s}"
        elif "rate limit" in error_str:
            reasoning = f"LLM rate limit exceeded, please retry later: {exc!s}"
        elif "timeout" in error_str:
            reasoning = f"LLM request timed out: {exc!s}"
        else:
            reasoning = f"Discovery failed due to error: {exc!s}"

        # Return same structure as successful exec() for consistency
        return {
            "found": False,
            "workflow_name": None,
            "confidence": 0.0,
            "reasoning": reasoning,
        }


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
        model_name = self.params.get("model", "anthropic/claude-sonnet-4-0")
        temperature = self.params.get("temperature", 0.0)

        # Instantiate Registry directly (PocketFlow pattern)
        try:
            registry = Registry()
            registry_metadata = registry.load()
            if not registry_metadata:
                logger.warning("Registry returned empty metadata, using empty dict", extra={"phase": "prep"})
                registry_metadata = {}
        except Exception as e:
            logger.exception("Failed to load registry", extra={"phase": "prep", "error": str(e)})
            # Continue with empty registry rather than failing
            registry_metadata = {}

        # Get discovery context for browsing
        try:
            discovery_context = build_discovery_context(
                node_ids=None, workflow_names=None, registry_metadata=registry_metadata
            )
        except Exception as e:
            logger.exception("Failed to build discovery context", extra={"phase": "prep", "error": str(e)})
            raise ValueError(f"Context preparation failed: {e}") from e

        return {
            "user_input": user_input,
            "discovery_context": discovery_context,
            "registry_metadata": registry_metadata,
            "model_name": model_name,
            "temperature": temperature,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Select components with over-inclusive approach.

        Args:
            prep_res: Prepared data with user_input, discovery_context, registry_metadata

        Returns:
            ComponentSelection dict with node_ids, workflow_names, reasoning
        """
        logger.debug(f"ComponentBrowsingNode: Browsing components for: {prep_res['user_input'][:100]}...")

        # S608: False positive - this is an LLM prompt, not SQL
        prompt = f"""You are a component browsing system that selects building blocks for workflow generation.

Available components:
{prep_res["discovery_context"]}

User request: {prep_res["user_input"]}

Select ALL nodes and workflows that could potentially help build this request.

BE OVER-INCLUSIVE:
- Include anything that might be useful (even 20% relevance)
- Include supporting nodes (logging, error handling, etc.)
- Include workflows that could be used as building blocks
- Better to include too many than miss critical components

The generator will decide what to actually use from your selection.

Return lists of node IDs and workflow names that could be helpful."""  # noqa: S608

        # Lazy-load model at execution time (PocketFlow best practice)
        model = llm.get_model(prep_res["model_name"])
        response = model.prompt(prompt, schema=ComponentSelection, temperature=prep_res["temperature"])
        result = self._parse_structured_response(response, ComponentSelection)

        logger.info(
            f"ComponentBrowsingNode: Selected {len(result['node_ids'])} nodes, "
            f"{len(result['workflow_names'])} workflows",
            extra={
                "phase": "exec",
                "node_count": len(result["node_ids"]),
                "workflow_count": len(result["workflow_names"]),
            },
        )

        return result

    def _parse_structured_response(self, response: Any, expected_type: type) -> dict[str, Any]:
        """Parse structured LLM response with Anthropic's nested format.

        Args:
            response: LLM response object
            expected_type: Expected Pydantic model type for validation

        Returns:
            Parsed response as dict

        Raises:
            ValueError: If response cannot be parsed
        """
        try:
            response_data = response.json()
            if response_data is None:
                raise ValueError("LLM returned None response")

            # CRITICAL: Structured data is nested in content[0]['input'] for Anthropic
            content = response_data.get("content")
            if not content or not isinstance(content, list) or len(content) == 0:
                raise ValueError("Invalid LLM response structure")

            return dict(content[0]["input"])
        except Exception as e:
            raise ValueError(f"Failed to parse {expected_type.__name__} from LLM response: {e}") from e

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

        # Get detailed planning context for selected components
        planning_context = build_planning_context(
            selected_node_ids=exec_res["node_ids"],
            selected_workflow_names=exec_res["workflow_names"],
            registry_metadata=prep_res["registry_metadata"],
            saved_workflows=None,  # Will load automatically
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
        """Handle LLM failures gracefully.

        Args:
            prep_res: Prepared data
            exc: Exception that occurred

        Returns:
            Safe default ComponentSelection matching exec() return type
        """
        logger.error(
            f"ComponentBrowsingNode: Browsing failed after retries - {exc}",
            extra={"phase": "fallback", "error": str(exc), "user_input": prep_res.get("user_input", "")[:100]},
        )

        # Provide specific error messages for common failure modes
        error_str = str(exc).lower()
        if "api key" in error_str or "unauthorized" in error_str:
            reasoning = f"LLM API authentication failed: {exc!s}"
        elif "rate limit" in error_str:
            reasoning = f"LLM rate limit exceeded, please retry later: {exc!s}"
        elif "timeout" in error_str:
            reasoning = f"LLM request timed out: {exc!s}"
        else:
            reasoning = f"Component browsing failed due to error: {exc!s}"

        # Return same structure as successful exec() for consistency
        return {"node_ids": [], "workflow_names": [], "reasoning": reasoning}
