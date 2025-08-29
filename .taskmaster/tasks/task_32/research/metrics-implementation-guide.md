# Unified Metrics and Tracing System - Implementation Guide

## Overview

The Unified Metrics and Tracing System (Task 32) provides comprehensive cost and performance tracking for pflow workflows. This system must track costs from two distinct sources: planning (one-time workflow compilation) and execution (including LLM nodes).

## Core Requirements

### 1. Dual-Layer Cost Tracking

The system must separately track:

#### Planning Costs (One-time)
- **Discovery Phase**: Checking if workflow already exists (~$0.02)
- **Component Browsing**: Selecting relevant nodes/workflows (~$0.10)
- **Parameter Discovery**: Extracting parameters from natural language (~$0.05)
- **Workflow Generation**: Creating workflow IR (~$0.50)
- **Validation**: Checking generated workflow (~$0.02)
- **Metadata Generation**: Creating name/description/tags (~$0.04)

Total planning typically costs $0.50-1.00 and happens ONCE per unique workflow.

#### Execution Costs (Per-run)
- **LLM Nodes**: Any workflow containing LLM nodes incurs cost per execution
- **Other Nodes**: Shell, file operations, etc. have zero cost
- **Caching**: Both workflow structure AND LLM node results can be cached

### 2. JSON Output Format

The metrics must support `--output-format json` flag, producing output compatible with Claude Code for direct comparison:

```json
{
  "type": "result",
  "subtype": "success",  // or "cached" when fully cached
  "is_error": false,
  "duration_ms": 32500,
  "total_cost_usd": 0.84,
  "planning_cost_usd": 0.73,
  "execution_cost_usd": 0.11,
  "saved_usd": 0.0,  // Cumulative savings from caching
  "cache_hit": false,
  "execution_count": 1,
  "workflow_id": "analyze-commits-abc123",
  "usage": {
    "planning_tokens": 15900,
    "execution_tokens": 2500,
    "total_tokens": 18400
  }
}
```

## Technical Implementation Details

### 1. LLM Call Interception

All LLM calls in pflow go through Simon Willison's `llm` library. The system needs to intercept these calls at two levels:

#### Planning Nodes (6 total in `src/pflow/planning/nodes.py`):
1. `WorkflowDiscoveryNode` - Determines Path A (reuse) vs Path B (generate)
2. `ComponentBrowsingNode` - Selects relevant components (Path B only)
3. `ParameterDiscoveryNode` - Extracts parameters (Path B only)
4. `ParameterMappingNode` - Maps values to parameters (both paths)
5. `WorkflowGeneratorNode` - Generates workflow IR (Path B only)
6. `MetadataGenerationNode` - Creates metadata (Path B only)

#### Runtime Nodes:
- `LLMNode` (`src/pflow/nodes/llm/llm.py`) - User-defined LLM calls in workflows
- Any future nodes that make LLM calls

### 2. Token Counting Challenge

The `llm` library doesn't consistently expose token counts. The implementation must:
- Attempt to extract from response.usage if available
- Fall back to estimation using tiktoken or similar
- Track both input and output tokens separately

### 3. Model-Specific Pricing

Maintain a pricing table for common models:

```python
MODEL_PRICING = {
    # OpenAI
    'gpt-4': {'input': 0.03, 'output': 0.06},        # per 1K tokens
    'gpt-4-turbo': {'input': 0.01, 'output': 0.03},
    'gpt-3.5-turbo': {'input': 0.0015, 'output': 0.002},

    # Anthropic (via llm library names)
    'anthropic/claude-3-opus': {'input': 0.015, 'output': 0.075},
    'anthropic/claude-3-sonnet': {'input': 0.003, 'output': 0.015},
    'anthropic/claude-3-haiku': {'input': 0.00025, 'output': 0.00125},
    'anthropic/claude-sonnet-4-0': {'input': 0.003, 'output': 0.015},  # Current default
}
```

### 4. Caching Layers

The system must track two types of caching:

#### Workflow Cache
- If workflow already exists (Path A), planning cost is minimal (~$0.02 for discovery only)
- Tracked via `planning_cached: bool` flag

#### Execution Cache
- LLM node results can be cached based on input hash
- Shell/file nodes have no cost to cache
- Tracked via `cache_hit: bool` for overall execution

### 5. Metrics Storage

Store metrics in `~/.pflow/metrics/`:

```python
# Per-workflow metrics file
~/.pflow/metrics/{workflow_id}.json
{
  "workflow_id": "analyze-commits-abc123",
  "first_run": "2024-01-15T10:30:00Z",
  "planning_cost": 0.73,
  "execution_history": [
    {"timestamp": "...", "cost": 0.11, "cached": false},
    {"timestamp": "...", "cost": 0.00, "cached": true},
  ],
  "total_runs": 10,
  "total_saved": 7.30
}
```

## Integration Points

### 1. Extend TraceCollector

