# Task 23: Tracing and Logging System - PocketFlow Implementation Guide

## Overview
This task implements comprehensive tracing and logging for pflow workflows, providing observability into execution flow, performance metrics, and debugging information. PocketFlow orchestrates the complex flow of trace collection, aggregation, and output formatting.

## PocketFlow Architecture

### Flow Structure
```
InitTracing >> ConfigureHandlers >> AttachToRuntime >> CollectTraces >> AggregateMetrics >> FormatOutput
      |                |                   |                |                  |                |
      v                v                   v                v                  v                v
 InitError      ConfigError         AttachError      CollectError      AggregateError      FormatError
                                                           |
                                                           v
                                                    BufferOverflow >> FlushTraces
```

### Key Nodes

#### 1. TracingInitNode
```python
class TracingInitNode(Node):
    """Initialize tracing system with configurable backends"""
    def __init__(self, config):
        super().__init__()
        self.config = config

    def exec(self, shared):
        # Create trace context
        trace_id = str(uuid.uuid4())
        shared["trace_id"] = trace_id
        shared["trace_buffer"] = deque(maxlen=10000)

        # Initialize backends
        backends = []

        if self.config.get("console", True):
            backends.append(ConsoleTraceBackend())

        if self.config.get("file"):
            backends.append(FileTraceBackend(self.config["file"]))

        if self.config.get("otlp"):
            backends.append(OTLPTraceBackend(self.config["otlp"]))

        shared["trace_backends"] = backends
        shared["trace_config"] = self.config

        # Set trace level
        shared["trace_level"] = self.config.get("level", "INFO")

        return "configure_handlers"
```

#### 2. TraceCollectorNode
```python
class TraceCollectorNode(Node):
    """Collect traces during workflow execution"""
    def __init__(self):
        super().__init__()
        self.span_stack = []

    def exec(self, shared):
        event_type = shared["trace_event_type"]

        if event_type == "workflow_start":
            return self._trace_workflow_start(shared)
        elif event_type == "node_start":
            return self._trace_node_start(shared)
        elif event_type == "node_end":
            return self._trace_node_end(shared)
        elif event_type == "error":
            return self._trace_error(shared)
        elif event_type == "custom":
            return self._trace_custom(shared)
        else:
            shared["error"] = f"Unknown trace event: {event_type}"
            return "error"

    def _trace_node_start(self, shared):
        node = shared["current_node"]
        parent_span = self.span_stack[-1] if self.span_stack else None

        # Create span
        span = {
            "trace_id": shared["trace_id"],
            "span_id": str(uuid.uuid4()),
            "parent_span_id": parent_span["span_id"] if parent_span else None,
            "operation": f"node.{node['type']}",
            "start_time": time.time_ns(),
            "attributes": {
                "node.id": node["id"],
                "node.type": node["type"],
                "node.config": json.dumps(node.get("config", {}))
            },
            "events": []
        }

        self.span_stack.append(span)
        shared["current_span"] = span

        # Add to buffer
        shared["trace_buffer"].append({
            "timestamp": span["start_time"],
            "type": "span_start",
            "data": span
        })

        return "continue"
```

#### 3. MetricsAggregatorNode
```python
class MetricsAggregatorNode(Node):
    """Aggregate performance metrics from traces"""
    def exec(self, shared):
        traces = list(shared["trace_buffer"])

        # Initialize metrics
        metrics = {
            "workflow_duration": 0,
            "node_durations": {},
            "node_counts": defaultdict(int),
            "error_count": 0,
            "success_rate": 0,
            "memory_usage": {},
            "throughput": {}
        }

        # Process spans
        spans = [t["data"] for t in traces if t["type"] == "span_end"]

        for span in spans:
            node_type = span["attributes"].get("node.type", "unknown")
            duration = span["duration_ns"] / 1e9  # Convert to seconds

            # Update metrics
            metrics["node_counts"][node_type] += 1

            if node_type not in metrics["node_durations"]:
                metrics["node_durations"][node_type] = {
                    "min": duration,
                    "max": duration,
                    "sum": duration,
                    "count": 1
                }
            else:
                stats = metrics["node_durations"][node_type]
                stats["min"] = min(stats["min"], duration)
                stats["max"] = max(stats["max"], duration)
                stats["sum"] += duration
                stats["count"] += 1

            # Memory metrics
            if "memory.used" in span["attributes"]:
                metrics["memory_usage"][span["span_id"]] = span["attributes"]["memory.used"]

        # Calculate derived metrics
        for node_type, stats in metrics["node_durations"].items():
            stats["avg"] = stats["sum"] / stats["count"]

        # Success rate
        total_nodes = sum(metrics["node_counts"].values())
        error_nodes = sum(1 for t in traces if t["type"] == "error")
        metrics["success_rate"] = (total_nodes - error_nodes) / total_nodes if total_nodes > 0 else 1.0

        shared["aggregated_metrics"] = metrics
        return "format_output"
```

