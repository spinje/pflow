# Task 32: Unified Metrics and Tracing System - Complete Implementation Guide

## Executive Summary

You are implementing a unified observability system that provides cost tracking and debugging capabilities for pflow. The system has three modes:
1. **Default** (no flags): Zero overhead, no collection
2. **Metrics** (`--output-format json`): Lightweight cost/timing metrics
3. **Tracing** (`--trace` / `--trace-planner`): Full debugging details

The core insight: Metrics and tracing are the same telemetry at different verbosity levels, collected through a single instrumentation layer.

## 🏗️ Architecture Overview

```
User Input
    ↓
CLI Layer (main.py)
    ├─→ Creates MetricsCollector if --output-format json
    ├─→ Creates TraceCollector if --trace flags
    ↓
Planner Execution (if natural language)
    ├─→ DebugWrapper (existing, enhance with metrics)
    ├─→ 6 LLM calls tracked
    ↓
Workflow Compilation (compiler.py)
    ├─→ Apply InstrumentedNodeWrapper (NEW)
    ├─→ Wrapper order: Instrumented → Namespaced → TemplateAware → Node
    ↓
Workflow Execution
    ├─→ Each node wrapped captures timing
    ├─→ LLM nodes append to shared["__llm_calls__"]
    ↓
Output (main.py)
    ├─→ JSON includes top-level metrics
    └─→ Traces saved to ~/.pflow/debug/
```

## 🔴 Critical Implementation Facts (All Verified)

### 1. LLM Usage Tracking
- **Current behavior**: `shared["llm_usage"]` is OVERWRITTEN on each LLM call
- **Your solution**: Create `shared["__llm_calls__"]` list to accumulate
- **Structure when available**:
  ```python
  {
      "model": "anthropic/claude-sonnet-4-0",
      "input_tokens": 1250,
      "output_tokens": 600,
      "total_tokens": 1850,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 0
  }
  ```
- **When unavailable**: Empty dict `{}`

### 2. Timing Implementation
- **Current issue**: Code uses `time.time()` (wrong!)
- **You must use**: `time.perf_counter()` for accuracy
- **Example from TimedResponse** (debug.py:45-57):
  ```python
  start = time.perf_counter()
  result = self._response.json()
  duration = time.perf_counter() - start
  ```

### 3. Trace File Locations
- **Directory**: `~/.pflow/debug/` (NOT `~/.pflow/traces/`)
- **Filename format**: `pflow-trace-YYYYMMDD-HHMMSS.json`
- **UUID**: Store INSIDE JSON as `execution_id`, not in filename
- **Example** (debug.py:361-362):
  ```python
  timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
  filename = f"pflow-trace-{timestamp}.json"
  ```

### 4. CLI Flags
- **Existing**: `--trace` (currently for planner only)
- **You must add**: `--trace-planner` (new flag)
- **New behavior**: `--trace` for workflows, `--trace-planner` for planner
- **Location**: `/src/pflow/cli/main.py:1313-1317`

### 5. Wrapper Delegation Pattern
All wrappers MUST follow this pattern (from node_wrapper.py:174-192):
```python
def __getattr__(self, name: str) -> Any:
    # Prevent infinite recursion during copy operations
    if name in ("__setstate__", "__getstate__", "__getnewargs__", "__getnewargs_ex__"):
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    # Get inner_node without triggering __getattr__ again
    inner = object.__getattribute__(self, "inner_node")
    return getattr(inner, name)
```

### 6. Template Resolution
- **Currently**: Only logged, not captured
- **You must**: Capture resolutions in trace
- **Available info**: Original template string + resolved value
- **Location of resolution**: node_wrapper.py:112-159

## 📝 Implementation Components

### 1. MetricsCollector (`src/pflow/core/metrics.py`) - NEW FILE

