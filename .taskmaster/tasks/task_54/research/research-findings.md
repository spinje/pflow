# Research Findings: HTTP Node Implementation Context

## Executive Summary

This document synthesizes comprehensive research into pflow's codebase to establish the correct patterns and approaches for implementing the HTTP node. The research reveals that pflow has mature, consistent patterns for external service integration, error handling, and natural language integration that the HTTP node must follow.

## Critical Discoveries

### 1. External Service Pattern: CLI-First, Not Direct HTTP

**Finding**: GitHub nodes use subprocess with GitHub CLI (`gh`) rather than direct HTTP calls.

**Implication for HTTP Node**: We should use the `requests` library directly for HTTP calls, as there's no equivalent CLI tool for general HTTP operations.

**Pattern Differences**:
- GitHub nodes: `subprocess.run(["gh", "issue", "view"])`
- HTTP node: `requests.request(method, url, **kwargs)`

### 2. Parameter Fallback Pattern is Universal

**Pattern**: `shared.get("key") or self.params.get("key")`

**Implementation Requirements**:
```python
def prep(self, shared: dict) -> dict:
    # Required parameter with error handling
    url = shared.get("url") or self.params.get("url")
    if not url:
        raise ValueError("HTTP node requires 'url' in shared store or parameters")

    # Optional parameters with defaults
    method = shared.get("method") or self.params.get("method")
    timeout = shared.get("timeout") or self.params.get("timeout", 30)

    # Environment variable expansion for sensitive data
    auth_token = shared.get("auth_token") or self.params.get("auth_token")
    if auth_token and auth_token.startswith("${"):
        auth_token = os.path.expandvars(auth_token)
```

### 3. Error Handling Must Follow PocketFlow Retry Pattern

**Critical Pattern Requirements**:
1. **NO try/except in exec()** - Let exceptions bubble up
2. **Use exec_fallback()** for final error handling
3. **Return only success values from exec()**
4. **Check for errors in post()** method

**Correct Implementation**:
```python
def exec(self, prep_res: dict) -> dict:
    # NO try/except here! Let exceptions bubble up
    response = requests.request(
        method=prep_res["method"],
        url=prep_res["url"],
        headers=prep_res.get("headers"),
        json=prep_res.get("body"),
        timeout=prep_res["timeout"]
    )

    # Only return success data
    return {
        "response": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
        "status_code": response.status_code,
        "headers": dict(response.headers)
    }

def exec_fallback(self, prep_res: dict, exc: Exception) -> None:
    """Transform technical errors into actionable user messages."""
    error_msg = str(exc)

    if isinstance(exc, requests.Timeout):
        raise ValueError(
            f"Request to {prep_res['url']} timed out after {prep_res['timeout']} seconds. "
            f"Try increasing timeout with --timeout=60 or check if the service is responding."
        )
    elif isinstance(exc, requests.ConnectionError):
        raise ValueError(
            f"Could not connect to {prep_res['url']}. "
            f"Please check the URL is correct and the service is running."
        )
    elif hasattr(exc, 'response') and exc.response is not None:
        status = exc.response.status_code
        if status == 401:
            raise ValueError(
                f"Authentication failed for {prep_res['url']}. "
                f"Please check your API key or token is valid and has required permissions."
            )
        elif status == 404:
            raise ValueError(f"Resource not found at {prep_res['url']}. Please verify the URL is correct.")
    else:
        raise ValueError(f"HTTP request failed after {self.max_retries} attempts. URL: {prep_res['url']}, Error: {exc}")
```

### 4. Testing Pattern: Mock at Library Level

**Finding**: GitHub nodes mock at subprocess level, not HTTP level.

**HTTP Node Testing Approach**:
```python
# Mock at requests library level
from unittest.mock import Mock, patch

def test_exec_successful_json_response(self):
    node = HttpNode()
    prep_res = {"method": "GET", "url": "https://api.example.com", "timeout": 30}

    # Mock requests.request
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": "test"}
    mock_response.headers = {"content-type": "application/json"}

    with patch("requests.request", return_value=mock_response) as mock_request:
        result = node.exec(prep_res)

        mock_request.assert_called_once_with(
            method="GET",
            url="https://api.example.com",
            headers=None,
            json=None,
            timeout=30
        )
        assert result["response"] == {"data": "test"}
        assert result["status_code"] == 200
```

### 5. Natural Language Integration Requirements

