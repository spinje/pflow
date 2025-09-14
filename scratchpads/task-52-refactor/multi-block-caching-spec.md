# Multi-Block Caching Implementation Specification

**Date**: January 2025
**Purpose**: Define comprehensive requirements for refactoring Task 52's Anthropic SDK integration to support proper multi-block incremental caching
**Status**: Draft Specification

## Executive Summary

The current implementation only caches the Workflow System Overview (~2914 tokens), missing significant optimization opportunities. This specification defines how to implement proper multi-block caching that can cache up to ~8000 tokens, reducing costs by 87% on retries while maintaining the critical cache-sharing mechanism between PlanningNode and WorkflowGeneratorNode.

**Key Architecture**: This follows PocketFlow's pattern where nodes communicate through a shared store (in-memory dictionary). PlanningNode writes cache blocks to the shared store, WorkflowGeneratorNode reads them, and the accumulation pattern enables efficient retries.

**Critical Understanding (Updated)**: PlanningNode creates blocks [A, B, C] where C is the plan output. WorkflowGeneratorNode reads these three blocks on first attempt, not just two. This ensures the plan is cached and available for the generator.

## Current State Analysis

### What's Working
- Cache sharing between PlanningNode and WorkflowGeneratorNode via tool-choice hack
- ~2914 tokens cached (Workflow System Overview only)
- Cost savings of ~$0.0078 per run on cached content
- Transparent integration with `llm.get_model()` interface

### What's Missing
- Only caching Block A (Workflow Overview), not B/C/D/E
- Context stored as strings in shared store, not structured blocks
- Regex extraction duplicated in 3 places
- Instructions mixed with cached content (should be separate)

### Current Token Distribution
```
Total tokens per workflow: ~8000
- Currently cached: 2914 (36%)
- Currently uncached: 5086 (64%)
  - Base context: ~2000 tokens
  - Planning output: ~1000 tokens
  - Generated workflow: ~2000 tokens
  - Instructions: ~1000 tokens
```

## Requirements

### Functional Requirements

#### FR1: Multi-Block Cache Structure
The system MUST support 5 distinct cache blocks:

**Block A: Workflow System Overview**
- Content: Static workflow rules from `workflow_system_overview.md`
- Size: ~2914 tokens
- Lifetime: Shared across ALL workflows
- Cache TTL: 5 minutes (ephemeral)

**Block B: Base Context**
- Content: User request, requirements, components, planning context, discovered params
- Size: ~2000 tokens
- Lifetime: Shared within a workflow run (both nodes)
- Cache TTL: 5 minutes (ephemeral)

**Block C: Planning Output**
- Content: Markdown plan from PlanningNode
- Size: ~1000 tokens
- Lifetime: Used by WorkflowGeneratorNode
- Cache TTL: 5 minutes (ephemeral)

**Block D: Generated Workflow**
- Content: JSON IR from generation attempts
- Size: ~2000 tokens per attempt
- Lifetime: Used for retries
- Cache TTL: 5 minutes (ephemeral)

**Block E: Validation Errors** (Optional - only if validation fails)
- Content: Top 3 validation errors
- Size: ~500 tokens
- Lifetime: Used for retries
- Cache TTL: 5 minutes (ephemeral)

#### FR2: Cache Block Accumulation Pattern
```
PlanningNode:
  - Sends [A, B] to model
  - After generating plan, appends Block C
  - Stores: planner_base_blocks = [A, B]
  - Stores: planner_extended_blocks = [A, B, C]

WorkflowGenerator (attempt 1):
  - Reads planner_extended_blocks [A, B, C]
  - After generation, appends Block D₁
  - After validation (if errors), appends Block E₁
  - Stores: planner_accumulated_blocks = [A, B, C, D₁, (E₁)]

WorkflowGenerator (retry n):
  - Reads planner_accumulated_blocks from previous attempt
  - After generation, appends Block Dₙ
  - After validation (if errors), appends Block Eₙ (optional)
  - Stores: planner_accumulated_blocks = [A, B, C, D₁, (E₁), Dₙ, (Eₙ)]
  - Note: If exceeding 4 breakpoints, combines recent D+E blocks
```

