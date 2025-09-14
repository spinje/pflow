"""Simplified prompt caching helper.

This module provides basic caching support for prompt templates.
Special-case logic has been moved into the nodes themselves.
"""

from typing import Any, Optional

from pflow.planning.prompts.loader import format_prompt, load_prompt


def build_cached_prompt(
    prompt_name: str,
    all_variables: dict[str, str],
    cacheable_variables: Optional[dict[str, str]] = None,  # Deprecated - kept for compatibility
) -> tuple[list[dict[str, Any]], str]:
    """Build cache blocks from a prompt template.

    Simple strategy:
    1. Instructions (before ## Context) are cached when substantial
    2. Context sections are always dynamic
    3. Nodes handle their own special caching logic

    Args:
        prompt_name: Name of prompt file (e.g., "discovery", "requirements_analysis")
        all_variables: All variables for formatting the template
        cacheable_variables: Deprecated - nodes now handle special caching internally

    Returns:
        (cache_blocks, formatted_prompt)
        - cache_blocks: List of blocks to cache (instructions only)
        - formatted_prompt: Full formatted template
    """
    prompt_template = load_prompt(prompt_name)
    cache_blocks = []

    # Split at ## Context marker to cache instructions
    if "## Context" in prompt_template:
        instructions, context_section = prompt_template.split("## Context", 1)

        # Cache instructions if substantial
        instructions = instructions.strip()
        if instructions and len(instructions) > 1000:  # ~250 tokens minimum
            cache_blocks.append({"text": instructions, "cache_control": {"type": "ephemeral"}})

    # Always format the full template
    formatted_prompt = format_prompt(prompt_template, all_variables)

    return cache_blocks, formatted_prompt
