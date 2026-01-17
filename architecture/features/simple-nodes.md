# Simple Node Architecture

## Overview

pflow implements a **simple, single-purpose node architecture** that dramatically reduces cognitive load while maintaining clear interfaces. Each node has one specific purpose, with smart exceptions like the general-purpose `llm` node to prevent proliferation of similar prompt-based nodes.

## Architecture Comparison

> **Note on Syntax**: The `>>` syntax below illustrates data flow between nodes conceptually.
> This is PocketFlow's Python operator for node chaining (used internally by the compiler).
> To run workflows, use JSON workflow files: `pflow workflow.json` or `pflow saved-name param=value`

### Before: Complex Action-Based Nodes
```bash
# Complex nodes with internal action dispatch (NOT OUR PATTERN)
github --action=get-issue --issue=1234 >>
claude --action=analyze --prompt="understand this issue" >>
claude --action=implement --prompt="create fix" >>
git --action=commit --message="Fix issue 1234"
```

**Problems**:
- **Complex APIs**: Each node requires learning multiple actions
- **Magic Dispatch**: Internal routing hides implementation complexity
- **Parameter Confusion**: Different actions need different parameter sets
- **Hard to Compose**: Action-specific interfaces complicate flow design

### After: Simple, Single-Purpose Nodes
```bash
# Clear, focused nodes with single responsibilities
shell --command="gh issue view 1234 --json title,body" >>
llm --prompt="Analyze this issue and suggest a fix" >>
write-file implementation.py >>
shell --command="git commit -m 'Fix issue 1234'"
```

**Benefits**:
- **Crystal Clear Purpose**: Each node does exactly one thing
- **No Magic**: Simple, predictable interfaces
- **Easy Composition**: Natural data flow between nodes
- **Smart Exceptions**: General `llm` node replaces many specific prompt nodes
- **Future-Ready**: Clean foundation for v2.0 CLI grouping syntax

## Simple Nodes Overview

### Core Simple Nodes (MVP)

| Node | Purpose | Interface |
|------|---------|-----------|
| **[`llm`](../core-node-packages/llm-nodes.md)** | General-purpose LLM processing | Reads: `prompt` → Writes: `response` |
| **`read-file`** | Read file contents | Reads: `file_path` → Writes: `content` |
| **`write-file`** | Write file contents | Reads: `content`, `file_path` → Writes: `written` |
| **`copy-file`** | Copy a file | Reads: `source`, `destination` → Writes: `copied` |
| **`shell`** | Execute shell commands | Reads: `command` → Writes: `stdout`, `stderr` |
| **`http`** | Make HTTP requests | Reads: `url`, `method` → Writes: `response` |
| **[`claude-code`](../core-node-packages/claude-nodes.md)** | Claude Code CLI for complex tasks | Reads: `instructions` → Writes: `code_report` |

### The LLM Node: Smart Exception to Prevent Proliferation

The `llm` node is our general-purpose solution for all text processing tasks:
- **Instead of**: `analyze-code`, `write-content`, `explain-concept`, `review-text`
- **Use**: `llm --prompt="Analyze this code"`, `llm --prompt="Write an introduction"`, etc.
- **Future Integration**: Will wrap Simon Willison's llm CLI for model management

## Simple Node Implementation

### Node Implementation Pattern

