# Refined Specification for 8.5

## Clear Objective
Add configurable stdout output from shared store and implement proper signal handling with exit codes for Unix pipe compatibility.

## Context from Knowledge Base
- Building on: Shell integration utilities from 8.1, CLI patterns from 8.2, binary handling from 8.4
- Avoiding: Platform-specific code without checks, breaking backward compatibility
- Following: Click option patterns, test-as-you-go strategy, proper resource cleanup
- **Cookbook patterns to apply**: N/A (utility enhancement, not PocketFlow node)

## Technical Specification

### Part 1: Stdout Output from Shared Store

#### CLI Option
Add `--output-key` option to the run command:
```python
@click.option('--output-key', '-o', 'output_key',
              help='Shared store key to output to stdout (default: auto-detect)')
```

#### Output Logic
After workflow execution (line 245 in main.py):
1. If `--output-key` specified:
   - Check if key exists in shared_storage
   - If exists and is string: output value
   - If exists and is bytes: skip with stderr warning
   - If missing: show error to stderr
2. If no `--output-key` specified:
   - Check keys in order: 'response', 'output', 'result', 'text'
   - Output first matching string value
   - Skip if no matches found

#### Success Message Handling
- When outputting: Suppress "Workflow executed successfully" message
- When not outputting: Keep existing success message

### Part 2: Signal Handling and Exit Codes

#### SIGPIPE Handler
Add after existing SIGINT handler (around line 369):
```python
# Handle broken pipe for shell compatibility
if hasattr(signal, 'SIGPIPE'):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
```

#### BrokenPipeError Handling
Wrap output operations with try/except:
```python
try:
    click.echo(output_value)
except BrokenPipeError:
    # Exit cleanly when pipe is closed
    os._exit(0)
```

#### Exit Codes
Continue using existing pattern:
- 0: Success (default)
- 1: General error (current pattern)
- 130: SIGINT (already implemented)

### Implementation Constraints
- Must use: Click's option decorators for --output-key
- Must avoid: Platform-specific code without hasattr checks
- Must maintain: Backward compatibility (existing behavior when no output)

## Success Criteria
- [ ] `pflow run -f workflow.json | grep pattern` works correctly
- [ ] `pflow run -f workflow.json --output-key result` outputs specified key
- [ ] Binary values are skipped with appropriate warning
- [ ] SIGPIPE handled gracefully (no error on `| head`)
- [ ] Ctrl+C continues to exit with code 130
- [ ] Success message suppressed when outputting
- [ ] All existing tests continue to pass
- [ ] New tests cover output scenarios

## Test Strategy

### Unit Tests
- Test output key detection logic
- Test binary vs text output handling
- Test missing key error handling

### Integration Tests
- Test actual subprocess piping scenarios
- Test signal handling with real processes
- Test exit code propagation

### Manual Verification
- Test with common Unix tools (grep, head, wc)
- Test Ctrl+C during execution
- Test broken pipe scenarios

## Dependencies
- Requires: Shared store populated by workflow execution
- Impacts: Terminal output behavior when using workflows

## Decisions Made
- Output first matching key in priority order (Option A - simple and predictable)
- Skip binary output with warning (Option B - safe for terminal)
- Always output when key exists (Option A - consistent behavior)
- Keep current exit code pattern (Option A - sufficient for MVP)
