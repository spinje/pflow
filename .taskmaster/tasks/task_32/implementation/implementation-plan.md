# Task 32: Implementation Plan - Unified Metrics and Tracing System

## Executive Summary

Implementing a unified observability system that provides cost tracking and debugging capabilities for pflow. The system uses a single `InstrumentedNodeWrapper` that serves both lightweight metrics (with JSON output) and detailed tracing (with --trace flags).

## Context Verification Summary

Through parallel subagent analysis, I've verified:

1. **DebugWrapper Pattern** (debug.py):
   - Uses TimedResponse wrapper for lazy LLM response timing
   - Intercepts at llm module level, not per-node
   - Cleanup restores original llm.get_model after planner

2. **Compiler Integration** (compiler.py):
   - `_create_single_node` at line 292 creates nodes
   - Current wrapper order: BaseNode → TemplateAwareNodeWrapper → NamespacedNodeWrapper
   - Need to add InstrumentedNodeWrapper as outermost

3. **CLI Integration** (main.py):
   - `--trace` flag at line 1318 (currently for planner only)
   - `execute_json_workflow` at line 532 is the convergence point for all execution paths
   - JSON output wrapped in `_handle_json_output` at line 333

4. **LLMNode Behavior** (llm.py):
   - OVERWRITES `shared["llm_usage"]` on each execution (line 120)
   - Need accumulation list `shared["__llm_calls__"]` to preserve all usage

## Implementation Tasks Breakdown

### Phase 1: Core Infrastructure (3 files, can parallelize)

#### Task 1.1: Create MetricsCollector
**File**: `src/pflow/core/metrics.py` (NEW)
**Dependencies**: None
**Assignee**: Subagent A

Components:
- MetricsCollector class with timing methods
- Cost calculation with MODEL_PRICING dictionary
- Aggregation from `__llm_calls__` list
- Summary generation for JSON output

#### Task 1.2: Create InstrumentedNodeWrapper
**File**: `src/pflow/runtime/instrumented_wrapper.py` (NEW)
**Dependencies**: None
**Assignee**: Subagent B

Components:
- Wrapper with metrics and trace collectors
- Timing capture with time.perf_counter()
- LLM usage accumulation to `__llm_calls__`
- Delegation pattern matching existing wrappers

#### Task 1.3: Create WorkflowTraceCollector
**File**: `src/pflow/runtime/workflow_trace.py` (NEW)
**Dependencies**: None
**Assignee**: Subagent C

Components:
- Event recording with shared store snapshots
- Mutation calculation
- JSON file saving to ~/.pflow/debug/
- Template resolution capture mechanism

### Phase 2: Integration Points (4 files, some dependencies)

#### Task 2.1: Enhance DebugWrapper
**File**: `src/pflow/planning/debug.py` (MODIFY)
**Lines**: Around 75-88 (init), add metrics parameter
**Dependencies**: Task 1.1 (MetricsCollector must exist)
**Assignee**: Main agent

Changes:
- Add metrics parameter to __init__
- Pass through DebugContext
- No additional logic needed (metrics aggregates from shared)

#### Task 2.2: Modify Compiler
**File**: `src/pflow/runtime/compiler.py` (MODIFY)
**Lines**: 292-349 (_create_single_node), 688-796 (compile_ir_to_flow)
**Dependencies**: Task 1.2 (InstrumentedNodeWrapper must exist)
**Assignee**: Subagent D

Changes:
- Add metrics_collector and trace_collector parameters to _create_single_node
- Apply InstrumentedNodeWrapper as outermost wrapper (after line 336)
- Pass collectors through compile_ir_to_flow

#### Task 2.3: Update CLI - Add Flags
**File**: `src/pflow/cli/main.py` (MODIFY)
**Lines**: Around 1318 (add --trace-planner)
**Dependencies**: None
**Assignee**: Subagent E

Changes:
- Add --trace-planner flag
- Update --trace help text
- Store in context object

#### Task 2.4: Update CLI - Integration
**File**: `src/pflow/cli/main.py` (MODIFY)
**Lines**: 532-607 (execute_json_workflow), 333-424 (_handle_json_output)
**Dependencies**: Tasks 1.1, 1.2, 1.3
**Assignee**: Main agent (complex integration)

Changes:
- Create collectors in execute_json_workflow
- Pass to compiler
- Wrap JSON output with metrics
- Save trace files

### Phase 3: Testing (Can parallelize after Phase 2)

#### Task 3.1: Unit Tests - Core Components
**Files**:
- `tests/test_core/test_metrics.py` (NEW)
- `tests/test_runtime/test_instrumented_wrapper.py` (NEW)
- `tests/test_runtime/test_workflow_trace.py` (NEW)
**Dependencies**: Phase 1 complete
**Assignee**: test-writer-fixer subagent

