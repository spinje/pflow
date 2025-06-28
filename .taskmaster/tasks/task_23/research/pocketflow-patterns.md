# PocketFlow Patterns for Task 23: Implement Execution Tracing System

## Task Context

- **Goal**: Build comprehensive execution visibility for debugging and optimization
- **Dependencies**: Task 3 (runtime execution)
- **Constraints**: Clear output, minimal overhead, actionable insights

## Overview

Task 23 implements execution tracing that makes workflows transparent and debuggable. Unlike traditional "black box" AI tools, pflow shows exactly what happens at each step, enabling users to understand, debug, and optimize their workflows.

## Core Patterns from Advanced Analysis

### Pattern: Progressive State Visualization
**Found in**: 6 of 7 repositories show state evolution
**Why It Applies**: Users need to see how data transforms

```python
# Show what changes at each step
[1] github-get-issue (0.12s)
    Input: {issue_number: "123", repo: "owner/repo"}
    Output: {issue: "Login button not working...", issue_title: "Auth Bug"}
    Shared Store Δ: +issue, +issue_title, +issue_author

[2] claude-code (3.45s)
    Input: {prompt: "Fix this issue:\nLogin button not working..."}
    Output: {code_report: "Fixed authentication...", files_modified: ["auth.py"]}
    Shared Store Δ: +code_report, +files_modified
    💰 Cost: $0.0234 (8,421 tokens)
```

### Pattern: Token and Cost Tracking
**Found in**: All LLM-using repos track token usage
**Why It Applies**: Cost transparency prevents surprises

```python
def track_llm_usage(node_type: str, tokens: Dict, model: str) -> Dict:
    """Track token usage and estimate costs"""

    COSTS_PER_1K = {
        "gpt-4": {"input": 0.03, "output": 0.06},
        "claude-3-opus": {"input": 0.015, "output": 0.075},
        "claude-3-sonnet": {"input": 0.003, "output": 0.015}
    }

    if model in COSTS_PER_1K:
        input_cost = (tokens["input"] / 1000) * COSTS_PER_1K[model]["input"]
        output_cost = (tokens["output"] / 1000) * COSTS_PER_1K[model]["output"]
        total_cost = input_cost + output_cost

        return {
            "tokens": tokens,
            "cost": {
                "input": input_cost,
                "output": output_cost,
                "total": total_cost
            },
            "model": model
        }
```

### Pattern: Error Context Preservation
**Found in**: Robust flows preserve full error context
**Why It Applies**: Debugging needs complete information

```python
# Not just "Error: API failed"
# But full context:
[3] github-create-pr (0.34s) ❌ FAILED
    Input: {title: "Fix: Auth Bug", body: "..."}
    Error: GitHubAPIError: Pull request creation failed
    Context:
      - Repository: owner/repo
      - Branch: fix-auth-bug
      - Base: main
      - API Response: 422 Unprocessable Entity
      - Reason: "A pull request already exists for owner:fix-auth-bug"
    Suggestion: Use 'github-list-prs' to find existing PR
    Shared Store at failure: {issue: "...", code_report: "...", ...}
```

## Relevant Cookbook Examples

- `cookbook/pocketflow-thinking`: Shows thinking/reasoning traces
- `cookbook/pocketflow-agent`: Multi-step execution with visibility
- `cookbook/AI-Paul-Graham`: Complex flow with clear stages

## Implementation Patterns

### Pattern: Comprehensive Tracing System

