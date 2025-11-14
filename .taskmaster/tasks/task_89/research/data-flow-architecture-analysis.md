# Data Flow Architecture Analysis
## Understanding pflow's Data Handling for Two-Phase MCP Retrieval

**Date**: 2025-11-14
**Purpose**: Analyze pflow's data flow architecture to evaluate feasibility of two-phase approach (structure + selective retrieval) for MCP token consumption problem

---

## Executive Summary

**Key Finding**: pflow's architecture is **fully compatible** with a two-phase approach, but requires careful consideration of where to implement the selective retrieval logic.

**Architecture Characteristics**:
- ✅ In-memory shared store (supports stateful access)
- ✅ Template resolution happens at runtime (can handle dynamic paths)
- ✅ No automatic cleanup between nodes (data persists)
- ❌ No existing lazy loading mechanism
- ❌ No streaming/chunking for large responses

---

## 1. Shared Store Architecture

### 1.1 Core Implementation

**Location**: `pocketflow/__init__.py` (lines 7-41)

The shared store is a **simple Python dictionary** passed through the workflow:

```python
# From PocketFlow framework
class BaseNode:
    def _run(self, shared):
        p = self.prep(shared)      # Read from shared
        e = self._exec(p)
        return self.post(shared, p, e)  # Write to shared
```

**Key Properties**:
- **In-memory**: Pure Python dict, no persistence
- **Mutable**: All nodes share the same dict instance
- **Persistent**: Data lives for entire workflow execution
- **No cleanup**: Nothing removes data between nodes

### 1.2 Namespaced Store Pattern

**Location**: `src/pflow/runtime/namespaced_store.py`

pflow adds automatic namespacing to prevent collisions:

```python
# Writes go to: shared[node_id][key]
shared["node1"]["result"] = data

# Reads check both:
# 1. shared[node_id][key] (own namespace)
# 2. shared[key] (root level)
```

**Important**: This is transparent to nodes - they just write to `shared["result"]` and the wrapper handles namespacing.

**Impact on Two-Phase**:
- ✅ Can store structure in one namespace
- ✅ Can store full data in another namespace
- ✅ Nodes can selectively read what they need

### 1.3 Data Lifecycle

**When data enters shared store**:
1. CLI provides initial inputs → `shared["input_key"]`
2. Each node writes outputs → `shared[node_id][output_key]`
3. Template resolution reads from shared → `${node_id.output_key}`

**When data is cleaned up**:
- ❌ **Never during workflow execution**
- ✅ Only when workflow completes (shared dict is garbage collected)

---

## 2. Template Resolution System

### 2.1 How It Works

**Location**: `src/pflow/runtime/template_resolver.py`

Templates use `${variable}` syntax with path support:

```python
# Simple access
"${node1.result}"

# Nested access
"${node1.result.messages}"

# Array access
"${node1.result.messages[0].text}"
```

**Resolution happens in two places**:

1. **Pre-execution validation** (lines 162-413 in `template_validator.py`):
   - Checks all templates have valid sources
   - Uses registry metadata to understand structure
   - Fails early if paths don't exist

2. **Runtime resolution** (in `TemplateAwareNodeWrapper`):
   - Happens during node execution
   - Resolves `${var}` to actual values from shared store
   - Preserves types for simple templates

### 2.2 Path Traversal Logic

**Location**: `template_resolver.py` (lines 173-240)

```python
def resolve_value(var_name: str, context: dict[str, Any]) -> Optional[Any]:
    """Resolve ${data.items[0].name} from context"""

    # Supports:
    # - Dots: data.field.subfield
    # - Arrays: items[0]
    # - Combined: data.items[0].name
```

**Important**: This is **eager resolution** - once you access `${node.result}`, you get the **entire result object**.

### 2.3 Template Validation

**Location**: `template_validator.py` (Enhanced in Task 71)

The validator knows about output structure from registry metadata:

```python
# Node interface defines structure:
{
  "result": {
    "type": "dict",
    "structure": {
      "messages": {"type": "array", "items": {"type": "dict"}},
      "has_more": {"type": "bool"}
    }
  }
}

# Validator can suggest:
"Did you mean ${node.result.messages} instead of ${node.msg}?"
```

**Implications for Two-Phase**:
- ✅ Can validate against structure-only metadata
- ✅ Can provide intelligent suggestions
- ✅ Knows what fields exist before fetching data

---

## 3. MCP Node Current Behavior

### 3.1 Data Extraction

**Location**: `src/pflow/nodes/mcp/node.py` (lines 745-782)

```python
def _extract_result(self, mcp_result: Any) -> Any:
    """Extract from MCP response"""

    # Priority 1: Structured content (outputSchema)
    if mcp_result.structuredContent:
        return mcp_result.structuredContent  # Entire object

    # Priority 2: Error flag
    if mcp_result.isError:
        return {"error": "...", "is_tool_error": True}

    # Priority 3: Content blocks
    if mcp_result.content:
        return self._process_content_blocks(mcp_result)
```

**Current behavior**: Returns **everything** from MCP server.

### 3.2 Post-Processing

