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
import json
import os
import stat
import sys
import tempfile
from dataclasses import dataclass

# Default memory limit: 10MB
DEFAULT_MEMORY_LIMIT = 10 * 1024 * 1024
# Binary detection sample size: 8KB
BINARY_SAMPLE_SIZE = 8 * 1024


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
    """Check if stdin is a real pipe (FIFO) that should be read.

    Returns True ONLY for real FIFO pipes (from shell piping like `echo x | pflow`).
    Returns False for everything else: terminals, sockets, character devices, StringIO.

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

    Environment Behavior:
    --------------------
    | Environment              | stdin type      | S_ISFIFO | Result        |
    |--------------------------|-----------------|----------|---------------|
    | `echo x \\| pflow`        | FIFO pipe       | True     | Read (block)  |
    | `echo -n "" \\| pflow`    | FIFO pipe       | True     | Read (empty)  |
    | Claude Code              | char device     | False    | Skip (no hang)|
    | CliRunner (tests)        | StringIO        | N/A      | Skip (no fd)  |
    | Interactive terminal     | TTY             | N/A      | Skip (early)  |

    For detailed investigation history, see:
    .taskmaster/tasks/task_115/implementation/progress-log.md (Session 6)

    Returns:
        True if stdin is a FIFO pipe, False otherwise
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

    # Check if stdin is a FIFO (real pipe)
    # Only FIFOs should be read - this is Unix standard behavior
    try:
        mode = os.fstat(fd).st_mode
        return stat.S_ISFIFO(mode)
    except OSError:
        return False


def read_stdin() -> str | None:
    """Read all stdin content if available.

    Only reads if stdin is a real FIFO pipe (Unix standard behavior).
    Empty string is valid content and will be returned (not treated as None).

    Returns:
        Content string if stdin is a pipe (including empty string),
        None if no pipe or binary/over limit

    Raises:
        UnicodeDecodeError: If stdin contains invalid UTF-8
    """
    # Only read if stdin is a real FIFO pipe
    if not stdin_has_data():
        return None

    try:
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


def determine_stdin_mode(content: str) -> str:
    """Determine if stdin contains workflow JSON or data.

    Args:
        content: The stdin content to analyze

    Returns:
        'workflow' if content is valid JSON with 'ir_version' key, 'data' otherwise
    """
    try:
        # Try to parse as JSON
        parsed = json.loads(content)

        # Check if it's a dict with ir_version key
        if isinstance(parsed, dict) and "ir_version" in parsed:
            return "workflow"

    except (json.JSONDecodeError, TypeError):
        # Not valid JSON or not the right type
        pass

    # Default to data mode
    return "data"


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
        chunks, total_size, peek = _read_within_memory_limit(sample, max_size)

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
