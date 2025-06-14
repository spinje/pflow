# Unified Flow with Action Routing Pattern

*This document explores using a single flow with action-based routing, unifying static and dynamic (MCP) tool definitions.*

---

## The Core Insight

Instead of separate flows for each action, we have **one flow per platform** that:
1. Takes an `--action` parameter
2. Routes internally to the appropriate execution
3. Works identically for both static implementations and MCP servers

```bash
# One command, multiple actions
pflow github --action=get-issue --repo=owner/repo --issue=123
pflow github --action=create-issue --repo=owner/repo --title="..." --body="..."
```

## The Flow Pattern (from pocketflow-mcp)

```python
# Simplified from the MCP example
get_tools_node = GetToolsNode()      # Discovers/defines available actions
decide_node = DecideToolNode()       # Routes based on --action param
execute_node = ExecuteToolNode()     # Executes the selected action

# Flow structure
get_tools_node >> decide_node >> execute_node
```

But crucially, our `DecideToolNode` is **deterministic**, not LLM-based:
- It reads `self.params["action"]`
- It validates against available tools
- It prepares the execution context

## Implementation Pattern

### For Static Tools (Local Implementation)

```python
class GitHubGetToolsNode(Node):
    """Define available GitHub actions statically."""

    def exec(self, prep_res):
        # Return static tool definitions
        return [
            {
                "name": "get-issue",
                "description": "Get issue details",
                "inputSchema": {
                    "properties": {
                        "repo": {"type": "string"},
                        "issue": {"type": "integer"}
                    },
                    "required": ["repo", "issue"]
                }
            },
            {
                "name": "create-issue",
                "description": "Create new issue",
                "inputSchema": {
                    "properties": {
                        "repo": {"type": "string"},
                        "title": {"type": "string"},
                        "body": {"type": "string"}
                    },
                    "required": ["repo", "title", "body"]
                }
            }
        ]

    def post(self, shared, prep_res, exec_res):
        shared["tools"] = exec_res
        shared["tool_map"] = {tool["name"]: tool for tool in exec_res}
        return "default"

class GitHubDecideNode(Node):
    """Route based on --action parameter."""

    def prep(self, shared):
        action = self.params.get("action")
        if not action:
            raise ValueError("--action parameter required")

        tool_map = shared.get("tool_map", {})
        if action not in tool_map:
            available = list(tool_map.keys())
            raise ValueError(f"Unknown action '{action}'. Available: {available}")

        return action, tool_map[action]

    def exec(self, prep_res):
        # Just pass through the decision
        return prep_res

    def post(self, shared, prep_res, exec_res):
        action, tool_spec = exec_res
        shared["selected_action"] = action
        shared["selected_tool"] = tool_spec
        return "execute"

class GitHubExecuteNode(Node):
    """Execute the selected GitHub action."""

    def prep(self, shared):
        action = shared["selected_action"]
        tool_spec = shared["selected_tool"]

        # Extract parameters based on tool schema
        params = {}
        for param, spec in tool_spec["inputSchema"]["properties"].items():
            # First check CLI params, then shared store
            if param in self.params:
                params[param] = self.params[param]
            elif param in shared:
                params[param] = shared[param]
            elif param in tool_spec["inputSchema"].get("required", []):
                raise ValueError(f"Missing required parameter: {param}")

        return action, params

    def exec(self, prep_res):
        action, params = prep_res

        # Dispatch to actual implementation
        if action == "get-issue":
            return self._get_issue(**params)
        elif action == "create-issue":
            return self._create_issue(**params)
        else:
            raise ValueError(f"No implementation for action: {action}")

    def _get_issue(self, repo, issue):
        # Actual GitHub API call
        return {"number": issue, "title": "Example Issue", "repo": repo}

    def _create_issue(self, repo, title, body):
        # Actual GitHub API call
        return {"number": 123, "title": title, "url": f"https://github.com/{repo}/issues/123"}

    def post(self, shared, prep_res, exec_res):
        action = prep_res[0]

        # Write to action-specific keys to avoid collisions
        if action == "get-issue":
            shared["issue"] = exec_res
        elif action == "create-issue":
            shared["created_issue"] = exec_res
            shared["issue_url"] = exec_res["url"]

        return "default"

# Create the flow
def create_github_flow():
    get_tools = GitHubGetToolsNode()
    decide = GitHubDecideNode()
    execute = GitHubExecuteNode()

    get_tools >> decide >> execute

    return Flow(start=get_tools)
```

### For Dynamic Tools (MCP)