**Location**: `node.py` (lines 341-422)

```python
def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
    """Store results in shared store"""

    result = exec_res.get("result")

    # Store entire result
    shared["result"] = result

    # Extract top-level fields (for structured data)
    if isinstance(result, dict):
        for key, value in result.items():
            if not key.startswith("_"):
                shared[key] = value  # Flatten to shared store
```

**Current behavior**:
1. Stores entire result in `shared["result"]`
2. Flattens top-level fields to shared store
3. All data enters shared store immediately

**No lazy loading** - everything is eagerly stored.

---

## 4. Workflow Execution Flow

### 4.1 Execution Pipeline

**Location**: `src/pflow/runtime/compiler.py` (lines 929-1042)

```
1. Parse IR → Validate structure
2. Instantiate nodes → Apply wrappers
3. Wire nodes → Create Flow object
4. Execute workflow → Node by node
```

**Wrapper chain** (lines 543-571):
```
InstrumentedNodeWrapper      # Outermost - metrics, caching
  └─ NamespacedNodeWrapper   # Middle - collision prevention
      └─ TemplateAwareNodeWrapper  # Innermost - template resolution
          └─ ActualNode (e.g., MCPNode)
```

### 4.2 When Templates Resolve

**Location**: `node_wrapper.py` (lines 54-127)

```python
class TemplateAwareNodeWrapper:
    def _run(self, shared):
        # Resolve templates NOW (before node runs)
        resolved_params = self._resolve_templates(shared)

        # Set resolved params on inner node
        self._inner_node.set_params(resolved_params)

        # Run inner node with resolved params
        return self._inner_node._run(shared)
```

**Key insight**: Template resolution happens **once per node**, not incrementally.

---

## 5. Technical Constraints

### 5.1 What pflow CAN support

✅ **Stateful shared store access**
- Data persists throughout workflow
- Nodes can read previously written data
- No automatic cleanup

✅ **Dynamic template paths**
- `${node.result.messages[0].text}` resolves at runtime
- Path traversal supports nested structures
- Array indexing supported

✅ **Partial data storage**
- Can store structure separately from full data
- Can use different keys for different data sets
- Namespacing prevents collisions

✅ **Validation before execution**
- Template validator runs before workflow
- Can check paths against metadata
- Can fail early if invalid

### 5.2 What pflow CANNOT support (currently)

❌ **Lazy loading**
- No mechanism to defer data fetching
- Templates resolve eagerly (all at once)
- No "promise" or "future" pattern

❌ **Streaming/chunking**
- No incremental data transfer
- No pagination support
- All data must fit in memory

❌ **Selective field retrieval from MCP**
- MCPNode always fetches full response
- No field-level filtering before fetch
- MCP protocol itself doesn't support partial responses

❌ **Conditional fetching**
- Templates always resolve (no lazy evaluation)
- Can't skip fetching if not needed
- No "fetch on first access" pattern

---

## 6. Feasibility Analysis for Two-Phase Approach

### 6.1 Approach A: Structure + Full Data (Current + Metadata)

**How it would work**:
```python
# Phase 1: MCP call gets structure only
shared["node1"]["_structure"] = {
  "messages": {"type": "array", "count": 1000},
  "has_more": {"type": "bool"}
}

# Phase 2: Manual retrieval if needed
shared["node1"]["result"] = full_data  # Still fetches everything
```

**Compatibility**: ✅ **Fully compatible**
- Shared store can hold multiple keys
- Template resolution works as-is
- Validation can use `_structure` metadata

**Problem**: Still fetches full data in phase 2 (no selective retrieval)

### 6.2 Approach B: Structure + On-Demand Retrieval

**How it would work**:
```python
# Phase 1: Structure only
shared["node1"]["_structure"] = {...}

# Phase 2: Fetch specific fields
shared["node1"]["messages"] = fetch_field("messages")  # Selective!
```

**Compatibility**: ⚠️ **Partially compatible**
- ✅ Shared store can hold field-level data
- ✅ Templates can access `${node1.messages}`
- ❌ **MCP protocol doesn't support field-level retrieval**
- ❌ Would need custom MCP server implementation

### 6.3 Approach C: Lazy Proxy Pattern

**How it would work**:
```python
# Phase 1: Return proxy object
shared["node1"]["result"] = LazyProxy(fetch_callback)

# Phase 2: Fetch on access
messages = shared["node1"]["result"].messages  # Triggers fetch
```

**Compatibility**: ❌ **Not compatible**
- Template resolution expects actual values, not proxies
- Would break type validation
- Would require significant refactoring
- PocketFlow framework doesn't support lazy evaluation

---

## 7. Recommended Implementation Strategy

### 7.1 Where to Implement Selective Logic

**Option 1: In MCPNode** (Recommended)
```python
class MCPNode:
    def prep(self, shared):
        # Check if params request "structure_only"
        structure_only = self.params.get("structure_only", False)
        return {"structure_only": structure_only, ...}

    def exec(self, prep_res):
        if prep_res["structure_only"]:
            # Make MCP call with special flag
            return await session.call_tool(
                tool_name,
                {"_structure_only": True}
            )
        else:
            # Normal full fetch
            return await session.call_tool(tool_name, args)
```

