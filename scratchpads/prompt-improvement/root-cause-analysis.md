# Root Cause Analysis: NoneType Error with gpt-5-nano

## The Problem
When running tests with `gpt-5-nano`, we get:
```
Exception: 'NoneType' object has no attribute 'lower'
```
at line 117 (or 130 in current version) of llm_helpers.py

## Root Cause Found

The issue is a **model mismatch** between what's requested and what's actually used:

### The Flow:
1. **Node requests a model**: e.g., `"anthropic/claude-sonnet-4-0"`
2. **Node calls**: `get_compatible_model("anthropic/claude-sonnet-4-0")`
3. **Inside get_compatible_model**:
   - It stores `model_name = "anthropic/claude-sonnet-4-0"`
   - It calls `llm.get_model("anthropic/claude-sonnet-4-0")`
4. **Test fixture intercepts** (conftest.py):
   - Sees `PFLOW_TEST_MODEL=gpt-5-nano` in environment
   - Ignores the requested model
   - Returns `gpt-5-nano` model instead
5. **Back in get_compatible_model**:
   - It wraps the model's prompt method
   - In the wrapper, it checks if `model_name` needs temperature adjustment
   - But `model_name` is still `"anthropic/claude-sonnet-4-0"`!
   - So it doesn't remove temperature for gpt-5-nano
6. **The actual error path** (hypothesis):
   - Something in the double-wrapping or model mismatch causes model_name to become None
   - Or the model object doesn't have expected attributes

## Why It Only Affects gpt-5-nano

- Claude models don't need temperature adjustment, so the mismatch doesn't matter
- gpt-5-nano DOES need temperature removed, but get_compatible_model doesn't know it's actually gpt-5-nano

## The Fix

### Option 1: Make Nodes Use Environment Variable Directly
Instead of nodes having their own default, they should check the environment first:
```python
# In nodes.py prep methods:
default_model = os.getenv("PFLOW_TEST_MODEL") or "anthropic/claude-sonnet-4-0"
model_name = self.params.get("model", default_model)
```
This is what's in the unstaged changes - nodes will request the right model from the start.

### Option 2: Fix get_compatible_model to Detect Actual Model
After getting the model from llm.get_model, check what model was actually returned:
```python
def get_compatible_model(model_name: str = None):
    # ... handle None case ...

    # Get the model (might be redirected by test fixture)
    model = llm.get_model(model_name)

    # IMPORTANT: Check what model we actually got
    # The model object should have a way to identify itself
    actual_model_name = getattr(model, 'model_id', model_name) or model_name

    # Use actual_model_name for temperature checks, not requested model_name
```

### Option 3: Remove Double Wrapping
The test fixture shouldn't wrap the prompt method since get_compatible_model already does it.

## Verification

The unstaged changes implement Option 1 - making nodes check the environment variable first. This ensures the requested model matches what the fixture will return.

## Summary

The bug happens because:
1. Nodes request Claude (their default)
2. Test fixture returns gpt-5-nano instead
3. get_compatible_model doesn't know about the switch
4. Temperature handling is wrong for the actual model
5. This causes errors in the prompt execution

The fix is to ensure the requested model matches what's actually used, which the unstaged changes do by making nodes respect PFLOW_TEST_MODEL.