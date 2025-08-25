# MCP Integration: Architectural Assessment

## Executive Summary

After analyzing pflow's registry system with extensive verification, **the registry is more flexible than initially assumed**. Multiple registry entries CAN point to the same class (verified: no validation prevents this), and entries CAN be added without scanning Python files (verified: Registry.save() accepts arbitrary dicts). This enables cleaner implementation than initially thought.

## Key Discoveries

### 1. Registry Flexibility (Verified)
- **Multiple entries → same class**: ✅ No validation prevents this
- **Manual registry updates**: ✅ Registry.save() accepts any dict[str, dict[str, Any]] without validation
- **No Python file required**: ✅ No file existence checks performed on file_path
- **Duplicate detection**: Only warns about duplicate node names, not duplicate class usage

### 2. How Nodes Get Parameters (Verified in compiler.py:254-296)
```python
# Compiler instantiates node with no constructor args (line 255)
node_instance = node_class()

# Then sets params via method (line 296)
node_instance.set_params(params)

# Node accesses in prep() - verified in multiple nodes
def prep(self, shared):
    server = self.params.get("server")
```

### 3. Existing Dynamic Patterns
- **WorkflowExecutor**: Already executes different workflows based on params
- **Wrapper pattern**: TemplateAwareNodeWrapper and NamespacedNodeWrapper show proxy patterns (store node_id but not node_type)
- **Registry injection**: Compiler injects special params like `__registry__` (copies params first to avoid side effects)

---

## All Viable Implementation Options

### Option 1: Direct Registry Manipulation (Recommended) ✅

**How it works:**
```python
class MCPRegistrar:
    def sync_server(self, server_name: str):
        # 1. Load existing registry
        registry = Registry()
        nodes = registry.load()

        # 2. Discover MCP tools
        client = MCPClient(server_name)
        tools = client.list_tools()

        # 3. Add each tool to registry
        for tool in tools:
            node_name = f"mcp-{server_name}-{tool.name}"
            nodes[node_name] = {
                "class_name": "MCPNode",
                "module": "pflow.nodes.mcp.node",
                "file_path": "virtual://mcp",  # Non-existent but doesn't matter
                "interface": {
                    "description": tool.description,
                    "params": tool.input_schema,
                    "outputs": tool.output_schema
                }
            }

        # 4. Save updated registry
        registry.save(nodes)
```

**MCPNode implementation:**
```python
class MCPNode(Node):
    def prep(self, shared):
        # NOTE: Nodes do NOT have access to node_type at runtime
        # Must rely on special params injected by compiler (see Option 8)
        server = self.params.get("__mcp_server__")
        tool = self.params.get("__mcp_tool__")

        if not server or not tool:
            # Fallback: parse from node_id if available through wrapper
            # But this requires additional wrapper implementation
            raise ValueError("MCP server/tool not provided")

        # Execute MCP tool
        client = MCPClient(server)
        return client.prepare_tool(tool, self.params)
```

**Pros:**
- ✅ Works with existing registry
- ✅ No code generation
- ✅ Clean separation of concerns
- ✅ Easy to implement