```python
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
import time

@dataclass
class MetricsCollector:
    """Lightweight metrics aggregation for pflow execution."""

    start_time: float = field(default_factory=time.perf_counter)
    planner_start: Optional[float] = None
    planner_end: Optional[float] = None
    workflow_start: Optional[float] = None
    workflow_end: Optional[float] = None

    planner_nodes: Dict[str, float] = field(default_factory=dict)
    workflow_nodes: Dict[str, float] = field(default_factory=dict)

    def record_planner_start(self):
        self.planner_start = time.perf_counter()

    def record_planner_end(self):
        self.planner_end = time.perf_counter()

    def record_workflow_start(self):
        self.workflow_start = time.perf_counter()

    def record_workflow_end(self):
        self.workflow_end = time.perf_counter()

    def record_node_execution(self, node_id: str, duration_ms: float, is_planner: bool = False):
        if is_planner:
            self.planner_nodes[node_id] = duration_ms
        else:
            self.workflow_nodes[node_id] = duration_ms

    def calculate_costs(self, llm_calls: List[Dict[str, Any]]) -> float:
        """Calculate total cost from accumulated LLM calls."""
        # Pricing per million tokens (from test_prompt_accuracy.py)
        MODEL_PRICING = {
            "anthropic/claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
            "anthropic/claude-sonnet-4-0": {"input": 3.00, "output": 15.00},
            "gpt-4": {"input": 30.0, "output": 60.0},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            # Add more models as needed
        }

        total_cost = 0.0
        for call in llm_calls:
            model = call.get("model", "anthropic/claude-sonnet-4-0")
            pricing = MODEL_PRICING.get(model, MODEL_PRICING["anthropic/claude-sonnet-4-0"])

            input_tokens = call.get("input_tokens", 0)
            output_tokens = call.get("output_tokens", 0)

            # Pricing is per million tokens
            input_cost = (input_tokens / 1_000_000) * pricing["input"]
            output_cost = (output_tokens / 1_000_000) * pricing["output"]

            total_cost += input_cost + output_cost

        return round(total_cost, 6)

    def get_summary(self, llm_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate metrics summary for JSON output."""
        # Calculate durations
        total_duration = (time.perf_counter() - self.start_time) * 1000
        planner_duration = None
        if self.planner_start and self.planner_end:
            planner_duration = (self.planner_end - self.planner_start) * 1000

        workflow_duration = None
        if self.workflow_start and self.workflow_end:
            workflow_duration = (self.workflow_end - self.workflow_start) * 1000

        # Aggregate token counts
        total_input = sum(call.get("input_tokens", 0) for call in llm_calls)
        total_output = sum(call.get("output_tokens", 0) for call in llm_calls)

        # Calculate costs
        total_cost = self.calculate_costs(llm_calls)

        # Count nodes
        num_nodes = len(self.planner_nodes) + len(self.workflow_nodes)

        return {
            "duration_ms": round(total_duration, 2),
            "duration_planner_ms": round(planner_duration, 2) if planner_duration else None,
            "total_cost_usd": total_cost,
            "num_nodes": num_nodes,
            "metrics": {
                "planner": {
                    "duration_ms": round(planner_duration, 2) if planner_duration else None,
                    "nodes_executed": len(self.planner_nodes),
                    "node_timings": self.planner_nodes
                } if self.planner_nodes else None,
                "workflow": {
                    "duration_ms": round(workflow_duration, 2) if workflow_duration else None,
                    "nodes_executed": len(self.workflow_nodes),
                    "node_timings": self.workflow_nodes
                } if self.workflow_nodes else None,
                "total": {
                    "tokens_input": total_input,
                    "tokens_output": total_output,
                    "tokens_total": total_input + total_output,
                    "cost_usd": total_cost
                }
            }
        }
```

### 2. InstrumentedNodeWrapper (`src/pflow/runtime/instrumented_wrapper.py`) - NEW FILE

