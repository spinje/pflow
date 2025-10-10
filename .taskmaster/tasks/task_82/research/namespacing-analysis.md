# Namespacing Analysis for Base64 Encoding Solution

## Executive Summary

**CRITICAL FINDING**: Metadata passing between nodes WILL NOT WORK with current namespacing design.

The proposed solution to have HTTP node write `shared["response_encoding"] = "base64"` and have write-file detect it is **fundamentally broken** by the namespacing system.

## How Namespacing Actually Works

### 1. Node Writes Are Namespaced

When HTTP node writes to shared store:

```python
# HTTP node executes with NamespacedSharedStore proxy
shared["response"] = base64_string           # Actually writes to: shared["http_node_id"]["response"]
shared["response_encoding"] = "base64"       # Actually writes to: shared["http_node_id"]["response_encoding"]
```

**Source**: `namespaced_store.py:43-48`
```python
def __setitem__(self, key: str, value: Any) -> None:
    """Write to the namespaced location.

    All writes go to shared[namespace][key] to prevent collisions.
    """
    self._parent[self._namespace][key] = value
```

### 2. Node Reads Check Namespace THEN Root

When write-file tries to read:

```python
# Write-file node executes with its own NamespacedSharedStore proxy
encoding = shared.get("response_encoding")    # Checks: shared["write_file_node_id"]["response_encoding"]
                                              # Then falls back to: shared["response_encoding"]
                                              # NEVER checks: shared["http_node_id"]["response_encoding"]
```

**Source**: `namespaced_store.py:50-69`
```python
def __getitem__(self, key: str) -> Any:
    """Read with namespace priority, falling back to root.

    Check order:
    1. shared[namespace][key] - For self-reading nodes or namespaced data
    2. shared[key] - For CLI inputs, legacy data, or cross-node reads

    Raises:
        KeyError: If key not found in namespace or root
    """
    # Check own namespace first
    if key in self._parent[self._namespace]:
        return self._parent[self._namespace][key]

    # Fall back to root level
    if key in self._parent:
        return self._parent[self._namespace]

    raise KeyError(f"Key '{key}' not found in namespace '{self._namespace}' or root")
```

### 3. Template Resolution Uses Explicit Node References

Template variables like `${http_node_id.response}` resolve BEFORE nodes execute:

```python
# Template resolver accesses shared store directly (not through NamespacedSharedStore)
# When resolving: "${download.response}"
context = shared  # Full shared store with all namespaces
value = context["download"]["response"]  # Direct access to namespace
```

**Source**: `template_resolver.py:173-240`
```python
@staticmethod
def resolve_value(var_name: str, context: dict[str, Any]) -> Optional[Any]:
    """Resolve a variable name (possibly with path and array indices) from context.

    Handles path traversal for nested data access:
    - 'url' -> context['url']
    - 'data.field' -> context['data']['field']
    - 'data.items[0]' -> context['data']['items'][0]
    """
    if "." in var_name or "[" in var_name:
        parts = re.split(r"\.(?![^\[]*\])", var_name)
        value = context

        for part in parts:
            # Traverse the path...
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        return value
```

## Why Metadata Passing Fails

### The Problem

1. **HTTP node writes** → `shared["http_node_id"]["response_encoding"] = "base64"`
2. **Write-file reads** → Checks `shared["write_file_id"]["response_encoding"]` (not found)
3. **Write-file reads** → Checks `shared["response_encoding"]` (not found)
4. **Result**: Write-file NEVER sees the encoding marker

### Visual Data Flow

```
After HTTP node executes:
shared = {
    "http_node_id": {
        "response": "<base64_string>",
        "response_encoding": "base64",        ← ISOLATED IN NAMESPACE
        "status_code": 200,
        ...
    }
}

When write-file reads shared["response_encoding"]:
1. Check shared["write_file_id"]["response_encoding"]  ❌ Not found
2. Check shared["response_encoding"]                    ❌ Not found
3. Never checks shared["http_node_id"]["response_encoding"] ❌ BY DESIGN
```

## How Template Variables ARE Different

Template variables work because they use EXPLICIT node references:

