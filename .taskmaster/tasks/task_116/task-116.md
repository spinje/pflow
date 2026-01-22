# Task 116: Windows Compatibility

## Status: Research, Deferred

## Priority: Low (pflow is Unix-first)

## Summary

Track Windows compatibility issues and potential improvements. pflow is designed as a Unix-first CLI tool, but basic Windows support may be valuable for broader adoption.

---

## Known Windows Issues

### 1. Stdin FIFO Detection (Task 115 Research)

**Problem:** `stat.S_ISFIFO()` always returns `False` on Windows because Windows doesn't have Unix FIFO pipes.

**Current Behavior:** Falls back to `return not sys.stdin.isatty()` which assumes piped stdin has data.

**Impact:** Workflow chaining (`pflow A | pflow B`) works, but rare edge cases (non-TTY with no data) could hang.

**Potential Fix:** Use Win32 API `PeekNamedPipe()` via ctypes:

```python
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
    if kernel32.GetFileType(handle) == 3:  # FILE_TYPE_PIPE
        available = wintypes.DWORD()
        kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None)
        return available.value > 0
```

**Complexity:** Medium - requires ctypes, Windows-specific code path

---

### 2. select() on Stdin

**Problem:** Python's `select.select()` on Windows only works with sockets, not file handles.

**Current Behavior:** Caught by exception handler, falls back to TTY check.

**Impact:** Non-blocking stdin checks don't work on Windows.

---

### 3. SIGPIPE Signal

**Problem:** Windows doesn't have SIGPIPE signal.

**Current Behavior:** Already handled with `hasattr(signal, "SIGPIPE")` check.

**Impact:** None - already works.

---

### 4. Path Separators

**Problem:** Windows uses `\` instead of `/` for paths.

**Current Behavior:** Most code uses `pathlib.Path` which handles this.

**Impact:** Low - likely already works, but needs verification.

---

### 5. Shell Node Commands

**Problem:** Shell commands may differ between Unix and Windows (e.g., `cat` vs `type`, `grep` vs `findstr`).

**Current Behavior:** Workflows with Unix commands will fail on Windows.

**Impact:** User responsibility - workflows are platform-specific.

---

## Testing Strategy (When Implementing)

1. **GitHub Actions:** Add `windows-latest` to CI matrix
2. **PowerShell pipes:** Test `pflow A | pflow B` in PowerShell
3. **CMD pipes:** Test in Command Prompt
4. **Path handling:** Test with Windows paths
5. **Shell node:** Document platform-specific commands

## Files Likely Affected

- `src/pflow/core/shell_integration.py` - stdin handling
- `src/pflow/nodes/shell/shell.py` - shell execution
- `src/pflow/cli/main.py` - signal handling (already handled)
- CI configuration - add Windows runner

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-22 | Create placeholder task | Document findings from Task 115 |
| 2026-01-22 | Defer implementation | Unix-first tool, current fallbacks are acceptable |

## Related

- Task 115: Automatic Stdin Routing for Unix-First Piping
- Bugfix BF-20250112-stdin-hang-nontty-grep: Original stdin hang fix