```python
import time
from typing import Any, Dict, Optional
import copy

class InstrumentedNodeWrapper:
    """Unified wrapper for metrics and optional tracing."""

    def __init__(self, inner_node: Any, node_id: str,
                 metrics_collector: Optional[Any] = None,
                 trace_collector: Optional[Any] = None):
        self.inner_node = inner_node
        self.node_id = node_id
        self.metrics = metrics_collector
        self.trace = trace_collector

    def __getattr__(self, name: str) -> Any:
        """Delegate all other attributes to inner node."""
        if name in ("__setstate__", "__getstate__", "__getnewargs__", "__getnewargs_ex__"):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        inner = object.__getattribute__(self, "inner_node")
        return getattr(inner, name)

    def __rshift__(self, action_str: str):
        """Delegate >> operator."""
        return self.inner_node >> action_str

    def __sub__(self, action_str: str):
        """Delegate - operator."""
        return self.inner_node - action_str

    def _run(self, shared: Dict[str, Any]) -> Any:
        """Execute with metrics and optional tracing."""
        # Capture state before execution
        start_time = time.perf_counter()
        shared_before = dict(shared) if self.trace else None

        # Initialize LLM calls list if needed
        if "__llm_calls__" not in shared:
            shared["__llm_calls__"] = []

        try:
            # Execute the inner node
            result = self.inner_node._run(shared)

            # Calculate duration
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Record metrics if collector present
            if self.metrics:
                self.metrics.record_node_execution(
                    self.node_id,
                    duration_ms,
                    is_planner=False
                )

            # Capture LLM usage if present
            if "llm_usage" in shared and shared["llm_usage"]:
                # Append to accumulator list
                llm_call_data = shared["llm_usage"].copy()
                llm_call_data["node_id"] = self.node_id
                llm_call_data["duration_ms"] = duration_ms
                shared["__llm_calls__"].append(llm_call_data)

            # Record trace if collector present
            if self.trace:
                shared_after = dict(shared)
                self.trace.record_node_execution(
                    node_id=self.node_id,
                    node_type=type(self.inner_node).__name__,
                    duration_ms=duration_ms,
                    shared_before=shared_before,
                    shared_after=shared_after,
                    success=True,
                    error=None
                )

            return result

        except Exception as e:
            # Still record metrics and trace on failure
            duration_ms = (time.perf_counter() - start_time) * 1000

            if self.metrics:
                self.metrics.record_node_execution(self.node_id, duration_ms, is_planner=False)

            if self.trace:
                self.trace.record_node_execution(
                    node_id=self.node_id,
                    node_type=type(self.inner_node).__name__,
                    duration_ms=duration_ms,
                    shared_before=shared_before,
                    shared_after=dict(shared),
                    success=False,
                    error=str(e)
                )

            raise
```

### 3. WorkflowTraceCollector (`src/pflow/runtime/workflow_trace.py`) - NEW FILE

```python
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

class WorkflowTraceCollector:
    """Detailed trace collection for workflow debugging."""

    def __init__(self, workflow_name: str = "workflow"):
        self.workflow_name = workflow_name
        self.execution_id = str(uuid.uuid4())
        self.start_time = datetime.now()
        self.events: List[Dict[str, Any]] = []

    def record_node_execution(self, node_id: str, node_type: str,
                             duration_ms: float, shared_before: Dict[str, Any],
                             shared_after: Dict[str, Any], success: bool,
                             error: Optional[str] = None):
        """Record detailed node execution data."""
        event = {
            "node_id": node_id,
            "node_type": node_type,
            "duration_ms": duration_ms,
            "success": success,
            "shared_before": self._filter_shared(shared_before),
            "shared_after": self._filter_shared(shared_after),
            "mutations": self._calculate_mutations(shared_before, shared_after),
            "timestamp": datetime.now().isoformat()
        }

        if error:
            event["error"] = error

        # Check for template resolutions (if logged)
        # TODO: Implement template resolution capture

        # Check for LLM call details
        if "llm_usage" in shared_after:
            event["llm_call"] = shared_after["llm_usage"]

        self.events.append(event)

    def _filter_shared(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """Filter sensitive or large data from shared store."""
        filtered = {}
        for key, value in shared.items():
            # Skip system keys except our tracking keys
            if key.startswith("__") and key not in ["__llm_calls__", "__metrics__"]:
                continue

            # Truncate large strings
            if isinstance(value, str) and len(value) > 1000:
                filtered[key] = value[:1000] + "... [truncated]"
            elif isinstance(value, bytes):
                filtered[key] = f"<binary data: {len(value)} bytes>"
            else:
                filtered[key] = value

        return filtered

    def _calculate_mutations(self, before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, List[str]]:
        """Calculate what changed in shared store."""
        added = list(set(after.keys()) - set(before.keys()))
        removed = list(set(before.keys()) - set(after.keys()))
        modified = [k for k in before.keys() & after.keys() if before[k] != after[k]]

        return {
            "added": added,
            "removed": removed,
            "modified": modified
        }

    def save_to_file(self) -> Path:
        """Save trace to JSON file."""
        # Create directory
        trace_dir = Path.home() / ".pflow" / "debug"
        trace_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"pflow-trace-workflow-{timestamp}.json"
        filepath = trace_dir / filename

        # Prepare trace data
        trace_data = {
            "execution_id": self.execution_id,
            "workflow_name": self.workflow_name,
            "start_time": self.start_time.isoformat(),
            "duration_ms": (datetime.now() - self.start_time).total_seconds() * 1000,
            "nodes": self.events,
            "final_status": "success" if all(e.get("success", True) for e in self.events) else "failed"
        }

        # Write to file
        with open(filepath, "w") as f:
            json.dump(trace_data, f, indent=2, default=str)

        return filepath
```

