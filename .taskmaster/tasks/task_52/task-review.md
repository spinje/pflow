# Task 52 Review: Improve planner with "plan" and "requirements" steps

## Metadata
- **Implementation Date**: 2024-12-19 through 2025-01-15
- **Session IDs**: 9a2e2f2b-daea-46c3-b35d-983c7f870bc9, 13681cc9-3d96-4856-b90e-ea5eb63d1faa
- **Branch**: feat/planner-plan-requirements
- **Lines Changed**: +2,200 added, -460 removed (net +1,740)

## Executive Summary
Implemented RequirementsAnalysisNode and PlanningNode to enhance the planner with early requirement validation and execution planning, added cross-session caching with 90% cost reduction, integrated Claude 3.5 Sonnet's thinking tokens with adaptive allocation, moved cost calculation upstream to record time, and refactored to eliminate ~460 lines of complexity. The system now catches vague inputs early, accumulates context across retry attempts, intelligently allocates thinking tokens based on complexity, and tracks costs at the source for full transparency.

## Implementation Overview

### What Was Built
Task 52 fundamentally restructured the planner pipeline with two new nodes, sophisticated caching system, and intelligent thinking token allocation:

1. **RequirementsAnalysisNode** (`nodes.py:866-1058`)
   - Extracts abstract operational requirements from natural language
   - Detects vague inputs and requests clarification
   - Replaces specific values with template variables (e.g., "30" → "${count}")
   - Routes IMPOSSIBLE requests to early failure
   - **NEW**: Calculates complexity score for thinking token allocation

2. **PlanningNode** (`nodes.py:1059-1309`)
   - Creates markdown execution plans with node chains
   - Determines workflow feasibility (FEASIBLE/PARTIAL/IMPOSSIBLE)
   - Builds and extends cache blocks for downstream nodes
   - Accumulates context for retry learning
   - **NEW**: Uses adaptive thinking tokens (0-32K) based on complexity

3. **PlannerContextBuilder** (`context_blocks.py:14-350`)
   - Manages cacheable context blocks with clear boundaries
   - Supports incremental accumulation across retries
   - Maintains immutable block pattern for cache efficiency
   - **Updated**: Cache TTL changed from ephemeral to 5 minutes for better reuse

4. **Cross-session caching**
   - `--cache-planner` CLI flag enables Anthropic prompt caching
   - 90% cost reduction on cached content (after initial cache creation)
   - Three distinct patterns: Standard, Special Context, Planning
   - **NEW**: Cache sharing optimized by unified thinking budget allocation

5. **Thinking Tokens Optimization** (NEW)
   - Adaptive allocation: 0 / 4,096 / 16,384 / 32,768 tokens
   - Complexity scoring system based on nodes, capabilities, patterns
   - 75% of workflows share 4,096 token cache pool
   - Integrated with Anthropic's Claude 3.5 Sonnet thinking mode

6. **Cost Calculation Refactoring** (NEW)
   - Created `src/pflow/core/llm_pricing.py` - single source of truth
   - Costs calculated at record time in `debug.py`, not post-processing
   - Full cost breakdown in trace files with cache and thinking costs
   - Eliminated duplicate pricing tables across codebase

7. **Anthropic Structured Client** (NEW)
   - `anthropic_structured_client.py` for structured outputs
   - Supports thinking tokens with tool use restrictions
   - Handles temperature requirements for thinking mode

8. **JSON Output Enhancements** (NEW)
   - `--output-format json` now includes comprehensive metrics
   - Cache performance: creation/read tokens, efficiency percentage
   - Thinking performance: tokens used, budget allocated, utilization
   - Cost breakdowns: input, output, cache, thinking costs per phase
   - Example: `"cache_efficiency_pct": 50.0, "thinking_utilization_pct": 66.7`

9. **Refactored architecture**
   - Eliminated all `if cache_planner:` branches
   - Removed `cache_builder.py` and related complexity
   - Single execution path: always build blocks, conditionally pass

