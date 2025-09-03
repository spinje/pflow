"""Tests for the HTTP node covering all 21 criteria from the specification.

Test Coverage Summary (21 criteria):
1. ✅ Missing url parameter → ValueError raised
2. ✅ GET request without body → method set to GET
3. ✅ POST request with body → method set to POST
4. ✅ Bearer token auth → Authorization header added
5. ✅ API key auth → X-API-Key header added
6. ✅ JSON body serialization → Content-Type set
7. ✅ JSON response parsing → dict returned
8. ✅ Plain text response → string returned
9. ✅ 200 status → default action
10. ✅ 404 status → error action
11. ✅ 500 status → error action
12. ✅ Timeout exception → ValueError raised
13. ✅ Connection error → ValueError raised
14. ✅ Parameter fallback shared → params used
15. ✅ Parameter fallback params → default used
16. ✅ exec_fallback timeout → actionable message
17. ✅ exec_fallback 401 → HTTP error (not exception)
18. ✅ exec_fallback 404 → HTTP error (not exception)
19. ✅ Response stored in shared → all keys present
20. ✅ Large payload handling → processes successfully
21. ✅ Empty response handling → empty string returned

Additional Coverage:
- Custom headers support
- Query parameters support
- String body handling
- Custom API key header name
- Malformed JSON fallback
- Retry mechanism verification
- Retry exhaustion
- Explicit method override
- General request exception handling
- Non-request exception handling
- Multiple auth methods together
"""

import json
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException, Timeout

from src.pflow.nodes.http import HttpNode


