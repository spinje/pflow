# PocketFlow Patterns for Task 13: Implement github-get-issue Node

## Overview

The github-get-issue node is the first of the GitHub platform nodes, demonstrating patterns for external API integration, authentication, and error handling that all API-based nodes will follow.

## Relevant Cookbook Examples

- `cookbook/pocketflow-tool-search`: External API integration patterns
- `cookbook/pocketflow-tool-database`: Clean tool separation
- `cookbook/pocketflow-agent`: API response handling

## Patterns to Adopt

### Pattern: External API Integration
**Source**: Various tool examples
**Compatibility**: ✅ Direct
**Description**: Clean integration with external services

**Implementation for pflow**:
```python
from pocketflow import Node
import os
import requests
from typing import Dict, Any

class GitHubGetIssueNode(Node):
    def __init__(self):
        # API calls need retry
        super().__init__(max_retries=3, wait=1)

    def prep(self, shared):
        # Required inputs - check shared first
        issue_number = shared.get("issue_number") or self.params.get("issue_number")
        repo = shared.get("repo") or self.params.get("repo")

        if not issue_number:
            raise ValueError("Missing required input: issue_number")
        if not repo:
            raise ValueError("Missing required input: repo (format: owner/repo)")

        # Get auth from environment
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN environment variable not set")

        return {
            "issue_number": issue_number,
            "repo": repo,
            "token": token,
            "api_base": self.params.get("api_base", "https://api.github.com")
        }

    def exec(self, prep_res):
        # Using requests for simplicity (could also use PyGithub)
        url = f"{prep_res['api_base']}/repos/{prep_res['repo']}/issues/{prep_res['issue_number']}"

        headers = {
            "Authorization": f"token {prep_res['token']}",
            "Accept": "application/vnd.github.v3+json"
        }

        response = requests.get(url, headers=headers)

        if response.status_code == 404:
            raise ValueError(f"Issue #{prep_res['issue_number']} not found in {prep_res['repo']}")
        elif response.status_code == 401:
            raise ValueError("Invalid GitHub token")
        elif response.status_code == 403:
            if 'rate limit' in response.text.lower():
                raise RuntimeError("GitHub API rate limit exceeded")
            raise ValueError("Access forbidden - check repository permissions")

        response.raise_for_status()
        return response.json()

    def post(self, shared, prep_res, exec_res):
        # Extract key fields for easy access
        shared["issue"] = exec_res["body"]  # Full issue description
        shared["issue_title"] = exec_res["title"]
        shared["issue_number"] = exec_res["number"]
        shared["issue_state"] = exec_res["state"]
        shared["issue_data"] = exec_res  # Full API response

        # Extract additional useful fields
        if exec_res.get("assignee"):
            shared["issue_assignee"] = exec_res["assignee"]["login"]
        if exec_res.get("labels"):
            shared["issue_labels"] = [label["name"] for label in exec_res["labels"]]

        return "default"
```

### Pattern: Environment-Based Authentication
**Source**: Best practices for API keys
**Compatibility**: ✅ Direct
**Description**: Use environment variables for sensitive data

**Key principles**:
```python
# NEVER hardcode tokens
# NEVER accept tokens as CLI parameters (they get logged)
# ALWAYS use environment variables

token = os.environ.get("GITHUB_TOKEN")
if not token:
    raise ValueError(
        "GITHUB_TOKEN environment variable not set. "
        "Please run: export GITHUB_TOKEN='your-token-here'"
    )
```

### Pattern: Natural Output Interface
**Source**: Shared store principles
**Compatibility**: ✅ Direct
**Description**: Provide both convenient fields and full data

**Output strategy**:
```python
# Commonly used fields get their own keys
shared["issue"] = exec_res["body"]  # Most common - issue description
shared["issue_title"] = exec_res["title"]
shared["issue_number"] = exec_res["number"]

# Full data available for advanced usage
shared["issue_data"] = exec_res  # Complete API response

# This enables:
# 1. Simple workflows: Use $issue directly
# 2. Advanced workflows: Access $issue_data.milestone.title
```

### Pattern: Graceful Error Handling
**Source**: API integration best practices
**Compatibility**: ✅ Direct
**Description**: Clear, actionable error messages