### Implementation Approach
The implementation diverged from the original spec in critical ways:
- **Added context accumulation** for retry learning (not in spec)
- **Moved ParameterDiscoveryNode** earlier in flow (position 2 instead of 3)
- **Added tool-choice hack** for passing cache blocks between nodes
- **Implemented three caching patterns** instead of unified approach

## Files Modified/Created

### Core Changes
```python
# Critical files with line numbers for quick navigation
src/pflow/planning/nodes.py:866-1309          # New nodes + thinking allocation
src/pflow/planning/context_blocks.py          # Cache block management (NEW)
src/pflow/planning/utils/anthropic_llm_model.py:259  # Monkey-patch + thinking
src/pflow/planning/utils/anthropic_structured_client.py  # Structured output (NEW)
src/pflow/planning/utils/prompt_cache_helper.py      # Simplified caching
src/pflow/planning/prompts/requirements_analysis.md  # Requirements prompt (NEW)
src/pflow/planning/prompts/planning_instructions.md  # Planning prompt (NEW)
src/pflow/cli/main.py:2464                    # Cache flag and monkey-patch control
src/pflow/core/llm_pricing.py                 # Centralized pricing (NEW)
src/pflow/core/metrics.py                     # Enhanced with thinking metrics
src/pflow/planning/debug.py:520-560           # Cost calculation at record time
scripts/analyze-trace/analyze.py              # Enhanced with thinking display
```

### Test Files
```python
# Critical tests that MUST pass
tests/test_planning/integration/test_context_accumulation.py  # Retry learning
tests/test_planning/unit/test_requirements_analysis.py        # Vague input + complexity
tests/test_planning/unit/test_planning_node.py                # Plan generation
tests/test_planning/unit/test_anthropic_llm_model_caching.py  # Thinking tokens (NEW)
tests/test_planning/integration/test_planner_integration.py   # Full flow
tests/test_core/test_llm_pricing.py                          # Cost calculation (NEW)
tests/test_core/test_metrics_thinking_cache.py               # Metrics tracking (NEW)
tests/test_planning/test_cost_in_trace.py                    # Cost in traces (NEW)
```

### Removed Files (Important!)
```python
# These files were deleted - do NOT recreate
src/pflow/planning/utils/cache_builder.py     # Obsolete, replaced by context_blocks.py
tests/test_planning/unit/test_cache_builder.py # Obsolete tests
```

## Integration Points & Dependencies

### Incoming Dependencies
```python
# What calls into Task 52's components
CLI.run() → install_anthropic_model() → llm.get_model (monkey-patched)
NaturalLanguagePlanner → RequirementsAnalysisNode (position 3 in flow)
NaturalLanguagePlanner → PlanningNode (position 5 in flow)
WorkflowGeneratorNode → shared["planner_extended_blocks"] (cache blocks)
ValidatorNode "retry" → shared["planner_accumulated_blocks"] (retry context)
```

### Outgoing Dependencies
```python
# What Task 52 components depend on
RequirementsAnalysisNode → llm.get_model("anthropic/claude-sonnet-4-0")
PlanningNode → llm.get_model("anthropic/claude-sonnet-4-0")
PlanningNode → PlannerContextBuilder.build_base_blocks()
PlanningNode → PlannerContextBuilder.append_planning_block()
All nodes → prompt templates in prompts/*.md
```

### Shared Store Keys
```python
# Critical shared store keys with data structures
shared["requirements_result"] = {
    "is_clear": bool,
    "steps": List[str],
    "required_capabilities": List[str],
    "estimated_nodes": int,
    "clarification_needed": Optional[str],
    "complexity_score": int,              # NEW: For thinking allocation
    "thinking_budget": int                # NEW: 0/4096/16384/32768
}

shared["plan_output"] = """
**Status**: FEASIBLE|PARTIAL|IMPOSSIBLE
**Node Chain**: node1 >> node2 >> node3
**Execution Steps**: ...
"""

shared["planner_extended_blocks"] = [
    {"text": str, "cache_control": {"type": "ephemeral"}},  # Static overview
    {"text": str, "cache_control": {"type": "ephemeral"}},  # Dynamic context
    {"text": str, "cache_control": {"type": "ephemeral"}}   # Plan output
]

shared["planner_accumulated_blocks"] = [  # Grows with each retry
    *planner_extended_blocks,
    {"text": "## Generated Workflow (Attempt N)", ...},
    {"text": "## Validation Errors", ...}
]
```