## 🔌 Integration Points

### 1. Enhance DebugWrapper for Planner (`src/pflow/planning/debug.py`)

Add metrics to existing DebugWrapper (around line 100):
```python
def __init__(self, node, trace, progress, metrics=None):  # Add metrics parameter
    self._wrapped = node
    self.trace = trace
    self.progress = progress
    self.metrics = metrics  # NEW
    # ... rest of init
```

In the `exec` method where LLM is intercepted (around line 200):
```python
# After capturing LLM response
if self.metrics and "model_name" in prep_res:
    # Record to metrics collector
    # The LLM interception already captures token usage
    pass  # Metrics will aggregate from shared["__llm_calls__"]
```

### 2. Modify Compiler (`src/pflow/runtime/compiler.py`)

In `_create_single_node` function (around line 292), add instrumentation:
```python
def _create_single_node(..., metrics_collector=None, trace_collector=None):  # Add parameters
    # ... existing node creation ...

    # Apply template wrapping (existing)
    node_instance = _apply_template_wrapping(...)

    # Apply namespacing (existing)
    if enable_namespacing:
        node_instance = NamespacedNodeWrapper(node_instance, node_id)

    # NEW: Apply instrumentation wrapper (outermost)
    if metrics_collector or trace_collector:
        from pflow.runtime.instrumented_wrapper import InstrumentedNodeWrapper
        node_instance = InstrumentedNodeWrapper(
            node_instance,
            node_id,
            metrics_collector,
            trace_collector
        )

    # Set params and return
    node_instance.set_params(params)
    return node_instance
```

### 3. Modify CLI (`src/pflow/cli/main.py`)

#### Add new --trace-planner flag (around line 1313):
```python
@click.option("--trace", is_flag=True, help="Save workflow execution trace")  # Updated help
@click.option("--trace-planner", is_flag=True, help="Save planner execution trace")  # NEW
```

#### In execute_json_workflow (around line 532):
```python
def execute_json_workflow(...):
    # Get flags from context
    output_format = ctx.obj.get("output_format", "text")
    trace_workflow = ctx.obj.get("trace", False)

    # Create collectors if needed
    metrics_collector = None
    workflow_trace = None

    if output_format == "json":
        from pflow.core.metrics import MetricsCollector
        metrics_collector = MetricsCollector()
        metrics_collector.record_workflow_start()

    if trace_workflow:
        from pflow.runtime.workflow_trace import WorkflowTraceCollector
        workflow_trace = WorkflowTraceCollector(ir_data.get("name", "workflow"))

    # Pass to compiler
    flow = compile_ir_to_flow(
        ir_data,
        registry,
        initial_params=execution_params,
        metrics_collector=metrics_collector,
        trace_collector=workflow_trace
    )

    # Execute
    result = flow.run(shared_storage)

    if metrics_collector:
        metrics_collector.record_workflow_end()

    # Save trace if needed
    if workflow_trace:
        trace_file = workflow_trace.save_to_file()
        click.echo(f"📊 Workflow trace saved: {trace_file}", err=True)

    # Handle output with metrics
    if output_format == "json" and metrics_collector:
        # Get accumulated LLM calls
        llm_calls = shared_storage.get("__llm_calls__", [])
        metrics_summary = metrics_collector.get_summary(llm_calls)

        # Wrap result with metrics
        json_output = {
            "result": outputs,  # existing output collection
            "is_error": False,
            **metrics_summary  # Spreads top-level metrics
        }
        _serialize_json_result(json_output)
```

