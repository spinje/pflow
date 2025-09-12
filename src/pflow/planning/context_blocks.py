"""Context block management for cache-optimized planner pipeline.

This module provides structured context building for the planner pipeline,
optimized for future context caching with clear block boundaries.
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
    def build_base_context(
        cls,
        user_request: str,
        requirements_result: dict[str, Any],
        browsed_components: dict[str, Any],
        planning_context: str,
        discovered_params: Optional[dict[str, Any]] = None,
    ) -> str:
        """Build the base context block shared by Planning and Generator.

        This is the foundational context that both nodes need. It will be
        cached and reused across the pipeline.

        Args:
            user_request: The user's request (preferably templatized)
            requirements_result: Requirements analysis output
            browsed_components: Selected components from ComponentBrowsingNode
            planning_context: Detailed component information
            discovered_params: Parameters discovered from user input (optional)

        Returns:
            Formatted base context block as a string
        """
        sections = []

        # Add introduction
        sections.extend(cls._build_introduction_section())

        # Add user request
        sections.extend(cls._build_user_request_section(user_request))

        # Add workflow overview
        sections.extend(cls._build_workflow_overview_section())

        # Add discovered parameters
        if discovered_params:
            sections.extend(cls._build_discovered_params_section(discovered_params))

        # Add requirements analysis
        if requirements_result:
            sections.extend(cls._build_requirements_section(requirements_result))

        # Add selected components
        if browsed_components:
            sections.extend(cls._build_selected_components_section(browsed_components))

        # Add component details
        if planning_context:
            sections.extend(cls._build_component_details_section(planning_context))

        return "\n".join(sections)

    @classmethod
    def _build_introduction_section(cls) -> list[str]:
        """Build the introduction section for the context.

        Returns:
            List of strings forming the introduction section
        """
        return [
            "You are a specialized workflow planner that first generatoes a detailed execution plan and then generates JSON workflows based on user requests and highly specific system requirements. Follow the provided instructions carefully and think hard about all the requirements, constraints and your current task (either creating a plan or executing the plan and creating the final workflow json ir).",
            "",
        ]

    @classmethod
    def _build_user_request_section(cls, user_request: str) -> list[str]:
        """Build the user request section.

        Args:
            user_request: The user's request

        Returns:
            List of strings forming the user request section
        """
        if not user_request:
            return []

        return [
            "## User Request\n",
            user_request,
            "",
        ]

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
    def _build_discovered_params_section(cls, discovered_params: dict[str, Any]) -> list[str]:
        """Build the discovered parameters section.

        Args:
            discovered_params: Parameters discovered from user input

        Returns:
            List of strings forming the discovered parameters section
        """
        sections = [
            "## Discovered Parameters\n",
            "These values were extracted from the user's request:",
        ]

        for param, value in discovered_params.items():
            sections.append(f"- {param}: {json.dumps(value)}")

        sections.extend([
            "",
            "> Note that these should NEVER be hardcoded in the workflow and should only be considered as POTENTIAL defaults in the inputs section",
            "",
        ])

        return sections

    @classmethod
    def _build_requirements_section(cls, requirements_result: dict[str, Any]) -> list[str]:
        """Build the requirements analysis section.

        Args:
            requirements_result: Requirements analysis output

        Returns:
            List of strings forming the requirements section
        """
        sections = ["## Requirements Analysis\n"]

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
            sections.append("")

        return sections

    @classmethod
    def _build_selected_components_section(cls, browsed_components: dict[str, Any]) -> list[str]:
        """Build the selected components section.

        Args:
            browsed_components: Selected components from ComponentBrowsingNode

        Returns:
            List of strings forming the selected components section
        """
        sections = ["## Available Nodes\n"]

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
                "> Note that you should not blindly use all the nodes available to you, but rather use the nodes that are most relevant to the user's request and requirements. There may or may not be more available nodes than what you are going to need to suffice the user's request."
            )
            sections.append("")

        return sections

    @classmethod
    def _build_component_details_section(cls, planning_context: str) -> list[str]:
        """Build the component details section with truncation.

        Args:
            planning_context: Detailed component information

        Returns:
            List of strings forming the component details section
        """
        sections = ["## Node Details\n"]

        # Intelligently truncate - keep first 3000 chars
        # This should include interfaces but not full descriptions
        truncated = planning_context[:5000]
        if len(planning_context) > 5000:
            truncated += "\n... (truncated for context management)"

        sections.append(truncated)
        sections.append("")

        return sections

    @classmethod
    def append_planning_output(cls, base_context: str, plan_markdown: str, parsed_plan: dict[str, Any]) -> str:
        """Append planning output as new cacheable block.

        This extends the base context with the planning results,
        creating a new cacheable prefix for the workflow generator.

        Args:
            base_context: The base context block
            plan_markdown: The full planning response
            parsed_plan: Parsed plan details (status, node_chain, etc.)

        Returns:
            Extended context with planning output appended
        """
        sections = [base_context.rstrip()]

        # Add planning output block
        sections.append(cls.BLOCK_SEPARATOR)
        sections.append("## Execution Plan\n")
        sections.append(plan_markdown)
        sections.append("")

        # Add parsed summary for quick reference
        sections.append("### Plan Summary\n")
        sections.append(f"- Status: {parsed_plan.get('status', 'UNKNOWN')}")
        sections.append(f"- Node Chain: {parsed_plan.get('node_chain', 'None')}")

        missing_caps = parsed_plan.get("missing_capabilities", [])
        if missing_caps:
            sections.append(f"- Missing Capabilities: {', '.join(missing_caps)}")

        sections.append("")

        return "\n".join(sections)

    @classmethod
    def append_workflow_output(cls, context: str, workflow: dict[str, Any], attempt: int) -> str:
        """Append generated workflow as new cacheable block.

        This adds the generated workflow to the context for potential
        retry scenarios, enabling the LLM to see what was previously tried.

        Args:
            context: The current context (base + planning)
            workflow: The generated workflow dict
            attempt: The attempt number

        Returns:
            Context with workflow output appended
        """
        sections = [context.rstrip()]

        # Add workflow output block
        sections.append(cls.BLOCK_SEPARATOR)
        sections.append(f"## Generated Workflow (Attempt {attempt})\n")

        # Add summary first
        nodes = workflow.get("nodes", [])
        node_ids = [n.get("id", "unknown") for n in nodes]
        sections.append(f"Generated {len(nodes)} nodes: {', '.join(node_ids)}")
        sections.append(f"Start node: {workflow.get('start_node', 'none')}")

        inputs = workflow.get("inputs", {})
        if inputs:
            sections.append(f"Workflow inputs: {', '.join(inputs.keys())}")
        sections.append("")

        # Add full JSON for reference
        sections.append("Full workflow JSON:")
        sections.append("```json")
        sections.append(json.dumps(workflow, indent=2))
        sections.append("```")
        sections.append("")

        return "\n".join(sections)

    @classmethod
    def append_validation_errors(cls, context: str, errors: list[str]) -> str:
        """Append validation errors for retry.

        This adds validation errors to the context so the LLM can
        understand what went wrong and fix it in the next attempt.

        Args:
            context: The current context
            errors: List of validation error messages

        Returns:
            Context with validation errors appended
        """
        sections = [context.rstrip()]

        # Add validation errors block
        sections.append(cls.BLOCK_SEPARATOR)
        sections.append("## Validation Errors\n")
        sections.append("The previous workflow failed validation with these errors:")

        for error in errors[:5]:  # Limit to 5 errors to avoid bloat
            sections.append(f"- {error}")

        if len(errors) > 5:
            sections.append(f"... and {len(errors) - 5} more errors")

        sections.append("")
        sections.append("Please generate a corrected workflow that fixes these specific issues.")
        sections.append("")

        return "\n".join(sections)

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
