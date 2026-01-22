# Research: Windows Stdin FIFO Detection

**Date:** 2026-01-22
**Context:** Task 115 - Automatic Stdin Routing for Unix-First Piping
**Researcher:** AI Agent

## Problem Statement

During Task 115 implementation, we added FIFO detection to `stdin_has_data()` to enable workflow chaining:

```bash
pflow -p workflow1.json | pflow workflow2.json
```

This works on Unix by detecting if stdin is a FIFO pipe using `stat.S_ISFIFO()`. On Windows, this approach doesn't work.

## Unix Implementation (Working)

```python
# src/pflow/core/shell_integration.py

def stdin_has_data() -> bool:
    if sys.stdin.isatty():
        return False

    # Check for /dev/null
    if sys.stdin.closed:
        return False
    if hasattr(sys.stdin, "name") and sys.stdin.name == os.devnull:
        return False

    # FIFO detection - THIS IS THE KEY PART
    try:
        mode = os.fstat(sys.stdin.fileno()).st_mode
        if stat.S_ISFIFO(mode):
            return True  # Real pipe - let caller block on read
    except (OSError, AttributeError):
        pass

    # Non-blocking check for sockets (Claude Code)
    try:
        rlist, _, _ = select.select([sys.stdin], [], [], 0)
        return bool(rlist)
    except (OSError, ValueError):
        return not sys.stdin.isatty()  # Fallback
```

## Windows Behavior Analysis

### 1. stat.S_ISFIFO() Always Returns False

Windows doesn't have Unix FIFO pipes. The `stat` module constants exist, but `S_ISFIFO(mode)` always returns `False` for any Windows file.

```python
>>> import stat
>>> stat.S_ISFIFO(0)
False
>>> # Even for pipes, mode won't have S_IFIFO bit set on Windows
```

### 2. select() Fails on Non-Sockets

Python's `select.select()` on Windows only works with **sockets**:

```python
>>> import select
>>> select.select([sys.stdin], [], [], 0)
OSError: [WinError 10038] An operation was attempted on something that is not a socket
```

This is caught by our exception handler and falls back to `return not sys.stdin.isatty()`.

### 3. Current Fallback Behavior

| Scenario | Unix | Windows |
|----------|------|---------|
| TTY (interactive) | False | False |
| FIFO pipe | True (S_ISFIFO) | True (fallback) |
| Socket (Claude Code) | select() works | N/A on Windows |
| /dev/null | False (explicit check) | False (explicit check) |
| Non-TTY, no data | False (select) | True (fallback) ⚠️ |

The last case is the only potential issue - on Windows with non-TTY stdin but no data, we return True and could hang. This is rare.

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

Keep current implementation. The fallback behavior is correct for most Windows pipe scenarios:
- Piped stdin → True → works correctly
- Console stdin → False → works correctly
- Edge cases are rare

### If Windows Support Becomes Important

Implement Option A (PeekNamedPipe) with proper error handling:

```python
def stdin_has_data() -> bool:
    if sys.stdin.isatty():
        return False

    # Platform-specific handling
    if sys.platform == "win32":
        return _stdin_has_data_windows()

    # Unix: FIFO detection
    try:
        mode = os.fstat(sys.stdin.fileno()).st_mode
        if stat.S_ISFIFO(mode):
            return True
    except (OSError, AttributeError):
        pass

    # Unix: select() for sockets
    try:
        rlist, _, _ = select.select([sys.stdin], [], [], 0)
        return bool(rlist)
    except (OSError, ValueError):
        return not sys.stdin.isatty()
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