Nodes follow the interface patterns defined in our [metadata schema](../reference/ir-schema.md#node-metadata-schema). All nodes inherit from `pocketflow.BaseNode` (or `pocketflow.Node`) and use the [shared store pattern](../core-concepts/shared-store.md) for communication.

```python
class ReadFileNode(Node):  # Use Node for retry support
    """Read file contents from disk.

    Reads the contents of a file from the local filesystem.

    Interface:
    - Reads: shared["file_path"]: str  # Path to file to read
    - Writes: shared["content"]: str  # File contents
    - Writes: shared["error"]: str  # Error message if operation failed
    - Actions: default (success), not_found (file doesn't exist)
    """

    # Node name is determined by:
    # 1. class.name attribute if present
    # 2. Otherwise, kebab-case conversion of class name
    name = "read-file"  # Optional explicit name

    def prep(self, shared):
        # Read from params (template resolution handles shared store wiring)
        file_path = self.params.get("file_path")
        if not file_path:
            raise ValueError("file_path parameter is required")
        return file_path

    def exec(self, prep_res):
        file_path = prep_res
        with open(file_path, "r") as f:
            return f.read()

    def post(self, shared, prep_res, exec_res):
        if exec_res is None:
            shared["error"] = "File not found"
            return "not_found"
        shared["content"] = exec_res
        return "default"
```

### Natural Interface Consistency

All simple nodes follow clear interface patterns based on our [shared store design](../core-concepts/shared-store.md#natural-interfaces):
- **Input**: Natural shared store keys (`shared["repo"]`, `shared["issue"]`, `shared["prompt"]`)
- **Parameters**: Node configuration via CLI flags (`--repo`, `--token`)
- **Output**: Structured results in natural shared store keys
- **Documentation**: Every node clearly documents its interface

## MCP Alignment Benefits

### Direct Mapping to MCP Tools
```javascript
// MCP server exposes multiple tools
{
  "name": "slack",
  "tools": ["send_message", "list_channels", "get_thread"]
}

// Each MCP tool becomes a simple pflow node with naming: mcp-<server>-<tool>
mcp-slack-send_message
mcp-slack-list_channels
mcp-slack-get_thread
```

### MCP Integration
MCP servers are fully integrated - each MCP tool maps to a pflow node:
- Each MCP tool maps to exactly one simple node
- Clear, predictable interfaces without internal complexity
- Consistent user experience between native and MCP nodes
- Node naming: `mcp-<server>-<tool>` (e.g., `mcp-slack-send_message`)

## Natural Interface Pattern

### Consistent Key Naming

All pflow nodes follow predictable shared store key patterns that make workflow composition intuitive:

**File Operations**:
- `shared["file_path"]` - Path to file
- `shared["content"]` - File contents
- `shared["encoding"]` - File encoding (optional)

**GitHub Operations**:
- `shared["issue"]` - Issue object/details
- `shared["repo"]` - Repository name
- `shared["pr"]` - Pull request details
- `shared["issue_title"]` - Issue title (when extracted)

**Git Operations**:
- `shared["commit_message"]` - Commit message
- `shared["branch"]` - Branch name
- `shared["commit_hash"]` - Result of commit

**LLM Operations**:
- `shared["prompt"]` - Input prompt
- `shared["response"]` - LLM response

**CI/Testing Operations**:
- `shared["test_command"]` - Command to run
- `shared["test_results"]` - Test execution results
- `shared["exit_code"]` - Command exit code

### Benefits of Natural Interfaces

This consistency provides significant advantages:

1. **Reduces Cognitive Load**: When composing workflows, you can predict what keys nodes expect
2. **Makes Workflows Self-Documenting**: Reading a workflow shows clear data flow
3. **Enables Node Composition Without Documentation**: Natural key names guide integration
4. **Supports Learning Through Exploration**: Consistent patterns teach the system

### Example: Natural Data Flow

```bash
# The key names make the data flow obvious
read-file --file_path=data.json >>      # Writes: shared["content"]
llm --prompt="Analyze ${content}" >>    # Reads: shared["content"], Writes: shared["response"]
write-file analysis.md                  # Reads: shared["response"] as content
```

No documentation needed - the natural interfaces guide composition.

## User Experience Benefits

### Discovery and Learning
```bash
# See all available nodes by category
$ pflow registry list file
📦 File Nodes:
- read-file: Read file contents from disk
- write-file: Write content to a file
- copy-file: Copy a file to a new location
- delete-file: Delete a file from disk

# Get detailed interface for specific node
$ pflow registry describe read-file
Reads: shared["file_path"]
Writes: shared["content"]
Params: --file_path
```

### Reduced Cognitive Load
- **Before**: Learn complex action dispatch and parameter mapping
- **After**: Each node does exactly one thing with clear interface

### Natural Workflow Patterns
Simple nodes create clear, linear workflows:
```bash
# Natural thought process: "Read file, analyze, write report"
read-file --file_path=code.py >>
llm --prompt="Review this code and suggest improvements" >>
write-file review.md
```

### Using Shell for Git/GitHub Operations
For Git and GitHub operations, use the `shell` node with CLI tools:
```bash
# GitHub operations via gh CLI
shell --command="gh issue view 123 --json title,body" >>
llm --prompt="Analyze this issue" >>
shell --command="gh issue comment 123 --body '${response}'"

# Git operations via git CLI
shell --command="git status --porcelain" >>
llm --prompt="Summarize these changes" >>
shell --command="git commit -m '${response}'"
```

## Real-World Examples

### Daily Standup Automation
```bash
# Business scenario: Automate morning standup preparation
$ pflow "check my team's open PRs, get failing CI builds, format for standup"

# Generated simple node workflow:
shell --command="gh pr list --state=open --json title,author,url" >>
shell --command="gh run list --status=failure --json name,conclusion" >>
llm --prompt="Format these updates as a standup report"

# Subsequent executions:
$ pflow standup-prep
```

### Production Incident Investigation
```bash
# Business scenario: Investigate production errors and correlate with recent changes
$ pflow "get recent errors, find related deploys, identify likely cause"

# Generated simple node workflow:
http --url="https://api.datadog.com/errors?window=1h" >>
shell --command="gh pr list --state=merged --json title,mergedAt" >>
llm --prompt="Correlate these errors with recent changes and identify likely cause"
```

### Customer Churn Analysis
```bash
# Business scenario: Identify churn signals from payment and CRM data
$ pflow "get stripe failed payments last 30 days, match with hubspot contacts, identify churn signals"

# Generated simple node workflow:
stripe-list-failed-payments --days=30 >>
hubspot-get-contacts >>
llm --prompt="Analyze churn risk from this payment and contact data" >>
write-file churn-analysis.csv
```

### Multi-System Deployment
```bash
# Business scenario: Coordinate deployment across multiple systems
$ pflow "deploy to staging"

# Generated simple node workflow:
shell --command="gh release create v2.0 --generate-notes" >>
shell --command="aws deploy create-deployment --application-name myapp --deployment-group staging" >>
http --method=POST --url="https://slack.com/api/chat.postMessage" --body='{"channel":"deploys","text":"Staging deployment complete"}'
```

## Trade-offs and Considerations

### Acknowledged Downsides

**1. More Node Names to Learn**
- Simple nodes: `read-file`, `write-file`, `shell`, `llm`
- Action-based (NOT our pattern): `file --action=read`
- **Trade-off**: More distinct names but each with crystal-clear purpose

**2. General LLM Node Complexity**
- All text processing goes through one `llm` node with different prompts
- Users need to craft appropriate prompts for different tasks
- **Mitigation**: Clear examples and future template system

**3. Node Name Length**
- Names like `read-file` are longer than `file`
- **Trade-off**: Longer names for absolute clarity of purpose

### Why These Trade-offs Are Acceptable

1. **Simplicity Wins**: Each node does exactly one thing, no magic
2. **Clear Mental Model**: No hidden complexity or action dispatch
3. **Easy Composition**: Natural data flow without parameter confusion
4. **Future-Proof**: Clean foundation for CLI grouping and MCP integration
5. **LLM Node Prevents Proliferation**: One flexible node vs dozens of specific prompt nodes

## Implementation Strategy

### Metadata Schema Updates

Simple nodes have straightforward metadata without action complexity, following our [node metadata schema](../reference/ir-schema.md#node-metadata-schema):
```json
{
  "id": "read-file",
  "type": "simple",
  "description": "Read file contents from disk",
  "interface": {
    "reads": ["file_path"],
    "writes": ["content"],
    "params": {
      "file_path": {"type": "string", "description": "Path to file to read"}
    }
  }
}
```

### Planning Engine Updates
The LLM planner works with simple node selection:
- Select specific nodes based on exact requirements
- No action dispatch complexity to manage
- Clear interface matching between nodes
- General `llm` node for all text processing tasks

### Registry System Updates
Node discovery supports simple node organization:
- `pflow registry list file` shows related file nodes
- `pflow registry describe read-file` shows specific node interface
- Clear categorization by platform or function
- Simple interface documentation

## Migration from Action-Based Approach

### Documentation Updates
- ✅ Update MVP scope examples to use simple node syntax
- ✅ Revise implementation plans for individual simple nodes
- ✅ Create simple node specifications (read-file, write-file, etc.)
- ✅ Update component inventory to reflect simple node architecture

### Implementation Updates
- Update node registry for simple node metadata
- Modify planner to select specific nodes instead of actions
- Implement simple node pattern without dispatch complexity
- Update CLI flag resolution for direct node parameters

## Future Extensibility

### Adding New Nodes
```python
# Adding new functionality follows a simple pattern
class ExtractJsonFieldNode(Node):
    """Extract a field from JSON data.

    Interface:
    - Reads: shared["json_data"]: dict  # JSON data to extract from
    - Writes: shared["extracted"]: any  # Extracted field value
    - Params: field: str  # JSON path to extract (e.g., "data.items[0].name")
    """

    def exec(self, prep_res):
        # Simple, focused implementation
        return extract_json_path(prep_res, self.params.get("field"))
```

### Adding New Platforms
New platforms follow the same simple pattern:
- Create individual nodes for each operation
- Each node has clear, single purpose
- Follow consistent interface patterns
- Add to registry with simple metadata
- For external APIs, prefer using `shell` with CLI tools or MCP servers

## Conclusion

The simple node architecture provides:
- **Crystal clear purpose** - each node does exactly one thing
- **No magic** - simple, predictable interfaces without hidden complexity
- **Easy composition** - natural data flow between focused nodes
- **Smart exceptions** - general `llm` node prevents prompt node proliferation
- **Future-ready** - clean foundation for CLI grouping and MCP integration

This architecture enables pflow to deliver on its promise of transforming AI-assisted development workflows while embracing simplicity and clarity over complexity.

## See Also

- [Shared Store](../core-concepts/shared-store.md) - Node communication pattern
- [Node Metadata](../reference/ir-schema.md#node-metadata-schema) - Interface format
- [Registry](../architecture.md#node-naming) - Node discovery
