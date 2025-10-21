# Phase 5 Critical Bug Fix - False Positive Detection

**Date**: 2025-10-20
**Issue**: Workflow failing with template resolution error when template WAS correctly resolved
**Status**: FIXED ✅

---

## The Problem

The workflow `slack-qa-responder` was failing on the second node with:

```
ERROR: Template in parameter 'stdin' could not be fully resolved: '${fetch-messages.result}'
```

Even though the debug logs showed:
```
variable_exists('fetch-messages.result', context) = True
resolve_value returned: True (type: dict)
```

**The template WAS resolving correctly, but still triggering an error!**

---

## Root Cause Analysis

### The Bug Location

**File**: `src/pflow/runtime/node_wrapper.py`
**Lines**: 320-322 (before fix)

```python
# OLD BUGGY CODE:
if "${" in str(resolved_value):
    # Template failed to resolve - still contains ${...}
    raise ValueError(...)
```

### What Went Wrong

1. **Template resolves correctly**: `${fetch-messages.result}` resolves to a dict containing Slack messages
2. **Dict contains MCP API data**: Slack messages include text like `"${save-message.stdout}"` (from previous failed workflow runs)
3. **String conversion triggers false positive**: `str(resolved_value)` converts the dict to a string representation
4. **String contains `${`**: The string representation includes the literal `${...}` from the Slack message text
5. **Error incorrectly triggered**: System thinks template wasn't resolved

### Example Data

From the workflow trace, the resolved dict contained messages with this text:

```json
{
  "messages": [
    {"text": "${save-message.stdout}"},  // ← Literal text from Slack API
    {"text": "${analyze-questions.response}"},
    // ... more messages
  ]
}
```

When this dict is converted to a string, it contains `${`, triggering the false positive.

---

## The Fix

### Changed Logic

**Before** (checked string representation of ANY value):
```python
if "${" in str(resolved_value):
    raise ValueError("Template not resolved")
```

**After** (only check string values that equal the original template):
```python
is_unresolved = (
    isinstance(resolved_value, str)        # Only check strings
    and "${" in resolved_value             # That contain ${
    and resolved_value == template         # And equal the original template
)

if is_unresolved:
    raise ValueError("Template not resolved")
```

### Why This Works

The fix ensures we only flag unresolved templates when:
1. **The resolved value is a string** (not dict/list/int/etc)
2. **It still contains template syntax** (`${...}`)
3. **It's unchanged from the original** (resolution failed)

This prevents false positives from:
- MCP API responses containing `${...}` as data
- Dicts/lists that contain strings with `${...}`
- Any resolved data that legitimately includes template-like syntax

---

## Testing

### Reproduction

The issue only occurs when:
1. MCP node returns data containing `${...}` in string fields
2. Downstream node uses a template to access that data
3. The check converts non-string data to string to search for `${`

### Verification

To verify the fix works, run any workflow that:
- Fetches data from external APIs (Slack, GitHub, etc.)
- That data might contain template-like syntax
- A template variable resolves to that data (as dict/list)

Example:
```bash
uv run pflow slack-qa-responder channel_id=... spreadsheet_id=...
```

Should NOT fail with "template not resolved" if `fetch-messages` succeeded.

---

## Impact

### What Was Broken

- **Any workflow using MCP nodes** that return data containing `${...}` text
- **Any nested data structures** with template-like strings inside
- Particularly affects Slack/GitHub/API integrations

### What Is Fixed

- Templates that resolve to dicts/lists are no longer flagged as unresolved
- Only actual unresolved templates (strings unchanged after resolution) trigger errors
- MCP API responses with `${...}` text no longer cause false positives

---

## Related Issues

This was exactly the scenario described in the research findings under "Edge Cases from MCP Nodes":

> **CRITICAL FINDING**: MCP nodes **legitimately return `${...}` as data**!
>
> Example:
> ```python
> # MCP Slack API returns:
> {"message": "User ${USER_ID} logged in"}
>
> # Should we validate this? NO!
> # The ${USER_ID} is API response data, not a pflow template
> ```

The fix implements the recommended approach: **Don't validate templates in resolved data, only validate that resolution succeeded**.

---

## Code Changes

**File**: `src/pflow/runtime/node_wrapper.py`

### Before (Lines 320-326)
```python
# Check if template was fully resolved (for BOTH simple and complex templates)
# Template is unresolved if it still contains ${...} syntax
if "${" in str(resolved_value):
    # Template failed to resolve - still contains ${...}
    # This happens when variable doesn't exist in context
    # Build enhanced error message with context and suggestions
    error_msg = self._build_enhanced_template_error(key, template, context)
```

### After (Lines 320-334)
```python
# Check if template was fully resolved (for BOTH simple and complex templates)
# Template is unresolved if:
# 1. It's a string AND still contains ${...} syntax AND equals the original template
# This avoids false positives from resolved dicts/lists that contain ${...} in their data
is_unresolved = (
    isinstance(resolved_value, str)
    and "${" in resolved_value
    and resolved_value == template
)

if is_unresolved:
    # Template failed to resolve - still contains ${...}
    # This happens when variable doesn't exist in context
    # Build enhanced error message with context and suggestions
    error_msg = self._build_enhanced_template_error(key, template, context)
```

---

## Lessons Learned

1. **Don't check string representations of objects** - `str(dict)` is implementation-dependent
2. **Be careful with external data** - API responses may contain any text, including template-like syntax
3. **Test with real data** - Synthetic tests don't catch issues with production API responses
4. **Value equality is better than pattern matching** - Check if value changed, not if it contains patterns

---

## Status

✅ **FIXED** - Committed to feat/runtime-template-resolution branch
✅ **TESTED** - Verified fix resolves false positive
⏳ **PENDING** - Full E2E test with successful MCP API call (timeout issue separate)

The template resolution logic now correctly handles:
- Simple templates resolving to any type
- Complex templates resolving to strings
- Data containing `${...}` syntax
- Actual unresolved templates (detection still works)
