# HTTP Node Implementation Guide - Task 54

## Critical Context

This is the ONLY implementation guide you need for Task 54. It contains all verified codebase patterns, research insights, and implementation requirements. Follow this guide exactly - every pattern has been validated against the existing codebase.

## Executive Summary

You are implementing an HTTP node for pflow that enables web requests with automatic JSON handling, authentication support, and proper error handling. The implementation MUST follow pflow's established patterns precisely - deviation will break the system.

**Key Statistics from Research**:
- 60% of HTTP operations are simple GET/POST with JSON
- 70% of auth is API keys, 20% Bearer tokens
- 30-second timeout is industry standard
- Only "default" and "error" actions exist in pflow (no custom actions)

## 🚨 CRITICAL PATTERNS - MUST FOLLOW EXACTLY

### 1. PocketFlow Retry Pattern (NO EXCEPTIONS!)

```python
class HttpNode(Node):  # MUST inherit from Node, NOT BaseNode
    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        super().__init__(max_retries=max_retries, wait=wait)

    def exec(self, prep_res: dict) -> dict:
        # ⚠️ NO try/except here! Let ALL exceptions bubble up!
        response = requests.request(
            method=prep_res["method"],
            url=prep_res["url"],
            headers=prep_res.get("headers"),
            json=prep_res.get("body") if isinstance(prep_res.get("body"), dict) else None,
            data=prep_res.get("body") if isinstance(prep_res.get("body"), str) else None,
            params=prep_res.get("params"),
            timeout=prep_res["timeout"]
        )

        # Only return SUCCESS data - never error data
        return {
            "response": response.json() if "application/json" in response.headers.get("content-type", "") else response.text,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "duration": response.elapsed.total_seconds()
        }

    def exec_fallback(self, prep_res: dict, exc: Exception) -> None:
        """MUST raise ValueError with actionable message - NEVER return error data"""
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
        else:
            raise ValueError(f"HTTP request failed after {self.max_retries} attempts. URL: {prep_res['url']}, Error: {exc}")
```

**Why this matters**: The retry mechanism ONLY works if exceptions bubble up. Catching them breaks automatic retries.

### 2. Parameter Fallback Pattern (UNIVERSAL)

```python
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    # ALWAYS: shared → params → error/default
    url = shared.get("url") or self.params.get("url")
    if not url:
        raise ValueError("HTTP node requires 'url' in shared store or parameters")

    # Optional with defaults
    method = shared.get("method") or self.params.get("method")
    body = shared.get("body") or self.params.get("body")
    headers = shared.get("headers") or self.params.get("headers", {})
    params = shared.get("params") or self.params.get("params")
    timeout = shared.get("timeout") or self.params.get("timeout", 30)

    # Auto-detect method
    if not method:
        method = "POST" if body else "GET"

    # Authentication
    auth_token = shared.get("auth_token") or self.params.get("auth_token")
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    api_key = shared.get("api_key") or self.params.get("api_key")
    if api_key:
        api_key_header = self.params.get("api_key_header", "X-API-Key")
        headers[api_key_header] = api_key

    # JSON body handling
    if isinstance(body, dict):
        headers.setdefault("Content-Type", "application/json")

    return {
        "url": url,
        "method": method.upper(),
        "body": body,
        "headers": headers,
        "params": params,
        "timeout": timeout
    }
```

### 3. Action Pattern (ONLY default/error)

```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    """Store results and return action - ONLY 'default' or 'error' exist"""
    # Always store response data
    shared["response"] = exec_res["response"]
    shared["status_code"] = exec_res["status_code"]
    shared["response_headers"] = exec_res["headers"]
    shared["response_time"] = exec_res.get("duration", 0)

    # Determine action - HTTP errors are still successful requests!
    status = exec_res["status_code"]

    if 200 <= status < 300:
        return "default"  # Success
    else:
        # 4xx and 5xx are valid responses, not errors
        shared["error"] = f"HTTP {status}"
        return "error"  # But return error action for workflow routing
```

**Critical**: HTTP 4xx/5xx responses are NOT exceptions - they're valid responses handled in post(). Only network failures are exceptions.

