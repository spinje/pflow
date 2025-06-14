# GitHub Node Package Specification

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

```python
class GitHubGetIssueNode(Node):
    """Get GitHub issue details by number.

    Interface:
    - Reads: shared["issue_number"], shared["repo"] (optional)
    - Writes: shared["issue"] - complete issue object with metadata
    - Params: repo, token, issue_number (optional if in shared store)
    """

    def prep(self, shared):
        issue_number = shared.get("issue_number") or self.params.get("issue_number")
        if not issue_number:
            raise ValueError("issue_number must be in shared store or params")

        repo = shared.get("repo") or self.params.get("repo")
        if not repo:
            raise ValueError("repo must be in shared store or params")

        return {
            "repo": repo,
            "issue_number": int(issue_number),
            "token": self.params.get("token") or os.getenv("GITHUB_TOKEN")
        }

    def exec(self, prep_res):
        return github_api.get_issue(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["issue"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Get specific issue
pflow github-get-issue --repo=owner/project --issue-number=123

# From shared store
echo "456" | pflow github-get-issue --repo=owner/project

# Chain with repo discovery
pflow github-get-repo >> github-get-issue --issue-number=789
```

**Parameters**:
- `repo` (optional): Repository name (owner/repo format) - can come from shared store
- `token` (optional): GitHub API token (default: GITHUB_TOKEN env var)
- `issue_number` (optional): Issue number - can come from shared store

### github-create-issue

**Purpose**: Create new GitHub issue

```python
class GitHubCreateIssueNode(Node):
    """Create new GitHub issue.

    Interface:
    - Reads: shared["title"], shared["body"] (optional), shared["repo"] (optional)
    - Writes: shared["issue"] - created issue object
    - Params: repo, token, title, body, labels, assignees
    """

    def prep(self, shared):
        title = shared.get("title") or self.params.get("title")
        if not title:
            raise ValueError("title must be in shared store or params")

        repo = shared.get("repo") or self.params.get("repo")
        if not repo:
            raise ValueError("repo must be in shared store or params")

        return {
            "repo": repo,
            "title": title,
            "body": shared.get("body") or self.params.get("body", ""),
            "labels": self.params.get("labels", []),
            "assignees": self.params.get("assignees", []),
            "token": self.params.get("token") or os.getenv("GITHUB_TOKEN")
        }

    def exec(self, prep_res):
        return github_api.create_issue(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["issue"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Create simple issue
pflow github-create-issue --repo=owner/project --title="Bug report" --body="Description here"

# With labels and assignees
pflow github-create-issue --repo=owner/project --title="Feature request" --labels='["enhancement"]' --assignees='["username"]'

# From LLM generation
pflow llm --prompt="Generate bug report for login issue" >> github-create-issue --repo=owner/project
```

### github-list-prs

**Purpose**: List pull requests for a repository

```python
class GitHubListPRsNode(Node):
    """List pull requests for repository.

    Interface:
    - Reads: shared["repo"], shared["state"] (optional)
    - Writes: shared["prs"] - array of pull request objects
    - Params: repo, token, state, per_page, sort
    """

    def prep(self, shared):
        repo = shared.get("repo") or self.params.get("repo")
        if not repo:
            raise ValueError("repo must be in shared store or params")

        return {
            "repo": repo,
            "state": shared.get("state") or self.params.get("state", "open"),
            "per_page": self.params.get("per_page", 30),
            "sort": self.params.get("sort", "created"),
            "token": self.params.get("token") or os.getenv("GITHUB_TOKEN")
        }

    def exec(self, prep_res):
        return github_api.list_prs(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["prs"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# List open PRs
pflow github-list-prs --repo=owner/project

# List all PRs
pflow github-list-prs --repo=owner/project --state=all

# Chain from repo discovery
pflow github-get-repo >> github-list-prs --state=closed
```

### github-create-pr

**Purpose**: Create new pull request

