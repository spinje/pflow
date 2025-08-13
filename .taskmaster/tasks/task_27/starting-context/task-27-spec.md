# Feature: planner_debugging_capabilities

## Objective

Enable visibility into planner execution failures.

## Requirements

- Must show which node is currently executing
- Must timeout gracefully after configurable duration
- Must capture all LLM prompts and responses
- Must not modify existing node implementations
- Must automatically save traces on failure
- Must display clean progress in terminal

## Scope

- Does not provide interactive debugging
- Does not profile memory usage
- Does not modify existing node code
- Does not manage trace file rotation
- Does not provide web UI
- Does not stream trace data in real-time

## Inputs

- `trace_flag`: bool - CLI flag --trace to force trace generation
- `timeout_seconds`: int - CLI flag --planner-timeout (default 60)
- `trace_dir`: str - CLI flag --trace-dir (default ~/.pflow/debug)
- `PFLOW_TRACE_ALWAYS`: str - Environment variable to always save traces
- `PFLOW_TRACE_DIR`: str - Environment variable for trace directory
- `PFLOW_PLANNER_TIMEOUT`: str - Environment variable for timeout seconds

## Outputs

Returns: Dict containing planner_output and optional trace_file path
Side effects:
- Progress indicators printed to stderr via click.echo
- JSON trace file saved to ~/.pflow/debug/ on failure or when requested
- Timeout detected and logged after configured duration

## Structured Formats

```json
{
  "trace_schema": {
    "execution_id": "string",
    "timestamp": "ISO8601",
    "user_input": "string",
    "status": "success|failed|timeout",
    "duration_ms": "number",
    "path_taken": "A|B",
    "llm_calls": [
      {
        "node": "string",
        "timestamp": "ISO8601",
        "duration_ms": "number",
        "model": "string",
        "prompt": "string",
        "response": "object",
        "tokens": {"input": "number", "output": "number"},
        "error": "string|null"
      }
    ],
    "node_execution": [
      {
        "node": "string",
        "start_time": "ISO8601",
        "phases": {
          "prep": {"duration_ms": "number"},
          "exec": {"duration_ms": "number", "had_llm_call": "boolean"},
          "post": {"duration_ms": "number", "action": "string"}
        }
      }
    ],
    "final_shared_store": "object",
    "error": {
      "type": "timeout|validation|llm_error",
      "message": "string",
      "node": "string",
      "phase": "string"
    }
  }
}
```

## State/Flow Changes

- `executing` → `timeout` when execution exceeds timeout duration
- `executing` → `failed` when planner raises exception
- `executing` → `success` when planner completes successfully
- `trace_pending` → `trace_saved` when trace file written to disk

## Constraints

- Timeout must be between 10 and 600 seconds
- Trace directory must be writable
- Node wrapper must preserve all original node attributes
- Node wrapper must handle special methods (__copy__, __deepcopy__)
- Progress output must use click.echo with err=True
- LLM interception must restore original methods after execution
- LLM interception at prompt method level, not module level

## Rules

1. Display progress when entering each node via wrapper._run()
2. Start timeout timer before flow.run() execution
3. Cancel timeout timer after flow.run() completion
4. Save trace file when planner fails
5. Save trace file when --trace flag is provided
6. Save trace file when timeout detected
7. Wrap all planner nodes with DebugWrapper
8. Intercept llm.get_model() calls at prompt method level
9. Record prompt before LLM call execution
10. Record response after LLM call completion
11. Use node.__class__.__name__ when node.name is absent
12. Create ~/.pflow/debug/ directory if it does not exist
13. Generate unique trace filename with timestamp
14. Include user_input in trace file
15. Include final_shared_store in trace file
16. Restore original LLM methods in finally block
17. Use threading.Timer for timeout detection
18. Check timeout flag after flow.run() completes
19. Delegate unknown attributes via __getattr__
20. Use click.echo with err=True for progress output
21. Implement __copy__ method in DebugWrapper for Flow compatibility

## Edge Cases

- Trace directory not writable → log error to stderr
- Timeout during LLM call → timeout detected after completion only
- Node has no name attribute → use class name
- LLM returns None → record as error in trace
- Trace file exceeds 100MB → truncate LLM responses
- Multiple planner calls → each gets own timeout
- Flow raises during prep phase → save trace with prep data only
- JSON serialization fails → use str() for non-serializable objects
- Flow calls copy.copy() on wrapper → __copy__ must return valid wrapper

## Error Handling

- Permission denied on trace save → log to stderr and continue
- LLM interception fails → log warning and continue without tracing
- Progress display interrupted → continue execution
- Timeout handler raises → log error and continue

## Non-Functional Criteria

- Wrapper delegation adds minimal overhead (~5%)
- Wrapper must observe only, not recreate Flow logic
- Trace file writes synchronously (single-threaded)
- Progress shown once per node execution
- Timeout detection occurs after flow completion only
- Single-threaded execution maintained

## Examples