#### 4. LogFormatterNode
```python
class LogFormatterNode(Node):
    """Format logs for different output targets"""
    def __init__(self):
        super().__init__()

    def exec(self, shared):
        format_type = shared.get("log_format", "json")
        traces = list(shared["trace_buffer"])

        if format_type == "json":
            return self._format_json(shared, traces)
        elif format_type == "human":
            return self._format_human(shared, traces)
        elif format_type == "otlp":
            return self._format_otlp(shared, traces)
        else:
            shared["error"] = f"Unknown format: {format_type}"
            return "error"

    def _format_human(self, shared, traces):
        """Human-readable log format"""
        lines = []
        indent_level = 0

        for trace in traces:
            if trace["type"] == "span_start":
                span = trace["data"]
                lines.append(
                    f"{'  ' * indent_level}→ {span['operation']} "
                    f"[{span['attributes'].get('node.id', 'unknown')}]"
                )
                indent_level += 1

            elif trace["type"] == "span_end":
                indent_level = max(0, indent_level - 1)
                span = trace["data"]
                duration_ms = span["duration_ns"] / 1e6
                lines.append(
                    f"{'  ' * indent_level}← {span['operation']} "
                    f"({duration_ms:.2f}ms)"
                )

            elif trace["type"] == "log":
                log = trace["data"]
                lines.append(
                    f"{'  ' * indent_level}  [{log['level']}] {log['message']}"
                )

        shared["formatted_output"] = "\n".join(lines)
        return "write_output"
```

#### 5. TraceExporterNode
```python
class TraceExporterNode(Node):
    """Export traces to configured backends"""
    def __init__(self):
        super().__init__(max_retries=3, wait=2)

    def exec(self, shared):
        backends = shared["trace_backends"]
        formatted_output = shared["formatted_output"]

        export_errors = []

        for backend in backends:
            try:
                if isinstance(backend, FileTraceBackend):
                    # Atomic write to file
                    self._write_to_file(backend.path, formatted_output)

                elif isinstance(backend, OTLPTraceBackend):
                    # Send to OTLP endpoint
                    self._send_otlp(backend, shared["trace_buffer"])

                elif isinstance(backend, ConsoleTraceBackend):
                    # Write to console with color support
                    self._write_console(formatted_output, backend.color)

            except Exception as e:
                export_errors.append({
                    "backend": type(backend).__name__,
                    "error": str(e)
                })

        if export_errors:
            shared["export_errors"] = export_errors
            return "partial_success"

        return "success"
```

## Implementation Plan

### Phase 1: Core Tracing
1. Create `src/pflow/flows/tracing/` structure
2. Implement trace collection nodes
3. Build span management
4. Create basic formatters

### Phase 2: Logging Integration
1. Add structured logging
2. Implement log levels
3. Create log correlation
4. Build filtering system

### Phase 3: Metrics & Analytics
1. Implement metrics aggregation
2. Add performance tracking
3. Create analytics nodes
4. Build dashboards

### Phase 4: Export & Integration
1. Add OTLP support
2. Implement file export
3. Create custom backends
4. Build real-time streaming

## Testing Strategy

### Unit Tests
```python
def test_span_lifecycle():
    """Test span creation and completion"""
    collector = TraceCollectorNode()
    shared = {
        "trace_id": "test-trace",
        "trace_buffer": deque(),
        "current_node": {"id": "n1", "type": "test_node"}
    }

    # Start span
    shared["trace_event_type"] = "node_start"
    result = collector.exec(shared)
    assert len(collector.span_stack) == 1
    assert shared["current_span"]["operation"] == "node.test_node"

    # End span
    shared["trace_event_type"] = "node_end"
    shared["node_result"] = "success"
    result = collector.exec(shared)
    assert len(collector.span_stack) == 0
    assert "duration_ns" in shared["current_span"]
```

### Integration Tests
```python
def test_full_trace_flow():
    """Test complete tracing workflow"""
    trace_flow = create_trace_flow()

    # Simulate workflow execution
    events = [
        {"type": "workflow_start", "workflow_id": "test"},
        {"type": "node_start", "node": {"id": "n1", "type": "read"}},
        {"type": "log", "level": "INFO", "message": "Reading file"},
        {"type": "node_end", "result": "success"},
        {"type": "workflow_end"}
    ]

    result = trace_flow.run({
        "trace_events": events,
        "log_format": "human"
    })

    assert "→ node.read [n1]" in result["formatted_output"]
    assert "[INFO] Reading file" in result["formatted_output"]
```

