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
from pflow.planning.utils.llm_helpers import generate_workflow_name, parse_structured_response
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

        # Get WorkflowManager from shared store if available
        workflow_manager = shared.get("workflow_manager")

        # Load discovery context with all nodes and workflows
        try:
            discovery_context = build_discovery_context(
                node_ids=None,  # All nodes
                workflow_names=None,  # All workflows
                registry_metadata=None,  # Will load from default registry
                workflow_manager=workflow_manager,  # Pass from shared store
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

        # Get WorkflowManager from shared store if available
        workflow_manager = shared.get("workflow_manager")

        # Get discovery context for browsing
        try:
            discovery_context = build_discovery_context(
                node_ids=None,
                workflow_names=None,
                registry_metadata=registry_metadata,
                workflow_manager=workflow_manager,  # Pass from shared store
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
        result = parse_structured_response(response, ComponentSelection)

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
        planning_context = build_planning_context(
            selected_node_ids=exec_res["node_ids"],
            selected_workflow_names=exec_res["workflow_names"],
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
    These hints provide context to help the generator create appropriate template variables.

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
        model_name = self.params.get("model", "anthropic/claude-sonnet-4-0")
        temperature = self.params.get("temperature", 0.0)

        # Check for stdin data (fallback parameter source)
        stdin_info = None
        if shared.get("stdin"):
            stdin_info = {"type": "text", "preview": str(shared["stdin"])[:200]}
        elif shared.get("stdin_binary"):
            stdin_info = {"type": "binary", "size": str(len(shared["stdin_binary"]))}
        elif shared.get("stdin_path"):
            stdin_info = {"type": "file", "path": shared["stdin_path"]}

        # Get planning context (might be empty string on error)
        planning_context = shared.get("planning_context", "")
        browsed_components = shared.get("browsed_components", {})

        return {
            "user_input": user_input,
            "stdin_info": stdin_info,
            "planning_context": planning_context,
            "browsed_components": browsed_components,
            "model_name": model_name,
            "temperature": temperature,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Extract named parameters from natural language.

        Args:
            prep_res: Prepared data with user_input and context

        Returns:
            ParameterDiscovery dict with parameters, stdin_type, reasoning
        """
        logger.debug(f"ParameterDiscoveryNode: Discovering parameters from: {prep_res['user_input'][:100]}...")

        # Build context about available components (if any)
        context_section = ""
        if prep_res["planning_context"]:
            context_section = f"\n\nAvailable components context:\n{prep_res['planning_context'][:2000]}"
        elif prep_res["browsed_components"]:
            nodes = prep_res["browsed_components"].get("node_ids", [])
            workflows = prep_res["browsed_components"].get("workflow_names", [])
            context_section = (
                f"\n\nSelected components:\n- Nodes: {', '.join(nodes[:10])}\n- Workflows: {', '.join(workflows[:5])}"
            )

        stdin_section = ""
        if prep_res["stdin_info"]:
            stdin_section = f"\n\nStdin data available: {prep_res['stdin_info']}"

        prompt = f"""You are a parameter discovery system that extracts named parameters from natural language requests.

User request: {prep_res["user_input"]}{context_section}{stdin_section}

Extract parameters with their likely names and values. Focus on:
1. File paths and names (e.g., "report.csv" → filename: "report.csv")
2. Numeric values (e.g., "last 20" → limit: "20")
3. States/filters (e.g., "closed issues" → state: "closed")
4. Formats (e.g., "as JSON" → output_format: "json")
5. Identifiers (e.g., "repo pflow" → repo: "pflow")

Return parameters as a simple name:value mapping. If stdin is present, note its type.

Examples:
- "process data.csv and convert to json" → {{"filename": "data.csv", "output_format": "json"}}
- "last 20 closed issues from repo" → {{"limit": "20", "state": "closed"}}
- "analyze the piped data" → {{}} (parameters will come from stdin)"""

        # Lazy-load model at execution time (PocketFlow best practice)
        model = llm.get_model(prep_res["model_name"])
        response = model.prompt(prompt, schema=ParameterDiscovery, temperature=prep_res["temperature"])
        result = parse_structured_response(response, ParameterDiscovery)

        logger.info(
            f"ParameterDiscoveryNode: Discovered {len(result['parameters'])} parameters",
            extra={"phase": "exec", "param_count": len(result["parameters"]), "stdin": result.get("stdin_type")},
        )

        return result

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

        logger.info(
            f"ParameterDiscoveryNode: Stored {len(exec_res['parameters'])} discovered parameters",
            extra={"phase": "post", "parameters": list(exec_res["parameters"].keys())},
        )

        # Path B continues to generation
        return ""  # No action string needed for simple continuation

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle LLM failures gracefully.

        Args:
            prep_res: Prepared data
            exc: Exception that occurred

        Returns:
            Safe default ParameterDiscovery matching exec() return type
        """
        logger.error(
            f"ParameterDiscoveryNode: Parameter discovery failed - {exc}",
            extra={"phase": "fallback", "error": str(exc)},
        )

        # Return empty parameters on failure (generation will proceed without hints)
        return {
            "parameters": {},
            "stdin_type": prep_res.get("stdin_info", {}).get("type"),
            "reasoning": f"Parameter discovery failed: {exc!s}. Proceeding without parameter hints.",
        }


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
        model_name = self.params.get("model", "anthropic/claude-sonnet-4-0")
        temperature = self.params.get("temperature", 0.0)

        # Get stdin as fallback parameter source
        stdin_data = shared.get("stdin", "")

        return {
            "user_input": user_input,
            "workflow_ir": workflow_ir,
            "stdin_data": stdin_data,
            "model_name": model_name,
            "temperature": temperature,
        }

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
        inputs_description = []
        for param_name, param_spec in inputs_spec.items():
            required = param_spec.get("required", True)  # Default to required
            param_type = param_spec.get("type", "string")
            description = param_spec.get("description", "")
            default = param_spec.get("default")

            status = "required" if required else f"optional (default: {default})"
            inputs_description.append(f"- {param_name} ({param_type}, {status}): {description}")

        stdin_section = ""
        if prep_res["stdin_data"]:
            stdin_section = f"\n\nStdin data available:\n{prep_res['stdin_data'][:500]}"

        prompt = f"""You are a parameter extraction system that maps user input to workflow parameters.

The workflow expects these input parameters:
{chr(10).join(inputs_description)}

User request: {prep_res["user_input"]}{stdin_section}

Extract values for each parameter from the user input or stdin data.
Focus on exact parameter names listed above.
If a required parameter is missing, include it in the missing list.

Important:
- Preserve exact parameter names (case-sensitive)
- Extract actual values, not template variables
- Check stdin if parameters not found in user input
- Required parameters without values should be listed as missing"""

        # Lazy-load model at execution time (PocketFlow best practice)
        model = llm.get_model(prep_res["model_name"])
        response = model.prompt(prompt, schema=ParameterExtraction, temperature=prep_res["temperature"])
        result = parse_structured_response(response, ParameterExtraction)

        # Validate all required parameters are present
        missing_required = []
        for param_name, param_spec in inputs_spec.items():
            if param_spec.get("required", True) and param_name not in result["extracted"]:
                missing_required.append(param_name)

        # Update missing list with any we found
        if missing_required:
            result["missing"] = list(set(result.get("missing", []) + missing_required))
            result["confidence"] = 0.0  # No confidence if missing required params

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
        """Store extraction results and route based on completeness.

        Args:
            shared: PocketFlow shared store
            prep_res: Prepared data
            exec_res: Execution result (ParameterExtraction)

        Returns:
            "params_complete" if all required found, "params_incomplete" otherwise
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

        logger.info(
            "ParameterMappingNode: All required parameters found - proceeding to preparation",
            extra={"phase": "post", "action": "params_complete", "params": list(exec_res["extracted"].keys())},
        )
        return "params_complete"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle LLM failures gracefully.

        Args:
            prep_res: Prepared data
            exc: Exception that occurred

        Returns:
            Safe default ParameterExtraction matching exec() return type
        """
        logger.error(
            f"ParameterMappingNode: Parameter mapping failed - {exc}",
            extra={"phase": "fallback", "error": str(exc)},
        )

        # On failure, mark all parameters as missing
        workflow_ir = prep_res.get("workflow_ir", {})
        inputs_spec = workflow_ir.get("inputs", {})
        missing = [name for name, spec in inputs_spec.items() if spec.get("required", True)]

        return {
            "extracted": {},
            "missing": missing,
            "confidence": 0.0,
            "reasoning": f"Parameter extraction failed: {exc!s}",
        }


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
        return {
            "model_name": self.params.get("model", "anthropic/claude-sonnet-4-0"),
            "temperature": self.params.get("temperature", 0.0),
            "planning_context": shared.get("planning_context", ""),
            "user_input": shared.get("user_input", ""),
            "discovered_params": shared.get("discovered_params"),
            "browsed_components": shared.get("browsed_components", {}),
            "validation_errors": shared.get("validation_errors", []),
            "generation_attempts": shared.get("generation_attempts", 0),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Generate workflow using LLM with structured output.

        Args:
            prep_res: Prepared data including planning context and parameters

        Returns:
            Dict with generated workflow and attempt count

        Raises:
            ValueError: If planning context is empty or response parsing fails
        """
        logger.debug(f"Generating workflow for: {prep_res['user_input'][:100]}...")

        # CRITICAL: Planning context must be available
        if not prep_res["planning_context"]:
            raise ValueError("Planning context is required but was empty")

        # Check if planning context is an error dict
        if isinstance(prep_res["planning_context"], dict) and "error" in prep_res["planning_context"]:
            raise ValueError(f"Planning context error: {prep_res['planning_context']['error']}")

        # Lazy load model
        model = llm.get_model(prep_res["model_name"])

        # Build prompt with template emphasis
        prompt = self._build_prompt(prep_res)

        # Import FlowIR here to avoid circular imports
        from pflow.planning.ir_models import FlowIR

        # Generate with schema
        response = model.prompt(prompt, schema=FlowIR, temperature=prep_res["temperature"])

        # Parse nested Anthropic response
        result = parse_structured_response(response, FlowIR)

        # Convert to dict if it's a Pydantic model
        if hasattr(result, "model_dump"):
            workflow = result.model_dump(by_alias=True, exclude_none=True)
        else:
            workflow = dict(result)

        logger.debug(f"Generated {len(workflow.get('nodes', []))} nodes")

        return {"workflow": workflow, "attempt": prep_res["generation_attempts"] + 1}

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store generated workflow and route to validation.

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

        # CRITICAL: Always route to validation
        return "validate"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
        """Handle generation failure gracefully.

        Returns same structure as exec() to maintain compatibility with post().
        The empty workflow will be caught by ValidatorNode and routed appropriately.

        Args:
            prep_res: Prepared data that caused the failure
            exc: Exception that occurred

        Returns:
            Dict with same structure as exec() - workflow dict and attempt count
        """
        logger.error(f"GeneratorNode failed after retries: {exc}")

        # Return minimal valid workflow structure that post() can process
        # ValidatorNode will detect this is empty and route to "failed"
        fallback_workflow = {
            "ir_version": "0.1.0",
            "nodes": [],  # Empty nodes will fail validation
            "edges": [],
            "start_node": None,
            "inputs": {},
            "outputs": {},
            # Store error information in the workflow for debugging
            "_error": f"Generation failed: {exc}",
            "_fallback": True,
        }

        return {"workflow": fallback_workflow, "attempt": prep_res.get("generation_attempts", 0) + 1}

    def _build_prompt(self, prep_res: dict[str, Any]) -> str:
        """Build generation prompt with template emphasis.

        Args:
            prep_res: Prepared data with context and parameters

        Returns:
            Formatted prompt string
        """
        prompt = f"""Generate a workflow for: {prep_res["user_input"]}

Available components:
{prep_res["planning_context"]}

CRITICAL Requirements:
1. Use template variables ($variable) for ALL dynamic values
2. NEVER hardcode values like "1234" - use $issue_number instead
3. Generate LINEAR workflow only - no branching
4. Template variables can use paths like $data.field.subfield
5. Each template variable MUST have a corresponding key in the inputs field
6. Create descriptive node IDs (e.g., "fetch_issues", not "n1")
7. Avoid multiple nodes of the same type (causes shared store collision)

Workflow Structure Requirements:
- Must include "ir_version": "0.1.0"
- Must include "inputs" field with parameter specifications
- Each input should have: description, required, type, and optional default
- Use universal defaults only (e.g., 100, not request-specific like 20)
- Rename parameters for clarity (e.g., "filename" -> "input_file")
"""

        # Add discovered parameters as hints
        if prep_res["discovered_params"]:
            prompt += "\nDiscovered parameters (use as hints, rename for clarity):\n"
            for param, value in prep_res["discovered_params"].items():
                prompt += f"  - {param}: {value}\n"
            prompt += "Remember: These are hints. You control the inputs specification.\n"

        # Add validation errors for retry
        if prep_res["generation_attempts"] > 0 and prep_res["validation_errors"]:
            prompt += "\n\nFix ONLY these specific issues from the previous attempt:\n"
            for error in prep_res["validation_errors"][:3]:  # Max 3 errors
                prompt += f"- {error}\n"
            prompt += "Keep the rest of the workflow unchanged."

        return prompt


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
        """Extract workflow and attempt count from shared store.

        Args:
            shared: PocketFlow shared store

        Returns:
            Dict with workflow and generation_attempts
        """
        return {
            "workflow": shared.get("generated_workflow"),
            "generation_attempts": shared.get("generation_attempts", 0),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Orchestrate validation checks.

        Calls:
        1. validate_ir() for structural validation
        2. TemplateValidator for template and unused input validation
        3. Registry check for node type validation

        Args:
            prep_res: Contains workflow and generation_attempts

        Returns:
            Dict with errors list (empty if valid)
        """
        workflow = prep_res.get("workflow")
        if not workflow:
            logger.error("No workflow provided for validation")
            return {"errors": ["No workflow provided for validation"]}

        errors: list[str] = []

        # Run all validation checks
        structural_errors = self._validate_structure(workflow)
        errors.extend(structural_errors)

        template_errors = self._validate_templates(workflow)
        errors.extend(template_errors)

        node_type_errors = self._validate_node_types(workflow)
        errors.extend(node_type_errors)

        # Return top 3 most actionable errors
        if errors:
            logger.info(f"Validation found {len(errors)} total errors, returning top 3")
        else:
            logger.info("All validation checks passed")

        return {"errors": errors[:3]}  # Limit to top 3 for LLM retry

    def _validate_structure(self, workflow: dict[str, Any]) -> list[str]:
        """Validate workflow structure using IR schema.

        Args:
            workflow: Workflow IR to validate

        Returns:
            List of structural validation errors
        """
        errors: list[str] = []
        try:
            from pflow.core.ir_schema import validate_ir

            validate_ir(workflow)
            logger.debug("Structural validation passed")
        except Exception as e:
            # Handle both ValidationError and other exceptions
            if hasattr(e, "path") and hasattr(e, "message"):
                # ValidationError with path
                error_msg = f"{e.path}: {e.message}" if e.path else str(e.message)
            else:
                # Other exceptions or ValidationError without path
                error_msg = str(e)
            errors.append(f"Structure: {error_msg}")
            logger.warning(f"Structural validation failed: {error_msg}")

        return errors

    def _validate_templates(self, workflow: dict[str, Any]) -> list[str]:
        """Validate template variables and unused inputs.

        Args:
            workflow: Workflow IR to validate

        Returns:
            List of template validation errors
        """
        errors: list[str] = []
        try:
            from pflow.runtime.template_validator import TemplateValidator

            template_errors = TemplateValidator.validate_workflow_templates(
                workflow,
                {},  # Empty dict - no initial_params at generation time
                self.registry,
            )
            errors.extend(template_errors)
            if template_errors:
                logger.warning(f"Template validation found {len(template_errors)} errors")
            else:
                logger.debug("Template validation passed")
        except Exception as e:
            errors.append(f"Template validation error: {e}")
            logger.exception("Template validation failed")

        return errors

    def _validate_node_types(self, workflow: dict[str, Any]) -> list[str]:
        """Validate that all node types exist in registry.

        Args:
            workflow: Workflow IR to validate

        Returns:
            List of unknown node type errors
        """
        errors: list[str] = []
        try:
            metadata = self.registry.get_nodes_metadata()  # type: ignore[call-arg]
            for node in workflow.get("nodes", []):
                node_type = node.get("type")
                if node_type and node_type not in metadata:
                    errors.append(f"Unknown node type: '{node_type}'")
                    logger.warning(f"Unknown node type: {node_type}")

            if not any("Unknown node type" in e for e in errors):
                logger.debug("Node type validation passed")
        except Exception as e:
            errors.append(f"Registry validation error: {e}")
            logger.exception("Registry validation failed")

        return errors

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
        return {
            "workflow": shared.get("generated_workflow", {}),
            "user_input": shared.get("user_input", ""),
            "planning_context": shared.get("planning_context", ""),
            "discovered_params": shared.get("discovered_params", {}),
            "model_name": self.params.get("model", "anthropic/claude-3-haiku-20240307"),  # Faster model
            "temperature": self.params.get("temperature", 0.3),  # Lower for consistency
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Use LLM to generate high-quality searchable metadata.

        Args:
            prep_res: Contains workflow and context for analysis

        Returns:
            Dict with rich metadata fields for discovery
        """

        import llm

        from pflow.planning.ir_models import WorkflowMetadata
        from pflow.planning.utils.llm_helpers import parse_structured_response

        workflow = prep_res.get("workflow", {})

        # Build comprehensive prompt for metadata generation
        prompt = self._build_metadata_prompt(
            workflow=workflow,
            user_input=prep_res.get("user_input", ""),
            discovered_params=prep_res.get("discovered_params", {}),
        )

        # Get LLM to analyze and generate metadata
        model = llm.get_model(prep_res["model_name"])
        response = model.prompt(prompt, schema=WorkflowMetadata, temperature=prep_res["temperature"])

        # Parse the structured response
        metadata = parse_structured_response(response, WorkflowMetadata)

        # Convert to plain dict for uniform downstream handling
        metadata_dict = metadata.model_dump() if hasattr(metadata, "model_dump") else dict(metadata)

        logger.debug(
            "Generated rich metadata: name=%s, keywords=%s",
            metadata_dict.get("suggested_name"),
            len(metadata_dict.get("search_keywords", [])),
        )

        # Return comprehensive metadata (keep keys as produced by schema/tests)
        return {
            "suggested_name": metadata_dict.get("suggested_name"),
            "description": metadata_dict.get("description"),
            "search_keywords": metadata_dict.get("search_keywords", []),
            "capabilities": metadata_dict.get("capabilities", []),
            "typical_use_cases": metadata_dict.get("typical_use_cases", []),
            "declared_inputs": list(workflow.get("inputs", {}).keys()),
            "declared_outputs": self._extract_outputs(workflow),
        }

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
        """Fallback with basic metadata using simple extraction.

        Args:
            prep_res: Prepared data
            exc: The exception that triggered the fallback

        Returns:
            Dict with basic metadata
        """
        logger.warning(f"MetadataGenerationNode exec_fallback triggered: {exc}, using simple extraction")

        workflow = prep_res.get("workflow", {})
        user_input = prep_res.get("user_input", "")

        # Fallback to simple extraction
        return {
            "suggested_name": generate_workflow_name(user_input),
            "description": user_input[:200] if user_input else "Generated workflow",
            "search_keywords": [],  # Empty in fallback
            "capabilities": [],  # Empty in fallback
            "typical_use_cases": [],  # Empty in fallback
            "declared_inputs": list(workflow.get("inputs", {}).keys()),
            "declared_outputs": self._extract_outputs(workflow),
        }

    def _build_metadata_prompt(self, workflow: dict, user_input: str, discovered_params: dict) -> str:
        """Build comprehensive prompt for metadata generation.

        Args:
            workflow: The generated workflow IR
            user_input: Original user request
            discovered_params: Parameters discovered from user input

        Returns:
            Detailed prompt for LLM metadata generation
        """

        # Analyze workflow to understand what it does
        nodes_summary = self._summarize_nodes(workflow.get("nodes", []))

        return f"""Analyze this workflow and generate high-quality metadata for future discovery.

ORIGINAL USER REQUEST:
{user_input}

WORKFLOW STRUCTURE:
Nodes: {nodes_summary}
Inputs: {", ".join(workflow.get("inputs", {}).keys()) or "none"}
Parameters discovered: {", ".join(discovered_params.keys()) if discovered_params else "none"}

CRITICAL REQUIREMENT: Generate metadata that enables this workflow to be found with various search queries.

CRITICAL RULES for description and keywords:
- NEVER include specific parameter values (like "30 issues" or "pflow repo")
- NEVER mention specific file names or paths from the user's request
- DO describe capabilities generically ("fetches closed issues", not "fetches 30 issues")
- DO focus on what the workflow CAN do, not what it WAS configured to do
- Example BAD: "Fetches the last 30 closed issues from pflow repo"
- Example GOOD: "Fetches closed issues from any GitHub repository"

The workflow is REUSABLE with different parameters - the metadata must reflect this!

Generate the following metadata:

1. suggested_name (kebab-case, max 50 chars):
   - Concise, memorable, searchable
   - Indicates primary function
   - Examples: "github-changelog-generator", "issue-triage-analyzer"

2. description (100-500 chars):
   - Explain WHAT it does, WHY it's useful, WHEN to use it
   - Include key technologies (GitHub, LLM, etc.)
   - Make it searchable - think about different phrasings
   - Focus on value, not implementation

3. search_keywords (3-10 terms):
   - Alternative ways users might search for this
   - Include synonyms and related concepts
   - Think: What would someone type when looking for this?
   - Example: "changelog" → also include "release notes", "version history"

4. capabilities (2-6 bullet points):
   - What this workflow can do
   - User-focused benefits
   - Example: "Fetches GitHub issues", "Categorizes changes automatically"

5. typical_use_cases (1-3 scenarios):
   - Real-world problems it solves
   - When someone would use this
   - Example: "Preparing release documentation"

REMEMBER: The metadata determines whether this workflow will be discovered and reused.
Poor metadata means duplicate workflows will be created instead of reusing this one."""

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
