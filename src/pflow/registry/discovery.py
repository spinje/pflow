"""Component discovery via LLM-powered selection.

Finds nodes (and optionally workflows) needed for building a workflow
based on a natural language task description.
Replaces the PocketFlow-based ComponentBrowsingNode with a plain function.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import llm
from pydantic import BaseModel

from pflow.core.llm_utils import parse_structured_response
from pflow.core.prompt_utils import format_prompt, load_prompt
from pflow.core.workflow.context import build_workflows_context
from pflow.registry.context_builder import build_component_context, build_nodes_context

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "component_browsing.md"


class ComponentSelectionSchema(BaseModel):
    """Schema for LLM structured output."""

    node_ids: list[str]
    workflow_names: list[str]
    reasoning: str


@dataclass(frozen=True)
class ComponentSelection:
    """Result of LLM-powered component discovery."""

    node_ids: list[str]
    reasoning: str
    component_context: str  # Pre-rendered markdown specs from build_component_context()


def find_components(
    task: str,
    model_name: Optional[str] = None,
    registry_metadata: Optional[dict[str, Any]] = None,
    include_workflows: bool = True,
) -> ComponentSelection:
    """Discover components (nodes) needed for building a workflow.

    Args:
        task: Natural language description of what needs to be built
        model_name: LLM model to use (defaults to discovery model from settings)
        registry_metadata: Pre-filtered registry entries (e.g., MCP-only)
        include_workflows: Include saved workflows in the LLM context.
            Set to False for MCP-scoped searches where workflows are irrelevant.

    Returns:
        ComponentSelection with selected node IDs and rendered component context
    """
    from pflow.core.llm_config import get_model_for_feature
    from pflow.core.workflow.manager import WorkflowManager

    resolved_model = model_name or get_model_for_feature("discovery")

    if registry_metadata is None:
        from pflow.registry import Registry

        registry_metadata = Registry().load()

    # Build contexts
    nodes_context = build_nodes_context(registry_metadata=registry_metadata)
    workflows_context = build_workflows_context() if include_workflows else ""

    # Load and format prompt
    prompt_template = load_prompt(_PROMPT_PATH)
    formatted_prompt = format_prompt(
        prompt_template,
        {
            "nodes_context": nodes_context,
            "workflows_context": workflows_context,
            "user_input": task,
            "requirements": "None",
        },
    )

    # LLM call
    model = llm.get_model(resolved_model)
    response = model.prompt(formatted_prompt, schema=ComponentSelectionSchema)
    result = parse_structured_response(response, ComponentSelectionSchema)

    # Clear workflow_names (current behavior — nested workflow selection not yet integrated)
    if result.get("workflow_names"):
        logger.info(
            f"find_components: Ignoring {len(result['workflow_names'])} workflows "
            "(nested workflows not integrated in discovery yet)",
        )
        result["workflow_names"] = []

    logger.info(f"find_components: Selected {len(result['node_ids'])} nodes")

    # Build detailed component context for selected components
    workflow_manager = WorkflowManager()
    component_context = build_component_context(
        selected_node_ids=result["node_ids"],
        selected_workflow_names=[],
        registry_metadata=registry_metadata,
        workflow_manager=workflow_manager,
    )

    # Handle error dict from build_component_context
    if isinstance(component_context, dict) and "error" in component_context:
        logger.warning(f"find_components: Component context error - {component_context['error']}")
        component_context_str = ""
    else:
        component_context_str = str(component_context)

    return ComponentSelection(
        node_ids=result["node_ids"],
        reasoning=result["reasoning"],
        component_context=component_context_str,
    )