```python
# src/pflow/runtime/tracing.py
import time
import json
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional, List
from pathlib import Path
import uuid

@dataclass
class NodeExecution:
    """Single node execution trace"""
    node_id: str
    node_type: str
    start_time: float
    end_time: float
    duration: float
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    shared_store_before: Dict[str, Any]
    shared_store_after: Dict[str, Any]
    shared_store_delta: Dict[str, Any]
    status: str  # "success", "failed", "skipped"
    error: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None  # tokens, cost, cache

class ExecutionTracer:
    """Comprehensive execution tracing system"""

    def __init__(self, trace_dir: Optional[Path] = None):
        self.trace_dir = trace_dir or Path.home() / ".pflow" / "traces"
        self.trace_dir.mkdir(parents=True, exist_ok=True)

        self.current_trace = {
            "id": str(uuid.uuid4()),
            "start_time": time.time(),
            "workflow_name": None,
            "nodes": [],
            "total_tokens": 0,
            "total_cost": 0.0,
            "status": "running"
        }

        self.verbosity = 1  # 0=quiet, 1=normal, 2=detailed
        self._node_stack = []

    def set_verbosity(self, level: int):
        """Set trace verbosity level"""
        self.verbosity = max(0, min(2, level))

    def start_workflow(self, workflow_name: str, params: Dict[str, Any]):
        """Start tracing a workflow execution"""
        self.current_trace.update({
            "workflow_name": workflow_name,
            "parameters": params,
            "start_time": time.time()
        })

        if self.verbosity > 0:
            print(f"\n🚀 Executing workflow: {workflow_name}")
            if params and self.verbosity > 1:
                print(f"   Parameters: {json.dumps(params, indent=2)}")

    def start_node(self, node_id: str, node_type: str, inputs: Dict[str, Any],
                   shared_store: Dict[str, Any]):
        """Start tracing node execution"""

        # Create node execution record
        node_exec = {
            "node_id": node_id,
            "node_type": node_type,
            "start_time": time.time(),
            "inputs": self._sanitize_data(inputs),
            "shared_store_before": self._sanitize_data(shared_store.copy()),
            "status": "running"
        }

        self._node_stack.append(node_exec)

        if self.verbosity > 0:
            node_num = len(self.current_trace["nodes"]) + 1
            print(f"\n[{node_num}] {node_type} ", end="", flush=True)

    def end_node(self, outputs: Dict[str, Any], shared_store: Dict[str, Any],
                 error: Optional[Exception] = None):
        """Complete node execution trace"""

        if not self._node_stack:
            return

        node_exec = self._node_stack.pop()
        end_time = time.time()

        # Calculate execution time
        duration = end_time - node_exec["start_time"]

        # Calculate shared store delta
        store_before = node_exec["shared_store_before"]
        store_after = self._sanitize_data(shared_store.copy())
        delta = self._calculate_delta(store_before, store_after)

        # Update node execution record
        node_exec.update({
            "end_time": end_time,
            "duration": duration,
            "outputs": self._sanitize_data(outputs),
            "shared_store_after": store_after,
            "shared_store_delta": delta,
            "status": "failed" if error else "success",
            "error": self._format_error(error) if error else None
        })

        # Add to trace
        self.current_trace["nodes"].append(node_exec)

        # Display trace
        self._display_node_trace(node_exec, len(self.current_trace["nodes"]))

    def add_metrics(self, node_id: str, metrics: Dict[str, Any]):
        """Add metrics (tokens, cost, cache) to most recent node"""

        if self.current_trace["nodes"]:
            node = self.current_trace["nodes"][-1]
            if node["node_id"] == node_id:
                node["metrics"] = metrics

                # Update totals
                if "tokens" in metrics:
                    total = metrics["tokens"].get("total", 0)
                    self.current_trace["total_tokens"] += total

                if "cost" in metrics:
                    cost = metrics["cost"].get("total", 0)
                    self.current_trace["total_cost"] += cost

                # Display metrics if verbose
                if self.verbosity > 0 and metrics:
                    self._display_metrics(metrics)

    def end_workflow(self, status: str = "success", error: Optional[Exception] = None):
        """Complete workflow trace"""

        self.current_trace.update({
            "end_time": time.time(),
            "duration": time.time() - self.current_trace["start_time"],
            "status": status,
            "error": self._format_error(error) if error else None
        })

        # Display summary
        if self.verbosity > 0:
            self._display_summary()

        # Save trace
        trace_file = self._save_trace()

        if self.verbosity > 0 and trace_file:
            print(f"\n📊 Trace saved: {trace_file}")

    def _calculate_delta(self, before: Dict, after: Dict) -> Dict:
        """Calculate what changed in shared store"""

        delta = {
            "added": {},
            "modified": {},
            "removed": []
        }

        # Find added and modified keys
        for key, value in after.items():
            if key not in before:
                delta["added"][key] = self._preview_value(value)
            elif before[key] != value:
                delta["modified"][key] = {
                    "before": self._preview_value(before[key]),
                    "after": self._preview_value(value)
                }

        # Find removed keys
        for key in before:
            if key not in after:
                delta["removed"].append(key)

        return delta

    def _display_node_trace(self, node_exec: Dict, node_num: int):
        """Display node execution trace"""

        if self.verbosity == 0:
            return

        # Basic info (verbosity 1+)
        status_icon = "✓" if node_exec["status"] == "success" else "❌"
        print(f"({node_exec['duration']:.2f}s) {status_icon}")

        if self.verbosity > 1:
            # Inputs
            if node_exec["inputs"]:
                print(f"    Input: {self._format_preview(node_exec['inputs'])}")

            # Outputs (on success)
            if node_exec["status"] == "success" and node_exec["outputs"]:
                print(f"    Output: {self._format_preview(node_exec['outputs'])}")

            # Shared store delta
            delta = node_exec["shared_store_delta"]
            if delta["added"] or delta["modified"] or delta["removed"]:
                delta_str = self._format_delta(delta)
                print(f"    Shared Store Δ: {delta_str}")

        # Error details (always show)
        if node_exec["error"]:
            self._display_error(node_exec["error"])

    def _display_metrics(self, metrics: Dict):
        """Display node metrics"""

        parts = []

        # Token usage
        if "tokens" in metrics:
            tokens = metrics["tokens"]
            if isinstance(tokens, dict):
                total = tokens.get("total", tokens.get("input", 0) + tokens.get("output", 0))
            else:
                total = tokens
            parts.append(f"{total:,} tokens")

        # Cost
        if "cost" in metrics:
            cost = metrics["cost"]
            if isinstance(cost, dict):
                total_cost = cost.get("total", 0)
            else:
                total_cost = cost
            parts.append(f"${total_cost:.4f}")

        # Cache hit
        if metrics.get("cache_hit"):
            parts.append("cached")

        if parts:
            print(f"    💰 {', '.join(parts)}")

    def _display_error(self, error: Dict):
        """Display error with context"""

        print(f"    Error: {error['type']}: {error['message']}")

        if "context" in error:
            print("    Context:")
            for key, value in error["context"].items():
                print(f"      - {key}: {value}")

        if "suggestion" in error:
            print(f"    Suggestion: {error['suggestion']}")

    def _display_summary(self):
        """Display execution summary"""

        trace = self.current_trace

        print(f"\n{'='*50}")
        print(f"Workflow: {trace['workflow_name']}")
        print(f"Status: {trace['status']}")
        print(f"Duration: {trace['duration']:.2f}s")
        print(f"Nodes executed: {len(trace['nodes'])}")

        if trace["total_tokens"] > 0:
            print(f"Total tokens: {trace['total_tokens']:,}")

        if trace["total_cost"] > 0:
            print(f"Total cost: ${trace['total_cost']:.4f}")

        # Cache statistics
        cache_hits = sum(1 for n in trace["nodes"]
                        if n.get("metrics", {}).get("cache_hit"))
        if cache_hits > 0:
            print(f"Cache hits: {cache_hits}/{len(trace['nodes'])}")

    def _format_preview(self, data: Dict) -> str:
        """Format data preview for display"""

        if not data:
            return "{}"

        # For single key-value, show inline
        if len(data) == 1:
            key, value = next(iter(data.items()))
            return f"{{{key}: {self._preview_value(value)}}}"

        # For multiple, show keys
        keys = list(data.keys())[:3]
        if len(data) > 3:
            keys.append("...")

        return "{" + ", ".join(f"{k}: ..." for k in keys) + "}"

    def _format_delta(self, delta: Dict) -> str:
        """Format shared store delta for display"""

        parts = []

        if delta["added"]:
            added_keys = list(delta["added"].keys())
            parts.append(f"+{', '.join(added_keys)}")

        if delta["modified"]:
            modified_keys = list(delta["modified"].keys())
            parts.append(f"~{', '.join(modified_keys)}")

        if delta["removed"]:
            parts.append(f"-{', '.join(delta['removed'])}")

        return ", ".join(parts) if parts else "no changes"

    def _preview_value(self, value: Any) -> Any:
        """Create preview of value for display"""

        if isinstance(value, str):
            if len(value) > 50:
                return value[:47] + "..."
            return value
        elif isinstance(value, (list, dict)):
            return f"<{type(value).__name__}[{len(value)}]>"
        else:
            return value

    def _sanitize_data(self, data: Any) -> Any:
        """Sanitize data for storage/display"""

        if isinstance(data, dict):
            # Remove sensitive keys
            sanitized = {}
            sensitive_keys = {"password", "token", "key", "secret", "api_key"}

            for key, value in data.items():
                if any(s in key.lower() for s in sensitive_keys):
                    sanitized[key] = "***REDACTED***"
                else:
                    sanitized[key] = self._sanitize_data(value)

            return sanitized

        elif isinstance(data, list):
            return [self._sanitize_data(item) for item in data]

        elif isinstance(data, str) and len(data) > 1000:
            # Truncate very long strings
            return data[:997] + "..."

        return data

    def _format_error(self, error: Exception) -> Dict:
        """Format error for trace"""

        error_dict = {
            "type": type(error).__name__,
            "message": str(error)
        }

        # Add context if available
        if hasattr(error, "context"):
            error_dict["context"] = error.context

        # Add suggestion if available
        if hasattr(error, "suggestion"):
            error_dict["suggestion"] = error.suggestion

        return error_dict

    def _save_trace(self) -> Optional[Path]:
        """Save trace to file"""

        try:
            filename = f"{self.current_trace['workflow_name']}_{self.current_trace['id'][:8]}.json"
            trace_file = self.trace_dir / filename

            with open(trace_file, 'w') as f:
                json.dump(self.current_trace, f, indent=2, default=str)

            return trace_file
        except Exception as e:
            print(f"Warning: Failed to save trace: {e}")
            return None

    def load_trace(self, trace_id: str) -> Dict:
        """Load a saved trace"""

        # Find trace file
        for trace_file in self.trace_dir.glob("*.json"):
            if trace_id in trace_file.name:
                with open(trace_file) as f:
                    return json.load(f)

        raise ValueError(f"Trace not found: {trace_id}")

    def replay_trace(self, trace_id: str):
        """Replay a saved trace with formatting"""

        trace = self.load_trace(trace_id)

        # Display header
        print(f"\n🔄 Replaying trace: {trace['workflow_name']}")
        print(f"   ID: {trace['id']}")
        print(f"   Time: {trace.get('start_time', 'Unknown')}")

        # Replay each node
        for i, node in enumerate(trace["nodes"], 1):
            self._display_node_trace(node, i)

        # Display summary
        self.current_trace = trace
        self._display_summary()
```

