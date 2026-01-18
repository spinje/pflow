> **HISTORICAL DOCUMENT**: Obsolete after Task 95 (llm library integration, 2025-12-19).
>
> This document describes Anthropic-specific prompt caching via `cache_blocks` parameter.
> The `llm` library now abstracts provider-specific caching. While caching may still occur
> at the provider level, pflow no longer exposes explicit cache control.
>
> **Status**: Superseded by llm library integration.

---

# Prompt Caching Architecture

## Overview

The pflow planner uses a sophisticated prompt caching system that respects the structure of prompt templates while maximizing cache reuse. This architecture enables 90%+ cost savings on subsequent planner runs when the `--cache-planner` flag is used.

## Core Principles

1. **All nodes MUST use prompt templates from .md files** - No inline prompt construction
2. **Instructions are always cacheable** - Everything before `## Context` section
3. **Context sections are usually dynamic** - User input and generated content
4. **Two special nodes have cacheable context**:
   - `discovery.md`: workflow descriptions are cacheable
   - `component_browsing.md`: node and workflow documentation are cacheable

## Architecture Components

### 1. Prompt Cache Helper (`src/pflow/planning/utils/prompt_cache_helper.py`)

The central component that intelligently builds cache blocks from prompt templates:

```python
# Basic usage for nodes with dynamic context only
cache_blocks, formatted_prompt = build_cached_prompt(
    "requirements_analysis",
    all_variables={"input_text": user_input},
    cacheable_variables=None  # No cacheable context
)

# Special usage for discovery/component_browsing with cacheable context
cache_blocks, formatted_prompt = build_cached_prompt(
    "discovery",
    all_variables={"discovery_context": context, "user_input": input},
    cacheable_variables={"discovery_context": context}  # This goes in cache
)
```

### 2. Prompt Structure

```
┌─────────────────────────┐
│  Instructions           │ ← Always cached (Block 1)
│  (before ## Context)    │   ~1000-3000 tokens per node
├─────────────────────────┤
│  ## Context             │
│                         │
│  Standard nodes:        │ ← Never cached (all dynamic)
│  - user input           │
│  - generated content    │
│                         │
│  Discovery node:        │
│  - discovery_context    │ ← Cached (Block 2) ~5000 tokens
│  - user_input          │ ← Not cached
│                         │
│  Component browsing:    │
│  - nodes_context       │ ← Cached (Block 2) ~10000 tokens
│  - workflows_context   │ ← Cached (Block 3) ~5000 tokens
│  - user_input          │ ← Not cached
│  - requirements        │ ← Not cached
└─────────────────────────┘
```

## Node Caching Behavior

| Node | Instructions Cached | Context Cached | Total Cache Size |
|------|-------------------|----------------|------------------|
| WorkflowDiscoveryNode | ✅ (~2000 tokens) | ✅ discovery_context (~5000 tokens) | ~7000 tokens |
| ComponentBrowsingNode | ✅ (~3000 tokens) | ✅ nodes + workflows (~15000 tokens) | ~18000 tokens |
| RequirementsAnalysisNode | ✅ (~1500 tokens) | ❌ | ~1500 tokens |
| ParameterDiscoveryNode | ✅ (~2000 tokens) | ❌ | ~2000 tokens |
| ParameterMappingNode | ✅ (~1500 tokens) | ❌ | ~1500 tokens |
| MetadataGenerationNode | ✅ (~1000 tokens) | ❌ | ~1000 tokens |
| PlanningNode* | ✅ (always caches) | ✅ (multi-block) | ~3000 tokens |
| WorkflowGeneratorNode* | ✅ (always caches) | ✅ (multi-block) | ~3000 tokens |

*PlanningNode and WorkflowGeneratorNode always cache for intra-session benefits (Task 52)

## Implementation Pattern

Every node follows this consistent pattern:

```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    from pflow.planning.prompts.loader import format_prompt, load_prompt
    from pflow.planning.utils.prompt_cache_helper import build_cached_prompt

    # Check if caching is enabled
    cache_planner = prep_res.get("cache_planner", False)
    model = llm.get_model(prep_res["model_name"])

    # Prepare all variables for the prompt template
    all_vars = {
        "var1": prep_res["var1"],
        "var2": prep_res["var2"],
        # ... all variables the prompt needs
    }

    if cache_planner:
        # Build cache blocks (instructions always cached, context sometimes)
        cache_blocks, formatted_prompt = build_cached_prompt(
            "prompt_name",  # Name of .md file
            all_variables=all_vars,
            cacheable_variables={...}  # Only for discovery/component_browsing
        )

        response = model.prompt(
            formatted_prompt,
            schema=ResponseSchema,
            temperature=prep_res["temperature"],
            cache_blocks=cache_blocks
        )
    else:
        # Traditional approach - no caching
        prompt_template = load_prompt("prompt_name")
        prompt = format_prompt(prompt_template, all_vars)

        response = model.prompt(
            prompt,
            schema=ResponseSchema,
            temperature=prep_res["temperature"]
        )
```

## Usage

### Enable Cross-Session Caching

```bash
# First run - creates cache blocks
uv run pflow --cache-planner "create workflow to analyze GitHub issues"
# Cost: ~$0.06 (includes 25% cache creation premium)

# Subsequent runs within 5 minutes - reuses cache
uv run pflow --cache-planner "fetch slack messages and summarize"
# Cost: ~$0.006 (90% discount on cached content)
```

### Normal Operation (No Caching)

```bash
# Standard usage without cross-session caching
uv run pflow "create workflow to analyze data"
# Cost: ~$0.05 (full price every time)
```

## Cache Metrics

Expected cache performance with the new architecture:

- **Total cached tokens**: ~33,000+ (vs 594 before fix)
- **Cache hit rate**: 70-90% of prompt content
- **Cost reduction**: 90%+ on subsequent runs
- **Cache TTL**: 5 minutes (Anthropic's ephemeral cache)

### Breakdown by Component

1. **Instructions (all nodes)**: ~12,000 tokens total
2. **Discovery context**: ~5,000 tokens
3. **Node documentation**: ~10,000 tokens
4. **Workflow documentation**: ~5,000 tokens
5. **Planning/Generator blocks**: ~1,000 tokens

## Key Design Decisions

### 1. Respect Prompt Template Structure

All nodes must use the `.md` prompt templates. This ensures:
- Consistency across the codebase
- Prompts remain maintainable
- Clear separation of concerns

### 2. Smart Context Handling

Only `discovery` and `component_browsing` have cacheable context because they contain large static documentation. Other nodes have user-specific context that changes every request.

### 3. Backward Compatibility

The system works normally without the `--cache-planner` flag, ensuring existing workflows continue to function.

### 4. Preserve Special Behaviors

PlanningNode and WorkflowGeneratorNode maintain their multi-block caching for intra-session benefits (from Task 52), regardless of the flag.

## Troubleshooting

### Cache Not Being Used

1. Check that `--cache-planner` flag is set
2. Verify prompt templates are being loaded (not inline prompts)
3. Ensure content is >1000 characters for caching

### Low Cache Hit Rate

1. Verify static content is in cache blocks
2. Check that dynamic content isn't accidentally cached
3. Review cache block sizes in logs

### Testing Cache Effectiveness

```bash
# Run with trace to see cache metrics
uv run pflow --cache-planner --trace-planner --output-format json "your request"

# Look for in the output:
# - cache_creation_tokens: X (first run)
# - cache_read_tokens: Y (subsequent runs)
```

## Migration Guide

When adding new nodes:

1. Create prompt template in `src/pflow/planning/prompts/`
2. Use `build_cached_prompt()` in the node's `exec()` method
3. Determine if any context variables are cacheable (usually not)
4. Test both cached and non-cached modes

## Future Improvements

1. **Persistent caching**: Save cache blocks to disk for longer reuse
2. **Cache warming**: Pre-populate cache on startup
3. **Dynamic threshold adjustment**: Tune cache size thresholds based on usage
4. **Cache metrics dashboard**: Visual display of cache performance

## References

- Anthropic Prompt Caching: https://docs.anthropic.com/claude/docs/prompt-caching
- Task 52 Implementation: Multi-block caching for Planning/Generator nodes
- Original Issue: Cross-session caching feature request