```bash
# Successful execution without trace
$ pflow "create changelog"
🔍 Discovery... ✓ 2.1s
📝 Parameters... ✓ 1.5s
✅ Workflow ready: generate-changelog

# Timeout with automatic trace
$ pflow "complex request"
🔍 Discovery... ✓ 2.1s
🤖 Generating...
❌ Planner timeout after 60s
📝 Debug trace saved: ~/.pflow/debug/pflow-trace-20240111-103000.json

# Explicit trace request
$ pflow "analyze data" --trace
🔍 Discovery... ✓ 2.1s
✅ Workflow ready: analyzer
📝 Trace saved: ~/.pflow/debug/pflow-trace-20240111-104000.json
```

## Test Criteria

1. Progress indicators appear via wrapper._run()
2. Timeout detected after 60 seconds default
3. Timeout detected after --planner-timeout value
4. Trace file saved on timeout detection
5. Trace file saved on planner exception
6. Trace file saved with --trace flag
7. Trace file contains all LLM prompts
8. Trace file contains all LLM responses
9. Node wrapper preserves successors attribute
10. Node wrapper delegates unknown attributes
11. LLM interception captures model.prompt calls
12. LLM methods restored after execution
13. Node name uses class name when name absent
14. ~/.pflow/debug/ directory created if missing
15. Unique trace filename includes timestamp
16. User input included in trace
17. Final shared store included in trace
18. Threading.Timer cancels on success
19. Timeout flag checked after flow.run()
20. click.echo used with err=True for progress
21. Trace directory permission error logged
22. Timeout during LLM detected after completion
23. Class name used when node.name missing
24. LLM None response recorded as error
25. Large trace truncates LLM responses
26. Multiple planner calls get separate timeouts
27. Prep phase error saves partial trace
28. JSON serialization uses str() for objects
29. DebugWrapper implements __copy__ method correctly

## Notes (Why)

- Progress indicators reduce user anxiety during 10-30 second waits
- Automatic trace on failure ensures debugging data is never lost
- Node wrapping avoids modifying tested production code
- JSON format enables programmatic analysis by AI agents
- Timeout protection prevents infinite hangs
- LLM prompt/response capture enables prompt improvement

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 2, 3                       |
| 3      | 18                         |
| 4      | 5                          |
| 5      | 6                          |
| 6      | 4                          |
| 7      | 9, 10                      |
| 8      | 11                         |
| 9      | 7                          |
| 10     | 8                          |
| 11     | 13, 23                     |
| 12     | 14                         |
| 13     | 15                         |
| 14     | 16                         |
| 15     | 17                         |
| 16     | 12                         |
| 17     | 2, 3, 18                   |
| 18     | 19                         |
| 19     | 10                         |
| 20     | 20                         |
| 21     | 29                         |

## Versioning & Evolution

- v1.0.0 — Initial debugging capabilities with progress and traces
- v1.1.0 — (Future) Add trace-viewer command
- v2.0.0 — (Future) Add trace analysis tools

## Epistemic Appendix

### Assumptions & Unknowns

- Verified: flow.run() is synchronous and blocking
- Verified: llm.get_model() is the only LLM entry point in planner
- Verified: click.echo() outputs immediately to stderr with err=True
- Unknown: Maximum practical trace file size before truncation needed
- Verified: Single-threaded execution makes monkey-patching safe

### Conflicts & Resolutions

- PRD specified "no modifications to nodes" vs need for debugging data → Resolution: Use wrapper pattern with delegation
- Need for thread interruption vs Python limitations → Resolution: Timeout detection only, cannot interrupt running thread
- Default /tmp vs platform consistency → Resolution: Use ~/.pflow/debug/ matching existing patterns

### Decision Log / Tradeoffs

- Chose wrapper pattern over AST modification for simplicity and safety
- Chose JSON traces over binary format for searchability by AI agents
- Chose threading.Timer for timeout detection (cannot interrupt, only detect)
- Chose 60s default timeout as balance between patience and hang detection
- Chose ~/.pflow/debug/ to match existing directory patterns
- Chose LLM interception at prompt level over module level for cleaner boundary
- Main agent implements all code (no code-implementer subagent needed)

### Ripple Effects / Impact Map

- Affects planner execution performance (~5% overhead)
- Touches create_planner_flow() function
- Creates new debug.py and debug_utils.py modules
- Adds CLI flags to main command
- May affect test timeout expectations
- Test infrastructure uses LLM-level mocking (clean imports)

### Residual Risks & Confidence

- Risk: Cannot interrupt hung LLM calls; Mitigation: Detect timeout after completion; Confidence: High (Python limitation)
- Risk: Large traces exhaust disk space; Mitigation: Truncation at 100MB; Confidence: High
- Risk: Progress output interferes with piped output; Mitigation: Use stderr via err=True; Confidence: High
- Risk: Wrapper breaks Flow compatibility; Mitigation: Delegate all attributes + implement __copy__; Confidence: High
- Risk: Logging interference; Mitigation: Don't use logging.basicConfig(); Confidence: High

### Epistemic Audit (Checklist Answers)

1. Verified synchronous execution, single-threaded model, LLM entry points
2. If wrong: timeout detection fails, LLM capture misses calls
3. Prioritized robustness (wrapping) over elegance (modification)
4. All rules mapped to tests, all tests map to rules/edges
5. Touches planner flow creation and CLI execution paths only
6. Remaining uncertainty: trace file size limits; Overall confidence: High