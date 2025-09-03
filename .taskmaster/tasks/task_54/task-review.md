# Task 54 Review: Implement HTTP Node

## Executive Summary
Implemented pflow's first native HTTP node using the requests library, establishing the pattern for direct Python library integration in nodes. The implementation revealed critical distinctions in pflow's error handling patterns and parameter fallback mechanisms that aren't documented elsewhere.

## Implementation Overview

### What Was Built
Built a comprehensive HTTP node supporting all standard HTTP methods with automatic JSON handling, authentication, and query parameters. Key deviations from spec:
- Added HEAD and OPTIONS methods (not in original spec)
- Enforced auth_token/api_key mutual exclusivity (spec was ambiguous, tests initially allowed both)
- Implemented presence-check parameter fallback instead of truthiness checks
- Added header copying to prevent mutation of caller's data

### Implementation Approach
Chose to follow the GitHub/LLM node patterns (newer) rather than file node patterns (older), particularly for error handling. This decision was critical as the two patterns are incompatible and choosing wrong would break retry mechanism.

## Files Modified/Created

### Core Changes
- `src/pflow/nodes/http/__init__.py` - Package initialization with HttpNode export
- `src/pflow/nodes/http/http.py` - Main implementation following Node pattern
- `pyproject.toml` - Added requests>=2.32.5 dependency (specific version for SSLContext fix)

### Test Files
- `tests/test_nodes/test_http/test_http.py` - 36 comprehensive tests
- `tests/test_nodes/test_http/test_http_discovery.py` - Registry discovery verification

Critical tests:
- `test_retry_mechanism` - Verifies retry actually happens (mock called multiple times)
- `test_headers_are_copied_not_mutated` - Prevents subtle caller data corruption
- `test_auth_methods_are_mutually_exclusive` - Enforces spec requirement

## Integration Points & Dependencies

### Incoming Dependencies
- Planning system -> HTTP node (via registry discovery and Interface documentation)
- Workflow executor -> HTTP node (via dynamic import and Node interface)
- Registry scanner -> HTTP node (via class introspection and docstring parsing)

### Outgoing Dependencies
- HTTP node -> pocketflow.Node (inheritance and retry mechanism)
- HTTP node -> requests library (HTTP operations)
- HTTP node -> json module (response parsing)

### Shared Store Keys
- `url` - API endpoint (required, falls back to params)
- `method` - HTTP verb (optional, auto-detects based on body)
- `body` - Request payload (optional, triggers POST if present)
- `headers` - Additional headers (optional, copied to avoid mutation)
- `params` - Query parameters (optional)
- `timeout` - Request timeout in seconds (optional, validated as positive int)
- `response` - Response data (written, JSON parsed or text)
- `status_code` - HTTP status code (written)
- `response_headers` - Response headers dict (written)
- `response_time` - Request duration in seconds (written)
- `error` - Error description for non-2xx responses (written)

## Architectural Decisions & Tradeoffs

### Key Decisions
1. **ValueError in exec_fallback** -> Followed GitHub/LLM pattern not file pattern -> File pattern returns strings which breaks retry
2. **Copy headers dict** -> Prevent mutation of caller data -> Alternative: document mutation behavior
3. **Presence checks for fallback** -> Handle falsy values correctly -> Truthiness checks drop empty dicts
4. **No environment variable expansion** -> Only MCP node does this -> Keep it simple for MVP
5. **"json" in content-type** -> Broader JSON detection -> Handles application/problem+json etc.

### Technical Debt Incurred
- No streaming response support (defer to v2)
- No file upload/multipart form support (defer to v2)
- No OAuth2 flows (defer to v2)
- No custom SSL certificate support (using requests defaults)
- Method complexity in prep() requires noqa comment

## Testing Implementation

### Test Strategy Applied
Set `wait=0` for all retry tests to avoid 2+ second delays per test. This pattern is CRITICAL for test performance with retry mechanisms.

