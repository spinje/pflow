# GitHub Platform Node Specification

## Overview

The `github` node is a platform node that provides comprehensive GitHub API integration through action-based dispatch. It follows the MCP-aligned action pattern where a single node provides multiple related capabilities.

## Node Interface

### Basic Information
- **Node ID**: `github`
- **Type**: Platform node with action dispatch
- **Purity**: Impure (modifies external GitHub state)
- **MCP Alignment**: Direct mapping to GitHub MCP server tool patterns

### Natural Interface Pattern

```python
class GitHubNode(Node):
    """GitHub API operations via action dispatch.

    Actions:
    - get-issue: Retrieve issue details by number
    - create-issue: Create new issue with title and body
    - list-prs: List pull requests with filtering
    - create-pr: Create pull request from branch
    - get-files: Get repository file contents
    - merge-pr: Merge pull request
    - add-comment: Add comment to issue or PR

    Interface:
    - Reads: shared["repo"], shared["action"] (via params)
    - Writes: shared["issue"], shared["pr"], shared["files"], shared["result"]
    - Params: action, repo, issue, title, body, branch, etc.
    """
```

## Supported Actions

### 1. get-issue
**Purpose**: Retrieve GitHub issue details

**Parameters**:
- `repo` (required): Repository in "owner/name" format
- `issue` (required): Issue number

**Natural Interface**:
- Reads: `shared["repo"]` (fallback to params), issue number from params
- Writes: `shared["issue"]` - Complete issue object with title, body, labels, etc.

**Example Usage**:
```bash
github --action=get-issue --repo=myorg/myrepo --issue=123
```

**Shared Store Result**:
```python
shared["issue"] = {
    "number": 123,
    "title": "Fix authentication bug",
    "body": "Description of the issue...",
    "state": "open",
    "labels": ["bug", "priority-high"],
    "assignees": ["developer1"]
}
```

### 2. create-issue
**Purpose**: Create new GitHub issue

**Parameters**:
- `repo` (required): Repository in "owner/name" format
- `title` (required): Issue title
- `body` (optional): Issue description
- `labels` (optional): Comma-separated labels
- `assignees` (optional): Comma-separated usernames

**Natural Interface**:
- Reads: `shared["repo"]`, `shared["title"]`, `shared["body"]` (fallback to params)
- Writes: `shared["issue"]` - Created issue object

**Example Usage**:
```bash
github --action=create-issue --repo=myorg/myrepo --title="New bug found" --body="Description here"
```

### 3. list-prs
**Purpose**: List repository pull requests

**Parameters**:
- `repo` (required): Repository in "owner/name" format
- `state` (optional): "open", "closed", "all" (default: "open")
- `limit` (optional): Maximum number of PRs (default: 10)

**Natural Interface**:
- Reads: `shared["repo"]` (fallback to params)
- Writes: `shared["prs"]` - Array of pull request objects

**Example Usage**:
```bash
github --action=list-prs --repo=myorg/myrepo --state=open --limit=5
```

### 4. create-pr
**Purpose**: Create pull request

**Parameters**:
- `repo` (required): Repository in "owner/name" format
- `title` (required): PR title
- `body` (optional): PR description
- `head` (required): Source branch
- `base` (optional): Target branch (default: "main")

**Natural Interface**:
- Reads: `shared["repo"]`, `shared["title"]`, `shared["body"]`, `shared["branch"]`
- Writes: `shared["pr"]` - Created pull request object

**Example Usage**:
```bash
github --action=create-pr --repo=myorg/myrepo --title="Fix issue 123" --head=fix-branch --base=main
```

### 5. get-files
**Purpose**: Retrieve repository file contents

**Parameters**:
- `repo` (required): Repository in "owner/name" format
- `path` (optional): File or directory path (default: root)
- `ref` (optional): Branch/commit reference (default: default branch)

**Natural Interface**:
- Reads: `shared["repo"]`, `shared["path"]` (fallback to params)
- Writes: `shared["files"]` - File contents or directory listing

**Example Usage**:
```bash
github --action=get-files --repo=myorg/myrepo --path=src/main.py
```

### 6. merge-pr
**Purpose**: Merge pull request

**Parameters**:
- `repo` (required): Repository in "owner/name" format
- `pr` (required): Pull request number
- `merge_method` (optional): "merge", "squash", "rebase" (default: "merge")

**Natural Interface**:
- Reads: `shared["repo"]`, `shared["pr"]` (fallback to params)
- Writes: `shared["merge_result"]` - Merge operation result

**Example Usage**:
```bash
github --action=merge-pr --repo=myorg/myrepo --pr=456 --merge-method=squash
```

### 7. add-comment
**Purpose**: Add comment to issue or pull request

**Parameters**:
- `repo` (required): Repository in "owner/name" format
- `issue` or `pr` (required): Issue/PR number
- `comment` (required): Comment text

**Natural Interface**:
- Reads: `shared["repo"]`, `shared["comment"]` (fallback to params)
- Writes: `shared["comment_result"]` - Created comment object

**Example Usage**:
```bash
github --action=add-comment --repo=myorg/myrepo --issue=123 --comment="Fixed in PR #456"
```

## Implementation Details

### Action Dispatch Pattern

```python
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

### Authentication

- **Environment Variable**: `GITHUB_TOKEN` for API authentication
- **Error Handling**: Clear error messages for authentication failures
- **Rate Limiting**: Respect GitHub API rate limits with appropriate backoff

### Error Actions

The node returns action strings for error handling:
- `"default"`: Successful operation
- `"auth_failed"`: Authentication error
- `"rate_limited"`: Rate limit exceeded
- `"not_found"`: Repository/issue/PR not found
- `"permission_denied"`: Insufficient permissions

### Testing Strategy

1. **Unit Tests**: Mock GitHub API responses for each action
2. **Integration Tests**: Real GitHub API testing with test repositories
3. **Error Handling**: Test authentication failures, rate limits, not found scenarios
4. **Action Dispatch**: Verify correct action routing and parameter handling

## Benefits of Action-Based Design

1. **Cognitive Load Reduction**: One node to learn instead of 7+ specific nodes
2. **MCP Alignment**: Direct mapping to GitHub MCP server tool patterns
3. **Easier Discovery**: `pflow describe github` shows all capabilities
4. **Flexible Extension**: Add new actions without breaking existing workflows
5. **Natural Grouping**: All GitHub operations logically grouped together

This design enables workflows like:
```bash
pflow "analyze github issue 123, implement fix, create PR"
# Generates: github --action=get-issue --issue=123 >> claude --action=implement >> github --action=create-pr
```
