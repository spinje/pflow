# Simple Node Architecture

## Overview

pflow implements a **simple, single-purpose node architecture** that dramatically reduces cognitive load while maintaining clear interfaces. Each node has one specific purpose, with smart exceptions like the general-purpose `llm` node to prevent proliferation of similar prompt-based nodes.

## Architecture Comparison

### Before: Complex Action-Based Nodes
```bash
# Complex nodes with internal action dispatch (NOT OUR PATTERN)
github --action=get-issue --issue=1234 >>
claude --action=analyze --prompt="understand this issue" >>
claude --action=implement --prompt="create fix" >>
ci --action=run-tests >>
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
github-get-issue --repo=owner/repo --issue=1234 >>
llm --prompt="Analyze this issue and suggest a fix" >>
write-file implementation.py >>
run-tests --command="pytest tests/" >>
git-commit --message="Fix issue 1234"
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
| **[`github-get-issue`](../core-node-packages/github-nodes.md#github-get-issue)** | Retrieve GitHub issue details | Reads: `issue_number`, `repo` → Writes: `issue` |
| **[`github-create-issue`](../core-node-packages/github-nodes.md#github-create-issue)** | Create new GitHub issue | Reads: `title`, `body`, `repo` → Writes: `created_issue` |
| **[`github-list-prs`](../core-node-packages/github-nodes.md#github-list-prs)** | List GitHub pull requests | Reads: `repo`, `state` → Writes: `prs` |
| **[`llm`](../core-node-packages/llm-nodes.md)** | General-purpose LLM processing | Reads: `prompt` → Writes: `response` |
| **`read-file`** | Read file contents | Reads: `file_path` → Writes: `content` |
| **`write-file`** | Write file contents | Reads: `content`, `file_path` → Writes: `written` |
| **[`run-tests`](../core-node-packages/ci-nodes.md#run-tests)** | Execute test commands | Reads: `test_command` → Writes: `test_results` |
| **`git-commit`** | Create git commit | Reads: `message`, `files` → Writes: `commit_hash` |

### The LLM Node: Smart Exception to Prevent Proliferation

The `llm` node is our general-purpose solution for all text processing tasks:
- **Instead of**: `analyze-code`, `write-content`, `explain-concept`, `review-text`
- **Use**: `llm --prompt="Analyze this code"`, `llm --prompt="Write an introduction"`, etc.
- **Future Integration**: Will wrap Simon Willison's llm CLI for model management

## Simple Node Implementation

### Node Implementation Pattern

Nodes follow the interface patterns defined in our [metadata schema](../core-concepts/schemas.md#node-metadata-schema). All nodes inherit from `pocketflow.Node` and use the [shared store pattern](../core-concepts/shared-store.md) for communication.

```python
class GitHubGetIssueNode(Node):
    """Get GitHub issue details.

    Interface:
    - Reads: shared["issue_number"] OR params["issue_number"]
    - Writes: shared["issue"]
    - Params: repo, token, issue_number (optional)
    """

    def prep(self, shared):
        # Check shared store first (dynamic), then params (static)
        issue_number = shared.get("issue_number") or self.params.get("issue_number")
        if not issue_number:
            raise ValueError("issue_number must be in shared store or params")
        return issue_number

    def exec(self, issue_number):
        repo = self.params.get("repo")
        token = self.params.get("token")
        return github_api.get_issue(repo, issue_number, token)

    def post(self, shared, prep_res, exec_res):
        shared["issue"] = exec_res
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
  "name": "github-server",
  "tools": ["get-issue", "create-issue", "list-prs", "create-pr"]
}

// Each MCP tool becomes a simple pflow node
mcp-github-get-issue
mcp-github-create-issue
mcp-github-list-prs
mcp-github-create-pr
```

### Future MCP Integration
When MCP servers are integrated in v2.0, simple nodes provide natural compatibility:
- Each MCP tool maps to exactly one simple node
- Clear, predictable interfaces without internal complexity
- Consistent user experience between native and MCP nodes
- Future CLI grouping syntax aligns naturally: `pflow mcp github get-issue`

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
github-get-issue --issue=123 >>         # Writes: shared["issue"]
llm --prompt="Analyze $issue" >>        # Reads: shared["issue"], Writes: shared["response"]
write-file analysis.md                  # Reads: shared["response"] as content
```

No documentation needed - the natural interfaces guide composition.

## User Experience Benefits

### Discovery and Learning
```bash
# See all available nodes by category
$ pflow registry list --category=github
📦 GitHub Nodes:
- github-get-issue: Retrieve issue details by number
- github-create-issue: Create new issue with title and body
- github-list-prs: List pull requests with filtering
- github-create-pr: Create pull request from branch

# Get detailed interface for specific node
$ pflow describe github-get-issue
Reads: shared["issue_number"], shared["repo"]
Writes: shared["issue"]
Params: --repo, --token, --issue (optional)
```

### Reduced Cognitive Load
- **Before**: Learn complex action dispatch and parameter mapping
- **After**: Each node does exactly one thing with clear interface

### Natural Workflow Patterns
Simple nodes create clear, linear workflows:
```bash
# Natural thought process: "Get issue, analyze, implement, test"
github-get-issue --repo=owner/repo --issue=123 >>
llm --prompt="Analyze this issue and suggest a fix" >>
write-file fix.py >>
run-tests --command="pytest tests/" >>
git-commit --message="Fix issue 123"
```