#### Task 3.2: Integration Tests
**File**: `tests/test_integration/test_metrics_integration.py` (NEW)
**Dependencies**: Phase 2 complete
**Assignee**: test-writer-fixer subagent

#### Task 3.3: CLI Flag Tests
**File**: `tests/test_cli/test_metrics_flags.py` (NEW)
**Dependencies**: Phase 2 complete
**Assignee**: test-writer-fixer subagent

## Dependency Graph

```
Phase 1 (Parallel):
├── Task 1.1: MetricsCollector
├── Task 1.2: InstrumentedNodeWrapper
└── Task 1.3: WorkflowTraceCollector

Phase 2 (Sequential/Parallel):
├── Task 2.1: DebugWrapper (depends on 1.1)
├── Task 2.2: Compiler (depends on 1.2)
├── Task 2.3: CLI Flags (independent)
└── Task 2.4: CLI Integration (depends on 1.1, 1.2, 1.3)

Phase 3 (Parallel after Phase 2):
├── Task 3.1: Unit Tests
├── Task 3.2: Integration Tests
└── Task 3.3: CLI Tests
```

## Risk Mitigation

### Risk 1: Wrapper Order Issues
**Mitigation**: Verified exact order needed: Instrumented → Namespaced → TemplateAware → BaseNode

### Risk 2: LLM Usage Overwrite
**Mitigation**: Use `__llm_calls__` accumulation list, verified pattern

### Risk 3: Template Resolution Capture
**Mitigation**: May need to modify TemplateAwareNodeWrapper or use logging intercept

### Risk 4: Performance Overhead
**Mitigation**: Use time.perf_counter(), minimal operations in hot path

### Risk 5: Test Coverage
**Mitigation**: Creating comprehensive tests from scratch, using existing mocking patterns

## Subagent Task Specifications

### Subagent A: MetricsCollector
"Create MetricsCollector class in src/pflow/core/metrics.py with timing methods, cost calculation using MODEL_PRICING dictionary (per-million tokens), aggregation from __llm_calls__ list, and summary generation. Use time.perf_counter() for all timing. Include methods: record_planner_start/end, record_workflow_start/end, record_node_execution, calculate_costs, get_summary."

### Subagent B: InstrumentedNodeWrapper
"Create InstrumentedNodeWrapper in src/pflow/runtime/instrumented_wrapper.py that wraps nodes for metrics and tracing. Must have __init__ with inner_node, node_id, metrics_collector, trace_collector parameters. Implement _run method that times execution with perf_counter, accumulates LLM usage to shared['__llm_calls__'] list, and delegates via __getattr__, __rshift__, __sub__. Follow delegation pattern from existing wrappers."

### Subagent C: WorkflowTraceCollector
"Create WorkflowTraceCollector in src/pflow/runtime/workflow_trace.py for detailed debugging. Record node executions with shared store before/after snapshots, calculate mutations, save to ~/.pflow/debug/pflow-trace-workflow-{timestamp}.json. Include execution_id UUID inside JSON. Filter large/sensitive data. Handle template resolutions if possible."

### Subagent D: Compiler Integration
"Modify src/pflow/runtime/compiler.py to apply InstrumentedNodeWrapper. In _create_single_node (line 292), add metrics_collector and trace_collector parameters. After line 336 (NamespacedNodeWrapper), apply InstrumentedNodeWrapper as outermost wrapper if collectors present. Update compile_ir_to_flow to accept and pass through collectors."

### Subagent E: CLI Flags
"Add --trace-planner flag to src/pflow/cli/main.py around line 1318. Update --trace flag help text to mention workflow execution. Store both flags in context object. Ensure flags are passed through all execution paths."

## Success Criteria

1. ✅ Zero overhead when no flags used
2. ✅ Metrics appear in JSON output with --output-format json
3. ✅ Workflow traces saved with --trace flag
4. ✅ Planner traces saved with --trace-planner flag
5. ✅ Accurate cost calculation for all LLM calls
6. ✅ All 31 test criteria from spec pass
7. ✅ Performance overhead < 1%
8. ✅ No regression in existing tests

## Timeline Estimate

- Phase 1: 2-3 hours (parallel execution)
- Phase 2: 2-3 hours (some parallel, some sequential)
- Phase 3: 2-3 hours (parallel testing)
- Total: 6-9 hours with parallelization

## Next Steps

1. Deploy Phase 1 subagents in parallel
2. Main agent handles complex integrations in Phase 2
3. Deploy test-writer-fixer for comprehensive test coverage
4. Verify all success criteria met