**Pros**:
- ✅ Minimal changes to pflow architecture
- ✅ Backward compatible
- ✅ Node-level control

**Cons**:
- ❌ Requires MCP server support for `_structure_only`
- ❌ Planner needs to decide when to use structure-only

**Option 2: In Planner** (Alternative)
- Planner generates two nodes: one for structure, one for data
- Uses conditional edges to skip data fetch if not needed

**Pros**:
- ✅ No MCP protocol changes needed
- ✅ Explicit in workflow IR

**Cons**:
- ❌ More complex workflow generation
- ❌ Still fetches full data when needed

### 7.2 Data Flow Pattern

**Recommended flow**:
```
1. Planner detects MCP node with large response potential
2. Generates structure-only node first
3. Stores structure in shared["node_id"]["_structure"]
4. Validation uses structure for template checking
5. IF templates need full data:
   - Generate follow-up node to fetch full data
6. ELSE:
   - Skip data fetch entirely (just use structure)
```

### 7.3 Shared Store Layout

```python
shared = {
  "fetch-messages": {
    # Structure metadata (always present)
    "_structure": {
      "messages": {"type": "array", "count": 1000},
      "has_more": {"type": "bool"}
    },

    # Full data (only if fetched)
    "result": {
      "messages": [...],  # 1000 items
      "has_more": true
    }
  }
}
```

**Template access**:
- `${fetch-messages._structure}` → Always available, small
- `${fetch-messages.result}` → Only available if fetched, large

---

## 8. Key Technical Decisions

### 8.1 Where to Store Structure

**Options**:
1. ✅ **`shared[node_id]["_structure"]`** (Recommended)
   - Clear separation from actual data
   - Underscore prefix indicates metadata
   - Can coexist with full data

2. ❌ `shared[node_id]["result"]` (overwrite)
   - Confusing - is it structure or data?
   - Can't keep both

3. ❌ Special reserved key `shared["__structures__"]`
   - Less discoverable
   - Breaks namespacing pattern

### 8.2 Template Validation Strategy

**Current behavior**:
- Validator checks `${node.result.messages}` against registry metadata
- Registry has static interface definition

**With two-phase**:
- Use `_structure` for validation instead of static metadata
- More accurate (reflects actual response)
- Still validates before execution

### 8.3 MCP Protocol Requirements

**Critical question**: Does MCP protocol support structure-only responses?

**Answer from investigation**: No standard support
- Would need custom parameter like `_pflow_structure_only: true`
- MCP servers would need to implement this
- Not portable across all MCP servers

**Alternative**: Use MCP's existing features
- Some tools have pagination (fetch 10 at a time)
- Some tools have field filtering (select specific fields)
- Check tool schema for these capabilities

---

## 9. Conclusions

### 9.1 Architecture Compatibility

**pflow's architecture IS compatible** with two-phase approach:
- ✅ In-memory shared store supports stateful access
- ✅ Template resolution can handle dynamic paths
- ✅ No data cleanup prevents interference
- ✅ Namespacing allows structure + data coexistence

**BUT** has limitations:
- ❌ No lazy loading mechanism
- ❌ Templates resolve eagerly (all at once)
- ❌ MCP protocol doesn't standardize structure-only

### 9.2 Recommended Path Forward

**Short-term** (MVP-compatible):
1. Add `structure_only` parameter to MCPNode
2. Store structure in `shared[node_id]["_structure"]`
3. Planner generates structure-first workflows when beneficial
4. Use existing MCP pagination/filtering where available

**Long-term** (Post-MVP):
1. Propose `_structure_only` extension to MCP protocol
2. Implement lazy proxy pattern in PocketFlow
3. Add template resolution optimization (only fetch used paths)
4. Consider streaming for large responses

### 9.3 Implementation Complexity

**Low complexity** (can do now):
- Store structure separately
- Use structure for validation
- Skip full fetch when not needed

**Medium complexity** (requires planning changes):
- Detect when to use structure-only
- Generate conditional workflows
- Handle mixed structure/data scenarios

**High complexity** (requires protocol changes):
- MCP server structure-only support
- Lazy loading in PocketFlow
- Template resolution optimization

---

## 10. Action Items for Decision

Before implementing two-phase approach:

1. ✅ **Confirm MCP server capabilities**
   - Check if Slack/Discord/etc support field filtering
   - Check if pagination is available
   - Test structure inference from schema

2. ✅ **Prototype structure storage**
   - Add `_structure` key to MCPNode
   - Test with template validation
   - Measure token savings

3. ✅ **Evaluate planner complexity**
   - How to detect large response potential?
   - When to generate structure-first?
   - How to handle errors if structure differs from data?

4. ⏳ **Consider alternatives**
   - Pagination-first approach (fetch 10, then more if needed)
   - Field filtering (if MCP server supports)
   - Response streaming (if MCP supports)

---

**Conclusion**: Two-phase approach is **architecturally feasible** but requires careful design of where logic lives (MCPNode vs Planner) and how MCP protocol limitations are handled.
