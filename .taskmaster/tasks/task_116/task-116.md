# Task 116: Windows Compatibility

## Status
not started

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

### 6. Default Encoding for Report Files (UTF-8 vs cp1252)

**Problem:** Report generation calls `Path.write_text()` / `Path.read_text()` without an explicit `encoding=` argument. Python 3.10–3.14 defer to `locale.getencoding()`, which is `cp1252` on a typical Windows install. The rendered `summary.md` contains non-ASCII characters (em-dash `—`, status glyphs in some surfaces, model names that may include UTF-8) that are not representable in cp1252.

**Surfaced by:** Gemini code review on PR #438 (https://github.com/spinje/pflow/pull/438#pullrequestreview-4379598499). The bot flagged the read sites; on inspection the WRITE sites have the same problem and would fail FIRST, so fixing reads alone is incomplete.

**Failure mode on Windows:**
- Write side fails with `UnicodeEncodeError` while building the report directory — the directory never gets created, so reads never run.
- Same applies to the trace JSON path if a workflow name contains non-ASCII.

**Write sites (need `encoding="utf-8"`):**
- `src/pflow/core/trace_report.py` — `_render_report_snapshot` (`summary.md` + `.pflow-report.json` marker)
- `src/pflow/core/trace_report.py` — `_write_node_files` (per-node `.md` files, container `summary.md` files, batch-item files)
- `src/pflow/runtime/workflow_trace.py` — `save_to_file` (trace JSON; verify `json.dump` write mode)

**Read sites (need `encoding="utf-8"`):**
- `src/pflow/cli/commands/report.py:64` — `(report_dir / "summary.md").read_text()` for stderr echo
- `src/pflow/cli/commands/run.py:164` — same call site on the `--report` path

**Recommended fix (when this task lands):** One sweep across all writers and readers of report-shaped files, all keyed on `encoding="utf-8"`. Avoid the half-fix (reads only) — it adds noise without changing the failure mode.

**Impact today:** Zero on macOS/Linux (locale is UTF-8). Will block Windows compatibility until addressed.

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