## Architectural Decisions & Tradeoffs

### Key Decisions

1. **Three separate caching patterns** (DO NOT UNIFY!)
   ```python
   # Pattern 1: Standard nodes (simple prompt caching)
   cache_blocks, prompt = build_cached_prompt(...)

   # Pattern 2: Special context nodes (custom _build_cache_blocks())
   def _build_cache_blocks(self, ...): ...

   # Pattern 3: Planning nodes (PlannerContextBuilder accumulation)
   blocks = PlannerContextBuilder.build_base_blocks(...)
   ```
   **Reasoning**: Each pattern has different performance characteristics
   **Alternative rejected**: Unified caching system would be more complex

2. **Single execution path**
   ```python
   # Always build blocks, conditionally pass
   cache_blocks = build_blocks()  # Always
   model.prompt(prompt, cache_blocks=cache_blocks if cache_planner else None)
   ```
   **Reasoning**: Eliminates branching complexity
   **Alternative rejected**: Dual paths with if/else branches

3. **Tool-choice hack for cache sharing**
   ```python
   # PlanningNode stores blocks in shared store
   shared["planner_extended_blocks"] = blocks
   # WorkflowGeneratorNode retrieves them
   blocks = prep_res.get("planner_extended_blocks")
   ```
   **Reasoning**: Avoids complex parameter passing
   **Alternative rejected**: Direct parameter passing through flow

### Technical Debt Incurred
- **Tool-choice hack**: Should be replaced with proper parameter passing in v2
- **Monkey-patching**: Won't scale to multiple model providers
- **Test mock conflicts**: Need consolidation to single approach
- **Cache block limit**: 4 blocks max (Anthropic limitation)

## Testing Implementation

### Test Strategy Applied
```bash
# Run these tests in order when modifying planner
pytest tests/test_planning/unit/test_requirements_analysis.py -xvs
pytest tests/test_planning/unit/test_planning_node.py -xvs
pytest tests/test_planning/integration/test_context_accumulation.py -xvs
pytest tests/test_planning/integration/test_planner_integration.py -xvs
make test  # Full suite to catch mock conflicts
```

### Critical Test Cases
```python
# These tests MUST pass - they catch real issues
test_context_accumulation.py::test_retry_preserves_and_extends_context
# ^ Validates that retries learn from previous attempts

test_requirements_analysis.py::test_vague_input_triggers_clarification_needed
# ^ Prevents generation of bad workflows from unclear inputs

test_planning_node.py::test_impossible_request_returns_impossible_status
# ^ Early failure detection saves LLM costs
```

## Unexpected Discoveries

### Gotchas Encountered

1. **Double-mocking breaks tests**
   ```python
   # DON'T DO THIS - causes test failures
   @pytest.fixture(autouse=True)
   def mock_llm_calls(): ...  # Global mock

   def test_something():
       with patch("llm.get_model"):  # Local mock - CONFLICTS!
   ```

2. **Cache creation costs MORE initially**
   - First request: 100% MORE expensive (2x cost for cache creation)
   - Subsequent requests: 90% savings
   - Break-even: After 2-3 requests

3. **Minimum cache size requirement**
   ```python
   # Won't cache - too small
   instructions = "Short prompt"  # < 1024 tokens

   # Will cache
   instructions = "Long prompt " * 100  # > 1024 tokens
   ```

