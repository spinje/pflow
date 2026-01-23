# Task 116: Windows Compatibility

## Status: Research, Deferred

## Priority: Low (pflow is Unix-first)

## Summary

Track Windows compatibility issues and potential improvements. pflow is designed as a Unix-first CLI tool, but basic Windows support may be valuable for broader adoption.

---

## Known Windows Issues

### 1. Stdin FIFO Detection (Task 115 - Updated)

**Problem:** `stat.S_ISFIFO()` always returns `False` on Windows because Windows doesn't have Unix FIFO pipes.

**Current Behavior (Simplified):** After Task 115 simplification, we use FIFO-only detection:
- Only `stat.S_ISFIFO()` is checked
- No fallbacks, no `select()` complexity
- On Windows: always returns `False` for piped input

**Impact:** **Stdin routing does NOT work on Windows.** Piping data will not be detected:
```powershell
# This does NOT work on Windows
echo "data" | pflow workflow.json
# Error: Workflow requires input 'data'
```

**Workaround:** Use file input or CLI parameters instead of piping.

**Potential Fix:** Add platform-specific detection using Win32 API:

```python
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
    file_type = kernel32.GetFileType(handle)
    if file_type == 3:  # FILE_TYPE_PIPE
        # Option A: Assume pipe has data (simple)
        return True
        # Option B: Use PeekNamedPipe (accurate)
        available = wintypes.DWORD()
        kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None)
        return available.value > 0
```

**Complexity:** Medium - requires ctypes, Windows-specific code path

---

### 2. select() Not Used (Removed)

**Previous Problem:** Python's `select.select()` on Windows only works with sockets.

**Current Status:** `select()` was **removed** from stdin handling in Task 115 simplification. This issue no longer applies.

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
| 2026-01-22 | Simplified to FIFO-only | Removed unreliable `select()` fallback; Windows stdin not supported |

## Related

- Task 115: Automatic Stdin Routing for Unix-First Piping
- Task 115 Session 6: Simplified FIFO detection (removed select() complexity)
