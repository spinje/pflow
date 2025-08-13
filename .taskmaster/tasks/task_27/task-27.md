# Task 27: Planner Debugging Capabilities

## Problem Statement

The Natural Language Planner is currently failing/hanging with no visibility into:
- **WHERE** it fails (which node)
- **WHY** it fails (timeout, bad LLM response, validation error)
- **WHAT** the LLM sees (prompts) and returns (responses)

Developers and AI agents cannot debug or improve the planner without this visibility. Raw LLM output dumped to terminal is unreadable and unsearchable.

## Success Criteria

1. **Progress Visibility**: Always see which node is executing
2. **Timeout Detection**: Planner timeout detected after 60s
3. **LLM Debugging**: Full prompts/responses captured in searchable JSON format
4. **Zero Node Changes**: Implementation via wrapping, not modification
5. **Automatic Traces**: Failed executions always produce debug trace
6. **Clean UX**: Terminal shows progress only, details go to trace file

## Solution Overview

### Two-Mode System

#### Mode 1: Progress Indicators (Always On)
Terminal shows real-time progress with timing:
```
🔍 Discovery... ✓ 2.1s
📦 Browsing... ✓ 1.8s
🤖 Generating... ✓ 3.2s
```

#### Mode 2: Trace Files (On Failure or --trace)
JSON file with complete debugging information:
- All LLM prompts and responses
- Node execution timing
- Final shared store state
- Error details

### Key Design Decisions

1. **Always show progress** - Users need feedback during 10-30s waits
2. **Trace on failure** - Never miss debugging data for failures
3. **JSON for traces** - Searchable, parseable by AI agents
4. **Node wrapping** - No modifications to existing nodes
5. **Timeout detection** - 60s default, detects after completion

## Technical Specification

### 1. Progress Tracking

#### PlannerProgress Class
```python
class PlannerProgress:
    """Displays real-time progress in terminal"""

    def on_node_start(self, node_name: str):
        # Show: 🔍 Discovery...

    def on_node_complete(self, node_name: str, duration: float):
        # Show: 🔍 Discovery... ✓ 2.1s

```

#### Progress Icons
- 🔍 Discovery
- 📦 Component browsing
- 🤖 Generation
- ✅ Validation
- 📝 Parameter extraction
- 💾 Metadata generation
- ⚡ Path A (reuse)
- 🚀 Path B (generation)

### 2. Trace Collection

#### TraceCollector Class
```python
@dataclass
class TraceCollector:
    """Collects execution data for debugging"""

    execution_id: str
    start_time: float
    events: List[TraceEvent] = field(default_factory=list)
    llm_calls: List[LLMCall] = field(default_factory=list)

    def record_node_phase(self, node: str, phase: str, duration: float)
    def record_llm_call(self, node: str, prompt: str, response: Any, duration: float)
    def save_to_file(self) -> str
```

#### Trace JSON Schema
```json
{
  "execution_id": "uuid",
  "timestamp": "2024-01-11T10:30:00Z",
  "user_input": "analyze data.csv",
  "status": "success|failed|timeout",
  "duration_ms": 12400,
  "path_taken": "A|B",

  "llm_calls": [
    {
      "node": "WorkflowDiscoveryNode",
      "timestamp": "2024-01-11T10:30:00Z",
      "duration_ms": 2100,
      "model": "anthropic/claude-3-sonnet",
      "prompt": "[full prompt text]",
      "response": {
        "found": false,
        "confidence": 0.3
      },
      "tokens": {"input": 4500, "output": 120},
      "error": null
    }
  ],

  "node_execution": [
    {
      "node": "WorkflowDiscoveryNode",
      "start_time": "2024-01-11T10:30:00Z",
      "phases": {
        "prep": {"duration_ms": 120},
        "exec": {"duration_ms": 2100, "had_llm_call": true},
        "post": {"duration_ms": 10, "action": "not_found"}
      }
    }
  ],

  "final_shared_store": {
    "user_input": "...",
    "discovery_result": "...",
    "planner_output": "..."
  },

  "error": {
    "type": "timeout|validation|llm_error",
    "message": "...",
    "node": "WorkflowGeneratorNode",
    "phase": "exec"
  }
}
```

### 3. Node Wrapping

