# Task 22: Shared Store Runtime with Output Capture - PocketFlow Implementation Guide

## Overview
This task implements the runtime execution engine for pflow workflows, managing the shared store, capturing outputs, and handling node execution. PocketFlow orchestrates the complex flow of setup, execution, output capture, and cleanup.

## PocketFlow Architecture

### Flow Structure
```
InitRuntime >> LoadWorkflow >> SetupStore >> ExecuteNodes >> CaptureOutput >> Cleanup >> Success
      |             |              |              |               |            |
      v             v              v              v               v            v
InitError    LoadError      StoreError     ExecError      CaptureError   CleanupError
                                                |
                                                v
                                          HandleFailure >> Rollback
```

### Key Nodes

#### 1. RuntimeInitNode
```python
class RuntimeInitNode(Node):
    """Initialize runtime environment with safety checks"""
    def __init__(self, config):
        super().__init__()
        self.config = config

    def exec(self, shared):
        # Set up runtime context
        runtime_id = str(uuid.uuid4())
        shared["runtime_id"] = runtime_id
        shared["start_time"] = datetime.now()

        # Initialize output capture
        shared["output_buffer"] = io.StringIO()
        shared["error_buffer"] = io.StringIO()

        # Set resource limits
        if self.config.get("memory_limit"):
            resource.setrlimit(
                resource.RLIMIT_AS,
                (self.config["memory_limit"], self.config["memory_limit"])
            )

        # Initialize tracing
        shared["trace_events"] = []
        shared["node_outputs"] = {}

        return "load_workflow"
```

#### 2. SharedStoreManagerNode
```python
class SharedStoreManagerNode(Node):
    """Manage shared store with isolation and safety"""
    def __init__(self):
        super().__init__()

    def exec(self, shared):
        workflow = shared["workflow"]

        # Create isolated shared store
        workflow_store = {}

        # Initialize with input data
        if "input_data" in shared:
            workflow_store.update(shared["input_data"])

        # Add system variables
        workflow_store["_runtime"] = {
            "id": shared["runtime_id"],
            "timestamp": shared["start_time"],
            "workflow_name": workflow.get("name", "unnamed")
        }

        # Create proxied stores for each node
        node_stores = {}
        for node in workflow["nodes"]:
            node_id = node["id"]
            # Each node gets a proxy with potential key mapping
            node_stores[node_id] = NodeAwareProxy(
                workflow_store,
                node_id,
                shared.get("key_mappings", {})
            )

        shared["workflow_store"] = workflow_store
        shared["node_stores"] = node_stores
        return "execute_flow"
```

#### 3. NodeExecutorNode
```python
class NodeExecutorNode(Node):
    """Execute individual nodes with output capture"""
    def __init__(self, node_registry):
        super().__init__(max_retries=2)
        self.registry = node_registry

    def exec(self, shared):
        current_node = shared["current_node"]
        node_store = shared["node_stores"][current_node["id"]]

        # Load node class
        node_class = self.registry.get_node_class(current_node["type"])
        if not node_class:
            shared["error"] = f"Unknown node type: {current_node['type']}"
            return "node_error"

        # Instantiate with config
        node_instance = node_class(**current_node.get("config", {}))

        # Capture output
        with OutputCapture() as capture:
            try:
                # Execute node lifecycle
                node_instance.prep(node_store)
                action = node_instance.exec(node_store)
                node_instance.post(node_store)

                # Store captured output
                shared["node_outputs"][current_node["id"]] = {
                    "stdout": capture.stdout,
                    "stderr": capture.stderr,
                    "action": action,
                    "store_delta": self._calculate_delta(node_store)
                }

                # Trace event
                shared["trace_events"].append({
                    "timestamp": datetime.now().isoformat(),
                    "node_id": current_node["id"],
                    "event": "executed",
                    "action": action
                })

                return "next_node"

            except Exception as e:
                shared["node_error"] = {
                    "node_id": current_node["id"],
                    "error": str(e),
                    "traceback": traceback.format_exc()
                }
                return "handle_error"
```

