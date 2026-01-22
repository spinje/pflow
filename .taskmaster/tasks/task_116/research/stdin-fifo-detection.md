# Research: Windows Stdin FIFO Detection

**Date:** 2026-01-22
**Updated:** 2026-01-22 (simplified to FIFO-only)
**Context:** Task 115 - Automatic Stdin Routing for Unix-First Piping
**Researcher:** AI Agent

## Problem Statement

During Task 115 implementation, we added FIFO detection to `stdin_has_data()` to enable workflow chaining:

```bash
pflow -p workflow1.json | pflow workflow2.json
```

This works on Unix by detecting if stdin is a FIFO pipe using `stat.S_ISFIFO()`. On Windows, this approach doesn't work.

## Unix Implementation (Current - Simplified)

After investigation, we simplified to **FIFO-only detection** - no `select()` needed:

```python
# src/pflow/core/shell_integration.py

def stdin_has_data() -> bool:
    """Check if stdin is a real FIFO pipe that should be read."""
    # Check closed first
    try:
        if sys.stdin.closed:
            return False
    except:
        return False

    # Check TTY
    if sys.stdin.isatty():
        return False

    # Check /dev/null
    if hasattr(sys.stdin, "name") and sys.stdin.name == os.devnull:
        return False

    # Check for real file descriptor (filters out StringIO)
    try:
        fd = sys.stdin.fileno()
    except:
        return False  # No fileno = not real stdin (e.g., CliRunner)

    # Only return True for FIFO pipes
    try:
        mode = os.fstat(fd).st_mode
        return stat.S_ISFIFO(mode)
    except:
        return False
```

**Key simplification:** No `select()` fallback. Only FIFOs return True.

## Windows Behavior Analysis

### 1. stat.S_ISFIFO() Always Returns False

Windows doesn't have Unix FIFO pipes. The `stat` module constants exist, but `S_ISFIFO(mode)` always returns `False` for any Windows file.

```python
>>> import stat
>>> stat.S_ISFIFO(0)
False
>>> # Even for pipes, mode won't have S_IFIFO bit set on Windows
```

### 2. Current Simplified Behavior

With the new FIFO-only approach, Windows behavior is straightforward:

| Scenario | Unix | Windows |
|----------|------|---------|
| TTY (interactive) | False | False |
| FIFO pipe | True (S_ISFIFO) | **False** (no FIFO on Windows) |
| File redirect | False | False |
| /dev/null | False (explicit check) | False (NUL device) |

**Key change:** No fallback. Windows simply returns False for all piped input because `S_ISFIFO()` is always False.

### 3. Impact on Windows Users

**Stdin routing will NOT work on Windows** with the current implementation:

```powershell
# This will NOT work - stdin not detected
echo "data" | pflow workflow.json
```

The workflow would fail with "Workflow requires input 'data'" because stdin is not detected.

**This is acceptable because:**
- pflow is explicitly Unix-first
- Task 116 exists to track Windows compatibility
- Users can use file input as workaround: `pflow workflow.json data="$(cat input.txt)"`

## Win32 API Solution Research

### Option A: PeekNamedPipe

The Win32 API provides `PeekNamedPipe` to check if data is available in a pipe without consuming it:

```python
import ctypes
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32

# Constants
STD_INPUT_HANDLE = -10
FILE_TYPE_PIPE = 3

def stdin_has_data_windows() -> bool:
    """Windows-specific stdin data check using Win32 API."""
    # Get stdin handle
    handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)

    if handle == -1:  # INVALID_HANDLE_VALUE
        return False

    # Check if it's a pipe
    file_type = kernel32.GetFileType(handle)
    if file_type != FILE_TYPE_PIPE:
        # Not a pipe - could be console or file
        # For console, check if it's interactive
        mode = wintypes.DWORD()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False  # Interactive console
        # For files, assume data is available
        return True

    # It's a pipe - check if data is available
    available = wintypes.DWORD()
    result = kernel32.PeekNamedPipe(
        handle,
        None,  # lpBuffer - we don't want to read
        0,     # nBufferSize
        None,  # lpBytesRead
        ctypes.byref(available),  # lpTotalBytesAvail
        None   # lpBytesLeftThisMessage
    )

    if not result:
        # PeekNamedPipe failed - assume data available
        return True

    return available.value > 0
```

**Pros:**
- Accurate detection of pipe data availability
- Works for both named and anonymous pipes

**Cons:**
- Requires ctypes
- Windows-specific code path
- Needs testing on different Windows versions
- `PeekNamedPipe` might not work for all pipe types

### Option B: GetFileType + Fallback

Simpler approach - just detect if stdin is a pipe and assume data:

```python
def stdin_has_data_windows_simple() -> bool:
    """Simplified Windows check - detect pipe, assume data."""
    handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)

    if handle == -1:
        return False

    file_type = kernel32.GetFileType(handle)

    if file_type == 1:  # FILE_TYPE_DISK (file redirection)
        return True  # File always has data
    elif file_type == 2:  # FILE_TYPE_CHAR (console)
        return False  # Interactive
    elif file_type == 3:  # FILE_TYPE_PIPE
        return True  # Pipe - assume data (matches current fallback)
    else:
        return False  # Unknown
```

**Pros:**
- Simpler than PeekNamedPipe
- More explicit than current fallback

**Cons:**
- Still can't detect "pipe with no data" edge case
- Requires ctypes

### Option C: msvcrt Module

Python's `msvcrt` module provides some Windows-specific functionality:

```python
import msvcrt

def stdin_has_data_msvcrt() -> bool:
    """Check using msvcrt - ONLY works for console input."""
    if msvcrt.kbhit():
        return True
    return False
```

**Limitation:** `kbhit()` only works for console keyboard input, NOT for pipes. This won't help our use case.

## Recommendation

### For Now (Unix-First)

Keep current FIFO-only implementation. Windows stdin routing is not supported:
- Unix pipes → True → works correctly
- Windows pipes → False → stdin not routed (explicit limitation)
- Console stdin → False → works correctly on both platforms

This is the cleanest approach - explicit platform behavior rather than unreliable heuristics.

### If Windows Support Becomes Important

Implement platform-specific detection using Win32 API (Option A or B below):

```python
def stdin_has_data() -> bool:
    # Early checks (both platforms)
    if sys.stdin.closed:
        return False
    if sys.stdin.isatty():
        return False

    # Platform-specific handling
    if sys.platform == "win32":
        return _stdin_has_data_windows()

    # Unix: FIFO-only detection
    try:
        fd = sys.stdin.fileno()
    except:
        return False

    try:
        mode = os.fstat(fd).st_mode
        return stat.S_ISFIFO(mode)
    except:
        return False
```

## Testing Requirements

If implementing Windows support:

1. **Unit Tests:**
   - Mock Win32 API calls
   - Test each GetFileType return value

2. **Integration Tests (Windows CI):**
   - PowerShell: `echo "data" | pflow workflow.json`
   - CMD: `echo data | pflow workflow.json`
   - Workflow chaining: `pflow A | pflow B`

3. **Edge Cases:**
   - Empty pipe (rare but possible)
   - Named pipe vs anonymous pipe
   - File redirection: `pflow workflow.json < input.txt`

## References

- [Win32 PeekNamedPipe](https://docs.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-peeknamedpipe)
- [Win32 GetFileType](https://docs.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfiletype)
- [Python ctypes](https://docs.python.org/3/library/ctypes.html)
- [Python select on Windows](https://docs.python.org/3/library/select.html#select.select)
