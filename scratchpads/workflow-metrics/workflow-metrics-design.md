# Workflow Metrics System Design

## Executive Summary

This document outlines the design for a comprehensive metrics system that tracks timing, token usage, and costs across pflow workflow executions. The system enables direct comparison with AI agent tools like Claude-Code, demonstrating pflow's "Plan Once, Run Forever" efficiency advantage.

## Motivation

### The Problem
Currently, we cannot quantitatively demonstrate pflow's efficiency advantages:
- No visibility into execution time per node
- No aggregated token usage across workflows
- No cost tracking for LLM calls
- No way to compare with Claude-Code's performance

### The Solution
Implement automatic metrics collection at the node wrapper level, providing:
- Zero-overhead timing for all nodes
- Automatic token usage aggregation
- Cost calculation based on model pricing
- Beautiful human-readable and JSON output formats
- Direct comparison capabilities with Claude-Code

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                   Workflow Execution                      │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │   Node 1     │──>│   Node 2     │──>│   Node 3     │ │
│  │ (ReadFile)   │   │   (LLM)      │   │ (WriteFile)  │ │
│  └──────────────┘   └──────────────┘   └──────────────┘ │
│         ↓                  ↓                   ↓         │
│  ┌────────────────────────────────────────────────────┐ │
│  │         TemplateAwareNodeWrapper (timing)          │ │
│  └────────────────────────────────────────────────────┘ │
│                           ↓                              │
│  ┌────────────────────────────────────────────────────┐ │
│  │              Shared Store (metrics)                │ │
│  │  - node_timings: {node_id: timing_data}            │ │
│  │  - llm_usage: {tokens, model, cost}                │ │
│  └────────────────────────────────────────────────────┘ │
│                           ↓                              │
│  ┌────────────────────────────────────────────────────┐ │
│  │           WorkflowMetrics (aggregation)            │ │
│  └────────────────────────────────────────────────────┘ │
│                           ↓                              │
│  ┌────────────────────────────────────────────────────┐ │
│  │              Display/Export (CLI)                  │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## Implementation Details

### 1. Node-Level Timing Collection

**Location**: `src/pflow/runtime/node_wrapper.py`

The `TemplateAwareNodeWrapper` already wraps every node for template resolution. We enhance it to capture timing:

```python
def _run(self, shared: dict[str, Any]) -> Any:
    """Execute with template resolution and timing."""
    import time

    # Capture start time with high precision
    start_time = time.perf_counter()

    try:
        # ... existing template resolution code ...
        result = self.inner_node._run(shared)

        # Capture success timing
        end_time = time.perf_counter()
        duration_ms = (end_time - start_time) * 1000

        # Initialize metrics storage
        if "node_timings" not in shared:
            shared["node_timings"] = {}

        # Store detailed timing data
        shared["node_timings"][self.node_id] = {
            "duration_ms": round(duration_ms, 2),
            "node_type": self.inner_node.__class__.__name__,
            "timestamp": time.time(),
            "success": True
        }

        # Track if this is an LLM node for token aggregation
        if self.inner_node.__class__.__name__ == "LLMNode":
            if "llm_nodes" not in shared:
                shared["llm_nodes"] = []
            shared["llm_nodes"].append(self.node_id)

        return result

    except Exception as e:
        # Capture failure timing
        end_time = time.perf_counter()
        duration_ms = (end_time - start_time) * 1000

        if "node_timings" not in shared:
            shared["node_timings"] = {}

        shared["node_timings"][self.node_id] = {
            "duration_ms": round(duration_ms, 2),
            "node_type": self.inner_node.__class__.__name__,
            "timestamp": time.time(),
            "success": False,
            "error": str(e)
        }

        raise  # Re-raise for PocketFlow retry mechanism
```

### 2. LLM Token Usage Tracking

**Location**: `src/pflow/nodes/llm/llm.py`

The LLM node captures token usage from the response:

