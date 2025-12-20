"""Main entry point for pflow MCP server.

This module provides the run_server function that starts the MCP server
with stdio transport. It handles signal handlers for graceful shutdown
and ensures proper logging configuration.
"""

import logging
import os
import signal
import sys
from types import FrameType

from .server import mcp, register_tools

# Configure logging to stderr (stdout is reserved for protocol messages)
logger = logging.getLogger(__name__)


def run_server() -> None:
    """Run the pflow MCP server with stdio transport.

    This function:
    1. Injects API keys from pflow settings into environment
    2. Installs Anthropic model wrapper (required for planning nodes)
    3. Registers all tools with the server
    4. Sets up signal handlers for graceful shutdown
    5. Runs the server with stdio transport

    The server uses stdio transport where:
    - stdin: Receives JSON-RPC requests from the client
    - stdout: Sends JSON-RPC responses to the client
    - stderr: All logging output

    Note: This function is synchronous because FastMCP manages
    its own event loop when using stdio transport.
    """
    # Inject API keys from pflow settings into environment
    # This must happen early, before any LLM operations
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        from pflow.core.llm_config import inject_settings_env_vars

        inject_settings_env_vars()
        logger.info("Injected environment variables from pflow settings")

    # Install Anthropic model wrapper (REQUIRED for planning nodes)
    # This monkey-patches llm.get_model() to return AnthropicLLMModel
    # for Claude models, enabling prompt caching and thinking tokens
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        from pflow.planning.utils.anthropic_llm_model import install_anthropic_model

        install_anthropic_model()
        logger.info("Installed Anthropic model wrapper for planning nodes")

    # Register all tools before starting the server
    register_tools()

    # Set up signal handlers for graceful shutdown
    def handle_shutdown(signum: int, frame: FrameType | None) -> None:
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    logger.info("Starting pflow MCP server with stdio transport...")
    logger.info("Server name: pflow")

    # Note: We can't call list_tools() here because it's async
    # and we're not in an async context anymore
    logger.info("MCP server initialized, ready for connections")

    try:
        # FastMCP's run() method manages its own event loop for stdio transport
        # This is a blocking call that runs until the server shuts down
        mcp.run("stdio")
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"MCP server error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("MCP server shutdown complete")


def configure_logging(debug: bool = False) -> None:
    """Configure logging for the MCP server.

    All logs go to stderr to keep stdout clean for protocol messages.

    Args:
        debug: Enable debug logging if True
    """
    level = logging.DEBUG if debug else logging.INFO

    # Configure root logger
    logging.basicConfig(
        stream=sys.stderr,
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Reduce noise from some verbose libraries
    if not debug:
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        logging.getLogger("mcp").setLevel(logging.INFO)


def main(debug: bool = False) -> None:
    """Main entry point for running the server.

    Args:
        debug: Enable debug logging if True
    """
    configure_logging(debug)

    try:
        # No asyncio.run() here - FastMCP manages its own event loop
        run_server()
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Server failed: {e}", exc_info=True)
        sys.exit(1)


__all__ = ["configure_logging", "main", "run_server"]
