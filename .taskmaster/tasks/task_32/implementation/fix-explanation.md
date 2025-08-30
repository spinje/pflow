# Fix for Planner LLM Cost Tracking Issue (Task 32)

## The Problem

The planner was showing `cost_usd: 0.0` in metrics output even though LLM calls were clearly being made. The trace files showed:
- `tokens: null` - No token usage data captured
- `model: "unknown"` - Model name not captured
- LLM calls were happening (we could see the responses) but no usage metrics

Example of broken output:
```json
{
  "metrics": {
    "planner": {
      "cost_usd": 0.0,  // Should have costs!
      "nodes_executed": 4
    }
  }
}
```

## Root Cause Analysis

### The Lazy Evaluation Trap

The `llm` library (Simon Willison's LLM CLI) uses **lazy evaluation** for performance:

1. **`model.prompt("...")` returns immediately** - No API call is made yet
2. **Returns a Response object** - This is just a wrapper, not the actual response
3. **API call happens on consumption** - Only when you call `response.json()` or `response.text()`
4. **Usage data populated after consumption** - `response.usage()` only has data AFTER the API call completes

### The Original Bug

The original code in `src/pflow/planning/debug.py` was doing this:

```python
# WRONG APPROACH - Task 27 implementation
def intercept_prompt(prompt_text, **kwargs):
    response = original_prompt(prompt_text, **kwargs)  # No API call yet!
    # Wrap in TimedResponse
    return TimedResponse(response, trace, current_node)

class TimedResponse:
    def json(self):
        start = time.perf_counter()
        result = self._response.json()  # API call happens HERE
        duration = time.perf_counter() - start
        # Pass the original response object (not the consumed data)
        self._trace.record_llm_response(node, self._response, duration)
        return result

# In TraceCollector
def record_llm_response(self, node, response, duration):
    # Try to get usage - but response has already been consumed!
    usage_data = response.usage()  # Returns None or stale data
    # Try to call json() again - might return cached or cause issues
    response_data = response.json()  # Second call - problematic!
```

The problem: We were trying to extract usage data from a response that had already been consumed, and potentially calling `json()` twice on the same response.

## The Fix

### New Approach: Capture Everything After Consumption

```python
class TimedResponse:
    def json(self):
        if self._json_cache is None:
            # Time the actual API call
            start = time.perf_counter()
            self._json_cache = self._response.json()  # Consume response
            duration = time.perf_counter() - start
            # NOW capture usage data (after consumption)
            self._capture_usage_and_record(duration, self._json_cache)
        return self._json_cache

    def _capture_usage_and_record(self, duration, response_data):
        # Response has been consumed, usage() now has data
        usage_obj = self._response.usage() if callable(self._response.usage) else self._response.usage

        # Handle different usage data formats
        if usage_obj:
            if isinstance(usage_obj, dict):
                usage_data = usage_obj
            elif hasattr(usage_obj, 'input') and hasattr(usage_obj, 'output'):
                # Object form (common with llm library)
                usage_data = {
                    'input_tokens': getattr(usage_obj, 'input', 0),
                    'output_tokens': getattr(usage_obj, 'output', 0),
                    'total_tokens': getattr(usage_obj, 'input', 0) + getattr(usage_obj, 'output', 0)
                }
                # Handle cache fields for Anthropic
                if hasattr(usage_obj, 'details') and usage_obj.details:
                    if hasattr(usage_obj.details, 'cache_creation_input_tokens'):
                        usage_data['cache_creation_input_tokens'] = usage_obj.details.cache_creation_input_tokens
                    if hasattr(usage_obj.details, 'cache_read_input_tokens'):
                        usage_data['cache_read_input_tokens'] = usage_obj.details.cache_read_input_tokens

        # Extract model name from response data
        model_name = response_data.get('model', 'unknown') if isinstance(response_data, dict) else 'unknown'

        # Pass pre-extracted data to avoid double consumption
        self._trace.record_llm_response_with_data(
            self._current_node,
            response_data,  # Already extracted response data
            duration,
            usage_data,     # Already extracted usage data
            model_name,     # Already extracted model name
            self._shared
        )
```

### Key Insights

1. **Consume First, Extract Second**: We must consume the response (trigger the API call) before trying to get usage data
2. **Cache Results**: Use `_json_cache` to ensure we only consume once
3. **Extract Everything at Once**: Get response data, usage data, and model name all together after consumption
4. **Pass Extracted Data**: New `record_llm_response_with_data()` method takes pre-extracted data to avoid re-consumption

## Why This Fix Works

### Aligns with llm Library Design

From the llm documentation and source code:
- Responses are lazy for performance (avoid unnecessary API calls)
- Usage data is populated by the plugin AFTER the response completes
- The `on_done` callback pattern exists specifically for this timing issue

### Follows the Data Flow

```
1. model.prompt() → Response object (no API call)
2. response.json() → API call happens → Response consumed
3. response.usage() → Now has data (populated during consumption)
4. Record everything → All data available and accurate
```

### Handles Edge Cases

- **Different usage formats**: Both dict and object forms
- **Cache fields**: Anthropic's cache_creation_input_tokens and cache_read_input_tokens
- **Model name extraction**: From response JSON, not from initial request
- **Mocked responses**: Minimum 1ms duration to avoid 0ms times

## Testing the Fix

Before fix:
```json
{
  "planner": {
    "cost_usd": 0.0,
    "nodes_executed": 4
  },
  "total": {
    "tokens_input": 0,
    "tokens_output": 0,
    "cost_usd": 0.0
  }
}
```

After fix (expected):
```json
{
  "planner": {
    "cost_usd": 0.002145,  // Actual costs!
    "nodes_executed": 4
  },
  "total": {
    "tokens_input": 1523,
    "tokens_output": 876,
    "cost_usd": 0.002145
  }
}
```

## Lessons Learned

1. **Understand Third-Party Library Internals**: The `llm` library's lazy evaluation wasn't documented prominently but is crucial for correct usage
2. **Timing Matters**: In lazy evaluation systems, WHEN you access data is as important as HOW
3. **Test with Real API Calls**: Mocked tests can hide timing issues that only appear with real async operations
4. **Follow the Data**: Trace where data actually becomes available, not where you expect it

## Related Code Locations

- **Primary Fix**: `src/pflow/planning/debug.py` - TimedResponse class
- **Metrics Integration**: `src/pflow/planning/debug.py` - record_llm_response_with_data method
- **Original Bug**: Introduced in Task 27 when planner debugging was implemented
- **Discovery**: Task 32 metrics implementation revealed the issue when costs were always 0.0

## Future Considerations

1. **Consider using `on_done` callbacks**: The llm library supports `response.on_done(callback)` which might be cleaner
2. **Add validation**: Could add checks to ensure usage data is present before calculating costs
3. **Monitor llm library updates**: If the library changes its lazy evaluation pattern, we'll need to adjust
4. **Document the pattern**: This lazy evaluation trap could affect other integrations

## Why Previous Fix Attempts Failed

Task 27's implementation (August 2025) attempted to fix duration tracking but missed the usage data issue:
- Fixed: Duration was 0ms (now tracks actual API call time)
- Missed: Usage data was still null (didn't realize it needed consumption first)
- Result: Times were fixed but costs remained at 0.0

This fix completes what Task 27 started by ensuring ALL metrics are captured correctly after response consumption.