#### In _execute_planner_and_workflow (around line 880):
```python
# Check for new flag
trace_planner = ctx.obj.get("trace_planner", False)

# Create metrics if JSON output
metrics_collector = None
if ctx.obj.get("output_format") == "json":
    from pflow.core.metrics import MetricsCollector
    metrics_collector = MetricsCollector()
    metrics_collector.record_planner_start()

# Pass metrics to debug context
debug_context = DebugContext(
    trace=trace_collector if trace_planner else None,  # Use new flag
    progress=progress,
    metrics=metrics_collector  # NEW
)
```

## ⚠️ Critical Pitfalls to Avoid

### 1. The `time.time()` Trap
**DON'T**: Use `time.time()` - it's wall clock time, affected by system clock adjustments
**DO**: Use `time.perf_counter()` - monotonic, high-resolution timer

### 2. The LLM Usage Overwrite Issue
**DON'T**: Rely on `shared["llm_usage"]` for aggregation - it's overwritten
**DO**: Append to `shared["__llm_calls__"]` list for accumulation

### 3. The Lazy Response Trap
**REMEMBER**: LLM responses are lazy! The actual API call happens when `.json()` or `.text()` is called, not when `prompt()` returns. Time the right operation!

### 4. The Wrapper Order Mistake
**CRITICAL**: InstrumentedNodeWrapper must be OUTERMOST to see all operations
**Order**: Instrumented → Namespaced → TemplateAware → BaseNode

### 5. The Missing Delegation
**DON'T**: Forget to implement `__getattr__`, `__rshift__`, `__sub__`
**DO**: Follow the exact pattern from existing wrappers

### 6. The Template Resolution Gap
**NOTE**: Template resolutions are currently only logged, not captured
**TODO**: Implement capture mechanism in InstrumentedNodeWrapper

## ✅ Testing Strategy

### Unit Tests to Write

1. **Test MetricsCollector** (`tests/test_core/test_metrics.py`):
   - Test aggregation from multiple LLM calls
   - Test cost calculation for different models
   - Test summary generation with/without planner

2. **Test InstrumentedNodeWrapper** (`tests/test_runtime/test_instrumented_wrapper.py`):
   - Test timing capture
   - Test LLM usage accumulation
   - Test delegation of attributes
   - Test error handling

3. **Test WorkflowTraceCollector** (`tests/test_runtime/test_workflow_trace.py`):
   - Test event recording
   - Test file saving
   - Test mutation calculation

### Integration Tests

1. **End-to-end with metrics**:
   ```python
   result = cli_runner.invoke(["run", "workflow.json", "--output-format", "json"])
   output = json.loads(result.output)
   assert "total_cost_usd" in output
   assert "duration_ms" in output
   ```

2. **Trace file generation**:
   ```python
   result = cli_runner.invoke(["run", "workflow.json", "--trace"])
   assert "Workflow trace saved" in result.stderr
   ```

### Manual Testing Commands

```bash
# Test metrics collection
pflow run test-workflow.json --output-format json | jq '.total_cost_usd'

# Test workflow tracing
pflow run test-workflow.json --trace
cat ~/.pflow/debug/pflow-trace-workflow-*.json | jq '.nodes[0]'

# Test planner tracing (new flag)
pflow "create a story" --trace-planner

# Test both
pflow "analyze this repo" --output-format json --trace --trace-planner
```

## 📋 Implementation Checklist

### Phase 1: Core Infrastructure
- [ ] Create `src/pflow/core/metrics.py` with MetricsCollector
- [ ] Create `src/pflow/runtime/instrumented_wrapper.py` with InstrumentedNodeWrapper
- [ ] Create `src/pflow/runtime/workflow_trace.py` with WorkflowTraceCollector
- [ ] Add MODEL_PRICING dictionary with accurate prices

