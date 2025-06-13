# Action-Based Node Architecture

## Overview

pflow implements an **action-based platform node architecture** that dramatically reduces cognitive load while aligning with MCP (Model Context Protocol) patterns. Instead of many specific function nodes, we use fewer platform nodes with action dispatch.

## Architecture Comparison

### Before: Coarse-Grained Specific Nodes
```bash
# Many specific nodes to learn and maintain
gh-issue-view >> claude-analyze >> claude-implement >> run-tests >> lint >> create-pr
```

**Problems**:
- **High Cognitive Load**: ~30+ specific function nodes to learn
- **Maintenance Burden**: Each function needs separate node implementation
- **Discovery Difficulty**: Hard to find all capabilities of a platform
- **Inconsistent Interfaces**: Different patterns across related functions

### After: Fine-Grained Action-Based Platform Nodes
```bash
# Fewer platform nodes with action dispatch
github --action=get-issue --issue=1234 >>
claude --action=analyze --prompt="understand this issue" >>
claude --action=implement --prompt="create fix" >>
ci --action=run-tests >>
git --action=commit --message="Fix issue 1234" >>
github --action=create-pr --title="Fix for issue 1234"
```

**Benefits**:
- **Cognitive Load Reduction**: ~6 platform nodes vs ~30+ specific function nodes
- **Natural Grouping**: All GitHub operations through one `github` node
- **MCP Alignment**: Direct 1:1 mapping with MCP server tool patterns
- **Easier Discovery**: `pflow describe github` shows all available actions
- **Flexible Extension**: Add actions without breaking existing workflows

## Platform Nodes Overview

### Core Platform Nodes (MVP)

| Platform | Actions | Purpose |
|----------|---------|---------|
| **`github`** | `get-issue`, `create-issue`, `list-prs`, `create-pr`, `get-files`, `merge-pr`, `add-comment` | GitHub API operations |
| **`claude`** | `analyze`, `implement`, `review`, `explain`, `refactor` | AI-assisted development |
| **`ci`** | `run-tests`, `get-status`, `trigger-build`, `get-logs`, `analyze-coverage` | Continuous integration |
| **`git`** | `commit`, `push`, `create-branch`, `merge`, `status` | Git operations |
| **`file`** | `read`, `write`, `copy`, `move`, `delete` | File system operations |
| **`shell`** | `exec`, `pipe`, `background` | Shell command execution |

## Action Dispatch Pattern

### Node Implementation
```python
class GitHubNode(Node):
    """GitHub API operations via action dispatch."""

    def exec(self, prep_res):
        action = self.params.get("action")

        if action == "get-issue":
            return self._get_issue(prep_res)
        elif action == "create-issue":
            return self._create_issue(prep_res)
        elif action == "list-prs":
            return self._list_prs(prep_res)
        # ... other actions
        else:
            raise ValueError(f"Unknown GitHub action: {action}")
```

### Natural Interface Consistency
All platform nodes follow the same natural interface pattern:
- **Input**: Natural shared store keys (`shared["repo"]`, `shared["issue"]`, `shared["code"]`)
- **Parameters**: Action-specific configuration via `--action=` and other flags
- **Output**: Structured results in natural shared store keys
- **Error Handling**: Consistent action strings for error flows

## MCP Alignment Benefits

### Direct Mapping to MCP Servers
```javascript
// MCP server exposes multiple tools
{
  "name": "github-server",
  "tools": ["get-issue", "create-issue", "list-prs", "create-pr"]
}

// pflow node follows same pattern
github --action=get-issue
github --action=create-issue
github --action=list-prs
github --action=create-pr
```

### Future MCP Integration
When MCP servers are integrated in v2.0, the action-based architecture provides seamless compatibility:
- Each MCP tool maps directly to a node action
- No architectural changes needed for MCP integration
- Consistent user experience between manual and MCP nodes

## User Experience Benefits

### Discovery and Learning
```bash
# See all capabilities of a platform
$ pflow describe github
📦 GitHub Node
Available actions:
- get-issue: Retrieve issue details by number
- create-issue: Create new issue with title and body
- list-prs: List pull requests with filtering
- create-pr: Create pull request from branch
...

# Autocomplete helps discovery
$ pflow github --action=<TAB>
get-issue  create-issue  list-prs  create-pr  ...
```

### Reduced Cognitive Load
- **Before**: Remember 30+ specific node names and their purposes
- **After**: Remember 6 platform names and explore their actions

### Natural Workflow Patterns
Action-based workflows mirror how developers think about tasks:
```bash
# Natural thought process: "I need to work with GitHub"
github --action=get-issue       # Get the issue details
github --action=get-files       # Look at the code
claude --action=analyze         # Understand the problem
claude --action=implement       # Create a solution
ci --action=run-tests          # Test the solution
github --action=create-pr       # Share the solution
```

## Implementation Strategy

### Metadata Schema Updates
Action-based nodes require enhanced metadata:
```json
{
  "id": "github",
  "type": "platform",
  "description": "GitHub API operations",
  "actions": {
    "get-issue": {
      "description": "Retrieve issue details by number",
      "inputs": ["repo", "issue"],
      "outputs": ["issue"],
      "params": {"repo": "string", "issue": "integer"}
    }
  }
}
```

### Planning Engine Updates
The LLM planner needs to understand action-based selection:
- Select platform nodes based on capability domains
- Choose appropriate actions based on specific requirements
- Generate action-specific parameters
- Validate action compatibility between nodes

### Registry System Updates
Node discovery and documentation systems support action-based patterns:
- `pflow registry list` shows platform nodes
- `pflow describe <platform>` shows all available actions
- Action-specific help and examples
- Parameter validation per action

## Migration from Coarse-Grained Approach

### Documentation Updates
- ✅ Update MVP scope examples to use action-based syntax
- ✅ Revise implementation plans for platform nodes with actions
- ✅ Create platform node specifications (github, claude, ci)
- ✅ Update component inventory to reflect action-based architecture

### Implementation Updates
- Update node registry to handle action metadata
- Modify planner to select actions instead of specific nodes
- Implement action dispatch pattern in node base classes
- Update CLI flag resolution for action parameters

## Future Extensibility

### Adding New Actions
```python
# Adding new GitHub action is simple
def _get_commits(self, prep_res):
    """Get repository commit history"""
    # Implementation here

# Update dispatch in exec()
elif action == "get-commits":
    return self._get_commits(prep_res)
```

### Adding New Platforms
New platforms follow the same pattern:
- Identify the platform domain (e.g., "slack", "aws", "docker")
- Define relevant actions for that platform
- Implement action dispatch pattern
- Add to registry with action metadata

## Conclusion

The action-based platform node architecture provides:
- **10x reduction in cognitive load** (6 platforms vs 60+ specific nodes)
- **Direct MCP alignment** for future integration
- **Natural workflow patterns** that match developer thinking
- **Flexible extensibility** without breaking existing flows
- **Consistent user experience** across all platform operations

This architecture enables pflow to deliver on its promise of transforming AI-assisted development workflows while maintaining simplicity and discoverability.
