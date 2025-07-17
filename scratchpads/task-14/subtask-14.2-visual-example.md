# Visual Example: What Subtask 14.2 Actually Does

This document shows the EXACT transformation that subtask 14.2 implements.

## Before (Without Structure Navigation)

This is what the context builder showed BEFORE the enhancement:

```markdown
### github-issue
Fetches issue data from GitHub API

**Inputs**: `repo: str`, `issue_number: int`
**Outputs**: `issue_data: dict`, `error: str` (error)
**Parameters**: `token: str`
```

The planner sees `issue_data: dict` but has NO IDEA what's inside it!

## After (With Structure Navigation)

This is what the context builder shows AFTER the enhancement:

```markdown
### github-issue
Fetches issue data from GitHub API

**Inputs**: `repo: str`, `issue_number: int`
**Outputs**: `issue_data: dict` - Navigate: .number, .title, .user, .user.login, .user.id, `error: str` (error)
**Parameters**: `token: str`
```

Now the planner KNOWS it can access:
- `issue_data.number`
- `issue_data.title`
- `issue_data.user.login`
- etc.

## The Metadata Behind This

The metadata extractor (from 14.1) provides:
```python
{
    "key": "issue_data",
    "type": "dict",
    "description": "",
    "structure": {
        "number": {"type": "int", "description": "Issue number"},
        "title": {"type": "str", "description": "Issue title"},
        "user": {
            "type": "dict",
            "description": "Author info",
            "structure": {
                "login": {"type": "str", "description": "GitHub username"},
                "id": {"type": "int", "description": "User ID"}
            }
        }
    }
}
```

## The Code That Does This

In `_format_node_section()`:
```python
# For each output
if isinstance(out, dict):
    key = out["key"]
    type_str = out.get("type", "any")

    # Base format
    output_str = f"`{key}: {type_str}`"

    # NEW: Add navigation hints for complex types
    if type_str in ("dict", "list", "list[dict]") and "structure" in out:
        paths = _extract_navigation_paths(out["structure"])
        if paths:
            nav_hints = ", ".join(f".{p}" for p in paths[:5])
            output_str += f" - Navigate: {nav_hints}"
```

## Why This Matters

Without navigation hints:
- Planner: "I see issue_data is a dict, but I don't know what's in it"
- Result: Can't generate `shared["issue_data"]["user"]["login"]`

With navigation hints:
- Planner: "I see issue_data.user.login is available"
- Result: Can correctly generate proxy mapping paths

## The Limit System

To prevent context overflow with many complex nodes:
- First 30 dict/list types get navigation hints
- After that, just show the type without hints
- This keeps output under 50KB limit

## Real-World Impact

This enhancement enables Task 17 (the planner) to:
1. Understand complex data structures
2. Generate valid proxy mapping paths
3. Connect nodes that work with nested data
4. Create more sophisticated workflows

Without this, the planner is "blind" to structure!
