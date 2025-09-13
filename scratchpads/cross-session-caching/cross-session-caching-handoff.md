# Cross-Session Caching Implementation Handoff

**⚠️ CRITICAL**: Do not begin implementing until you've read this entire document and confirmed you understand the current broken state and the subtle caching mechanisms. Say "Ready to begin" when you're done reading.

## 🔥 The Current Crisis

The planner is **COMPLETELY BROKEN** as of Task 52's multi-block caching implementation. Here's what happened:

1. Task 52 successfully implemented multi-block caching between PlanningNode → WorkflowGeneratorNode
2. To ensure caching worked, they made `cache_blocks` a REQUIRED parameter in `AnthropicLLMModel.prompt()`
3. They forgot that 6 other planner nodes also call this method without cache blocks
4. Result: ALL planner commands fail immediately with `ValueError: cache_blocks parameter is required`

**The broken code**: `/Users/andfal/projects/pflow-feat-planner-plan-requirements/src/pflow/planning/utils/anthropic_llm_model.py` lines 74-79

## 🎯 What You're Actually Building

Two things that seem separate but are deeply connected:

1. **Immediate Fix**: Make cache_blocks optional again (unblock the planner)
2. **Cross-Session Caching**: Add `--cache-planner` flag that caches static content ACROSS different user queries

The beauty is that fixing #1 sets up the infrastructure for #2 perfectly.

## 🧠 Critical Knowledge Not in Other Docs

### The Tool-Choice Hack (DO NOT BREAK THIS)

Task 52 discovered that Anthropic creates **separate cache namespaces** based on tool definitions. To share cache between PlanningNode (text output) and WorkflowGeneratorNode (structured output), they use this clever hack:

```python
# BOTH nodes define the same FlowIR tool
# PlanningNode: force_text_output=True → tool_choice='none' → gets text
# WorkflowGeneratorNode: force_text_output=False → tool_choice='tool' → gets structured
# Same tool definition = same cache namespace = cache sharing works!
```

This is in `anthropic_llm_model.py` lines 127-135. If you change this, you break the ~$0.01 per workflow savings from Task 52.

### AnthropicStructuredClient Already Handles None

**DO NOT** create new methods in `AnthropicStructuredClient`. Both `generate_with_schema` and `generate_with_schema_text_mode` already have `cache_blocks: Optional[...] = None` as parameters. When None, they simply don't add a system parameter. Perfect as-is!

### The Multi-Block Architecture from Task 52

Currently working perfectly in PlanningNode/WorkflowGeneratorNode:

```python
# Stored in shared store (these are lists of dict blocks, not strings!)
shared["planner_base_blocks"] = [A, B]  # Created by PlanningNode
shared["planner_extended_blocks"] = [A, B, C]  # C = plan output
shared["planner_accumulated_blocks"] = [A, B, C, D, E]  # D = workflow, E = errors
```

The old string-based keys (`planner_base_context`, etc.) were completely removed. No backward compatibility exists or is needed.

### Where Cache Blocks Come From

`PlannerContextBuilder` in `/Users/andfal/projects/pflow-feat-planner-plan-requirements/src/pflow/planning/context_blocks.py` has these methods:
- `build_base_blocks()` - Creates [A, B, C] blocks
- `append_planning_block()` - Adds plan output
- `append_workflow_block()` - Adds generated workflow
- `append_errors_block()` - Adds validation errors

These return **lists of dicts** with `"text"` and `"cache_control"` keys.

## 🔍 Hidden Gotchas I Discovered

### 1. Token Counts Are Misleading
The user said "I will fix the prompts to be big enough" - this means don't worry about the 1024 token minimum. Anthropic gracefully handles too-small blocks by just not caching them. No errors.

### 2. Model Detection Is Hardcoded
The monkey-patching in `install_anthropic_model()` only applies to models containing "claude-sonnet-4". Other models use the regular llm library and will never hit the AnthropicLLMModel code.

### 3. Shared Store Creation Timing
The shared store is created ONCE at the start of planner execution in `_setup_planner_execution()`. Adding the flag there makes it available to ALL nodes automatically through their `prep()` methods.

### 4. Cache TTL Is Perfect for Dev
Anthropic's 5-minute cache TTL seems limiting but is actually perfect - developers iterate rapidly, running the planner multiple times within minutes. Each run benefits from the previous cache.

## 📊 The Real Impact

Here's what the user hasn't fully grasped yet:

**Current (broken)**: Can't run planner at all
**After immediate fix**: ~$0.05 per planner run
**With --cache-planner (first run)**: ~$0.06 (creates cache + 25% premium)
**With --cache-planner (subsequent runs)**: ~$0.005 (90% cached!)

For a developer iterating on workflows, this is 10x cost reduction after the first run.

## ⚠️ What Could Go Wrong

### If You Change the Tool-Choice Hack
- Cache sharing between PlanningNode/WorkflowGeneratorNode breaks
- Retries become expensive again
- Task 52's work is undone

### If You Add Backward Compatibility
- The code becomes unnecessarily complex
- There are NO consumers of the old string-based context
- The user explicitly said "clean break"

### If You Modify AnthropicStructuredClient
- You're adding complexity where none is needed
- It already handles None perfectly
- You risk breaking the existing working implementation

## 🔗 Critical Files and Their Roles

- **The broken line**: `src/pflow/planning/utils/anthropic_llm_model.py:74-79`
- **Cache block creation**: `src/pflow/planning/context_blocks.py` (already perfect)
- **All 8 LLM nodes**: `src/pflow/planning/nodes.py` (see lines in other docs)
- **CLI entry**: `src/pflow/cli/main.py:760` (run command)
- **Shared store creation**: `src/pflow/cli/main.py:1663` (_setup_planner_execution)
- **Monkey-patching**: `src/pflow/planning/utils/anthropic_llm_model.py:216-235`

## 🎪 The Bigger Picture

This isn't just a bug fix. Cross-session caching transforms the planner from an expensive one-shot tool to a rapid iteration development environment. The infrastructure from Task 52 (multi-block caching) was the hard part. This is just opening it up to more use cases.

## ✅ Quick Validation Tests

After Phase 1 (immediate fix):
```bash
uv run pflow "create a workflow"  # Should work (currently broken)
```

After Phase 2 (CLI flag):
```bash
uv run pflow --cache-planner "test"  # Flag should be in shared["cache_planner"]
```

After Phase 4 (full implementation):
```bash
# Run twice with flag, check logs for "cache_read_input_tokens" > 0 on second run
```

## 🚨 Final Critical Warning

The immediate fix is trivial but URGENT. Every minute the planner is broken is a minute users can't use pflow. Fix `anthropic_llm_model.py` FIRST, test it works, THEN do everything else.

The rest of the implementation is straightforward - the patterns are established, the infrastructure exists, and the spec/plan documents are comprehensive. But without that first fix, nothing else matters.

---

**Remember**: Do not begin implementing until you've read this entire document. Confirm you understand:
1. The planner is currently broken
2. The tool-choice hack must be preserved
3. AnthropicStructuredClient needs no changes
4. The immediate fix is urgent but simple

Say "Ready to begin fixing the broken planner" when you're ready.