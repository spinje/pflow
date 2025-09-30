# Critical Node Error Handling Fixes Required

## Date: 2024-01-25

## Executive Summary

Three node types (MCP, LLM, Git) are **hiding failures** by returning "default" action instead of "error" when operations fail. This completely breaks the repair system because workflows appear to succeed even when they fail. This document provides exact fixes needed.

## The Problem

### Current Broken Behavior
```
API call fails → Node logs error → Returns "default" → Workflow "succeeds" → No repair
```

### Expected Behavior
```
API call fails → Node logs error → Returns "error" → Workflow fails → Repair triggers
```

## Root Cause

Historical "planner limitation" led to nodes returning "default" even on errors. This made sense when there was no repair system, but now it prevents repair from working at all.

## Files That Need Fixes

### 1. MCP Node - ALREADY FIXED ✓
**File**: `src/pflow/nodes/mcp/node.py`
**Status**: Already fixed in line 384 (changed from "default" to "error")

### 2. LLM Node - NEEDS FIX
**File**: `src/pflow/nodes/llm/llm.py`

#### Problem Areas:
1. **Lines 178-196**: `exec_fallback()` raises exceptions instead of returning error values
2. **Line 176**: `post()` always returns "default", ignoring errors

#### Required Changes:

**Change exec_fallback() from:**
```python
def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> None:
    """Handle errors after all retries exhausted."""
    error_msg = str(exc)

    if "UnknownModelError" in error_msg:
        raise ValueError(f"Unknown model: {prep_res['model']}...")
    elif "NeedsKeyException" in error_msg:
        raise ValueError(f"API key required...")
    else:
        raise ValueError(f"LLM call failed...")
```

**To:**
```python
def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> dict[str, Any]:
    """Handle errors after all retries exhausted."""
    error_msg = str(exc)

    if "UnknownModelError" in error_msg:
        error_detail = f"Unknown model: {prep_res['model']}. Run 'llm models' to see available models."
    elif "NeedsKeyException" in error_msg:
        error_detail = f"API key required for model: {prep_res['model']}. Set up with 'llm keys set <provider>'."
    else:
        error_detail = f"LLM call failed after {self.max_retries} attempts. Model: {prep_res['model']}"

    # Return error dict instead of raising
    return {
        "response": "",
        "error": error_detail,
        "model": prep_res.get('model', 'unknown'),
        "usage": {}
    }
```

**Change post() from:**
```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    """Store results in shared store."""
    raw_response = exec_res["response"]
    # ... processing ...
    return "default"  # Always return "default"
```

**To:**
```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    """Store results in shared store."""
    # Check for error first
    if "error" in exec_res and exec_res["error"]:
        shared["error"] = exec_res["error"]
        shared["response"] = ""
        shared["llm_usage"] = {}
        return "error"  # Return error to trigger repair

    raw_response = exec_res["response"]
    # ... normal processing ...
    return "default"
```

### 3. Git Nodes - NEED FIX
**Files**: All files in `src/pflow/nodes/git/` that have `exec_fallback` methods

#### Example: `src/pflow/nodes/git/commit.py`

**Problem**: Line 202 always returns "default" even when exec_res contains error

**Change post() from:**
```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> Optional[str]:
    """Update shared store with commit results and return action."""
    shared["commit_sha"] = exec_res.get("commit_sha", "")
    shared["commit_message"] = exec_res.get("commit_message", "")

    # Log status if present
    if "status" in exec_res:
        shared["commit_status"] = exec_res["status"]

    # Always return default action
    return "default"
```

**To:**
```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> Optional[str]:
    """Update shared store with commit results and return action."""
    # Check for error status first
    if exec_res.get("status") == "error":
        shared["error"] = exec_res.get("error", "Git operation failed")
        shared["commit_sha"] = ""
        shared["commit_message"] = exec_res.get("commit_message", "")
        shared["commit_status"] = "error"
        return "error"  # Return error to trigger repair

    # Normal processing for success
    shared["commit_sha"] = exec_res.get("commit_sha", "")
    shared["commit_message"] = exec_res.get("commit_message", "")

    if "status" in exec_res:
        shared["commit_status"] = exec_res["status"]

    return "default"
```

**Apply similar fix to all Git nodes that have exec_fallback methods:**
- `checkout.py`
- `push.py`
- `status.py`
- `log.py`
- `get_latest_tag.py`

## Why This Is Critical

1. **Repair System Is Broken**: Without these fixes, the repair system never triggers because workflows appear to succeed even when they fail.

2. **User Experience**: Users see "✓" checkmarks next to failed operations, leading to confusion when nothing actually worked.

3. **Violates PocketFlow Pattern**: The CLAUDE.md clearly states that nodes should return "error" on failure, not hide errors.

## Testing the Fixes

After making these changes, test with:

1. **LLM Node**: Use an invalid model name
   - Should return "error" action
   - Repair should attempt to fix the model name

2. **Git Node**: Try to commit in a non-git directory
   - Should return "error" action
   - Repair should attempt to fix the path

3. **MCP Node**: Send invalid data to Google Sheets
   - Already fixed, should return "error"
   - Repair should attempt to fix the data structure

## Implementation Order

1. **Fix LLM node first** - Most commonly used, highest impact
2. **Fix Git commit node** - Next most common operation
3. **Fix remaining Git nodes** - Complete the pattern

## Validation

Each fix should ensure:
- ✅ Node returns "error" action when operation fails
- ✅ Error message is stored in shared["error"]
- ✅ Repair system triggers on failure
- ✅ Follows PocketFlow pattern from CLAUDE.md

## Important Note

The comment about "planner limitation" is outdated. The repair system needs to know about failures to work properly. Always return "error" on failure, not "default".