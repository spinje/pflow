# Refined Specification for Subtask 14.2

## Clear Objective
Add structure navigation hints to the context builder's output for complex types (dict/list) while maintaining the existing type display functionality.

## Context from Knowledge Base
- Building on: Rich format metadata from 14.1, exclusive params pattern
- Avoiding: Breaking existing functionality, over-engineering for MVP
- Following: Minimal changes requirement, 50KB output limit
- **Cookbook patterns to apply**: Not applicable (no PocketFlow usage)

## Technical Specification

### Current State
The context builder already:
- Displays types in format: `key: type` (when type is not "any")
- Filters exclusive params correctly with dict format
- Handles backward compatibility with string format

### What Needs to be Added
1. **Structure Navigation Hints**
   - For dict/list types that have a "structure" field in metadata
   - Display inline after type: `issue_data: dict` - Navigate: .number, .user.login
   - Extract navigation paths from the structure recursively
   - Limit depth to 2-3 levels for readability

2. **Structure Hint Limiting**
   - Track number of structure hints shown
   - Limit to first 20-30 occurrences to respect 50KB limit
   - Add counter in build_context() function

### Implementation Details

#### Structure Navigation Algorithm
```python
def _extract_navigation_paths(structure: dict, prefix: str = "", max_depth: int = 2) -> list[str]:
    """Extract navigation paths from structure dict."""
    paths = []
    if max_depth <= 0:
        return paths

    for field_name, field_info in structure.items():
        current_path = f"{prefix}.{field_name}" if prefix else field_name
        paths.append(current_path)

        # Recurse for nested structures
        if isinstance(field_info, dict) and "structure" in field_info:
            nested = _extract_navigation_paths(
                field_info["structure"],
                current_path,
                max_depth - 1
            )
            paths.extend(nested[:3])  # Limit nested paths

    return paths[:10]  # Limit total paths per structure
```

#### Updated Formatting
In `_format_node_section()`, enhance the rich format handling:
```python
if isinstance(out, dict):
    key = out["key"]
    type_str = out.get("type", "any")

    # Base format with type
    if type_str != "any":
        output_str = f"`{key}: {type_str}`"
    else:
        output_str = f"`{key}`"

    # Add navigation hints for complex types
    if type_str in ("dict", "list", "list[dict]") and "structure" in out:
        paths = _extract_navigation_paths(out["structure"])
        if paths:
            nav_hints = ", ".join(f".{p}" for p in paths[:5])
            output_str += f" - Navigate: {nav_hints}"
```

### Success Criteria
- [x] Structure navigation hints appear for dict/list types with structures
- [x] Navigation paths are readable and helpful (e.g., .user.login)
- [x] Existing type display functionality remains unchanged
- [x] Backward compatibility with string format maintained
- [x] Structure hints are limited to prevent 50KB overflow
- [x] All existing tests continue to pass
- [x] New tests added for structure navigation feature

## Test Strategy
- Unit tests: Test `_extract_navigation_paths()` with various structures
- Integration tests: Test full formatting with complex metadata
- Edge cases: Empty structures, deeply nested structures, circular references
- Performance: Verify 50KB limit is respected with many complex nodes

## Dependencies
- Requires: Metadata extractor returning structure field (already done in 14.1)
- Impacts: Context builder output format (additive change only)

## Decisions Made
- Use inline navigation hints format (confirmed via evaluation)
- Omit descriptions to maintain minimal changes (confirmed)
- Limit structure hints to manage output size (confirmed)
- Focus only on missing structure navigation feature