#### 4. OutputCaptureNode
```python
class OutputCaptureNode(Node):
    """Aggregate and format captured outputs"""
    def exec(self, shared):
        node_outputs = shared["node_outputs"]
        format_type = shared.get("output_format", "json")

        if format_type == "json":
            output = {
                "workflow_id": shared["runtime_id"],
                "execution_time": (datetime.now() - shared["start_time"]).total_seconds(),
                "final_store": shared["workflow_store"],
                "node_outputs": node_outputs,
                "trace": shared["trace_events"]
            }
            shared["final_output"] = json.dumps(output, indent=2)

        elif format_type == "text":
            lines = [f"Workflow Execution: {shared['runtime_id']}"]
            lines.append(f"Duration: {datetime.now() - shared['start_time']}")
            lines.append("\nNode Outputs:")

            for node_id, output in node_outputs.items():
                lines.append(f"\n[{node_id}]")
                if output["stdout"]:
                    lines.append(f"Output: {output['stdout']}")
                if output["stderr"]:
                    lines.append(f"Errors: {output['stderr']}")

            shared["final_output"] = "\n".join(lines)

        return "cleanup"
```

#### 5. ExecutionFlowControlNode
```python
class ExecutionFlowControlNode(Node):
    """Control flow between nodes based on actions"""
    def exec(self, shared):
        workflow = shared["workflow"]
        current_idx = shared.get("current_node_idx", 0)

        if current_idx >= len(workflow["nodes"]):
            # All nodes executed
            return "capture_output"

        current_node = workflow["nodes"][current_idx]
        shared["current_node"] = current_node

        # Check if node should execute
        if self._should_skip(current_node, shared):
            shared["current_node_idx"] = current_idx + 1
            return "execute_flow"  # Skip to next

        # Set up node execution
        return "execute_node"

    def _should_skip(self, node, shared):
        """Check conditions for skipping node"""
        if "when" in node:
            # Conditional execution
            condition = node["when"]
            return not self._evaluate_condition(condition, shared["workflow_store"])
        return False
```

## Implementation Plan

### Phase 1: Core Runtime
1. Create `src/pflow/flows/runtime/` structure
2. Implement runtime initialization
3. Build shared store management
4. Create basic node executor

### Phase 2: Output Capture
1. Implement stdout/stderr capture
2. Add store delta tracking
3. Create output formatting
4. Build trace system

### Phase 3: Flow Control
1. Implement action-based routing
2. Add conditional execution
3. Create parallel execution support
4. Build error recovery

### Phase 4: Advanced Features
1. Resource limits and monitoring
2. Checkpoint/resume support
3. Debug mode with stepping
4. Performance profiling

## Testing Strategy

### Unit Tests
```python
def test_output_capture():
    """Test node output is properly captured"""
    class TestNode(Node):
        def exec(self, shared):
            print("Hello from node")
            sys.stderr.write("Warning message")
            shared["result"] = 42
            return "success"

    executor = NodeExecutorNode(mock_registry)
    shared = {
        "current_node": {"id": "test", "type": "test_node"},
        "node_stores": {"test": {}}
    }

    result = executor.exec(shared)

    assert shared["node_outputs"]["test"]["stdout"] == "Hello from node\n"
    assert shared["node_outputs"]["test"]["stderr"] == "Warning message"
    assert shared["node_outputs"]["test"]["action"] == "success"
```

### Integration Tests
```python
def test_full_workflow_execution():
    """Test complete workflow with multiple nodes"""
    runtime_flow = create_runtime_flow()

    workflow = {
        "nodes": [
            {"id": "read", "type": "read_file", "config": {"path": "input.txt"}},
            {"id": "process", "type": "transform", "config": {"operation": "upper"}},
            {"id": "write", "type": "write_file", "config": {"path": "output.txt"}}
        ]
    }

    result = runtime_flow.run({
        "workflow": workflow,
        "input_data": {}
    })

    assert result["execution_complete"]
    assert len(result["node_outputs"]) == 3
    assert Path("output.txt").exists()
```