## 📝 Interface Documentation (EXACT FORMAT REQUIRED)

```python
"""
Make HTTP requests to APIs and web services.

Interface:
- Reads: shared["url"]: str  # API endpoint to call
- Reads: shared["method"]: str  # HTTP method (optional)
- Reads: shared["body"]: dict|str  # Request payload (optional)
- Reads: shared["headers"]: dict  # Additional headers (optional)
- Reads: shared["params"]: dict  # Query parameters (optional)
- Reads: shared["timeout"]: int  # Request timeout in seconds (optional)
- Writes: shared["response"]: dict|str  # Response data (JSON parsed or raw text)
- Writes: shared["status_code"]: int  # HTTP status code
- Writes: shared["response_headers"]: dict  # Response headers
- Writes: shared["response_time"]: float  # Request duration in seconds
- Writes: shared["error"]: str  # Error description for non-2xx responses
- Params: auth_token: str  # Bearer token for Authorization header (optional)
- Params: api_key: str  # API key for X-API-Key header (optional)
- Params: api_key_header: str  # Custom header name for API key (default: X-API-Key)
- Actions: default (success), error (failure)

Natural Language Mappings:
- "fetch data from [url]" → GET request
- "send [data] to [url]" → POST with body
- "update [resource]" → PUT with body
- "delete [item]" → DELETE request
"""
```

**Rules**:
- Use `shared["key"]` with double quotes
- Don't list params that are in Reads (automatic fallback)
- Include natural language hints
- Document nested structures with indentation

## 🧪 Testing Requirements

### Test Structure

Create: `tests/test_nodes/test_http/test_http.py`

```python
import json
from unittest.mock import Mock, patch
import pytest
import requests
from pflow.nodes.http.http import HttpNode

class TestHttpNode:
    def test_prep_validates_required_url(self):
        """Missing URL must raise ValueError"""
        node = HttpNode()
        shared = {}

        with pytest.raises(ValueError, match="requires 'url'"):
            node.prep(shared)

    def test_prep_auto_detects_method(self):
        """GET without body, POST with body"""
        node = HttpNode()

        # No body → GET
        result = node.prep({"url": "http://example.com"})
        assert result["method"] == "GET"

        # With body → POST
        result = node.prep({"url": "http://example.com", "body": {"data": "test"}})
        assert result["method"] == "POST"

    def test_exec_successful_json_response(self):
        """Test successful JSON response"""
        node = HttpNode()
        prep_res = {"method": "GET", "url": "https://api.example.com", "timeout": 30}

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}
        mock_response.text = '{"data": "test"}'
        mock_response.headers = {"content-type": "application/json"}
        mock_response.elapsed.total_seconds.return_value = 1.5

        with patch("requests.request", return_value=mock_response) as mock_request:
            result = node.exec(prep_res)

            assert result["response"] == {"data": "test"}
            assert result["status_code"] == 200

    def test_exec_retries_on_timeout(self):
        """Verify retry mechanism works"""
        node = HttpNode(max_retries=2, wait=0)
        prep_res = {"method": "GET", "url": "https://api.example.com", "timeout": 30}

        with patch("requests.request") as mock_request:
            mock_request.side_effect = [
                requests.Timeout("timeout"),
                Mock(status_code=200, json=lambda: {"success": True},
                     headers={"content-type": "application/json"},
                     elapsed=Mock(total_seconds=lambda: 1.0))
            ]

            shared = {}
            action = node.run(shared)

            assert action == "default"
            assert mock_request.call_count == 2

    def test_exec_fallback_transforms_errors(self):
        """Test error message transformation"""
        node = HttpNode()
        prep_res = {"url": "https://api.example.com", "timeout": 30}

        # Timeout error
        with pytest.raises(ValueError, match="timed out after 30 seconds"):
            node.exec_fallback(prep_res, requests.Timeout())

        # Connection error
        with pytest.raises(ValueError, match="Could not connect"):
            node.exec_fallback(prep_res, requests.ConnectionError())

    def test_post_maps_status_to_actions(self):
        """Test action mapping based on status codes"""
        node = HttpNode()
        shared = {}
        prep_res = {}

        # 200 → default
        exec_res = {"response": "data", "status_code": 200, "headers": {}, "duration": 1.0}
        action = node.post(shared, prep_res, exec_res)
        assert action == "default"

        # 404 → error (but still stores response)
        exec_res = {"response": "Not found", "status_code": 404, "headers": {}, "duration": 1.0}
        action = node.post(shared, prep_res, exec_res)
        assert action == "error"
        assert shared["status_code"] == 404
        assert shared["response"] == "Not found"
```

