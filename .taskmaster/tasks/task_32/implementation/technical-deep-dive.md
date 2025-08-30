# Technical Deep Dive: LLM Usage Capture Timing Issue

## The Sequence of Events (What Actually Happens)

### Before Fix - Why Usage Was Always Null

```python
# Step 1: Planner node calls LLM
model = llm.get_model("claude-3-sonnet")
response = model.prompt("Generate a workflow...")  # Returns immediately!

# Step 2: DebugWrapper intercepts and wraps
# intercept_prompt() in DebugWrapper
response = original_prompt(prompt_text, **kwargs)  # Still no API call
wrapped = TimedResponse(response, trace, node)    # Wrap the lazy response
return wrapped

# Step 3: Planner node tries to get result
result = response.json()  # This triggers TimedResponse.json()

# Step 4: Inside TimedResponse.json() - THE BUG
def json(self):
    start = time.perf_counter()
    result = self._response.json()  # API CALL HAPPENS HERE
    duration = time.perf_counter() - start

    # BUG: We pass the response object, not the data
    self._trace.record_llm_response(node, self._response, duration)
    return result

# Step 5: Inside record_llm_response() - TRYING TO GET USAGE
def record_llm_response(self, node, response, duration):
    # Problem 1: Response already consumed, might not work
    response_data = response.json()  # Second call - returns cached or fails

    # Problem 2: Usage might not be populated correctly after double consumption
    usage_data = response.usage()  # Often returns None

    # Result: No usage data captured!
```

### After Fix - Correct Usage Capture

```python
# Steps 1-3: Same as before (intercept, wrap, call json())

# Step 4: Inside TimedResponse.json() - THE FIX
def json(self):
    if self._json_cache is None:  # Only consume once
        start = time.perf_counter()
        self._json_cache = self._response.json()  # API CALL, response consumed
        duration = time.perf_counter() - start

        # NOW the response has been consumed, usage() will have data
        self._capture_usage_and_record(duration, self._json_cache)
    return self._json_cache

# Step 5: Inside _capture_usage_and_record() - CORRECT TIMING
def _capture_usage_and_record(self, duration, response_data):
    # Response has been consumed, NOW we can get usage
    usage_obj = self._response.usage()  # Has data now!

    # usage_obj might be:
    # 1. Dict: {'input_tokens': 100, 'output_tokens': 50}
    # 2. Object: Usage(input=100, output=50, details=...)
    # 3. None: If model doesn't support usage tracking

    # Extract in the format we need
    if hasattr(usage_obj, 'input'):  # Object form
        usage_data = {
            'input_tokens': usage_obj.input,
            'output_tokens': usage_obj.output,
            'total_tokens': usage_obj.input + usage_obj.output
        }
    elif isinstance(usage_obj, dict):  # Dict form
        usage_data = usage_obj

    # Pass already-extracted data (no re-consumption)
    self._trace.record_llm_response_with_data(
        node,
        response_data,  # Already have the JSON
        duration,
        usage_data,     # Already have the usage
        model_name,     # Already extracted
        shared
    )
```

## The Critical Timing Window

```
Timeline of API Call and Data Availability:

[Create Response]          [Consume Response]           [Data Available]
      |                            |                           |
      v                            v                           v
model.prompt() ----lazy----> response.json() ----API----> usage() has data
      ^                            ^                           ^
      |                            |                           |
  No API call                  API call made              Usage populated
  No usage data                Being processed            Ready to read
  Response empty               Response filling           Response complete
```

## Why Double Consumption is Problematic

The `llm` library's Response objects are NOT designed for multiple consumption:

1. **First `json()` call**: Triggers API call, consumes stream, caches result
2. **Second `json()` call**: Might return cached data, might fail, behavior undefined
3. **`usage()` after double consumption**: Might be stale, might be null, unreliable

### What the llm Library Does Internally

```python
# Simplified version of llm library's Response class
class Response:
    def __init__(self, model, prompt):
        self._json_cache = None
        self._usage = None
        self._consumed = False

    def json(self):
        if not self._consumed:
            # Make actual API call
            result = self._make_api_call()
            self._json_cache = result
            self._consumed = True
            # Plugin populates usage AFTER api call completes
            self._usage = self._extract_usage_from_result(result)
        return self._json_cache

    def usage(self):
        # Only has data AFTER json() or text() was called
        return self._usage
```

## The Model Name Mystery

Another subtle issue: The model name in the response might differ from what was requested:

```python
# You request:
model = llm.get_model("claude-3-sonnet")  # Alias

# You get back:
response.json() = {
    "model": "claude-3-sonnet-20240229",  # Actual model version
    "response": "..."
}

# Why "unknown" appeared:
# - We were looking at current_llm_call["model"] set during request
# - Should look at response_data["model"] after consumption
```

## Memory and Performance Implications

### Before Fix (Problematic)
- Potentially consuming response twice (memory spike)
- Undefined behavior on second consumption
- Missing data leads to incorrect metrics

### After Fix (Optimal)
- Single consumption with caching
- All data extracted in one pass
- Minimal memory footprint
- Accurate metrics

## Verification Checklist

To verify the fix is working:

1. **Check trace files**: Look for non-null `tokens` field in LLM calls
2. **Check model names**: Should see actual model names, not "unknown"
3. **Check costs**: Should see non-zero costs for planner execution
4. **Check token counts**: Should match what Claude/GPT actually used
5. **Check timing**: Duration should be 2000-8000ms for real calls, not 0

## The Lesson for Future LLM Integrations

When working with any LLM library:

1. **Understand the lazy evaluation model** - Most optimize by deferring API calls
2. **Know when data becomes available** - Usage often populated post-consumption
3. **Consume once, extract everything** - Don't try to consume responses multiple times
4. **Cache aggressively** - Responses are expensive, cache after first consumption
5. **Test with real API calls** - Mocks hide timing issues

## Edge Cases This Fix Handles

1. **Models without usage tracking**: Returns empty usage, costs calculate as 0 (correct)
2. **Cached responses from Anthropic**: Includes cache_creation_input_tokens and cache_read_input_tokens
3. **Different response formats**: Handles both dict and object usage formats
4. **Failed API calls**: Still records duration, no usage data (correct)
5. **Mocked tests**: Minimum 1ms duration prevents divide-by-zero issues

## What Could Still Break

1. **If llm library changes Response internals**: Would need to update our consumption pattern
2. **If new model providers use different usage format**: Would need to add handling
3. **If streaming responses are used**: Current fix assumes non-streaming
4. **If response.json() starts throwing on second call**: Would break old code paths

The fix is robust for current usage but should be monitored if the underlying `llm` library changes significantly.