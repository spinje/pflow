# Task 32: Unified Metrics and Tracing System for Workflow Execution

## ID
32

## Title
Unified Metrics and Tracing System for Workflow Execution

## Description
Implement a comprehensive observability system that provides tracing for workflow execution (similar to planner tracing from Task 27) and adds unified metrics collection for both planner and workflows. The system will track LLM token usage, calculate costs, measure performance, and output operational metrics in JSON format while maintaining detailed debug traces. This enables cost transparency, performance optimization, and complete visibility into AI operations.

## Status
pending

## Dependencies
- Task 27: Planner Debugging Capabilities - Builds upon the DebugWrapper and tracing infrastructure
- Task 24: Workflow Manager - Integrates with workflow loading and execution
- Task 18: Template Variable System - Must handle template resolution visibility
- Task 31: Automatic Namespacing - Must trace through namespace wrappers

## Priority
high

## Details
The unified metrics and tracing system addresses critical observability gaps in pflow, providing users with cost transparency and performance insights while maintaining comprehensive debug capabilities.

### Core Problems Being Solved
1. **No Workflow Execution Visibility**: Can't see what happens during workflow execution
2. **Hidden AI Costs**: Users don't know how much their LLM calls cost
3. **Missing Performance Metrics**: No timing data for optimization
4. **Fragmented Tracing**: Planner has tracing but workflows don't
5. **Token Usage Opacity**: Can't track token consumption across operations

### Two-Tier Information Architecture

#### Tier 1: User-Facing Metrics (JSON Output)
Operational data displayed with `--output-format json`:
```json
{
  "result": "... actual workflow output ...",
  "metrics": {
    "planner": {
      "duration_ms": 12500,
      "llm_calls": 6,
      "tokens": {"input": 15234, "output": 3421, "total": 18655},
      "cost_usd": 0.0234,
      "path_taken": "B"
    },
    "workflow": {
      "duration_ms": 8300,
      "nodes_executed": 5,
      "llm_calls": 2,
      "tokens": {"input": 2100, "output": 850, "total": 2950},
      "cost_usd": 0.0089,
      "node_timings": {
        "read_file_1": 45,
        "llm_summarize": 3200,
        "write_output": 125
      }
    },
    "total": {
      "duration_ms": 20800,
      "llm_calls": 8,
      "tokens_total": 21605,
      "cost_usd": 0.0323
    }
  }
}
```

#### Tier 2: Debug Traces (Trace Files)
Detailed execution data saved to `~/.pflow/traces/`:
- Full prompts and responses
- Shared store mutations
- Template resolutions
- Node parameters
- Error details

### Implementation Requirements

#### Core Components

1. **MetricsCollector** (`src/pflow/core/metrics.py`)
   - Unified metrics collection across planner and workflows
   - Token counting and cost calculation
   - Performance timing aggregation
   - Model-aware pricing

2. **TracingNodeWrapper** (`src/pflow/runtime/tracing_wrapper.py`)
   - Wraps workflow nodes during compilation
   - Captures shared store mutations
   - Records template resolutions
   - Tracks node execution timing

3. **WorkflowTraceCollector** (`src/pflow/runtime/workflow_trace.py`)
   - Accumulates workflow execution data
   - Records data flow between nodes
   - Handles namespace isolation visibility
   - Saves comprehensive trace files

4. **Pricing Configuration** (`~/.pflow/pricing.json`)
   - User-configurable model pricing
   - Default pricing for common models
   - Per-token cost calculation

### Key Design Decisions

1. **Wrapper Pattern Consistency**: Use same wrapper approach as planner tracing
2. **Outermost Wrapper Position**: TracingWrapper → NamespacedWrapper → TemplateAwareWrapper → BaseNode
3. **Shared Store Metrics Key**: Reserved `__metrics__` key for passing metrics through execution
4. **Incremental Aggregation**: Collect metrics during execution, not post-processing
5. **Selective Data Capture**: Filter large data objects to avoid trace bloat
6. **Model Pricing Config**: External configuration file with built-in defaults

### Technical Implementation

#### Enhanced Planner DebugWrapper
```python
class DebugWrapper:
    def __init__(self, node, debug_context: DebugContext, metrics: MetricsCollector):
        self.metrics = metrics
        # ... existing code ...

    def exec(self, prep_res):
        # ... existing LLM interception ...
        # Add metrics recording for LLM calls
        self.metrics.record_llm_call(
            context=f"planner.{node_name}",
            model=model_name,
            input_tokens=tokens['input'],
            output_tokens=tokens['output'],
            duration_ms=duration
        )
```

#### New TracingNodeWrapper for Workflows
```python
class TracingNodeWrapper:
    def __init__(self, node, node_id: str, trace: WorkflowTraceCollector, metrics: MetricsCollector):
        self._wrapped = node
        self.node_id = node_id
        self.trace = trace
        self.metrics = metrics
        # Copy critical attributes for Flow
        self.successors = node.successors
        self.params = getattr(node, 'params', {})

    def _run(self, shared):
        # Capture shared store before
        before_snapshot = self._snapshot_shared(shared)
        start_time = time.time()

        # Setup LLM interception if needed
        if self._is_llm_node():
            self._setup_llm_metrics_interception()

        # Execute node
        result = self._wrapped._run(shared)

        # Capture shared store after
        after_snapshot = self._snapshot_shared(shared)
        duration_ms = (time.time() - start_time) * 1000

        # Record execution data
        self.trace.record_node_execution(
            node_id=self.node_id,
            node_type=self._wrapped.__class__.__name__,
            duration_ms=duration_ms,
            shared_before=before_snapshot,
            shared_after=after_snapshot,
            mutations=self._calculate_mutations(before_snapshot, after_snapshot)
        )

        # Record metrics
        self.metrics.record_node_execution(self.node_id, duration_ms)

        return result
```

