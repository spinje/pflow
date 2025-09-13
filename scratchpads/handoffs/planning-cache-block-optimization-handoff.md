# Handoff: Optimizing Cache Block Structure for PlanningNode/WorkflowGeneratorNode

## 🎯 Critical Context You Need to Know

You're about to optimize the cache block structure for PlanningNode and WorkflowGeneratorNode. These nodes are **SPECIAL** - they use a completely different caching architecture from the other 6 nodes we just fixed. Here's what you absolutely must understand:

## 🔴 The Discovery That Triggered This

While analyzing the trace file `/Users/andfal/.pflow/debug/planner-trace-20250913-174542.json`, we discovered that Block 1 contains:
- **Static introduction text** (~250 chars): "You are a specialized workflow planner..."
- **Dynamic user request** (~50-200 chars): The actual user's request

This is inefficient! The static introduction should be cached with the other static content in Block 2 (Workflow System Overview), not mixed with dynamic content.

## 🏗️ Current Architecture (From Task 52)

### How PlanningNode/WorkflowGeneratorNode Work Differently

Unlike the other 6 nodes we fixed today that use prompt templates directly, these two nodes have a **multi-block caching architecture**:

1. **Cache Blocks (System Context)**: 3 blocks passed as `cache_blocks` parameter
   - Block 1: Introduction + User Request (MIXED static/dynamic - THE PROBLEM)
   - Block 2: Workflow System Overview (static, ~8254 chars)
   - Block 3: Requirements, Components, Parameters (dynamic, ~800 chars)

2. **Instructions (User Message)**: Loaded from `planning_instructions.md` or `workflow_generator_instructions.md`
   - NOT cached - goes in the `prompt` parameter
   - References "context provided above" because Anthropic shows system messages before user messages

### The Tool-Choice Hack

These nodes use a special "tool-choice hack" for cache sharing:
- Both use FlowIR tool definition
- PlanningNode: `tool_choice: none` (gets text output)
- WorkflowGeneratorNode: `tool_choice: tool` (gets structured output)
- This enables them to share the same cache namespace

## 📁 Key Files and Their Roles

### Files You'll Need to Modify

1. **`src/pflow/planning/prompts/workflow_system_overview.md`** (line 1)
   - Currently starts with "# Workflow System Overview"
   - Should add the introduction text at the very beginning

2. **`src/pflow/planning/context_blocks.py`**
   - Line 256-259: `_build_introduction_section()` - DELETE this method
   - Line 88-90: Removes the introduction from Block A
   - Line 86-97: Simplify Block A construction to only include user request

### Files for Reference (Don't Modify)

3. **`src/pflow/planning/nodes.py`** (lines 1055-1127, 1735-1831)
   - PlanningNode and WorkflowGeneratorNode implementations
   - They call `PlannerContextBuilder.build_base_blocks()`
   - DON'T change these - they'll automatically use the updated blocks

4. **`src/pflow/planning/utils/anthropic_llm_model.py`** (lines 83-161)
   - The `_prompt_with_cache_blocks()` method that handles multi-block caching
   - Shows how cache blocks are passed to Anthropic SDK

## 🎨 The Optimization

### Current Structure (Inefficient)
```
Block 1 (458 chars): [STATIC intro] + [DYNAMIC user request]
Block 2 (8254 chars): [STATIC workflow overview]
Block 3 (798 chars): [DYNAMIC requirements/components]
```

### Optimized Structure (What You're Building)
```
Block 1 (~200 chars): [DYNAMIC user request only]
Block 2 (~8500 chars): [STATIC intro + workflow overview]
Block 3 (798 chars): [DYNAMIC requirements/components]
```

### Why This Matters
- **Cache hit rate**: Block 2 becomes ~8500 chars of pure static content
- **Cost savings**: Reduces cache creation for Block 1 by ~250 chars per request
- **Cleaner separation**: Static vs dynamic content properly isolated

## ⚠️ Critical Warnings

### DO NOT Touch These Things

1. **Don't modify PlanningNode or WorkflowGeneratorNode directly** - They'll automatically use the updated blocks from PlannerContextBuilder

2. **Don't change the prompt template architecture** - PlanningNode/WorkflowGeneratorNode are special and don't use the `prompt_cache_helper.py` we created today

3. **Don't alter the multi-block structure** - Must remain 3 blocks for the context accumulation pattern to work

4. **Don't modify the tool-choice hack** - Both nodes must continue using FlowIR for cache sharing

### Edge Cases to Consider

1. **Empty user request**: The code already handles this (line 271-272 in context_blocks.py)

2. **Block size limits**: Anthropic has a 4-block limit, but we're only using 3

3. **Minimum cache size**: Blocks <1024 tokens (~4000 chars) may not be cached by Anthropic, but Block 2 is already ~8254 chars so it's fine

## 🔍 How to Verify Your Changes

1. **Run a test workflow**:
   ```bash
   uv run pflow --cache-planner "count words in test.txt"
   ```

2. **Check the trace file** (created in `~/.pflow/debug/`):
   - Block 1 should only contain user request
   - Block 2 should start with the introduction
   - All 3 blocks should have `cache_control: {"type": "ephemeral"}`

3. **Run the verification script**:
   ```bash
   uv run python test_cache_verification.py
   ```
   Should show all dynamic content is included

## 🤔 Non-Obvious Insights

1. **Why the introduction was separate**: Probably for modularity during development of Task 52, but now it's causing inefficiency

2. **Why this matters more than it seems**: Every planner invocation pays the cache creation cost for Block 1. Moving 250 static chars out saves money on EVERY request

3. **The context accumulation pattern**: PlanningNode creates blocks, adds its output as Block 4, then WorkflowGeneratorNode uses all 4. Your change won't affect this pattern

4. **Why other nodes are different**: The 6 nodes we fixed today use single-block caching with prompt templates. PlanningNode/WorkflowGeneratorNode are fundamentally different architecturally

## 📊 Expected Impact

- **Cache creation cost**: Reduced by ~62 tokens per request (250 chars / 4)
- **Cache efficiency**: Block 2 increases from 8254 to ~8500 chars of pure static content
- **No functional changes**: Everything works exactly the same, just more efficiently

## 🔗 Related Context

- **Task 52**: Implemented the original multi-block caching for PlanningNode/WorkflowGeneratorNode
- **Today's work**: Fixed prompt template caching for the other 6 nodes (different architecture)
- **Architecture doc**: `/Users/andfal/projects/pflow-feat-planner-plan-requirements/architecture/prompt-caching-architecture.md`

## 💡 Final Thoughts

This is a surgical optimization - you're moving one line of static text from a mixed block to a pure static block. The implementation is simple but the context around WHY and HOW is complex. The multi-block caching architecture from Task 52 is sophisticated and works well - we're just making it slightly more efficient.

Remember: The user noticed this inefficiency by looking at the trace file and asking "why are the first two in separate blocks, they are both static?" - a great observation that led to this optimization opportunity.

---

**DO NOT begin implementing yet** - read this document fully, understand the architecture, and confirm you're ready to make these specific changes to optimize the cache block structure.