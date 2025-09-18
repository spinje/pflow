"""Authentication utilities for MCP HTTP transport."""

import base64
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


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
        pattern = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

        def replacer(match: Any) -> str:
            env_var = match.group(1)
            env_value = os.environ.get(env_var, "")
            if not env_value:
                logger.warning(f"Environment variable {env_var} not found, using empty string")
            return env_value

        return pattern.sub(replacer, data)
    else:
        # Return other types unchanged (int, bool, None, etc.)
        return data


def _add_bearer_auth(headers: dict[str, str], auth: dict[str, Any]) -> None:
    """Add Bearer token authentication to headers."""
    token = auth.get("token", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        logger.warning("Bearer auth configured but token is empty")


def _add_api_key_auth(headers: dict[str, str], auth: dict[str, Any]) -> None:
    """Add API key authentication to headers."""
    key = auth.get("key", "")
    header_name = auth.get("header", "X-API-Key")
    if key:
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

    # Validate credentials don't contain control characters that could break HTTP headers
    if any(ord(c) < 32 for c in username) or any(ord(c) < 32 for c in password):
        logger.error("Basic auth credentials contain invalid control characters")
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
        "bearer": _add_bearer_auth,
        "api_key": _add_api_key_auth,
        "basic": _add_basic_auth,
    }

    handler = auth_handlers.get(auth_type)
    if handler:
        handler(headers, auth)
    else:
        logger.warning(f"Unknown auth type: {auth_type}")

    return headers
