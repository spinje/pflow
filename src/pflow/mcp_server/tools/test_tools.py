"""Test tools for Phase 1 verification.

This module contains simple tools used to verify the MCP server
infrastructure is working correctly. These tools test:
- Basic request/response flow
- Async/sync bridge pattern
- Error handling
- Parameter parsing
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import Field

from ..server import mcp

logger = logging.getLogger(__name__)


@mcp.tool()
async def ping(
    echo: str | None = Field(None, description="Optional message to echo back"),
    error: bool = Field(False, description="If true, simulate an error"),
) -> dict[str, Any]:
    """Simple ping tool to verify the MCP server is working.

    This tool is used for:
    - Verifying the server is running and responsive
    - Testing the async/sync bridge pattern
    - Testing error handling
    - Testing parameter parsing

    Args:
        echo: Optional message to echo back in the response
        error: If true, simulate an error for testing error handling

    Returns:
        Dictionary with status, timestamp, and optional echo message

    Raises:
        ValueError: If error parameter is True (for testing)
    """
    logger.debug(f"Ping called with echo='{echo}', error={error}")

    # Test error handling if requested
    if error:
        logger.warning("Simulating error as requested")
        raise ValueError("Simulated error for testing")

    # Create response
    response = {
        "status": "pong",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "server_name": "pflow",
    }

    if echo:
        response["echo"] = echo

    logger.debug(f"Ping response: {response}")
    return response


@mcp.tool()
async def test_sync_bridge(
    delay_seconds: float = Field(0.1, ge=0, le=5, description="Delay in seconds"),
) -> dict[str, Any]:
    """Test the async/sync bridge pattern used for pflow integration.

    This tool simulates calling synchronous pflow code from the async MCP server
    using asyncio.to_thread, which is the pattern we'll use for all real tools.

    Args:
        delay_seconds: How long to delay (simulates sync operation)

    Returns:
        Dictionary with timing information
    """
    logger.debug(f"Testing sync bridge with {delay_seconds}s delay")

    # Define a synchronous function that simulates pflow code
    def _sync_operation(delay: float) -> dict[str, Any]:
        """Simulate a synchronous pflow operation."""
        import time

        start = time.time()
        time.sleep(delay)  # Simulate work
        end = time.time()

        return {
            "operation": "sync_bridge_test",
            "requested_delay": delay,
            "actual_duration": end - start,
            "thread_safe": True,  # We use fresh instances per request
        }

    # Use asyncio.to_thread to run sync code (pattern for all pflow tools)
    result = await asyncio.to_thread(_sync_operation, delay_seconds)

    logger.debug(f"Sync bridge test complete: {result}")
    return result


@mcp.tool()
async def test_stateless_pattern() -> dict[str, Any]:
    """Verify the stateless pattern by creating fresh instances.

    This tool demonstrates the critical pattern of creating fresh
    instances for every request, which is essential for thread safety
    and preventing stale data bugs.

    Returns:
        Dictionary demonstrating fresh instance creation
    """
    logger.debug("Testing stateless pattern")

    def _create_fresh_instances() -> dict[str, Any]:
        """Simulate creating fresh pflow service instances."""
        # This simulates what we'll do in real tools:
        # manager = WorkflowManager()  # Fresh instance
        # registry = Registry()        # Fresh instance

        import uuid

        instance_id = str(uuid.uuid4())

        return {
            "pattern": "stateless",
            "instance_id": instance_id,  # Unique per request
            "explanation": "Each request gets fresh instances",
            "thread_safe": True,
            "prevents": ["stale data", "race conditions", "cache pollution"],
        }

    # Run in thread pool (matches real pattern)
    result = await asyncio.to_thread(_create_fresh_instances)

    logger.debug(f"Stateless pattern test: {result}")
    return result


# Export all test tools
__all__ = ["ping", "test_stateless_pattern", "test_sync_bridge"]
