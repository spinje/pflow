# Task 115 Review: Automatic Stdin Routing for Unix-First Piping

## Metadata
- **Implementation Date**: 2026-01-22
- **Status**: Complete
- **Branch**: `feat/stdin-routing`

## Executive Summary

Implemented explicit stdin routing via `"stdin": true` input declarations, enabling Unix-style workflow chaining (`pflow -p workflow1.json | pflow workflow2.json`). The implementation required a critical fix for FIFO pipe detection to prevent the downstream workflow from checking stdin before upstream data arrives. All 4016 tests pass.

## Implementation Overview

### What Was Built

1. **IR Schema Extension**: Added `stdin` boolean field to workflow input declarations
2. **Stdin Routing Logic**: Routes piped stdin to the input marked `"stdin": true`
3. **FIFO Pipe Detection**: Distinguishes real pipes from sockets to enable proper blocking
4. **Legacy Removal**: Completely removed the `${stdin}` shared store pattern

### Deviations from Original Spec

**FIFO Detection (Not in Spec)**: The spec assumed stdin routing was the only change needed. In reality, workflow chaining failed because `stdin_has_data()` used `select()` with timeout=0, which returns immediately before the upstream process writes data. This required detecting FIFO pipes and blocking appropriately.

**Error Function Signature**: Spec suggested `_route_stdin_to_params()` return `(params, error)` tuple. Implemented with `NoReturn` function `_show_stdin_routing_error()` instead, matching existing CLI patterns (direct `click.echo()` + `ctx.exit(1)`).

### Implementation Approach

The key insight was that stdin routing must happen **inside** `_validate_and_prepare_workflow_params()`, between parameter parsing and input validation. If routing happens after, required inputs fail validation before stdin is considered.

For workflow chaining, the solution distinguishes between:
- **FIFO pipes** (real `|` pipes): Return True immediately, let caller block on `sys.stdin.read()`
- **Other non-TTY** (sockets like Claude Code): Use `select()` with timeout=0 to avoid hanging

## Files Modified/Created

### Core Changes

| File | Change | Impact |
|------|--------|--------|
| `src/pflow/core/ir_schema.py` | Added `stdin` boolean field to input schema | Schema now accepts `"stdin": true` |
| `src/pflow/core/shell_integration.py` | Added FIFO detection in `stdin_has_data()`, removed `populate_shared_store()` | Workflow chaining works, legacy pattern removed |
| `src/pflow/core/__init__.py` | Removed `populate_shared_store` export | API cleanup |
| `src/pflow/runtime/workflow_validator.py` | Added multi-stdin validation | Rejects workflows with multiple `stdin: true` inputs |
| `src/pflow/cli/main.py` | Added stdin routing helpers, modified `_validate_and_prepare_workflow_params()` | Stdin routes to correct input before validation |
| `src/pflow/execution/executor_service.py` | Removed `populate_shared_store()` call | Legacy pattern fully removed |
| `src/pflow/planning/nodes.py` | Removed stdin checking from ParameterDiscoveryNode | Planner no longer knows about stdin |

### Test Files

| File | Purpose | Criticality |
|------|---------|-------------|
| `tests/test_cli/test_dual_mode_stdin.py` | Workflow chaining, error paths, CLI override | **Critical** - tests real subprocess piping |
| `tests/test_core/test_stdin_no_hang.py` | FIFO detection, socket fallback | **Critical** - prevents Claude Code regression |
| `tests/test_shell_integration.py` | Removed `populate_shared_store` tests | Cleanup |

## Integration Points & Dependencies

### Incoming Dependencies

```
CLI (_handle_named_workflow)
  → _validate_and_prepare_workflow_params(stdin_data=...)
    → _route_stdin_to_params()
      → _find_stdin_input()
```

### Outgoing Dependencies

```
stdin_has_data()
  → read_stdin() / read_stdin_enhanced()
    → CLI main loop
```

### Shared Store Keys

**Removed**:
- `shared["stdin"]` - Legacy pattern, no longer used
- `shared["stdin_binary"]` - Legacy pattern, no longer used
- `shared["stdin_path"]` - Legacy pattern, no longer used

**No new keys added** - stdin routes directly to workflow input params.

## Architectural Decisions & Tradeoffs

### Key Decisions

| Decision | Reasoning | Alternative Considered |
|----------|-----------|----------------------|
| Explicit `stdin: true` declaration | Predictable, agent-friendly, no magic | Type-based auto-detection (rejected - too magical) |
| FIFO detection via `stat.S_ISFIFO()` | Matches Unix tool behavior (cat, grep, jq) | Timeout-based waiting (rejected - unreliable) |
| CLI param overrides stdin | Debugging/testing flexibility | Stdin always wins (rejected - less useful) |
| Remove `${stdin}` entirely | `stdin: true` is strictly more flexible | Keep both patterns (rejected - confusing) |

### Technical Debt Incurred

**None significant**. The implementation is clean and follows existing patterns.

