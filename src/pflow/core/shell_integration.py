"""Shell integration utilities for pflow.

This module provides core functions for detecting, reading, and categorizing
stdin input, enabling dual-mode stdin handling in pflow workflows.

The module supports:
- Detection of piped stdin vs interactive terminal
- FIFO-based pipe detection (only reads from real shell pipes)
- Reading text data from stdin with UTF-8 encoding
- Binary data detection and handling
- Large file streaming to temporary storage
- Determining if stdin contains workflow JSON or data

Key Design Decision:
    stdin_has_data() returns True ONLY for FIFO pipes (real shell pipes).
    This avoids hanging in environments like Claude Code where stdin is a
    character device that never sends EOF. See stdin_has_data() docstring
    for detailed rationale.
"""

import contextlib
import io
import os
import stat
import sys
import tempfile
from dataclasses import dataclass

# Default memory limit: 10MB
DEFAULT_MEMORY_LIMIT = 10 * 1024 * 1024
# Binary detection sample size: 8KB
BINARY_SAMPLE_SIZE = 8 * 1024
# Win32 GetFileType return value for pipes (winbase.h: 1=DISK, 2=CHAR, 3=PIPE)
_FILE_TYPE_PIPE = 3


@dataclass
class StdinData:
    """Container for different types of stdin data.

    Only one of the fields will be populated based on the data type:
    - text_data: For text content under memory limit
    - binary_data: For binary content under memory limit
    - temp_path: For any content over memory limit
    """

    text_data: str | None = None
    binary_data: bytes | None = None
    temp_path: str | None = None

    @property
    def is_text(self) -> bool:
        """Check if this contains text data."""
        return self.text_data is not None

    @property
    def is_binary(self) -> bool:
        """Check if this contains binary data."""
        return self.binary_data is not None

    @property
    def is_temp_file(self) -> bool:
        """Check if this contains a temp file path."""
        return self.temp_path is not None


def detect_stdin() -> bool:
    """Check if stdin is piped (not a TTY).

    Returns:
        True if stdin is piped, False if interactive terminal
    """
    return not sys.stdin.isatty()


def stdin_has_data() -> bool:
    """Check if stdin is a real pipe that should be read.

    Returns True ONLY for real shell pipes (from piping like `echo x | pflow`):
    FIFO pipes on Unix, anonymous/named pipes on Windows.
    Returns False for everything else: terminals, sockets, character devices,
    StringIO, file redirects on Windows.

    Design Decision - Why FIFO-only, not select():
    -----------------------------------------------
    We previously used `select.select([sys.stdin], [], [], 0)` to check for data.
    This was UNRELIABLE because:

    1. In Claude Code, stdin is a character device (S_ISCHR=True)
    2. select() LIES on character devices - returns "ready" even with no data
    3. Calling stdin.read() then hangs forever waiting for EOF that never comes

    The Unix standard approach (used by cat, grep, jq) is simpler:
    - Check isatty() - if terminal, no stdin
    - Otherwise just read() - blocks until data or EOF

    But we can't "just read" because Claude Code's stdin never sends EOF.
    Solution: Only read from FIFO pipes. Real shell pipes are FIFOs.
    Character devices, sockets, StringIO are not - we skip them.

    Windows (Task 116): pipes are not POSIX FIFOs (`S_ISFIFO` is always False
    there), so win32 asks the kernel directly: `GetFileType(handle) ==
    FILE_TYPE_PIPE`. This mirrors the Unix semantics exactly — pipes are
    detected, consoles and file redirects (`pflow < file`) are not.

    Environment Behavior:
    --------------------
    | Environment              | stdin type      | Detected via     | Result        |
    |--------------------------|-----------------|------------------|---------------|
    | `echo x \\| pflow` (Unix) | FIFO pipe       | S_ISFIFO=True    | Read (block)  |
    | `echo -n "" \\| pflow`    | FIFO pipe       | S_ISFIFO=True    | Read (empty)  |
    | `echo x \\| pflow` (win32)| anonymous pipe  | FILE_TYPE_PIPE   | Read (block)  |
    | `pflow < file` (win32)   | disk file       | FILE_TYPE_DISK   | Skip          |
    | Windows console          | char device     | FILE_TYPE_CHAR   | Skip (early)  |
    | Claude Code              | char device     | S_ISFIFO=False   | Skip (no hang)|
    | CliRunner (tests)        | StringIO        | no fd            | Skip (no fd)  |
    | Interactive terminal     | TTY             | isatty           | Skip (early)  |

    For detailed investigation history, see:
    .taskmaster/tasks/task_115/implementation/progress-log.md (Session 6)

    Returns:
        True if stdin is a real pipe, False otherwise
    """
    # Check if stdin is closed first (before any other operations)
    try:
        if sys.stdin.closed:
            return False
    except (AttributeError, OSError):
        return False

    # Check if TTY (interactive terminal)
    try:
        if sys.stdin.isatty():
            return False
    except (AttributeError, OSError, ValueError):
        return False

    # Check if /dev/null
    try:
        if hasattr(sys.stdin, "name") and sys.stdin.name == os.devnull:
            return False
    except (AttributeError, OSError):
        pass

    # Check if stdin has a real file descriptor
    # StringIO (CliRunner) doesn't have one
    try:
        fd = sys.stdin.fileno()
    except (AttributeError, OSError, ValueError):
        return False

    # Windows pipes are not POSIX FIFOs - ask the Win32 API instead
    if sys.platform == "win32":
        return _stdin_is_pipe_windows(fd)

    # Check if stdin is a FIFO (real pipe)
    # Only FIFOs should be read - this is Unix standard behavior
    try:
        mode = os.fstat(fd).st_mode
        return stat.S_ISFIFO(mode)
    except OSError:
        return False