```python
class McpGetToolsNode(Node):
    """Discover tools from MCP server dynamically."""

    def __init__(self, server_name):
        super().__init__()
        self.server_name = server_name

    def exec(self, prep_res):
        # Check cache first
        cached_tools = load_cached_tools(self.server_name)
        if cached_tools and not self.params.get("refresh_cache"):
            return cached_tools

        # Discover from MCP server
        tools = discover_mcp_tools(self.server_name)
        return tools

    def post(self, shared, prep_res, exec_res):
        shared["tools"] = exec_res
        shared["tool_map"] = {tool.name: tool for tool in exec_res}

        # Cache for future runs
        save_cached_tools(self.server_name, exec_res)

        return "default"

class McpExecuteNode(Node):
    """Execute MCP tool."""

    def __init__(self, server_name):
        super().__init__()
        self.server_name = server_name
        self.mcp_client = McpClient(server_name)

    def prep(self, shared):
        # Same parameter extraction as static version
        action = shared["selected_action"]
        tool_spec = shared["selected_tool"]

        params = extract_params_from_spec(tool_spec, self.params, shared)
        return action, params

    def exec(self, prep_res):
        action, params = prep_res
        # Call MCP tool
        return self.mcp_client.call_tool(action, params)

    def post(self, shared, prep_res, exec_res):
        # MCP tools typically return to a generic key
        shared["result"] = exec_res
        return "default"

# Create MCP flow
def create_mcp_flow(server_name):
    get_tools = McpGetToolsNode(server_name)
    decide = DecideNode()  # Same decide logic!
    execute = McpExecuteNode(server_name)

    get_tools >> decide >> execute

    return Flow(start=get_tools)
```

## Key Advantages

### 1. Unified Pattern
Both static and dynamic tools use the same flow structure:
- Get available tools (static list or MCP discovery)
- Decide based on --action parameter
- Execute the selected tool

### 2. Parameter Resolution
```python
# The flow handles all parameters
flow = create_github_flow()
flow.set_params({
    "action": "get-issue",
    "repo": "owner/repo",
    "issue": 123,
    "token": "..."
})
flow.run(shared)
```

### 3. Shared Store Interface
Each action can define its own interface, resolved at execution time:
```python
# get-issue writes to shared["issue"]
# create-issue writes to shared["created_issue"]
# No collisions!
```

### 4. Caching for MCP
Tool discovery is cached, making subsequent runs fast:
```python
# First run: discovers tools from MCP server
pflow mcp-github --action=search-code --query="test"

# Second run: uses cached tool definitions (fast!)
pflow mcp-github --action=search-code --query="example"
```

## Metadata and Discovery

### Static Tool Metadata
```json
{
  "flow": {
    "id": "github",
    "type": "action-based",
    "actions": {
      "get-issue": {
        "description": "Get issue details",
        "inputs": ["repo", "issue"],
        "outputs": ["issue"],
        "parameters": {
          "repo": {"type": "string", "required": true},
          "issue": {"type": "integer", "required": true}
        }
      },
      "create-issue": {
        "description": "Create new issue",
        "inputs": ["repo", "title", "body"],
        "outputs": ["created_issue", "issue_url"],
        "parameters": {
          "repo": {"type": "string", "required": true},
          "title": {"type": "string", "required": true},
          "body": {"type": "string", "required": true}
        }
      }
    }
  }
}
```

### Dynamic Tool Metadata (MCP)
```json
{
  "flow": {
    "id": "mcp-github",
    "type": "mcp-wrapper",
    "mcp_server": "github-server",
    "cache_ttl": 3600,
    "discovered_actions": null  // Populated at runtime
  }
}
```

## CLI Integration

```python
@click.command()
@click.argument('flow_name')
@click.option('--action', required=True, help='Action to execute')
@click.pass_context
def run_flow(ctx, flow_name, action, **kwargs):
    # Load flow from registry
    flow = registry.get_flow(flow_name)

    # Set all parameters (action + others)
    params = {"action": action, **kwargs}
    flow.set_params(params)

    # Run with shared store
    shared = load_shared_from_stdin()
    flow.run(shared)

    # Output results
    output_shared_to_stdout(shared)
```

## Example Usage

### Static GitHub Flow
```bash
# Get an issue
pflow github --action=get-issue --repo=anthropics/pflow --issue=123

# Create an issue
echo '{"title": "Bug report", "body": "..."}' | \
  pflow github --action=create-issue --repo=anthropics/pflow

# Chain operations
pflow github --action=get-issue --repo=anthropics/pflow --issue=123 | \
  pflow transform --template="Follow-up to #{issue.number}" | \
  pflow github --action=create-issue --repo=anthropics/pflow
```

### Dynamic MCP Flow
```bash
# First run - discovers tools
pflow mcp-github --action=search-code --query="TODO" --language=python

# Subsequent runs - uses cache
pflow mcp-github --action=get-repo --owner=anthropics --repo=pflow
```

## Critical Benefits

### 1. Single Command Interface
Users interact with platforms, not individual actions:
```bash
pflow github --action=...
pflow slack --action=...
pflow aws --action=...
```

### 2. Consistent Pattern
All flows follow the same structure:
- Discover/define tools
- Route based on action
- Execute selected tool

### 3. Natural Evolution
Start with static implementations, add MCP support later:
```python
# Version 1: Static implementation
flow = create_github_flow()

# Version 2: Add MCP support
flow = create_mcp_flow("github-server") if USE_MCP else create_github_flow()
```