**Interface Documentation Must Include**:
1. Semantic descriptions for natural language mapping
2. Type annotations for all parameters
3. Structure documentation for nested outputs
4. Exclusive params pattern (don't list params already in Reads)

**Required Format**:
```python
"""
Make HTTP requests to APIs and web services.

Interface:
- Reads: shared["url"]: str  # API endpoint to call
- Reads: shared["body"]: dict|str  # Request payload (optional)
- Reads: shared["headers"]: dict  # Additional headers (optional)
- Writes: shared["response"]: dict|str  # Response data (JSON parsed or raw text)
- Writes: shared["status_code"]: int  # HTTP status code
- Writes: shared["response_headers"]: dict  # Response headers
- Writes: shared["response_time"]: float  # Request duration in seconds
- Params: method: str  # HTTP method (default: auto-detect)
- Params: auth_token: str  # Bearer token for Authorization header (optional)
- Params: timeout: int  # Request timeout in seconds (default: 30)
- Actions: success (2xx), client_error (4xx), server_error (5xx), timeout

Natural Language Mappings:
- "fetch data from [url]" → GET request
- "send [data] to [url]" → POST with body
"""
```

## Implementation Guidelines

### 1. Class Structure and Initialization

```python
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union
import requests
from pocketflow import Node

# Add pocketflow to path (standard pattern)
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

class HttpNode(Node):
    """[Interface documentation here]"""

    name = "http"  # Explicit naming for registry

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        """Initialize with retry support for transient network failures."""
        super().__init__(max_retries=max_retries, wait=wait)
```

### 2. Parameter Handling in prep()

```python
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    """Extract and validate parameters with fallback pattern."""
    # Required parameter
    url = shared.get("url") or self.params.get("url")
    if not url:
        raise ValueError("HTTP node requires 'url' in shared store or parameters")

    # Auto-detect method based on body presence
    body = shared.get("body") or self.params.get("body")
    method = shared.get("method") or self.params.get("method")
    if not method:
        method = "POST" if body else "GET"

    # Optional parameters with defaults
    headers = shared.get("headers") or self.params.get("headers", {})
    timeout = shared.get("timeout") or self.params.get("timeout", 30)

    # Authentication handling
    auth_token = shared.get("auth_token") or self.params.get("auth_token")
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    api_key = shared.get("api_key") or self.params.get("api_key")
    if api_key:
        api_key_header = self.params.get("api_key_header", "X-API-Key")
        headers[api_key_header] = api_key

    return {
        "url": url,
        "method": method.upper(),
        "body": body,
        "headers": headers,
        "timeout": timeout
    }
```

### 3. Action Mapping in post()

```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    """Store results and determine action based on status code."""
    # Store response data
    shared["response"] = exec_res["response"]
    shared["status_code"] = exec_res["status_code"]
    shared["response_headers"] = exec_res["headers"]
    shared["response_time"] = exec_res.get("duration", 0)

    # Determine action based on status code
    status = exec_res["status_code"]

    if 200 <= status < 300:
        return "success"
    elif 400 <= status < 500:
        shared["error"] = f"Client error: HTTP {status}"
        return "client_error"
    elif 500 <= status < 600:
        shared["error"] = f"Server error: HTTP {status}"
        return "server_error"
    else:
        shared["error"] = f"Unexpected status: HTTP {status}"
        return "error"
```

### 4. Testing Structure

```python
# tests/test_nodes/test_http/test_http.py

class TestHttpNode:
    def test_prep_validates_required_url(self):
        """Test that missing URL raises error."""

    def test_prep_auto_detects_method(self):
        """Test GET without body, POST with body."""

    def test_exec_makes_successful_request(self):
        """Test successful HTTP request."""

    def test_exec_retries_on_timeout(self):
        """Test retry mechanism for timeouts."""

    def test_exec_fallback_transforms_errors(self):
        """Test error message transformation."""

    def test_post_maps_status_to_actions(self):
        """Test action mapping based on status codes."""
```

## Key Patterns to Follow

### 1. Error Message Pattern
All error messages must be actionable with suggestions:
- ❌ "Request failed"
- ✅ "Request timed out after 30 seconds. Try increasing timeout with --timeout=60"

### 2. Complex Data Storage
Store structured data as native Python dicts:
```python
shared["response"] = response.json()  # Stores dict
shared["response_headers"] = dict(response.headers)  # Convert to dict
```

### 3. Security Considerations
- Never use `shell=True` (not applicable for HTTP, but principle stands)
- Always validate and sanitize URLs
- Never log sensitive data (tokens, keys)
- Use environment variable expansion for credentials

### 4. Natural Language Hints
Include verb mappings in docstring:
- "fetch" → GET
- "send" → POST
- "update" → PUT
- "delete" → DELETE

## Anti-Patterns to Avoid

Based on codebase analysis, avoid these mistakes:

1. **DON'T catch exceptions in exec()** - Breaks retry mechanism
2. **DON'T forget parameter fallback** - Always check shared then params
3. **DON'T use generic error messages** - Be specific and actionable
4. **DON'T list params already in Reads** - Exclusive params pattern
5. **DON'T assume response format** - Check Content-Type header

## Integration Checklist

Before implementation is complete, verify:

- [ ] Node inherits from `pocketflow.Node`
- [ ] Has `name = "http"` class attribute
- [ ] Interface documentation follows enhanced format
- [ ] Parameter fallback pattern used throughout
- [ ] NO try/except in exec() method
- [ ] exec_fallback() provides actionable errors
- [ ] post() maps status codes to actions
- [ ] Tests mock at requests library level
- [ ] Natural language mappings documented
- [ ] Semantic descriptions for all parameters

## Conclusion

The HTTP node implementation must follow pflow's established patterns precisely. The most critical aspects are:
1. PocketFlow retry pattern (no exceptions caught in exec)
2. Parameter fallback (shared → params)
3. Actionable error messages with suggestions
4. Natural language-friendly documentation

These patterns ensure the HTTP node integrates seamlessly with pflow's existing ecosystem while maintaining consistency with other nodes that interact with external services.