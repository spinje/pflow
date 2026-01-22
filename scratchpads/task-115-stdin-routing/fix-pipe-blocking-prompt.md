# Implementation Prompt: Fix Stdin Pipe Blocking for Workflow Chaining

## Problem Summary

Workflow chaining (`pflow -p workflow1.json | pflow workflow2.json`) doesn't work because `stdin_has_data()` uses a non-blocking `select()` check that returns false before the upstream process has produced output.

**Current behavior:**
```bash
# This works (intermediate file)
pflow -p workflow1.json > /tmp/out.json && cat /tmp/out.json | pflow workflow2.json

# This FAILS (direct pipe)
pflow -p workflow1.json | pflow workflow2.json
# Error: "Workflow requires input 'data'"
```

**Root cause:** In `src/pflow/core/shell_integration.py`, the `stdin_has_data()` function uses:
```python
rlist, _, _ = select.select([sys.stdin], [], [], 0)  # timeout=0 = instant
return bool(rlist)
```

When shell pipes two processes, they start simultaneously. Process B checks for stdin before Process A writes anything.

---

## Context Files to Read First

**Read these files to understand the full context:**

1. **Task specification:**
   ```
   .taskmaster/tasks/task_115/starting-context/task-115-spec.md
   ```

2. **Progress log (what's been done):**
   ```
   .taskmaster/tasks/task_115/implementation/progress-log.md
   ```

3. **Braindump (tacit knowledge):**
   ```
   .taskmaster/tasks/task_115/starting-context/braindump-research-complete.md
   ```

4. **Manual testing plan and results:**
   ```
   scratchpads/task-115-stdin-routing/manual-testing-plan.md
   ```

5. **Current implementation (staged changes):**
   ```bash
   git diff --staged
   ```

---

## The Fix: Detect FIFO (Pipe) vs Other Non-TTY

### Why the current code exists

The `select()` with timeout=0 was added to prevent hanging when stdin is non-TTY but has no data (e.g., in Claude Code or IDE environments where stdin/stdout are non-TTY sockets). Without it, `sys.stdin.read()` would block forever.

### The solution

Distinguish between:
- **Actual pipe (FIFO)** → Block until data/EOF (like `cat`, `grep`, `jq` do)
- **Other non-TTY** (socket, /dev/null, etc.) → Use non-blocking check

### Implementation approach

Modify `stdin_has_data()` in `src/pflow/core/shell_integration.py`:

```python
import stat

def stdin_has_data() -> bool:
    """Check if stdin actually has data available.

    For FIFO pipes (from shell piping), we block until data is available.
    For other non-TTY cases (sockets, /dev/null), we use non-blocking check
    to avoid hanging in environments like Claude Code.
    """
    if sys.stdin.isatty():
        return False

    # Check if stdin is closed or /dev/null
    try:
        if sys.stdin.closed:
            return False
        if hasattr(sys.stdin, "name") and sys.stdin.name == os.devnull:
            return False
    except (AttributeError, OSError):
        pass

    # Check if stdin is a FIFO (pipe from another process)
    try:
        mode = os.fstat(sys.stdin.fileno()).st_mode
        if stat.S_ISFIFO(mode):
            # Real pipe - return True, let caller block on read
            # This is correct Unix behavior (cat, grep, jq all do this)
            return True
    except (OSError, AttributeError):
        pass

    # For other non-TTY cases (sockets, etc.), use non-blocking check
    # This prevents hanging in environments like Claude Code
    try:
        rlist, _, _ = select.select([sys.stdin], [], [], 0)
        return bool(rlist)
    except (OSError, ValueError):
        return not sys.stdin.isatty()
```

---

## Files to Modify

| File | Change |
|------|--------|
| `src/pflow/core/shell_integration.py` | Modify `stdin_has_data()` to detect FIFO |

---

## Test Cases

### Manual tests (run these to verify)

```bash
# Create test workflows
mkdir -p /tmp/pipe-test

# Producer workflow
cat > /tmp/pipe-test/producer.json << 'EOF'
{
  "ir_version": "0.1.0",
  "inputs": {"count": {"type": "number", "required": true}},
  "nodes": [{"id": "gen", "type": "shell", "params": {"command": "echo '[1,2,3,4,5]' | jq '.[0:${count}]'"}}],
  "edges": [],
  "start_node": "gen",
  "outputs": {"result": {"source": "${gen.stdout}"}}
}
EOF

# Consumer workflow
cat > /tmp/pipe-test/consumer.json << 'EOF'
{
  "ir_version": "0.1.0",
  "inputs": {"data": {"type": "string", "required": true, "stdin": true}},
  "nodes": [{"id": "count", "type": "shell", "params": {"stdin": "${data}", "command": "jq 'length'"}}],
  "edges": [],
  "start_node": "count",
  "outputs": {"count": {"source": "${count.stdout}"}}
}
EOF

# Test 1: Direct pipe (MUST WORK after fix)
uv run pflow -p /tmp/pipe-test/producer.json count=3 | uv run pflow -p /tmp/pipe-test/consumer.json
# Expected output: 3

# Test 2: Producer alone
uv run pflow -p /tmp/pipe-test/producer.json count=3
# Expected: [1, 2, 3]

# Test 3: Consumer with echo
echo '[1,2,3]' | uv run pflow -p /tmp/pipe-test/consumer.json
# Expected: 3

# Test 4: No stdin (terminal) - should NOT hang
uv run pflow /tmp/pipe-test/consumer.json
# Expected: Error about missing input 'data' (not hanging)

# Test 5: Three-stage pipeline
uv run pflow -p /tmp/pipe-test/producer.json count=4 | uv run pflow -p /tmp/pipe-test/consumer.json | cat
# Expected: 4
```

### Existing tests to verify still pass

```bash
# All existing tests should pass
make test

# Specifically stdin-related tests
uv run pytest tests/test_shell_integration.py -v
uv run pytest tests/test_cli/test_dual_mode_stdin.py -v
```

---

## Verification Checklist

- [ ] `make test` passes (all ~4012 tests)
- [ ] `make check` passes (linting, types)
- [ ] Manual test 1: Direct pipe works
- [ ] Manual test 2: Producer alone works
- [ ] Manual test 3: Consumer with echo works
- [ ] Manual test 4: No stdin doesn't hang
- [ ] Manual test 5: Three-stage pipeline works

---

## Important Considerations

1. **Platform differences:** `os.fstat()` and `stat.S_ISFIFO()` should work on macOS and Linux. Windows might need different handling (but pflow is Unix-first).

2. **Don't break existing behavior:** The non-blocking check for non-FIFO cases must remain to prevent hanging in Claude Code and similar environments.

3. **Test edge cases:**
   - `/dev/null` as stdin
   - Empty pipe (`echo -n "" | pflow`)
   - Very slow producer (should still work, just waits)

4. **Update progress log:** After implementing, add a new session entry to:
   ```
   .taskmaster/tasks/task_115/implementation/progress-log.md
   ```

---

## Why This Matters

Unix-first piping is a core pflow feature. The task-115.md spec explicitly mentions:
```
cat data.json | pflow transform.json | pflow analyze.json > report.md
```

Without this fix, workflow chaining doesn't work, undermining pflow's Unix-first positioning.

---

## Summary

1. Read context files listed above
2. Modify `stdin_has_data()` to detect FIFO pipes
3. Run manual tests to verify pipe chaining works
4. Run `make test` and `make check`
5. Update progress log