### Critical Test Cases
- `test_retry_mechanism` - Proves retry actually works (not just that it doesn't crash)
- `test_invalid_timeout_raises_error` - Validates timeout as positive integer
- `test_headers_are_copied_not_mutated` - Catches header mutation bug
- `test_auth_methods_are_mutually_exclusive` - Enforces spec constraint

## Unexpected Discoveries

### Gotchas Encountered
1. **Two incompatible error patterns in pflow**: File nodes return error strings, GitHub/LLM nodes raise ValueError. Must pick correct one or retry breaks.
2. **sys.path manipulation anti-pattern**: Initial implementation used sys.path.insert() - this is a security smell and breaks in production
3. **Test performance trap**: Using default wait=1.0 in retry tests causes 8+ second test runs
4. **Parameter fallback truthiness trap**: `shared.get("key") or self.params.get("key")` treats empty dict as falsy

### Edge Cases Found
- JSON parsing failure must fall back to text (not raise)
- HTTP 4xx/5xx are valid responses, not exceptions (don't use raise_for_status())
- Empty response body should return empty string, not None
- Headers can be None, empty dict, or populated - must handle all cases

## Patterns Established

### Reusable Patterns
```python
# Parameter fallback with presence check (not truthiness)
value = shared.get("key") if "key" in shared else self.params.get("key", default)

# Copy mutable parameters before modification
base_headers = shared.get("headers") if "headers" in shared else self.params.get("headers", {})
headers = dict(base_headers) if base_headers else {}

# Validation with actionable errors
try:
    timeout = int(raw_timeout)
except (TypeError, ValueError):
    raise ValueError(f"Timeout must be a positive integer, got: {raw_timeout}") from None

# Test performance optimization
node = HttpNode(wait=0)  # Critical for retry test performance
```

### Anti-Patterns to Avoid
- Never use try/except in exec() method - breaks retry mechanism
- Don't return error strings from exec_fallback() - raise ValueError
- Don't mutate parameters passed from caller
- Don't use sys.path manipulation in production code
- Don't use truthiness checks for parameter fallback with dicts

## Breaking Changes

### API/Interface Changes
None - new node addition

### Behavioral Changes
None - new functionality

## Future Considerations

### Extension Points
- `exec()` method could support JSONPath extraction (see task 56)
- Authentication could support OAuth2 flows
- Response handling could support streaming
- Could add retry strategy customization

### Scalability Concerns
- Large response bodies held in memory (no streaming)
- No connection pooling (new connection per request)
- No caching mechanism

## AI Agent Guidance

### Quick Start for Related Tasks
1. First read `src/pflow/nodes/github/get_issue.py` for modern patterns
2. Copy parameter fallback pattern with presence checks
3. Use HttpNode as template for new external service nodes
4. Always set wait=0 in retry tests

Key pattern files:
- `src/pflow/nodes/github/*.py` - Modern error handling patterns
- `src/pflow/nodes/llm/llm.py` - Parameter fallback examples
- Avoid patterns from `src/pflow/nodes/file/*.py` - Older error handling

### Common Pitfalls
1. **Wrong error pattern**: File nodes use old pattern - follow GitHub/LLM instead
2. **Forgetting wait=0 in tests**: Causes 2+ second delays per retry test
3. **Parameter mutation**: Always copy dicts/lists before modifying
4. **Truthiness fallback**: Use presence checks for dict parameters
5. **Missing validation**: Validate user inputs (timeout, method, etc.)

### Test-First Recommendations
When modifying HTTP node:
1. Run `pytest tests/test_nodes/test_http/test_http.py::TestHttpNode::test_retry_mechanism` - Ensures retry still works
2. Run `pytest tests/test_nodes/test_http/test_http.py::TestHttpNode::test_headers_are_copied_not_mutated` - Prevents mutation bugs
3. Add test with wait=0 for any new error conditions
4. Mock at requests level, not subprocess level

## Implementation Metadata

### Session Information
- **Claude Session ID**: cbc0418f-4a5b-4255-9b08-1cf43a85a693
- **Pull Request**: [#14](https://github.com/spinje/pflow/pull/14)
- **Branch**: feat/http-node
- **Implementation Date**: 2025-09-03

---

*Generated from implementation context of Task 54*
*Session: cbc0418f-4a5b-4255-9b08-1cf43a85a693*