# Flows Not Actions: A Fundamental Architecture Shift

*This document explores the paradigm shift from action-based nodes to flow-based composition, inspired by the pocketflow-mcp example.*

---

## The Core Insight

Looking at the pocketflow-mcp example and understanding that **Flows can have parameters**, we realize:

1. **An "action" doesn't need to be a parameter** - it can be a Flow choice
2. **Flows are composable** - they can be nodes in other flows
3. **Parameters flow through** - parent flow params are passed to child nodes

This means instead of:
```bash
pflow github --action=get-issue --repo=owner/repo --issue=123
```

We could have:
```bash
pflow github-get-issue --repo=owner/repo --issue=123
```

Where `github-get-issue` is actually a Flow, not just a Node.

## Examining the MCP Example

The pocketflow-mcp example shows a pattern:

```python
# main.py structure:
GetToolsNode >> DecideToolNode >> ExecuteToolNode

# This is a flow that:
1. Discovers available tools
2. Decides which tool to use (via LLM)
3. Executes the chosen tool
```

For pflow, we don't need the "decide" step because the user specifies the action via CLI. But we can learn from the pattern.

## The Fundamental Shift

### Current Thinking (Action-Based Nodes)
```python
class GitHubNode(Node):
    def exec(self, prep_res):
        action = self.params.get("action")
        if action == "get-issue":
            return self._get_issue(prep_res)
        elif action == "create-issue":
            return self._create_issue(prep_res)
```

### New Thinking (Flow-Based Composition)
```python
# Each "action" is a flow
class GitHubGetIssueFlow(Flow):
    def __init__(self):
        # Compose nodes that handle the operation
        validate = ValidateGitHubParams()
        fetch = FetchGitHubIssue()
        format = FormatIssueOutput()

        validate >> fetch >> format
        super().__init__(start=validate)

# Or even simpler - single node flows
class GitHubGetIssueNode(Node):
    """Simple focused node that gets an issue."""

get_issue_flow = Flow(start=GitHubGetIssueNode())
```

## Benefits of This Approach

### 1. Natural Composition
Flows can be composed of multiple nodes, allowing complex operations:

```python
# A flow that gets an issue and its comments
class GitHubIssueWithCommentsFlow(Flow):
    def __init__(self):
        get_issue = GitHubGetIssueNode()
        get_comments = GitHubGetCommentsNode()
        merge_data = MergeIssueAndCommentsNode()

        get_issue >> get_comments >> merge_data
        super().__init__(start=get_issue)
```

### 2. Parameter Handling is Built-In
```python
# Flow-level parameters
flow = GitHubGetIssueFlow()
flow.set_params({"repo": "owner/repo", "issue": 123, "token": "..."})
flow.run(shared)

# The flow passes params to all its nodes automatically!
```

### 3. No Key Collision Issues
Each flow can have its own interface without worrying about action-specific keys:

```python
# GitHubGetIssueFlow
# Reads: shared["issue_number"]
# Writes: shared["issue"]

# GitHubCreateIssueFlow
# Reads: shared["title"], shared["body"]
# Writes: shared["created_issue"]

# No collision because they're separate flows!
```

### 4. MCP Integration Becomes Natural

For MCP servers, we can generate flows instead of action-based nodes:

```python
def generate_mcp_flows(server_name: str) -> Dict[str, Flow]:
    """Generate a flow for each MCP tool."""
    tools = discover_mcp_tools(server_name)
    flows = {}

    for tool in tools:
        # Create a flow for this tool
        node = McpToolExecutorNode(server_name, tool.name)
        flow = Flow(start=node)
        flows[f"mcp-{server_name}-{tool.name}"] = flow

    return flows
```

## How This Changes Everything

### 1. CLI Resolution
Instead of:
```bash
pflow github --action=get-issue --repo=owner/repo --issue=123
```

We have:
```bash
pflow github-get-issue --repo=owner/repo --issue=123
```

The CLI directly maps to a flow name, not a node + action.

### 2. Registry Structure
```
registry/
├── flows/
│   ├── github-get-issue/
│   │   ├── flow.py
│   │   └── metadata.json
│   ├── github-create-issue/
│   │   ├── flow.py
│   │   └── metadata.json
│   └── github-search-issues/
│       ├── flow.py
│       └── metadata.json
├── nodes/
│   ├── core/
│   │   ├── read-file/
│   │   ├── write-file/
│   │   └── transform-text/
```

