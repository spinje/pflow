# Error Response Data Storage Pattern Analysis

## Critical Question
When `_build_error_list()` executes at line 248 in `src/pflow/execution/executor_service.py`, is the error data still available in the shared store?

## Answer: YES - Data is Available in Namespaced Location

**TL;DR**: Both HTTP and MCP nodes write error data through the NamespacedSharedStore wrapper, which redirects writes to `shared[node_id][key]`. Error extraction already handles this correctly via `_extract_node_level_error()`. Data is fully accessible at line 248.

---

## 1. HTTP Node Storage Pattern

### Location: `/Users/andfal/projects/pflow-feat-cli-agent-workflow/src/pflow/nodes/http/http.py`

#### Where HTTP stores response data:

**Lines 168-183 (`post()` method)**:
```python
def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
    """Store results and determine action."""
    # Always store response data
    shared["response"] = exec_res["response"]              # WRITES TO ROOT
    shared["status_code"] = exec_res["status_code"]        # WRITES TO ROOT
    shared["response_headers"] = exec_res["headers"]       # WRITES TO ROOT
    shared["response_time"] = exec_res.get("duration", 0)  # WRITES TO ROOT

    # Determine action based on status code
    status = exec_res["status_code"]
    if 200 <= status < 300:
        return "default"  # Success
    else:
        # HTTP errors are valid responses, not exceptions
        shared["error"] = f"HTTP {status}"                 # WRITES TO ROOT
        return "error"  # Return error action for workflow routing
```

#### Key Findings:
- **Node intent**: Write directly to `shared["key"]` (appears to be root level)
- **Error storage**: `shared["error"] = f"HTTP {status}"`
- **Status code**: `shared["status_code"] = exec_res["status_code"]`
- **Response data**: `shared["response"] = exec_res["response"]`
- **BUT**: Wrapper intercepts these writes!

---

## 2. MCP Node Storage Pattern

### Location: `/Users/andfal/projects/pflow-feat-cli-agent-workflow/src/pflow/nodes/mcp/node.py`

#### Where MCP stores result data:

**Lines 341-422 (`post()` method)**:
```python
def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
    """Store results in shared store and determine next action."""

    # Check for protocol/execution errors
    if "error" in exec_res:
        # Store error in shared store
        shared["error"] = exec_res["error"]                 # WRITES TO ROOT
        shared["error_details"] = {                          # WRITES TO ROOT
            "server": prep_res["server"],
            "tool": prep_res["tool"],
            "timeout": exec_res.get("timeout", False),
        }
        logger.error(f"MCP tool failed: {exec_res['error']}", extra=shared["error_details"])
        return "default"  # WORKAROUND: Return "default" instead of "error"

    # Get the result
    result = exec_res.get("result")

    # Check for tool-level errors (from isError flag)
    if isinstance(result, dict) and result.get("is_tool_error"):
        shared["error"] = result.get("error", "Tool execution failed")  # WRITES TO ROOT
        shared["error_details"] = {                          # WRITES TO ROOT
            "server": prep_res["server"],
            "tool": prep_res["tool"],
            "is_tool_error": True
        }
        logger.warning(f"MCP tool returned error: {shared['error']}", extra=shared["error_details"])
        return "error"  # Trigger repair system

    # Store successful result
    shared["result"] = result                                # WRITES TO ROOT

    # For structured data, extract top-level fields
    if isinstance(result, dict) and not result.get("error"):
        for key, value in result.items():
            if not key.startswith("_") and not key.startswith("is_"):
                shared[key] = value                          # WRITES TO ROOT (each field)

    # Store result with server-specific key
    result_key = f"{prep_res['server']}_{prep_res['tool']}_result"
    shared[result_key] = result                              # WRITES TO ROOT

    return "default"
```

#### Key Findings:
- **Node intent**: Write directly to `shared["key"]` (appears to be root level)
- **Error storage**: `shared["error"] = exec_res["error"]`
- **Error details**: `shared["error_details"] = {...}` (includes server/tool)
- **Result data**: `shared["result"] = result`
- **BUT**: Wrapper intercepts these writes!

---

## 3. Namespaced Wrapper Impact (THE KEY INSIGHT!)

### Location: `/Users/andfal/projects/pflow-feat-cli-agent-workflow/src/pflow/runtime/namespaced_wrapper.py`

### How namespacing redirects writes:

**Lines 34-50 (`_run()` method)**:
```python
def _run(self, shared: dict[str, Any]) -> Any:
    """Execute the node with a namespaced shared store.

    This intercepts the _run method to provide a namespaced proxy
    instead of the raw shared store.
    """
    # Create namespaced proxy for this node
    namespaced_shared = NamespacedSharedStore(shared, self._node_id)

    # Execute inner node with namespaced store  ← NODE SEES THIS PROXY!
    return self._inner_node._run(namespaced_shared)
```

