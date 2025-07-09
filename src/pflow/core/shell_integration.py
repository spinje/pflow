"""Shell integration utilities for pflow.

This module provides core functions for detecting, reading, and categorizing
stdin input, enabling dual-mode stdin handling in pflow workflows.

The module supports:
- Detection of piped stdin vs interactive terminal
- Reading text data from stdin with UTF-8 encoding
- Binary data detection and handling
- Large file streaming to temporary storage
- Determining if stdin contains workflow JSON or data
- Populating the shared store with stdin content
"""

import json
import os
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


def read_stdin() -> str | None:
    """Read all stdin content if available.

    This function maintains backward compatibility while internally using
    the enhanced stdin handling. For binary or large files, returns None
    and the caller should check the enhanced read_stdin_enhanced() function.

    Returns:
        Content string if stdin has text data under memory limit,
        None if no stdin, empty, binary, or over limit

    Raises:
        UnicodeDecodeError: If stdin contains invalid UTF-8
    """
    if not detect_stdin():
        return None

    # For backward compatibility, we still use the simple text reading
    # This ensures existing code continues to work
    try:
        content = sys.stdin.read()

        # Treat empty stdin as no input per spec
        if content == "":
            return None

        # Strip trailing newline only (not all whitespace)
        # This preserves intentional whitespace in data
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
    if not detect_stdin():
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


def populate_shared_store(shared: dict, content: str) -> None:
    """Add stdin content to shared store.

    Args:
        shared: The shared store dictionary
        content: The stdin content to store

    Side Effects:
        Sets shared['stdin'] = content
    """
    shared["stdin"] = content


def detect_binary_content(sample: bytes) -> bool:
    """Detect if content is likely binary by checking for null bytes.

    Args:
        sample: First few KB of content to check

    Returns:
        True if binary content detected, False otherwise
    """
    # Check for null bytes - common indicator of binary data
    return b"\x00" in sample


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
        if peek:
            # Need to stream to temp file
            temp_file = tempfile.NamedTemporaryFile(mode="wb", delete=False, prefix="pflow_stdin_")
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
                return StdinData(temp_path=temp_file.name)
            except Exception:
                # Clean up on error
                temp_file.close()
                try:
                    os.unlink(temp_file.name)
                except OSError:
                    pass
                raise

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
