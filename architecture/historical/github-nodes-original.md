# GitHub Node Package Specification

> **Prerequisites**: Before implementing or using these nodes, read the [Node Implementation Reference](../reference/node-reference.md) for common patterns and best practices.

> **Note on Implementation Status**: This is a specification document. Currently implemented nodes are:
> `github-get-issue`, `github-list-issues`, `github-list-prs`, `github-create-pr`.
> Run `pflow registry list` to see all available nodes.

> **Note on Syntax**: The `=>` examples below illustrate conceptual data flow between nodes.
> pflow uses JSON workflow files for composition, not CLI pipe syntax.
> To run workflows: `pflow workflow.json` or `pflow saved-name param=value`

This document specifies the **GitHub node package** - a collection of simple, single-purpose nodes for GitHub operations. Each node handles one specific GitHub API interaction with clear interfaces and natural shared store patterns.

## Node Package Overview

The GitHub node package provides essential GitHub functionality through individual, focused nodes:

| Node | Purpose | Interface |
|------|---------|-----------|
| **`github-get-issue`** | Retrieve issue details | Reads: `issue_number`, `repo` → Writes: `issue` |
| **`github-create-issue`** | Create new issue | Reads: `title`, `body`, `repo` → Writes: `issue` |
| **`github-list-prs`** | List pull requests | Reads: `repo`, `state` (optional) → Writes: `prs` |
| **`github-create-pr`** | Create pull request | Reads: `title`, `body`, `head`, `base` → Writes: `pr` |
| **`github-get-files`** | Get repository files | Reads: `repo`, `path` (optional) → Writes: `files` |
| **`github-merge-pr`** | Merge pull request | Reads: `pr_number`, `repo` → Writes: `merge_result` |
| **`github-add-comment`** | Add issue comment | Reads: `comment`, `issue_number` → Writes: `comment_id` |
| **`github-search-code`** | Search code in repos | Reads: `query`, `repo` (optional) → Writes: `search_results` |

## Individual Node Specifications

### github-get-issue

**Purpose**: Retrieve GitHub issue details by issue number

**Interface**:
- Reads: `shared["issue_number"]`: int  # GitHub issue number
- Reads: `shared["repo"]`: str  # Repository name (owner/repo format)
- Writes: `shared["issue"]`: dict  # Complete issue object with metadata
- Params: `token`: str  # GitHub API token (default: GITHUB_TOKEN env var)

**CLI Examples**:
```bash
# Get specific issue
pflow github-get-issue --repo=owner/project --issue-number=123

# From shared store
echo "456" | pflow github-get-issue --repo=owner/project

# Chain with repo discovery
pflow github-get-repo => github-get-issue --issue-number=789
```

**Parameters**:
- `repo` (optional): Repository name (owner/repo format) - can come from shared store
- `token` (optional): GitHub API token (default: GITHUB_TOKEN env var)
- `issue_number` (optional): Issue number - can come from shared store

### github-create-issue

**Purpose**: Create new GitHub issue

**Interface**:
- Reads: `shared["title"]`: str  # Issue title
- Reads: `shared["body"]`: str  # Issue description (optional)
- Reads: `shared["repo"]`: str  # Repository name (owner/repo format)
- Writes: `shared["issue"]`: dict  # Created issue object
- Params: `token`: str  # GitHub API token
- Params: `labels`: list  # Issue labels
- Params: `assignees`: list  # User logins to assign

**CLI Examples**:
```bash
# Create simple issue
pflow github-create-issue --repo=owner/project --title="Bug report" --body="Description here"

# With labels and assignees
pflow github-create-issue --repo=owner/project --title="Feature request" --labels='["enhancement"]' --assignees='["username"]'

# From LLM generation
pflow llm --prompt="Generate bug report for login issue" => github-create-issue --repo=owner/project
```

### github-list-prs

**Purpose**: List pull requests for a repository

