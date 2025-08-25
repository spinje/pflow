# External Patterns for Task 23: Implement execution tracing system

## Summary
This task implements execution tracing using general best practices, with limited inspiration from llm-main:

**What comes from llm**:
- Token tracking field names (`input_tokens`, `output_tokens`, `token_details`)
- The concept of logging execution metadata alongside responses

**What does NOT come from llm**:
- Real-time tracing (llm only logs after completion)
- stderr output (llm logs to SQLite database)
- Cost calculation (llm doesn't estimate costs)
- Hierarchical flow tracing (custom for pocketflow)
- Structured event types (custom design)

**Our approach**: Real-time execution tracing to stderr during workflow execution, with hierarchical support for nested pocketflow nodes

## Specific Implementation

**Note**: The implementation below is a custom design for pflow's needs, not directly from llm. It combines:
- General software engineering best practices for tracing/debugging
- Token tracking inspired by llm's database schema
- Real-time output suitable for CLI tools
- Hierarchical structure for pocketflow's nested execution model

### Pattern: Execution Tracer for Pocketflow

```python
# src/pflow/runtime/tracing.py
import time
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from contextlib import contextmanager

class ExecutionTracer:
    """Trace pocketflow execution for debugging and cost analysis."""

    def __init__(self, run_id: str, verbose: bool = False):
        self.run_id = run_id
        self.verbose = verbose
        self.start_time = time.time()
        self.events: List[Dict[str, Any]] = []
        self.node_stack: List[str] = []  # Track nested flows
        self.current_node_start: Optional[float] = None

    @contextmanager
    def trace_flow(self, flow_name: str):
        """Context manager for tracing flow execution."""
        self.flow_start(flow_name)
        try:
            yield
        finally:
            self.flow_complete(flow_name)

    def flow_start(self, flow_name: str):
        """Record flow execution start."""
        event = {
            "type": "flow_start",
            "name": flow_name,
            "timestamp": time.time(),
            "elapsed": self._elapsed(),
            "depth": len(self.node_stack)
        }
        self.events.append(event)
        self.node_stack.append(flow_name)

        if self.verbose:
            self._output(f"{'  ' * event['depth']}→ Flow: {flow_name}")

    def node_start(self, node_class: str, shared_snapshot: Dict[str, Any]):
        """Record node execution start."""
        self.current_node_start = time.time()

        # Create safe snapshot (keys and types only)
        safe_snapshot = {k: type(v).__name__ for k, v in shared_snapshot.items()}

        event = {
            "type": "node_start",
            "class": node_class,
            "timestamp": self.current_node_start,
            "elapsed": self._elapsed(),
            "shared_keys": list(safe_snapshot.keys()),
            "shared_types": safe_snapshot,
            "depth": len(self.node_stack)
        }
        self.events.append(event)

        if self.verbose:
            indent = "  " * event["depth"]
            self._output(f"{indent}[{self._elapsed()}] → {node_class}")
            if shared_snapshot:
                keys_preview = ", ".join(list(safe_snapshot.keys())[:5])
                if len(safe_snapshot) > 5:
                    keys_preview += f" (+{len(safe_snapshot) - 5} more)"
                self._output(f"{indent}  Keys: {keys_preview}")

    def node_complete(self, node_class: str, action: str,
                     shared_before: Dict[str, Any],
                     shared_after: Dict[str, Any]):
        """Record node completion with shared store changes."""
        duration = time.time() - (self.current_node_start or time.time())

        # Calculate what changed
        added_keys = set(shared_after.keys()) - set(shared_before.keys())
        modified_keys = {
            k for k in shared_before.keys() & shared_after.keys()
            if shared_before[k] != shared_after[k]
        }
        removed_keys = set(shared_before.keys()) - set(shared_after.keys())

        event = {
            "type": "node_complete",
            "class": node_class,
            "timestamp": time.time(),
            "elapsed": self._elapsed(),
            "duration": duration,
            "action": action,
            "changes": {
                "added": sorted(added_keys),
                "modified": sorted(modified_keys),
                "removed": sorted(removed_keys)
            },
            "depth": len(self.node_stack)
        }

        # Track LLM usage if present
        if "llm_usage" in shared_after:
            usage = shared_after["llm_usage"]
            event["tokens"] = usage.get("total_tokens", 0)
            event["cost"] = self._estimate_cost(
                usage,
                shared_after.get("llm_model", "unknown")
            )

            # Track prompt/completion tokens separately
            event["token_details"] = {
                "prompt": usage.get("prompt_tokens", 0),
                "completion": usage.get("completion_tokens", 0)
            }

        self.events.append(event)

        if self.verbose:
            indent = "  " * event["depth"]
            self._output(f"{indent}  ✓ {duration:.2f}s → {action}")

            # Show changes
            changes = []
            if added_keys:
                changes.append(f"+{len(added_keys)}")
            if modified_keys:
                changes.append(f"~{len(modified_keys)}")
            if removed_keys:
                changes.append(f"-{len(removed_keys)}")

            if changes:
                self._output(f"{indent}  Δ: {' '.join(changes)} keys")

            # Show cost if present
            if "cost" in event and event["cost"] > 0:
                self._output(f"{indent}  💰 ${event['cost']:.4f} ({event['tokens']} tokens)")

    def flow_complete(self, flow_name: str):
        """Record flow completion."""
        if self.node_stack and self.node_stack[-1] == flow_name:
            self.node_stack.pop()

        event = {
            "type": "flow_complete",
            "name": flow_name,
            "timestamp": time.time(),
            "elapsed": self._elapsed(),
            "depth": len(self.node_stack)
        }
        self.events.append(event)

        if self.verbose:
            indent = "  " * event["depth"]
            self._output(f"{indent}← Flow: {flow_name}")

    def add_error(self, error: Exception, context: str = ""):
        """Record an error event."""
        event = {
            "type": "error",
            "timestamp": time.time(),
            "elapsed": self._elapsed(),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "context": context,
            "depth": len(self.node_stack)
        }
        self.events.append(event)

        if self.verbose:
            indent = "  " * event["depth"]
            self._output(f"{indent}❌ Error: {error}", error=True)

    def save(self) -> Path:
        """Save trace to file."""
        trace_dir = Path.home() / ".pflow" / "traces"
        trace_dir.mkdir(parents=True, exist_ok=True)

        trace_file = trace_dir / f"{self.run_id}.json"

        # Calculate summary statistics
        total_duration = time.time() - self.start_time
        node_events = [e for e in self.events if e["type"] == "node_complete"]
        total_tokens = sum(e.get("tokens", 0) for e in node_events)
        total_cost = sum(e.get("cost", 0) for e in node_events)

        trace_data = {
            "run_id": self.run_id,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(),
            "duration": total_duration,
            "summary": {
                "total_tokens": total_tokens,
                "total_cost": round(total_cost, 4),
                "node_executions": len(node_events),
                "flows_executed": len([e for e in self.events if e["type"] == "flow_start"]),
                "errors": len([e for e in self.events if e["type"] == "error"])
            },
            "events": self.events
        }

        with open(trace_file, "w") as f:
            json.dump(trace_data, f, indent=2)

        if self.verbose:
            self._output(f"\nExecution Summary:")
            self._output(f"  Duration: {total_duration:.2f}s")
            if total_tokens > 0:
                self._output(f"  Tokens: {total_tokens:,}")
                self._output(f"  Cost: ${total_cost:.4f}")
            self._output(f"  Nodes: {len(node_events)}")
            self._output(f"  Trace saved: {trace_file}")

        return trace_file

    def _elapsed(self) -> str:
        """Get elapsed time as string."""
        return f"{time.time() - self.start_time:.1f}s"

    def _estimate_cost(self, usage: Dict[str, Any], model: str) -> float:
        """Estimate cost from token usage."""
        # Example rates per 1K tokens (prompt, completion)
        # NOTE: These are example rates and should be updated with current pricing
        rates = {
            "gpt-4": (0.03, 0.06),
            "gpt-4o": (0.005, 0.015),
            "gpt-4o-mini": (0.00015, 0.0006),
            "gpt-3.5-turbo": (0.0015, 0.002),
            "claude-3-5-sonnet": (0.003, 0.015),
            "claude-3-opus": (0.015, 0.075),
            "claude-3-haiku": (0.00025, 0.00125)
        }

        # Find matching rate
        prompt_rate, completion_rate = 0.001, 0.002  # defaults
        for model_prefix, (p_rate, c_rate) in rates.items():
            if model_prefix in model.lower():
                prompt_rate, completion_rate = p_rate, c_rate
                break

        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        cost = (prompt_tokens * prompt_rate + completion_tokens * completion_rate) / 1000
        return round(cost, 6)

    def _output(self, text: str, error: bool = False):
        """Output trace information to stderr."""
        # Always use stderr for traces to not interfere with stdout
        print(text, file=sys.stderr)
```

### Pattern: Integration with Pocketflow Execution

```python
# src/pflow/runtime/traced_execution.py
from pocketflow import Node, Flow
from typing import Optional
from .tracing import ExecutionTracer

class TracedNode(Node):
    """Wrapper to add tracing to any node."""

    def __init__(self, node: Node, tracer: ExecutionTracer):
        super().__init__(max_retries=node.max_retries)
        self.wrapped_node = node
        self.tracer = tracer
        # Copy params from wrapped node
        self.params = node.params

    def prep(self, shared):
        """Delegate to wrapped node."""
        return self.wrapped_node.prep(shared)

    def exec(self, prep_res):
        """Delegate to wrapped node."""
        return self.wrapped_node.exec(prep_res)

    def post(self, shared, prep_res, exec_res):
        """Delegate to wrapped node."""
        return self.wrapped_node.post(shared, prep_res, exec_res)

    def _run(self, shared):
        """Run with tracing."""
        # Snapshot before
        shared_before = dict(shared)

        # Trace start
        self.tracer.node_start(
            self.wrapped_node.__class__.__name__,
            shared
        )

        try:
            # Execute wrapped node
            action = self.wrapped_node._run(shared)

            # Trace completion
            self.tracer.node_complete(
                self.wrapped_node.__class__.__name__,
                action or "default",
                shared_before,
                shared
            )

            return action

        except Exception as e:
            # Trace error
            self.tracer.add_error(e, f"in {self.wrapped_node.__class__.__name__}")
            raise


def create_traced_flow(flow: Flow, tracer: ExecutionTracer) -> Flow:
    """Wrap all nodes in a flow with tracing."""
    # This is a simplified version - real implementation would
    # need to handle the flow graph properly
    traced_flow = Flow()

    # Would need to traverse flow graph and wrap each node
    # This is conceptual - actual implementation depends on
    # how pocketflow exposes the flow structure

    return traced_flow
```

### Pattern: CLI Integration

```python
# In src/pflow/cli.py
import uuid
from pflow.runtime.tracing import ExecutionTracer

@click.command()
@click.option('--trace/--no-trace', default=True, help='Enable execution tracing')
@click.option('--verbose-trace', is_flag=True, help='Show trace output during execution')
@click.pass_context
def run(ctx, workflow, trace, verbose_trace):
    """Run a workflow with optional tracing."""
    # Generate run ID
    run_id = str(uuid.uuid4())[:8]

    # Create tracer if enabled
    tracer = None
    if trace:
        tracer = ExecutionTracer(run_id, verbose=verbose_trace)

    try:
        # Compile and execute workflow
        flow = compile_workflow(workflow)

        if tracer:
            # Wrap with tracing
            with tracer.trace_flow("main"):
                flow.run(ctx.obj['shared'])
        else:
            flow.run(ctx.obj['shared'])

        # Save trace if enabled
        if tracer:
            trace_file = tracer.save()
            if not verbose_trace:
                click.echo(f"Trace saved: {trace_file}", err=True)

    except Exception as e:
        if tracer:
            tracer.add_error(e, "workflow execution failed")
            tracer.save()
        raise
```

## Testing Approach

```python
# tests/test_tracing.py
import pytest
from pflow.runtime.tracing import ExecutionTracer
from pocketflow import Node

class TestTracing:
    def test_basic_tracing(self):
        """Test basic trace operations."""
        tracer = ExecutionTracer("test-run", verbose=False)

        # Test flow tracing
        with tracer.trace_flow("test_flow"):
            # Test node tracing
            shared = {"input": "test"}
            tracer.node_start("TestNode", shared)

            # Simulate node execution
            shared["output"] = "result"

            tracer.node_complete(
                "TestNode",
                "success",
                {"input": "test"},
                shared
            )

        # Verify events
        assert len(tracer.events) == 4  # flow_start, node_start, node_complete, flow_complete

        node_event = next(e for e in tracer.events if e["type"] == "node_complete")
        assert node_event["changes"]["added"] == ["output"]
        assert node_event["action"] == "success"

    def test_cost_tracking(self):
        """Test LLM cost estimation."""
        tracer = ExecutionTracer("test-run")

        shared_before = {}
        shared_after = {
            "llm_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150
            },
            "llm_model": "gpt-4o-mini"
        }

        tracer.node_start("LLMNode", shared_before)
        tracer.node_complete("LLMNode", "default", shared_before, shared_after)

        event = tracer.events[-1]
        assert "cost" in event
        assert event["tokens"] == 150
        assert event["cost"] > 0

    def test_trace_persistence(self, tmp_path, monkeypatch):
        """Test saving traces to disk."""
        # Mock home directory
        monkeypatch.setenv("HOME", str(tmp_path))

        tracer = ExecutionTracer("test-123")
        tracer.flow_start("test")
        tracer.flow_complete("test")

        # Save trace
        trace_file = tracer.save()

        assert trace_file.exists()
        assert "test-123.json" in str(trace_file)

        # Verify content
        import json
        with open(trace_file) as f:
            data = json.load(f)

        assert data["run_id"] == "test-123"
        assert len(data["events"]) == 2
```

## Common Pitfalls to Avoid

1. **Don't trace to stdout**: Always use stderr for traces
2. **Don't log sensitive data**: Only log keys and types, not values
3. **Handle nested flows**: Track depth for proper indentation
4. **Estimate costs carefully**: Models have different pricing
5. **Make tracing optional**: Allow --no-trace for production

## Benefits of this Approach

1. **Clear Execution Flow**: See exactly what happened when
2. **Cost Visibility**: Track LLM expenses in real-time
3. **Performance Analysis**: Find bottlenecks easily
4. **Error Context**: Know exactly where failures occurred
5. **Debugging Power**: Replay execution from traces

## Integration with Existing Code

```python
# When executing a workflow
if args.trace:
    tracer = ExecutionTracer(run_id, verbose=args.verbose)
    # Wrap nodes with tracing
else:
    tracer = None
    # Run without tracing overhead
```

## Key Differences from llm

1. **Real-time vs Post-execution**:
   - llm: Logs to SQLite after execution completes
   - pflow: Real-time tracing to stderr during execution

2. **Storage**:
   - llm: SQLite database with full schema for queries
   - pflow: JSON trace files for debugging

3. **Token/Cost Tracking**:
   - llm: Stores `input_tokens`, `output_tokens`, `token_details` from model responses
   - pflow: Extends this with cost estimation based on model pricing

4. **Output Separation**:
   - llm: All output to stdout, logs to database
   - pflow: Traces to stderr, results to stdout (allows piping)

## References
- `llm-main/llm/models.py`: Database logging in `log_to_db()` method
- `llm-main/llm/docs/logging.md`: SQLite storage approach
- Best practices: stderr for traces, stdout for data (Unix philosophy)
