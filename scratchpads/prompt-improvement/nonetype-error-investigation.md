# Investigation: NoneType Error in Discovery Tests

## The Error
When running tests with certain models (particularly `gpt-5-nano`), we're seeing:
```
Exception: 'NoneType' object has no attribute 'lower'
```

## Location of Error
Based on grep results, the error is happening at:
```python
# /Users/andfal/projects/pflow/src/pflow/planning/utils/llm_helpers.py:117
if model_prefix in model_name.lower():
```

## Root Cause Analysis

### Where the error occurs:
The error happens in the `get_compatible_model()` function in `llm_helpers.py`:

```python
# Line 115-123 in llm_helpers.py
# Check if this model only supports default temperature
for model_prefix in DEFAULT_TEMP_ONLY_MODELS:
    if model_prefix in model_name.lower():  # <-- Line 117: ERROR HERE
        if 'temperature' in kwargs:
            original_temp = kwargs['temperature']
            # Remove temperature parameter entirely - use model's default
            del kwargs['temperature']
            logger.debug(f"Removed temperature parameter (was {original_temp}) for {model_name} - using model default")
        break
```

### Why it happens:
The `model_name` variable is `None` when it reaches this line, causing the AttributeError when trying to call `.lower()` on it.

### When it happens:
This occurs during the discovery prompt tests, specifically when:
1. The test is using the `gpt-5-nano` model (a test model)
2. The `get_compatible_model()` function is called
3. The `model_name` parameter passed to this function is `None`

### The call chain:
1. Test runs `WorkflowDiscoveryNode.prep()`
2. `prep()` calls `get_compatible_model()` to set up the LLM
3. `get_compatible_model()` receives `model_name=None`
4. Tries to call `.lower()` on None → Error

## The Real Problem

Looking at the `WorkflowDiscoveryNode.prep()` method, it likely gets the model name from configuration or environment. When using test models like `gpt-5-nano`, the model name might not be properly propagated through the system, resulting in `None` being passed.

## Recommended Fix

We should add a null check in `llm_helpers.py` to handle the case where `model_name` is None:

```python
def get_compatible_model(model_name: Optional[str] = None, **kwargs) -> Any:
    """Get a model with compatibility adjustments."""
    # Add null check
    if model_name is None:
        model_name = os.getenv("PFLOW_TEST_MODEL") or "claude-3-haiku-20240307"

    # Rest of the function...
    for model_prefix in DEFAULT_TEMP_ONLY_MODELS:
        if model_prefix in model_name.lower():  # Now safe
            # ...
```

Or more defensively:

```python
# Check if this model only supports default temperature
if model_name:  # Add null check
    for model_prefix in DEFAULT_TEMP_ONLY_MODELS:
        if model_prefix in model_name.lower():
            # ...
```

## Impact

This error is intermittent because:
1. It only happens with certain test models
2. The model name propagation might work differently in different test scenarios
3. Some tests might provide a default model name while others don't

## Summary

The error is a **bug in our code** - we're not handling the case where `model_name` could be `None` in the `get_compatible_model()` function. This is exposed when running tests with alternative models like `gpt-5-nano` where the model name might not be properly set in all code paths.

The fix is simple: add a null check before calling `.lower()` on `model_name`.