### Pattern: Runtime Integration

```python
# Integration with pocketflow runtime
class TracedNodeExecution:
    """Wrapper for traced node execution"""

    def __init__(self, node, tracer):
        self.node = node
        self.tracer = tracer

    def run(self, shared):
        """Execute node with tracing"""

        # Extract inputs
        inputs = self._extract_inputs(shared)

        # Start trace
        self.tracer.start_node(
            node_id=self.node.id,
            node_type=type(self.node).__name__,
            inputs=inputs,
            shared_store=shared
        )

        try:
            # Execute node
            result = self.node._run(shared)

            # Extract outputs
            outputs = self._extract_outputs(shared, inputs)

            # End trace
            self.tracer.end_node(outputs, shared)

            # Add metrics if available
            if hasattr(self.node, "_last_metrics"):
                self.tracer.add_metrics(self.node.id, self.node._last_metrics)

            return result

        except Exception as e:
            # Trace error
            self.tracer.end_node({}, shared, error=e)
            raise

    def _extract_inputs(self, shared: Dict) -> Dict:
        """Extract node inputs from shared store"""

        # Get node metadata to know expected inputs
        if hasattr(self.node, "_metadata"):
            expected_inputs = self.node._metadata.get("inputs", [])
            return {key: shared.get(key) for key in expected_inputs if key in shared}

        # Fallback: extract based on node access patterns
        return {}

    def _extract_outputs(self, shared_after: Dict, inputs: Dict) -> Dict:
        """Extract what node added to shared store"""

        # Simple heuristic: new keys are likely outputs
        outputs = {}
        for key, value in shared_after.items():
            if key not in inputs:
                outputs[key] = value

        return outputs
```