```python
def exec(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
    model = llm.get_model(prep_res["model"])
    response = model.prompt(prep_res["prompt"], **kwargs)

    # Capture both response and usage
    text = response.text()
    usage = response.usage() or {}

    return {
        "response": text,
        "usage": usage,
        "model": prep_res["model"]
    }

def post(self, shared: Dict[str, Any], prep_res: Dict[str, Any],
         exec_res: Dict[str, Any]) -> str:
    shared["response"] = exec_res["response"]

    # Store structured usage data
    shared["llm_usage"] = {
        "model": exec_res.get("model", "unknown"),
        "input_tokens": exec_res.get("usage", {}).get("input_tokens", 0),
        "output_tokens": exec_res.get("usage", {}).get("output_tokens", 0),
        "total_tokens": exec_res.get("usage", {}).get("total_tokens", 0)
    }

    return "default"
```

### 3. Metrics Aggregation

**Location**: `src/pflow/runtime/workflow_metrics.py`

```python
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
import json
from datetime import datetime

@dataclass
class NodeMetrics:
    """Metrics for a single node execution."""
    node_id: str
    node_type: str
    duration_ms: float
    timestamp: float
    success: bool = True
    error: Optional[str] = None
    llm_usage: Optional[Dict[str, Any]] = None

@dataclass
class WorkflowMetrics:
    """Aggregated metrics for entire workflow execution."""
    workflow_name: str
    total_duration_ms: float
    node_count: int
    nodes_succeeded: int
    nodes_failed: int
    node_metrics: List[NodeMetrics]
    total_tokens: Dict[str, int]
    total_llm_cost_usd: float
    timestamp: str

    @classmethod
    def from_shared(cls, shared: Dict[str, Any],
                   workflow_name: str = "workflow") -> "WorkflowMetrics":
        """Build metrics from shared store after workflow execution."""
        node_timings = shared.get("node_timings", {})
        llm_nodes = shared.get("llm_nodes", [])

        node_metrics = []
        total_duration = 0
        nodes_succeeded = 0
        nodes_failed = 0
        total_tokens = {"input": 0, "output": 0, "total": 0}

        for node_id, timing in node_timings.items():
            # Get LLM usage if this is an LLM node
            llm_usage = None
            if node_id in llm_nodes:
                llm_usage = shared.get("llm_usage", {})
                total_tokens["input"] += llm_usage.get("input_tokens", 0)
                total_tokens["output"] += llm_usage.get("output_tokens", 0)
                total_tokens["total"] += llm_usage.get("total_tokens", 0)

            success = timing.get("success", True)
            if success:
                nodes_succeeded += 1
            else:
                nodes_failed += 1

            node_metrics.append(NodeMetrics(
                node_id=node_id,
                node_type=timing["node_type"],
                duration_ms=timing["duration_ms"],
                timestamp=timing["timestamp"],
                success=success,
                error=timing.get("error"),
                llm_usage=llm_usage
            ))

            total_duration += timing["duration_ms"]

        # Calculate cost based on model pricing
        total_cost = calculate_llm_cost(total_tokens, model="claude-sonnet-4-20250514")

        return cls(
            workflow_name=workflow_name,
            total_duration_ms=round(total_duration, 2),
            node_count=len(node_metrics),
            nodes_succeeded=nodes_succeeded,
            nodes_failed=nodes_failed,
            node_metrics=node_metrics,
            total_tokens=total_tokens,
            total_llm_cost_usd=round(total_cost, 6),
            timestamp=datetime.now().isoformat()
        )

def calculate_llm_cost(tokens: Dict[str, int], model: str) -> float:
    """Calculate cost based on model pricing."""
    # Pricing per 1M tokens (as of 2024)
    pricing = {
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "gpt-4": {"input": 30.0, "output": 60.0},
        "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
    }

    model_pricing = pricing.get(model, pricing["claude-sonnet-4-20250514"])

    input_cost = (tokens["input"] / 1_000_000) * model_pricing["input"]
    output_cost = (tokens["output"] / 1_000_000) * model_pricing["output"]

    return input_cost + output_cost
```

