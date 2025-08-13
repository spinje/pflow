# Integration Overview - Task 27

## Architecture Summary

```
User Input → CLI (with flags) → Wrapped Planner → Output + Trace
                ↓                      ↓
          Timeout Timer          Progress Display
                                       ↓
                                  Debug Trace File
```

## Component Interaction

### 1. CLI Entry Point
- User runs: `pflow "request" --trace --planner-timeout 120`
- CLI parses flags
- Calls planner with debug enabled

### 2. Debug Wrapping
- `create_planner_flow_with_debug()` creates wrapped nodes
- Each node wrapped with `DebugWrapper`
- `TraceCollector` and `PlannerProgress` shared between wrappers

### 3. Execution Flow
```python
# Simplified execution flow
flow, trace = create_planner_flow_with_debug(user_input, trace=True)
timer = threading.Timer(timeout, lambda: timed_out.set())
timer.start()

try:
    flow.run(shared)  # Synchronous, blocking - CANNOT BE INTERRUPTED

    # IMPORTANT: Timeout can only be detected AFTER completion
    # Python limitation: threads cannot be interrupted
    if timed_out.is_set():
        # Operation took too long (but completed)
        # Save trace, show timeout message
    else:
        # Normal completion within timeout
finally:
    timer.cancel()
```

### 4. During Execution
- Each node's `_run()` called by Flow
- DebugWrapper intercepts and:
  - Shows progress: `🔍 Discovery...`
  - Times execution
  - Intercepts LLM calls if node uses LLM
  - Records in TraceCollector
  - Shows completion: `✓ 2.1s`

### 5. LLM Interception (at prompt level, not module level)
```python
# When node has model_name in prep_res:
original_get_model = llm.get_model

def intercept_get_model(*args, **kwargs):
    model = original_get_model(*args, **kwargs)
    original_prompt = model.prompt

    def intercept_prompt(prompt_text, **kwargs):
        # Record before/after at prompt level
        trace.record_llm_request(node_name, prompt_text, kwargs)
        response = original_prompt(prompt_text, **kwargs)
        trace.record_llm_response(node_name, response, duration)
        return response

    model.prompt = intercept_prompt  # Intercept at prompt method
    return model

llm.get_model = intercept_get_model
try:
    node.exec(prep_res)  # Makes LLM calls
finally:
    llm.get_model = original_get_model  # Always restore
```

### 6. Trace Collection
- Accumulates throughout execution
- Records: nodes, timing, LLM calls, errors
- Detects Path A vs B based on nodes executed
- Saves to JSON at end if needed

## File Structure

```
src/pflow/planning/
├── debug.py              # DebugWrapper, TraceCollector, PlannerProgress
├── debug_utils.py        # Utility functions (save_trace, format_progress, etc.)
└── flow.py              # Modified: create_planner_flow_with_debug()

src/pflow/cli/
└── main.py              # Modified: New flags, timeout execution

tests/test_planning/
├── test_debug.py         # Unit tests
├── test_debug_integration.py  # Integration tests
└── test_debug_utils.py   # Utility tests

tests/test_cli/
└── test_debug_flags.py   # CLI flag tests
```

## Data Flow

### Progress Output (Terminal)
```
🔍 Discovery... ✓ 2.1s
📦 Browsing... ✓ 1.8s
🤖 Generating... ✓ 3.2s
```

### Trace File (JSON)
```json
{
  "execution_id": "uuid",
  "user_input": "...",
  "path_taken": "B",
  "llm_calls": [
    {
      "node": "WorkflowDiscoveryNode",
      "prompt": "Full prompt text...",
      "response": {...},
      "duration_ms": 2100
    }
  ],
  "node_execution": [...],
  "final_shared_store": {...}
}
```

## Critical Success Factors

### 1. Node Compatibility
- DebugWrapper MUST preserve all node attributes
- MUST delegate unknown attributes via __getattr__
- MUST handle special methods (__copy__, __deepcopy__)
- MUST NOT break node lifecycle
- MUST NOT recreate Flow logic (wrap only)

### 2. LLM Interception
- MUST intercept at prompt method level (not module level)
- MUST capture before call (prompt)
- MUST capture after call (response)
- MUST restore original methods in finally block

### 3. Performance
- Progress output should be immediate
- Wrapper overhead should be minimal (~5%)
- Trace save should be fast
- Timeout detection after completion only

### 4. Error Handling
- Failures MUST save trace
- Timeout MUST be detected (after completion)
- Errors MUST be logged
- Non-serializable objects use default=str

## Implementation Order

1. **Phase 1**: Main agent creates debug.py with all classes
2. **Phase 2**: Main agent creates debug_utils.py with utilities
3. **Phase 3**: Main agent integrates into flow.py and cli/main.py
4. **Phase 4**: Test-writer creates all tests using new mock infrastructure
5. **Phase 5**: Manual testing and refinement

## Integration Points

### CLI → Planner
```python
# In CLI main.py
if needs_planner:
    result = execute_with_planner_debug(
        user_input,
        timeout=timeout_value,
        trace=trace_flag
    )
```

### Planner → Debug
```python
# In flow.py
def create_planner_flow_with_debug(user_input, trace=False):
    trace_collector = TraceCollector(user_input)
    progress = PlannerProgress()

    # Wrap all nodes
    node = DebugWrapper(original_node, trace_collector, progress)
```

### Debug → Output
```python
# Progress to terminal
click.echo("🔍 Discovery...", err=True)

# Trace to file
trace_path = trace_collector.save_to_file()
```

## Environment Setup

### Required Imports
```python
import time
import json
import uuid
import threading
from pathlib import Path
from datetime import datetime
import click
import llm
```

### Directory Structure
```
~/.pflow/
└── debug/           # Trace files saved here
    ├── pflow-trace-20240111-103000.json
    └── pflow-trace-20240111-104000.json
```

## Validation Checklist

Before considering complete:

- [ ] Can run: `pflow "test" --trace`
- [ ] See progress indicators during execution
- [ ] Trace file saved to ~/.pflow/debug/
- [ ] Trace contains LLM prompts/responses
- [ ] Timeout detected after 60s
- [ ] Existing planner still works
- [ ] All tests pass

## Common Issues and Solutions

### Issue: Nodes don't execute
**Solution**: Check DebugWrapper delegates all attributes and handles special methods

### Issue: RecursionError with copy.copy()
**Solution**: Implement __copy__ and __deepcopy__ methods in wrapper

### Issue: No progress shown
**Solution**: Verify click.echo uses err=True, check logging not interfering

### Issue: LLM calls not captured
**Solution**: Check model_name in prep_res detection, verify prompt interception

### Issue: Timeout doesn't interrupt
**Solution**: Expected - Python limitation, can only detect after completion

### Issue: Trace file invalid JSON
**Solution**: Use default=str in json.dump()

### Issue: Tests fail with mock errors
**Solution**: Use new LLM-level mock infrastructure, not module-level