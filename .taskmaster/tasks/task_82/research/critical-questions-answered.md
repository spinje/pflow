# Critical Questions Answered: Namespacing and Base64 Encoding

## Question 1: With namespacing enabled, how are node outputs stored?

### Answer: Outputs are stored in `shared[node_id][key]` - NOT in `shared[key]`

**Code Evidence** (`namespaced_store.py:43-48`):
```python
def __setitem__(self, key: str, value: Any) -> None:
    """Write to the namespaced location.

    All writes go to shared[namespace][key] to prevent collisions.
    """
    self._parent[self._namespace][key] = value
```

### Example: HTTP Node Writes

When HTTP node (with id "download") executes:
```python
# Inside HTTP node's post() method:
shared["response"] = base64_string
shared["status_code"] = 200
shared["response_headers"] = headers
```

**Actual storage location**:
```python
shared = {
    "download": {                          # ← node_id becomes namespace
        "response": "<base64_string>",
        "status_code": 200,
        "response_headers": {...},
    }
}
```

**NOT**:
```python
shared = {
    "response": "<base64_string>",         # ❌ WRONG - This never happens
    "status_code": 200,
    "response_headers": {...},
}
```

---

## Question 2: How can write-file access HTTP's metadata?

### Answer: Write-file CANNOT directly access HTTP's namespace - Template variables required

**Code Evidence** (`namespaced_store.py:50-69`):
```python
def __getitem__(self, key: str) -> Any:
    """Read with namespace priority, falling back to root.

    Check order:
    1. shared[namespace][key] - For self-reading nodes
    2. shared[key] - For CLI inputs, legacy data

    Raises:
        KeyError: If key not found in namespace or root
    """
    # Check own namespace first
    if key in self._parent[self._namespace]:
        return self._parent[self._namespace][key]

    # Fall back to root level
    if key in self._parent:
        return self._parent[key]

    raise KeyError(...)
```

### Read Priority for Write-File Node

When write-file tries to read `shared["response_encoding"]`:

1. **Check own namespace**: `shared["write_file_id"]["response_encoding"]` ❌
2. **Check root level**: `shared["response_encoding"]` ❌
3. **Never checks**: `shared["http_node_id"]["response_encoding"]` ❌ BY DESIGN

### Data Flow Visualization

```
After HTTP node:
shared = {
    "download": {
        "response": "iVBORw0KG...",
        "response_encoding": "base64",     ← ISOLATED HERE
    }
}

Write-file node reads shared["response_encoding"]:
  Step 1: Check shared["write"]["response_encoding"]  → Not found
  Step 2: Check shared["response_encoding"]           → Not found
  Result: KeyError or returns None
```

### The ONLY Way: Template Variables

**In workflow IR**:
```json
{
  "id": "write",
  "type": "write-file",
  "params": {
    "content": "${download.response}",                              ← WORKS
    "encoding_hint": "${download.response_headers.content-type}"    ← WORKS
  }
}
```

**Why this works**:
- Template resolver has access to FULL shared store (all namespaces)
- `${download.response}` explicitly says "look in 'download' namespace"
- Resolution happens BEFORE node execution
- Result is passed as parameter to node

**Template resolution code** (`template_resolver.py:173-240`):
```python
def resolve_value(var_name: str, context: dict[str, Any]) -> Optional[Any]:
    """Resolve 'data.field' → context['data']['field']"""
    if "." in var_name:
        parts = var_name.split(".")
        value = context
        for part in parts:
            value = value[part]  # Direct namespace access
        return value
```

---

## Question 3: Template variable resolution with namespacing

### Answer: `${download.response}` → `shared["download"]["response"]` (direct access)

**Wrapper Chain** (from `runtime/CLAUDE.md`):
```
InstrumentedNodeWrapper._run()
  └→ NamespacedNodeWrapper._run()
      └→ TemplateAwareNodeWrapper._run()  ← TEMPLATE RESOLUTION HAPPENS HERE
          └→ ActualNode._run()
```

### Resolution Process

**Step 1: Template Resolution** (`node_wrapper.py` - TemplateAwareNodeWrapper)
```python
def _run(self, shared: dict[str, Any]) -> Any:
    # Resolve templates with FULL shared store access
    context = {**shared, **self.initial_params}
    resolved = TemplateResolver.resolve_nested(self.template_params, context)

    # Pass resolved values as regular parameters
    self.inner_node.set_params({**self.static_params, **resolved})

    return self.inner_node._run(shared)
```

**Step 2: Namespace Access** (Template resolver has direct access)
```python
# Template: "${download.response}"
parts = ["download", "response"]
value = shared["download"]["response"]  # Direct dictionary access - no proxy!
```

**Step 3: Node Execution** (Node receives resolved value)
```python
# Write-file node sees:
self.params = {
    "content": "<actual_base64_string>",  # ← Already resolved
    "file_path": "/tmp/output.png"
}
```

