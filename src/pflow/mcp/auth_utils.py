"""Authentication utilities for MCP HTTP transport."""

import base64
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Compile regex pattern once for performance
ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

# Authentication type constants
AUTH_TYPE_BEARER = "bearer"
AUTH_TYPE_API_KEY = "api_key"
AUTH_TYPE_BASIC = "basic"
DEFAULT_API_KEY_HEADER = "X-API-Key"


def expand_env_vars_nested(data: Any) -> Any:
    """Recursively expand environment variables in nested structures.

    Args:
        data: Any data structure potentially containing ${VAR} references

    Returns:
        Data with all environment variables expanded
    """
    if isinstance(data, dict):
        # Recursively process dictionary values
        return {key: expand_env_vars_nested(value) for key, value in data.items()}
    elif isinstance(data, list):
        # Recursively process list items
        return [expand_env_vars_nested(item) for item in data]
    elif isinstance(data, str):
        # Expand environment variables in strings
        def replacer(match: Any) -> str:
            env_var = match.group(1)
            env_value = os.environ.get(env_var, "")
            if not env_value:
                logger.warning(f"Environment variable {env_var} not found, using empty string")
            return env_value

        return ENV_VAR_PATTERN.sub(replacer, data)
    else:
        # Return other types unchanged (int, bool, None, etc.)
        return data


def _validate_auth_value(value: str, field_name: str) -> bool:
    """Validate authentication values don't contain dangerous characters.

    Prevents header injection attacks by rejecting:
    - Control characters (ASCII < 32)
    - Newline characters (\\n, \\r)
    - Null bytes (\\x00)

    Examples of invalid values:
    - "user\\nInjected-Header: malicious"
    - "pass\\x00word"
    - "token\\rSet-Cookie: stolen"

    Args:
        value: The authentication value to validate
        field_name: Name of the field for error messages

    Returns:
        True if valid, False otherwise
    """
    if any(ord(c) < 32 for c in value):
        logger.error(f"{field_name} contains invalid control characters")
        return False
    if "\n" in value or "\r" in value:
        logger.error(f"{field_name} contains newline characters")
        return False
    return True


def _add_bearer_auth(headers: dict[str, str], auth: dict[str, Any]) -> None:
    """Add Bearer token authentication to headers."""
    token = auth.get("token", "")
    if token:
        if not _validate_auth_value(token, "Bearer token"):
            return
        headers["Authorization"] = f"Bearer {token}"
    else:
        logger.warning("Bearer auth configured but token is empty")


def _add_api_key_auth(headers: dict[str, str], auth: dict[str, Any]) -> None:
    """Add API key authentication to headers."""
    key = auth.get("key", "")
    header_name = auth.get("header", DEFAULT_API_KEY_HEADER)
    if key:
        if not _validate_auth_value(key, "API key"):
            return
        headers[header_name] = key
    else:
        logger.warning("API key auth configured but key is empty")


def _add_basic_auth(headers: dict[str, str], auth: dict[str, Any]) -> None:
    """Add Basic authentication to headers with validation."""
    username = auth.get("username", "")
    password = auth.get("password", "")

    if not username or not password:
        logger.warning("Basic auth configured but username or password is empty")
        return

    # Validate both username and password
    if not _validate_auth_value(username, "Basic auth username"):
        return
    if not _validate_auth_value(password, "Basic auth password"):
        return

    # Colon is technically allowed in passwords but not in username for Basic auth
    if ":" in username:
        logger.warning("Basic auth username contains colon, which may cause issues")

    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    headers["Authorization"] = f"Basic {credentials}"


def build_auth_headers(config: dict[str, Any]) -> dict[str, str]:
    """Build authentication headers from configuration.

    Supports bearer token, API key, and basic auth.

    Args:
        config: Server configuration dictionary

    Returns:
        Dictionary of HTTP headers including authentication
    """
    headers = {}

    # Add custom headers if provided (expand env vars)
    if "headers" in config:
        expanded_headers = expand_env_vars_nested(config["headers"])
        if isinstance(expanded_headers, dict):
            headers.update(expanded_headers)

    # Handle authentication
    auth = config.get("auth", {})
    if not auth:
        return headers

    # Expand environment variables in auth config
    auth = expand_env_vars_nested(auth)
    if not isinstance(auth, dict):
        logger.warning("Auth config is not a dictionary after expansion")
        return headers

    auth_type = auth.get("type")
    if not auth_type:
        return headers

    # Dispatch to appropriate auth handler
    auth_handlers = {
        AUTH_TYPE_BEARER: _add_bearer_auth,
        AUTH_TYPE_API_KEY: _add_api_key_auth,
        AUTH_TYPE_BASIC: _add_basic_auth,
    }

    handler = auth_handlers.get(auth_type)
    if handler:
        handler(headers, auth)
    else:
        logger.warning(f"Unknown auth type: {auth_type}")

    return headers
