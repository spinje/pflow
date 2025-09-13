"""Smart prompt caching that respects template structure.

This module provides intelligent caching for prompt templates, understanding which
parts of prompts should be cached (instructions) and which should remain dynamic
(context sections), with special handling for discovery and component_browsing.
"""

from typing import Optional, Tuple, List, Dict, Any
from pflow.planning.prompts.loader import load_prompt, format_prompt


class PromptCacheBuilder:
    """Builds cache blocks from prompt templates intelligently."""
    
    # Nodes with cacheable context sections
    # Only these two nodes have static documentation in their context
    CACHEABLE_CONTEXT_NODES = {
        "discovery": ["discovery_context"],
        "component_browsing": ["nodes_context", "workflows_context"]
    }
    
    def build_cache_blocks(
        self,
        prompt_name: str,
        static_context_values: Optional[Dict[str, str]] = None
    ) -> Tuple[List[Dict[str, Any]], str]:
        """Build cache blocks from a prompt template.
        
        The strategy:
        1. Instructions (before ## Context) are always cached
        2. Context sections are usually dynamic (user input, generated content)
        3. Exception: discovery and component_browsing have cacheable documentation
        
        Args:
            prompt_name: Name of prompt file (e.g., "discovery", "requirements_analysis")
            static_context_values: Values for cacheable context variables
                Only used for discovery and component_browsing nodes
                e.g., {"discovery_context": "...", "nodes_context": "..."}
        
        Returns:
            (cache_blocks, prompt_template_for_dynamic)
            - cache_blocks: List of blocks to cache
            - prompt_template_for_dynamic: Full template to format with ALL variables
        """
        prompt_template = load_prompt(prompt_name)
        
        # Split at ## Context marker
        if "## Context" in prompt_template:
            instructions, context_section = prompt_template.split("## Context", 1)
            context_section = "## Context" + context_section
        else:
            # No context section, entire prompt is instructions
            instructions = prompt_template
            context_section = ""
        
        cache_blocks = []
        
        # Block 1: Instructions (always cached if substantial)
        # For special nodes with cacheable context, we exclude the ## Context part from instructions
        if prompt_name in self.CACHEABLE_CONTEXT_NODES and context_section:
            # Don't include Context section in instructions block since it'll be in its own block
            instructions = instructions.strip()
        else:
            # For regular nodes, include everything before ## Context
            instructions = instructions.strip()
        
        if instructions and len(instructions) > 1000:  # ~250 tokens minimum
            cache_blocks.append({
                "text": instructions,
                "cache_control": {"type": "ephemeral"}
            })
        
        # Special handling for nodes with cacheable context
        # Only discovery and component_browsing have static content in context
        if prompt_name in self.CACHEABLE_CONTEXT_NODES:
            cache_blocks.extend(
                self._build_context_cache_blocks(
                    prompt_name, 
                    static_context_values or {}
                )
            )
        
        # Return the full template for dynamic formatting
        # The caller will format this with ALL variables (cached and dynamic)
        # Anthropic will recognize duplicated content and use the cache
        return cache_blocks, prompt_template
    
    def _build_context_cache_blocks(
        self,
        prompt_name: str,
        static_values: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """Build cache blocks for cacheable context sections.
        
        Only used for discovery and component_browsing nodes which have
        large static documentation in their context sections.
        """
        blocks = []
        cacheable_vars = self.CACHEABLE_CONTEXT_NODES.get(prompt_name, [])
        
        # Build the Context section header and static parts as a separate block
        if prompt_name == "discovery":
            # For discovery node, always build the Context section
            # Even if empty, the structure needs to be there
            discovery_content = static_values.get("discovery_context", "")
            
            # Always create the context block, even if content is small/empty
            # The LLM needs to see the <existing_workflows> tags to understand no workflows exist
            context_block = f"""## Context

<existing_workflows>
{discovery_content if discovery_content else ""}
</existing_workflows>"""
            
            # Only cache if substantial, but always include the block
            if discovery_content and len(discovery_content) > 1000:
                blocks.append({
                    "text": context_block,
                    "cache_control": {"type": "ephemeral"}
                })
            else:
                # For small/empty content, include without caching
                # This ensures the structure is always present
                blocks.append({
                    "text": context_block,
                    "cache_control": None  # No caching for small content
                })
        
        elif prompt_name == "component_browsing":
            # For component_browsing, build cacheable parts of Context section
            context_parts = ["## Context"]
            
            if "nodes_context" in static_values:
                nodes_content = static_values["nodes_context"]
                if nodes_content and len(nodes_content) > 1000:
                    context_parts.append(f"""
<available_nodes>
{nodes_content}
</available_nodes>""")
            
            if "workflows_context" in static_values:
                workflows_content = static_values["workflows_context"]
                if workflows_content and len(workflows_content) > 1000:
                    context_parts.append(f"""
<available_workflows>
{workflows_content}
</available_workflows>""")
            
            # Only create block if we have substantial content
            if len(context_parts) > 1:  # More than just the header
                context_block = "\n".join(context_parts)
                blocks.append({
                    "text": context_block,
                    "cache_control": {"type": "ephemeral"}
                })
        
        return blocks


def build_cached_prompt(
    prompt_name: str,
    all_variables: Dict[str, str],
    cacheable_variables: Optional[Dict[str, str]] = None
) -> Tuple[List[Dict[str, Any]], str]:
    """Convenience function to build cached prompt with proper structure.
    
    This function ensures that:
    1. Prompt templates from .md files are always used
    2. Instructions are cached
    3. Context is handled appropriately (cached only for specific nodes)
    
    Args:
        prompt_name: Name of prompt template (e.g., "discovery", "requirements_analysis")
        all_variables: All variables for formatting the template (cached + dynamic)
        cacheable_variables: Subset of variables that should be cached
            - Only used for discovery and component_browsing nodes
            - For discovery: {"discovery_context": "..."}
            - For component_browsing: {"nodes_context": "...", "workflows_context": "..."}
            - For all others: None or empty dict
    
    Returns:
        (cache_blocks, formatted_dynamic_prompt)
        - cache_blocks: List of cache blocks for Anthropic API
        - formatted_dynamic_prompt: Dynamic content only (when blocks exist) or full prompt
    
    Example:
        # For discovery node (has cacheable context)
        cache_blocks, prompt = build_cached_prompt(
            "discovery",
            all_variables={"discovery_context": "...", "user_input": "..."},
            cacheable_variables={"discovery_context": "..."}
        )
        
        # For requirements node (no cacheable context)
        cache_blocks, prompt = build_cached_prompt(
            "requirements_analysis",
            all_variables={"input_text": "..."},
            cacheable_variables=None  # Context is all dynamic
        )
    """
    builder = PromptCacheBuilder()
    cache_blocks, template = builder.build_cache_blocks(
        prompt_name,
        cacheable_variables
    )
    
    # Extract just the dynamic part for the prompt when caching
    if cache_blocks and "## Context" in template:
        # Special handling for nodes with cacheable context
        if prompt_name in PromptCacheBuilder.CACHEABLE_CONTEXT_NODES:
            # For discovery and component_browsing, we need to extract only the truly dynamic parts
            # The cacheable parts of Context are already in cache blocks
            formatted_template = format_prompt(template, all_variables)
            
            # For discovery: only user_input is dynamic
            if prompt_name == "discovery":
                # Find the ACTUAL user_input section in the Context, not the reference in instructions
                # Look for "## Inputs" section which contains the actual user request
                if "## Inputs" in formatted_template:
                    start = formatted_template.index("## Inputs")
                    dynamic_section = formatted_template[start:]
                    formatted_prompt = dynamic_section
                elif "<user_request>" in formatted_template:
                    # Find the LAST occurrence (in Context, not in instructions)
                    # The instructions say "see <user_request>" but we want the actual one
                    start = formatted_template.rfind("<user_request>")
                    if start > 0:
                        # Back up to find the section header
                        inputs_marker = formatted_template.rfind("## Inputs", 0, start)
                        if inputs_marker > 0:
                            formatted_prompt = formatted_template[inputs_marker:]
                        else:
                            formatted_prompt = formatted_template[start:]
                    else:
                        formatted_prompt = f"## Inputs\n\n<user_request>\n{all_variables.get('user_input', '')}\n</user_request>"
                else:
                    # Fallback if structure is different
                    formatted_prompt = f"## Inputs\n\n<user_request>\n{all_variables.get('user_input', '')}\n</user_request>"
            
            # For component_browsing: user_input and requirements are dynamic
            elif prompt_name == "component_browsing":
                # Extract the Inputs section which contains user_input and requirements
                formatted_prompt = f"""## Inputs

<user_request>
{all_variables.get('user_input', '')}
</user_request>

<extracted_requirements>
{all_variables.get('requirements', '')}
</extracted_requirements>"""
            else:
                # Should not reach here, but fallback to Context section
                context_start = template.index("## Context")
                dynamic_section = template[context_start:]
                formatted_prompt = format_prompt(dynamic_section, all_variables)
        else:
            # For regular nodes, only send the Context section as the prompt
            # The instructions are already in the cache blocks
            context_start = template.index("## Context")
            dynamic_section = template[context_start:]
            formatted_prompt = format_prompt(dynamic_section, all_variables)
    else:
        # No cache blocks means no caching - return full formatted template
        # This maintains backward compatibility when caching is disabled
        formatted_prompt = format_prompt(template, all_variables)
    
    return cache_blocks, formatted_prompt