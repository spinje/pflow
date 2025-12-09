"""MCP server configuration manager for pflow."""

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MCPServerManager:
    """Manages MCP server configurations.

    This class handles loading, saving, and managing MCP server configurations
    stored in ~/.pflow/mcp-servers.json using the standard MCP format.

    ## Standard MCP Configuration Format

    ```json
    {
        "mcpServers": {
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {
                    "GITHUB_TOKEN": "${GITHUB_TOKEN}"
                }
            },
            "http-server": {
                "type": "http",
                "url": "https://api.example.com/mcp",
                "headers": {
                    "Authorization": "Bearer ${TOKEN}"
                }
            }
        }
    }
    ```

    ## Key Format Rules
    - All servers are under the "mcpServers" key
    - The "type" field is optional for stdio servers (absence means stdio)
    - The "type" field must be "http" for HTTP servers
    - No timestamps, version numbers, or other metadata

    ## Environment Variable Expansion

    The `env` field supports `${VAR}` and `${VAR:-default}` syntax for environment
    variable expansion. This expansion happens at runtime when the server is started.
    """

    DEFAULT_CONFIG_PATH = Path("~/.pflow/mcp-servers.json")

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
            Configuration dictionary in standard MCP format

        """
        if not self.config_path.exists():
            logger.info(f"No MCP server configuration found at {self.config_path}, returning empty config")
            return {"mcpServers": {}}

        try:
            with open(self.config_path) as f:
                config = json.load(f)

            # Ensure mcpServers exists
            if "mcpServers" not in config:
                config["mcpServers"] = {}

            logger.debug(f"Loaded {len(config.get('mcpServers', {}))} MCP servers from configuration")
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
            config: Configuration dictionary in standard MCP format

        """
        # Validate structure
        if "mcpServers" not in config:
            raise ValueError("Configuration must have 'mcpServers' field")

        # Create temporary file in same directory for atomic write
        temp_fd, temp_path = tempfile.mkstemp(dir=self.config_path.parent, prefix=".mcp-servers-", suffix=".tmp")

        try:
            # Write to temporary file
            with os.fdopen(temp_fd, "w") as f:
                json.dump(config, f, indent=2, sort_keys=True)
                f.write("\n")  # Add final newline

            # Atomic rename (overwrites existing file)
            Path(temp_path).replace(self.config_path)

            logger.info(f"Saved {len(config.get('mcpServers', {}))} MCP servers to configuration")

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

        Creates a standard MCP configuration format entry.
        For stdio servers, the "type" field is omitted (defaults to stdio).
        For HTTP servers, "type": "http" is added.

        Args:
            name: Server name (e.g., "github")
            transport: Transport type ("stdio" or "http")
            command: Command to execute (required for stdio)
            args: Command arguments (for stdio)
            env: Environment variables with ${VAR} expansion support
            url: Server URL (required for HTTP)
            auth: Authentication config (for HTTP)
            headers: Custom headers (for HTTP)
            timeout: HTTP timeout in seconds (not part of standard format)
            sse_timeout: SSE read timeout in seconds (not part of standard format)

        """
        # Validate server name
        self._validate_server_name(name)

        config = self.load()
        servers = config.get("mcpServers", {})
        is_update = name in servers

        # Build configuration based on transport
        if transport == "stdio":
            server_config = self._build_stdio_config(command, args, env)
        elif transport == "http":
            server_config = self._build_http_config(url, auth, headers, timeout, sse_timeout, env)
        else:
            raise ValueError(f"Unsupported transport: {transport}. Supported: 'stdio', 'http'")

        # Validate the complete configuration
        self.validate_server_config(server_config)

        servers[name] = server_config
        config["mcpServers"] = servers
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
    ) -> dict[str, Any]:
        """Build stdio configuration in standard MCP format.

        Args:
            command: Command to execute
            args: Command arguments
            env: Environment variables

        Returns:
            Server configuration in standard format

        Raises:
            ValueError: If command is missing

        """
        if not command:
            raise ValueError("Command is required for stdio transport")

        config: dict[str, Any] = {
            "command": command,
        }

        if args:
            config["args"] = args

        if env:
            config["env"] = env

        # type is optional for stdio (it's the default)
        return config

    def _build_http_config(
        self,
        url: Optional[str],
        auth: Optional[dict[str, Any]],
        headers: Optional[dict[str, str]],
        timeout: Optional[int],
        sse_timeout: Optional[int],
        env: Optional[dict[str, str]],
    ) -> dict[str, Any]:
        """Build HTTP configuration in standard MCP format.

        Args:
            url: Server URL
            auth: Authentication config
            headers: Custom headers
            timeout: HTTP timeout
            sse_timeout: SSE timeout
            env: Environment variables

        Returns:
            Server configuration in standard format

        Raises:
            ValueError: If URL is missing

        """
        if not url:
            raise ValueError("URL is required for HTTP transport")

        config: dict[str, Any] = {
            "type": "http",
            "url": url,
        }

        # Add optional fields if provided
        if auth:
            config["auth"] = auth
        if headers:
            config["headers"] = headers
        if env:
            config["env"] = env

        # Note: timeout fields are not part of the standard, skip them
        return config

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
        servers = config.get("mcpServers", {})

        if name not in servers:
            logger.warning(f"MCP server '{name}' not found in configuration")
            return False

        del servers[name]
        config["mcpServers"] = servers
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
        servers = config.get("mcpServers", {})
        server_config = servers.get(name)
        return server_config if server_config is not None else None

    def list_servers(self) -> list[str]:
        """List all configured MCP server names.

        Returns:
            List of server names

        """
        config = self.load()
        return list(config.get("mcpServers", {}).keys())

    def get_all_servers(self) -> dict[str, dict[str, Any]]:
        """Get all server configurations.

        Returns:
            Dictionary mapping server names to configurations

        """
        config = self.load()
        return dict(config["mcpServers"])

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
            config: Server configuration to validate (in standard MCP format)

        Raises:
            ValueError: If configuration is invalid

        """
        # Determine transport type from config
        # type field is optional for stdio, required and must be "http" for HTTP
        transport_type = config.get("type", "stdio")

        if transport_type == "stdio" or transport_type is None:
            self._validate_stdio_config(config)
        elif transport_type == "http":
            self._validate_http_config(config)
        else:
            raise ValueError(f"Unsupported transport type: {transport_type}. Supported: 'stdio' (default), 'http'")

        # Common validation for both transports
        # Validate env is a dictionary if present
        if "env" in config and not isinstance(config["env"], dict):
            raise ValueError("Environment variables must be a dictionary")

    def _validate_stdio_config(self, config: dict[str, Any]) -> None:
        """Validate stdio transport configuration.

        Args:
            config: Server configuration to validate (in standard MCP format)

        Raises:
            ValueError: If configuration is invalid

        """
        if "command" not in config:
            raise ValueError("stdio configuration requires 'command' field")

        if not config["command"]:
            raise ValueError("Command cannot be empty")

        # Validate args is a list if present
        if "args" in config and not isinstance(config["args"], list):
            raise ValueError("Arguments must be a list")

    def _validate_http_config(self, config: dict[str, Any]) -> None:
        """Validate HTTP transport configuration.

        Args:
            config: Server configuration to validate (in standard MCP format)

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
            raise ValueError("HTTP configuration requires 'url' field")

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

    def parse_standard_mcp_config(self, config_path: Path) -> dict[str, dict[str, Any]]:
        """Parse a standard MCP JSON config file with mcpServers wrapper.

        Standard MCP config format:
        {
            "mcpServers": {
                "server-name": {
                    "command": "node",
                    "args": ["server.js"],
                    "env": {"KEY": "${VALUE}"}
                },
                "http-server": {
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "headers": {"Authorization": "Bearer ${TOKEN}"}
                }
            }
        }

        Args:
            config_path: Path to the MCP config file

        Returns:
            Dictionary of server configurations in standard MCP format

        Raises:
            ValueError: If file format is invalid
            FileNotFoundError: If config file doesn't exist
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {config_path}: {e}") from e

        # Check for mcpServers wrapper
        if "mcpServers" not in data:
            raise ValueError(f"Invalid MCP config format in {config_path}: missing 'mcpServers' key")

        servers = data["mcpServers"]
        if not isinstance(servers, dict):
            raise TypeError(f"Invalid MCP config format in {config_path}: 'mcpServers' must be an object")

        # Validate each server config but keep in standard format
        validated_servers = {}
        for name, config in servers.items():
            try:
                # Just validate, don't convert
                self._validate_standard_config(name, config)
                validated_servers[name] = config
            except Exception as e:
                logger.exception(f"Failed to validate server '{name}' from {config_path}")
                raise ValueError(f"Failed to validate server '{name}': {e}") from e

        return validated_servers

    def _validate_standard_config(self, name: str, config: dict[str, Any]) -> None:
        """Validate a standard MCP server config.

        Args:
            name: Server name
            config: Standard MCP server configuration

        Raises:
            ValueError: If configuration is invalid or unsupported
        """
        # Determine transport type from standard format
        # type field is optional for stdio (absence means stdio)
        # type field must be "http" for HTTP servers
        transport_type = config.get("type", "stdio")

        # Validate based on transport type
        if transport_type == "stdio" or transport_type is None:
            if "command" not in config:
                raise ValueError(f"Server '{name}' requires 'command' field for stdio configuration")
        elif transport_type == "http":
            if "url" not in config:
                raise ValueError(f"Server '{name}' requires 'url' field for HTTP configuration")
        else:
            raise ValueError(
                f"Unsupported type '{transport_type}' for server '{name}'. Supported: 'stdio' (default), 'http'"
            )

    def add_servers_from_file(self, config_path: Path) -> list[str]:
        """Add servers from a standard MCP config file.

        Args:
            config_path: Path to the MCP config file

        Returns:
            List of server names that were added/updated

        Raises:
            ValueError: If file format is invalid
            FileNotFoundError: If config file doesn't exist
        """
        # Parse the standard config
        new_servers = self.parse_standard_mcp_config(config_path)

        # Load existing config
        existing_config = self.load()
        servers = existing_config.get("mcpServers", {})

        # Add/update each server
        added_servers = []

        for name, server_config in new_servers.items():
            # The configs are already in standard format from parse_standard_mcp_config
            # Just validate before adding
            self.validate_server_config(server_config)

            # Add to servers (in standard format, no timestamps)
            is_update = name in servers
            servers[name] = server_config
            added_servers.append(name)

            action = "Updated" if is_update else "Added"
            logger.info(f"{action} server '{name}' from {config_path}")

        # Save the updated configuration
        existing_config["mcpServers"] = servers
        self.save(existing_config)

        return added_servers

    def add_servers_from_config(self, config: dict) -> list[str]:
        """Add servers from a parsed config dictionary.

        Args:
            config: Dictionary with 'mcpServers' key containing server configs

        Returns:
            List of server names that were added/updated

        Raises:
            ValueError: If config format is invalid
        """
        if "mcpServers" not in config:
            raise ValueError("Config must contain 'mcpServers' key")

        new_servers = config["mcpServers"]
        if not isinstance(new_servers, dict):
            raise TypeError("'mcpServers' must be a dictionary")

        # Load existing config
        existing_config = self.load()
        servers = existing_config.get("mcpServers", {})

        # Add/update each server
        added_servers = []

        for name, server_config in new_servers.items():
            # Validate before adding
            self._validate_standard_config(name, server_config)

            # Add to servers
            is_update = name in servers
            servers[name] = server_config
            added_servers.append(name)

            action = "Updated" if is_update else "Added"
            logger.info(f"{action} server '{name}' from JSON input")

        # Save the updated configuration
        existing_config["mcpServers"] = servers
        self.save(existing_config)

        return added_servers