**Cons:**
- ❌ Node cannot determine its identity without compiler help (nodes don't have access to node_type)
- ❌ Registry becomes hybrid (scanned + manual entries)

---

### Option 2: Pre-configured Parameter Injection

**How it works:**
```python
# When registering MCP tools, include server/tool as default params
nodes[node_name] = {
    "class_name": "MCPNode",
    "module": "pflow.nodes.mcp.node",
    "interface": {
        "params": [
            {"name": "_mcp_server", "type": "str", "default": server_name, "hidden": True},
            {"name": "_mcp_tool", "type": "str", "default": tool_name, "hidden": True},
            # ... actual tool params
        ]
    }
}
```

**MCPNode reads pre-configured params:**
```python
class MCPNode(Node):
    def prep(self, shared):
        server = self.params.get("_mcp_server")
        tool = self.params.get("_mcp_tool")
        # These are set as defaults in registry
```

**Pros:**
- ✅ Clean parameter passing
- ✅ Node doesn't need to parse its name
- ✅ Params visible in registry

**Cons:**
- ❌ Mixing metadata with user params
- ❌ Could be overridden accidentally

---

### Option 3: Code Generation (Python Files)

**How it works:**
```python
def generate_mcp_nodes(server_name: str):
    """Generate actual Python files for each MCP tool."""

    for tool in discover_tools(server_name):
        code = f'''
from pflow.nodes.mcp.base import MCPNode

class {server_name.title()}{tool.name.title()}Node(MCPNode):
    """MCP: {server_name}:{tool.name}"""

    MCP_SERVER = "{server_name}"
    MCP_TOOL = "{tool.name}"
'''

        file_path = f"src/pflow/nodes/mcp_generated/{server_name}_{tool.name}.py"
        Path(file_path).write_text(code)
```

**Pros:**
- ✅ Works with existing scanner
- ✅ Each node is a real class
- ✅ IDE autocomplete works
- ✅ Clean node identity

**Cons:**
- ❌ Generates many files
- ❌ Needs regeneration when tools change
- ❌ Clutters codebase

---

### Option 4: Custom Registry Scanner

**How it works:**
```python
class MCPScanner:
    """Special scanner for MCP servers."""

    def scan(self):
        results = {}

        # Read MCP server configs
        for server in load_mcp_configs():
            client = MCPClient(server)
            tools = client.list_tools()

            for tool in tools:
                # Create virtual scan result
                results[f"mcp-{server}-{tool.name}"] = {
                    "class_name": "MCPNode",
                    "module": "pflow.nodes.mcp.node",
                    # ... rest of metadata
                }

        return results

# Modify main scanner to include MCP scanner
def scan_all():
    results = scan_python_files()
    results.update(MCPScanner().scan())
    return results
```

**Pros:**
- ✅ Integrates with existing scan process
- ✅ Clean architecture
- ✅ Automatic discovery

**Cons:**
- ❌ Requires modifying core scanner
- ❌ MCP discovery at every scan (slow)

---

### Option 5: Factory Pattern with Metadata Store

**How it works:**
```python
class MCPNodeFactory:
    """Factory that creates configured MCP nodes."""

    _metadata = {}  # Server/tool mappings

    @classmethod
    def register_tool(cls, node_name, server, tool):
        cls._metadata[node_name] = (server, tool)

    @classmethod
    def create_node(cls, node_name):
        server, tool = cls._metadata[node_name]
        node = MCPNode()
        node.mcp_server = server
        node.mcp_tool = tool
        return node

# Registry points to factory method
nodes[node_name] = {
    "class_name": "create_node",  # Factory method
    "module": "pflow.nodes.mcp.factory.MCPNodeFactory",
    # ...
}
```

**Pros:**
- ✅ Clean separation
- ✅ No runtime name parsing
- ✅ Testable

**Cons:**
- ❌ Requires compiler changes to support factories
- ❌ More complex

---

### Option 6: Entry Points (Plugin System)

**How it works:**
```python
# In pyproject.toml for each MCP integration
[project.entry-points."pflow.mcp"]
github = "pflow_mcp_github:discover"
filesystem = "pflow_mcp_filesystem:discover"

# Each package provides discovery function
def discover():
    return [
        {"name": "mcp-github-create-issue", "class": MCPNode, "config": {...}},
        # ...
    ]
```

**Pros:**
- ✅ Standard Python pattern
- ✅ Extensible by third parties
- ✅ Clean packaging

**Cons:**
- ❌ Requires separate packages
- ❌ More complex deployment

---

### Option 7: Metadata via Special Parameters (Cleanest) ⭐

**How it works:**
```python
# In compiler.py _instantiate_nodes(), line ~291
if params:
    # Inject node metadata as special parameters
    params_with_metadata = params.copy()
    params_with_metadata['__node_id__'] = node_id
    params_with_metadata['__node_type__'] = node_type
    node_instance.set_params(params_with_metadata)
```

**MCPNode uses metadata:**
```python
class MCPNode(Node):
    def prep(self, shared):
        # Node knows its type from special params
        node_type = self.params.get("__node_type__")
        parts = node_type.split("-")
        server = parts[1]
        tool = "-".join(parts[2:])
```

**Pros:**
- ✅ Minimal change (3 lines in compiler)
- ✅ Backward compatible (existing nodes ignore special params)
- ✅ Nodes know their identity from IR
- ✅ Clean and predictable

**Cons:**
- ❌ Special params could theoretically conflict with user params
- ❌ Requires compiler modification (but tiny one)

---

### Option 8: Follow Existing `__registry__` Pattern ⭐⭐

**How it works:**
```python
# The compiler ALREADY does this for WorkflowExecutor (line 282-284):
if node_type == "workflow" or node_type == "pflow.runtime.workflow_executor":
    params = params.copy()  # Don't modify original
    params["__registry__"] = registry

# Just extend it for MCP nodes (following same pattern):
if node_type.startswith("mcp-"):
    params = params.copy()  # Don't modify original
    params["__mcp_server__"] = node_type.split("-")[1]
    params["__mcp_tool__"] = "-".join(node_type.split("-")[2:])
```

**Pros:**
- ✅ Follows established pattern
- ✅ Compiler already has precedent for special params
- ✅ Very simple change
- ✅ Immediately clear what server/tool to use

**Cons:**
- ❌ Hardcodes MCP logic in compiler
- ❌ Less generic than Option 7

---

## Recommendation

### For MVP: Option 1 + Option 8
**Combine Direct Registry Manipulation with Existing Compiler Pattern**

1. **Registry Side (Option 1):**
   - Use `Registry.save()` to add MCP tools directly
   - No Python files needed
   - Clean virtual nodes

2. **Compiler Side (Option 8):**
   - Add 4 lines to compiler following `__registry__` pattern:
   ```python
   if node_type.startswith("mcp-"):
       params = params.copy()  # Don't modify original
       params["__mcp_server__"] = node_type.split("-")[1]
       params["__mcp_tool__"] = "-".join(node_type.split("-")[2:])
   ```

3. **MCPNode Implementation:**
   ```python
   class MCPNode(Node):
       def prep(self, shared):
           server = self.params.get("__mcp_server__")
           tool = self.params.get("__mcp_tool__")
           # Clear and simple
   ```

### Why This Combination Wins

- ✅ **Minimal changes**: 4 lines in compiler, 1 new file (MCPNode)
- ✅ **Follows patterns**: Uses existing `__registry__` precedent
- ✅ **Clean identity**: Nodes know exactly what they are
- ✅ **No hacks**: Works within existing architecture
- ✅ **Ships fast**: Can implement in hours, not days

### Future Evolution Path

1. **Phase 1 (MVP)**: Option 1 + 8
2. **Phase 2**: If needed, make compiler enhancement generic (Option 7)
3. **Phase 3**: If IDE support crucial, add code generation (Option 3)
4. **Phase 4**: For ecosystem, implement entry points (Option 6)

## Critical Insights

### 🎯 The Registry is NOT the Problem (Verified)
- Multiple entries → same class: ✅ Works (no validation prevents this)
- Manual updates: ✅ Works (Registry.save() is public API)
- Virtual entries: ✅ Works (no file existence checks)

### 🎯 The Real Challenge: Node Identity (Verified)
- Nodes do NOT have access to node_type at runtime (only node_id through wrappers)
- Solution: Inject metadata through existing param mechanism that compiler already uses for `__registry__`
- Compiler copies params before modification to avoid side effects (line 283)

### 🎯 No "Hacks" Needed
The architecture already supports what we need. We just need to:
1. Add entries to registry (Registry.save() accepts arbitrary dicts)
2. Pass metadata to nodes (compiler already does this for __registry__)
3. Create one MCPNode class (follows BaseNode pattern)

## Implementation Checklist

- [ ] Create `MCPNode` class that reads `__mcp_server__` and `__mcp_tool__` params
- [ ] Add 4 lines to compiler for MCP node detection (including params.copy())
- [ ] Implement `pflow mcp add/sync` commands to update registry
- [ ] Test with real MCP server
- [ ] Ship it

Total effort: ~2 days for working MVP.