```json
{
  "id": "write",
  "type": "write-file",
  "params": {
    "content": "${download.response}",         ← EXPLICIT: Look in "download" namespace
    "file_path": "${download.response_headers.filename}"  ← EXPLICIT PATH
  }
}
```

**Resolution happens at runtime**:
```python
# TemplateAwareNodeWrapper resolves templates BEFORE node executes
# Template: "${download.response}"
node_id = "download"  # First part before dot
path = "response"     # Path after dot

# Direct access to namespace in shared store
value = shared[node_id][path]  # shared["download"]["response"]
```

## Existing Metadata Pattern (Claude Code Node)

Only ONE node in the codebase uses metadata: `claude/claude_code.py`

```python
# Lines 14, 95, 754
shared["_claude_metadata"] = metadata  # Writes to: shared["node_id"]["_claude_metadata"]
```

This ONLY works because:
1. It's for observability (not inter-node communication)
2. External systems access full `shared` dict after workflow completes
3. No other node needs to read `_claude_metadata` during execution

## Valid Solutions

### Option 1: Explicit Template Variable (RECOMMENDED)

**HTTP node writes everything as before**:
```python
shared["response"] = base64_string
shared["status_code"] = 200
shared["response_headers"] = headers
```

**Write-file uses template for encoding check**:
```json
{
  "id": "write",
  "type": "write-file",
  "params": {
    "content": "${download.response}",
    "file_path": "/tmp/output.png",
    "__encoding_hint": "${download.response_headers.content-transfer-encoding}"
  }
}
```

**Write-file implementation**:
```python
def prep(self, shared: dict) -> tuple:
    content = shared.get("content") or self.params.get("content")

    # Check if planner provided encoding hint via template
    encoding_hint = self.params.get("__encoding_hint", "")

    if encoding_hint == "base64":
        import base64
        content = base64.b64decode(content)

    return content, file_path, ...
```

**Pros**:
- Works with namespacing
- Planner has visibility into HTTP headers
- Explicit in IR

**Cons**:
- Requires planner to detect base64 in response headers
- Not all APIs include `content-transfer-encoding` header

### Option 2: Convention-Based Detection (CURRENT IMPLEMENTATION)

**Write-file detects base64 automatically**:
```python
def prep(self, shared: dict) -> tuple:
    content = shared.get("content") or self.params.get("content")

    if isinstance(content, str) and self._looks_like_base64(content):
        import base64
        content = base64.b64decode(content)

    return content, file_path, ...
```

**Pros**:
- No namespacing issues
- Works transparently
- No planner changes needed

**Cons**:
- Heuristic detection can have false positives
- Not explicit about intent

### Option 3: Root-Level Metadata (BREAKS NAMESPACING)

**HTTP node writes to root**:
```python
def post(self, shared, prep_res, exec_res):
    # Namespaced writes
    shared["response"] = exec_res["response"]
    shared["status_code"] = exec_res["status_code"]

    # HACK: Bypass namespacing by accessing parent store
    # This is a VIOLATION of the namespacing architecture
    self._parent[f"__{self._node_id}__encoding"] = "base64"
```

**Cons**:
- Violates namespacing architecture
- Nodes shouldn't know about namespacing
- Creates new collision risks
- NOT RECOMMENDED

## Recommendation

**Use Option 2 (Convention-Based Detection)** - Already implemented and working.

**Rationale**:
1. Namespacing makes metadata passing architecturally complex
2. Base64 detection is reliable with proper heuristics
3. No changes needed to planner or other nodes
4. Transparent to users

**Future Enhancement** (if needed):
- Add `__encoding_hint` parameter support for explicit cases
- Let planner extract from response headers when available
- Falls back to detection when hint not provided

## Key Takeaways

1. **Namespacing isolates node outputs by design** - Nodes cannot read each other's namespace
2. **Template variables are the ONLY cross-namespace communication** - Must be explicit with `${node_id.key}`
3. **Metadata passing requires template variables** - No other mechanism exists
4. **Convention-based detection avoids namespacing complexity** - Best for binary encoding