def _stdin_is_pipe_windows(fd: int) -> bool:
    """Check whether a Windows file descriptor is a pipe.

    Win32 equivalent of the `S_ISFIFO` check: `GetFileType` on the underlying
    OS handle returns FILE_TYPE_PIPE (3) for anonymous and named pipes,
    FILE_TYPE_CHAR for consoles, FILE_TYPE_DISK for file redirects — so shell
    pipes are detected and everything else is skipped, mirroring Unix.

    Deliberately ctypes + msvcrt (stdlib only, no pywin32 dependency) and no
    PeekNamedPipe — an open-but-empty pipe blocks on read exactly like an
    open-but-empty FIFO does on Unix (Task 116 decision).

    The imports are lazy on purpose: `msvcrt` does not exist on non-Windows
    platforms and `ctypes.windll` only exists on Windows — importing either
    at module top would break every non-Windows run. Linux unit tests inject
    fakes via `sys.modules["msvcrt"]` and `ctypes.windll`.

    Args:
        fd: File descriptor to check (honors the fd the caller validated,
            rather than re-deriving stdin via GetStdHandle)

    Returns:
        True if the fd is a pipe, False for anything else (including any
        failure along the way — matching this module's defensive style)
    """
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(fd)  # type: ignore[attr-defined, unused-ignore]
        # windll/get_osfhandle are typed win32-only in typeshed; ubuntu mypy needs
        # the attr-defined suppression, the Windows mypy run needs unused-ignore.
        file_type = ctypes.windll.kernel32.GetFileType(handle)  # type: ignore[attr-defined, unused-ignore]
        return int(file_type) == _FILE_TYPE_PIPE
    except Exception:
        return False


def read_stdin() -> str | None:
    """Read all stdin content if available.

    Only reads if stdin is a real pipe (see stdin_has_data). On Windows the
    byte stream is re-read as UTF-8 with universal newlines — identical text
    semantics to the Unix read, with only the encoding pinned (the default
    win32 text layer would decode cp1252 and silently mojibake UTF-8 input).
    Empty string is valid content and will be returned (not treated as None).

    Returns:
        Content string if stdin is a pipe (including empty string),
        None if no pipe, or if the content is not valid UTF-8 (binary input
        is left to read_stdin_enhanced)
    """
    # Only read if stdin is a real pipe
    if not stdin_has_data():
        return None

    try:
        if sys.platform == "win32":
            # Windows text-mode stdin decodes with the locale code page
            # (cp1252), which almost never raises — UTF-8 input like "café"
            # silently becomes mojibake. Re-wrap the byte stream with UTF-8
            # pinned. A wrapper (not bare buffer.read().decode()) keeps the
            # Unix text-read semantics: universal newlines (\r\n -> \n, which
            # every native Windows producer emits) and incremental decoding
            # (a bare full read would consume the whole stream before failing
            # on binary input, starving the read_stdin_enhanced fallback).
            # detach() afterwards so closing the wrapper can't close stdin.
            buffer = getattr(sys.stdin, "buffer", None)
            if buffer is None:
                # In-process test harnesses and embedded callers can replace
                # stdin with StringIO. Real win32 pipes have .buffer; this
                # fallback keeps the function defensive once stdin_has_data()
                # has already been mocked or prevalidated by the caller.
                content = sys.stdin.read()
            else:
                wrapper = io.TextIOWrapper(buffer, encoding="utf-8", newline=None)
                try:
                    content = wrapper.read()
                finally:
                    wrapper.detach()
        else:
            content = sys.stdin.read()

        # Strip trailing newline only (not all whitespace)
        # This preserves intentional whitespace in data
        # Note: empty string is valid content per Unix standard
        if content and content.endswith("\n"):
            content = content[:-1]

        return content
    except UnicodeDecodeError:
        # Binary data detected - return None so enhanced reading can handle it
        return None