### Key Point: Templates Bypass Namespacing

- **Template resolver**: Has full `shared` dict → can access any namespace
- **Node execution**: Has `NamespacedSharedStore` proxy → limited to own namespace + root
- **Result**: Templates are the ONLY cross-namespace communication mechanism

---

## Question 4: Metadata passing patterns

### Answer: NO existing cross-node metadata patterns exist

**Evidence**: Grep search found ONLY ONE metadata usage:
```python
# claude/claude_code.py:754
shared["_claude_metadata"] = metadata
```

This is **NOT cross-node communication** - it's for observability:
- Written for external systems to read AFTER workflow completes
- No other node reads this during execution
- Works because external code has full `shared` dict

### Why No Cross-Node Metadata?

**Design Decision**: Namespacing prevents cross-namespace reads

From `namespaced_store.py` design:
```python
class NamespacedSharedStore:
    """Proxy that namespaces all node writes while maintaining backward compatibility.

    This proxy ensures that all writes from a node go to shared[node_id][key]
    while reads check both the namespace and root level for backward compatibility
    with CLI inputs and legacy data.
    """
```

**Reads only check**:
1. Own namespace: `shared[own_node_id][key]`
2. Root level: `shared[key]`
3. **NEVER other namespaces**: `shared[other_node_id][key]` ❌

---

## Solution: How Write-File Should Detect Base64

### Recommended: Convention-Based Detection (Already Implemented)

**Write-file node logic**:
```python
def prep(self, shared: dict) -> tuple:
    content = shared.get("content") or self.params.get("content")

    # Auto-detect base64 encoding
    if isinstance(content, str) and self._looks_like_base64(content):
        import base64
        content = base64.b64decode(content)

    return content, file_path, encoding

def _looks_like_base64(self, text: str) -> bool:
    """Check if text looks like base64 encoded data."""
    # Base64 alphabet: A-Za-z0-9+/= with padding
    if len(text) < 20:
        return False
    if not all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=" for c in text):
        return False
    # Check for padding
    padding = text.count("=")
    if padding > 2:
        return False
    return True
```

**Why this works**:
- No namespacing issues (operates on resolved template values)
- No metadata passing required
- Transparent to planner
- Handles 99% of binary file downloads

### Alternative: Explicit Encoding Hint (If Needed)

**Workflow IR**:
```json
{
  "nodes": [
    {
      "id": "download",
      "type": "http",
      "params": {"url": "https://example.com/image.png"}
    },
    {
      "id": "write",
      "type": "write-file",
      "params": {
        "content": "${download.response}",
        "file_path": "/tmp/output.png",
        "__encoding_hint": "${download.response_headers.content-transfer-encoding}"
      }
    }
  ]
}
```

**Write-file implementation**:
```python
def prep(self, shared: dict) -> tuple:
    content = shared.get("content") or self.params.get("content")

    # Check explicit hint first (from template resolution)
    encoding_hint = self.params.get("__encoding_hint", "")

    if encoding_hint == "base64":
        import base64
        content = base64.b64decode(content)
    elif isinstance(content, str) and self._looks_like_base64(content):
        # Fallback to detection
        import base64
        content = base64.b64decode(content)

    return content, file_path, encoding
```

---

## Key Architectural Insights

1. **Namespacing is strict isolation by design**
   - Prevents namespace collisions
   - No cross-namespace reads during node execution

2. **Template variables are the ONLY cross-namespace bridge**
   - Resolver has full shared store access
   - Must be explicit: `${node_id.key}`
   - Resolution happens before node execution

3. **Metadata passing requires templates**
   - Direct shared store reads cannot access other namespaces
   - No "side channel" for metadata communication
   - Must pass through template variables in IR

4. **Convention-based detection avoids complexity**
   - Works with namespacing limitations
   - No planner changes required
   - Transparent to users

---

## Final Answer: How Write-File Detects Base64 with Namespacing

**Direct Answer**: Write-file CANNOT detect encoding metadata written by HTTP node.

**Why**: Namespacing isolates `shared["http_node_id"]["response_encoding"]` from write-file's namespace.

**Solution**: Write-file must either:
1. **Auto-detect** base64 from content heuristics (RECOMMENDED)
2. **Accept explicit hint** via template: `"__encoding_hint": "${download.response_headers.content-type}"`

**Data flow**:
```
HTTP writes → shared["download"]["response"] = base64_string
                   ↓
Template resolution: "${download.response}" → base64_string
                   ↓
Write-file receives: params["content"] = base64_string
                   ↓
Write-file detects: _looks_like_base64(content) → True
                   ↓
Write-file decodes: base64.b64decode(content) → binary data
```

**No metadata passing occurs** - content flows through template variables, detection happens at destination node.