#### DebugWrapper Class
```python
class DebugWrapper:
    """Wraps PocketFlow nodes to capture debugging data"""

    def __init__(self, node: BaseNode, trace: TraceCollector, progress: PlannerProgress):
        self._wrapped = node
        self.trace = trace
        self.progress = progress
        # Copy critical Flow attributes directly
        self.successors = node.successors
        self.params = getattr(node, 'params', {})

    def __getattr__(self, name):
        """Delegate unknown attributes to wrapped node"""
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return getattr(self._wrapped, name)

    def __copy__(self):
        """CRITICAL: Flow uses copy.copy() on nodes - MUST implement!"""
        import copy
        return DebugWrapper(copy.copy(self._wrapped), self.trace, self.progress)

    def set_params(self, params):
        """Flow calls this to set parameters"""
        self.params = params
        if hasattr(self._wrapped, 'set_params'):
            self._wrapped.set_params(params)

    def _run(self, shared):
        """Main execution method called by Flow"""
        # This calls prep, exec, post in sequence
        node_name = getattr(self._wrapped, 'name', self._wrapped.__class__.__name__)
        self.progress.on_node_start(node_name)
        start_time = time.time()

        try:
            result = self._wrapped._run(shared)
            duration = time.time() - start_time
            self.progress.on_node_complete(node_name, duration)
            return result
        except Exception as e:
            duration = time.time() - start_time
            self.trace.record_error(node_name, str(e), duration)
            raise

    def prep(self, shared):
        # Record prep phase
        start = time.time()
        result = self._wrapped.prep(shared)
        self.trace.record_node_phase(self._wrapped.__class__.__name__, "prep", time.time() - start)
        return result

    def exec(self, prep_res):
        # Intercept LLM calls via monkey-patching
        start = time.time()

        # Set up LLM interception if this node uses LLM
        import llm
        original_get_model = None
        if 'model_name' in prep_res:  # Node uses LLM
            original_get_model = llm.get_model
            def intercept_get_model(*args, **kwargs):
                model = original_get_model(*args, **kwargs)
                original_prompt = model.prompt

                def intercept_prompt(prompt, **kwargs):
                    prompt_start = time.time()
                    self.trace.record_llm_request(self._wrapped.__class__.__name__, prompt, kwargs)
                    response = original_prompt(prompt, **kwargs)
                    self.trace.record_llm_response(
                        self._wrapped.__class__.__name__,
                        response,
                        time.time() - prompt_start
                    )
                    return response

                model.prompt = intercept_prompt
                return model
            llm.get_model = intercept_get_model

        try:
            result = self._wrapped.exec(prep_res)
        finally:
            if original_get_model:
                llm.get_model = original_get_model

        self.trace.record_node_phase(self._wrapped.__class__.__name__, "exec", time.time() - start)
        return result

    def post(self, shared, prep_res, exec_res):
        # Record post phase and action
        start = time.time()
        result = self._wrapped.post(shared, prep_res, exec_res)
        self.trace.record_node_phase(
            self._wrapped.__class__.__name__,
            "post",
            time.time() - start,
            {"action": result}
        )
        return result
```

### 4. Timeout Protection

```python
import threading
import click

def execute_planner_with_timeout(user_input: str, timeout: int = 60, trace: bool = False):
    """Execute planner with timeout detection"""

    flow = create_planner_flow(debug_mode=True)  # Always wrap for progress
    shared = {"user_input": user_input, "workflow_manager": WorkflowManager()}

    # Set up timeout detection
    timed_out = threading.Event()

    def timeout_handler():
        timed_out.set()

    timer = threading.Timer(timeout, timeout_handler)
    timer.start()

    try:
        # Run planner (this is synchronous and blocking)
        flow.run(shared)

        # Check if we timed out after completion
        if timed_out.is_set():
            click.echo(f"\n❌ Planner timeout detected after {timeout}s", err=True)
            # Save trace on timeout
            if "_trace_collector" in shared:
                trace_file = shared["_trace_collector"].save_to_file()
                click.echo(f"📝 Debug trace saved: {trace_file}", err=True)

        # Check result
        planner_output = shared.get("planner_output", {})

        # Save trace if requested or failed
        if trace or not planner_output.get("success", False):
            if "_trace_collector" in shared:
                trace_file = shared["_trace_collector"].save_to_file()
                if not planner_output.get("success", False):
                    click.echo(f"📝 Debug trace saved: {trace_file}", err=True)
                elif trace:
                    click.echo(f"📝 Trace saved: {trace_file}")

        return planner_output

    finally:
        timer.cancel()  # Cancel timer if we finished early
```

### 5. CLI Integration

#### New CLI Flags
```bash
# Always save trace (even on success)
pflow "request" --trace

# Custom timeout detection
pflow "request" --planner-timeout 120

# Custom trace directory
pflow "request" --trace-dir ~/.pflow/debug
```

#### Environment Variables
```bash
# Always save traces
export PFLOW_TRACE_ALWAYS=1

# Custom trace directory
export PFLOW_TRACE_DIR=~/.pflow/traces

# Custom timeout (seconds)
export PFLOW_PLANNER_TIMEOUT=120
```

### 6. Trace Viewer