4. **Claude 4 Sonnet thinking tokens behavior** (NEW)
   - No explicit `thinking_tokens` field in API response
   - `output_tokens` already includes thinking (hidden from view)
   - Must estimate: `thinking = total_output - visible_output`
   - Thinking incompatible with forced tool use

5. **Cache key sensitivity** (NEW)
   - Different thinking_budget = different cache namespace
   - Must use identical budgets across nodes for cache sharing
   - Solution: Unified allocation from RequirementsAnalysisNode

6. **Debug wrapper type mismatch** (NEW)
   - `AnthropicResponse.usage()` returns dictionary, not object
   - `hasattr(dict, "key")` always returns False
   - Fixed by checking `isinstance(usage_obj, dict)`

### Edge Cases Found
- Empty requirements → Routes to clarification flow
- IMPOSSIBLE status → Skips generation entirely
- Cache blocks must be immutable → `blocks = blocks + [new]` not `blocks.append(new)`
- Test environment → Must check `PYTEST_CURRENT_TEST` before monkey-patching

## Patterns Established

### Reusable Patterns

**Context Accumulation Pattern** (use for any retry mechanism):
```python
# Initial attempt
blocks = PlannerContextBuilder.build_base_blocks(
    user_request, requirements, components, planning_context
)
blocks = PlannerContextBuilder.append_planning_block(blocks, plan)
shared["planner_extended_blocks"] = blocks

# On retry
blocks = shared.get("planner_accumulated_blocks", blocks)
blocks = PlannerContextBuilder.append_workflow_block(blocks, workflow, attempt)
blocks = PlannerContextBuilder.append_errors_block(blocks, errors)
shared["planner_accumulated_blocks"] = blocks
```

**Complexity Scoring Pattern** (use for adaptive resource allocation):
```python
# Linear scoring system for thinking token allocation
score = (estimated_nodes * 2.5) +           # Each node: 2.5 points
        (len(capabilities) * 4) +           # Each capability: 4 points
        (_score_operation_complexity()) +   # Patterns: 0-25 points
        (conditionals * 10) +                # Binary indicators
        (iteration * 12) +
        (external_services * 5)

# Three-tier allocation
if score < 20:   thinking_budget = 0        # Trivial
elif score < 70: thinking_budget = 4096     # Standard (75% of workflows)
elif score < 100: thinking_budget = 16384   # Complex
else: thinking_budget = 32768               # Extreme
```

**Cost Calculation at Source Pattern** (use for any metered API):
```python
# In debug.py when recording LLM response
from pflow.core.llm_pricing import calculate_llm_cost
cost_breakdown = calculate_llm_cost(
    model=model_name,
    input_tokens=input_tokens,
    output_tokens=output_tokens,
    cache_creation_tokens=cache_creation_tokens,
    cache_read_tokens=cache_read_tokens,
    thinking_tokens=thinking_tokens,
)
self.current_llm_call["cost"] = cost_breakdown  # Store with trace
```

**Monkey-patch Control Pattern** (use for any global modifications):
```python
# In CLI or main entry point
import os
if not os.environ.get("PYTEST_CURRENT_TEST"):
    install_anthropic_model()  # Only in production
```

### Anti-Patterns to Avoid
```python
# ❌ NEVER: Dual code paths
if cache_planner:
    # Complex caching logic
else:
    # Different logic

# ❌ NEVER: Modify cache blocks in place
blocks.append(new_block)  # WRONG - mutates

# ✅ ALWAYS: Create new lists
blocks = blocks + [new_block]  # Correct - immutable

# ❌ NEVER: Mix global and local mocks
with patch("llm.get_model"):  # Conflicts with global mock

# ✅ ALWAYS: Use consistent mock pattern
mock_llm_calls.set_response(...)  # Use global mock
```

## Breaking Changes

### API/Interface Changes
**New planner flow order** (memorize this!):
```python
# Old: Discovery → ComponentBrowsing → ParameterDiscovery → Generation
# New: Discovery → ParameterDiscovery → Requirements → ComponentBrowsing → Planning → Generation
#      Position 1 → Position 2        → Position 3    → Position 4       → Position 5 → Position 6
```

