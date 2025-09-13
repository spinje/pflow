"""Cache utility functions for planner nodes.

This module contains utility functions for cache management and metrics.
The main cache block building logic has moved to prompt_cache_helper.py.
"""

from typing import Any


def extract_static_from_prompt(
    full_prompt: str,
    dynamic_markers: list[str]
) -> tuple[str, str]:
    """Extract static and dynamic portions from a prompt.
    
    Helper function to separate static content (cacheable) from
    dynamic content (user-specific) in existing prompts.
    
    Args:
        full_prompt: The complete prompt with both static and dynamic content
        dynamic_markers: List of markers that indicate dynamic content
                        (e.g., ["User Request:", "Selected Components:"])
        
    Returns:
        Tuple of (static_content, dynamic_content)
    """
    static_parts = []
    dynamic_parts = []
    
    lines = full_prompt.split('\n')
    in_dynamic_section = False
    
    for line in lines:
        # Check if this line starts a dynamic section
        for marker in dynamic_markers:
            if marker in line:
                in_dynamic_section = True
                break
        
        if in_dynamic_section:
            dynamic_parts.append(line)
        else:
            static_parts.append(line)
    
    static_content = '\n'.join(static_parts).strip()
    dynamic_content = '\n'.join(dynamic_parts).strip()
    
    return static_content, dynamic_content


def should_use_caching(
    cache_planner: bool,
    node_name: str,
    always_cache_nodes: list[str] = None
) -> bool:
    """Determine if a node should use caching.
    
    Some nodes (like PlanningNode and WorkflowGeneratorNode) should always
    use caching for intra-session benefits, regardless of the flag.
    
    Args:
        cache_planner: The cache_planner flag from CLI
        node_name: Name of the current node
        always_cache_nodes: List of nodes that should always cache
                           (defaults to ["planning", "workflow-generator"])
        
    Returns:
        True if the node should use caching, False otherwise
    """
    if always_cache_nodes is None:
        always_cache_nodes = ["planning", "workflow-generator"]
    
    # These nodes always cache for intra-session benefits
    if node_name in always_cache_nodes:
        return True
    
    # Other nodes only cache if flag is set
    return cache_planner


def format_cache_metrics(usage: dict[str, Any]) -> str:
    """Format cache metrics for logging.
    
    Args:
        usage: Usage dictionary from LLM response
        
    Returns:
        Formatted string describing cache metrics
    """
    cache_creation = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    
    if cache_creation > 0 and cache_read > 0:
        return f"Cache: created {cache_creation} tokens, read {cache_read} tokens"
    elif cache_creation > 0:
        return f"Cache: created {cache_creation} tokens"
    elif cache_read > 0:
        return f"Cache: read {cache_read} tokens (saved ~90% on cached content)"
    else:
        return "Cache: no caching occurred"