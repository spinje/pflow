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
        transport: str = "stdio",
        command: Optional[str] = None,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        url: Optional[str] = None,
        auth: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[int] = None,
        sse_timeout: Optional[int] = None,
    ) -> None:
        """Add or update an MCP server configuration.

        Args:
            name: Server name (e.g., "github")
            transport: Transport type ("stdio" or "http")
            command: Command to execute (required for stdio)
            args: Command arguments (for stdio)
            env: Environment variables with ${VAR} expansion support
            url: Server URL (required for HTTP)
            auth: Authentication config (for HTTP)
            headers: Custom headers (for HTTP)
            timeout: HTTP timeout in seconds (default: 30)
            sse_timeout: SSE read timeout in seconds (default: 300)

        """
        # Validate server name
        self._validate_server_name(name)

        config = self.load()
        now = datetime.now(timezone.utc).isoformat()
        is_update = name in config["servers"]

        # Build configuration based on transport
        if transport == "stdio":
            server_config = self._build_stdio_config(command, args, env, now)
        elif transport == "http":
            server_config = self._build_http_config(url, auth, headers, timeout, sse_timeout, env, now)
        else:
            raise ValueError(f"Unsupported transport: {transport}. Supported: 'stdio', 'http'")

        # Preserve created_at for updates
        self._set_created_at(server_config, is_update, config.get("servers", {}).get(name, {}), now)

        # Validate the complete configuration
        self.validate_server_config(server_config)

        config["servers"][name] = server_config
        self.save(config)

        # Log the action
        self._log_server_action(is_update, name, transport, command, url)

    def _validate_server_name(self, name: str) -> None:
        """Validate server name format.

        Args:
            name: Server name to validate

        Raises:
            ValueError: If name is invalid

        """
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                f"Invalid server name: {name}. Use alphanumeric characters, hyphens, and underscores only.",
            )

    def _build_stdio_config(
        self,
        command: Optional[str],
        args: Optional[list[str]],
        env: Optional[dict[str, str]],
        now: str,
    ) -> dict[str, Any]:
        """Build stdio transport configuration.

        Args:
            command: Command to execute
            args: Command arguments
            env: Environment variables
            now: Current timestamp

        Returns:
            Server configuration dict

        Raises:
            ValueError: If command is missing

        """
        if not command:
            raise ValueError("Command is required for stdio transport")

        return {
            "transport": "stdio",
            "command": command,
            "args": args or [],
            "env": env or {},
            "updated_at": now,
        }

    def _build_http_config(
        self,
        url: Optional[str],
        auth: Optional[dict[str, Any]],
        headers: Optional[dict[str, str]],
        timeout: Optional[int],
        sse_timeout: Optional[int],
        env: Optional[dict[str, str]],
        now: str,
    ) -> dict[str, Any]:
        """Build HTTP transport configuration.

        Args:
            url: Server URL
            auth: Authentication config
            headers: Custom headers
            timeout: HTTP timeout
            sse_timeout: SSE timeout
            env: Environment variables
            now: Current timestamp

        Returns:
            Server configuration dict

        Raises:
            ValueError: If URL is missing

        """
        if not url:
            raise ValueError("URL is required for HTTP transport")

        server_config: dict[str, Any] = {
            "transport": "http",
            "url": url,
            "updated_at": now,
        }

        # Add optional fields if provided
        if auth:
            server_config["auth"] = auth
        if headers:
            server_config["headers"] = headers
        if timeout is not None:
            server_config["timeout"] = timeout
        if sse_timeout is not None:
            server_config["sse_timeout"] = sse_timeout
        if env:
            server_config["env"] = env  # Some HTTP servers may need env vars

        return server_config

    def _set_created_at(
        self,
        server_config: dict[str, Any],
        is_update: bool,
        existing_config: dict[str, Any],
        now: str,
    ) -> None:
        """Set created_at timestamp for server config.

        Args:
            server_config: Server configuration to update
            is_update: Whether this is an update
            existing_config: Existing server config if updating
            now: Current timestamp

        """
        if not is_update:
            server_config["created_at"] = now
        elif "created_at" in existing_config:
            server_config["created_at"] = existing_config["created_at"]
        else:
            server_config["created_at"] = now

    def _log_server_action(
        self,
        is_update: bool,
        name: str,
        transport: str,
        command: Optional[str],
        url: Optional[str],
    ) -> None:
        """Log server add/update action.

        Args:
            is_update: Whether this was an update
            name: Server name
            transport: Transport type
            command: Command for stdio transport
            url: URL for HTTP transport

        """
        action = "Updated" if is_update else "Added"
        if transport == "stdio":
            logger.info(f"{action} MCP server '{name}' with command '{command}'")
        else:
            logger.info(f"{action} HTTP MCP server '{name}' at {url}")

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
        """Validate a server configuration for both stdio and HTTP transports.

        Args:
            config: Server configuration to validate

        Raises:
            ValueError: If configuration is invalid

        """
        # Transport is always required
        if "transport" not in config:
            raise ValueError("Missing required field: transport")

        transport = config["transport"]

        if transport == "stdio":
            self._validate_stdio_config(config)
        elif transport == "http":
            self._validate_http_config(config)
        else:
            raise ValueError(f"Unsupported transport type: {transport}. Supported: 'stdio', 'http'")

        # Common validation for both transports
        # Validate env is a dictionary if present
        if "env" in config and not isinstance(config["env"], dict):
            raise ValueError("Environment variables must be a dictionary")

    def _validate_stdio_config(self, config: dict[str, Any]) -> None:
        """Validate stdio transport configuration.

        Args:
            config: Server configuration to validate

        Raises:
            ValueError: If configuration is invalid

        """
        if "command" not in config:
            raise ValueError("stdio transport requires 'command' field")

        if not config["command"]:
            raise ValueError("Command cannot be empty")

        # Validate args is a list if present
        if "args" in config and not isinstance(config["args"], list):
            raise ValueError("Arguments must be a list")

    def _validate_http_config(self, config: dict[str, Any]) -> None:
        """Validate HTTP transport configuration.

        Args:
            config: Server configuration to validate

        Raises:
            ValueError: If configuration is invalid

        """
        # Validate required URL field
        self._validate_http_url(config)

        # Validate optional auth field
        if "auth" in config:
            self._validate_auth_config(config["auth"])

        # Validate optional headers field
        if "headers" in config and not isinstance(config["headers"], dict):
            raise ValueError("Headers must be a dictionary")

        # Validate timeout fields
        self._validate_http_timeouts(config)

    def _validate_http_url(self, config: dict[str, Any]) -> None:
        """Validate HTTP URL field.

        Args:
            config: Server configuration to validate

        Raises:
            ValueError: If URL is invalid

        """
        if "url" not in config:
            raise ValueError("HTTP transport requires 'url' field")

        url = config["url"]
        if not url or not isinstance(url, str):
            raise ValueError("URL must be a non-empty string")

        # Validate URL format
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")

        # Warn about non-HTTPS for non-localhost URLs
        if url.startswith("http://") and not any(host in url for host in ["localhost", "127.0.0.1", "::1"]):
            logger.warning(f"Using non-HTTPS URL for remote server: {url}. Consider using HTTPS for security.")

    def _validate_http_timeouts(self, config: dict[str, Any]) -> None:
        """Validate HTTP timeout fields.

        Args:
            config: Server configuration to validate

        Raises:
            ValueError: If timeouts are invalid

        """
        if "timeout" in config:
            timeout = config["timeout"]
            if not isinstance(timeout, (int, float)) or timeout <= 0:
                raise ValueError("Timeout must be a positive number")
            if timeout > 600:
                raise ValueError("Timeout cannot exceed 600 seconds (10 minutes)")

        if "sse_timeout" in config:
            sse_timeout = config["sse_timeout"]
            if not isinstance(sse_timeout, (int, float)) or sse_timeout <= 0:
                raise ValueError("SSE timeout must be a positive number")

    def _validate_auth_config(self, auth: dict[str, Any]) -> None:
        """Validate authentication configuration.

        Args:
            auth: Authentication configuration to validate

        Raises:
            TypeError: If auth is not a dictionary
            ValueError: If authentication configuration is invalid

        """
        if not isinstance(auth, dict):
            raise TypeError("Auth config must be a dictionary")

        if "type" not in auth:
            raise ValueError("Auth config must specify 'type'")

        auth_type = auth["type"]

        if auth_type == "bearer":
            if "token" not in auth:
                raise ValueError("Bearer auth requires 'token' field")
        elif auth_type == "api_key":
            if "key" not in auth:
                raise ValueError("API key auth requires 'key' field")
            # header is optional, defaults to X-API-Key
        elif auth_type == "basic":
            if "username" not in auth:
                raise ValueError("Basic auth requires 'username' field")
            if "password" not in auth:
                raise ValueError("Basic auth requires 'password' field")
        else:
            raise ValueError(f"Unsupported auth type: {auth_type}. Supported: 'bearer', 'api_key', 'basic'")