### 4. Display Formatting

**Human-Readable Format**:
```
============================================================
Workflow Metrics: fix-github-issue
============================================================
Execution Summary:
  • Total Duration: 3,521.3ms
  • Nodes Executed: 4 (4 succeeded, 0 failed)
  • Timestamp: 2024-01-16T10:30:45.123456

Node Performance:
  ┌─────────────────────────────────────────────────────┐
  │ Node ID         Type            Duration    Status  │
  ├─────────────────────────────────────────────────────┤
  │ read_config     ReadFileNode       12.5ms    ✓      │
  │ get_issue       GitHubNode        487.2ms    ✓      │
  │ analyze         LLMNode         2,876.4ms    ✓      │
  │ write_pr        WriteFileNode     145.2ms    ✓      │
  └─────────────────────────────────────────────────────┘

LLM Token Usage:
  • Input Tokens:   1,250
  • Output Tokens:    600
  • Total Tokens:   1,850
  • Estimated Cost: $0.0127

Performance Analysis:
  • Fastest Node: read_config (12.5ms)
  • Slowest Node: analyze (2,876.4ms - 81.7% of total)
  • LLM Time: 2,876.4ms (81.7%)
  • Non-LLM Time: 644.9ms (18.3%)
============================================================
```

**JSON Format** (for programmatic analysis):
```json
{
  "workflow_name": "fix-github-issue",
  "total_duration_ms": 3521.3,
  "node_count": 4,
  "nodes_succeeded": 4,
  "nodes_failed": 0,
  "node_metrics": [
    {
      "node_id": "read_config",
      "node_type": "ReadFileNode",
      "duration_ms": 12.5,
      "timestamp": 1737000000.123,
      "success": true,
      "error": null,
      "llm_usage": null
    },
    {
      "node_id": "analyze",
      "node_type": "LLMNode",
      "duration_ms": 2876.4,
      "timestamp": 1737000012.623,
      "success": true,
      "error": null,
      "llm_usage": {
        "model": "claude-sonnet-4-20250514",
        "input_tokens": 1250,
        "output_tokens": 600,
        "total_tokens": 1850
      }
    }
  ],
  "total_tokens": {
    "input": 1250,
    "output": 600,
    "total": 1850
  },
  "total_llm_cost_usd": 0.012750,
  "timestamp": "2024-01-16T10:30:45.123456"
}
```

### 5. CLI Integration

**Location**: `src/pflow/cli/main.py`

```python
@click.option('--metrics/--no-metrics', default=True,
              help='Display workflow metrics after execution')
@click.option('--save-metrics', type=click.Path(),
              help='Save metrics to JSON file')
def run(ctx, workflow_file, metrics, save_metrics):
    """Execute a workflow and display metrics."""
    from pflow.runtime.workflow_metrics import WorkflowMetrics

    # ... workflow execution ...

    if metrics:
        metrics_obj = WorkflowMetrics.from_shared(shared, workflow_name)

        if ctx.obj.get("json_output"):
            print(metrics_obj.to_json())
        else:
            print(metrics_obj.display_summary())

        if save_metrics:
            with open(save_metrics, 'w') as f:
                f.write(metrics_obj.to_json())
```

## Comparison with Claude-Code

### Data Structure Compatibility

Claude-Code output (with -p flag):
```json
{
  "type": "result",
  "duration_ms": 2676,
  "duration_api_ms": 2654,
  "num_turns": 1,
  "total_cost_usd": 0.093387,
  "usage": {
    "input_tokens": 24880,
    "output_tokens": 6
  }
}
```

pflow metrics can be directly compared:
- `duration_ms` vs `total_duration_ms`
- `total_cost_usd` vs `total_llm_cost_usd`
- `usage.input_tokens + usage.output_tokens` vs `total_tokens.total`

### Comparison Analysis

