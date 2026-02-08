"""Authentication utilities for MCP HTTP transport."""

import base64
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Compile regex pattern once for performance
# Updated to support ${VAR} and ${VAR:-default} syntax
# Accepts both uppercase and lowercase variable names
ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

# Authentication type constants
AUTH_TYPE_BEARER = "bearer"
AUTH_TYPE_API_KEY = "api_key"
AUTH_TYPE_BASIC = "basic"
DEFAULT_API_KEY_HEADER = "X-API-Key"


def expand_env_vars_nested(  # noqa: C901
    data: Any,
    *,
    include_settings: bool = False,
    raise_on_missing: bool = False,
) -> Any:
    """Recursively expand environment variables in nested structures.

    Supports expansion from both process environment (os.environ) and
    settings.json (where `pflow settings set-env` stores values).

    Args:
        data: Any data structure potentially containing ${VAR} references
        include_settings: If True, check settings.json in addition to os.environ
        raise_on_missing: If True, raise ValueError instead of returning empty string
                         for missing variables (only applies when no default is provided)

    Returns:
        Data with all environment variables expanded

    Raises:
        ValueError: If raise_on_missing=True and variables are missing

    Examples:
        Basic usage (backward compatible):
        >>> expand_env_vars_nested("${HOME}/path")
        "/Users/john/path"

        With settings.json support:
        >>> expand_env_vars_nested(
        ...     {"token": "${API_KEY}"},
        ...     include_settings=True
        ... )
        {"token": "value-from-settings"}

        With error raising:
        >>> expand_env_vars_nested(
        ...     "${MISSING_VAR}",
        ...     raise_on_missing=True
        ... )
        ValueError: Missing environment variable(s): MISSING_VAR
    """
    # Load settings.json if requested (import inside function to avoid circular deps)
    settings_env: dict[str, str] = {}
    if include_settings:
        try:
            from pflow.core.settings import SettingsManager

            settings = SettingsManager()
            settings_env = settings.list_env(mask_values=False)
        except Exception as e:
            # Log warning but continue with empty settings dict
            logger.warning(f"Failed to load settings env vars: {e}")
            settings_env = {}

    # Track missing variables for error reporting
    missing_vars: set[str] = set()

    def get_variable(var_name: str) -> str | None:
        """Get variable from environment or settings (case-insensitive for settings)."""
        # Check process environment first (case-sensitive)
        if var_name in os.environ:
            return os.environ[var_name]

        # Check settings.json (case-insensitive fallback)
        # This handles both ${REPLICATE_API_TOKEN} and ${replicate_api_token}
        if include_settings:
            for key, value in settings_env.items():
                if key.lower() == var_name.lower():
                    return value

        return None

    def expand_value(value: Any) -> Any:
        """Recursively expand variables in nested structures."""
        if isinstance(value, dict):
            # Recursively process dictionary values
            return {key: expand_value(val) for key, val in value.items()}
        elif isinstance(value, list):
            # Recursively process list items
            return [expand_value(item) for item in value]
        elif isinstance(value, str):
            # Expand environment variables in strings
            def replacer(match: Any) -> str:
                var_name = match.group(1)
                default_value = match.group(2)  # Will be None if no default specified

                var_value = get_variable(var_name)

                if var_value is not None:
                    return var_value
                elif default_value is not None:
                    # Use the default value if provided
                    return str(default_value)
                else:
                    # No value and no default
                    if raise_on_missing:
                        # Track for error reporting
                        missing_vars.add(var_name)
                        return ""
                    else:
                        # Log warning and use empty string (backward compatible)
                        logger.warning(f"Environment variable {var_name} not found, using empty string")
                        return ""

            return ENV_VAR_PATTERN.sub(replacer, value)
        else:
            # Return other types unchanged (int, bool, None, etc.)
            return value

    # Expand all variables
    result = expand_value(data)

    # If any variables were missing and raise_on_missing=True, raise a helpful error
    if raise_on_missing and missing_vars:
        var_list = ", ".join(sorted(missing_vars))
        first_var = next(iter(missing_vars))
        raise ValueError(
            f"Missing environment variable(s): {var_list}\n\n"
            f"To set these variables, use one of:\n"
            f"  • pflow settings set-env {first_var}=your_value\n"
            f"  • export {first_var}=your_value"
        )

    return result


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

    Note: Env var expansion (${VAR}) should be done by the caller before
    passing config to this function. This function builds headers from
    already-resolved values.

    Args:
        config: Server configuration dictionary (env vars already expanded)

    Returns:
        Dictionary of HTTP headers including authentication
    """
    headers = {}

    # Add custom headers if provided (already expanded by caller)
    if "headers" in config:
        raw_headers = config["headers"]
        if isinstance(raw_headers, dict):
            headers.update(raw_headers)

    # Handle authentication (already expanded by caller)
    auth = config.get("auth", {})
    if not auth:
        return headers

    if not isinstance(auth, dict):
        logger.warning("Auth config is not a dictionary")
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
