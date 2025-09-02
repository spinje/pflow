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

### Core Requirements
The HTTPNode should support:
- All standard HTTP methods (GET, POST, PUT, DELETE, PATCH)
- Automatic JSON serialization/deserialization
- Custom headers including authentication
- Configurable timeouts
- Proper error handling with status codes
- Both JSON and plain text responses

### Interface Design
The node should follow pflow's standard interface patterns:
- Clear parameter names matching common usage (url, method, headers, body)
- Automatic detection of JSON responses based on Content-Type
- Store responses in predictable shared store keys
- Return appropriate actions based on HTTP status codes

### Key Use Cases
1. API Health Monitoring - Check if services are responding
2. Webhook Integration - Send processed data to external services
3. Data Fetching - Retrieve JSON data for analysis
4. Authentication Flows - Support for Bearer tokens and API keys
5. Multi-step API Workflows - Chain multiple API calls

### Implementation Considerations
- Use the requests library for reliability and simplicity
- Handle both JSON and form-encoded request bodies
- Provide clear error messages for common failures (timeout, connection refused, auth errors)
- Support environment variable expansion for sensitive data like API keys
- Consider retry logic for transient failures (can be added in v2)

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