```python
class GitHubCreatePRNode(Node):
    """Create new pull request.

    Interface:
    - Reads: shared["title"], shared["body"] (optional), shared["head"], shared["base"] (optional)
    - Writes: shared["pr"] - created pull request object
    - Params: repo, token, title, body, head, base, draft
    """

    def prep(self, shared):
        title = shared.get("title") or self.params.get("title")
        head = shared.get("head") or self.params.get("head")

        if not title:
            raise ValueError("title must be in shared store or params")
        if not head:
            raise ValueError("head branch must be in shared store or params")

        repo = shared.get("repo") or self.params.get("repo")
        if not repo:
            raise ValueError("repo must be in shared store or params")

        return {
            "repo": repo,
            "title": title,
            "body": shared.get("body") or self.params.get("body", ""),
            "head": head,
            "base": shared.get("base") or self.params.get("base", "main"),
            "draft": self.params.get("draft", False),
            "token": self.params.get("token") or os.getenv("GITHUB_TOKEN")
        }

    def exec(self, prep_res):
        return github_api.create_pr(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["pr"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Create PR from feature branch
pflow github-create-pr --repo=owner/project --title="Fix login bug" --head=feature-branch --base=main

# Create draft PR
pflow github-create-pr --repo=owner/project --title="WIP: New feature" --head=feature --draft=true

# Chain from issue analysis
pflow github-get-issue --issue-number=123 >>
  llm --prompt="Create PR title and description to fix this issue" >>
  github-create-pr --head=fix-issue-123
```

### github-get-files

**Purpose**: Get repository files and content

```python
class GitHubGetFilesNode(Node):
    """Get repository files and content.

    Interface:
    - Reads: shared["repo"], shared["path"] (optional)
    - Writes: shared["files"] - file listing or content
    - Params: repo, token, path, ref, recursive
    """

    def prep(self, shared):
        repo = shared.get("repo") or self.params.get("repo")
        if not repo:
            raise ValueError("repo must be in shared store or params")

        return {
            "repo": repo,
            "path": shared.get("path") or self.params.get("path", ""),
            "ref": self.params.get("ref", "main"),
            "recursive": self.params.get("recursive", False),
            "token": self.params.get("token") or os.getenv("GITHUB_TOKEN")
        }

    def exec(self, prep_res):
        return github_api.get_files(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["files"] = exec_res
        return "default"
```

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

```python
class GitHubMergePRNode(Node):
    """Merge pull request.

    Interface:
    - Reads: shared["pr_number"], shared["repo"] (optional)
    - Writes: shared["merge_result"] - merge operation result
    - Params: repo, token, pr_number, merge_method, commit_title
    """

    def prep(self, shared):
        pr_number = shared.get("pr_number") or self.params.get("pr_number")
        if not pr_number:
            raise ValueError("pr_number must be in shared store or params")

        repo = shared.get("repo") or self.params.get("repo")
        if not repo:
            raise ValueError("repo must be in shared store or params")

        return {
            "repo": repo,
            "pr_number": int(pr_number),
            "merge_method": self.params.get("merge_method", "merge"),
            "commit_title": self.params.get("commit_title"),
            "token": self.params.get("token") or os.getenv("GITHUB_TOKEN")
        }

    def exec(self, prep_res):
        return github_api.merge_pr(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["merge_result"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Merge PR
pflow github-merge-pr --repo=owner/project --pr-number=456

# Squash merge
pflow github-merge-pr --repo=owner/project --pr-number=456 --merge-method=squash

# Chain from PR creation
pflow github-create-pr --title="Auto fix" >> github-merge-pr --merge-method=squash
```

### github-add-comment

**Purpose**: Add comment to issue or pull request

