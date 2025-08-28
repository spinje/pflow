"""MCP server configuration manager for pflow."""

import contextlib
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MCPServerManager:
    """Manages MCP server configurations.

    This class handles loading, saving, and managing MCP server configurations
    stored in ~/.pflow/mcp-servers.json. It follows the same patterns as
    WorkflowManager and Registry for consistency.

    ## Configuration Format

    ```json
    {
        "servers": {
            "github": {
                "command": "npx -y @modelcontextprotocol/server-github",
                "args": [],
                "env": {
                    "GITHUB_TOKEN": "${GITHUB_TOKEN}"
                },
                "transport": "stdio",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z"
            }
        },
        "version": "1.0.0"
    }
    ```

    ## Environment Variable Expansion

    The `env` field supports `${VAR}` syntax for environment variable expansion.
    This expansion happens at runtime when the server is started, not when saved.
    """

    DEFAULT_CONFIG_PATH = Path("~/.pflow/mcp-servers.json")
    CONFIG_VERSION = "1.0.0"

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize MCPServerManager.

        Args:
            config_path: Path to MCP config file. Defaults to ~/.pflow/mcp-servers.json
        """
        if config_path is None:
            config_path = self.DEFAULT_CONFIG_PATH

        self.config_path = Path(config_path).expanduser().resolve()

        # Create parent directory if it doesn't exist
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        logger.debug(f"MCPServerManager initialized with config path: {self.config_path}")

    def load(self) -> dict[str, Any]:
        """Load MCP server configuration from disk.

        Returns:
            Configuration dictionary with servers and metadata
        """
        if not self.config_path.exists():
            logger.info(f"No MCP server configuration found at {self.config_path}, returning empty config")
            return {"servers": {}, "version": self.CONFIG_VERSION}

        try:
            with open(self.config_path) as f:
                config = json.load(f)

            # Ensure required fields exist
            if "servers" not in config:
                config["servers"] = {}
            if "version" not in config:
                config["version"] = self.CONFIG_VERSION

            logger.debug(f"Loaded {len(config['servers'])} MCP servers from configuration")
            return dict(config)

        except json.JSONDecodeError as e:
            logger.exception("Failed to parse MCP server configuration")
            raise ValueError(f"Invalid JSON in MCP server configuration file: {e}") from e
        except Exception:
            logger.exception("Failed to load MCP server configuration")
            raise

    def save(self, config: dict[str, Any]) -> None:
        """Save MCP server configuration to disk atomically.

        Uses atomic file operations to prevent corruption.

        Args:
            config: Configuration dictionary to save
        """
        # Ensure version is set
        if "version" not in config:
            config["version"] = self.CONFIG_VERSION

        # Validate structure
        if "servers" not in config:
            raise ValueError("Configuration must have 'servers' field")

        # Create temporary file in same directory for atomic write
        temp_fd, temp_path = tempfile.mkstemp(dir=self.config_path.parent, prefix=".mcp-servers-", suffix=".tmp")

        try:
            # Write to temporary file
            with os.fdopen(temp_fd, "w") as f:
                json.dump(config, f, indent=2, sort_keys=True)
                f.write("\n")  # Add final newline

            # Atomic rename (overwrites existing file)
            Path(temp_path).replace(self.config_path)

            logger.info(f"Saved {len(config['servers'])} MCP servers to configuration")

        except Exception:
            # Clean up temporary file on error
            with contextlib.suppress(Exception):
                Path(temp_path).unlink()

            logger.exception("Failed to save MCP server configuration")
            raise

    def add_server(
        self,
        name: str,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        transport: str = "stdio",
    ) -> None:
        """Add or update an MCP server configuration.

        Args:
            name: Server name (e.g., "github")
            command: Command to execute (e.g., "npx")
            args: Command arguments (e.g., ["@modelcontextprotocol/server-github"])
            env: Environment variables with ${VAR} expansion support
            transport: Transport type (only "stdio" supported in MVP)
        """
        if transport != "stdio":
            raise ValueError(f"Only 'stdio' transport is supported in MVP, got '{transport}'")

        # Validate server name
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                f"Invalid server name: {name}. Use alphanumeric characters, hyphens, and underscores only."
            )

        config = self.load()

        now = datetime.now(timezone.utc).isoformat()

        # Check if updating existing server
        is_update = name in config["servers"]

        # Create server entry
        server_config = {
            "command": command,
            "args": args or [],
            "env": env or {},
            "transport": transport,
            "updated_at": now,
        }

        if not is_update:
            server_config["created_at"] = now
        else:
            # Preserve created_at for existing servers
            if "created_at" in config["servers"][name]:
                server_config["created_at"] = config["servers"][name]["created_at"]
            else:
                server_config["created_at"] = now

        config["servers"][name] = server_config

        self.save(config)

        action = "Updated" if is_update else "Added"
        logger.info(f"{action} MCP server '{name}' with command '{command}'")

    def remove_server(self, name: str) -> bool:
        """Remove an MCP server configuration.

        Args:
            name: Server name to remove

        Returns:
            True if server was removed, False if not found
        """
        config = self.load()

        if name not in config["servers"]:
            logger.warning(f"MCP server '{name}' not found in configuration")
            return False

        del config["servers"][name]
        self.save(config)

        logger.info(f"Removed MCP server '{name}' from configuration")
        return True

    def get_server(self, name: str) -> Optional[dict[str, Any]]:
        """Get configuration for a specific MCP server.

        Args:
            name: Server name

        Returns:
            Server configuration or None if not found
        """
        config = self.load()
        result = config["servers"].get(name)
        return dict(result) if result else None

    def list_servers(self) -> list[str]:
        """List all configured MCP server names.

        Returns:
            List of server names
        """
        config = self.load()
        return list(config["servers"].keys())

    def get_all_servers(self) -> dict[str, dict[str, Any]]:
        """Get all server configurations.

        Returns:
            Dictionary mapping server names to configurations
        """
        config = self.load()
        return dict(config["servers"])

    def parse_command_string(self, command_str: str) -> tuple[str, list[str]]:
        """Parse a command string into command and arguments.

        Handles both simple commands and commands with arguments.

        Args:
            command_str: Full command string (e.g., "npx @modelcontextprotocol/server-github")

        Returns:
            Tuple of (command, args)
        """
        import shlex

        parts = shlex.split(command_str)
        if not parts:
            raise ValueError("Empty command string")

        command = parts[0]
        args = parts[1:] if len(parts) > 1 else []

        return command, args

    def validate_server_config(self, config: dict[str, Any]) -> None:
        """Validate a server configuration.

        Args:
            config: Server configuration to validate

        Raises:
            ValueError: If configuration is invalid
        """
        required_fields = ["command", "transport"]

        for field in required_fields:
            if field not in config:
                raise ValueError(f"Missing required field: {field}")

        if config["transport"] != "stdio":
            raise ValueError(f"Only 'stdio' transport is supported, got '{config['transport']}'")

        if not config["command"]:
            raise ValueError("Command cannot be empty")

        # Validate env is a dictionary if present
        if "env" in config and not isinstance(config["env"], dict):
            raise ValueError("Environment variables must be a dictionary")

        # Validate args is a list if present
        if "args" in config and not isinstance(config["args"], list):
            raise ValueError("Arguments must be a list")