### 3. Metadata Becomes Simpler
```json
{
  "flow": {
    "id": "github-get-issue",
    "description": "Get GitHub issue details",
    "inputs": {
      "issue_number": {"type": "integer", "required": true}
    },
    "outputs": {
      "issue": {"type": "object"}
    },
    "parameters": {
      "repo": {"type": "string", "required": true},
      "token": {"type": "string", "required": true}
    }
  }
}
```

No need for action-specific metadata!

## Example: GitHub Operations

### Simple Approach (Single-Node Flows)
```python
# github_get_issue.py
class GitHubGetIssueNode(Node):
    """Get issue details from GitHub.

    Interface:
    - Reads: shared["issue_number"]
    - Writes: shared["issue"]
    - Params: repo (str), token (str)
    """

    def prep(self, shared):
        return shared["issue_number"]

    def exec(self, issue_number):
        repo = self.params["repo"]
        token = self.params["token"]
        return github_api.get_issue(repo, issue_number, token)

    def post(self, shared, prep_res, exec_res):
        shared["issue"] = exec_res
        return "default"

# Register as a flow
github_get_issue = Flow(start=GitHubGetIssueNode())
```

### Complex Approach (Multi-Node Flows)
```python
# github_create_pr_flow.py
class GitHubCreatePRFlow(Flow):
    """Create a PR with validation and formatting."""

    def __init__(self):
        validate = ValidatePRDataNode()
        create = CreatePRNode()
        notify = NotifyPRCreatedNode()

        validate >> create >> notify
        validate - "invalid" >> error_handler

        super().__init__(start=validate)

# Usage
pr_flow = GitHubCreatePRFlow()
pr_flow.set_params({
    "repo": "owner/repo",
    "token": "...",
    "notify_slack": True
})
pr_flow.run(shared)
```

## MCP Wrapper Pattern

With this approach, MCP wrapping becomes elegant:

```python
class McpToolFlow(Flow):
    """Generic flow for any MCP tool."""

    def __init__(self, server_name: str, tool_name: str, tool_schema: dict):
        # Create a node that executes this specific tool
        executor = McpToolExecutorNode(server_name, tool_name, tool_schema)
        super().__init__(start=executor)

        # Store metadata for discovery
        self.metadata = {
            "inputs": extract_inputs_from_schema(tool_schema),
            "outputs": {"result": "any"},
            "parameters": extract_params_from_schema(tool_schema),
            "mcp_source": f"{server_name}/{tool_name}"
        }

# Generate flows for all MCP tools
def register_mcp_server(server_name: str):
    tools = discover_mcp_tools(server_name)

    for tool in tools:
        flow = McpToolFlow(server_name, tool.name, tool.schema)
        registry.register_flow(f"mcp-{server_name}-{tool.name}", flow)
```

## Critical Advantages

### 1. Simplicity Returns
- No action dispatch complexity
- Each flow does one thing well
- Natural shared store interfaces

### 2. Composition Power
- Flows can contain multiple nodes
- Complex operations through simple composition
- Reusable sub-flows

### 3. Parameter Clarity
- Flow parameters are separate from shared store
- No confusion about CLI flags vs inputs
- Built-in parameter propagation

### 4. Natural Evolution Path
- Start with single-node flows (simple)
- Evolve to multi-node flows (complex) as needed
- Same interface to users

## Implementation Strategy

### Phase 1: Core Infrastructure
1. Update CLI to resolve flow names instead of node + action
2. Create flow registry alongside node registry
3. Update metadata extraction for flows

### Phase 2: Migration
1. Convert existing action-based examples to flows
2. Create single-node flows for simple operations
3. Identify opportunities for multi-node flows

### Phase 3: MCP Integration
1. Generate flows from MCP tool definitions
2. Cache tool discovery for performance
3. Seamless integration with native flows

## The Beautiful Realization

**Flows ARE the natural unit of composition in pflow**, not nodes with actions. This aligns perfectly with:

1. **Unix Philosophy**: Each flow does one thing well
2. **Composition**: Flows compose naturally with `>>`
3. **Simplicity**: No action dispatch complexity
4. **Flexibility**: Single-node or multi-node as needed

## Example Flow Definitions