## Runtime Patterns

### Output Capture Context Manager
```python
class OutputCapture:
    """Capture stdout/stderr during node execution"""
    def __enter__(self):
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.old_stdout = sys.stdout
        self.old_stderr = sys.stderr
        sys.stdout = self.stdout
        sys.stderr = self.stderr
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.old_stdout
        sys.stderr = self.old_stderr
        self.stdout = self.stdout.getvalue()
        self.stderr = self.stderr.getvalue()
```

### Store Delta Tracking
```python
def _calculate_delta(self, store_before, store_after):
    """Track changes made by node"""
    delta = {
        "added": {},
        "modified": {},
        "removed": []
    }

    # Find additions and modifications
    for key, value in store_after.items():
        if key not in store_before:
            delta["added"][key] = value
        elif store_before[key] != value:
            delta["modified"][key] = {
                "old": store_before[key],
                "new": value
            }

    # Find removals
    for key in store_before:
        if key not in store_after:
            delta["removed"].append(key)

    return delta
```

## Benefits of PocketFlow Approach

1. **Execution Control**: Clear flow between nodes
2. **Error Isolation**: Each node failure handled
3. **Output Tracking**: Comprehensive capture system
4. **State Management**: Clean store isolation
5. **Debugging Support**: Full execution trace

## Advanced Features

### Parallel Execution
```python
class ParallelExecutorNode(Node):
    """Execute independent nodes in parallel"""
    def exec(self, shared):
        parallel_group = shared["parallel_nodes"]

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = {}

            for node in parallel_group:
                future = executor.submit(
                    self._execute_node,
                    node,
                    shared["node_stores"][node["id"]]
                )
                futures[future] = node

            # Collect results
            for future in concurrent.futures.as_completed(futures):
                node = futures[future]
                try:
                    result = future.result()
                    shared["node_outputs"][node["id"]] = result
                except Exception as e:
                    shared["node_errors"][node["id"]] = str(e)

        return "continue"
```

### Checkpoint Support
```python
class CheckpointNode(Node):
    """Save execution state for resume"""
    def exec(self, shared):
        if shared.get("checkpoint_enabled"):
            checkpoint = {
                "runtime_id": shared["runtime_id"],
                "completed_nodes": shared["completed_nodes"],
                "workflow_store": shared["workflow_store"],
                "timestamp": datetime.now().isoformat()
            }

            checkpoint_path = Path(f".pflow/checkpoints/{shared['runtime_id']}.json")
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

            with open(checkpoint_path, 'w') as f:
                json.dump(checkpoint, f)

            shared["checkpoint_saved"] = str(checkpoint_path)

        return "continue"
```

## Performance Monitoring

```python
class PerformanceMonitorNode(Node):
    """Track execution metrics"""
    def exec(self, shared):
        node_id = shared["current_node"]["id"]

        # Start timing
        start_time = time.perf_counter()
        start_memory = psutil.Process().memory_info().rss

        # Execute (would be done by executor)
        yield "execute"

        # Collect metrics
        end_time = time.perf_counter()
        end_memory = psutil.Process().memory_info().rss

        shared["performance_metrics"][node_id] = {
            "duration": end_time - start_time,
            "memory_delta": end_memory - start_memory,
            "cpu_percent": psutil.cpu_percent(interval=0)
        }

        return "continue"
```

## Future Extensions

1. **Distributed Execution**: Run nodes on multiple machines
2. **GPU Support**: Accelerate ML nodes
3. **Real-time Monitoring**: Live execution dashboard
4. **Advanced Debugging**: Step-through execution