## Tracing Patterns

### Contextual Logging
```python
class ContextualLogger:
    """Logger that includes trace context"""
    def __init__(self, trace_buffer, current_span):
        self.buffer = trace_buffer
        self.span = current_span

    def log(self, level, message, **attributes):
        log_entry = {
            "timestamp": time.time_ns(),
            "level": level,
            "message": message,
            "trace_id": self.span["trace_id"],
            "span_id": self.span["span_id"],
            "attributes": attributes
        }

        # Add to trace buffer
        self.buffer.append({
            "timestamp": log_entry["timestamp"],
            "type": "log",
            "data": log_entry
        })

        # Add to span events
        self.span["events"].append(log_entry)
```

### Performance Tracking
```python
class PerformanceTracer:
    """Track detailed performance metrics"""
    def trace_node_execution(self, node_id, func):
        start_time = time.perf_counter_ns()
        start_memory = self._get_memory_usage()

        try:
            # Execute with CPU tracking
            with self._cpu_tracker() as cpu:
                result = func()

            end_time = time.perf_counter_ns()
            end_memory = self._get_memory_usage()

            # Record metrics
            metrics = {
                "duration_ns": end_time - start_time,
                "memory_delta": end_memory - start_memory,
                "cpu_percent": cpu.usage,
                "success": True
            }

        except Exception as e:
            end_time = time.perf_counter_ns()
            metrics = {
                "duration_ns": end_time - start_time,
                "success": False,
                "error": str(e)
            }
            raise

        return result, metrics
```

## Benefits of PocketFlow Approach

1. **Flexible Collection**: Multiple trace event types
2. **Buffered Processing**: Handle high-volume traces
3. **Export Resilience**: Retry failed exports
4. **Format Flexibility**: Multiple output formats
5. **Real-time Capability**: Stream processing support

## Advanced Features

### Distributed Tracing
```python
class DistributedTraceNode(Node):
    """Handle distributed trace correlation"""
    def exec(self, shared):
        # Extract trace context from headers/env
        trace_context = shared.get("trace_context")

        if trace_context:
            # Continue existing trace
            shared["trace_id"] = trace_context["trace_id"]
            shared["parent_span_id"] = trace_context["span_id"]
            shared["baggage"] = trace_context.get("baggage", {})
        else:
            # Start new trace
            shared["trace_id"] = self._generate_trace_id()
            shared["parent_span_id"] = None

        # Propagate context
        shared["propagated_context"] = {
            "trace_id": shared["trace_id"],
            "span_id": shared["current_span_id"],
            "flags": shared.get("trace_flags", 0)
        }

        return "continue"
```

### Sampling Strategy
```python
class TraceSamplerNode(Node):
    """Implement trace sampling for performance"""
    def __init__(self, sample_rate=0.1):
        super().__init__()
        self.sample_rate = sample_rate

    def exec(self, shared):
        # Deterministic sampling based on trace ID
        trace_id_hash = int(shared["trace_id"][:8], 16)
        should_sample = (trace_id_hash % 100) < (self.sample_rate * 100)

        if should_sample:
            shared["trace_sampled"] = True
            return "full_trace"
        else:
            # Only collect critical traces
            shared["trace_sampled"] = False
            return "minimal_trace"
```

## Output Formats

### JSON Format
```json
{
    "trace_id": "abc123",
    "spans": [
        {
            "span_id": "span1",
            "operation": "node.read_file",
            "start_time": 1234567890,
            "duration_ms": 45.2,
            "attributes": {
                "node.id": "reader",
                "file.path": "input.txt"
            }
        }
    ],
    "metrics": {
        "total_duration_ms": 234.5,
        "node_count": 5,
        "success_rate": 1.0
    }
}
```

### Human Format
```
Workflow Trace: abc123
→ workflow.start [2024-01-15 10:30:45]
  → node.read_file [reader]
    [INFO] Opening file: input.txt
    [DEBUG] File size: 1024 bytes
  ← node.read_file (45.2ms) ✓
  → node.transform [processor]
    [INFO] Processing 10 records
  ← node.transform (123.4ms) ✓
← workflow.end (234.5ms)

Summary:
- Total Duration: 234.5ms
- Nodes Executed: 2
- Success Rate: 100%
```

## Future Extensions

1. **APM Integration**: DataDog, New Relic support
2. **Custom Instrumentation**: User-defined trace points
3. **Anomaly Detection**: Identify performance issues
4. **Trace Analysis**: Pattern recognition