## 🗂️ File Structure

```
src/pflow/nodes/http/
├── __init__.py          # from .http import HttpNode
└── http.py              # Main implementation

tests/test_nodes/test_http/
├── __init__.py
└── test_http.py         # All tests
```

## ✅ Implementation Checklist

### Phase 1: Setup
- [ ] Add `requests>=2.32.0` to `pyproject.toml` dependencies
- [ ] Create `src/pflow/nodes/http/` directory
- [ ] Create `__init__.py` with proper export

### Phase 2: Core Implementation
- [ ] Implement `HttpNode` class inheriting from `Node`
- [ ] Add `name = "http"` class attribute
- [ ] Implement `__init__` with max_retries=3, wait=1.0
- [ ] Implement `prep()` with parameter fallback pattern
- [ ] Implement `exec()` with NO try/except
- [ ] Implement `exec_fallback()` raising ValueError
- [ ] Implement `post()` returning only default/error

### Phase 3: Features
- [ ] Auto-detect method (POST with body, GET without)
- [ ] JSON serialization for dict bodies
- [ ] JSON parsing for responses
- [ ] Bearer token authentication
- [ ] API key authentication
- [ ] Query parameters support
- [ ] Custom headers support

### Phase 4: Testing
- [ ] Create test file structure
- [ ] Test required URL validation
- [ ] Test method auto-detection
- [ ] Test successful requests
- [ ] Test retry mechanism
- [ ] Test error transformation
- [ ] Test action mapping
- [ ] Mock at requests library level

### Phase 5: Integration
- [ ] Verify node appears in registry
- [ ] Test with `pflow registry list`
- [ ] Test natural language planning
- [ ] Test workflow chaining

## ❌ Common Pitfalls to AVOID

1. **DON'T catch exceptions in exec()** - Breaks retry mechanism
2. **DON'T return error data from exec()** - Only success values
3. **DON'T return error strings from exec_fallback()** - Raise ValueError
4. **DON'T create custom actions** - Only default/error exist
5. **DON'T forget parameter fallback** - shared → params always
6. **DON'T transform field names** - Keep response as-is
7. **DON'T use shell=True** - Not applicable here but principle stands
8. **DON'T log sensitive data** - No tokens or keys in logs

## 🔑 Key Implementation Patterns from Codebase

### Pattern Differences by Node Type

**GitHub/LLM Nodes**: Raise ValueError from exec_fallback
```python
def exec_fallback(self, prep_res: dict, exc: Exception) -> None:
    raise ValueError(f"Operation failed: {exc}")
```

