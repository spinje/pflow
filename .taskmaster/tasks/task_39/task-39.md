# Task 39: Support Parallel Execution in Workflows

## ID
39

## Title
Support Parallel Execution in Workflows

## Description
Enable pflow to generate and execute workflows with parallel branches using PocketFlow's BatchNode and BatchFlow capabilities. This addresses the natural tendency of LLMs to create parallel data pipelines when users request multiple operations on the same data.

## Status
not started

## Dependencies
- Task 38: Support Branching in Generated Workflows - We need conditional branching working first to understand the execution model before adding parallel capabilities
- Task 28: Improve Performance of Planner Prompts - Revealed the fundamental need for parallel execution through test failures

## Priority
low

## Details
Through Task 28's workflow generator testing, we discovered that LLMs naturally create parallel branching patterns in ~40% of complex workflows. This isn't a bug - it's the correct interpretation of user requests like "analyze data AND generate visualizations". Currently, these workflows fail because PocketFlow's default Flow class only supports sequential execution with conditional branching.

### The Problem

When users say "filter the data, then analyze it and create visualizations", they mean:
```
filter_data → [analyze, visualize] (in parallel) → save_results
```

But PocketFlow's basic Flow only supports:
```
filter_data → analyze → visualize → save_results (sequential)
```

This creates inefficiency and fights against natural LLM interpretation.

### The Solution

PocketFlow already has `BatchNode` and `BatchFlow` classes designed for parallel processing:

1. **BatchNode**: Can process multiple items in parallel
2. **BatchFlow**: Can orchestrate parallel execution paths
3. **AsyncBatchNode**: Supports async/await patterns

We need to:
1. Enable the workflow generator to use these components
2. Update the IR schema to express parallel execution
3. Teach the planner when to use parallel vs sequential patterns

### Technical Approach

#### Phase 1: Research and Design
- Study PocketFlow's BatchNode/BatchFlow implementation
- Determine how to express parallelism in the IR
- Design patterns for common parallel workflows

#### Phase 2: IR Schema Extension
- Add parallel execution markers to edges
- Support fan-out/fan-in patterns
- Maintain backward compatibility

#### Phase 3: Compiler Updates
- Detect parallel patterns in IR
- Generate BatchFlow instead of Flow when needed
- Handle data merging at convergence points

#### Phase 4: Planner Updates
- Teach workflow generator about parallel patterns
- Provide examples of when to use parallel execution
- Update tests to validate parallel workflows

### Example Parallel Workflow

```json
{
  "ir_version": "0.2.0",
  "execution_mode": "parallel",
  "nodes": [
    {
      "id": "filter_data",
      "type": "filter-node",
      "purpose": "Filter input data"
    },
    {
      "id": "analyze",
      "type": "llm",
      "purpose": "Analyze filtered data"
    },
    {
      "id": "visualize",
      "type": "llm",
      "purpose": "Generate visualization code"
    },
    {
      "id": "merge_results",
      "type": "merge-node",
      "purpose": "Combine analysis and visualization"
    }
  ],
  "edges": [
    {"from": "filter_data", "to": "analyze", "parallel_group": "1"},
    {"from": "filter_data", "to": "visualize", "parallel_group": "1"},
    {"from": "analyze", "to": "merge_results"},
    {"from": "visualize", "to": "merge_results"}
  ]
}
```

### Success Criteria

1. Workflows can express parallel execution patterns
2. Compiler generates appropriate BatchFlow objects
3. Parallel branches execute simultaneously
4. Data correctly merges at convergence points
5. Task 28's "branching" test failures now pass

### Limitations

- Not all nodes may support parallel execution
- Memory constraints for large parallel operations
- Debugging parallel workflows is more complex
- Error handling in parallel branches needs careful design

## Test Strategy

### Unit Tests
- Test BatchFlow generation from parallel IR
- Verify parallel execution actually occurs
- Test data merging at convergence points
- Test error handling in parallel branches

### Integration Tests
- End-to-end parallel workflows
- Performance comparison (parallel vs sequential)
- Resource usage monitoring
- Error propagation across branches

### Planner Tests
- Update workflow generator tests to expect parallel patterns
- Test that appropriate workflows use parallelism
- Verify backward compatibility with sequential workflows

### Key Test Scenarios
1. **Data Analysis Pipeline**: Read → Filter → [Analyze || Visualize] → Save
2. **Multi-Source Report**: [Fetch Issues || Fetch PRs || Fetch Commits] → Merge → Generate Report
3. **Error Handling**: Parallel branches with different error behaviors
4. **Resource Limits**: Many parallel branches hitting system limits

## Notes

This task directly addresses the root cause discovered in Task 28: LLMs naturally generate parallel workflows because it's the correct interpretation of user intent. Instead of fighting this tendency, we should support it properly.

The key insight from the research: "The LLM is not wrong - parallel branching IS more efficient. The constraint is artificial - PocketFlow chose simplicity."

By supporting parallel execution, we'll:
1. Get more efficient workflows
2. Stop fighting LLM instincts
3. Match user expectations
4. Enable more complex use cases

This is a post-MVP enhancement but critical for making pflow truly powerful for complex data pipeline workflows.