**Interface**:
- Reads: `shared["repo"]`: str  # Repository name (owner/repo format)
- Reads: `shared["state"]`: str  # PR state filter (optional)
- Writes: `shared["prs"]`: list  # Array of pull request objects
- Params: `token`: str  # GitHub API token
- Params: `per_page`: int  # Results per page
- Params: `sort`: str  # Sort order

**CLI Examples**:
```bash
# List open PRs
pflow github-list-prs --repo=owner/project

# List all PRs
pflow github-list-prs --repo=owner/project --state=all

# Chain from repo discovery
pflow github-get-repo => github-list-prs --state=closed
```

### github-create-pr

**Purpose**: Create new pull request

**Interface**:
- Reads: `shared["title"]`: str  # Pull request title
- Reads: `shared["body"]`: str  # Pull request description (optional)
- Reads: `shared["head"]`: str  # Head branch name
- Reads: `shared["base"]`: str  # Base branch name (optional)
- Writes: `shared["pr"]`: dict  # Created pull request object
- Params: `repo`: str  # Repository name
- Params: `token`: str  # GitHub API token
- Params: `draft`: bool  # Create as draft PR

**CLI Examples**:
```bash
# Create PR from feature branch
pflow github-create-pr --repo=owner/project --title="Fix login bug" --head=feature-branch --base=main

# Create draft PR
pflow github-create-pr --repo=owner/project --title="WIP: New feature" --head=feature --draft=true

# Chain from issue analysis
pflow github-get-issue --issue-number=123 =>
  llm --prompt="Create PR title and description to fix this issue" =>
  github-create-pr --head=fix-issue-123
```

### github-get-files

**Purpose**: Get repository files and content

**Interface**:
- Reads: `shared["repo"]`: str  # Repository name (owner/repo format)
- Reads: `shared["path"]`: str  # File or directory path (optional)
- Writes: `shared["files"]`: any  # File listing or content
- Params: `token`: str  # GitHub API token
- Params: `ref`: str  # Branch or commit reference
- Params: `recursive`: bool  # Recursive directory listing

**CLI Examples**:
```bash
# List root files
pflow github-get-files --repo=owner/project

# Get specific file
pflow github-get-files --repo=owner/project --path=src/main.py

# Recursive directory listing
pflow github-get-files --repo=owner/project --path=src --recursive=true
```

### github-merge-pr

**Purpose**: Merge pull request

**Interface**:
- Reads: `shared["pr_number"]`: int  # Pull request number
- Reads: `shared["repo"]`: str  # Repository name (owner/repo format)
- Writes: `shared["merge_result"]`: dict  # Merge operation result
- Params: `token`: str  # GitHub API token
- Params: `merge_method`: str  # Merge method (merge, squash, rebase)
- Params: `commit_title`: str  # Custom commit title

**CLI Examples**:
```bash
# Merge PR
pflow github-merge-pr --repo=owner/project --pr-number=456

# Squash merge
pflow github-merge-pr --repo=owner/project --pr-number=456 --merge-method=squash

# Chain from PR creation
pflow github-create-pr --title="Auto fix" => github-merge-pr --merge-method=squash
```

### github-add-comment

**Purpose**: Add comment to issue or pull request

**Interface**:
- Reads: `shared["comment"]`: str  # Comment text
- Reads: `shared["issue_number"]`: int  # Issue or PR number
- Reads: `shared["repo"]`: str  # Repository name (owner/repo format)
- Writes: `shared["comment_id"]`: int  # Created comment ID
- Params: `token`: str  # GitHub API token

**CLI Examples**:
```bash
# Add comment to issue
pflow github-add-comment --repo=owner/project --issue-number=123 --comment="This is fixed"

# Chain from analysis
pflow github-get-issue --issue-number=123 =>
  llm --prompt="Analyze this issue and provide helpful comment" =>
  github-add-comment --issue-number=123
```

### github-search-code

**Purpose**: Search code in GitHub repositories