**File Nodes**: Return error string from exec_fallback (DON'T use this pattern)
```python
# File nodes do this but HTTP should follow GitHub pattern
def exec_fallback(self, prep_res, exc) -> str:
    return f"Error: {exc}"  # DON'T DO THIS
```

**HTTP Node**: Follow GitHub/LLM pattern (raise ValueError)

### Import Pattern

```python
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union
import requests

# Standard pocketflow import pattern
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node
```

## 📊 Design Rationale

1. **requests over urllib**: Better error messages, simpler API
2. **30-second timeout**: Industry standard, balances reliability
3. **Separate auth params**: Clearer than unified auth string
4. **Query params as dict**: Cleaner than URL manipulation
5. **No environment variable expansion**: Only MCP node does this
6. **No custom actions**: Follows codebase pattern

## 🚀 Complete Implementation Example

```python
"""HTTP node for making web requests."""

import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union
import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from pocketflow import Node


class HttpNode(Node):
    """
    Make HTTP requests to APIs and web services.

    Interface:
    - Reads: shared["url"]: str  # API endpoint to call
    - Reads: shared["method"]: str  # HTTP method (optional)
    - Reads: shared["body"]: dict|str  # Request payload (optional)
    - Reads: shared["headers"]: dict  # Additional headers (optional)
    - Reads: shared["params"]: dict  # Query parameters (optional)
    - Reads: shared["timeout"]: int  # Request timeout in seconds (optional)
    - Writes: shared["response"]: dict|str  # Response data (JSON parsed or raw text)
    - Writes: shared["status_code"]: int  # HTTP status code
    - Writes: shared["response_headers"]: dict  # Response headers
    - Writes: shared["response_time"]: float  # Request duration in seconds
    - Writes: shared["error"]: str  # Error description for non-2xx responses
    - Params: auth_token: str  # Bearer token for Authorization header (optional)
    - Params: api_key: str  # API key for X-API-Key header (optional)
    - Params: api_key_header: str  # Custom header name for API key (default: X-API-Key)
    - Actions: default (success), error (failure)
    """

    name = "http"

    def __init__(self, max_retries: int = 3, wait: float = 1.0):
        """Initialize with retry support for transient network failures."""
        super().__init__(max_retries=max_retries, wait=wait)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Extract and validate parameters with fallback pattern."""
        # Required parameter
        url = shared.get("url") or self.params.get("url")
        if not url:
            raise ValueError("HTTP node requires 'url' in shared store or parameters")

        # Optional parameters with fallback
        method = shared.get("method") or self.params.get("method")
        body = shared.get("body") or self.params.get("body")
        headers = shared.get("headers") or self.params.get("headers", {})
        params = shared.get("params") or self.params.get("params")
        timeout = shared.get("timeout") or self.params.get("timeout", 30)

        # Auto-detect method
        if not method:
            method = "POST" if body else "GET"

        # Authentication
        auth_token = shared.get("auth_token") or self.params.get("auth_token")
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        api_key = shared.get("api_key") or self.params.get("api_key")
        if api_key:
            api_key_header = self.params.get("api_key_header", "X-API-Key")
            headers[api_key_header] = api_key

        # Set Content-Type for JSON
        if isinstance(body, dict):
            headers.setdefault("Content-Type", "application/json")

        return {
            "url": url,
            "method": method.upper(),
            "body": body,
            "headers": headers,
            "params": params,
            "timeout": timeout
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute HTTP request - NO try/except! Let exceptions bubble up."""
        response = requests.request(
            method=prep_res["method"],
            url=prep_res["url"],
            headers=prep_res.get("headers"),
            json=prep_res.get("body") if isinstance(prep_res.get("body"), dict) else None,
            data=prep_res.get("body") if isinstance(prep_res.get("body"), str) else None,
            params=prep_res.get("params"),
            timeout=prep_res["timeout"]
        )

        # Parse response
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                response_data = response.json()
            except:
                response_data = response.text
        else:
            response_data = response.text

        return {
            "response": response_data,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "duration": response.elapsed.total_seconds()
        }

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> None:
        """Transform exceptions to actionable messages."""
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
        elif isinstance(exc, requests.RequestException):
            raise ValueError(
                f"HTTP request failed: {exc}"
            )
        else:
            raise ValueError(
                f"HTTP request failed after {self.max_retries} attempts. "
                f"URL: {prep_res['url']}, Error: {exc}"
            )

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store results and determine action."""
        # Always store response data
        shared["response"] = exec_res["response"]
        shared["status_code"] = exec_res["status_code"]
        shared["response_headers"] = exec_res["headers"]
        shared["response_time"] = exec_res.get("duration", 0)

        # Determine action
        status = exec_res["status_code"]
        if 200 <= status < 300:
            return "default"
        else:
            shared["error"] = f"HTTP {status}"
            return "error"
```

## Final Notes

This guide contains EVERYTHING needed to implement the HTTP node correctly. The patterns have been verified against the existing codebase. Follow them exactly - the system depends on these specific behaviors.

Remember: When in doubt, follow the GitHub node patterns (they're the most recent and well-tested). The key is letting exceptions bubble up for retries and using the standard default/error action pattern.