**Error handling hierarchy**:
```python
# 1. Authentication errors - fail fast
if response.status_code == 401:
    raise ValueError("Invalid GitHub token")

# 2. Not found - clear message
if response.status_code == 404:
    raise ValueError(f"Issue #{number} not found in {repo}")

# 3. Rate limits - let retry mechanism handle
if response.status_code == 403 and 'rate limit' in response.text:
    raise RuntimeError("GitHub API rate limit exceeded")  # Will retry

# 4. Other errors - include context
response.raise_for_status()  # Includes status code and message
```

### Pattern: PyGithub Alternative
**Source**: Library integration patterns
**Compatibility**: ✅ Direct
**Description**: Using PyGithub for richer functionality

**Alternative implementation**:
```python
def exec(self, prep_res):
    from github import Github

    g = Github(prep_res["token"])

    try:
        repo = g.get_repo(prep_res["repo"])
        issue = repo.get_issue(int(prep_res["issue_number"]))

        # Convert to dict for consistency
        return {
            "number": issue.number,
            "title": issue.title,
            "body": issue.body,
            "state": issue.state,
            "labels": [{"name": l.name} for l in issue.labels],
            "assignee": {"login": issue.assignee.login} if issue.assignee else None,
            # ... other fields
        }
    except Exception as e:
        if "404" in str(e):
            raise ValueError(f"Issue not found")
        raise
```

## Patterns to Avoid

### Pattern: Complex State Management
**Issue**: Caching API responses, tracking rate limits
**Alternative**: Let each execution be independent

### Pattern: Batch Operations
**Issue**: Getting multiple issues at once
**Alternative**: Simple nodes - one issue per execution

### Pattern: Token as Parameter
**Issue**: Security risk - tokens in logs/history
**Alternative**: Always use environment variables

## Implementation Guidelines

1. **Single purpose**: Get one issue, nothing more
2. **Rich output**: Provide commonly needed fields
3. **Clear errors**: Help users debug API issues
4. **Standard auth**: Environment variables only
5. **Fail fast**: Validate inputs early

## Usage Examples

### Example 1: Basic Usage
```bash
# CLI usage
export GITHUB_TOKEN="ghp_..."
pflow github-get-issue --issue=1234 --repo=owner/repo

# In workflow
github-get-issue >> llm --prompt="Analyze this issue: $issue"
```

### Example 2: With Dynamic Input
```python
# Previous node sets issue number
shared = {
    "issue_number": "1234",
    "repo": "facebook/react"
}

node = GitHubGetIssueNode()
node.run(shared)

# Now shared contains:
# - issue: "Bug: Component not rendering..."
# - issue_title: "Component rendering issue"
# - issue_labels: ["bug", "high-priority"]
```

### Example 3: Error Handling
```python
# Missing token
os.environ.pop("GITHUB_TOKEN", None)
with pytest.raises(ValueError, match="GITHUB_TOKEN"):
    node.run(shared)

# Invalid issue
shared = {"issue_number": "99999", "repo": "owner/repo"}
with pytest.raises(ValueError, match="not found"):
    node.run(shared)
```

## Testing Approach

```python
import pytest
from unittest.mock import patch, Mock

def test_github_get_issue_success():
    node = GitHubGetIssueNode()
    shared = {
        "issue_number": "123",
        "repo": "owner/repo"
    }

    # Mock the API response
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "number": 123,
        "title": "Test Issue",
        "body": "Issue description",
        "state": "open",
        "labels": [{"name": "bug"}]
    }

    with patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
        with patch('requests.get', return_value=mock_response):
            node.run(shared)

    assert shared["issue"] == "Issue description"
    assert shared["issue_title"] == "Test Issue"
    assert shared["issue_labels"] == ["bug"]

def test_rate_limit_retry():
    node = GitHubGetIssueNode()
    shared = {"issue_number": "123", "repo": "owner/repo"}

    mock_response = Mock()
    mock_response.status_code = 403
    mock_response.text = "rate limit exceeded"

    with patch.dict(os.environ, {"GITHUB_TOKEN": "fake-token"}):
        with patch('requests.get', return_value=mock_response):
            # Should raise RuntimeError (retryable)
            with pytest.raises(RuntimeError, match="rate limit"):
                node.run(shared)
```

This node establishes patterns for all external API integrations: clean interfaces, proper authentication, and helpful error handling.
