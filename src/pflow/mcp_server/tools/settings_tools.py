"""Settings management tools for the MCP server.

These tools provide settings read/write capabilities for
configuring API keys and other settings.
"""

import asyncio
import logging
from typing import Any

from pydantic import Field

from ..server import mcp
from ..services.settings_service import SettingsService

logger = logging.getLogger(__name__)


@mcp.tool()
async def settings_get(
    key: str = Field(..., description="Environment variable name to retrieve"),
) -> dict[str, Any]:
    """Get an environment variable or setting value.

    Retrieves values from pflow environment configuration.
    Most commonly used for API keys and feature flags.

    Args:
        key: Environment variable name (e.g., "ANTHROPIC_API_KEY", "test_nodes_enabled")

    Returns:
        Dictionary with key, value, and found status

    Examples:
        Get API key: key="ANTHROPIC_API_KEY"
        Returns {"key": "ANTHROPIC_API_KEY", "value": "sk-ant-...", "found": true}

        Get feature flag: key="test_nodes_enabled"
        Returns {"key": "test_nodes_enabled", "value": true, "found": true}
    """
    logger.debug(f"settings_get called for key: {key}")

    def _sync_get() -> dict[str, Any]:
        """Synchronous get operation."""
        result: dict[str, Any] = SettingsService.get_setting(key)
        return result

    # Run in thread pool
    result = await asyncio.to_thread(_sync_get)

    logger.info(f"Retrieved setting: {key}")
    return result


@mcp.tool()
async def settings_set(
    key: str = Field(..., description="Environment variable name to set"),
    value: str = Field(..., description="Value to set"),
) -> dict[str, Any]:
    """Set an environment variable or setting value.

    Sets environment configuration for pflow.
    Most commonly used for configuring API keys and feature flags.

    Args:
        key: Environment variable name (e.g., "ANTHROPIC_API_KEY")
        value: Value to set

    Returns:
        Confirmation with success status

    Examples:
        Set API key: key="ANTHROPIC_API_KEY", value="sk-ant-..."
        Returns {"success": true, "message": "Setting updated"}

        Set flag: key="test_nodes_enabled", value="true"
        Returns {"success": true, "message": "Setting updated"}
    """
    logger.debug(f"settings_set called for key: {key}")

    def _sync_set() -> dict[str, Any]:
        """Synchronous set operation."""
        result: dict[str, Any] = SettingsService.set_setting(key, value)
        return result

    # Run in thread pool
    result = await asyncio.to_thread(_sync_set)

    logger.info(f"Set setting: {key}")
    return result


@mcp.tool()
async def settings_show() -> str:
    """Show all pflow settings including environment variable overrides.

    Returns all configured settings from ~/.pflow/settings.json plus
    any environment variables that override settings (like PFLOW_INCLUDE_TEST_NODES).

    Returns formatted text matching CLI output exactly.

    Returns:
        Formatted text string with settings path, JSON settings, and env overrides

    Example response:
        Settings file: /Users/user/.pflow/settings.json

        Current settings:
        {
          "version": "1.0.0",
          "registry": {
            "nodes": {"allow": ["*"], "deny": []}
          }
        }

        ⚠️  PFLOW_INCLUDE_TEST_NODES environment variable is set
           Test nodes are enabled via environment variable
    """
    logger.debug("settings_show called")

    def _sync_show() -> str:
        """Synchronous show operation."""
        result: str = SettingsService.show_all_settings()
        return result

    # Run in thread pool
    result = await asyncio.to_thread(_sync_show)

    logger.info("Retrieved all settings")
    return result


@mcp.tool()
async def settings_list_env(
    show_values: bool = Field(False, description="Show full values instead of masked"),
) -> str:
    """List all configured environment variables.

    By default, values are masked showing only the first 3 characters
    for security. Use show_values=true to display full values.

    Returns formatted text matching CLI output exactly.

    Args:
        show_values: If true, show full unmasked values (use with caution)

    Returns:
        Formatted text string with environment variables

    Example response (masked):
        Environment variables:
          ANTHROPIC_API_KEY: sk-***
          OPENAI_API_KEY: sk-***

    Example response (unmasked):
        ⚠️  Displaying unmasked values

        Environment variables:
          ANTHROPIC_API_KEY: sk-ant-1234...
          OPENAI_API_KEY: sk-proj-5678...
    """
    logger.debug(f"settings_list_env called with show_values={show_values}")

    def _sync_list_env() -> str:
        """Synchronous list operation."""
        result: str = SettingsService.list_env_variables(show_values=show_values)
        return result

    # Run in thread pool
    result = await asyncio.to_thread(_sync_list_env)

    logger.info(f"Retrieved environment variables (masked={not show_values})")
    return result
