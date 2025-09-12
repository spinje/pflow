# Task 61: Implement Fast Mode for Planner with Aggressive Parallelization

## ID
61

## Title
Implement Fast Mode for Planner with Aggressive Parallelization

## Description
Add a `--fast` CLI flag to the planner that enables aggressive parallelization of nodes, trading some component selection quality for significant speed improvements (23% faster). This gives users control over the speed/quality trade-off, with the default remaining quality-first sequential execution.

## Status
not started

## Dependencies
- Task 52: Improve planner with "plan" and "requirements" steps - The parallelization builds on top of the new RequirementsAnalysisNode and PlanningNode architecture. These nodes must exist before we can parallelize them.
- Task 17: Implement Natural Language Planner System - The base planner system must exist and be working correctly before adding parallelization optimizations.

## Priority
medium

## Details
The Fast Mode implementation will provide users with an opt-in flag to enable aggressive parallelization of the planner pipeline, reducing execution time from ~3.5 seconds to ~2.7 seconds (23% improvement) for Path B (workflow generation) workflows.

### Current Sequential Architecture (Task 52)
```
Discovery (500ms) → ParameterDiscovery (400ms) → RequirementsAnalysis (400ms) →
ComponentBrowsing (400ms) → Planning (600ms) → WorkflowGenerator (1200ms)
Total: ~3500ms
```

### Fast Mode Parallel Architecture
```
Stage 1: Discovery + ParameterDiscovery (parallel) - 500ms
Stage 2: RequirementsAnalysis + ComponentBrowsing (parallel) - 400ms
Stage 3: Planning → WorkflowGenerator (sequential, required) - 1800ms
Total: ~2700ms (800ms saved)
```

### Key Design Decisions (MVP Approach)
- **Opt-in only**: Users must explicitly use `--fast` flag to enable
- **Two parallel stages**: Stage 1 (Discovery + ParameterDiscovery) and Stage 2 (Requirements + ComponentBrowsing)
- **Modified ComponentBrowsing**: In fast mode, works without requirements using templatized input instead
- **Preserved context accumulation**: Planning and WorkflowGenerator remain sequential to maintain Task 52's context benefits
- **PocketFlow async patterns**: Use existing AsyncParallelBatchNode for implementation

### Technical Implementation
1. **CLI Flag Addition**: Add `--fast` option to the plan command
2. **Create Fast Flow Variant**: New `create_fast_planner_flow()` function with parallel stages
3. **Modify ComponentBrowsingNode**: Add fast mode logic to work without requirements
4. **Create Parallel Stage Nodes**:
   - `FastPlannerStage1` for Discovery + ParameterDiscovery
   - `FastPlannerStage2` for Requirements + ComponentBrowsing

### Quality Trade-offs
- **Component over-selection**: Fast mode may select 10-20% more components than necessary
- **Less optimal selection**: Without requirements context, ComponentBrowsing makes less informed choices
- **Planning still optimizes**: The PlanningNode will optimize the workflow regardless of initial over-selection

### User Experience
```bash
# Standard mode (default)
$ pflow "analyze github issues and create report"
✓ Workflow generated in 3.5s

# Fast mode (opt-in)
$ pflow --fast "analyze github issues and create report"
✓ Workflow generated in 2.7s (fast mode)
```

### Performance Metrics to Track
- Path A vs Path B distribution
- Actual latency improvements in production
- Component over-selection rates
- Retry rates in fast mode vs standard mode
- User preference (which mode gets used more)

### Future Considerations
- **Phase 1**: Implement Discovery + ParameterDiscovery parallelization for both modes
- **Phase 2**: Add --fast flag with Requirements + ComponentBrowsing parallelization
- **Phase 3**: Consider automatic mode selection based on input complexity
- **Phase 4**: Make fast mode default if quality impact < 5% and user satisfaction increases

## Test Strategy
Testing will ensure both modes work correctly and that fast mode maintains acceptable quality:

### Unit Tests
- Test parallel execution of Stage 1 nodes (Discovery + ParameterDiscovery)
- Test parallel execution of Stage 2 nodes (Requirements + ComponentBrowsing)
- Test ComponentBrowsingNode behavior with and without requirements
- Verify proper result merging from parallel nodes
- Test routing decisions after parallel stages

### Integration Tests
- End-to-end tests for both standard and fast mode
- Verify same user input produces functional workflows in both modes
- Test that fast mode is actually faster (performance benchmarks)
- Ensure context accumulation still works in fast mode
- Test error handling when parallel nodes have conflicts

### Quality Validation Tests
- Compare component selection between modes
- Measure over-selection rates in fast mode
- Verify Planning can optimize over-selected components
- Test that retry learning still works with parallel execution

### Edge Cases
- Test behavior when one parallel node fails
- Verify vague input detection works in fast mode
- Test Path A (workflow reuse) with fast mode enabled
- Ensure validation and metadata generation remain unchanged