# Bug Report: Namespace Collision with Parameter Names

**Severity:** High
**Component:** Runtime (namespaced_store.py, node parameter fallback pattern)
**Discovered:** 2024-12-30
**Updated:** 2024-12-30 (added workflow input collision)
**Status:** Open

## Summary

There are **two sources** of namespace collision that cause silent failures:

### 1. Node ID Collision (Original Discovery)
When a workflow node has an ID that matches a parameter name used by another node (e.g., a node named `images` and the LLM node's `images` parameter), the parameter fallback pattern silently uses the wrong value - returning the node's namespace dict instead of the intended parameter value.

### 2. Workflow Input Collision (New Discovery)
When a workflow **input** has a name that matches a parameter name used by a node (e.g., input named `url` and the HTTP node's `url` parameter), the node uses the raw input value instead of the template-resolved parameter.

**Example:**
- Workflow input: `url = "https://example.com"`
- HTTP node param: `"url": "https://r.jina.ai/${url}"`
- Expected: HTTP calls `https://r.jina.ai/https://example.com`
- Actual: HTTP calls `https://example.com` (ignores template!)

Both cause **silent failures** that are extremely difficult to debug because:
1. No error is raised during template resolution
2. The wrong value type causes cryptic errors deep in node execution
3. The connection between naming and parameter collision is non-obvious

## Root Cause Analysis

### The Parameter Fallback Pattern

Most pflow nodes use this pattern to allow parameters to be passed via shared store OR node params:

```python
# Example from LLM node (src/pflow/nodes/llm/llm.py:124)
images = shared.get("images") if "images" in shared else self.params.get("images", [])
```

This pattern is documented in `src/pflow/nodes/CLAUDE.md`:
```python
file_path = shared.get("file_path") or self.params.get("file_path")  # Always do this
```

### How Namespacing Works

With automatic namespacing enabled (Task 9), node outputs are stored at `shared[node_id][output_key]`:

```python
# NamespacedNodeWrapper writes to:
shared["my-node"]["stdout"] = "output value"
shared["my-node"]["stderr"] = ""
shared["my-node"]["exit_code"] = 0
```

This creates a dict at `shared["my-node"]`.

### The Collision

When checking `"images" in shared`:

1. **Expected behavior:** Check if workflow input `images` exists
2. **Actual behavior:** Returns `True` if ANY node has id `images` (because `shared["images"]` is the namespace dict)

Then `shared.get("images")` returns the **namespace dict** `{stdout: ..., stderr: ..., exit_code: ...}` instead of the **parameter value**.

### Why NamespacedSharedStore Doesn't Prevent This

The `NamespacedSharedStore.keys()` method (line 132-144) combines namespace keys with root keys:

```python
def keys(self) -> set[str]:
    namespace_keys = set(self._parent[self._namespace].keys())
    root_keys = set(self._parent.keys())
    root_keys.discard(self._namespace)  # Only discards OWN namespace
    return namespace_keys | root_keys
```

It only discards its OWN namespace key, not OTHER node namespaces. So when iterating over shared or checking `in`, other node namespace dicts are visible.

## Steps to Reproduce

### Minimal Reproduction

```json
{
  "inputs": {
    "url": {"type": "string", "required": true}
  },
  "nodes": [
    {
      "id": "fetch",
      "type": "shell",
      "params": {"command": "echo 'test'"}
    },
    {
      "id": "images",
      "type": "shell",
      "params": {"command": "echo '[\"https://example.com/image.png\"]'"}
    },
    {
      "id": "analyze",
      "type": "llm",
      "batch": {"items": "${images.stdout}"},
      "params": {
        "prompt": "Describe this image",
        "images": "${item}"
      }
    }
  ],
  "edges": [
    {"from": "fetch", "to": "images"},
    {"from": "images", "to": "analyze"}
  ]
}
```

### Expected Behavior

The LLM node receives `images` parameter as the URL string `"https://example.com/image.png"`.

### Actual Behavior

The LLM node receives `images` as the namespace dict:
```python
{
  "stdout": "[\"https://example.com/image.png\"]",
  "stdout_is_binary": False,
  "stderr": "",
  "stderr_is_binary": False,
  "exit_code": 0,
  "command": "echo '[\"https://example.com/image.png\"]'"
}
```

This causes the error:
```
Image must be a string (URL or path), got: dict
```

### Execution Flow

1. Node `images` executes, stores output at `shared["images"] = {stdout: ..., ...}`
2. Batch node extracts items from `${images.stdout}` correctly
3. Template resolution sets `self.params["images"] = "https://..."` correctly
4. **BUG:** LLM node's `prep()` checks `"images" in shared` → `True`
5. Returns `shared.get("images")` → namespace dict instead of param
6. LLM node fails trying to use dict as image URL

## Affected Nodes and Parameters

**Complete list of vulnerable parameters** (from codebase search):

| Node Type | Vulnerable Parameters |
|-----------|----------------------|
| `http` | `url`, `method`, `body`, `headers`, `params`, `timeout`, `auth_token`, `api_key` |
| `llm` | `prompt`, `system`, `images` |
| `write-file` | `content`, `file_path`, `encoding`, `content_is_binary` |
| `read-file` | `file_path`, `encoding` |
| `copy-file` | `source_path`, `dest_path` |
| `move-file` | `source_path`, `dest_path` |
| `delete-file` | `file_path` |
| `shell` | `stdin` |
| `claude-code` | `prompt`, `output_schema` |
| `git-push` | `branch`, `remote`, `working_directory` |
| `git-status` | `working_directory` |
| `git-log` | `since`, `until`, `author`, `grep`, `path`, `working_directory` |
| `git-checkout` | `branch`, `create`, `base`, `force`, `stash`, `working_directory` |
| `git-commit` | `message`, `files`, `working_directory` |
| `git-get-latest-tag` | `pattern`, `working_directory` |
| `github-get-issue` | `issue_number`, `repo` |
| `github-list-issues` | `repo`, `state`, `limit`, `since` |
| `github-list-prs` | `repo`, `state`, `limit` |
| `github-create-pr` | `title`, `body`, `head`, `base`, `repo` |
| `test-echo` | `message`, `count`, `data` |

**High-risk names to avoid for node IDs AND workflow inputs:**
- `url`, `images`, `prompt`, `content`, `body`, `data`
- `file_path`, `source_path`, `dest_path`, `path`
- `message`, `title`, `repo`, `branch`, `base`, `head`
- `stdin`, `command`, `headers`, `params`, `timeout`
- `state`, `limit`, `count`, `files`, `pattern`

## Impact

1. **Silent failures:** No warning when collision occurs
2. **Cryptic errors:** Type mismatch errors deep in node execution
3. **Non-obvious cause:** Users won't connect node naming to the failure
4. **Workflow breakage:** Previously working workflows can break by adding/renaming nodes
5. **Batch mode especially affected:** Batch params like `${item}` are correctly resolved but then overwritten by shared lookup

## Workaround

### For Node IDs
Avoid using these node IDs:
- Any name that matches a parameter used by downstream nodes
- Prefer descriptive names like `extract-images` instead of `images`

### For Workflow Inputs
Avoid using these input names:
- Any name that matches a parameter used by nodes in the workflow
- Prefer descriptive names like `target_url` instead of `url`

**Example fix for input collision:**
```json
// Before (broken):
{
  "inputs": {"url": {"type": "string"}},
  "nodes": [{"id": "fetch", "type": "http", "params": {"url": "https://api.example.com/${url}"}}]
}

// After (works):
{
  "inputs": {"target_url": {"type": "string"}},
  "nodes": [{"id": "fetch", "type": "http", "params": {"url": "https://api.example.com/${target_url}"}}]
}
```

## Proposed Fixes

### Option 1: Filter Node Namespaces from Root Keys (Recommended)

Modify `NamespacedSharedStore.keys()` to exclude ALL node namespace dicts, not just own:

```python
def keys(self) -> set[str]:
    namespace_keys = set(self._parent[self._namespace].keys())
    root_keys = set(self._parent.keys())

    # Filter out all node namespace dicts (they have specific structure)
    root_keys = {k for k in root_keys if not self._is_node_namespace(k)}

    return namespace_keys | root_keys

def _is_node_namespace(self, key: str) -> bool:
    """Check if a root key is a node namespace dict."""
    if key.startswith("__") and key.endswith("__"):
        return False  # Special keys are not namespaces
    value = self._parent.get(key)
    if not isinstance(value, dict):
        return False
    # Node namespaces have specific output keys
    return any(k in value for k in ("stdout", "response", "result", "content"))
```

**Pros:**
- Preserves existing semantics
- Fixes collision without changing node code
- Backward compatible

**Cons:**
- Heuristic-based detection of node namespaces
- Might need maintenance as new output patterns emerge

### Option 2: Invert Parameter Priority

Change parameter fallback to check params first:

```python
# Before (vulnerable):
images = shared.get("images") if "images" in shared else self.params.get("images", [])

# After (safe):
images = self.params.get("images") if "images" in self.params else shared.get("images", [])
```

**Pros:**
- Simple, clear fix
- No heuristics

**Cons:**
- **Breaking change:** Changes semantics of how workflow inputs work
- Workflow inputs via shared store would no longer override params
- Would need to update all nodes

### Option 3: Add Collision Detection

Add validation during compilation to detect and warn about collisions:

```python
def _check_parameter_collisions(nodes: list, edges: list):
    node_ids = {n["id"] for n in nodes}
    for node in nodes:
        for param_name in node.get("params", {}).keys():
            if param_name in node_ids:
                # Check if the colliding node executes before this one
                if _is_upstream(param_name, node["id"], edges):
                    raise ValidationError(
                        f"Node '{node['id']}' parameter '{param_name}' collides with "
                        f"upstream node ID '{param_name}'. Rename the node to avoid collision."
                    )
```

**Pros:**
- Explicit error with clear fix suggestion
- No behavior change

**Cons:**
- Only catches collisions at compile time with known param names
- Doesn't fix runtime behavior

### Option 4: Explicit Namespace Prefix

Require explicit prefix to access node outputs:

```python
# Instead of shared["images"] being the namespace
# Use shared["node:images"] or shared["@images"]
```

**Pros:**
- Clear separation
- No ambiguity

**Cons:**
- **Major breaking change**
- Would require updating all existing workflows

## Recommendation

**Implement Option 1 (filter namespaces) + Option 3 (collision detection):**

1. Short-term: Add collision detection to warn users immediately
2. Medium-term: Filter node namespaces from root-level visibility
3. Document the issue and workaround in CLAUDE.md and user docs

## Files to Modify

1. `src/pflow/runtime/namespaced_store.py` - Filter node namespaces
2. `src/pflow/runtime/compiler.py` - Add collision detection
3. `src/pflow/nodes/CLAUDE.md` - Document the issue
4. All nodes using fallback pattern - Consider inverting priority (if Option 2 chosen)

## Test Cases Needed

```python
def test_node_id_does_not_collide_with_downstream_params():
    """Node named 'images' should not affect LLM node's images param."""
    workflow = {
        "nodes": [
            {"id": "images", "type": "shell", "params": {"command": "echo '[]'"}},
            {"id": "llm", "type": "llm", "params": {"prompt": "test", "images": []}}
        ],
        "edges": [{"from": "images", "to": "llm"}]
    }
    # Should not raise "Image must be a string, got: dict"

def test_namespaced_store_keys_excludes_node_namespaces():
    """NamespacedSharedStore.keys() should not expose other node namespaces."""
    shared = {"images": {"stdout": "test"}, "workflow_input": "value"}
    store = NamespacedSharedStore(shared, "my-node")
    assert "images" not in store.keys()  # Node namespace filtered
    assert "workflow_input" in store.keys()  # Real input visible

def test_collision_detection_warns_on_compile():
    """Compiler should warn when node ID matches downstream param name."""
    # Should raise or warn about collision
```

## References

- Discovery context: Building `webpage-to-markdown-simple.json` workflow
- Related: Task 9 (Implement shared store collision detection using automatic namespacing)
- Affected: All nodes using parameter fallback pattern
- Trace file: `~/.pflow/debug/workflow-trace-20251230-021205.json`
