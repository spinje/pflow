# Revised Approach: Nested Template Path Validation

## Overview
Instead of HTTP node extraction, we use nested template variables with runtime path validation.

## Key Change: Template Path Detection

### Before (Extraction Approach)
```json
{
  "name": "http",
  "params": {
    "url": "https://api.github.com/users/torvalds",
    "extract": {
      "username": "$.login",
      "biography": "$.bio"
    }
  }
}
// Downstream: ${http.extracted.username}
```

### After (Nested Template Approach)
```json
{
  "name": "http",
  "params": {
    "url": "https://api.github.com/users/torvalds"
  }
}
// Downstream: ${http.response.login}
```

## How The Learning Loop Works

### 1. Initial Attempt (Planner Guesses)
```json
{
  "name": "llm",
  "params": {
    "prompt": "User ${http.response.username} has bio: ${http.response.biography}"
  }
}
```

### 2. Runtime Validation Detects Missing Paths
- Missing: `${http.response.username}`
- Missing: `${http.response.biography}`
- Available at `http.response`: `login`, `bio`, `name`, `id`, `avatar_url`, etc.

### 3. Planner Corrects Template Paths
```json
{
  "name": "llm",
  "params": {
    "prompt": "User ${http.response.login} has bio: ${http.response.bio}"
  }
}
```

## RuntimeValidationNode Implementation

### Core Responsibilities
1. Execute candidate workflow with fresh shared store
2. Detect missing template paths by comparing IR templates to actual shared store
3. Build helpful error messages with available paths
4. Route actions based on errors found

### Error Detection Mechanisms

#### 1. Exception Handling
```python
# Catch any exception during workflow execution
try:
    result = flow.run(shared_child)
except Exception as e:
    # Classify as fixable or fatal
```

#### 2. Namespaced Error Detection
```python
# Check for errors in node namespaces
for node_id, node_data in shared_after.items():
    if isinstance(node_data, dict) and "error" in node_data:
        # Node reported an error
```

#### 3. Missing Template Path Detection
```python
# Extract all ${node.path} references from IR
templates = extract_templates_from_ir(workflow_ir)

# Check each template path exists
for template in templates:
    if not path_exists_in_shared(template, shared_after):
        # Build error with available paths
        available = get_available_paths_at_level(template, shared_after)
        errors.append({
            "category": "missing_template_path",
            "attempted": template,
            "available": available
        })
```

### Path Discovery Helper
```python
def get_available_paths(shared: dict, node_id: str, partial_path: str) -> list[str]:
    """Get available paths at a given level.

    Example:
    - shared = {"http": {"response": {"login": "torvalds", "bio": "..."}}}
    - node_id = "http"
    - partial_path = "response"
    - Returns: ["login", "bio"]
    """
    # Navigate to the level
    current = shared.get(node_id, {})
    for part in partial_path.split("."):
        if isinstance(current, dict):
            current = current.get(part, {})
        else:
            return []

    # Return available keys at this level
    if isinstance(current, dict):
        return list(current.keys())
    return []
```

## Benefits of This Approach

1. **Simpler**: No extraction logic in HTTP node
2. **More Flexible**: Access any nested field without pre-declaration
3. **Natural**: Uses existing template syntax
4. **Discoverable**: Runtime feedback shows available paths
5. **Universal**: Works for all nodes, not just HTTP

## Example Runtime Error
```json
{
  "source": "template",
  "node_id": "http",
  "category": "missing_template_path",
  "attempted": "${http.response.username}",
  "available": ["login", "bio", "name", "id", "avatar_url", "html_url"],
  "message": "Template path '${http.response.username}' not found. Available fields at 'http.response': login, bio, name, id, avatar_url, html_url"
}
```

## Implementation Steps

1. ✅ Keep HTTP node as-is (no extraction)
2. ⏳ Implement RuntimeValidationNode with template path detection
3. ⏳ Wire into planner flow
4. ⏳ Update WorkflowGeneratorNode to handle template path errors
5. ⏳ Write tests for the new approach