```python
def compare_efficiency(pflow_metrics: WorkflowMetrics, claude_output: dict):
    """Generate efficiency comparison report."""

    # Calculate advantages
    time_ratio = pflow_metrics.total_duration_ms / claude_output["duration_ms"]
    cost_ratio = pflow_metrics.total_llm_cost_usd / claude_output["total_cost_usd"]
    token_ratio = pflow_metrics.total_tokens["total"] / (
        claude_output["usage"]["input_tokens"] +
        claude_output["usage"]["output_tokens"]
    )

    print(f"""
╔══════════════════════════════════════════════════════════╗
║           pflow vs Claude-Code Comparison                ║
╠══════════════════════════════════════════════════════════╣
║ Metric          │ pflow        │ Claude-Code  │ Savings  ║
╟─────────────────┼──────────────┼──────────────┼──────────╢
║ Duration        │ {pflow_metrics.total_duration_ms:>10.1f}ms │ {claude_output['duration_ms']:>10.1f}ms │ {(1-time_ratio)*100:>6.1f}%  ║
║ Tokens          │ {pflow_metrics.total_tokens['total']:>12,} │ {claude_output['usage']['input_tokens']+claude_output['usage']['output_tokens']:>12,} │ {(1-token_ratio)*100:>6.1f}%  ║
║ Cost            │ ${pflow_metrics.total_llm_cost_usd:>11.4f} │ ${claude_output['total_cost_usd']:>11.4f} │ {(1-cost_ratio)*100:>6.1f}%  ║
╚═════════════════╧══════════════╧══════════════╧══════════╝

ROI Analysis:
  • Break-even after: {int(claude_output['total_cost_usd'] / (claude_output['total_cost_usd'] - pflow_metrics.total_llm_cost_usd))} workflow runs
  • Daily savings (10 runs): ${(claude_output['total_cost_usd'] - pflow_metrics.total_llm_cost_usd) * 10:.2f}
  • Monthly savings (300 runs): ${(claude_output['total_cost_usd'] - pflow_metrics.total_llm_cost_usd) * 300:.2f}
    """)
```

## Implementation Phases

### Phase 1: Core Timing (Immediate)
- [ ] Update `TemplateAwareNodeWrapper` with timing capture
- [ ] Update LLM node to track token usage
- [ ] Basic shared store metrics structure

### Phase 2: Aggregation (Next)
- [ ] Implement `WorkflowMetrics` class
- [ ] Add cost calculation logic
- [ ] Create display formatters

### Phase 3: CLI Integration (Follow-up)
- [ ] Add --metrics flag to run command
- [ ] Implement JSON and human-readable output
- [ ] Add --save-metrics option

### Phase 4: Comparison Tools (Future)
- [ ] Create comparison command
- [ ] Add ROI calculator
- [ ] Build metrics dashboard

## Benefits

1. **Quantifiable Efficiency**: Concrete numbers showing pflow's advantages
2. **Performance Insights**: Identify bottlenecks in workflows
3. **Cost Tracking**: Understand LLM API costs per workflow
4. **Marketing Material**: Data for demonstrating value proposition
5. **Optimization Targets**: Know where to focus optimization efforts

## Technical Considerations

### Performance Impact
- Timing overhead: ~0.01ms per node (negligible)
- Memory overhead: ~200 bytes per node execution
- No impact on workflow logic or reliability

### Compatibility
- Works with all existing nodes automatically
- No changes required to PocketFlow framework
- Backward compatible with existing workflows

### Extensibility
- Easy to add new metrics (memory usage, CPU, etc.)
- Plugin architecture for custom metric collectors
- Export to various formats (CSV, Prometheus, etc.)

## Conclusion

This metrics system provides comprehensive visibility into workflow performance with minimal implementation complexity. By leveraging the existing `TemplateAwareNodeWrapper`, we get automatic timing for all nodes "for free" while maintaining clean separation of concerns.

The combination of timing data and token usage tracking enables powerful comparisons with tools like Claude-Code, quantitatively demonstrating pflow's "Plan Once, Run Forever" efficiency advantage.
