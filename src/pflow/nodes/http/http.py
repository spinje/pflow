"""HTTP node for making web requests."""

import base64
import json
from typing import Any

import requests

from pflow.pocketflow import Node


class HttpNode(Node):
    """
    Make HTTP requests to APIs and web services.

    Interface:
    - Params: url: str  # API endpoint to call
    - Params: method: str  # HTTP method (optional)
    - Params: body: dict|str  # Request payload (optional)
    - Params: headers: dict  # Additional headers (optional)
    - Params: params: dict  # Query parameters (optional)
    - Params: timeout: int  # Request timeout in seconds (optional)
    - Writes: shared["response"]: dict|str  # Response data (JSON parsed, raw text, or base64-encoded binary)
    - Writes: shared["response_is_binary"]: bool  # True if response is binary data
    - Writes: shared["status_code"]: int  # HTTP status code
    - Writes: shared["response_headers"]: dict  # Response headers
    - Writes: shared["response_time"]: float  # Request duration in seconds
    - Writes: shared["error"]: str  # Error description for non-2xx responses
    - Params: auth_token: str  # Bearer token for Authorization header (optional, mutually exclusive with api_key)
    - Params: api_key: str  # API key for X-API-Key header (optional, mutually exclusive with auth_token)
    - Params: api_key_header: str  # Custom header name for API key (default: X-API-Key, params only)
    - Actions: default (success), error (failure)

    Natural Language Mappings:
    - "fetch data from [url]" → GET request
    - "send [data] to [url]" → POST with body
    - "update [resource]" → PUT with body
    - "delete [item]" → DELETE request
    """

    name = "http"  # CRITICAL: Required for registry discovery

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        """Initialize with retry support for transient network failures."""
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:  # noqa: C901
        """Extract and validate HTTP request parameters."""
        # Required parameter
        url = self.params.get("url")
        if not url:
            raise ValueError("HTTP node requires 'url' parameter")

        # Optional parameters
        method = self.params.get("method")
        body = self.params.get("body")

        # Headers: copy to avoid mutating caller's dict
        base_headers = self.params.get("headers", {})
        headers = dict(base_headers) if base_headers else {}

        # Query parameters
        params = self.params.get("params")

        # Timeout with validation
        raw_timeout = self.params.get("timeout", 30)
        if raw_timeout is None:
            timeout = 30  # Default timeout
        else:
            try:
                timeout = int(raw_timeout)
            except (TypeError, ValueError):
                raise ValueError(f"Timeout must be a positive integer, got: {raw_timeout}") from None
        if timeout <= 0:
            raise ValueError(f"Timeout must be a positive integer, got: {timeout}")

        # Auto-detect method
        if not method:
            method = "POST" if body else "GET"

        # Validate method
        method = method.upper()
        valid_methods = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}
        if method not in valid_methods:
            raise ValueError(f"Invalid HTTP method '{method}'. Allowed: {', '.join(sorted(valid_methods))}")

        # Authentication - check for mutual exclusivity per spec
        auth_token = self.params.get("auth_token")
        api_key = self.params.get("api_key")

        if auth_token and api_key:
            raise ValueError("Cannot specify both auth_token and api_key - they are mutually exclusive")

        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        if api_key:
            api_key_header = self.params.get("api_key_header", "X-API-Key")
            headers[api_key_header] = api_key

        # Set Content-Type for JSON
        if isinstance(body, dict):
            headers.setdefault("Content-Type", "application/json")

        return {
            "url": url,
            "method": method,  # Already uppercased above
            "body": body,
            "headers": headers,
            "params": params,
            "timeout": timeout,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute HTTP request - NO try/except! Let exceptions bubble up."""
        # Make the request - NO try/except! Let exceptions bubble up for retry mechanism
        response = requests.request(
            method=prep_res["method"],
            url=prep_res["url"],
            headers=prep_res.get("headers"),
            json=prep_res.get("body") if isinstance(prep_res.get("body"), dict) else None,
            data=prep_res.get("body") if isinstance(prep_res.get("body"), str) else None,
            params=prep_res.get("params"),
            timeout=prep_res["timeout"],
        )

        # Parse response based on Content-Type (handle various JSON content types)
        content_type = response.headers.get("content-type", "").lower()

        # Binary detection
        BINARY_CONTENT_TYPES = [
            "image/",
            "video/",
            "audio/",
            "application/pdf",
            "application/octet-stream",
            "application/zip",
            "application/gzip",
            "application/x-tar",
        ]
        is_binary = any(ct in content_type for ct in BINARY_CONTENT_TYPES)

        # Parse response (priority: binary > json > text)
        if is_binary:
            response_data = response.content  # bytes - DO NOT USE response.text
        elif "json" in content_type:
            try:
                response_data = response.json()
            except (ValueError, json.JSONDecodeError):
                # If JSON parsing fails, return raw text
                response_data = response.text
        else:
            response_data = response.text

        # Return only success data - never error data
        return {
            "response": response_data,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "duration": response.elapsed.total_seconds(),
            "is_binary": is_binary,
        }

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> None:
        """Transform exceptions to actionable messages - MUST raise ValueError."""
        # Transform technical errors to actionable user guidance
        # Note: We use ValueError (not TypeError) to follow the pflow pattern
        # where exec_fallback transforms exceptions into user-friendly error messages
        if isinstance(exc, requests.Timeout):
            raise ValueError(  # noqa: TRY004
                f"Request to {prep_res['url']} timed out after {prep_res['timeout']} seconds. "
                f"Try increasing timeout with --timeout=60 or check if the service is responding."
            )
        elif isinstance(exc, requests.ConnectionError):
            raise ValueError(  # noqa: TRY004
                f"Could not connect to {prep_res['url']}. Please check the URL is correct and the service is running."
            )
        elif isinstance(exc, requests.RequestException):
            raise ValueError(f"HTTP request failed: {exc}")  # noqa: TRY004
        else:
            raise ValueError(  # noqa: TRY004
                f"HTTP request failed after {self.max_retries} attempts. URL: {prep_res['url']}, Error: {exc}"
            )

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store results and determine action."""
        # Handle binary encoding
        response_data = exec_res["response"]
        is_binary = exec_res.get("is_binary", False)

        if is_binary:
            # Encode binary data as base64
            encoded = base64.b64encode(response_data).decode("ascii")
            shared["response"] = encoded
            shared["response_is_binary"] = True
        else:
            # Store text/JSON as-is
            shared["response"] = response_data
            shared["response_is_binary"] = False

        # Store other metadata
        shared["status_code"] = exec_res["status_code"]
        shared["response_headers"] = exec_res["headers"]
        shared["response_time"] = exec_res.get("duration", 0)

        # Determine action based on status code
        status = exec_res["status_code"]
        if 200 <= status < 300:
            return "default"  # Success
        else:
            # HTTP errors are valid responses, not exceptions
            shared["error"] = f"HTTP {status}"
            return "error"  # Return error action for workflow routing
