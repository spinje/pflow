# Critical Decisions for Task 32 Implementation

## 1. Core Architecture Pattern - Importance: 5/5

The research documents present three different architectural approaches for implementing metrics. We need to choose one before proceeding.

### Context:
Task 32 needs to collect metrics across both planner and workflow execution. The documents suggest different patterns for how to structure this collection system.

### Options:

- [x] **Option A: Unified MetricsCollector Pattern**
  - Single `MetricsCollector` class that spans both planner and workflow
  - Passed through execution via dependency injection
  - Clean separation of metrics from tracing/debugging
  - Pros: Consistent with Task 27 patterns, easy to test, clear ownership
  - Cons: Requires passing collector through multiple layers

- [ ] **Option B: Enhanced Shared Store Pattern**
  - Store all metrics directly in shared store during execution
  - Aggregate metrics at the end from shared store
  - No separate collector class needed
  - Pros: Simpler, uses existing infrastructure
  - Cons: Pollutes shared store, harder to test, mixing concerns

- [ ] **Option C: Real-time ExecutionTracer Pattern**
  - Create comprehensive tracer that outputs to stderr in real-time
  - Combines metrics and tracing in one system
  - Pros: Immediate visibility, good for debugging
  - Cons: More complex, mixes user output with metrics, heavier implementation

**Recommendation**: Option A - The MetricsCollector pattern provides the cleanest separation of concerns and aligns with existing patterns from Task 27.

---

## 2. Wrapper Implementation Location - Importance: 4/5

Where should we add metrics collection for workflow nodes?

### Context:
Workflow nodes go through multiple wrapper layers. We need to decide where to inject metrics collection.

### Options:

- [x] **Option A: New TracingNodeWrapper as Outermost**
  - Create new wrapper specifically for metrics/tracing
  - Apply as: TracingWrapper → NamespacedWrapper → TemplateAwareWrapper → Node
  - Pros: Clean separation, sees all transformations, follows Task 27 pattern
  - Cons: Another wrapper layer, needs careful attribute copying

- [ ] **Option B: Enhance Existing TemplateAwareNodeWrapper**
  - Add metrics collection to existing wrapper
  - Pros: No new wrapper, simpler implementation
  - Cons: Mixing concerns, won't see namespace transformations

**Recommendation**: Option A - New wrapper follows the established pattern and provides better visibility.

---

## 3. JSON Output Format - Importance: 3/5

What structure should the JSON metrics output follow?

### Context:
The `--output-format json` flag needs to include metrics. Multiple formats are proposed.

### Options:

- [x] **Option A: Nested Structure with Sections**
  ```json
  {
    "result": "...",
    "metrics": {
      "planner": { "duration_ms": 5000, "cost_usd": 0.73 },
      "workflow": { "duration_ms": 3000, "cost_usd": 0.11 },
      "total": { "duration_ms": 8000, "cost_usd": 0.84 }
    }
  }
  ```
  - Pros: Clear separation, easy to understand
  - Cons: More nested

- [ ] **Option B: Flat Structure (Claude Code Compatible)**
  ```json
  {
    "result": "...",
    "duration_ms": 8000,
    "total_cost_usd": 0.84,
    "planning_cost_usd": 0.73,
    "execution_cost_usd": 0.11
  }
  ```
  - Pros: Simpler, more compatible with other tools
  - Cons: Less organized for complex metrics

**Recommendation**: Option A - Better organization for future expansion while still being parseable.

---

## 4. Token Counting Strategy - Importance: 2/5

How much effort should we invest in accurate token counting for the MVP?

### Context:
The `llm` library doesn't always provide token counts. We need fallback strategies.

### Options:

- [x] **Option A: Simple Estimation for MVP**
  - Use `response.usage()` when available
  - Fall back to character count ÷ 4 estimation
  - Pros: Simple, good enough for cost estimates
  - Cons: Not perfectly accurate

- [ ] **Option B: Full Accuracy with tiktoken**
  - Install and use tiktoken for OpenAI models
  - Implement model-specific tokenizers
  - Pros: Accurate token counts
  - Cons: More dependencies, more complex, slower

**Recommendation**: Option A - Simple estimation is sufficient for MVP. We can add accuracy later.

---

## 5. Metrics Display Default - Importance: 2/5

Should metrics be displayed by default or only when requested?

### Context:
We need to maintain backward compatibility while providing value to users.

### Options:

- [ ] **Option A: Display by Default**
  - Always show metrics summary after execution
  - Pros: Users immediately see value
  - Cons: May break existing scripts expecting clean output

- [x] **Option B: Opt-in Only**
  - Only show metrics with `--metrics` flag or `--output-format json`
  - Pros: Backward compatible, clean by default
  - Cons: Users might not discover the feature

**Recommendation**: Option B - Maintain backward compatibility and let users opt in.

---

## Summary of Recommendations

1. **Architecture**: MetricsCollector pattern ✓
2. **Wrapper Location**: New TracingNodeWrapper as outermost ✓
3. **JSON Format**: Nested structure with sections ✓
4. **Token Counting**: Simple estimation for MVP ✓
5. **Display Default**: Opt-in only ✓

Please review these decisions and let me know if you agree with the recommendations or prefer different options.