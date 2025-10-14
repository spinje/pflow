"""Settings service for MCP server.

Provides settings read/write capabilities.
All operations are stateless with fresh SettingsManager instances.
"""

import logging
from typing import Any

from pflow.core.settings import SettingsManager

from .base_service import BaseService, ensure_stateless

logger = logging.getLogger(__name__)


class SettingsService(BaseService):
    """Service for settings management.

    Provides settings read/write capabilities.
    All operations are stateless with fresh SettingsManager instances.
    """

    @classmethod
    @ensure_stateless
    def get_setting(cls, key: str) -> dict[str, Any]:
        """Get a setting value (environment variable).

        Args:
            key: Setting key to retrieve

        Returns:
            Dictionary with key, value, and found status
        """
        manager = SettingsManager()  # Fresh instance

        # Get environment variable
        value = manager.get_env(key)

        if value is not None:
            return {"key": key, "value": value, "found": True}
        else:
            return {
                "key": key,
                "value": None,
                "found": False,
                "error": f"Setting '{key}' not found",
            }

    @classmethod
    @ensure_stateless
    def set_setting(cls, key: str, value: str) -> dict[str, Any]:
        """Set a setting value (environment variable).

        Args:
            key: Setting key
            value: Setting value

        Returns:
            Confirmation with success status
        """
        manager = SettingsManager()  # Fresh instance

        # Set environment variable
        manager.set_env(key, value)

        return {
            "key": key,
            "value": value,
            "success": True,
            "message": f"Setting '{key}' updated successfully",
        }

    @classmethod
    @ensure_stateless
    def show_all_settings(cls) -> str:
        """Get all settings including environment variable overrides.

        Returns:
            Formatted text string matching CLI output
        """
        import json
        import os

        manager = SettingsManager()  # Fresh instance
        settings = manager.load()

        # Format output to match CLI (lines 38-55 in commands/settings.py)
        lines = [
            f"Settings file: {manager.settings_path}",
            "",
            "Current settings:",
            json.dumps(settings.model_dump(), indent=2),
        ]

        # Check for environment variable overrides
        if os.getenv("PFLOW_INCLUDE_TEST_NODES"):
            env_value = os.getenv("PFLOW_INCLUDE_TEST_NODES", "").lower()
            is_enabled = env_value in ("true", "1", "yes")
            lines.append("")
            lines.append("⚠️  PFLOW_INCLUDE_TEST_NODES environment variable is set")
            lines.append(f"   Test nodes are {'enabled' if is_enabled else 'disabled'} via environment variable")

        return "\n".join(lines)

    @classmethod
    @ensure_stateless
    def list_env_variables(cls, show_values: bool = False) -> str:
        """List all configured environment variables.

        Args:
            show_values: If True, show full values; if False, mask them

        Returns:
            Formatted text string matching CLI output
        """
        manager = SettingsManager()  # Fresh instance

        # Get environment variables (masked or unmasked)
        env_vars = manager.list_env(mask_values=not show_values)

        # Format output to match CLI (lines 289-313 in commands/settings.py)
        lines = []

        if show_values:
            lines.append("⚠️  Displaying unmasked values")
            lines.append("")

        if not env_vars:
            lines.append("No environment variables configured")
        else:
            lines.append("Environment variables:")
            for key, value in sorted(env_vars.items()):
                lines.append(f"  {key}: {value}")

        return "\n".join(lines)