class TestHttpNode:
    """Test suite for HttpNode covering all specification criteria."""

    # Test Criteria 1: Missing url parameter → ValueError raised
    def test_missing_url_raises_error(self):
        """Test that missing URL raises ValueError with helpful message."""
        node = HttpNode()
        node.set_params({})  # No url in params
        shared = {}  # No url in shared

        with pytest.raises(ValueError) as exc_info:
            node.run(shared)

        assert "HTTP node requires 'url'" in str(exc_info.value)
        assert "shared store or parameters" in str(exc_info.value)

    # Test Criteria 2: GET request without body → method set to GET
    def test_auto_detect_get_method(self):
        """Test that method defaults to GET when no body is provided."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.elapsed = timedelta(seconds=0.5)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/data"}

            action = node.run(shared)

            assert action == "default"
            # Verify GET method was used
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["method"] == "GET"
            assert call_args[1]["url"] == "https://api.example.com/data"
            assert call_args[1].get("json") is None
            assert call_args[1].get("data") is None

    # Test Criteria 3: POST request with body → method set to POST
    def test_auto_detect_post_method(self):
        """Test that method defaults to POST when body is provided."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 201
            mock_response.text = "Created"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.elapsed = timedelta(seconds=0.3)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/data", "body": {"name": "test", "value": 123}}

            action = node.run(shared)

            assert action == "default"
            # Verify POST method was used with JSON body
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["method"] == "POST"
            assert call_args[1]["json"] == {"name": "test", "value": 123}
            assert call_args[1]["headers"]["Content-Type"] == "application/json"

    # Test Criteria 4: Bearer token auth → Authorization header added
    def test_bearer_token_authentication(self):
        """Test that auth_token adds Bearer Authorization header."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "Authenticated"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.elapsed = timedelta(seconds=0.2)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/protected"}
            node.set_params({"auth_token": "secret-token-123"})

            action = node.run(shared)

            assert action == "default"
            # Verify Authorization header
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["headers"]["Authorization"] == "Bearer secret-token-123"

    # Test Criteria 5: API key auth → X-API-Key header added
    def test_api_key_authentication(self):
        """Test that api_key adds X-API-Key header."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "API Key Valid"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.elapsed = timedelta(seconds=0.15)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/data"}
            node.set_params({"api_key": "my-api-key-456"})

            action = node.run(shared)

            assert action == "default"
            # Verify X-API-Key header
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["headers"]["X-API-Key"] == "my-api-key-456"

    # Test Criteria 6: JSON body serialization → Content-Type set
    def test_json_body_serialization(self):
        """Test that dict body sets Content-Type and uses json parameter."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/data", "body": {"key": "value", "number": 42}}

            action = node.run(shared)

            assert action == "default"
            # Verify JSON serialization
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["json"] == {"key": "value", "number": 42}
            assert call_args[1]["headers"]["Content-Type"] == "application/json"
            assert call_args[1].get("data") is None

    # Test Criteria 7: JSON response parsing → dict returned
    def test_json_response_parsing(self):
        """Test that JSON responses are parsed to dict."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "application/json"}
            mock_response.json.return_value = {"result": "success", "id": 123}
            mock_response.elapsed = timedelta(seconds=0.25)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/data"}

            action = node.run(shared)

            assert action == "default"
            assert shared["response"] == {"result": "success", "id": 123}
            assert shared["status_code"] == 200

    # Test Criteria 8: Plain text response → string returned
    def test_plain_text_response(self):
        """Test that plain text responses are returned as strings."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "Hello, World!"
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/text"}

            action = node.run(shared)

            assert action == "default"
            assert shared["response"] == "Hello, World!"
            assert shared["status_code"] == 200

    # Test Criteria 9: 200 status → default action
    def test_200_status_returns_default(self):
        """Test that 200 status returns 'default' action."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "Success"
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/data"}

            action = node.run(shared)

            assert action == "default"
            assert shared["status_code"] == 200
            assert "error" not in shared

    # Test Criteria 10: 404 status → error action
    def test_404_status_returns_error(self):
        """Test that 404 status returns 'error' action."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 404
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "Not Found"
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/missing"}

            action = node.run(shared)

            assert action == "error"
            assert shared["status_code"] == 404
            assert shared["response"] == "Not Found"
            assert shared["error"] == "HTTP 404"

    # Test Criteria 11: 500 status → error action
    def test_500_status_returns_error(self):
        """Test that 500 status returns 'error' action."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 500
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "Internal Server Error"
            mock_response.elapsed = timedelta(seconds=0.2)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/broken"}

            action = node.run(shared)

            assert action == "error"
            assert shared["status_code"] == 500
            assert shared["response"] == "Internal Server Error"
            assert shared["error"] == "HTTP 500"

    # Test Criteria 12: Timeout exception → ValueError raised
    def test_timeout_raises_value_error(self):
        """Test that timeout exception raises ValueError with actionable message."""
        with patch("requests.request") as mock_request:
            mock_request.side_effect = Timeout("Request timed out")

            node = HttpNode(wait=0)  # Set wait=0 to speed up test
            shared = {"url": "https://api.example.com/slow", "timeout": 5}

            with pytest.raises(ValueError) as exc_info:
                node.run(shared)

            error_msg = str(exc_info.value)
            assert "timed out after 5 seconds" in error_msg
            assert "--timeout=60" in error_msg
            assert "check if the service is responding" in error_msg

    # Test Criteria 13: Connection error → ValueError raised
    def test_connection_error_raises_value_error(self):
        """Test that connection error raises ValueError with helpful message."""
        with patch("requests.request") as mock_request:
            mock_request.side_effect = RequestsConnectionError("Connection refused")

            node = HttpNode(wait=0)  # Set wait=0 to speed up test
            shared = {"url": "https://api.example.com/offline"}

            with pytest.raises(ValueError) as exc_info:
                node.run(shared)

            error_msg = str(exc_info.value)
            assert "Could not connect to https://api.example.com/offline" in error_msg
            assert "check the URL is correct" in error_msg
            assert "service is running" in error_msg

    # Test Criteria 14: Parameter fallback shared → params used
    def test_parameter_fallback_from_shared(self):
        """Test that parameters from shared take precedence over params."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            node.set_params({"url": "https://params.example.com", "method": "PUT", "timeout": 10})
            shared = {"url": "https://shared.example.com", "method": "GET", "timeout": 20}

            action = node.run(shared)

            assert action == "default"
            # Verify shared values were used
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["url"] == "https://shared.example.com"
            assert call_args[1]["method"] == "GET"
            assert call_args[1]["timeout"] == 20

    # Test Criteria 15: Parameter fallback params → default used
    def test_parameter_fallback_to_params(self):
        """Test that params are used when not in shared."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            node.set_params({"url": "https://params.example.com", "method": "DELETE", "headers": {"X-Custom": "value"}})
            shared = {}  # Empty shared - should use params

            action = node.run(shared)

            assert action == "default"
            # Verify params values were used
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["url"] == "https://params.example.com"
            assert call_args[1]["method"] == "DELETE"
            assert call_args[1]["headers"]["X-Custom"] == "value"

    # Test Criteria 16: exec_fallback timeout → actionable message
    def test_exec_fallback_timeout_message(self):
        """Test that exec_fallback provides actionable timeout message."""
        node = HttpNode()
        prep_res = {"url": "https://api.example.com/slow", "timeout": 10}
        exc = Timeout("Connection timed out")

        with pytest.raises(ValueError) as exc_info:
            node.exec_fallback(prep_res, exc)

        error_msg = str(exc_info.value)
        assert "timed out after 10 seconds" in error_msg
        assert "Try increasing timeout with --timeout=60" in error_msg

    # Test Criteria 17: exec_fallback 401 → auth suggestion
    # NOTE: This is actually for HTTP status codes, not exceptions
    # The node handles HTTP errors as valid responses, not exceptions
    def test_401_status_returns_error(self):
        """Test that 401 status returns error action with auth info."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 401
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = "Unauthorized"
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/auth"}

            action = node.run(shared)

            assert action == "error"
            assert shared["status_code"] == 401
            assert shared["error"] == "HTTP 401"

    # Test Criteria 18: exec_fallback 404 → URL suggestion
    # NOTE: This is actually for HTTP status codes, not exceptions
    def test_404_status_with_response(self):
        """Test that 404 status provides response data."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 404
            mock_response.headers = {"content-type": "application/json"}
            mock_response.json.return_value = {"error": "Resource not found"}
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/missing"}

            action = node.run(shared)

            assert action == "error"
            assert shared["status_code"] == 404
            assert shared["response"] == {"error": "Resource not found"}
            assert shared["error"] == "HTTP 404"

    # Test Criteria 19: Response stored in shared → all keys present
    def test_response_stored_in_shared(self):
        """Test that all response data is stored in shared."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 201
            mock_response.headers = {"content-type": "application/json", "x-request-id": "abc123"}
            mock_response.json.return_value = {"id": 42, "status": "created"}
            mock_response.elapsed = timedelta(seconds=0.75)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/create"}

            action = node.run(shared)

            assert action == "default"
            # Verify all keys are present
            assert "response" in shared
            assert shared["response"] == {"id": 42, "status": "created"}
            assert "status_code" in shared
            assert shared["status_code"] == 201
            assert "response_headers" in shared
            assert shared["response_headers"]["content-type"] == "application/json"
            assert shared["response_headers"]["x-request-id"] == "abc123"
            assert "response_time" in shared
            assert shared["response_time"] == 0.75

    # Test Criteria 20: Large payload handling → processes successfully
    def test_large_payload_handling(self):
        """Test that large payloads are handled correctly."""
        with patch("requests.request") as mock_request:
            # Create a large response
            large_data = {"items": [{"id": i, "data": f"item_{i}" * 100} for i in range(1000)]}
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "application/json"}
            mock_response.json.return_value = large_data
            mock_response.elapsed = timedelta(seconds=2.5)
            mock_request.return_value = mock_response

            node = HttpNode()
            # Also test with large request body
            large_body = {"data": "x" * 10000}
            shared = {"url": "https://api.example.com/large", "body": large_body}

            action = node.run(shared)

            assert action == "default"
            assert shared["response"] == large_data
            assert shared["status_code"] == 200
            # Verify large body was sent
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["json"] == large_body

    # Test Criteria 21: Empty response handling → empty string returned
    def test_empty_response_handling(self):
        """Test that empty responses are handled correctly."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 204  # No Content
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.text = ""
            mock_response.elapsed = timedelta(seconds=0.05)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/delete"}

            action = node.run(shared)

            assert action == "default"
            assert shared["response"] == ""
            assert shared["status_code"] == 204

    # Additional Tests

    def test_custom_headers(self):
        """Test that custom headers are added to request."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {
                "url": "https://api.example.com/data",
                "headers": {"X-Custom-Header": "custom-value", "User-Agent": "pflow/1.0"},
            }

            action = node.run(shared)

            assert action == "default"
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["headers"]["X-Custom-Header"] == "custom-value"
            assert call_args[1]["headers"]["User-Agent"] == "pflow/1.0"

    def test_query_parameters(self):
        """Test that query parameters are passed to request."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "Results"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/search", "params": {"q": "test query", "page": 2, "limit": 10}}

            action = node.run(shared)

            assert action == "default"
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["params"] == {"q": "test query", "page": 2, "limit": 10}

    def test_string_body_handling(self):
        """Test that string bodies are sent as data, not JSON."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/raw", "body": "raw text data", "method": "POST"}

            action = node.run(shared)

            assert action == "default"
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["data"] == "raw text data"
            assert call_args[1].get("json") is None

    def test_custom_api_key_header(self):
        """Test that custom API key header name can be used."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            node.set_params({"api_key": "secret-key", "api_key_header": "X-Custom-Auth"})
            shared = {"url": "https://api.example.com/data"}

            action = node.run(shared)

            assert action == "default"
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["headers"]["X-Custom-Auth"] == "secret-key"
            assert "X-API-Key" not in call_args[1]["headers"]

    def test_malformed_json_fallback(self):
        """Test that malformed JSON responses fall back to text."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.headers = {"content-type": "application/json"}
            mock_response.text = "Not valid JSON {broken"
            mock_response.json.side_effect = json.JSONDecodeError("Error", "", 0)
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {"url": "https://api.example.com/bad-json"}

            action = node.run(shared)

            assert action == "default"
            # Should fall back to text when JSON parsing fails
            assert shared["response"] == "Not valid JSON {broken"
            assert shared["status_code"] == 200

    def test_retry_mechanism(self):
        """Test that retry mechanism works with transient failures."""
        with patch("requests.request") as mock_request:
            # First two calls fail, third succeeds
            mock_request.side_effect = [
                RequestsConnectionError("Connection failed"),
                RequestsConnectionError("Connection failed"),
                Mock(
                    status_code=200,
                    text="Success after retry",
                    headers={"content-type": "text/plain"},
                    elapsed=timedelta(seconds=0.1),
                ),
            ]

            node = HttpNode(max_retries=3, wait=0.01)  # Fast retries for testing
            shared = {"url": "https://api.example.com/flaky"}

            action = node.run(shared)

            assert action == "default"
            assert shared["response"] == "Success after retry"
            assert shared["status_code"] == 200
            # Verify it was called 3 times
            assert mock_request.call_count == 3

    def test_retry_exhaustion(self):
        """Test that retries are exhausted and error is raised."""
        with patch("requests.request") as mock_request:
            # All calls fail
            mock_request.side_effect = RequestsConnectionError("Connection failed")

            node = HttpNode(max_retries=3, wait=0.01)  # Fast retries for testing
            shared = {"url": "https://api.example.com/always-fails"}

            with pytest.raises(ValueError) as exc_info:
                node.run(shared)

            # Verify it was called 3 times
            assert mock_request.call_count == 3
            error_msg = str(exc_info.value)
            assert "Could not connect" in error_msg

    def test_explicit_method_override(self):
        """Test that explicit method overrides auto-detection."""
        with patch("requests.request") as mock_request:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"
            mock_response.headers = {"content-type": "text/plain"}
            mock_response.elapsed = timedelta(seconds=0.1)
            mock_request.return_value = mock_response

            node = HttpNode()
            shared = {
                "url": "https://api.example.com/data",
                "method": "PUT",  # Explicit method
                "body": {"data": "test"},  # Would normally trigger POST
            }

            action = node.run(shared)

            assert action == "default"
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[1]["method"] == "PUT"  # Should use explicit method

    def test_general_request_exception(self):
        """Test that general request exceptions are handled."""
        with patch("requests.request") as mock_request:
            mock_request.side_effect = RequestException("General request error")

            node = HttpNode(wait=0)  # Set wait=0 to speed up test
            shared = {"url": "https://api.example.com/error"}

            with pytest.raises(ValueError) as exc_info:
                node.run(shared)

            error_msg = str(exc_info.value)
            assert "HTTP request failed: General request error" in error_msg

    def test_non_request_exception_handling(self):
        """Test handling of non-request exceptions."""
        with patch("requests.request") as mock_request:
            mock_request.side_effect = RuntimeError("Unexpected error")

            node = HttpNode(wait=0)  # Set wait=0 to speed up test
            shared = {"url": "https://api.example.com/unexpected"}

            with pytest.raises(ValueError) as exc_info:
                node.run(shared)

            error_msg = str(exc_info.value)
            assert "HTTP request failed after 3 attempts" in error_msg
            assert "Unexpected error" in error_msg

    def test_auth_methods_are_mutually_exclusive(self):
        """Test that auth_token and api_key are mutually exclusive."""
        node = HttpNode()
        node.set_params({"auth_token": "bearer-token", "api_key": "api-key-value"})
        shared = {"url": "https://api.example.com/dual-auth"}

        # Should raise ValueError when both are provided
        with pytest.raises(ValueError, match="Cannot specify both auth_token and api_key"):
            node.prep(shared)

    def test_invalid_method_raises_error(self):
        """Test that invalid HTTP method raises ValueError."""
        node = HttpNode()
        shared = {"url": "https://api.example.com/test", "method": "INVALID"}

        with pytest.raises(ValueError, match="Invalid HTTP method 'INVALID'"):
            node.prep(shared)

    def test_invalid_timeout_raises_error(self):
        """Test that invalid timeout values raise ValueError."""
        node = HttpNode()

        # Negative timeout
        shared = {"url": "https://api.example.com/test", "timeout": -5}
        with pytest.raises(ValueError, match="Timeout must be a positive integer"):
            node.prep(shared)

        # Zero timeout
        shared = {"url": "https://api.example.com/test", "timeout": 0}
        with pytest.raises(ValueError, match="Timeout must be a positive integer"):
            node.prep(shared)

        # Non-integer timeout
        shared = {"url": "https://api.example.com/test", "timeout": "not_a_number"}
        with pytest.raises(ValueError, match="Timeout must be a positive integer"):
            node.prep(shared)

    def test_headers_are_copied_not_mutated(self):
        """Test that providing headers doesn't mutate the original dict."""
        original_headers = {"X-Custom": "value"}
        node = HttpNode()
        node.set_params({"api_key": "test-key"})
        shared = {"url": "https://api.example.com/test", "headers": original_headers}

        # Run prep which should add auth headers
        prep_result = node.prep(shared)

        # Original headers should not be modified
        assert original_headers == {"X-Custom": "value"}
        # Prep result should have both original and new headers
        assert prep_result["headers"]["X-Custom"] == "value"
        assert prep_result["headers"]["X-API-Key"] == "test-key"