The existing `TraceCollector` class in `src/pflow/planning/debug.py` already tracks:
- LLM call timestamps and durations
- Node execution times
- Attempts to capture token usage

Enhance it to:
- Calculate costs based on model and tokens
- Separate planning vs execution costs
- Write metrics to persistent storage

### 2. Workflow Executor Enhancement

The `WorkflowExecutor` in `src/pflow/runtime/workflow_executor.py` currently has no metrics. Add:
- Per-node execution tracking
- LLM node cost calculation
- Overall execution metrics aggregation

### 3. CLI Integration

In the main CLI (`src/pflow/cli/main.py`), add:
- `--output-format json` flag support
- Metrics display in human-readable format (default)
- Cost summaries after execution

## Cost Calculation Formula

```python
def calculate_llm_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for an LLM call."""
    if model not in MODEL_PRICING:
        # Log warning and use a default or return 0
        return 0.0

    pricing = MODEL_PRICING[model]
    input_cost = (input_tokens / 1000) * pricing['input']
    output_cost = (output_tokens / 1000) * pricing['output']

    return round(input_cost + output_cost, 6)  # 6 decimal places for precision
```

## Critical Considerations

### 1. Token Estimation Fallback

Since the `llm` library may not provide token counts:

```python
def estimate_tokens(text: str, model: str) -> int:
    """Estimate token count when not provided by API."""
    # Rough estimation: ~1 token per 4 characters for English
    # Better: use tiktoken for accurate counting
    if 'gpt' in model:
        # Use tiktoken for OpenAI models
        import tiktoken
        encoding = tiktoken.encoding_for_model(model.replace('gpt-', 'gpt-'))
        return len(encoding.encode(text))
    else:
        # Fallback for other models
        return len(text) // 4
```

### 2. Path A vs Path B Detection

The metrics system must detect which planning path was taken:
- **Path A** (reuse): Only Discovery + Parameter Mapping (~$0.02-0.05)
- **Path B** (generate): Full planning pipeline (~$0.50-1.00)

This is determined by the `WorkflowDiscoveryNode` result.

### 3. Execution Caching Strategy

For LLMNode caching:
```python
def get_cache_key(node_id: str, params: dict, shared_inputs: dict) -> str:
    """Generate stable cache key for LLM node execution."""
    # Include node ID, parameters, and relevant shared store values
    cache_data = {
        'node_id': node_id,
        'params': params,
        'inputs': shared_inputs  # Only include values this node reads
    }
    return hashlib.sha256(json.dumps(cache_data, sort_keys=True).encode()).hexdigest()
```

### 4. Cumulative Savings Calculation

Track savings across multiple executions:
```python
def calculate_savings(workflow_id: str, current_run: int) -> float:
    """Calculate cumulative savings from caching."""
    if current_run == 1:
        return 0.0

    # Load metrics history
    metrics = load_workflow_metrics(workflow_id)
    first_run_cost = metrics['planning_cost'] + metrics['execution_history'][0]['cost']

    # Savings = (cost if regenerated each time) - (actual cost paid)
    potential_cost = first_run_cost * current_run
    actual_cost = metrics['planning_cost'] + sum(e['cost'] for e in metrics['execution_history'])

    return round(potential_cost - actual_cost, 2)
```

## Expected Behavior Examples

### First Run (Path B - Full Generation)
```json
{
  "total_cost_usd": 0.84,
  "planning_cost_usd": 0.73,
  "execution_cost_usd": 0.11,
  "cache_hit": false,
  "saved_usd": 0.0
}
```

### Second Run (Cached)
```json
{
  "total_cost_usd": 0.0,
  "planning_cost_usd": 0.0,
  "execution_cost_usd": 0.0,
  "cache_hit": true,
  "saved_usd": 0.84
}
```

### Different Input (Path A - Reuse Workflow)
```json
{
  "total_cost_usd": 0.13,
  "planning_cost_usd": 0.02,  // Just discovery + parameter mapping
  "execution_cost_usd": 0.11,  // LLM node with new input
  "cache_hit": false,
  "saved_usd": 0.71  // Saved most of planning cost
}
```

## Implementation Priority

1. **Core Metrics Class**: Create `PflowMetrics` dataclass with all fields
2. **LLM Call Wrapper**: Intercept all LLM calls to capture costs
3. **Planning Integration**: Enhance existing `TraceCollector`
4. **Execution Tracking**: Add metrics to `WorkflowExecutor`
5. **JSON Output**: Implement `--output-format json` in CLI
6. **Persistent Storage**: Save metrics for historical tracking
7. **Human-Readable Display**: Default output format with cost breakdown

## Testing Considerations

The implementation should be tested with:
- Mock LLM calls with known token counts
- Both Path A (reuse) and Path B (generation) scenarios
- Various caching states
- Different models with different pricing
- Edge cases like errors and timeouts

This metrics system is critical for demonstrating pflow's value proposition: "compile once, run forever" with transparent cost tracking.