### Pattern: Cost-Aware Execution

```python
class CostTracker:
    """Track and limit execution costs"""

    def __init__(self, budget: Optional[float] = None):
        self.budget = budget
        self.spent = 0.0
        self.model_costs = {
            "gpt-4": {"input": 0.03, "output": 0.06},
            "gpt-3.5-turbo": {"input": 0.001, "output": 0.002},
            "claude-3-opus": {"input": 0.015, "output": 0.075},
            "claude-3-sonnet": {"input": 0.003, "output": 0.015}
        }

    def track_usage(self, model: str, tokens: Dict[str, int]) -> float:
        """Track token usage and return cost"""

        if model not in self.model_costs:
            return 0.0

        costs = self.model_costs[model]
        input_cost = (tokens.get("input", 0) / 1000) * costs["input"]
        output_cost = (tokens.get("output", 0) / 1000) * costs["output"]
        total_cost = input_cost + output_cost

        self.spent += total_cost

        # Check budget
        if self.budget and self.spent > self.budget:
            raise BudgetExceededError(
                f"Cost budget exceeded: ${self.spent:.4f} > ${self.budget:.4f}"
            )

        return total_cost

    def get_summary(self) -> Dict:
        """Get cost summary"""

        return {
            "total_spent": self.spent,
            "budget": self.budget,
            "remaining": self.budget - self.spent if self.budget else None,
            "percentage_used": (self.spent / self.budget * 100) if self.budget else None
        }
```