Simple command to view trace summaries:
```bash
# Show trace summary
pflow trace-viewer /tmp/pflow-trace-xxx.json

# Output:
Execution ID: 550e8400-e29b-41d4
Status: timeout
Duration: 60.0s
Path: B (Generation)
Last Node: WorkflowGeneratorNode

LLM Calls (5):
  1. Discovery: 2.1s, 4500→120 tokens
  2. Browsing: 1.8s, 3800→95 tokens
  3. Parameters: 1.5s, 2200→80 tokens
  4. Generation: 60.0s, TIMEOUT

Error: Timeout in WorkflowGeneratorNode.exec()

To see full prompts: jq '.llm_calls[3].prompt' <trace-file>
```

## Implementation Plan

### Phase 1: Core Infrastructure (Priority 1)
1. Create `src/pflow/planning/debug.py` with:
   - `PlannerProgress` class
   - `TraceCollector` class
   - `DebugWrapper` class
2. Add timeout protection to planner execution
3. Wire up progress display (always on)

**Note on Node Identification**: Since nodes don't have consistent `name` attributes, use:
```python
node_name = getattr(node, 'name', node.__class__.__name__)
```
This gives us names like "WorkflowDiscoveryNode", "ComponentBrowsingNode", etc.

### Phase 2: Node Wrapping (Priority 2)
1. Modify `create_planner_flow()` to wrap nodes when debugging
2. Implement LLM call interception via monkey-patching
3. Test wrapper compatibility with Flow

### Phase 3: Trace Output (Priority 3)
1. Implement JSON trace serialization
2. Add automatic trace on failure
3. Add --trace CLI flag

### Phase 4: Trace Viewer (Priority 4)
1. Create `pflow trace-viewer` command
2. Add summary generation
3. Add helpful query examples

## Testing Strategy

**NOTE**: The test infrastructure now mocks at the LLM level, not module level. This means you can import from `pflow.planning.debug` normally and patch specific functions without issues. The `mock_llm_responses` fixture is provided globally.

### Unit Tests
- Progress display formatting
- Trace collection accuracy
- Node wrapper compatibility (including __copy__ handling)
- Timeout detection

### Integration Tests
- Full planner execution with tracing
- Failure trace generation
- LLM call capture
- Timeout handling

### Manual Testing Scenarios
1. **Successful execution** - Progress shown, no trace
2. **Successful with --trace** - Progress shown, trace saved
3. **Timeout** - Progress → timeout message → trace saved
4. **LLM error** - Progress → error → trace saved
5. **Validation failure** - Full execution → trace saved

## Out of Scope

- Interactive debugging (breakpoints, stepping)
- Performance profiling beyond timing
- Memory usage tracking
- Distributed tracing
- Trace file management/rotation
- Web UI for trace viewing
- Real-time streaming of trace data
- Modification of existing node implementations

## Success Metrics

1. **Timeout Detection Rate**: 100% of hangs detected within 65s
2. **Trace Completeness**: All LLM calls captured with full prompts/responses
3. **Performance Impact**: <5% overhead when not tracing
4. **Debug Success Rate**: Developers can identify failure cause from trace
5. **Zero Node Changes**: All existing nodes work without modification

## Future Enhancements

1. **Trace Analysis Tools** - Automated pattern detection in traces
2. **Trace Comparison** - Diff two traces to see what changed
3. **Cost Tracking** - Show cumulative LLM costs in trace
4. **Retry Visualization** - Show retry attempts clearly
5. **Prompt Templates** - Extract prompts for testing/improvement

## Example Usage

### Normal Execution (No Issues)
```bash
$ pflow "create a changelog from recent commits"
🔍 Discovery... ✓ 2.1s
📝 Parameters... ✓ 1.5s
✅ Workflow ready: generate-changelog
```

### Timeout with Auto-Trace
```bash
$ pflow "complex analysis request"
🔍 Discovery... ✓ 2.1s
📦 Browsing... ✓ 1.8s
🤖 Generating... [hangs]
❌ Planner timeout detected after 60s
📝 Debug trace saved: ~/.pflow/debug/pflow-trace-20240111-103000.json

To view: pflow trace-viewer ~/.pflow/debug/pflow-trace-20240111-103000.json
```

### Explicit Trace Request
```bash
$ pflow "analyze data.csv" --trace
🔍 Discovery... ✓ 2.1s
📦 Browsing... ✓ 1.8s
🤖 Generating... ✓ 3.2s
✅ Validation... ✓ 0.1s
📝 Parameters... ✓ 1.5s
✅ Workflow ready: data-analyzer
📝 Trace saved: ~/.pflow/debug/pflow-trace-20240111-104000.json
```

## Acceptance Criteria

- [ ] Progress indicators appear for all planner executions
- [ ] Planner times out after 60s with clear error message
- [ ] Failed executions automatically save trace file
- [ ] Trace files contain all LLM prompts and responses
- [ ] --trace flag forces trace file generation
- [ ] No modifications to existing node code
- [ ] trace-viewer command shows useful summary
- [ ] All existing planner tests still pass
- [ ] Documentation updated with debugging guide

## Dependencies
- Task 17 (Natural Language Planner) - Complete