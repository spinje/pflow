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
    enable_caching: bool = True,  # New parameter to control caching
) -> tuple[list[dict[str, Any]], str]:
    """Build cache blocks from a prompt template.

    Simple strategy when caching is enabled:
    1. Instructions (before ## Context) are cached
    2. Context sections are returned as dynamic prompt
    3. Nodes handle their own special caching logic

    When caching is disabled:
    - Returns empty cache blocks and full formatted prompt

    Args:
        prompt_name: Name of prompt file (e.g., "discovery", "requirements_analysis")
        all_variables: All variables for formatting the template
        cacheable_variables: Deprecated - nodes now handle special caching internally
        enable_caching: Whether to create cache blocks (default True for backwards compatibility)

    Returns:
        (cache_blocks, formatted_prompt)
        - cache_blocks: List of blocks to cache (empty if caching disabled)
        - formatted_prompt: Full formatted template or partial if instructions cached
    """
    prompt_template = load_prompt(prompt_name)

    # If caching is disabled, return full prompt with no cache blocks
    if not enable_caching:
        return [], format_prompt(prompt_template, all_variables)

    cache_blocks = []

    # Split at ## Context marker to cache instructions
    if "## Context" in prompt_template:
        instructions, context_section = prompt_template.split("## Context", 1)

        # Cache instructions when they exist (no length check)
        instructions = instructions.strip()
        if instructions:
            cache_blocks.append({"text": instructions, "cache_control": {"type": "ephemeral", "ttl": "1h"}})

            # When caching instructions, only return the context part as the prompt
            # to avoid duplication (instructions are in cache block)
            formatted_prompt = format_prompt("## Context" + context_section, all_variables)
        else:
            # If no instructions, return the full formatted template
            formatted_prompt = format_prompt(prompt_template, all_variables)
    else:
        # No context marker, return full template
        formatted_prompt = format_prompt(prompt_template, all_variables)

    return cache_blocks, formatted_prompt