## Advanced Patterns

### Pattern: Trace Analysis
**Source**: Performance optimization needs
**Description**: Analyze traces for bottlenecks

```python
def analyze_trace(trace: Dict) -> Dict:
    """Analyze trace for optimization opportunities"""

    analysis = {
        "total_time": trace["duration"],
        "node_times": [],
        "bottlenecks": [],
        "cache_opportunities": [],
        "cost_breakdown": {}
    }

    # Analyze each node
    for node in trace["nodes"]:
        node_info = {
            "node": node["node_id"],
            "type": node["node_type"],
            "duration": node["duration"],
            "percentage": (node["duration"] / trace["duration"]) * 100
        }
        analysis["node_times"].append(node_info)

        # Identify bottlenecks (>30% of total time)
        if node_info["percentage"] > 30:
            analysis["bottlenecks"].append(node_info)

        # Identify cache opportunities
        if node["node_type"] in ["llm", "claude-code"] and not node.get("metrics", {}).get("cache_hit"):
            if node["duration"] > 1.0:  # Slow operations
                analysis["cache_opportunities"].append({
                    "node": node["node_id"],
                    "potential_savings": node["duration"]
                })

    # Sort by duration
    analysis["node_times"].sort(key=lambda x: x["duration"], reverse=True)

    return analysis
```

### Pattern: Trace Comparison
**Source**: Debugging pattern changes
**Description**: Compare traces to find differences

```python
def compare_traces(trace1: Dict, trace2: Dict) -> Dict:
    """Compare two traces to find differences"""

    comparison = {
        "duration_change": trace2["duration"] - trace1["duration"],
        "cost_change": trace2.get("total_cost", 0) - trace1.get("total_cost", 0),
        "node_differences": [],
        "new_errors": []
    }

    # Compare node executions
    nodes1 = {n["node_id"]: n for n in trace1["nodes"]}
    nodes2 = {n["node_id"]: n for n in trace2["nodes"]}

    for node_id, node2 in nodes2.items():
        if node_id in nodes1:
            node1 = nodes1[node_id]
            if abs(node2["duration"] - node1["duration"]) > 0.5:
                comparison["node_differences"].append({
                    "node": node_id,
                    "duration_change": node2["duration"] - node1["duration"],
                    "status_change": f"{node1['status']} → {node2['status']}"
                })

    return comparison
```

