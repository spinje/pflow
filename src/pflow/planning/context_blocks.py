"""Context block management for cache-optimized planner pipeline.

This module provides structured context building for the planner pipeline,
optimized for Anthropic prompt caching with clear block boundaries.
Each block is self-contained and cacheable, enabling incremental context
accumulation across planning, generation, and retry stages.
"""

import json
from pathlib import Path
from typing import Any, Optional


class PlannerContextBuilder:
    """Manages cacheable context blocks for planner pipeline.

    The context is built as discrete blocks that can be cached:
    1. Base Context Block - User request, requirements, components
    2. Planning Output Block - Execution plan from PlanningNode
    3. Workflow Output Block - Generated workflow from WorkflowGeneratorNode
    4. Validation Errors Block - Errors for retry attempts

    Each block has clear boundaries for optimal cache prefix matching.
    """

    # Block separators for visual clarity (not semantic)
    BLOCK_SEPARATOR = "\n" + "=" * 60 + "\n"

    # Cached workflow overview (loaded once)
    _workflow_overview_cache: Optional[str] = None
    
    # Maximum retry history to keep in blocks
    MAX_RETRY_HISTORY = 3

    @classmethod
    def _load_workflow_overview(cls) -> str:
        """Load the workflow system overview from markdown file.

        This is loaded once and cached since it's static content.

        Returns:
            The workflow system overview markdown content
        """
        if cls._workflow_overview_cache is None:
            # Load from the prompts directory
            prompts_dir = Path(__file__).parent / "prompts"
            overview_path = prompts_dir / "workflow_system_overview.md"

            if overview_path.exists():
                cls._workflow_overview_cache = overview_path.read_text()
            else:
                # Fallback if file not found
                cls._workflow_overview_cache = "## Workflow System Overview\n\n(Overview not available)\n"

        return cls._workflow_overview_cache

    @classmethod
    def build_base_blocks(
        cls,
        user_request: str,
        requirements_result: dict[str, Any],
        browsed_components: dict[str, Any],
        planning_context: str,
        discovered_params: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Build cache blocks for Anthropic SDK with proper static/dynamic separation.
        
        Block 1: Workflow System Overview (including introduction) - FULLY STATIC, cacheable across all requests
        Block 2: Dynamic Context - All workflow-specific data in XML tags
        
        This structure ensures Block 1 can be cached and reused across ALL workflow
        planning requests, providing maximum cache efficiency.
        
        Args:
            user_request: The user's request (preferably templatized)
            requirements_result: Requirements analysis output
            browsed_components: Selected components from ComponentBrowsingNode
            planning_context: Detailed component information
            discovered_params: Parameters discovered from user input (optional)
            
        Returns:
            List of cache blocks with cache_control markers
        """
        blocks = []
        
        # Block 1: Workflow System Overview (FULLY STATIC - cacheable across all requests)
        # This now includes the introduction text, making it 100% static
        workflow_overview = cls._load_workflow_overview()
        if workflow_overview:
            blocks.append({
                "text": workflow_overview,
                "cache_control": {"type": "ephemeral"}
            })
        
        # Block 2: ALL Dynamic Context (workflow-specific, wrapped in XML tags)
        dynamic_sections = []
        
        # Add user request in XML tags
        dynamic_sections.append("<user_request>")
        dynamic_sections.append(user_request)
        dynamic_sections.append("</user_request>")
        dynamic_sections.append("")
        
        # Add discovered parameters if available
        if discovered_params:
            dynamic_sections.append("<discovered_parameters>")
            dynamic_sections.extend(cls._build_discovered_params_content(discovered_params))
            dynamic_sections.append("</discovered_parameters>")
            dynamic_sections.append("")
        
        # Add requirements if available
        if requirements_result:
            dynamic_sections.append("<requirements_analysis>")
            dynamic_sections.extend(cls._build_requirements_content(requirements_result))
            dynamic_sections.append("</requirements_analysis>")
            dynamic_sections.append("")
        
        # Add selected components if available
        if browsed_components:
            dynamic_sections.append("<selected_components>")
            dynamic_sections.extend(cls._build_components_content(browsed_components))
            dynamic_sections.append("</selected_components>")
            dynamic_sections.append("")
        
        # Add component details if available
        if planning_context:
            dynamic_sections.append("<component_details>")
            dynamic_sections.append(planning_context)
            dynamic_sections.append("</component_details>")
            dynamic_sections.append("")
        
        dynamic_text = "\n".join(dynamic_sections)
        if dynamic_text:
            blocks.append({
                "text": dynamic_text,
                "cache_control": {"type": "ephemeral"}
            })
        
        return blocks

    @classmethod
    def append_planning_block(
        cls,
        blocks: list[dict],
        plan_output: str,
        parsed_plan: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Append planning output block to existing blocks.
        
        CRITICAL: Returns NEW list with block appended (immutable pattern)!
        Example: [Static, Dynamic] + [Plan] → [Static, Dynamic, Plan] as separate list entries
        
        NEVER modify the original blocks list - return blocks + [new_block]
        
        Args:
            blocks: Existing cache blocks [Static overview, Dynamic context]
            plan_output: Markdown plan from PlanningNode
            parsed_plan: Parsed plan dictionary (for potential metadata)
            
        Returns:
            New list with planning block appended: [Static, Dynamic, Plan]
        """
        plan_text = f"## Execution Plan\n\n{plan_output}"
        
        # Check if we're approaching the 4-breakpoint limit
        # Anthropic allows max 4 cache_control markers
        if len(blocks) >= 4:
            # We're at the limit - combine with the last block
            last_block = blocks[-1].copy()
            last_block["text"] = last_block["text"] + "\n\n" + plan_text
            return blocks[:-1] + [last_block]
        
        # Return new list with block appended
        return blocks + [{
            "text": plan_text,
            "cache_control": {"type": "ephemeral"}
        }]

    @classmethod
    def append_workflow_block(
        cls,
        blocks: list[dict],
        workflow: dict[str, Any],
        attempt_number: int,
    ) -> list[dict[str, Any]]:
        """Append Block E (generated workflow) for retry attempts.
        
        CRITICAL: Returns NEW list with block appended (immutable pattern)!
        Example: [A, B, C, D] + [E] → [A, B, C, D, E]
        
        Args:
            blocks: Existing cache blocks
            workflow: Generated workflow JSON
            attempt_number: Which attempt this is (1, 2, 3...)
            
        Returns:
            New list with workflow block appended
        """
        workflow_text = f"## Generated Workflow (Attempt {attempt_number})\n\n{json.dumps(workflow, indent=2)}"
        
        # Check if we're approaching the 4-breakpoint limit
        # Anthropic allows max 4 cache_control markers
        if len(blocks) >= 4:
            # We're at the limit - combine with the last block
            # This typically happens on retry 2+
            last_block = blocks[-1].copy()
            last_block["text"] = last_block["text"] + "\n\n" + workflow_text
            return blocks[:-1] + [last_block]
        
        # Return new list with block appended
        return blocks + [{
            "text": workflow_text,
            "cache_control": {"type": "ephemeral"}
        }]

    @classmethod
    def append_errors_block(
        cls,
        blocks: list[dict],
        validation_errors: list[str],
    ) -> list[dict[str, Any]]:
        """Append Block F (validation errors) for retry attempts.
        
        CRITICAL: Returns NEW list with block appended (immutable pattern)!
        Example: [A, B, C, D, E] + [F] → [A, B, C, D, E, F]
        
        Only appends if validation_errors is non-empty.
        If approaching 4-breakpoint limit, may combine with previous block.
        
        Args:
            blocks: Existing cache blocks
            validation_errors: List of validation error messages
            
        Returns:
            New list with errors block appended (or same list if no errors)
        """
        if not validation_errors:
            return blocks
        
        # Take top 3 errors to avoid bloat
        errors_to_show = validation_errors[:3]
        errors_text = "## Validation Errors\n\n" + "\n".join(
            f"{i+1}. {err}" for i, err in enumerate(errors_to_show)
        )
        
        # Check if we're at or approaching the 4-breakpoint limit
        if len(blocks) >= 4:
            # Combine with the last block
            last_block = blocks[-1].copy()
            last_block["text"] = last_block["text"] + "\n\n" + errors_text
            return blocks[:-1] + [last_block]
        
        # Return new list with block appended
        return blocks + [{
            "text": errors_text,
            "cache_control": {"type": "ephemeral"}
        }]

    # Introduction section removed - now part of workflow_system_overview.md
    # User request section removed - handled directly in build_base_blocks with XML tags

    @classmethod
    def _build_workflow_overview_section(cls) -> list[str]:
        """Build the workflow overview section.

        Returns:
            List of strings forming the workflow overview section
        """
        workflow_overview = cls._load_workflow_overview()
        if not workflow_overview:
            return []

        return [
            workflow_overview,
            "",  # Add spacing after overview
        ]

    @classmethod
    def _build_discovered_params_content(cls, discovered_params: dict[str, Any]) -> list[str]:
        """Build the discovered parameters content (without headers, for XML wrapping).

        Args:
            discovered_params: Parameters discovered from user input

        Returns:
            List of strings with parameter content
        """
        sections = ["These values were extracted from the user's request:"]

        # Handle both dict format and nested format with 'parameters' key
        params_dict = discovered_params.get("parameters", discovered_params) if isinstance(discovered_params, dict) else {}
        
        for param, value in params_dict.items():
            sections.append(f"- {param}: {json.dumps(value)}")

        sections.extend([
            "",
            "Note: These should NEVER be hardcoded in the workflow and should only be considered as POTENTIAL defaults in the inputs section",
        ])

        return sections

    @classmethod
    def _build_requirements_content(cls, requirements_result: dict[str, Any]) -> list[str]:
        """Build the requirements analysis content (without headers, for XML wrapping).

        Args:
            requirements_result: Requirements analysis output

        Returns:
            List of strings with requirements content
        """
        sections = []

        # Add extracted steps
        steps = requirements_result.get("steps", [])
        if steps:
            sections.append("Steps to accomplish:")
            for step in steps:
                sections.append(f"- {step}")
            sections.append("")

        # Add required capabilities
        capabilities = requirements_result.get("required_capabilities", [])
        if capabilities:
            sections.append(f"Required capabilities: {', '.join(capabilities)}")
            sections.append("")

        # Add complexity indicators
        complexity = requirements_result.get("complexity_indicators", {})
        if complexity:
            sections.append("Complexity analysis:")
            for key, value in complexity.items():
                sections.append(f"- {key}: {value}")

        return sections if sections else ["No requirements analysis available"]

    @classmethod
    def _build_components_content(cls, browsed_components: dict[str, Any]) -> list[str]:
        """Build the selected components content (without headers, for XML wrapping).

        Args:
            browsed_components: Selected components from ComponentBrowsingNode

        Returns:
            List of strings with components content
        """
        sections = []

        # Add node IDs
        node_ids = browsed_components.get("node_ids", [])
        if node_ids:
            sections.append(f"Available nodes: {', '.join(node_ids)}")
            sections.append("")

        # Add reasoning for selection
        reasoning = browsed_components.get("reasoning", "")
        if reasoning and node_ids:
            sections.append(f"Selection reasoning: {reasoning}")
            sections.append("")

        if node_ids:
            sections.append(
                "Note: You should not blindly use all the nodes available to you, but rather use the nodes that are most relevant to the user's request and requirements. There may or may not be more available nodes than what you are going to need to suffice the user's request."
            )

        return sections if sections else ["No components selected"]

    # Component details section removed - handled directly in build_base_blocks with XML tags

    @classmethod
    def get_context_metrics(cls, context: str) -> dict[str, Any]:
        """Get metrics about the context for monitoring.

        Args:
            context: The context string

        Returns:
            Dict with metrics (size, blocks, estimated tokens)
        """
        blocks = context.count(cls.BLOCK_SEPARATOR)
        lines = context.count("\n")
        chars = len(context)
        # Rough token estimate (1 token ≈ 4 chars)
        estimated_tokens = chars // 4

        return {
            "blocks": blocks,
            "lines": lines,
            "characters": chars,
            "estimated_tokens": estimated_tokens,
        }