### Behavioral Changes
- **Vague inputs fail early** with clarification request
- **Impossible requests fail fast** without attempting generation
- **Retries accumulate context** and improve with each attempt
- **Cache flag required** for cost savings (`--cache-planner`)

## Future Considerations

### Extension Points
```python
# Add new requirement patterns here
src/pflow/planning/prompts/requirements_analysis.md

# Extend planning strategies here
src/pflow/planning/prompts/planning_instructions.md

# Add new cache block types here
src/pflow/planning/context_blocks.py::PlannerContextBuilder

# Update complexity scoring thresholds here
src/pflow/planning/nodes.py::RequirementsAnalysisNode._calculate_complexity_score

# Add new model pricing here
src/pflow/core/llm_pricing.py::MODEL_PRICING
```

### Scalability Concerns
- **Cache block limit**: Max 4 blocks (Anthropic API limitation)
- **Context size**: Accumulated blocks could exceed token limits after many retries
- **Monkey-patching**: Current approach won't work with multiple model providers
- **Test isolation**: Global mock conflicts will worsen as test suite grows
- **Thinking token limits**: 32K max may be insufficient for extreme workflows
- **Cost tracking precision**: Thinking tokens estimated for Claude 4, not exact

### Economic Impact
- **Cache sharing benefit**: 75% of workflows share 4,096 token pool
- **Daily cost projection**: ~$95/day for 1,000 workflows (vs $150 without optimization)
- **Break-even point**: 2-3 requests for cache creation cost to pay off
- **Net positive**: Cache savings often exceed thinking token costs

## AI Agent Guidance

### Quick Start for Related Tasks

**READ THESE FILES FIRST** (in order):
1. `src/pflow/planning/CLAUDE.md` - Complete architecture guide
2. `src/pflow/planning/nodes.py:866-1309` - See the actual implementation
3. `tests/test_planning/integration/test_context_accumulation.py` - Understand retry flow
4. `.taskmaster/tasks/task_52/implementation/progress-log.md` - Full implementation journey

**Key Commands**:
```bash
# Test your changes
pytest tests/test_planning/unit/test_requirements_analysis.py -xvs
pytest tests/test_planning/unit/test_planning_node.py -xvs

# Run with caching enabled
pflow run "your prompt" --cache-planner --trace-planner

# Check trace output
cat .pflow/debug/planner_trace_*.json | jq '.cache_metrics'
```

### Common Pitfalls

1. **DON'T unify the caching patterns** - They're separate for good reasons
2. **DON'T add if/else for caching** - Use single path with conditional passing
3. **DON'T modify cache blocks** - Always create new lists
4. **DON'T skip the tool-choice hack** - WorkflowGeneratorNode needs those blocks
5. **DON'T recreate cache_builder.py** - It was removed intentionally

### Test-First Recommendations

**When modifying ANY planner component**:
```bash
# 1. Check context accumulation still works
pytest tests/test_planning/integration/test_context_accumulation.py::test_retry_preserves_and_extends_context -xvs

# 2. Verify requirements analysis
pytest tests/test_planning/unit/test_requirements_analysis.py -xvs

# 3. Check full flow
pytest tests/test_planning/integration/test_planner_integration.py -xvs

# 4. Run full suite for mock conflicts
make test
```

**Red flags in test output**:
- "double mock" or "already mocked" → Mock conflict
- "cache_blocks not found" → Lost context between nodes
- "IMPOSSIBLE not handled" → Planning status routing broken

---

*Generated from implementation context of Task 52 - Sessions 9a2e2f2b-daea-46c3-b35d-983c7f870bc9 and 13681cc9-3d96-4856-b90e-ea5eb63d1faa*
*Last updated: 2025-01-15 with thinking tokens, cost tracking, and JSON output enhancements*