### The Crucial Redirect Mechanism:

**Lines 43-48 (`__setitem__` in namespaced_store.py)**:
```python
def __setitem__(self, key: str, value: Any) -> None:
    """Write to the namespaced location.

    All writes go to shared[namespace][key] to prevent collisions.
    """
    self._parent[self._namespace][key] = value  ← REDIRECTS HERE!
```

### What This Means:

When HTTP node executes `shared["error"] = "HTTP 404"`:
1. Node thinks it's writing to root level
2. But `shared` is actually a `NamespacedSharedStore` proxy
3. Proxy redirects to `shared[node_id]["error"] = "HTTP 404"`
4. **Actual storage location**: `shared["http-fetch"]["error"]`

**Nodes DON'T write to root level - wrapper intercepts and namespaces everything!**

---

## 4. Data Availability at Error Extraction

### Execution Flow Trace:

```
1. Wrapper creates namespaced proxy
   namespaced_shared = NamespacedSharedStore(shared, "http-fetch")
   ↓
2. Node executes with proxy (thinks it's real shared store)
   node._run(namespaced_shared)
   ↓
3. Node's post() writes: shared["error"] = "HTTP 404"
   ↓ (proxy intercepts!)
4. Proxy redirects: shared["http-fetch"]["error"] = "HTTP 404"
   ↓
5. Flow returns "error" action
   ↓
6. executor_service._build_error_list() called (line 218-249)
   ↓
7. executor_service._extract_error_info() called (line 251-278)
   ↓
8. Tries multiple sources:
   - _extract_root_level_error() → checks shared["error"]  ❌ NOT THERE
   - _extract_node_level_error() → checks shared[node_id]["error"] ✅ FOUND HERE
```

### Error Extraction Helpers:

**Lines 295-315 (`_extract_root_level_error()`)**:
```python
def _extract_root_level_error(self, shared_store: dict[str, Any]) -> Optional[dict[str, str]]:
    """Extract error from root level of shared store."""
    if "error" not in shared_store:
        return None  # ❌ Will return None because error is namespaced

    result = {"message": str(shared_store["error"])}

    # Try to extract node from error_details
    if "error_details" in shared_store:
        error_details = shared_store.get("error_details", {})
        if isinstance(error_details, dict) and "server" in error_details and "tool" in error_details:
            result["node"] = f"{error_details['server']}_{error_details['tool']}"

    return result
```

**Lines 317-342 (`_extract_node_level_error()`)**:
```python
def _extract_node_level_error(self, failed_node: Optional[str], shared_store: dict[str, Any]) -> Optional[str]:
    """Extract error from failed node's output."""
    if not failed_node or failed_node not in shared_store:
        return None

    node_output = shared_store.get(failed_node, {})  # ✅ Gets namespaced data
    if not isinstance(node_output, dict):
        return None

    # Check direct error field
    if "error" in node_output:
        return str(node_output["error"])  # ✅ FOUND HERE - "HTTP 404"

    # Check MCP result format
    if "result" in node_output:
        return self._extract_error_from_mcp_result(node_output["result"])

    return None
```

---

## 5. Conclusion and Implications

### Data Availability: ✅ YES - Fully Accessible

**Error data IS available at `_build_error_list()` execution time** in the **namespaced location**:

- HTTP error: `shared["http-fetch"]["error"]` = `"HTTP 404"`
- HTTP status: `shared["http-fetch"]["status_code"]` = `404`
- HTTP response: `shared["http-fetch"]["response"]` = `{...}`
- MCP error: `shared["mcp-github-create-issue"]["error"]` = `"MCP tool failed: ..."`
- MCP error_details: `shared["mcp-github-create-issue"]["error_details"]` = `{server, tool, timeout}`
- MCP result: `shared["mcp-github-create-issue"]["result"]` = `{...}`

### Current Implementation Already Works:

The existing error extraction **correctly handles namespaced data**:

1. `_extract_error_info()` gets `failed_node` from `__execution__.failed_node`
2. Calls `_extract_root_level_error()` → Returns None (no root-level error)
3. Falls back to `_extract_node_level_error(failed_node, shared_store)`
4. This correctly accesses `shared[node_id]["error"]` ✅

**No bug exists - extraction already works with namespacing!**

### Enhancement Opportunities at Line 248:

Since data is available in namespaced location, you can enhance error messages by accessing additional fields:

**Proposed Enhancement in `_build_error_list()` around line 240-248:**
```python
def _build_error_list(
    self, success: bool, action_result: Optional[str], shared_store: dict[str, Any]
) -> list[dict[str, Any]]:
    """Build error list if execution failed."""
    if success:
        return []

    # Extract error information
    error_info = self._extract_error_info(action_result, shared_store)

    # ENHANCEMENT: Extract additional node-level data for richer errors
    failed_node = error_info["failed_node"]
    node_output = shared_store.get(failed_node, {}) if failed_node else {}

    # HTTP-specific enhancement
    if isinstance(node_output, dict):
        if "status_code" in node_output:
            status_code = node_output["status_code"]
            response = node_output.get("response", "")
            error_info["message"] = f"HTTP {status_code}: {self._format_response(response)}"

        # MCP-specific enhancement
        if "error_details" in node_output:
            details = node_output["error_details"]
            if "server" in details and "tool" in details:
                error_info["message"] = f"MCP {details['server']}.{details['tool']} failed: {error_info['message']}"

    # Determine error category
    category = self._determine_error_category(error_info["message"] or "")

    return [
        {
            "source": "runtime",
            "category": category,
            "message": error_info["message"],
            "action": action_result,
            "node_id": error_info["failed_node"],
            "fixable": True,
        }
    ]
```

### No Data Loss Concerns:

- Data written by nodes **persists** in shared store
- Namespacing **does not delete** or **move** data
- Data remains available under `shared[node_id][...]` throughout workflow execution
- Error extraction correctly accesses namespaced data via `_extract_node_level_error()`

---

## 6. Verification Example

To verify this analysis, you can trace a real HTTP error:

```python
# Simulate HTTP node execution with namespacing
shared = {}

# Wrapper creates namespaced proxy
from pflow.runtime.namespaced_store import NamespacedSharedStore
proxy = NamespacedSharedStore(shared, "http-fetch")

# Node writes (thinks it's writing to root)
proxy["error"] = "HTTP 404"
proxy["status_code"] = 404
proxy["response"] = {"error": "Not found"}

# Verify actual storage location
assert "http-fetch" in shared                        # ✅ Namespace exists
assert "error" in shared["http-fetch"]               # ✅ Error stored
assert shared["http-fetch"]["error"] == "HTTP 404"   # ✅ Correct value
assert shared["http-fetch"]["status_code"] == 404    # ✅ Status stored
assert "error" not in shared                         # ✅ NOT at root level

# Verify error extraction can access it (as executor_service does)
failed_node = "http-fetch"
node_output = shared.get(failed_node, {})
assert "error" in node_output                        # ✅ Accessible
print(f"✅ Error accessible: {node_output['error']}")
print(f"✅ Status code: {node_output['status_code']}")
print(f"✅ Response: {node_output['response']}")
```

---

## 7. Recommendations

### Option A: Enhance at Line 248 ✅ RECOMMENDED
- **Feasibility**: HIGH - Data is available in `shared[node_id]`
- **Location**: `_build_error_list()` around line 240-248
- **Implementation**: Extract additional fields from `shared[failed_node]`
- **Benefit**: Richer error messages with HTTP status codes and response bodies
- **Risk**: LOW - Non-breaking change, only enhances existing messages

### Option B: Modify Nodes to Write to Root Level ❌ NOT RECOMMENDED
- **Feasibility**: HIGH - But defeats namespacing purpose
- **Risk**: HIGH - Collisions if multiple HTTP/MCP nodes in workflow
- **Benefit**: NONE - Current approach works fine and prevents collisions

### Option C: Modify Earlier Extraction Helpers ⚠️ ALTERNATIVE
- **Feasibility**: MEDIUM
- **Location**: `_extract_node_level_error()` lines 317-342
- **Benefit**: Centralize enhanced error formatting
- **Tradeoff**: More generic, less context-aware than Option A

**Verdict**: **Option A** is best - enhance at line 248 in `_build_error_list()` where you have full context about error category, node type, and available data.

---

## 8. Key Takeaways

1. **Nodes write to "root"** - But it's a lie! They write through a proxy.
2. **Wrapper redirects everything** - `shared["key"]` → `shared[node_id]["key"]`
3. **Error extraction already works** - Uses `_extract_node_level_error()` correctly
4. **All data is preserved** - Nothing is lost or moved, just namespaced
5. **Enhancement is safe** - Can access `shared[node_id]` at line 248 for richer errors
6. **No breaking changes needed** - Current implementation is correct

The system is working as designed. Namespacing is transparent to nodes but provides collision prevention at the infrastructure level.
