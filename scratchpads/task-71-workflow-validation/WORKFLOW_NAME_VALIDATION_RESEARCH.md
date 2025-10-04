# Workflow Name Validation Research Findings

## Executive Summary

**Confirmed Dual Validation Approach**: The system uses **permissive validation** at the service layer (WorkflowManager) and needs **stricter validation** at the CLI layer to provide better UX. This research validates the rationale documented in Task 71.

## 1. WorkflowManager Validation Rules

**Location**: `/Users/andfal/projects/pflow-feat-cli-agent-workflow/src/pflow/core/workflow_manager.py:37-59`

### Pattern Details

```python
def _validate_workflow_name(self, name: str) -> None:
    """Validate workflow name."""
    if not name:
        raise WorkflowValidationError("Workflow name cannot be empty")
    if len(name) > 50:
        raise WorkflowValidationError("Workflow name cannot exceed 50 characters")
    if "/" in name or "\\" in name:
        raise WorkflowValidationError("Workflow name cannot contain path separators")

    # Check for invalid characters (allow alphanumeric, hyphens, underscores, dots)
    import re
    if not re.match(r"^[a-zA-Z0-9._-]+$", name):
        raise WorkflowValidationError(
            "Workflow name can only contain letters, numbers, dots, hyphens, and underscores"
        )
```

### Allowed Characters

**Regex**: `^[a-zA-Z0-9._-]+$`

**Allowed**:
- Letters: `a-z`, `A-Z`
- Numbers: `0-9`
- Dots: `.`
- Hyphens: `-`
- Underscores: `_`

**Max Length**: 50 characters

**Forbidden**:
- Path separators: `/`, `\`
- Spaces
- Special characters: `@`, `#`, `$`, `%`, etc.
- Pipe: `|`
- Redirects: `>`, `<`

### Error Types Raised

1. **`WorkflowValidationError`**: Invalid name format (lines 47, 49, 57-59)
2. **`WorkflowExistsError`**: Workflow already exists (line 112)
3. **`WorkflowNotFoundError`**: Workflow doesn't exist (lines 188, 274)

### Storage Location

**Directory**: `~/.pflow/workflows/`
**Format**: `{name}.json`
**Wrapper**: Metadata wrapper containing `ir`, `description`, `created_at`, etc.

```json
{
  "name": "my-workflow",
  "description": "Description here",
  "ir": { /* actual workflow IR */ },
  "created_at": "2025-01-29T10:00:00+00:00",
  "updated_at": "2025-01-29T10:00:00+00:00",
  "version": "1.0.0",
  "rich_metadata": { /* optional */ }
}
```

## 2. CLI Usage of WorkflowManager

**Found 2 locations calling `workflow_manager.save()`**:

### Location 1: Line 803
```python
workflow_manager.save(workflow_name, ir_data, description, metadata=rich_metadata)
```

### Location 2: Line 868
```python
workflow_manager.save(workflow_name, ir_data, description, metadata=rich_metadata)
```

**Both calls are in auto-save and prompt-save flows** - they rely on WorkflowManager validation ONLY.

### No Additional CLI-Level Validation

**Current State**: CLI does NOT apply additional validation before calling `workflow_manager.save()`
- No pre-validation in main.py
- No validation in workflow.py commands
- No validation utilities imported

**Implication**: If we add CLI validation, it will be a NEW addition, not a replacement of existing logic.

## 3. File Path vs Workflow Name Detection

**Location**: `/Users/andfal/projects/pflow-feat-cli-agent-workflow/src/pflow/cli/main.py:168-170`

### Detection Function

```python
def _is_path_like(identifier: str) -> bool:
    """Heuristic to determine if identifier looks like a file path or .json file."""
    return (os.sep in identifier) or (os.altsep and os.altsep in identifier) or identifier.lower().endswith(".json")
```

### Detection Logic

1. **Contains `/` (Unix)** → Path
2. **Contains `\` (Windows)** → Path (via `os.altsep`)
3. **Ends with `.json`** (case-insensitive) → Path

**Otherwise** → Workflow name

### Test Cases

```python
'my-workflow'                    → path_like=False  (workflow name)
'my-workflow.json'               → path_like=True   (file path)
'./my-workflow.json'             → path_like=True   (file path)
'/path/to/my-workflow.json'      → path_like=True   (file path)
'.pflow/workflows/draft.json'    → path_like=True   (file path)
'workflows/draft.json'           → path_like=True   (file path)
```

### Resolution Order (`resolve_workflow`, line 209)

```python
def resolve_workflow(identifier: str, wm: WorkflowManager | None = None):
    """Resolve workflow from file path or saved name.

    Resolution order:
    1. File paths (contains / or ends with .json)
    2. Exact saved workflow name
    3. Saved workflow without .json extension
    """
