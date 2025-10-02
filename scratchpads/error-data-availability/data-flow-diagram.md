# Error Data Flow Diagram

## Visual Representation of Where Data Goes

```
┌─────────────────────────────────────────────────────────┐
│                    HTTP Node (http.py)                   │
│                                                          │
│  def post(self, shared, prep_res, exec_res):            │
│      shared["error"] = "HTTP 404"        ← Writes here  │
│      shared["status_code"] = 404                         │
│      shared["response"] = {...}                          │
│      return "error"                                      │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ But `shared` is actually...
                     ▼
┌─────────────────────────────────────────────────────────┐
│          NamespacedSharedStore Proxy                     │
│                                                          │
│  def __setitem__(self, key, value):                     │
│      self._parent[self._namespace][key] = value         │
│                    └─────┬─────┘                        │
│                          │                               │
└──────────────────────────┼───────────────────────────────┘
                           │
                           │ Redirects to...
                           ▼
┌─────────────────────────────────────────────────────────┐
│              Actual Shared Store (dict)                  │
│                                                          │
│  {                                                       │
│    "http-fetch": {           ← Node ID namespace        │
│      "error": "HTTP 404",    ← Actual storage location  │
│      "status_code": 404,                                 │
│      "response": {...}                                   │
│    },                                                    │
│    "__execution__": {                                    │
│      "failed_node": "http-fetch"  ← Points to namespace │
│    }                                                     │
│  }                                                       │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ Later accessed by...
                     ▼
┌─────────────────────────────────────────────────────────┐
│   executor_service._build_error_list() - Line 248       │
│                                                          │
│  1. Gets failed_node = "http-fetch"                     │
│                                                          │
│  2. Calls _extract_error_info()                         │
│     ├─ _extract_root_level_error()                      │
│     │   └─ Checks shared["error"] ❌ Not found          │
│     │                                                    │
│     └─ _extract_node_level_error(failed_node)           │
│         └─ Checks shared[failed_node]["error"]          │
│            ✅ FOUND: "HTTP 404"                         │
│                                                          │
│  3. Can also access:                                    │
│     ✅ shared["http-fetch"]["status_code"] = 404        │
│     ✅ shared["http-fetch"]["response"] = {...}         │
│                                                          │
│  4. Builds enhanced error:                              │
│     "HTTP 404: Not found"                               │
└─────────────────────────────────────────────────────────┘
```

## Key Insight

**Node thinks**: "I'm writing to `shared["error"]`"
**Reality**: Proxy redirects to `shared[node_id]["error"]`
**Result**: No collisions, data preserved, accessible in error extraction

## Storage Locations Summary

| What Node Writes | Where Node Thinks It Goes | Where It Actually Goes | Accessible in _build_error_list()? |
|-----------------|--------------------------|------------------------|-------------------------------------|
| `shared["error"]` | `shared["error"]` | `shared[node_id]["error"]` | ✅ YES via `_extract_node_level_error()` |
| `shared["status_code"]` | `shared["status_code"]` | `shared[node_id]["status_code"]` | ✅ YES via `shared[node_id]` |
| `shared["response"]` | `shared["response"]` | `shared[node_id]["response"]` | ✅ YES via `shared[node_id]` |
| `shared["error_details"]` | `shared["error_details"]` | `shared[node_id]["error_details"]` | ✅ YES via `shared[node_id]` |
| `shared["result"]` | `shared["result"]` | `shared[node_id]["result"]` | ✅ YES via `shared[node_id]` |

## Wrapper Chain

```
InstrumentedNodeWrapper
    ├─ Tracks __execution__
    ├─ Records failed_node
    └─ Calls: NamespacedNodeWrapper._run()
              ↓
NamespacedNodeWrapper
    ├─ Creates NamespacedSharedStore proxy
    ├─ Redirects all writes to namespace
    └─ Calls: ActualNode._run(proxy)
              ↓
HTTP/MCP Node
    ├─ Thinks it's writing to root
    ├─ Actually writing through proxy
    └─ Returns "error" action
```

## Error Extraction Flow

```
_build_error_list(success=False, action="error", shared_store)
    ↓
_extract_error_info(action, shared_store)
    ↓
    ├─ Get failed_node from __execution__ ✅
    │   └─ failed_node = "http-fetch"
    │
    ├─ Try _extract_root_level_error() ❌
    │   └─ shared["error"] not found
    │
    └─ Try _extract_node_level_error(failed_node) ✅
        ├─ node_output = shared["http-fetch"]
        ├─ Found: node_output["error"] = "HTTP 404"
        ├─ Available: node_output["status_code"] = 404
        └─ Available: node_output["response"] = {...}
```

## Conclusion

**Everything is available** - just access `shared[failed_node]` to get all error data including:
- `error` - Error message
- `status_code` - HTTP status (for HTTP nodes)
- `response` - HTTP response body (for HTTP nodes)
- `error_details` - MCP server/tool details (for MCP nodes)
- `result` - MCP result object (for MCP nodes)

**No modifications needed to nodes** - Namespacing works transparently.
**Enhancement location**: Line 248 in `_build_error_list()` - access `shared[failed_node]` for richer errors.
