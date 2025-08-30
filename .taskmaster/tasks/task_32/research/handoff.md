# Task 32: Unified Metrics and Tracing System - Handoff

## Why This Task Matters

After implementing planner debugging (Task 27), we have visibility into the planner but workflows remain opaque. Users don't know:
- What their AI operations cost
- Which nodes are performance bottlenecks
- How data flows through their workflows
- Why workflows fail or behave unexpectedly

This task extends our observability to cover the entire pflow execution lifecycle.

## Key Insights from Task 27

The planner debugging implementation taught us:
1. **Wrapper pattern works well** - Non-invasive, preserves node functionality
2. **LLM interception is tricky** - Need to handle closures and method vs property carefully
3. **_run() must call our prep/exec/post** - Not just delegate to wrapped._run()
4. **Progress indicators are valuable** - Users appreciate real-time feedback

## Critical Design Decisions

### 1. Two-Tier Information System
- **Metrics**: User-facing operational data (costs, performance)
- **Traces**: Developer-facing debug data (full details)

This separation prevents information overload while maintaining debuggability.

### 2. Unified MetricsCollector
A single collector that spans both planner and workflow execution ensures:
- Consistent cost calculation
- Total token counts
- End-to-end timing

### 3. Wrapper Ordering Matters
```
TracingWrapper → NamespacedWrapper → TemplateAwareWrapper → BaseNode
```
TracingWrapper must be outermost to see all transformations.

### 4. Shared Store for Metrics
Using `shared["__metrics__"]` allows metrics to flow through the entire execution pipeline without modifying existing interfaces.

## Implementation Challenges to Watch

### 1. Token Extraction Variability
Different LLM providers return tokens differently:
- OpenAI: `response.usage.prompt_tokens`
- Anthropic: `response.usage.input_tokens`
- Some: `response.usage()` (method not property)

Need robust extraction that handles all cases.

### 2. Dynamic Node Types
Unlike the planner's fixed 9 nodes, workflows have arbitrary nodes loaded from registry. The tracing wrapper must be applied during compilation, not hardcoded.

### 3. Performance Impact
Snapshotting shared store could be expensive. Use shallow copies and filter large objects.

### 4. Model Pricing Maintenance
Prices change. Use external config file (`~/.pflow/pricing.json`) with defaults.

## Relationship to Existing Code

### Builds On
- Task 27's DebugWrapper and tracing patterns
- Task 24's WorkflowManager for loading workflows
- Task 31's namespacing wrappers

### Integrates With
- CLI's execute_json_workflow function
- Runtime compiler's node instantiation
- Planner's debug infrastructure

### Extends
- Adds MetricsCollector to existing DebugContext
- Creates parallel TracingNodeWrapper for workflows
- Enhances JSON output format with metrics

## Expected User Experience

### Without Metrics
```bash
$ pflow "summarize report.txt"
Here is a summary of the report...
```

### With Metrics (--output-format json)
```json
{
  "result": "Here is a summary of the report...",
  "metrics": {
    "planner": {
      "duration_ms": 5200,
      "cost_usd": 0.0156
    },
    "workflow": {
      "duration_ms": 3100,
      "cost_usd": 0.0089,
      "node_timings": {
        "read_file": 45,
        "llm_summarize": 2900,
        "format_output": 155
      }
    },
    "total": {
      "duration_ms": 8300,
      "cost_usd": 0.0245,
      "tokens_total": 4500
    }
  }
}
```

## Testing Approach

1. **Unit test each component** - MetricsCollector, TracingNodeWrapper, token extraction
2. **Integration test the full pipeline** - Planner → Workflow → Metrics output
3. **Test wrapper compatibility** - Ensure works with existing wrappers
4. **Performance benchmarks** - Measure overhead of tracing

## Future Vision

This infrastructure enables:
- Cost budgets and limits
- Performance optimization tools
- Usage analytics and trends
- Model comparison and recommendations
- Workflow profiling and bottleneck analysis

The unified metrics system transforms pflow from a workflow tool into a **cost-aware AI orchestration platform**.