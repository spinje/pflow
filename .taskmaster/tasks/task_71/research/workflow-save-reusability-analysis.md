# Workflow Saving Logic - Reusability Analysis for CLI and MCP

**Date**: 2025-10-02
**Purpose**: Analyze existing workflow saving logic to determine if refactoring is needed for MCP tool reuse

---

## Executive Summary

**Recommendation**: ✅ **NO REFACTORING NEEDED** - The `WorkflowManager.save()` method is already perfectly abstracted and ready for reuse in both CLI and MCP contexts.

The current implementation is clean, service-oriented, and handles all necessary functionality. The CLI commands contain only presentation logic (prompts, retries, error display), which is appropriate for the UI layer.

---

## 1. WorkflowManager.save() Method Analysis

### Location
`src/pflow/core/workflow_manager.py:119-172`

### Method Signature
```python
def save(
    self,
    name: str,
    workflow_ir: dict[str, Any],
    description: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> str
```

### What It Does
1. **Validates workflow name** (internal `_validate_workflow_name()`)
2. **Creates metadata wrapper** (internal `_create_metadata_wrapper()`)
3. **Performs atomic file save** (internal `_perform_atomic_save()`)
4. **Returns absolute file path**

### Validation Rules (Built-in)
- Name cannot be empty
- Name max 50 characters
- No path separators (`/` or `\`)
- Only alphanumeric, dots, hyphens, underscores: `^[a-zA-Z0-9._-]+$`

### Error Handling
- Raises `WorkflowValidationError` for invalid names
- Raises `WorkflowExistsError` if workflow already exists (atomic safety)
- Raises `WorkflowValidationError` for other save failures

### Atomicity
- Uses `tempfile.mkstemp()` for temporary file creation
- Uses `os.link()` for atomic save (fails if target exists)
- Automatic cleanup on failure

---

## 2. Existing Usage Patterns

### CLI Usage - Interactive Save (`_prompt_workflow_save`, lines 816-883)
**Location**: `src/pflow/cli/main.py:816-883`

**CLI-Specific Logic** (not needed in MCP):
- User prompts for name and confirmation
- Retry loop for name conflicts
- Rich metadata extraction from planner
- Success/error messages with emoji
- Interactive retry on `WorkflowExistsError`

**Core Operation** (line 868):
```python
workflow_manager.save(workflow_name, ir_data, description, metadata=rich_metadata)
```

### CLI Usage - Auto Save (`_auto_save_workflow`, lines 768-813)
**Location**: `src/pflow/cli/main.py:768-813`

**CLI-Specific Logic**:
- Auto-naming with counter fallback (`name_1`, `name_2`, etc.)
- Silent error handling
- Safety limit (max 100 attempts)

**Core Operation** (line 803):
```python
workflow_manager.save(workflow_name, ir_data, description, metadata=rich_metadata)
```

### Key Insight
Both CLI patterns use the same `WorkflowManager.save()` call. All retry logic, prompts, and error display are in the CLI layer - **exactly where they belong**.

---

## 3. Validation Logic Analysis

### Where Validation Happens

#### A. Name Validation (Service Layer)
**Location**: `src/pflow/core/workflow_manager.py:37-59`

```python
def _validate_workflow_name(self, name: str) -> None:
    """Validate workflow name.

    Raises:
        WorkflowValidationError: If name is invalid
    """
    if not name:
        raise WorkflowValidationError("Workflow name cannot be empty")
    if len(name) > 50:
        raise WorkflowValidationError("Workflow name cannot exceed 50 characters")
    if "/" in name or "\\" in name:
        raise WorkflowValidationError("Workflow name cannot contain path separators")

    import re
    if not re.match(r"^[a-zA-Z0-9._-]+$", name):
        raise WorkflowValidationError(
            "Workflow name can only contain letters, numbers, dots, hyphens, and underscores"
        )
```

**Status**: ✅ **Perfect for reuse** - This is business logic, correctly placed in the service layer.

#### B. IR Validation (NOT in WorkflowManager)
**Important**: `WorkflowManager` does NOT validate the workflow IR itself. This is intentional separation of concerns:
- IR validation happens in `pflow.core.ir_schema.validate_ir()`
- Structural validation in `pflow.runtime.workflow_validator.validate_ir_structure()`
- Called by **execution layer before compilation** (see `src/pflow/execution/workflow_execution.py`)

**For MCP**: You'll need to validate IR before calling `save()` - same as CLI does.

---

## 4. File Operations Analysis

### Current Patterns

#### Atomic Save Operation
**Location**: `src/pflow/core/workflow_manager.py:92-117`

```python
def _perform_atomic_save(self, file_path: Path, temp_path: str) -> None:
    """Perform atomic file save operation using os.link().

    Raises:
        WorkflowExistsError: If workflow already exists
        OSError: For other OS-level errors
    """
    try:
        os.link(temp_path, file_path)  # Atomic - fails if exists
        os.unlink(temp_path)            # Clean up temp file
    except FileExistsError:
        os.unlink(temp_path)
        raise WorkflowExistsError(f"Workflow '{file_path.stem}' already exists") from None
    except OSError:
        Path(temp_path).unlink(missing_ok=True)
        raise
```

**Status**: ✅ **Production-ready** - Thread-safe, atomic, proper cleanup.

#### Delete Operation (for reference)
**Location**: `src/pflow/core/workflow_manager.py:262-280`

```python
def delete(self, name: str) -> None:
    """Delete a workflow.

    Raises:
        WorkflowNotFoundError: If workflow doesn't exist
    """
    file_path = self.workflows_dir / f"{name}.json"

    if not file_path.exists():
        raise WorkflowNotFoundError(f"Workflow '{name}' not found")

    try:
        file_path.unlink()
        logger.info(f"Deleted workflow '{name}'")
    except Exception as e:
        raise WorkflowValidationError(f"Failed to delete workflow '{name}': {e}") from e
```

**Status**: ✅ **Ready for MCP reuse** if needed.

---

## 5. Metadata Structure

### Storage Format
**Location**: Generated by `_create_metadata_wrapper()` at line 61-90

```json
{
  "name": "workflow-name",
  "description": "Human-readable description",
  "ir": { /* actual workflow IR */ },
  "created_at": "2025-01-29T10:00:00+00:00",
  "updated_at": "2025-01-29T10:00:00+00:00",
  "version": "1.0.0",
  "rich_metadata": {
    "search_keywords": ["tag1", "tag2"],
    "capabilities": ["feature1", "feature2"],
    "typical_use_cases": ["use case 1"],
    "execution_count": 0,
    "last_execution_timestamp": "...",
    "last_execution_success": true,
    "last_execution_params": {}
  }
}
```

### Metadata Parameters
- **name**: Required (validated internally)
- **workflow_ir**: Required (NOT validated by WorkflowManager)
- **description**: Optional (defaults to empty string)
- **metadata**: Optional rich metadata dict

**For MCP**: You can pass `None` for description and metadata - minimal save works fine.

---

## 6. Recommendations for MCP Integration

### What to Reuse Directly
✅ **Use `WorkflowManager.save()` as-is**:
```python
from pflow.core.workflow_manager import WorkflowManager

# In your MCP tool implementation
wm = WorkflowManager()  # Uses default ~/.pflow/workflows/
try:
    file_path = wm.save(
        name=workflow_name,
        workflow_ir=validated_ir,
        description=description,  # Optional
        metadata=None  # Optional - MCP might not need rich metadata
    )
    return {"success": True, "path": file_path, "name": workflow_name}
except WorkflowExistsError:
    return {"success": False, "error": "workflow_exists", "name": workflow_name}
except WorkflowValidationError as e:
    return {"success": False, "error": "invalid_name", "message": str(e)}
```

### What to Implement for MCP

#### 1. IR Validation (Required)
```python
from pflow.core.ir_schema import validate_ir, ValidationError

try:
    validated_ir = validate_ir(workflow_ir)  # Returns validated dict
except ValidationError as e:
    return {"success": False, "error": "invalid_ir", "message": str(e)}
```

#### 2. Name Conflict Handling (Optional)
**Option A**: Return error and let client decide
```python
except WorkflowExistsError:
    return {"success": False, "error": "workflow_exists"}
```

**Option B**: Auto-increment (like CLI auto-save)
```python
counter = 1
while True:
    try:
        return wm.save(workflow_name, ir_data, description)
    except WorkflowExistsError:
        workflow_name = f"{base_name}_{counter}"
        counter += 1
        if counter > 100:  # Safety limit
            return {"success": False, "error": "too_many_conflicts"}
```

**Recommendation**: Start with Option A (explicit error). Add auto-increment only if clients request it.

#### 3. Error Response Format (Required)
Define clear MCP response structure:
```typescript
// Success response
{
  "success": true,
  "name": "workflow-name",
  "path": "/full/path/to/workflow.json",
  "message": "Workflow saved successfully"
}

// Error responses
{
  "success": false,
  "error": "workflow_exists" | "invalid_name" | "invalid_ir" | "save_failed",
  "message": "Human-readable error message",
  "details": {  // Optional, for validation errors
    "field": "name",
    "rule": "max_length",
    "limit": 50
  }
}
```

---

## 7. No Refactoring Needed - Here's Why

### Service Layer is Already Clean
- ✅ Single Responsibility: `save()` does one thing well
- ✅ No UI Logic: No prompts, no retries, no formatting
- ✅ Proper Error Handling: Raises specific exceptions
- ✅ Atomic Operations: Thread-safe file handling
- ✅ Well-Tested: Comprehensive test coverage

### CLI Logic is Appropriately Layered
The CLI contains **presentation logic**, which should NOT be in the service layer:
- User prompts (not relevant to MCP)
- Retry loops (client decision)
- Error formatting (UI concern)
- Success messages (CLI output)

**Moving this to a shared function would be wrong** - it would:
1. Mix concerns (service + presentation)
2. Force MCP to depend on CLI utilities
3. Make the service layer more complex
4. Reduce testability

### Separation of Concerns is Correct
```
┌─────────────────────────────────────┐
│   CLI Layer (main.py)               │
│   - User prompts                    │
│   - Retry logic                     │
│   - Error display                   │
│   - Success messages                │
└────────────┬────────────────────────┘
             │ Calls save()
             ▼
┌─────────────────────────────────────┐
│   Service Layer (WorkflowManager)   │
│   - Name validation                 │
│   - Metadata creation               │
│   - Atomic file operations          │
│   - Business rules                  │
└─────────────────────────────────────┘
```

**For MCP**: You'll build your own presentation layer that calls the same service.

---

## 8. Testing Recommendations

### Service Layer Tests (Already Exist)
**Location**: `tests/test_core/test_workflow_manager.py`

Existing coverage:
- ✅ Basic save operation
- ✅ Name validation (empty, too long, invalid chars)
- ✅ Conflict detection (`WorkflowExistsError`)
- ✅ Atomic operation correctness
- ✅ Metadata structure
- ✅ Concurrent access handling

**Status**: No additional service layer tests needed.

### MCP Integration Tests (You'll Need to Create)
Recommended test scenarios:
```python
def test_mcp_save_workflow_tool():
    """Test MCP save_workflow tool with valid input."""
    result = mcp_save_workflow(
        name="test-workflow",
        workflow_ir=valid_ir,
        description="Test description"
    )
    assert result["success"] is True
    assert result["name"] == "test-workflow"
    assert "path" in result

def test_mcp_save_workflow_name_conflict():
    """Test MCP tool handles name conflicts."""
    mcp_save_workflow(name="test", workflow_ir=valid_ir)
    result = mcp_save_workflow(name="test", workflow_ir=valid_ir)
    assert result["success"] is False
    assert result["error"] == "workflow_exists"

def test_mcp_save_workflow_invalid_name():
    """Test MCP tool handles invalid names."""
    result = mcp_save_workflow(
        name="invalid/name",
        workflow_ir=valid_ir
    )
    assert result["success"] is False
    assert result["error"] == "invalid_name"

def test_mcp_save_workflow_invalid_ir():
    """Test MCP tool handles invalid IR."""
    result = mcp_save_workflow(
        name="test",
        workflow_ir={"invalid": "structure"}
    )
    assert result["success"] is False
    assert result["error"] == "invalid_ir"
```

---

## 9. Summary: Implementation Checklist for MCP

### ✅ Ready to Use As-Is
- [x] `WorkflowManager.save()` - No changes needed
- [x] Name validation - Built into service layer
- [x] Atomic file operations - Already implemented
- [x] Error handling - Proper exception hierarchy

### 📝 You Need to Implement (MCP Layer)
- [ ] IR validation before save (use `validate_ir()`)
- [ ] MCP tool function wrapping `WorkflowManager.save()`
- [ ] Error response formatting for MCP protocol
- [ ] Name conflict strategy (explicit error vs auto-increment)
- [ ] Integration tests for MCP tool

### ❌ DO NOT Implement
- [ ] ~~Shared save service function~~ - Not needed, would mix concerns
- [ ] ~~Move CLI retry logic~~ - This is presentation logic, keep in CLI
- [ ] ~~Create validation facade~~ - Direct exception handling is cleaner

---

## 10. Code Example for MCP Tool

```python
# src/pflow/mcp/tools/workflow_management.py

from typing import Any
from pflow.core.workflow_manager import WorkflowManager
from pflow.core.ir_schema import validate_ir, ValidationError
from pflow.core.exceptions import WorkflowExistsError, WorkflowValidationError

def save_workflow_tool(
    name: str,
    workflow_ir: dict[str, Any],
    description: str | None = None,
    overwrite: bool = False
) -> dict[str, Any]:
    """Save a workflow to the user's workflow library.

    Args:
        name: Workflow name (alphanumeric, dots, hyphens, underscores)
        workflow_ir: Valid workflow IR dictionary
        description: Optional workflow description
        overwrite: If True, update existing workflow instead of failing

    Returns:
        MCP-formatted response dict
    """
    # Step 1: Validate IR structure
    try:
        validated_ir = validate_ir(workflow_ir)
    except ValidationError as e:
        return {
            "success": False,
            "error": "invalid_ir",
            "message": f"Invalid workflow structure: {e}"
        }

    # Step 2: Initialize workflow manager
    wm = WorkflowManager()

    # Step 3: Handle overwrite case
    if overwrite and wm.exists(name):
        try:
            wm.update_ir(name, validated_ir)
            return {
                "success": True,
                "name": name,
                "path": wm.get_path(name),
                "message": f"Workflow '{name}' updated successfully",
                "operation": "updated"
            }
        except Exception as e:
            return {
                "success": False,
                "error": "update_failed",
                "message": str(e)
            }

    # Step 4: Save new workflow
    try:
        file_path = wm.save(name, validated_ir, description)
        return {
            "success": True,
            "name": name,
            "path": file_path,
            "message": f"Workflow '{name}' saved successfully",
            "operation": "created"
        }
    except WorkflowExistsError:
        return {
            "success": False,
            "error": "workflow_exists",
            "message": f"Workflow '{name}' already exists. Use overwrite=true to update.",
            "name": name
        }
    except WorkflowValidationError as e:
        return {
            "success": False,
            "error": "invalid_name",
            "message": str(e)
        }
    except Exception as e:
        return {
            "success": False,
            "error": "save_failed",
            "message": f"Failed to save workflow: {e}"
        }
```

---

## Final Verdict

**NO REFACTORING REQUIRED**

The existing architecture is:
- ✅ Clean separation of concerns
- ✅ Reusable service layer
- ✅ Appropriate error handling
- ✅ Production-ready atomicity
- ✅ Well-tested
- ✅ Ready for MCP integration

**Next Steps**:
1. Implement MCP tool wrapper (see code example above)
2. Add MCP-specific error formatting
3. Write integration tests
4. Document MCP tool interface