#### Compiler Integration
```python
def compile_ir_to_flow(ir_dict, registry, initial_params=None, trace_collector=None, metrics_collector=None):
    # ... existing compilation ...

    # Apply tracing wrapper if collectors provided
    if trace_collector and metrics_collector:
        for node_id, node in nodes.items():
            nodes[node_id] = TracingNodeWrapper(
                node, node_id, trace_collector, metrics_collector
            )

    return flow
```

#### CLI Integration
```python
def execute_json_workflow(ctx, ir_data, ..., metrics=None):
    # Create trace collector for workflows
    if ctx.obj.get("trace") or metrics:
        workflow_trace = WorkflowTraceCollector(ir_data)
        flow = compile_ir_to_flow(
            ir_data, registry, initial_params,
            trace_collector=workflow_trace,
            metrics_collector=metrics
        )
    else:
        flow = compile_ir_to_flow(ir_data, registry, initial_params)

    # Execute workflow
    shared_storage["__metrics__"] = metrics
    result = flow.run(shared_storage)

    # Save trace if needed
    if workflow_trace and (ctx.obj.get("trace") or not success):
        trace_file = workflow_trace.save_to_file()
        click.echo(f"📊 Workflow trace saved: {trace_file}", err=True)

    return result
```

### Token Extraction Strategy

Handle various LLM response formats:
```python
def extract_token_counts(response, model_name: str) -> dict:
    """Extract token counts from various response formats."""
    tokens = {"input": 0, "output": 0}

    if hasattr(response, 'usage'):
        usage = response.usage() if callable(response.usage) else response.usage

        if isinstance(usage, dict):
            # OpenAI format
            tokens["input"] = usage.get("prompt_tokens", 0)
            tokens["output"] = usage.get("completion_tokens", 0)
            # Anthropic format
            if tokens["input"] == 0:
                tokens["input"] = usage.get("input_tokens", 0)
                tokens["output"] = usage.get("output_tokens", 0)

    # Fallback: estimate from text length (~4 chars per token)
    if tokens["input"] == 0 and hasattr(response, 'text'):
        tokens["output"] = len(response.text) // 4

    return tokens
```

### Model Pricing Configuration

Default pricing with user overrides:
```python
# ~/.pflow/pricing.json (optional user config)
{
  "gpt-4": {"input": 0.03, "output": 0.06},
  "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
  "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
  "custom-model": {"input": 0.001, "output": 0.002}
}
```

### Integration Points

1. **CLI (`src/pflow/cli/main.py`)**
   - Create MetricsCollector at start
   - Pass through planner and workflow execution
   - Output metrics with JSON format

2. **Planner (`src/pflow/planning/flow.py`)**
   - Accept MetricsCollector in DebugContext
   - Record planner-specific metrics

3. **Compiler (`src/pflow/runtime/compiler.py`)**
   - Apply TracingNodeWrapper during node instantiation
   - Maintain wrapper ordering

4. **Workflow Execution**
   - Pass metrics through shared store
   - Aggregate node-level metrics

### Performance Considerations

1. **Efficient Snapshotting**: Use shallow copies for shared store snapshots
2. **Selective Capture**: Don't capture large binary data or files
3. **Lazy Serialization**: Only serialize traces when saving to disk
4. **Incremental Updates**: Update metrics in-place, don't recreate

## Test Strategy

### Unit Tests
- MetricsCollector aggregation and calculation
- TracingNodeWrapper attribute delegation
- Token extraction from various formats
- Cost calculation with different models
- Shared store mutation detection
- Template resolution tracking

### Integration Tests
- End-to-end planner + workflow with metrics
- Trace file generation for workflows
- Metrics output in JSON format
- Multi-layer wrapper compatibility
- LLM interception in workflow nodes

### Performance Tests
- Overhead of tracing wrapper
- Memory usage with large shared stores
- Trace file size limits

### Edge Cases
- Nodes without LLM usage
- Nested workflows
- Parallel node execution
- Missing token counts
- Unknown model pricing

## Future Enhancement Opportunities

1. **Cost Controls**
   - `--max-cost` flag to abort expensive operations
   - Cost warnings before execution
   - Budget tracking across runs

2. **Advanced Analytics**
   - Historical metrics storage
   - Usage trends visualization
   - Model performance comparison
   - Cost optimization suggestions

3. **Enhanced Tracing**
   - Distributed tracing for parallel nodes
   - Span correlation IDs
   - OpenTelemetry export
   - Real-time trace streaming

4. **Caching Metrics**
   - Cache hit/miss rates
   - Saved tokens from caching
   - Cost savings calculation

5. **Workflow Profiling**
   - Bottleneck identification
   - Resource usage tracking
   - Optimization recommendations

## Success Criteria

- ✅ Workflow execution has same visibility as planner
- ✅ All LLM calls tracked with token counts
- ✅ Costs calculated and displayed accurately
- ✅ Performance metrics available for all nodes
- ✅ JSON output includes comprehensive metrics
- ✅ Trace files capture complete execution data
- ✅ No significant performance degradation
- ✅ Works with existing wrapper layers
- ✅ Backward compatible (opt-in via flags)