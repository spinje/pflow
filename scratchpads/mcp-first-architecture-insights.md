# MCP-First Architecture: Key Design Insights

*This document captures critical architectural decisions from exploring node design patterns with MCP integration as the primary constraint.*

---

## The Core Insight: MCP Servers = Platform Nodes

**The natural mapping is perfect:**
- **MCP Server** → **Platform Node** (e.g., `github-server` → `github` node)
- **MCP Tool** → **Action** (e.g., `get-issue` tool → `--action=get-issue`)
- **Tool InputSchema** → **Action Parameters**
- **Server Connection** → **Node Connection** (single connection for all tools)

This 1:1 alignment should drive our architecture.

---

## The Journey: Why Action-Based Nodes Win

### We Explored Flow-Based Routing
```python
# Initial idea: Wrap related nodes in a Flow
router - "get-issue" >> github_get_issue_node
router - "create-issue" >> github_create_issue_node
github_flow = Flow(start=router)
```

**Why it failed:**
- **Dynamic parameters problem**: CLI needs to validate params before flow runs
- **Same metadata complexity**: Still need action-parameter mappings upfront
- **MCP impedance mismatch**: Would create multiple nodes wrapping same MCP server
- **Connection inefficiency**: Each node needs connection to same server

### Action-Based Nodes Align Perfectly with MCP
```python
class GitHubNode(Node):
    def __init__(self):
        self.mcp_client = McpClient("github-server")  # Single connection

    def exec(self, prep_res):
        action = self.params.get("action")
        return self.mcp_client.call_tool(action, prep_res)
```

**Why it works:**
- Natural server-to-node mapping
- Single connection per platform
- Matches MCP discovery pattern (`tools/list`)
- Parameter validation happens pre-execution

---

## The Service Abstraction Pattern

To address LLM generation complexity, consider **MCP-like service abstraction**:

### The Pattern
```python
# 1. Pure service (no pflow dependencies)
class GitHubService:
    def get_issue(self, repo: str, issue: int) -> dict:
        return github_api.get_issue(repo, issue)

# 2. Thin node wrapper
class GitHubNode(Node):
    def __init__(self):
        self.service = GitHubService()

    def prep(self, shared):
        # Extract from shared store based on action
        if self.params.get("action") == "get-issue":
            return {"repo": shared["repo"], "issue": shared["issue"]}

    def exec(self, prep_res):
        action = self.params.get("action")
        if action == "get-issue":
            return self.service.get_issue(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["issue_data"] = exec_res
```

### Trade-offs
**Benefits:**
- Testable business logic
- Clean MCP migration path (swap service implementation)
- Separation of concerns

**Costs:**
- More code (service + node + translation)
- Node becomes translation layer
- Added indirection

**Recommendation**: Use services for complex platforms, direct implementation for simple operations.

---

## Design Principles for MCP-First Architecture

### 1. Make MCP Wrapping Trivial
```python
def wrap_mcp_server(server_id: str) -> Type[Node]:
    """Generate platform node from MCP server - this should be our template"""
    class McpPlatformNode(Node):
        def __init__(self):
            self.client = McpClient(server_id)
            self.tools = self.client.list_tools()

        def exec(self, prep_res):
            action = self.params.get("action")
            return self.client.call_tool(action, prep_res)

    return McpPlatformNode
```

### 2. Copy This Pattern Everywhere
Even for non-MCP nodes, follow the same structure:
- Platform node with action dispatch
- Consistent metadata schema
- Same discovery patterns

### 3. Metadata Drives Everything
```json
{
  "id": "github",
  "actions": {
    "get-issue": {
      "inputs": ["repo", "issue"],
      "outputs": ["issue_data"],
      "params": {"repo": "string", "issue": "integer"}
    }
  }
}
```

---

## Key Architectural Decisions

1. **Action-based platform nodes** for all integrations (MCP and native)
2. **Simple focused nodes** for core operations (read-file, transform-text)
3. **Service abstraction** optional - use where complexity justifies it
4. **Shared store translation** happens in nodes, not services
5. **Metadata-driven validation** with upfront parameter schemas

---

## Implementation Strategy

### Phase 1: Design the MCP Wrapper Pattern
Create the perfect MCP wrapper that handles:
- Connection management
- Tool discovery
- Parameter validation
- Action dispatch

### Phase 2: Apply Pattern to Native Platforms
Use identical structure for native integrations:
```python
class NativeGitHubNode(Node):
    # Same interface as MCP wrapper
    def exec(self, prep_res):
        action = self.params.get("action")
        # Direct API calls instead of MCP
```

### Phase 3: Gradual MCP Migration
Swap implementations without changing interfaces:
```python
# v1.0
self.service = NativeGitHubService()

# v2.0 - Same interface!
self.service = McpGitHubService()
```

---

## The Bottom Line

**Design for MCP wrapping first** - this constraint leads to clean, consistent architecture:
- Platform nodes with action dispatch
- Upfront parameter schemas
- Single connection per platform
- Natural tool-to-action mapping

This pattern works equally well for MCP servers and native integrations, providing a unified approach to all platform nodes in pflow.