def read_stdin_enhanced() -> StdinData | None:
    """Read stdin with enhanced binary and size handling.

    This is the new enhanced version that handles:
    - Binary data detection
    - Large file streaming to temp files
    - Proper memory management

    Returns:
        StdinData object with appropriate field populated,
        or None if no stdin available
    """
    # Check if stdin actually has data available to avoid hanging
    if not stdin_has_data():
        return None

    try:
        stdin_data = read_stdin_with_limit()

        # Handle empty stdin case
        if stdin_data.is_text and stdin_data.text_data == "":
            return None

        return stdin_data
    except Exception:
        # Log error and return None
        # In production, would use proper logging
        return None


def detect_binary_content(sample: bytes) -> bool:
    """Detect if content is likely binary by checking for null bytes.

    Args:
        sample: First few KB of content to check

    Returns:
        True if binary content detected, False otherwise
    """
    # Check for null bytes - common indicator of binary data
    return b"\x00" in sample


def _read_within_memory_limit(sample: bytes, max_size: int) -> tuple[list[bytes], int, bytes | None]:
    """Read from stdin up to memory limit.

    Args:
        sample: Initial sample already read
        max_size: Maximum bytes to keep in memory

    Returns:
        Tuple of (chunks, total_size, peek_byte)
    """
    chunks = [sample]
    total_size = len(sample)

    # Read up to the memory limit
    while total_size < max_size:
        chunk_size = min(max_size - total_size, 8192)  # Read in 8KB chunks
        chunk = sys.stdin.buffer.read(chunk_size)
        if not chunk:
            break
        chunks.append(chunk)
        total_size += len(chunk)

    # Check if there's more data beyond the limit
    peek = sys.stdin.buffer.read(1)
    return chunks, total_size, peek


def _stream_to_temp_file(chunks: list[bytes], peek: bytes) -> str:
    """Stream large data to temporary file.

    Args:
        chunks: Initial chunks already read
        peek: First byte beyond memory limit

    Returns:
        Path to temporary file

    Raises:
        IOError: If temp file creation fails
    """
    temp_file = tempfile.NamedTemporaryFile(mode="wb", delete=False, prefix="pflow_stdin_")  # noqa: SIM115
    try:
        # Write what we've read so far
        for c in chunks:
            temp_file.write(c)
        temp_file.write(peek)

        # Stream the rest
        while True:
            chunk = sys.stdin.buffer.read(8192)  # 8KB chunks
            if not chunk:
                break
            temp_file.write(chunk)

        temp_file.close()
        return temp_file.name
    except Exception:
        # Clean up on error
        temp_file.close()
        with contextlib.suppress(OSError):
            os.unlink(temp_file.name)
        raise


def read_stdin_with_limit(max_size: int | None = None) -> StdinData:
    """Read stdin with size limit and binary detection.

    Args:
        max_size: Maximum bytes to keep in memory (default from env or 10MB)

    Returns:
        StdinData object with appropriate field populated

    Raises:
        IOError: If temp file creation fails
    """
    if max_size is None:
        # Check environment variable for memory limit
        env_limit = os.environ.get("PFLOW_STDIN_MEMORY_LIMIT")
        if env_limit:
            try:
                max_size = int(env_limit)
            except ValueError:
                max_size = DEFAULT_MEMORY_LIMIT
        else:
            max_size = DEFAULT_MEMORY_LIMIT

    # Read initial sample for binary detection
    sample = sys.stdin.buffer.read(BINARY_SAMPLE_SIZE)
    if not sample:
        # Empty stdin
        return StdinData(text_data="")

    is_binary = detect_binary_content(sample)

    # Check if we need to stream to temp file
    if len(sample) == BINARY_SAMPLE_SIZE:
        # More data might be available, check total size
        chunks, _total_size, peek = _read_within_memory_limit(sample, max_size)

        if peek:
            # Need to stream to temp file
            temp_path = _stream_to_temp_file(chunks, peek)
            return StdinData(temp_path=temp_path)

        # All data fits in memory
        all_data = b"".join(chunks)
    else:
        # Sample was the entire input
        all_data = sample

    # Return appropriate type based on binary detection
    if is_binary:
        return StdinData(binary_data=all_data)
    else:
        # Decode as text
        try:
            text = all_data.decode("utf-8")
            # Strip trailing newline for text data
            if text.endswith("\n"):
                text = text[:-1]
            return StdinData(text_data=text)
        except UnicodeDecodeError:
            # Fallback to binary if decode fails
            return StdinData(binary_data=all_data)