### Future CLI Grouping (v2.0)
While nodes remain simple underneath, v2.0 will add convenient CLI grouping:
```bash
# v2.0 CLI sugar - same simple nodes underneath
pflow github get-issue --repo=owner/repo --issue=123
pflow github create-pr --title="Fix" --branch=fix-branch

# This is purely CLI convenience, not node architecture!
# Internally maps to: github-get-issue, github-create-pr
```

## Real-World Examples

### Daily Standup Automation
```bash
# Business scenario: Automate morning standup preparation
$ pflow "check my team's open PRs, get failing CI builds, summarize weekend slack alerts, format for standup"

# Generated simple node workflow:
github-list-prs --team=backend >>
ci-get-failures >>
slack-get-messages --since=friday >>
llm --prompt="Format these updates as a standup report"

# Subsequent executions:
$ pflow standup-prep
```

### Production Incident Investigation
```bash
# Business scenario: Investigate production errors and correlate with recent changes
$ pflow "get datadog errors last hour, find related deploys, check which PRs merged, identify likely cause"

# Generated simple node workflow:
datadog-get-errors --window=1h >>
github-get-deploys >>
github-get-merged-prs >>
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
github-create-release --tag=v2.0 >>
aws-deploy --env=staging >>
slack-send-message --channel=deploys --message="Staging deployment complete"
```

## Trade-offs and Considerations

### Acknowledged Downsides

**1. More Node Names to Learn**
- Simple nodes: `github-get-issue`, `github-create-issue`, `github-list-prs`
- Action-based (NOT our pattern): `github --action=get-issue`
- **Trade-off**: More distinct names but each with crystal-clear purpose

**2. General LLM Node Complexity**
- All text processing goes through one `llm` node with different prompts
- Users need to craft appropriate prompts for different tasks
- **Mitigation**: Clear examples and future template system

**3. Node Name Length**
- Names like `github-get-issue` are longer than `github`
- **Trade-off**: Longer names for absolute clarity of purpose

### Why These Trade-offs Are Acceptable

1. **Simplicity Wins**: Each node does exactly one thing, no magic
2. **Clear Mental Model**: No hidden complexity or action dispatch
3. **Easy Composition**: Natural data flow without parameter confusion
4. **Future-Proof**: Clean foundation for CLI grouping and MCP integration
5. **LLM Node Prevents Proliferation**: One flexible node vs dozens of specific prompt nodes

## Implementation Strategy

### Metadata Schema Updates

Simple nodes have straightforward metadata without action complexity, following our [node metadata schema](../core-concepts/schemas.md#node-metadata-schema):
```json
{
  "id": "github-get-issue",
  "type": "simple",
  "description": "Retrieve GitHub issue details by number",
  "interface": {
    "reads": ["issue_number", "repo"],
    "writes": ["issue"],
    "params": {
      "repo": {"type": "string", "description": "Repository name"},
      "token": {"type": "string", "description": "GitHub API token"},
      "issue_number": {"type": "integer", "description": "Issue number (optional if in shared store)"}
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
- `pflow registry list --category=github` shows related nodes
- `pflow describe github-get-issue` shows specific node interface
- Clear categorization by platform or function
- Simple interface documentation

## Migration from Action-Based Approach

### Documentation Updates
- ✅ Update MVP scope examples to use simple node syntax
- ✅ Revise implementation plans for individual simple nodes
- ✅ Create simple node specifications (github-get-issue, etc.)
- ✅ Update component inventory to reflect simple node architecture

### Implementation Updates
- Update node registry for simple node metadata
- Modify planner to select specific nodes instead of actions
- Implement simple node pattern without dispatch complexity
- Update CLI flag resolution for direct node parameters

## Future Extensibility

### Adding New Nodes
```python
# Adding new GitHub functionality is simple
class GitHubGetCommitsNode(Node):
    """Get repository commit history.

    Interface:
    - Reads: shared["repo"]
    - Writes: shared["commits"]
    - Params: repo, token, limit
    """

    def exec(self, prep_res):
        # Simple, focused implementation
        return github_api.get_commits(...)
```

### Adding New Platforms
New platforms follow the same simple pattern:
- Create individual nodes for each operation (e.g., "slack-send-message", "aws-deploy")
- Each node has clear, single purpose
- Follow consistent interface patterns
- Add to registry with simple metadata

## Conclusion

The simple node architecture provides:
- **Crystal clear purpose** - each node does exactly one thing
- **No magic** - simple, predictable interfaces without hidden complexity
- **Easy composition** - natural data flow between focused nodes
- **Smart exceptions** - general `llm` node prevents prompt node proliferation
- **Future-ready** - clean foundation for CLI grouping and MCP integration

This architecture enables pflow to deliver on its promise of transforming AI-assisted development workflows while embracing simplicity and clarity over complexity.

## See Also

- **Core Patterns**: [Shared Store + Proxy Pattern](../core-concepts/shared-store.md) - Understanding data flow and node communication
- **Node Specifications**:
  - [GitHub Nodes](../core-node-packages/github-nodes.md) - Platform integration nodes
  - [Claude Nodes](../core-node-packages/claude-nodes.md) - Development automation "super node"
  - [CI Nodes](../core-node-packages/ci-nodes.md) - Testing and deployment nodes
  - [LLM Node](../core-node-packages/llm-nodes.md) - General text processing
- **Implementation Details**:
  - [Node Metadata Schema](../core-concepts/schemas.md#node-metadata-schema) - Interface format specification
  - [Registry System](../core-concepts/registry.md) - Node discovery and management
  - [CLI Runtime](./cli-runtime.md) - How nodes integrate with the CLI
