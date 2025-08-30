# Planner Debugging Features

> **Navigation**: [Index](../index.md) → Features → Debugging

## Overview

The pflow planner provides comprehensive debugging capabilities to help developers understand and troubleshoot workflow generation. These features provide visibility into the planner's decision-making process, LLM interactions, and execution flow.

## Key Features

### 1. Real-Time Progress Indicators
Always-on progress display showing which planner nodes are executing:

```
🔍 Discovery... ✓ 2.1s
📦 Browsing... ✓ 1.8s
🤖 Generating... ✓ 3.2s
```

### 2. Trace Files
Detailed JSON traces capturing:
- All LLM prompts and responses
- Node execution times
- Path taken (A: reuse or B: generate)
- Errors and validation issues
- Final workflow IR

### 3. Timeout Detection
Configurable timeout to detect hung operations with automatic trace saving.

## CLI Flags

### `--trace`
Save a debug trace file even on successful execution.

```bash
# Save trace for successful workflow generation
pflow --trace "create a workflow that summarizes news articles"
```

Output:
```
📝 Trace saved: ~/.pflow/debug/pflow-trace-20250114-103000.json
```

### `--planner-timeout <seconds>`
Set timeout for planner execution (default: 60 seconds).

```bash
# Allow up to 120 seconds for complex planning
pflow --planner-timeout 120 "complex multi-step workflow"
```

If timeout is exceeded:
```
⏰ Operation exceeded 120s timeout
📝 Debug trace saved: ~/.pflow/debug/pflow-trace-20250114-104500.json
```

## Trace File Location

All trace files are saved to:
```
~/.pflow/debug/pflow-trace-YYYYMMDD-HHMMSS.json
```

## Understanding Trace Files

### Trace Structure

```json
{
  "execution_id": "uuid",
  "timestamp": "2025-01-14T10:30:00Z",
  "user_input": "original natural language request",
  "status": "success|failed|timeout",
  "duration_ms": 15234,
  "path_taken": "A|B",  // A=reuse, B=generate
  "llm_calls": [...],
  "node_execution": [...],
  "events": [...],
  "final_shared_store": {...},
  "error": {...}  // Only if failed
}
```

### Path A vs Path B

The planner has two execution paths:

- **Path A (Reuse)**: Found existing workflow to adapt
  - WorkflowDiscoveryNode → ParameterMappingNode → ParameterPreparationNode
  - Typically 5-10 seconds

- **Path B (Generate)**: Creating new workflow
  - WorkflowDiscoveryNode → ComponentBrowsingNode → ParameterDiscoveryNode → WorkflowGeneratorNode → ValidatorNode → MetadataGenerationNode
  - Typically 20-30 seconds

### LLM Call Details

Each LLM call in the trace contains:

```json
{
  "node": "WorkflowDiscoveryNode",
  "timestamp": "2025-01-14T10:30:05Z",
  "model": "anthropic/claude-sonnet-4-0",
  "prompt": "Full prompt text...",
  "response": {
    // Structured response from LLM
  },
  "duration_ms": 2134,
  "tokens": {
    "input": 450,
    "output": 230
  }
}
```

## Progress Indicators

Progress indicators appear automatically during planner execution:

| Node | Icon | Description |
|------|------|-------------|
| WorkflowDiscoveryNode | 🔍 Discovery | Searching for existing workflows |
| ComponentBrowsingNode | 📦 Browsing | Finding relevant components |
| ParameterDiscoveryNode | 🔎 Parameters Discovery | Extracting parameters from request |
| ParameterMappingNode | 📝 Parameters | Mapping user inputs to workflow |
| WorkflowGeneratorNode | 🤖 Generating | Creating new workflow |
| ValidatorNode | ✅ Validation | Validating generated workflow |
| MetadataGenerationNode | 💾 Metadata | Adding workflow metadata |
| ParameterPreparationNode | 📋 Preparation | Preparing final parameters |
| ResultPreparationNode | 📤 Finalizing | Assembling final result |

## Common Use Cases

### 1. Debugging Failed Workflow Generation

When the planner fails, a trace is automatically saved:

```bash
$ pflow "invalid or ambiguous request"
❌ Planner failed: Validation error
📝 Debug trace saved: ~/.pflow/debug/pflow-trace-20250114-105000.json
```

Examine the trace to see:
- Which node failed
- The error message
- The LLM's responses leading to failure

### 2. Optimizing Prompt Engineering

Use traces to improve prompts:

```bash
$ pflow --trace "your workflow request"
$ cat ~/.pflow/debug/pflow-trace-*.json | jq '.llm_calls[0].prompt'
```

Review prompts to:
- Identify ambiguous instructions
- Find missing context
- Optimize for better LLM responses

### 3. Performance Analysis

Analyze execution times:

```bash
$ cat ~/.pflow/debug/pflow-trace-*.json | jq '.node_execution[] | "\(.node): \(.duration_ms)ms"'
```

Output:
```
"WorkflowDiscoveryNode: 2134ms"
"ComponentBrowsingNode: 1823ms"
"ParameterDiscoveryNode: 1567ms"
...
```

### 4. Understanding Path Selection

Check why the planner chose reuse vs generation:

```bash
$ cat ~/.pflow/debug/pflow-trace-*.json | jq '{path: .path_taken, discovery: .llm_calls[0].response}'
```

## Troubleshooting

### No Trace File Created

If no trace file appears with `--trace`:
1. Check if the command completed (not interrupted)
2. Verify write permissions to `~/.pflow/debug/`
3. Look for error messages about file writing

### Empty LLM Calls

If `llm_calls` array is empty in trace:
1. Ensure LLM API keys are configured
2. Check if planner actually executed (vs cached result)
3. Verify the request triggered LLM usage

### Timeout Issues

If experiencing frequent timeouts:
1. Increase timeout: `--planner-timeout 120`
2. Simplify the natural language request
3. Check network connectivity to LLM API
4. Review trace for slow nodes

## Implementation Details

### Architecture

The debugging system uses a wrapper pattern to instrument planner nodes without modifying them:

```
DebugWrapper
├── Wraps each planner node
├── Intercepts prep/exec/post phases
├── Records timing and results
└── Captures LLM calls via monkey-patching
```

### LLM Interception

LLM calls are captured by temporarily replacing `llm.get_model()` with an interceptor that:
1. Records the prompt before sending
2. Captures the response after receiving
3. Measures execution time
4. Extracts token usage if available

### Performance Impact

Debugging features have minimal performance impact:
- Progress indicators: < 1ms per node
- Trace collection: < 10ms total overhead
- LLM interception: < 5ms per call
- File writing: Async, doesn't block execution

## Related Documentation

- [Planner Architecture](planner.md) - How the planner works
- [CLI Reference](../reference/cli-reference.md) - All CLI flags
- [Workflow Analysis](workflow-analysis.md) - Why debugging matters

## Future Enhancements

Planned improvements for v2.0:
- Interactive debugging mode
- Trace file viewer CLI command
- Automatic trace analysis
- Performance profiling
- Cost tracking for LLM calls