### File Operations (Simple)
```python
# read_file_flow.py
read_file = Flow(start=ReadFileNode())

# write_file_flow.py
write_file = Flow(start=WriteFileNode())

# No need for FileNode with read/write actions!
```

### LLM Operations (Grouped by similarity)
```python
# llm_complete_flow.py
complete = Flow(start=LLMCompleteNode())

# llm_chat_flow.py
chat = Flow(start=LLMChatNode())

# llm_analyze_flow.py
analyze = Flow(start=LLMAnalyzeNode())

# These share enough logic to potentially use a base class
# but are still separate flows!
```

### Complex Operations (Multi-node)
```python
# youtube_summarize_flow.py
class YouTubeSummarizeFlow(Flow):
    def __init__(self):
        extract = YouTubeTranscriptNode()
        chunk = ChunkTextNode()
        summarize = SummarizeTextNode()

        extract >> chunk >> summarize
        super().__init__(start=extract)
```

## Conclusion

By embracing **Flows as the primary abstraction** instead of action-based nodes:

1. We eliminate the complexity of action dispatch
2. We avoid shared store key collisions
3. We get natural composition and parameter handling
4. We align perfectly with pflow's philosophy

The pocketflow-mcp example shows us the way: **use the framework's natural abstractions** instead of fighting against them with complex action-based patterns.

**Flows, not actions, are the answer.**

## Addendum: How This Solves All Our Problems

Let's revisit the problems from our action-based analysis and see how flows solve them:

### Problem 1: Output Key Collisions ✅ SOLVED
**Action-based issue**: `get-issue` and `create-issue` both write to `shared["issue_data"]`

**Flow solution**:
```python
# Separate flows with clear interfaces
GitHubGetIssueFlow:    writes to shared["issue"]
GitHubCreateIssueFlow: writes to shared["created_issue"]

# No collision possible!
```

### Problem 2: Input/Parameter Confusion ✅ SOLVED
**Action-based issue**: Unclear when to use CLI params vs shared store

**Flow solution**:
```python
# Crystal clear separation
flow.set_params({"repo": "owner/repo"})  # CLI parameters
flow.run(shared)                          # Shared store data

# Params flow to nodes automatically via pocketflow!
```

### Problem 3: Natural Key Naming ✅ SOLVED
**Action-based issue**: Natural naming leads to overwrites in flows

**Flow solution**:
```python
# Each flow has its own natural interface
MarkdownToHtmlFlow: reads shared["markdown"], writes shared["html"]
HtmlToPdfFlow:      reads shared["html"], writes shared["pdf"]

# Natural and no conflicts!
```

### Problem 4: Static vs Dynamic Interfaces ✅ SOLVED
**Action-based issue**: How to declare dynamic behavior in static metadata?

**Flow solution**:
```python
# Use different flows for different behaviors
GitHubSearchSingleFlow:    returns shared["issue"]
GitHubSearchMultipleFlow:  returns shared["issues"]

# Or use flow composition with conditional nodes
search >> check_results
check_results - "single" >> format_single
check_results - "multiple" >> format_multiple
```

### The MCP Connection

The pocketflow-mcp example essentially does:
1. **Discover tools** (like our registry)
2. **Select tool** (like our CLI command)
3. **Execute tool** (like our node execution)

But it does this as a FLOW, not as an action-based node. This is the key insight!

For pflow:
- Each MCP tool becomes a Flow
- Tool discovery happens at registration time (cached)
- User selects the flow directly via CLI
- No dynamic action dispatch needed

### The Ultimate Simplification

**Before** (Complex Action-Based):
```bash
pflow github --action=get-issue --repo=owner/repo --issue=123
# Requires: Action dispatch, metadata per action, key collision management
```

**After** (Simple Flow-Based):
```bash
pflow github-get-issue --repo=owner/repo --issue=123
# Just: Run a flow with params. That's it.
```

This is not just simpler - it's **fundamentally more aligned** with how pocketflow works. We're using the framework as intended, not building complex patterns on top of it.

## The Path Forward

1. **Embrace single-purpose flows** over multi-action nodes
2. **Use flow composition** for complex operations
3. **Let pocketflow handle** parameter propagation
4. **Keep interfaces natural** without collision worries
5. **Generate flows from MCP** instead of action-based wrappers

This is the architecture that pflow was meant to have.