**Interface**:
- Reads: `shared["query"]`: str  # Search query string
- Reads: `shared["repo"]`: str  # Repository scope (optional)
- Writes: `shared["search_results"]`: list  # Code search results
- Params: `language`: str  # Programming language filter
- Params: `filename`: str  # Filename pattern
- Params: `extension`: str  # File extension filter
- Params: `size`: str  # File size filter
- Params: `path`: str  # Path filter

**CLI Examples**:
```bash
# Search for function
pflow github-search-code --query="def authenticate" --language=python

# Search in specific repo
pflow github-search-code --query="TODO" --repo=owner/project --extension=py

# Chain from issue
pflow github-get-issue --issue-number=123 =>
  llm --prompt="Extract keywords to search for related code" =>
  github-search-code --repo=owner/project
```

## Node Package Composition Patterns

### Issue Analysis Workflow
```bash
# Get issue → analyze → search related code → comment
pflow github-get-issue --issue-number=123 =>
  llm --prompt="Analyze this issue and suggest search terms" =>
  github-search-code --language=python =>
  llm --prompt="Analyze code and suggest fix" =>
  github-add-comment --issue-number=123
```

### Pull Request Workflow
```bash
# Create branch → make changes → create PR → merge
pflow git-create-branch --name=fix-issue-123 =>
  file-write --path=fix.py =>
  git-commit --message="Fix issue 123" =>
  github-create-pr --title="Fix for issue 123" --head=fix-issue-123 =>
  github-merge-pr
```

### Repository Analysis
```bash
# Get files → analyze structure → create documentation issue
pflow github-get-files --recursive=true =>
  llm --prompt="Analyze repo structure and suggest documentation improvements" =>
  github-create-issue --title="Documentation improvements" --labels='["documentation"]'
```

### Code Review Support
```bash
# List PRs → get files → analyze → comment
pflow github-list-prs --state=open =>
  github-get-files --path=src =>
  llm --prompt="Review code changes and provide feedback" =>
  github-add-comment
```

## Design Principles

### Single Responsibility
Each GitHub node has one clear purpose:
- `github-get-issue`: Only issue retrieval
- `github-create-issue`: Only issue creation
- `github-list-prs`: Only PR listing
- `github-create-pr`: Only PR creation
- `github-get-files`: Only file operations
- `github-merge-pr`: Only merge operations
- `github-add-comment`: Only comment creation
- `github-search-code`: Only code search

### Natural Interfaces

All nodes use intuitive shared store keys:
- `shared["issue"]` for issue data
- `shared["pr"]` for pull request data
- `shared["files"]` for file listings/content
- `shared["search_results"]` for search results
- `shared["repo"]` for repository identification

### Flexible Authentication
Multiple auth methods supported:
- Environment variable (`GITHUB_TOKEN`)
- Parameter override (`--token`)
- GitHub CLI integration (future)
- OAuth flows (future)

### Error Handling
Clear error messages for common issues:
- Missing authentication
- Repository access denied
- Rate limiting
- Resource not found
- Invalid parameters

## Future Extensions

### Additional Nodes (v2.0)
- `github-create-repo`: Repository creation
- `github-fork-repo`: Repository forking
- `github-get-commits`: Commit history
- `github-create-release`: Release management
- `github-manage-labels`: Label operations
- `github-get-contributors`: Contributor data

### Enhanced Features
- GitHub Apps authentication
- Enterprise GitHub support
- Webhook integration
- Advanced search filters
- Batch operations
- File content editing

### MCP Integration
- GitHub MCP server compatibility
- Real-time event streaming
- Advanced permission handling
- Multi-org support

This GitHub node package provides comprehensive GitHub functionality through simple, composable nodes that integrate naturally with other pflow node packages and follow established shared store patterns.

## See Also

- [Simple Nodes](../features/simple-nodes.md) - Node design philosophy
- [Shared Store](../core-concepts/shared-store.md) - Inter-node data flow
- [Node Metadata](../reference/ir-schema.md#node-metadata-schema) - Interface format