### Potential Future Work

- **Auto `-p` flag**: When stdout is piped, auto-enable print mode (separate task)
- **Binary stdin routing**: Currently only text is routed; binary could route to temp file path

## Testing Implementation

### Test Strategy Applied

1. **Unit tests**: FIFO detection, socket fallback behavior
2. **Integration tests**: Real subprocess piping with `shell=True`
3. **Behavior tests**: Error messages, CLI override, validation errors

### Critical Test Cases

| Test | What It Validates |
|------|-------------------|
| `test_workflow_chaining_producer_to_consumer` | **THE key test** - real subprocess pipe works |
| `test_three_stage_pipeline` | Multi-stage piping works |
| `test_stdin_has_data_returns_true_for_fifo` | FIFO detection returns True |
| `test_stdin_has_data_uses_select_for_non_fifo_non_tty` | Claude Code (socket) uses select() |
| `test_stdin_error_when_no_stdin_input_declared` | Error message is agent-friendly |

## Unexpected Discoveries

### Gotchas Encountered

1. **Workflow chaining timing**: Shell starts both processes simultaneously. Process B checks stdin before Process A writes. This is why FIFO detection was essential.

2. **Claude Code environment**: stdin is a socket (non-TTY, non-FIFO). The original `select()` fix must be preserved for sockets, only overridden for real FIFOs.

3. **SIGPIPE handling**: Already handled in main.py with `SIG_IGN`. Without this, large data piping would fail.

### Edge Cases Found

| Scenario | Behavior |
|----------|----------|
| Empty stdin (`echo -n "" \| pflow`) | Routes empty string (valid content) |
| Binary stdin | Not routed, falls back to normal required input behavior |
| Large stdin (>10MB) | Handled via temp file, not routed (text only) |
| Formatted JSON output | jq may fail parsing multi-line JSON - use `-c` for compact |

## Patterns Established

### Reusable Patterns

**FIFO Detection Pattern**:
```python
import stat
mode = os.fstat(sys.stdin.fileno()).st_mode
if stat.S_ISFIFO(mode):
    # Real pipe - block on read
    return True
# Socket/other - use non-blocking check
```

**Agent-Friendly Error Messages**:
```python
def _show_stdin_routing_error(ctx: click.Context) -> NoReturn:
    click.echo("❌ Piped input cannot be routed to workflow", err=True)
    click.echo('   This workflow has no input marked with "stdin": true.', err=True)
    # Show JSON example of the fix
    click.echo('     "inputs": {', err=True)
    click.echo('       "data": {"type": "string", "required": true, "stdin": true}', err=True)
    click.echo("     }", err=True)
    ctx.exit(1)
```

### Anti-Patterns to Avoid

1. **Don't use `select()` alone for pipe detection** - It fails for workflow chaining because downstream checks before upstream writes.

2. **Don't put stdin in shared store** - It bypasses input validation and loses CLI override capability.

3. **Don't auto-detect stdin target by type** - Explicit declaration is more predictable for agents.

## Breaking Changes

### API/Interface Changes

- **Removed**: `populate_shared_store()` function from public API
- **Removed**: `${stdin}` template variable support

### Behavioral Changes

- Piping to workflow without `stdin: true` now shows helpful error (previously silent failure)
- Workflows with `stdin: true` work identically via pipe OR CLI args

## Future Considerations

### Extension Points

1. **Auto `-p` flag** (Task mentioned in task-115.md): When stdout is piped, auto-enable print mode
2. **Binary stdin routing**: Route to temp file path for binary data inputs
3. **Multiple stdin sources**: Currently one input; could support named pipes

### Scalability Concerns

None. FIFO detection is O(1) syscall. No memory overhead.

## AI Agent Guidance

### Quick Start for Related Tasks

1. **Read first**: `src/pflow/core/shell_integration.py` - the FIFO detection logic
2. **Understand**: The distinction between FIFO (pipes) and sockets (Claude Code)
3. **Test with**: Real subprocess tests using `shell=True` for actual pipe behavior

### Common Pitfalls

1. **CliRunner doesn't simulate real pipes** - Use subprocess tests for pipe behavior
2. **Don't forget SIGPIPE** - It's handled in main.py, must stay `SIG_IGN`
3. **Stdin routing is BEFORE validation** - Position matters in `_validate_and_prepare_workflow_params()`

### Test-First Recommendations

When modifying stdin handling:
1. Run `test_stdin_no_hang_integration` first - ensures Claude Code doesn't hang
2. Run `test_workflow_chaining_producer_to_consumer` - ensures pipes work
3. Run full `tests/test_cli/test_dual_mode_stdin.py` suite

### Key Files to Understand

```
src/pflow/core/shell_integration.py:68-112  # stdin_has_data() with FIFO detection
src/pflow/cli/main.py:3073-3190              # Stdin routing helpers
src/pflow/cli/main.py:3257-3262              # Call site in _handle_named_workflow
```

---

*Generated from implementation context of Task 115*