### Phase 2: Planner Integration
- [ ] Modify DebugWrapper to accept metrics parameter
- [ ] Update DebugContext to include metrics
- [ ] Pass metrics through planner execution

### Phase 3: Workflow Integration
- [ ] Modify `_create_single_node` to apply InstrumentedNodeWrapper
- [ ] Update `compile_ir_to_flow` to accept collectors
- [ ] Ensure wrapper order is correct

### Phase 4: CLI Integration
- [ ] Add `--trace-planner` flag
- [ ] Update `--trace` help text
- [ ] Modify execute_json_workflow for metrics/tracing
- [ ] Update _execute_planner_and_workflow
- [ ] Implement JSON output wrapping with top-level metrics

### Phase 5: Testing
- [ ] Write unit tests for each component
- [ ] Write integration tests
- [ ] Test performance overhead (<1%)
- [ ] Verify trace file format
- [ ] Test cost calculations

## 🎯 Success Criteria

You'll know you've succeeded when:

1. `pflow run workflow.json` = Clean output, no overhead
2. `pflow run workflow.json --output-format json` includes top-level metrics
3. `pflow run workflow.json --trace` saves workflow trace to ~/.pflow/debug/
4. `pflow "create story" --trace-planner` saves planner trace
5. Metrics show accurate costs based on token usage
6. All existing tests still pass
7. Performance overhead < 1% when metrics enabled

## 🚨 CRITICAL DISCOVERY: Zero Test Coverage for Debug System

**WARNING**: The existing debug/tracing system from Task 27 has **ZERO test coverage**. The test files mentioned in Task 27's documentation (`test_debug.py`, `test_debug_integration.py`, `test_debug_flags.py`) **do not exist**.

This means:
1. You're building on untested code
2. You need to create comprehensive tests for the new system
3. There are no examples of how to test tracing/debug features

### What Tests You MUST Create

Since there are no existing tests to follow, you need to create:

1. **Unit Tests for Core Components**:
   - Test MetricsCollector aggregation
   - Test InstrumentedNodeWrapper delegation and timing
   - Test WorkflowTraceCollector event recording
   - Test cost calculation accuracy

2. **Integration Tests**:
   - Full planner + workflow with metrics
   - Trace file generation and format
   - CLI flag behavior (`--trace`, `--trace-planner`)
   - JSON output with metrics

3. **LLM Mocking Strategy** (from existing planner tests):
   ```python
   with patch("llm.get_model") as mock_get_model:
       mock_model = Mock()
       mock_response = Mock()
       mock_response.json.return_value = {"content": [{"input": {...}}]}
       mock_response.usage.return_value = Mock(input=100, output=50)
       mock_model.prompt.return_value = mock_response
       mock_get_model.return_value = mock_model
   ```

4. **Critical Edge Cases to Test**:
   - No LLM nodes (cost should be 0)
   - Multiple LLM nodes (accumulation)
   - Failed nodes (still capture metrics)
   - Missing usage data (empty dict fallback)
   - Unknown models (default pricing)

### Testing Patterns to Follow

From `tests/test_runtime/test_node_wrapper.py` (TemplateAwareNodeWrapper tests):
- Test transparent delegation
- Test attribute access
- Test error propagation
- Use `caplog` fixture for log assertions
- Test with real PocketFlow nodes

### The Silver Lining

Since there are no existing tests, you have complete freedom to design the test suite properly from scratch. Make it comprehensive—this is the foundation for future observability features.

## 💡 Final Tips

1. **Start with MetricsCollector** - It's the foundation
2. **Create tests as you go** - Don't leave it for the end
3. **Test wrapper delegation thoroughly** - Most bugs come from here
4. **Use existing patterns** - Copy from DebugWrapper and existing node wrappers
5. **Verify the math** - Token costs should match Claude Code for comparison
6. **Keep traces readable** - Filter large data but keep enough for debugging

Remember: This is the observability layer that makes pflow's costs transparent. Users will rely on these metrics to understand their AI spend. Make it accurate, make it fast, make it useful.

Good luck! The architecture is sound, the patterns are proven, and all the hard decisions have been made. Now it's just careful implementation with proper test coverage.