"""Workflow discovery via LLM-powered matching.

Finds saved workflows that match a user's natural language query.
Replaces the PocketFlow-based WorkflowDiscoveryNode with a plain function.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from pflow.core.exceptions import WorkflowNotFoundError
from pflow.core.llm_client import complete
from pflow.core.llm_utils import parse_structured_response
from pflow.core.prompt_utils import format_prompt, load_prompt
from pflow.core.workflow.context import build_workflows_context
from pflow.core.workflow.manager import WorkflowManager

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "discovery.md"


class WorkflowDecision(BaseModel):
    """Schema for LLM structured output."""

    found: bool
    workflow_name: str | None = None
    confidence: float
    reasoning: str


@dataclass(frozen=True)
class WorkflowMatch:
    """Result of LLM-powered workflow discovery."""

    found: bool
    workflow_name: str | None
    confidence: float
    reasoning: str
    workflow: dict[str, Any] | None  # Full metadata from WorkflowManager.load() if found


def find_workflow(
    query: str,
    model_name: str | None = None,
    workflow_manager: WorkflowManager | None = None,
) -> WorkflowMatch:
    """Discover a saved workflow that matches the user's query.

    Args:
        query: Natural language description of desired workflow
        model_name: LLM model to use (defaults to discovery model from settings)
        workflow_manager: Optional WorkflowManager instance

    Returns:
        WorkflowMatch with discovery results
    """
    from pflow.core.llm_config import get_model_for_feature

    resolved_model = model_name or get_model_for_feature("discovery")
    manager = workflow_manager or WorkflowManager()

    # Build workflows context
    discovery_context = build_workflows_context(workflow_manager=manager)

    # Early return if no saved workflows exist
    if not discovery_context:
        logger.info("find_workflow: No workflows exist, skipping LLM call")
        return WorkflowMatch(
            found=False,
            workflow_name=None,
            confidence=1.0,
            reasoning="No existing workflows in the system to match against",
            workflow=None,
        )

    # Load and format prompt
    prompt_template = load_prompt(_PROMPT_PATH)
    formatted_prompt = format_prompt(prompt_template, {"discovery_context": discovery_context, "user_input": query})

    # LLM call via the pflow-owned LiteLLM adapter.
    # Pydantic class → JSON Schema dict (the adapter accepts only dicts).
    response = complete(
        model=resolved_model,
        prompt=formatted_prompt,
        schema=WorkflowDecision.model_json_schema(),
    )
    result = parse_structured_response(response, WorkflowDecision, model=resolved_model)

    logger.info(
        f"find_workflow: found={result['found']}, "
        f"workflow={result.get('workflow_name')}, confidence={result['confidence']}",
    )

    # If found, try to load the workflow from disk
    if result["found"] and result.get("workflow_name"):
        try:
            loaded_workflow = manager.load(result["workflow_name"])
            return WorkflowMatch(
                found=True,
                workflow_name=result["workflow_name"],
                confidence=result["confidence"],
                reasoning=result["reasoning"],
                workflow=loaded_workflow,
            )
        except WorkflowNotFoundError:
            logger.warning(f"find_workflow: Workflow '{result['workflow_name']}' not found on disk")

    return WorkflowMatch(
        found=False,
        workflow_name=result.get("workflow_name"),
        confidence=result["confidence"],
        reasoning=result["reasoning"],
        workflow=None,
    )