#### FR3: System vs User Message Separation
- **System parameter**: ALL cache blocks (A, B, C, D, E)
- **User message**: Node-specific instructions ONLY
  - PlanningNode: `planning_instructions.md`
  - WorkflowGenerator: `workflow_generator_instructions.md` or `workflow_generator_retry.md`

#### FR4: Cross-Node Cache Sharing
- Blocks A and B MUST be byte-identical between PlanningNode and WorkflowGeneratorNode
- Both nodes MUST use the same FlowIR tool definition
- Tool-choice hack MUST be preserved:
  - PlanningNode: `tool_choice={'type': 'none'}`
  - WorkflowGeneratorNode: `tool_choice={'type': 'tool'}`

#### FR5: Centralized Extraction Logic
- ALL workflow overview extraction MUST use a single centralized module
- Create `src/pflow/planning/utils/cache_utils.py` with:
  - Single regex pattern definition
  - `extract_workflow_overview()` function
  - `remove_workflow_overview()` function
- NO inline regex patterns allowed in other modules

#### FR6: Deterministic Block Construction
- Block content MUST be consistent across runs for cache hits
- Requirements:
  - Sort ONLY collections that have no inherent semantic order (e.g., node_ids lists)
  - DO NOT sort workflow JSON keys (preserve node execution order)
  - Use consistent JSON formatting (indent=2, no trailing spaces)
  - Preserve user-authored content order (don't sort prose)
  - Consistent whitespace (single trailing newline per block)
- **WARNING**: Never use `sort_keys=True` on workflow JSON as node order may be semantically important

### Non-Functional Requirements

#### NFR1: Backward Compatibility
- MUST maintain compatibility with existing `llm.get_model()` interface
- MUST support fallback to regex extraction if cache_blocks not provided (for other nodes)
- MUST not break existing tests (32 tests rely on current behavior)
- NOTE: No backward compatibility needed for shared store keys - they're internal only
  - The keys `planner_*_context` (strings) can be replaced with `planner_*_blocks` (lists)
  - Only PlanningNode writes and WorkflowGeneratorNode reads these keys
  - Both nodes are updated together, so no transition period needed

#### NFR2: Performance
- Cache creation overhead: <100ms
- Block accumulation: O(1) append operations
- Memory usage: <50MB for accumulated blocks
- Retry history limit: Maximum 3 attempts kept (older D/E blocks removed)
- Memory optimization: Generate string versions on-demand from blocks when needed

#### NFR3: Maintainability
- Single source of truth for workflow overview extraction
- No duplicated regex patterns
- Clear separation of concerns (blocks vs instructions)
- Comprehensive logging of cache metrics

#### NFR4: Cost Optimization
- Target: 87% cost reduction on retries
- Cache hit rate: >95% for blocks A and B within 5-minute window
- Total cached content: ~8000 tokens (vs current 2914)
- No token counting needed - Anthropic handles minimum thresholds automatically

## Critical: How Anthropic Cache Blocks Work

### MUST Use Separate Blocks, NOT Merged Text

**This is the most critical implementation detail that will make or break caching.**

#### ✅ CORRECT - Separate blocks that accumulate:
```python
# Each block is a SEPARATE entry in the list
cache_blocks = [
    {"text": "Block A content", "cache_control": {"type": "ephemeral"}},
    {"text": "Block B content", "cache_control": {"type": "ephemeral"}},
    {"text": "Block C content", "cache_control": {"type": "ephemeral"}}
]
```

#### ❌ WRONG - Merged into single block:
```python
# DO NOT DO THIS - completely breaks incremental caching!
merged_text = block_a + "\n" + block_b + "\n" + block_c
cache_blocks = [
    {"text": merged_text, "cache_control": {"type": "ephemeral"}}
]
```

### How Anthropic's Prefix Matching Works

When you send separate blocks, Anthropic automatically finds the longest matching prefix:

1. **First call** (PlanningNode): Send [A, B] → Creates cache for prefix [A, B]
2. **Second call** (WorkflowGenerator): Send [A, B, C] →
   - Anthropic checks: Is [A, B] cached? YES!
   - Reads [A, B] from cache (90% discount)
   - Only processes C as new content
3. **Third call** (Retry): Send [A, B, C, D, E] →
   - Anthropic checks: Is [A, B, C] cached? Maybe (if step 2 created cache)
   - Falls back to: Is [A, B] cached? YES!
   - Uses longest available match

### The 4 Breakpoint Limit

Anthropic allows **maximum 4 cache_control markers** per request. Our design fits perfectly:

```python
# Our block accumulation pattern:
PlanningNode:        [A, B]        # 2 breakpoints used
WorkflowGenerator:   [A, B, C]     # 3 breakpoints used
Retry:              [A, B, C, D, E] # 4-5 blocks, but can use 4 breakpoints

# If we hit the limit, combine D+E:
blocks = [
    {"text": "Block A", "cache_control": {"type": "ephemeral"}},  # 1
    {"text": "Block B", "cache_control": {"type": "ephemeral"}},  # 2
    {"text": "Block C", "cache_control": {"type": "ephemeral"}},  # 3
    {"text": "Block D\n\nBlock E", "cache_control": {"type": "ephemeral"}}  # 4
]
```

### Implementation MUST:
1. **Keep blocks as separate list entries** - never merge into single text
2. **Append new blocks to the list** - don't recreate or merge
3. **Ensure byte-identical content** for blocks A and B across nodes
4. **Use at most 4 cache_control markers** per request

## Critical Implementation Constraints

### MUST Preserve Exactly
1. **The regex pattern**: Even one character difference breaks caching
   ```python
   r"(# Workflow System Overview.*?)(?=\n## (?:Requirements Analysis|User Request|Available|Planning Instructions|Workflow Generation)|\Z)"
   ```
2. **Tool-choice hack**: Both nodes MUST have FlowIR tool definition
   - PlanningNode: `tool_choice={'type': 'none'}` for text output
   - WorkflowGeneratorNode: `tool_choice={'type': 'tool'}` for structured output
3. **Block ordering**: Anthropic requires exact prefix matching
4. **System vs User separation**: Cached blocks in system, instructions in user message
5. **Single `#` not `##`**: Workflow overview starts with single hash

### Implementation Warnings
1. **Never sort workflow JSON keys** - Node execution order is semantic
2. **Preserve whitespace exactly** - Single trailing newline per block
3. **Don't mix cached and non-cached content** - Clear separation required
4. **Tool definition must be identical** - Import FlowIR in both paths

## Technical Design

### Component Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     PlanningNode                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ PlannerContextBuilder.build_base_blocks()       │    │
│  │  ├─ Block A: Workflow Overview (cached)         │    │
│  │  └─ Block B: Base Context (cached)              │    │
│  └─────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ model.prompt(instructions, cache_blocks=[A,B])  │    │
│  │ → Generates plan markdown                       │    │
│  └─────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ PlannerContextBuilder.append_planning_block()   │    │
│  │  └─ Block C: Planning Output (cached)           │    │
│  └─────────────────────────────────────────────────┘    │
│  Writes to shared["planner_base_blocks"] = [A,B]        │
│  Writes to shared["planner_extended_blocks"] = [A,B,C]  │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                WorkflowGeneratorNode                     │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Reads from shared["planner_extended_blocks"]    │    │
│  │ Gets blocks: [A, B, C]                          │    │
│  └─────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ model.prompt(instructions, cache_blocks=[A,B,C])│    │
│  │ → Generates workflow JSON                       │    │
│  └─────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ Appends Block D (workflow) and E (errors if any)│    │
│  └─────────────────────────────────────────────────┘    │
│  Writes to shared["planner_accumulated_blocks"]         │
│  Contains: [A,B,C,D,(E)] for potential retries          │
└─────────────────────────────────────────────────────────┘
```

### API Changes

#### Cache Utilities Module (NEW)
```python
# src/pflow/planning/utils/cache_utils.py
import re
from typing import Optional

# Single source of truth for the regex pattern
WORKFLOW_OVERVIEW_PATTERN = re.compile(
    r"(# Workflow System Overview.*?)(?=\n## (?:Requirements Analysis|User Request|Available|Planning Instructions|Workflow Generation)|\Z)",
    re.DOTALL
)

def extract_workflow_overview(text: str) -> Optional[str]:
    """Extract workflow overview from text if it exists and is large enough.

    Returns:
        Extracted overview text or None if not found/too small
    """
    match = WORKFLOW_OVERVIEW_PATTERN.search(text or "")
    if not match:
        return None
    content = match.group(1).strip()
    # Return content as-is, Anthropic will ignore if below minimum tokens (1024 for Sonnet)
    return content if content else None

def remove_workflow_overview(text: str) -> str:
    """Remove workflow overview from text, leaving remaining content.

    Returns:
        Text with workflow overview removed
    """
    match = WORKFLOW_OVERVIEW_PATTERN.search(text or "")
    if match:
        return text.replace(match.group(1), "").strip()
    return (text or "").strip()
```

#### PlannerContextBuilder API
```python
class PlannerContextBuilder:
    # Maximum retry attempts to keep in history
    MAX_RETRY_HISTORY = 3

    @classmethod
    def build_base_blocks(
        cls,
        user_request: str,
        requirements_result: dict,
        browsed_components: dict,
        planning_context: str,
        discovered_params: Optional[dict] = None
    ) -> list[dict[str, Any]]:
        """Build [Block A, Block B] as cacheable blocks."""

    @classmethod
    def append_planning_block(
        cls,
        blocks: list[dict],
        plan_output: str,
        parsed_plan: dict
    ) -> list[dict[str, Any]]:
        """Append Block C to existing blocks.

        CRITICAL: Returns NEW list with block appended (immutable pattern)!
        Example: [A, B] + [C] → [A, B, C] as separate list entries

        NEVER modify the original blocks list - return blocks + [new_block]
        """

    @classmethod
    def append_workflow_block(
        cls,
        blocks: list[dict],
        workflow: dict,
        attempt_number: int
    ) -> list[dict[str, Any]]:
        """Append Block D for retry attempts.

        CRITICAL: Returns NEW list with block appended (immutable pattern)!
        Example: [A, B, C] + [D] → [A, B, C, D]

        Note: For debugging, keep all attempts in shared store but only
        send recent attempts as cache blocks to respect 4-breakpoint limit.
        """

    @classmethod
    def append_errors_block(
        cls,
        blocks: list[dict],
        validation_errors: list[str]
    ) -> list[dict[str, Any]]:
        """Append Block E for retry attempts (max 3 errors shown).

        CRITICAL: Returns NEW list with block appended (immutable pattern)!
        Example: [A, B, C, D] + [E] → [A, B, C, D, E]

        Only appends if validation_errors is non-empty.
        If approaching 4-breakpoint limit, may combine with Block D.
        """

    @classmethod
    def _trim_old_attempts(cls, blocks: list[dict]) -> list[dict]:
        """Remove oldest D/E blocks when exceeding retry limit."""
```

#### AnthropicLLMModel API Extension
```python
class AnthropicLLMModel:
    def prompt(
        self,
        prompt: Union[str, list],
        schema: Optional[type[BaseModel]] = None,
        temperature: float = 0.0,
        cache_blocks: Optional[list[dict[str, Any]]] = None,  # NEW
        **kwargs: Any
    ) -> AnthropicResponse:
        """Execute prompt with optional cache blocks."""
```

#### Shared Store Keys (PocketFlow Pattern)
The shared store is PocketFlow's in-memory dictionary for inter-node communication.
All nodes read from and write to this shared store during the workflow execution.

```python
# PlanningNode writes these to shared store in post():
shared["planner_base_blocks"]        # [A, B] - for WorkflowGeneratorNode
shared["planner_extended_blocks"]    # [A, B, C] - includes plan output

# WorkflowGeneratorNode reads from shared store in prep():
blocks = shared.get("planner_extended_blocks")  # First attempt
blocks = shared.get("planner_accumulated_blocks")  # Retries

# WorkflowGeneratorNode writes back to shared store in post():
shared["planner_accumulated_blocks"] # [A, B, C, D, E] - for next retry

# NO BACKWARD COMPATIBILITY NEEDED - These are internal implementation details
# The shared store keys are only used between PlanningNode and WorkflowGeneratorNode
# No external code depends on these keys, so we can change freely

# OLD keys (DELETE these completely):
shared["planner_base_context"]        # String - DELETE
shared["planner_extended_context"]    # String - DELETE
shared["planner_accumulated_context"] # String - DELETE

# NEW keys (blocks only):
shared["planner_base_blocks"]        # [A, B] - blocks with cache_control
shared["planner_extended_blocks"]    # [A, B, C] - blocks with cache_control
shared["planner_accumulated_blocks"] # [A, B, C, D, (E)] - blocks with cache_control

# IMPORTANT: Since both nodes are updated together in this refactor,
# there's no transition period needed. Just use blocks everywhere.
```

### Implementation Phases

#### Phase 0: Create Cache Utilities Module
1. Create `src/pflow/planning/utils/cache_utils.py`
2. Implement centralized extraction functions
3. Add unit tests for extraction consistency
4. Replace all inline regex patterns with these utilities

#### Phase 1: PlannerContextBuilder Refactor
1. Create methods to build structured blocks
2. Maintain both block and string outputs
3. Use cache_utils for workflow overview extraction
4. Add comprehensive unit tests

#### Phase 2: AnthropicLLMModel Enhancement
1. Add cache_blocks parameter
2. Implement direct block passing to SDK
3. Maintain regex fallback for compatibility
4. Add metrics for cache block usage

#### Phase 3: Node Integration
1. Update PlanningNode to use blocks
2. Update WorkflowGeneratorNode to use blocks
3. Store both blocks and strings in shared
4. Verify cache sharing works

#### Phase 4: Cleanup and Optimization
1. Remove duplicate regex patterns
2. Delete unused methods
3. Optimize block accumulation
4. Add comprehensive logging

## Testing Requirements

### Unit Tests
1. **PlannerContextBuilder Tests**
   - Block structure validation
   - Content consistency
   - Accumulation patterns
   - Size constraints

2. **AnthropicLLMModel Tests**
   - cache_blocks parameter handling
   - Fallback to regex extraction
   - Tool-choice preservation
   - Response format compatibility

### Integration Tests
1. **Cache Sharing Verification**
   - Blocks A and B identical between nodes (byte-for-byte comparison)
   - Cache metrics show hits
   - Cost calculations correct
   - Add explicit hash comparison tests:
   ```python
   def test_blocks_identical_between_nodes():
       planning_blocks = get_planning_blocks()
       generator_blocks = get_generator_blocks()[:2]
       # Must be byte-identical for cache sharing
       import hashlib
       for i in range(2):  # Check blocks A and B
           assert hashlib.sha256(planning_blocks[i]["text"].encode()).hexdigest() == \
                  hashlib.sha256(generator_blocks[i]["text"].encode()).hexdigest()
   ```

2. **Retry Flow Testing**
   - Block accumulation works
   - Each retry adds blocks
   - Errors properly appended
   - Old attempts trimmed after MAX_RETRY_HISTORY

3. **Backward Compatibility**
   - Existing tests pass (may need mock updates for new keys)
   - Non-cached calls work (for other nodes not using blocks)
   - No string compatibility needed (keys are internal only)

### Performance Tests
1. **Cache Efficiency**
   - Measure cache hit rates
   - Verify token counts increase from ~2914 to ~8000
   - Calculate cost savings
   - Expected metrics progression:
     ```
     PlanningNode:     cache_creation=~4914 (A+B), cache_read=0
     WorkflowGenerator: cache_creation=~1000 (C), cache_read=~4914 (A+B)
     Retry:            cache_creation=~2500 (D+E), cache_read=~4914+ (A+B or A+B+C)
     ```

2. **Memory Usage**
   - Monitor block accumulation
   - Check for memory leaks
   - Verify cleanup

## Success Criteria

### Quantitative Metrics
- [ ] Cache size increased from 2914 to ~8000 tokens
- [ ] Cost reduction of 87% on retries achieved
- [ ] Cache hit rate >95% for blocks A and B
- [ ] All 32 existing tests pass
- [ ] Zero performance regression

### Qualitative Metrics
- [ ] Code is cleaner and more maintainable
- [ ] No duplicate extraction logic
- [ ] Clear separation of cached vs uncached content
- [ ] Comprehensive documentation
- [ ] Easy to debug and monitor

## Risks and Mitigations

### Risk 1: Cache Key Mismatch
**Risk**: Blocks not byte-identical, cache doesn't share
**Mitigation**: Strict validation tests, byte comparison in tests

### Risk 2: Backward Compatibility Break
**Risk**: Existing code breaks with new implementation
**Mitigation**: Maintain dual paths, extensive testing

### Risk 3: Anthropic API Changes
**Risk**: Cache behavior changes in future API versions
**Mitigation**: Version pinning, comprehensive error handling

### Risk 4: Memory Growth
**Risk**: Accumulated blocks consume too much memory
**Mitigation**:
- Block size limits enforced
- MAX_RETRY_HISTORY = 3 (auto-trim old attempts)
- On-demand string generation from blocks
- Cleanup on completion

### Risk 5: Cache Failure Handling
**Risk**: Caching fails silently or breaks execution
**Mitigation**:
- Graceful fallback to non-cached execution
- Comprehensive error logging
- Metrics tracking for cache failures

## Implementation Checklist

### Preparation
- [ ] Review current implementation thoroughly
- [ ] Document all dependencies
- [ ] Create test baseline
- [ ] Set up metrics tracking

### Implementation
- [ ] Create cache_utils.py module (Phase 0)
- [ ] Implement PlannerContextBuilder changes
- [ ] Update AnthropicLLMModel wrapper
- [ ] Modify PlanningNode to create [A, B, C]
- [ ] Modify WorkflowGeneratorNode to read [A, B, C]
- [ ] Update shared store keys
- [ ] Add logging and metrics

### Testing
- [ ] Run unit tests
- [ ] Run integration tests
- [ ] Verify cache metrics
- [ ] Check cost calculations
- [ ] Performance benchmarks
- [ ] Backward compatibility tests

### Documentation
- [ ] Update code comments
- [ ] Update CLAUDE.md files
- [ ] Document new APIs
- [ ] Create migration guide
- [ ] Update handoff documentation

### Cleanup
- [ ] Remove duplicate code
- [ ] Delete unused methods
- [ ] Optimize implementations
- [ ] Final testing pass
- [ ] Code review

## Appendix A: Block Content Examples

### Block A: Workflow System Overview
```
# Workflow System Overview

## How Workflows Work
Workflows are DATA PIPELINES where...
[~2914 tokens of static content]
```

### Block B: Base Context
```
## User Request
Create a workflow to analyze GitHub issues

## Requirements Analysis
Steps to accomplish:
- Fetch issues from repository
- Analyze patterns
[~2000 tokens of request-specific content]
```

### Block C: Planning Output
```
## Execution Plan

**Status**: FEASIBLE
**Node Chain**: fetch_issues >> analyze >> save_report
[~1000 tokens of plan]
```

### Block D: Generated Workflow
```
## Generated Workflow (Attempt 1)
{
  "ir_version": "1.0.0",
  "nodes": [...],
  "edges": [...]
}
[~2000 tokens of JSON]
```

### Block E: Validation Errors
```
## Validation Errors
1. Missing required input: api_key
2. Invalid node reference: analyize (did you mean analyze?)
3. Circular dependency detected
[~500 tokens of errors]
```

## Appendix B: Migration Path

### For Existing Code
1. No changes required initially (backward compatible)
2. Optional: Pass cache_blocks for better performance
3. Gradual migration as convenient

### For New Code
1. Always use cache_blocks parameter
2. Follow block accumulation pattern
3. Keep instructions separate from cached content

---

**Document Status**: This specification is ready for review and implementation. It provides comprehensive requirements while maintaining flexibility for implementation details.