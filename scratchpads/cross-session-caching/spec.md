# Cross-Session Planner Caching Specification

**Date**: January 2025
**Purpose**: Enable cross-session caching for planner LLM calls to dramatically reduce costs and latency during development iteration
**Status**: Design Specification

## Executive Summary

Currently, our multi-block caching only works within a single workflow generation session (PlanningNode → WorkflowGeneratorNode). This spec extends caching to work ACROSS different user queries with a `--cache-planner` flag, enabling 90%+ cost savings when iterating on workflows during development.

**Key Insight**: Anthropic's 5-minute cache TTL is perfect for development iteration - developers run the planner multiple times in quick succession, and each run can benefit from the previous run's cache.

## Problem Statement

### Immediate Issue
- `cache_blocks` parameter is currently REQUIRED in AnthropicLLMModel
- This breaks all nodes that don't provide cache blocks (WorkflowDiscoveryNode, ComponentBrowsingNode, etc.)
- Planner is completely broken

### Opportunity
- Each planner node loads massive static content (workflow descriptions, node documentation, rules)
- This static content is identical across different user queries
- Currently, we pay to process this content on EVERY planner run
- With caching, we could pay once and reuse for 5 minutes

## Architecture Design

### Two Types of Caching

#### 1. Intra-Session Caching (Current)
- **Scope**: Within single workflow generation
- **Nodes**: PlanningNode → WorkflowGeneratorNode
- **Benefit**: 87% cost savings on retries
- **When**: ALWAYS enabled (critical for retry efficiency)

#### 2. Inter-Session Caching (New)
- **Scope**: Across different user queries
- **Nodes**: ALL planner nodes
- **Benefit**: 90%+ cost savings on subsequent runs
- **When**: Only with `--cache-planner` flag

### Content Classification

Each node's content can be classified as:

| Node | Static Content (Cacheable) | Dynamic Content (Not Cacheable) | Est. Cache Size |
|------|---------------------------|----------------------------------|-----------------|
| **WorkflowDiscoveryNode** | All workflow metadata/descriptions | User query, stdin_data | ~5000 tokens |
| **ComponentBrowsingNode** | All node/workflow documentation | User requirements, selected components | ~10000+ tokens |
| **RequirementsAnalysisNode** | Analysis instructions/rules | User input text | ~2000 tokens |
| **ParameterDiscoveryNode** | Parameter extraction rules | User query, component selection | ~1500 tokens |
| **PlanningNode** | Workflow System Overview | User request, requirements, components | ~2914 tokens |
| **WorkflowGeneratorNode** | Workflow System Overview | Plan output, previous attempts | ~2914 tokens |
| **MetadataGenerationNode** | Metadata generation rules | Generated workflow | ~1000 tokens |

### Implementation Strategy

```python
# 1. Make cache_blocks OPTIONAL in AnthropicLLMModel
class AnthropicLLMModel:
    def prompt(self, prompt, cache_blocks=None, **kwargs):
        if cache_blocks is not None:
            # Use provided blocks (optimized path)
            return self._prompt_with_cache_blocks(...)
        else:
            # Fall back to no caching or basic extraction
            return self._prompt_without_cache(...)

# 2. Each node decides whether to cache
class SomePlannerNode(Node):
    def exec(self, prep_res):
        # Check if caching is enabled
        cache_planner = prep_res.get("cache_planner", False)

        # Special nodes ALWAYS cache (intra-session benefit)
        force_cache = self.name in ["planning", "workflow-generator"]

        if cache_planner or force_cache:
            # Build cache blocks
            blocks = self._build_cache_blocks(prep_res)
            response = model.prompt(
                dynamic_content,  # User message
                cache_blocks=blocks,  # System blocks
                temperature=...
            )
        else:
            # No caching - traditional approach
            full_prompt = static_content + dynamic_content
            response = model.prompt(full_prompt, temperature=...)
```

## Implementation Phases

### Phase 1: Fix Immediate Issue (30 min)
1. Make `cache_blocks` optional in AnthropicLLMModel
2. Add fallback path for when cache_blocks not provided
3. Verify planner works again

### Phase 2: Add CLI Flag (1 hour)
1. Add `--cache-planner` flag to CLI
2. Propagate flag through shared store as `cache_planner: bool`
3. Update CLI help text

### Phase 3: Update Critical Nodes (2 hours)
1. Keep PlanningNode and WorkflowGeneratorNode always using cache blocks
2. Add cache block building to WorkflowDiscoveryNode
3. Add cache block building to ComponentBrowsingNode
4. Test cross-session caching works

### Phase 4: Update Remaining Nodes (2 hours)
1. RequirementsAnalysisNode
2. ParameterDiscoveryNode
3. MetadataGenerationNode
4. Any other LLM-calling nodes

## Node Implementation Pattern

Each node should follow this pattern:

```python
def _build_cache_blocks(self, prep_res: dict) -> list[dict]:
    """Build cache blocks for cross-session caching.

    Returns blocks with static content that doesn't change between queries.
    Dynamic content (user input) will be passed separately.
    """
    blocks = []

    # Add static instructions/rules
    static_instructions = load_prompt("node_instructions")
    blocks.append({
        "text": static_instructions,
        "cache_control": {"type": "ephemeral"}
    })

    # Add static context (e.g., all workflow descriptions)
    if hasattr(self, '_get_static_context'):
        static_context = self._get_static_context()
        if len(static_context) > 1024:  # Minimum for caching
            blocks.append({
                "text": static_context,
                "cache_control": {"type": "ephemeral"}
            })

    return blocks

def _get_dynamic_content(self, prep_res: dict) -> str:
    """Extract dynamic content that changes per query.

    This includes user input, selected components, etc.
    This content goes in the user message, not cache blocks.
    """
    parts = []

    # Add user-specific content
    if prep_res.get("user_input"):
        parts.append(f"User Request: {prep_res['user_input']}")

    # Add any dynamic context
    if prep_res.get("selected_components"):
        parts.append(f"Selected: {prep_res['selected_components']}")

    return "\n\n".join(parts)
```

## Cache Size Optimization

Some nodes may need content adjustment to reach the 1024 token minimum for caching:

1. **Small prompts**: Combine multiple static sections
2. **Padding**: Add detailed examples or additional instructions
3. **Consolidation**: Group related static content together

## User Experience

### Without Flag (Default)
```bash
pflow "create a workflow to analyze GitHub issues"
# Normal execution, no cross-session caching
# PlanningNode ↔ WorkflowGeneratorNode still cache share
```

### With Flag (Development Mode)
```bash
pflow --cache-planner "create a workflow to analyze GitHub issues"
# First run: Creates cache for all static content
# Cost: ~$0.05 (full price + 25% cache creation)

pflow --cache-planner "fetch slack messages and summarize"
# Second run: Reuses cache from first run
# Cost: ~$0.005 (90% discount on cached content)

pflow --cache-planner "deploy to kubernetes"
# Third run: Still using cache
# Cost: ~$0.005 (cache still warm)
```

### Benefits
- **Development iteration**: Near-instant subsequent runs
- **Cost savings**: 90%+ reduction after first run
- **Better UX**: Rapid feedback when testing different queries
- **Debugging**: Faster iteration when troubleshooting

## Error Handling

1. **Non-Anthropic models**: Gracefully fall back to no caching
2. **Cache creation failure**: Continue without caching
3. **Token limit**: Only cache blocks >1024 tokens
4. **Mixed models**: Handle when some nodes use Anthropic, others don't

## Success Metrics

1. **Immediate**: Planner works again (unblocked)
2. **Phase 2**: --cache-planner flag reduces cost by 90%+ on second run
3. **Phase 3**: All nodes support caching when flag is set
4. **Long-term**: Development iteration time reduced by 80%+

## Testing Strategy

### Unit Tests
1. Test cache_blocks optional parameter
2. Test flag propagation
3. Test cache block building per node

### Integration Tests
1. Run planner twice with flag, verify cache metrics
2. Verify different queries share cache
3. Test cache expiration after 5 minutes

### Manual Testing
1. Run planner multiple times with flag
2. Monitor Anthropic dashboard for cache hits
3. Verify cost reduction

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Cache key mismatch | No cache sharing | Ensure static content is byte-identical |
| Dynamic content cached | Wrong results | Strict separation of static/dynamic |
| Non-Anthropic models | Feature doesn't work | Graceful fallback, clear docs |
| Cache too small | No caching benefit | Pad content to >1024 tokens |

## Future Enhancements

1. **Persistent cache**: Save cache blocks to disk for longer reuse
2. **Cache warming**: Pre-populate cache on startup
3. **Selective caching**: Fine-grained control per node
4. **Cache metrics**: Show savings in CLI output
5. **Auto-enable**: Detect rapid iteration and suggest flag

## Implementation Checklist

### Phase 1: Immediate Fix
- [ ] Make cache_blocks optional in AnthropicLLMModel
- [ ] Add _prompt_without_cache() method
- [ ] Test planner works without cache blocks
- [ ] Verify PlanningNode/WorkflowGeneratorNode still cache

### Phase 2: CLI Flag
- [ ] Add --cache-planner flag to CLI
- [ ] Propagate flag to shared store
- [ ] Update help text
- [ ] Add flag to workflow execution context

### Phase 3: Critical Nodes
- [ ] Update WorkflowDiscoveryNode
- [ ] Update ComponentBrowsingNode
- [ ] Test cross-session caching
- [ ] Verify cache metrics

### Phase 4: Remaining Nodes
- [ ] Update RequirementsAnalysisNode
- [ ] Update ParameterDiscoveryNode
- [ ] Update MetadataGenerationNode
- [ ] Final testing

## Conclusion

This feature transforms the planner development experience by making iteration nearly free after the first run. The 5-minute cache TTL aligns perfectly with development workflows where developers run the planner multiple times in succession. By separating static content (cacheable) from dynamic content (not cacheable), we can achieve 90%+ cost savings while maintaining correctness.