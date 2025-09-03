# Task 54: Implement HTTP Node

## ID
54

## Title
Implement HTTP Node

## Description
Add a native HTTP node for making web requests with automatic JSON handling, authentication support, and proper error handling. This enables common API integrations without requiring shell commands or MCP servers, making pflow immediately useful for webhook, API health checks, and data fetching workflows.

## Status
not started

## Dependencies
None

## Priority
high

## Details
The HTTP node is a fundamental building block that enables essential workflows like API health checks, webhook notifications, and data fetching. Without it, users must rely on awkward shell+curl combinations or install MCP servers for basic HTTP operations.

Research shows 60% of HTTP operations are simple GET/POST with JSON, 25% require authentication, and only 15% need advanced features. This guides our phased implementation approach.

### Core Requirements
The HTTPNode should support:
- All standard HTTP methods (GET, POST, PUT, DELETE, PATCH)
- Automatic method detection (POST with body, GET without)
- Automatic JSON serialization/deserialization
- Query parameters as a separate field for clean URL handling
- Custom headers including authentication (API key 70%, Bearer token 20% of use cases)
- Configurable timeouts (default: 30 seconds based on industry standards)
- Proper error handling with actionable suggestions, not just status codes
- Both JSON and plain text responses

### Interface Design
The node should follow pflow's standard interface patterns:
- Only `url` is required; all other parameters have smart defaults
- Clear parameter names matching common usage (url, method, headers, body, params)
- Automatic detection of JSON responses based on Content-Type
- Store responses in predictable shared store keys (response, status_code, response_headers)
- Return specific actions: success (2xx), client_error (4xx), server_error (5xx), timeout

### Key Use Cases
1. API Health Monitoring - Check if services are responding
2. Webhook Integration - Send processed data to external services
3. Data Fetching - Retrieve JSON data for analysis
4. Authentication Flows - Support for Bearer tokens and API keys
5. Multi-step API Workflows - Chain multiple API calls

### Implementation Considerations
- Use the requests library for reliability and simplicity (validated through research)
- Handle both JSON and form-encoded request bodies
- Provide actionable error messages with suggestions (e.g., "Request timed out. Try --timeout=60")
- Support environment variable expansion for sensitive data like API keys
- Natural language mapping: "fetch"→GET, "send"→POST, "update"→PUT, "delete"→DELETE
- Defer retry logic for transient failures to v2 (only 15% of use cases need advanced features)

### Integration Points
- Works with LLMNode for analyzing API responses
- Chains with ShellNode for hybrid workflows
- Compatible with future authentication nodes
- Provides foundation for specialized API nodes (GitHub, Slack wrappers)

## Test Strategy
Comprehensive testing to ensure reliability across different API scenarios:

- Unit tests with mocked requests for all HTTP methods
- Test JSON serialization/deserialization with complex nested data
- Test error handling for timeouts, 4xx, 5xx responses
- Test header handling including auth headers
- Integration tests against httpbin.org for real requests
- Test with both JSON and plain text responses
- Verify proper shared store key naming
- Test environment variable expansion in sensitive fields
- Performance tests with large payloads
- Test connection error handling (refused, DNS failure)