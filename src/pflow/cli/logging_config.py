"""Centralized logging configuration for CLI commands.

This module provides a single source of truth for logging configuration
across all CLI command groups (workflow, registry, mcp, settings, etc.).
"""

import logging
import os


def configure_logging(verbose: bool) -> None:
    """Configure logging levels based on verbose flag.

    This function should be called ONCE at CLI startup before any command execution.
    It configures the root logger and suppresses noisy third-party libraries.

    Args:
        verbose: If True, show INFO+ logs. If False, show only WARNING+ logs.

    Examples:
        >>> # In main_wrapper.py or command entry point
        >>> configure_logging(verbose=True)   # Show INFO logs
        >>> configure_logging(verbose=False)  # Only WARNING+ logs
    """
    # Skip configuration if running in test environment
    # Tests manage their own logging to avoid interference
    if os.getenv("PYTEST_CURRENT_TEST"):
        return

    # Only configure if not already configured
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO if verbose else logging.WARNING,
            format="%(levelname)s: %(message)s",
        )
    else:
        # Just adjust the root level if handlers already exist
        logging.getLogger().setLevel(logging.INFO if verbose else logging.WARNING)

    # Always silence noisy third-party libraries (even in verbose mode)
    # These libraries generate excessive INFO logs that aren't useful for users
    for logger_name in [
        "httpx",
        "httpx._client",
        "httpcore",
        "httpcore.http11",
        "urllib3",
        "composio",
        "mcp",
        "streamable_http",
    ]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    if not verbose:
        # In non-verbose mode, also suppress INFO from pflow itself
        # This ensures clean output showing only important messages
        logging.getLogger("pflow").setLevel(logging.WARNING)