### 4. Performance Optimization
- Static tools have zero discovery overhead
- MCP tools cache discovery results
- Routing is deterministic and fast

## Solving Our Original Problems

### ✅ Shared Store Collisions
Each action writes to distinct keys, resolved in the execute node's `post()` method.

### ✅ Parameter vs Input Clarity
- CLI flags → `self.params` (including action)
- Shared data → `shared` store
- Clear separation maintained

### ✅ Static vs Dynamic Tools
Same flow pattern works for both, with appropriate discovery mechanisms.

### ✅ Metadata Complexity
Action metadata lives with the flow, discovered at runtime for MCP.

## Conclusion

This unified flow pattern with action routing provides:
1. **One command per platform** with action selection
2. **Consistent pattern** for static and dynamic tools
3. **Natural parameter handling** through pocketflow
4. **Performance optimization** through caching
5. **Clear separation** of concerns

The key insight: **Flows can handle action routing internally**, making them perfect for both static platform implementations and dynamic MCP wrappers. The decide node doesn't need AI - it just routes based on the `--action` parameter!

This is the elegant solution that unifies all our requirements.

## Additional Insights

### Why This Pattern Works So Well

1. **The Flow is the Platform Abstraction**
   - Each platform (github, slack, aws) is a flow
   - The flow encapsulates all actions for that platform
   - Natural mental model: "I'm using GitHub" → `pflow github`

2. **Action Routing is Lightweight**
   - No complex dispatch in nodes
   - DecideNode just validates and routes
   - All complexity isolated to ExecuteNode

3. **Perfect MCP Alignment**
   ```python
   # MCP server exposes tools
   # We discover them in GetToolsNode
   # User selects via --action
   # Same execution pattern!
   ```

4. **Shared Store Usage is Natural**
   ```python
   # Each action can read/write different keys
   # ExecuteNode.post() handles the mapping
   # No collision because it's contextual to the action
   ```

### The Beautiful Symmetry

**Static Flow:**
```
GetTools (hardcoded) → Decide (--action) → Execute (local impl)
```

**Dynamic Flow:**
```
GetTools (discover) → Decide (--action) → Execute (MCP call)
```

The pattern is identical! Only the implementation details differ.

### Registry Structure

```
registry/
├── flows/
│   ├── github/              # Static implementation
│   │   ├── flow.py
│   │   ├── metadata.json
│   │   └── nodes/
│   │       ├── get_tools.py
│   │       ├── decide.py
│   │       └── execute.py
│   ├── mcp-github/          # Dynamic MCP wrapper
│   │   ├── flow.py
│   │   └── metadata.json
│   └── slack/               # Another platform
│       ├── flow.py
│       └── metadata.json
```

### Performance Considerations

1. **Static Tools**: Near-zero overhead
   - Tool definitions are hardcoded
   - No discovery needed
   - Direct execution

2. **Dynamic Tools**: Optimized with caching
   - First run: Discover and cache
   - Subsequent runs: Use cache
   - Cache invalidation via --refresh-cache flag

### Future Extensions

1. **Hybrid Flows**: Mix static and dynamic actions
   ```python
   # Some actions implemented locally
   # Others delegated to MCP server
   if action in LOCAL_ACTIONS:
       return execute_local(action, params)
   else:
       return mcp_client.call_tool(action, params)
   ```

2. **Action Aliases**: User-friendly names
   ```python
   ACTION_ALIASES = {
       "pr": "pull-request",
       "issue": "get-issue",
   }
   ```

3. **Composite Actions**: Actions that run sub-flows
   ```python
   if action == "full-issue-report":
       # Run multiple actions in sequence
       self._get_issue()
       self._get_comments()
       self._get_timeline()
   ```

### The Final Architecture

```python
class PlatformFlow(Flow):
    """Base class for platform flows with action routing."""

    def __init__(self, platform_name: str, is_mcp: bool = False):
        self.platform_name = platform_name
        self.is_mcp = is_mcp

        # Build the flow
        get_tools = self._create_get_tools_node()
        decide = self._create_decide_node()
        execute = self._create_execute_node()

        get_tools >> decide >> execute
        super().__init__(start=get_tools)

    @abstractmethod
    def _create_get_tools_node(self) -> Node:
        """Create node for tool discovery/definition."""
        pass

    def _create_decide_node(self) -> Node:
        """Create routing node - same for all platforms!"""
        return UniversalDecideNode()

    @abstractmethod
    def _create_execute_node(self) -> Node:
        """Create execution node for platform."""
        pass
```

This base class ensures consistency while allowing platform-specific implementations.

## The Verdict

This architecture achieves everything we need:
- ✅ Single command per platform
- ✅ Action-based routing
- ✅ Works for static and dynamic tools
- ✅ Natural shared store usage
- ✅ Performance optimized
- ✅ Simple to understand and implement

By using flows with action routing, we get the best of all worlds!
