"""Shared formatter for execution history display.

This module provides formatting for workflow execution history across CLI and MCP interfaces.
Formats timestamps, execution counts, and parameter history for display in discovery and describe tools.

Usage:
    >>> from pflow.execution.formatters.history_formatter import format_execution_history
    >>> metadata = {
    ...     "execution_count": 5,
    ...     "last_execution_timestamp": "2025-10-18T22:01:49.857930",
    ...     "last_execution_success": True,
    ...     "last_execution_params": {"channel": "C09", "api_key": "<REDACTED>"}
    ... }
    >>> print(format_execution_history(metadata, mode="compact"))
    5 times | Last: 2025-10-18 22:01 | Status: ✓ Success
"""

from datetime import datetime, timezone
from typing import Any, Optional


def format_execution_history(
    rich_metadata: dict[str, Any],
    mode: str = "compact",
) -> Optional[str]:
    """Format execution history from rich_metadata.

    Args:
        rich_metadata: Workflow rich_metadata dict containing execution history
        mode: Display mode - "compact" for single line, "detailed" for multi-line

    Returns:
        Formatted history string or None if no execution history

    Example:
        >>> metadata = {
        ...     "execution_count": 3,
        ...     "last_execution_timestamp": "2025-10-18T22:01:49.857930",
        ...     "last_execution_success": True
        ... }
        >>> result = format_execution_history(metadata, mode="compact")
        >>> "3 times" in result
        True
    """
    if not rich_metadata:
        return None

    execution_count = rich_metadata.get("execution_count", 0)
    if execution_count == 0:
        return None

    timestamp = rich_metadata.get("last_execution_timestamp")
    success = rich_metadata.get("last_execution_success", True)
    last_params = rich_metadata.get("last_execution_params", {})

    if mode == "compact":
        return _format_compact(execution_count, timestamp, success)
    elif mode == "detailed":
        return _format_detailed(execution_count, timestamp, success, last_params)
    else:
        raise ValueError(f"Invalid mode: {mode}. Must be 'compact' or 'detailed'")


def _format_compact(
    execution_count: int,
    timestamp: Optional[str],
    success: bool,
) -> str:
    """Format execution history as single line.

    Args:
        execution_count: Number of executions
        timestamp: ISO format timestamp
        success: Whether last execution succeeded

    Returns:
        Compact single-line formatted string
    """
    parts = []

    # Execution count
    times_text = "time" if execution_count == 1 else "times"
    parts.append(f"{execution_count} {times_text}")

    # Timestamp
    if timestamp:
        formatted_time = format_timestamp(timestamp, mode="short")
        parts.append(f"Last: {formatted_time}")

    # Success status
    status_icon = "✓" if success else "✗"
    status_text = "Success" if success else "Failed"
    parts.append(f"Status: {status_icon} {status_text}")

    return " | ".join(parts)


def _format_detailed(
    execution_count: int,
    timestamp: Optional[str],
    success: bool,
    last_params: dict[str, Any],
) -> str:
    """Format execution history with parameters.

    Args:
        execution_count: Number of executions
        timestamp: ISO format timestamp
        success: Whether last execution succeeded
        last_params: Last execution parameters (already sanitized)

    Returns:
        Multi-line formatted string
    """
    lines = []

    # Execution count
    times_text = "time" if execution_count == 1 else "times"
    lines.append(f"  Runs: {execution_count} {times_text}")

    # Timestamp
    if timestamp:
        formatted_time = format_timestamp(timestamp, mode="full")
        lines.append(f"  Last: {formatted_time}")

    # Success status
    status_icon = "✓" if success else "✗"
    status_text = "Success" if success else "Failed"
    lines.append(f"  Status: {status_icon} {status_text}")

    # Parameters (if any)
    if last_params:
        params_str = _format_parameters(last_params)
        lines.append(f"  Last Parameters: {params_str}")

    return "\n".join(lines)


def format_timestamp(timestamp_str: str, mode: str = "short") -> str:
    """Format ISO timestamp for display.

    Args:
        timestamp_str: ISO format timestamp string
        mode: Display mode - "short" (date + time), "full" (includes timezone), "relative" (time ago)

    Returns:
        Formatted timestamp string

    Example:
        >>> ts = "2025-10-18T22:01:49.857930"
        >>> result = format_timestamp(ts, mode="short")
        >>> "2025-10-18" in result
        True
    """
    # Validate mode first (outside try block)
    if mode not in ("short", "full", "relative"):
        raise ValueError(f"Invalid mode: {mode}")

    try:
        # Parse timestamp (may or may not have timezone)
        if "+" in timestamp_str or timestamp_str.endswith("Z"):
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        else:
            # Assume local/naive timestamp
            dt = datetime.fromisoformat(timestamp_str)

        if mode == "short":
            # Date + time without seconds
            return dt.strftime("%Y-%m-%d %H:%M")
        elif mode == "full":
            # Full timestamp
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        else:  # mode == "relative"
            # Time ago (e.g., "2 days ago")
            return _format_relative_time(dt)

    except (ValueError, AttributeError):
        # If parsing fails, return original
        return timestamp_str


def _format_relative_time(dt: datetime) -> str:
    """Format datetime as relative time (e.g., '2 days ago').

    Args:
        dt: Datetime to format

    Returns:
        Relative time string
    """
    # Get current time (with timezone awareness if dt has it)
    now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()

    # Calculate difference
    delta = now - dt
    seconds = delta.total_seconds()

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif seconds < 2592000:
        weeks = int(seconds / 604800)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    elif seconds < 31536000:
        months = int(seconds / 2592000)
        return f"{months} month{'s' if months != 1 else ''} ago"
    else:
        years = int(seconds / 31536000)
        return f"{years} year{'s' if years != 1 else ''} ago"


def _format_parameters(params: dict[str, Any], max_length: int = 100) -> str:
    """Format parameters dictionary as compact string.

    Args:
        params: Parameters dictionary (already sanitized)
        max_length: Maximum length before truncation

    Returns:
        Compact parameter string (e.g., "channel=C09, limit=20, api_key=<REDACTED>")
    """
    if not params:
        return "(none)"

    # Format as key=value pairs
    pairs = [f"{k}={v}" for k, v in params.items()]
    result = ", ".join(pairs)

    # Truncate if too long
    if len(result) > max_length:
        result = result[: max_length - 3] + "..."

    return result
