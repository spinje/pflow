# Anthropic Prompt Caching Implementation - Critical Handoff

**Date**: January 12, 2025  
**Context**: Task 52 - Anthropic SDK integration with prompt caching for planner

## 🚨 READ THIS FIRST - DO NOT START IMPLEMENTING

This handoff contains critical discoveries about Anthropic's caching behavior that took hours to debug. Read everything before making any changes.

## 🎯 What We Were Trying to Achieve

Enable prompt caching between PlanningNode and WorkflowGeneratorNode to save costs. The workflow system overview (~7250 chars, ~2000 tokens) is identical for both nodes and should be cached and reused.

## 💥 The Core Discovery That Changes Everything

**Anthropic's cache CANNOT be shared between API calls with different tool configurations.**

This single fact drove the entire implementation:
- Calls WITHOUT `tools` parameter → Cache key A
- Calls WITH `tools` parameter → Cache key B
- These caches are COMPLETELY SEPARATE

Even if everything else is identical (system prompt, user message, model), the mere presence/absence of tools creates different cache namespaces.

## 🔧 The Solution We Implemented

### The Hack That Works

Both nodes now use the SAME tool definition (FlowIR) but with different `tool_choice`:
- **PlanningNode**: `tools=[FlowIR], tool_choice={'type': 'none'}` → Gets text output
- **WorkflowGeneratorNode**: `tools=[FlowIR], tool_choice={'type': 'tool'}` → Gets structured output

### Key Files Modified

1. **`src/pflow/planning/utils/anthropic_llm_model.py`** (lines 105-164)
   - Both text and structured paths now use `generate_with_schema_text_mode()`
   - Text path imports FlowIR and passes `force_text_output=True`
   - This ensures both nodes have identical tool definitions

2. **`src/pflow/planning/utils/anthropic_structured_client.py`** (lines 67-176)
   - Added `generate_with_schema_text_mode()` method
   - Handles both text and structured output with same tool definition
   - `force_text_output` parameter controls `tool_choice`

3. **`src/pflow/core/metrics.py`** (lines 107-125)
   - Fixed cost calculation bug - `input_tokens` from Anthropic ALREADY excludes cache tokens
   - Was double-subtracting cache tokens, making costs negative

## 📊 What's Actually Working

Current behavior with the fix:
```
cache_creation_tokens: 2914  (created by PlanningNode)
cache_read_tokens: 2914      (read by WorkflowGeneratorNode)
```

This is WORKING but the cache is smaller than expected (2914 vs 5066 tokens we saw earlier).

### Cost Impact
- Cache creation: 2914 × $3.75/M = $0.0109 (25% premium)
- Cache read: 2914 × $0.30/M = $0.0009 (90% discount)
- Savings per run: ~$0.0078

## ⚠️ Critical Implementation Details

### 1. Workflow Overview Extraction

The regex pattern is VERY specific:
```python
workflow_pattern = r"(# Workflow System Overview.*?)(?=\n## (?:Requirements Analysis|User Request|Available|Planning Instructions|Workflow Generation)|\Z)"
```

Note: The overview starts with SINGLE `#` not double `##`. This took forever to debug.

### 2. Cache Placement

The cached content MUST be in the `system` parameter, not in message content blocks:
- System parameter → Can be cached
- User message content blocks → Different for each node (includes plan output for generator)

### 3. Model Configuration

Both clients use `claude-sonnet-4-20250514` but through different wrappers:
- `AnthropicLLMModel` wraps for llm library compatibility
- `AnthropicStructuredClient` handles direct SDK calls

## 🐛 Subtle Bugs We Fixed Along the Way

1. **Double subtraction in cost calculation**: `input_tokens` already excludes cache tokens per API spec
2. **Wrong regex for workflow overview**: Was looking for `##` instead of `#`
3. **Cache content mismatch**: Was including different content in cache blocks
4. **Missing model parameter**: Text path wasn't passing model to API

## 🤔 Unsolved Mysteries

### Why is the cache only 2914 tokens?

Expected ~5066 based on workflow overview size (~7250 chars). Possible reasons:
1. Anthropic might be compressing or truncating
2. Some content might not meet minimum cache requirements
3. Token counting might be different than expected

### Why do we see creation but not reads sometimes?

Cache persists for 5 minutes. If you run multiple times quickly:
- First run: Shows creation
- Second run (within 5 min): Shows reads only
- After 5 min: Shows creation again

## 🚀 Future Improvements to Consider

1. **Pre-cache warming**: Make a dummy call at startup to create cache
2. **Cache metrics tracking**: Add detailed logging of what's being cached
3. **Extend to other nodes**: RequirementsAnalysisNode, ComponentBrowsingNode could also benefit
4. **1-hour cache**: Use TTL parameter for longer cache persistence

## 🔗 Essential Context Links

### Documentation
- `scratchpads/anthropic-sdk-implementation-plan.md` - Original implementation plan
- `scratchpads/task-52-complete-braindump.md` - Full journey and discoveries
- `.taskmaster/tasks/task_52/implementation/progress-log.md` - Detailed progress log

### Anthropic Docs (from conversation)
- Cache requires minimum 1024 tokens for Sonnet models
- `tool_choice` changes only affect message blocks, not system cache
- Cache creation costs 25% more, reads cost 90% less

## ❌ What NOT to Do

1. **Don't remove the FlowIR tool from PlanningNode** - It breaks cache sharing
2. **Don't change tool definitions between nodes** - Must be identical
3. **Don't put cached content in user messages** - Use system parameter
4. **Don't trust `tokens_input` to include cache tokens** - It doesn't

## 🎭 The Philosophical Insight

We're essentially tricking Anthropic's API into thinking both nodes are making the same type of call by giving them identical tool configurations, then using `tool_choice` to control behavior. It's a hack, but it works.

The deeper lesson: Cache keys in LLM APIs are often more restrictive than documented. Test empirically.

## 🔍 How to Verify It's Working

Run: `uv run pflow --trace-planner --output-format json "create a test workflow"`

Look for in metrics:
- `cache_creation_tokens` > 0 (first node creates)
- `cache_read_tokens` > 0 (second node reads)
- Both should be same value (~2914 currently)

## 🧠 Questions for Investigation

1. Why is cached content smaller than expected?
2. Can we cache more of the context (requirements, components)?
3. Would separating calls (pre-cache, then actual) be more reliable?
4. Is the 5-minute TTL sufficient for typical usage patterns?

## 📝 Final Note to Next Agent

The implementation works but feels fragile. The core issue is that we're working around an API limitation rather than with it. If Anthropic changes how cache keys are computed, this could break.

The code is currently committed but not thoroughly tested in production. Test with real workflows before considering this complete.

**DO NOT begin implementing changes yet. First acknowledge you've read and understood this handoff.**