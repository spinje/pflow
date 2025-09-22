# Task 68: Refined Understanding & Remaining Questions

Based on code verification and your clarifications, here's my refined understanding:

## ✅ Confirmed Decisions

1. **Full Caching Implementation** - We're implementing the complete caching system from node-execution-caching.md
2. **Unified Flow Architecture** - Repair IS the primary execution path when auto-repair is enabled
3. **Reuse Existing Patterns** - RepairGeneratorNode should follow WorkflowGeneratorNode patterns

## ✅ Clarified Technical Details

### PocketFlow Flow Mechanics
- **No Flow.end()** - Flows end naturally when `get_next_node()` returns None
- **Action routing** - Use `"default"` or custom action strings, flow ends when no successor found
- **Error warning** - "Flow ends: 'error' not found in ['default']" happens when node returns unhandled action

### OutputController
- Located in `src/pflow/core/__init__.py`
- Constructor: `OutputController(print_flag=True, output_format='text')`
- Used for progress display during execution

### Error Collection Strategy
- Stop at first node failure (PocketFlow design)
- But collect context from partial execution:
  - Template mismatches in executed nodes
  - Missing fields in API responses
  - Type mismatches in produced data

## 🟡 Remaining Questions

### 1. RepairGeneratorNode LLM Implementation
Looking at WorkflowGeneratorNode pattern, I see it uses:
- `llm.get_model()` from the llm library
- Prompt templates from `prompts/` directory
- Cache blocks for efficiency

**Questions:**
1. Should we create new prompt templates in `src/pflow/repair/prompts/` or reuse planning prompts?
2. Which model should repair use? Same as planner (`anthropic/claude-sonnet-4-0`)?
3. Should repair use thinking tokens like the planner does?

### 2. CLI Context Storage
Currently `ctx.obj` doesn't store `workflow_ir`.

**Questions:**
1. Where in the CLI flow should we set `ctx.obj["workflow_ir"]` and `ctx.obj["execution_params"]`?
2. Should we also store `original_request` for repair context?

### 3. Flow Termination in Repair
Since there's no `Flow.end()`, repair flow should terminate by returning from a node without successors.

**Question:** Should we use `None` return in `post()` or just not wire any successors for terminal nodes?

### 4. Caching Integration Points
The unified flow needs caching at multiple levels:

**Questions:**
1. Should WorkflowExecutorService manage the cache lifecycle or should CLI/repair service?
2. How should cache persist across repair attempts within same execution?
3. Should we implement cache serialization for debugging/inspection?

### 5. Test Mocking Strategy
For RepairGeneratorNode testing without real LLM:

**Questions:**
1. Should we mock at the llm.get_model() level or at the node level?
2. What test fixtures for different error scenarios (template errors, API changes, etc.)?
3. How to test cache correctness without real execution?

## 📋 Implementation Approach

Based on understanding, here's the refined approach:

### Phase 1: WorkflowExecutorService Foundation
1. **Create WorkflowExecutorService** with caching infrastructure
2. **Add WorkflowManager.update_metadata()** for execution tracking
3. **Refactor CLI** to use service and set ctx.obj values
4. **Implement NodeExecutionCache** and CachingNodeWrapper

### Phase 2: Unified Repair Flow
1. **Remove RuntimeValidationNode** from planner (11 nodes instead of 12)
2. **Create repair module** with repair-specific nodes
3. **Implement execute_with_auto_repair** as primary execution path
4. **Integrate with CLI** using unified flow by default

### Phase 3: RepairGeneratorNode Implementation
1. **Create repair prompts** based on planner patterns
2. **Implement LLM-based repair** logic using llm library
3. **Handle error context** from partial execution
4. **Test with mocked LLM** responses

## 🎯 Next Steps

Before starting implementation, I need answers to:
1. RepairGeneratorNode prompt and model strategy
2. CLI context storage points
3. Cache lifecycle management approach

Once these are clarified, I can create the final implementation spec and begin coding.