```python
class GitHubAddCommentNode(Node):
    """Add comment to GitHub issue or PR.

    Interface:
    - Reads: shared["comment"], shared["issue_number"], shared["repo"] (optional)
    - Writes: shared["comment_id"] - created comment ID
    - Params: repo, token, issue_number, comment
    """

    def prep(self, shared):
        comment = shared.get("comment") or self.params.get("comment")
        issue_number = shared.get("issue_number") or self.params.get("issue_number")

        if not comment:
            raise ValueError("comment must be in shared store or params")
        if not issue_number:
            raise ValueError("issue_number must be in shared store or params")

        repo = shared.get("repo") or self.params.get("repo")
        if not repo:
            raise ValueError("repo must be in shared store or params")

        return {
            "repo": repo,
            "issue_number": int(issue_number),
            "comment": comment,
            "token": self.params.get("token") or os.getenv("GITHUB_TOKEN")
        }

    def exec(self, prep_res):
        return github_api.add_comment(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["comment_id"] = exec_res["id"]
        return "default"
```

**CLI Examples**:
```bash
# Add comment to issue
pflow github-add-comment --repo=owner/project --issue-number=123 --comment="This is fixed"

# Chain from analysis
pflow github-get-issue --issue-number=123 >>
  llm --prompt="Analyze this issue and provide helpful comment" >>
  github-add-comment --issue-number=123
```

### github-search-code

**Purpose**: Search code in GitHub repositories

```python
class GitHubSearchCodeNode(Node):
    """Search code in GitHub repositories.

    Interface:
    - Reads: shared["query"], shared["repo"] (optional)
    - Writes: shared["search_results"] - code search results
    - Params: query, repo, language, filename, extension, size, path
    """

    def prep(self, shared):
        query = shared.get("query") or self.params.get("query")
        if not query:
            raise ValueError("query must be in shared store or params")

        # Build search query with filters
        search_parts = [query]

        if repo := (shared.get("repo") or self.params.get("repo")):
            search_parts.append(f"repo:{repo}")
        if language := self.params.get("language"):
            search_parts.append(f"language:{language}")
        if filename := self.params.get("filename"):
            search_parts.append(f"filename:{filename}")
        if extension := self.params.get("extension"):
            search_parts.append(f"extension:{extension}")
        if path := self.params.get("path"):
            search_parts.append(f"path:{path}")

        return {
            "query": " ".join(search_parts),
            "per_page": self.params.get("per_page", 30),
            "sort": self.params.get("sort", "indexed"),
            "token": self.params.get("token") or os.getenv("GITHUB_TOKEN")
        }

    def exec(self, prep_res):
        return github_api.search_code(**prep_res)

    def post(self, shared, prep_res, exec_res):
        shared["search_results"] = exec_res
        return "default"
```

**CLI Examples**:
```bash
# Search for function
pflow github-search-code --query="def authenticate" --language=python

# Search in specific repo
pflow github-search-code --query="TODO" --repo=owner/project --extension=py

# Chain from issue
pflow github-get-issue --issue-number=123 >>
  llm --prompt="Extract keywords to search for related code" >>
  github-search-code --repo=owner/project
```

## Node Package Composition Patterns

### Issue Analysis Workflow
```bash
# Get issue → analyze → search related code → comment
pflow github-get-issue --issue-number=123 >>
  llm --prompt="Analyze this issue and suggest search terms" >>
  github-search-code --language=python >>
  llm --prompt="Analyze code and suggest fix" >>
  github-add-comment --issue-number=123
```

### Pull Request Workflow
```bash
# Create branch → make changes → create PR → merge
pflow git-create-branch --name=fix-issue-123 >>
  file-write --path=fix.py >>
  git-commit --message="Fix issue 123" >>
  github-create-pr --title="Fix for issue 123" --head=fix-issue-123 >>
  github-merge-pr
```

### Repository Analysis
```bash
# Get files → analyze structure → create documentation issue
pflow github-get-files --recursive=true >>
  llm --prompt="Analyze repo structure and suggest documentation improvements" >>
  github-create-issue --title="Documentation improvements" --labels='["documentation"]'
```

### Code Review Support
```bash
# List PRs → get files → analyze → comment
pflow github-list-prs --state=open >>
  github-get-files --path=src >>
  llm --prompt="Review code changes and provide feedback" >>
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