```

**Implementation**:
1. Check if `_is_path_like()` → Try file load
2. Try exact workflow name from WorkflowManager
3. Try workflow name with `.json` stripped (e.g., `my-workflow.json` → `my-workflow`)

## 4. Filesystem Constraints

### Cross-Platform Considerations

**Unix/Linux/macOS**:
- Path separator: `/`
- Case-sensitive (usually)
- Forbidden: `/`, null byte
- Max filename: 255 bytes

**Windows**:
- Path separator: `\`
- Case-insensitive
- Forbidden: `<`, `>`, `:`, `"`, `/`, `\`, `|`, `?`, `*`
- Max filename: 255 characters
- Reserved names: `CON`, `PRN`, `AUX`, `NUL`, etc.

**WorkflowManager Pattern Handles This**:
- Forbids path separators (`/`, `\`)
- Allows safe characters only: `[a-zA-Z0-9._-]`
- Max length: 50 chars (well under 255)
- Avoids Windows reserved characters

**No Additional Filesystem Constraints Found**: The WorkflowManager pattern is already conservative enough for all platforms.

## 5. Dual Validation Rationale

### Why Stricter CLI Validation is Beneficial

#### 1. Better User Experience
**Current Problem**: User gets cryptic WorkflowManager error after full workflow generation
```
❌ Workflow name can only contain letters, numbers, dots, hyphens, and underscores
```

**With CLI Validation**: User gets immediate feedback with helpful suggestions
```
❌ Invalid workflow name: 'my workflow'

Workflow names must:
  • Use only letters, numbers, dots, hyphens, and underscores
  • Not exceed 50 characters
  • Start with a letter or number (recommended)

Suggestion: Use 'my-workflow' instead
```

#### 2. Prevent Wasted Work
- Planning takes time (LLM calls)
- Workflow generation is expensive
- Failing at save time wastes resources
- CLI validation fails fast

#### 3. Enforcing Best Practices
**CLI can be MORE strict** without breaking WorkflowManager:
- Require starting with alphanumeric (not dot/hyphen)
- Suggest kebab-case conventions
- Warn about ambiguous names
- Prevent names that look like file paths

#### 4. Precedent in the Codebase

**Parameter Validation** (`src/pflow/core/validation_utils.py:8-48`):
```python
def is_valid_parameter_name(name: str) -> bool:
    """Security-aware parameter validation."""
    # Forbids: $|><&; spaces, tabs
    # Used in 3 places: CLI params, workflow inputs, workflow outputs
```

**This shows the pattern**:
- Core validation (permissive, service-layer)
- CLI validation (strict, user-facing)
- Security validation (restrictive, safety-critical)

## 6. Validation Pattern Examples

### Current Validation Patterns in CLI

**No workflow name validation found**, but similar patterns exist:

#### MCP Server Validation (`src/pflow/cli/mcp.py:233`)
```python
def _validate_sync_arguments(name: Optional[str], all_servers: bool) -> None:
    """Validate sync command arguments before execution."""
    if name and all_servers:
        raise click.UsageError(...)
```

#### Parameter Name Validation (`src/pflow/cli/main.py:503`)
```python
# Uses validation_utils
if not is_valid_parameter_name(param_name):
    error = get_parameter_validation_error(param_name)
    click.echo(f"Invalid parameter name: {error}", err=True)
    sys.exit(1)
```

**Pattern**: Validate at CLI, provide helpful errors, exit early

## 7. Existing Workflow Commands

**Location**: `/Users/andfal/projects/pflow-feat-cli-agent-workflow/src/pflow/cli/commands/workflow.py`

**Commands**:
- `workflow list` - No validation needed (read-only)
- `workflow describe <name>` - Uses WorkflowManager.exists()
- `workflow show <name>` - Uses WorkflowManager.load()
- `workflow delete <name>` - Uses WorkflowManager.delete()

**None validate names on input** - they rely on WorkflowManager errors

## 8. Recommendations for CLI Validation

### Stricter CLI Rules (Beyond WorkflowManager)

```python
def validate_workflow_name_cli(name: str) -> tuple[bool, Optional[str]]:
    """Validate workflow name with CLI-specific rules.

    Returns:
        (is_valid, error_message)
    """
    # Check WorkflowManager rules first (via direct call)
    try:
        # Could instantiate WorkflowManager and call _validate_workflow_name
        # OR duplicate the regex check with same pattern
        if not name:
            return False, "Workflow name cannot be empty"
        if len(name) > 50:
            return False, "Workflow name cannot exceed 50 characters"
        if "/" in name or "\\" in name:
            return False, "Workflow name cannot contain path separators"
        if not re.match(r"^[a-zA-Z0-9._-]+$", name):
            return False, "Workflow name can only contain letters, numbers, dots, hyphens, and underscores"
    except Exception as e:
        return False, str(e)

    # Additional CLI-specific rules
    if not name[0].isalnum():
        return False, "Workflow name should start with a letter or number (not '.', '-', or '_')"

    # Check for file-path-like patterns
    if _is_path_like(name):
        return False, f"Workflow name looks like a file path. Use a simple name like '{name.replace('.json', '')}' instead"

    return True, None
```

### Benefits of This Approach

1. **Layered Validation**:
   - CLI: User-friendly, strict, fast-fail
   - WorkflowManager: Permissive, service-layer, safety net

2. **Maintainability**:
   - WorkflowManager rules are the source of truth
   - CLI can add restrictions without breaking service layer
   - Easy to relax CLI rules if needed (service layer unchanged)

3. **User Experience**:
   - Immediate feedback with suggestions
   - Prevents wasted planning/generation time
   - Educational (teaches naming conventions)

4. **Future-Proof**:
   - If requirements change, WorkflowManager stays stable
   - CLI can evolve validation rules independently
   - No breaking changes to API/service layer

## 9. Validation Test Cases

### WorkflowManager Validation (Permissive)

```python
# Valid
'my-workflow'           ✅
'my_workflow'           ✅
'my.workflow'           ✅
'workflow123'           ✅
'123workflow'           ✅
'workflow.test'         ✅
'workflow--test'        ✅
'.hidden'               ✅  (starts with dot - WorkflowManager allows)
'-dashed'               ✅  (starts with hyphen - WorkflowManager allows)

# Invalid
'my workflow'           ❌  (space)
'my@workflow'           ❌  (@)
'my/workflow'           ❌  (path separator)
'my|workflow'           ❌  (pipe)
'my>workflow'           ❌  (redirect)
''                      ❌  (empty)
'x' * 51                ❌  (too long)
```

### Recommended CLI Validation (Stricter)

```python
# Valid (same as WorkflowManager)
'my-workflow'           ✅
'my_workflow'           ✅
'my.workflow'           ✅
'workflow123'           ✅
'123workflow'           ✅
'workflow.test'         ✅

# Invalid (stricter than WorkflowManager)
'.hidden'               ❌  (starts with dot - looks like hidden file)
'-dashed'               ❌  (starts with hyphen - confusing)
'my-workflow.json'      ❌  (looks like file path)
'./my-workflow'         ❌  (looks like file path)
'workflows/draft'       ❌  (looks like file path)

# Invalid (same as WorkflowManager)
'my workflow'           ❌  (space)
'my@workflow'           ❌  (@)
'my/workflow'           ❌  (path separator)
```

## 10. Implementation Locations

### Where to Add CLI Validation

1. **`pflow workflow save <file> <name>`** command
   - Location: Would be in workflow.py or new `workflow save` command
   - Validate `<name>` argument before calling WorkflowManager

2. **Auto-save flow** (main.py:803)
   - Validate workflow name before saving
   - Show suggestions if invalid

3. **Prompt-save flow** (main.py:868)
   - Validate user-provided name in prompt
   - Re-prompt if invalid with suggestion

### Validation Utility Location

**Recommended**: Create in `src/pflow/core/validation_utils.py` (already has parameter validation)

```python
# Add to validation_utils.py
def is_valid_workflow_name(name: str, strict: bool = False) -> bool:
    """Validate workflow name with optional strict CLI rules."""
    ...

def get_workflow_name_validation_error(name: str) -> str:
    """Get descriptive error message for invalid workflow name."""
    ...

def suggest_workflow_name(invalid_name: str) -> str:
    """Suggest a valid workflow name based on invalid input."""
    ...
```

## 11. Summary

### Confirmed Facts

1. ✅ **WorkflowManager uses permissive validation**: `^[a-zA-Z0-9._-]+$`, max 50 chars
2. ✅ **CLI has NO additional validation**: Relies entirely on WorkflowManager
3. ✅ **Path detection is clear**: `/`, `\`, or `.json` suffix → file path
4. ✅ **Storage location**: `~/.pflow/workflows/{name}.json`
5. ✅ **Filesystem constraints**: Already handled by WorkflowManager pattern
6. ✅ **Error types**: WorkflowValidationError, WorkflowExistsError, WorkflowNotFoundError

### Dual Validation Rationale

**Service Layer (WorkflowManager)**: Permissive, stable, safety net
- Allows technical flexibility (starts with `.` or `-`)
- Maintains backward compatibility
- Focuses on filesystem safety

**CLI Layer (Recommended)**: Strict, user-friendly, fast-fail
- Enforces best practices (start with alphanumeric)
- Prevents ambiguous names (looks like file paths)
- Provides helpful suggestions
- Fails fast (before expensive operations)

### Next Steps

1. Create CLI validation functions in `validation_utils.py`
2. Add validation to workflow save commands
3. Add validation to auto-save and prompt-save flows
4. Write comprehensive tests for validation logic
5. Document naming conventions in CLI reference

---

**Verification Date**: 2025-01-29
**Verified By**: pflow-codebase-searcher agent
**Source Files**:
- `src/pflow/core/workflow_manager.py:37-59`
- `src/pflow/cli/main.py:168-170, 209-236, 803, 868`
- `src/pflow/cli/commands/workflow.py`
- `src/pflow/core/validation_utils.py`