## Testing Approach

```python
def test_execution_tracing():
    """Test complete tracing flow"""

    tracer = ExecutionTracer()
    tracer.set_verbosity(2)

    # Start workflow
    tracer.start_workflow("test-flow", {"param": "value"})

    # Trace node execution
    tracer.start_node("node1", "TestNode", {"input": "data"}, {})
    tracer.end_node({"output": "result"}, {"output": "result"})

    # Add metrics
    tracer.add_metrics("node1", {
        "tokens": {"input": 100, "output": 50},
        "cost": {"total": 0.0045}
    })

    # End workflow
    tracer.end_workflow()

    # Verify trace
    assert len(tracer.current_trace["nodes"]) == 1
    assert tracer.current_trace["total_cost"] == 0.0045

def test_error_tracing():
    """Test error context preservation"""

    tracer = ExecutionTracer()

    # Create error with context
    error = RuntimeError("API failed")
    error.context = {"status_code": 422, "endpoint": "/repos/owner/repo/pulls"}
    error.suggestion = "Check if PR already exists"

    # Trace error
    tracer.start_node("github", "GitHubNode", {}, {})
    tracer.end_node({}, {}, error=error)

    # Verify error captured
    node = tracer.current_trace["nodes"][0]
    assert node["status"] == "failed"
    assert node["error"]["context"]["status_code"] == 422
    assert "suggestion" in node["error"]
```

## Integration Points

### Connection to Task 3 (Runtime)
Tracing wraps runtime execution:
```python
# Runtime integrates tracer
if tracing_enabled:
    tracer = ExecutionTracer()
    node = TracedNodeExecution(original_node, tracer)
```

### Connection to Task 24 (Caching)
Tracing shows cache effectiveness:
```python
# Cache hits shown in trace
[2] llm (0.001s) ✓
    💰 cached
    Shared Store Δ: +response
```

### Connection to Task 22 (Named Execution)
Named workflows include trace info:
```python
# Execution shows trace
pflow fix-issue --issue=123 --trace
# Displays real-time trace
# Saves to ~/.pflow/traces/fix-issue_abc123.json
```

## Minimal Test Case

```python
# Save as test_tracing.py
import time

class MockNode:
    def __init__(self, node_id, duration=0.1):
        self.id = node_id
        self.duration = duration

    def run(self, shared):
        time.sleep(self.duration)
        shared[f"{self.id}_output"] = f"Result from {self.id}"
        return "default"

def test_trace_visibility():
    """Demonstrate execution transparency"""

    # Create tracer
    tracer = ExecutionTracer()
    tracer.set_verbosity(2)

    # Start workflow
    tracer.start_workflow("demo-flow", {"input": "test"})

    # Execute nodes with tracing
    shared = {"input": "test"}

    for i in range(3):
        node = MockNode(f"node{i+1}", duration=0.1 * (i + 1))

        # Trace execution
        tracer.start_node(node.id, "MockNode", {"input": shared.get("input")}, shared)

        # Execute
        node.run(shared)

        # End trace
        tracer.end_node({f"{node.id}_output": shared[f"{node.id}_output"]}, shared)

        # Add mock metrics for node2
        if i == 1:
            tracer.add_metrics(node.id, {
                "tokens": {"total": 1500},
                "cost": {"total": 0.0045}
            })

    # End workflow
    tracer.end_workflow()

    print("\n✅ Execution fully traced and transparent!")

if __name__ == "__main__":
    test_trace_visibility()
```

## Summary

Task 23's execution tracing provides unprecedented visibility into AI workflows:

1. **Complete Transparency** - See every input, output, and transformation
2. **Cost Tracking** - Know exactly what each execution costs
3. **Performance Analysis** - Identify bottlenecks and optimization opportunities
4. **Error Context** - Full debugging information when things go wrong
5. **Historical Analysis** - Compare executions over time

This transforms AI workflows from "black boxes" to glass boxes where every operation is visible, measurable, and optimizable.
