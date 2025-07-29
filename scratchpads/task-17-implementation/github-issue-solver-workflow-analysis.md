# GitHub Issue Solver Workflow Analysis

## Overview
This workflow represents a sophisticated automated development pipeline that showcases pflow's capabilities for complex, multi-step automation with nested workflows and conditional logic.

## Workflow Breakdown

### 1. Get Issue from GitHub
```json
{
  "id": "get_issue",
  "type": "github-get-issue",
  "params": {
    "issue": "$issue_number",
    "repo": "$repo_name"
  }
}
```
Outputs: `issue_data` with title, body, labels, etc.

### 2. Create Work Tree and Branch
```json
{
  "id": "setup_workspace",
  "type": "git-worktree",
  "params": {
    "branch_name": "fix-issue-$issue_data.number",
    "base_branch": "$base_branch"
  }
}
```
Outputs: `worktree_path`, `branch_name`

### 3. Do the Work Using Claude Code
This is the complex part - needs specialized prompting:
```json
{
  "id": "implement_fix",
  "type": "claude-code",
  "params": {
    "prompt": "Fix the following issue:\n\nIssue #$issue_data.number: $issue_data.title\n\n$issue_data.body\n\nInstructions:\n1. Analyze the issue thoroughly\n2. Implement a complete fix\n3. Add appropriate tests\n4. Output structured data with:\n   - files_changed: list of modified files\n   - summary: brief description of changes\n   - test_results: test execution results",
    "working_directory": "$worktree_path",
    "use_subagents": true,
    "output_format": "structured"
  }
}
```
Outputs: `implementation_result` with structured data

### 4. Create Git PR
```json
{
  "id": "create_pr",
  "type": "github-create-pr",
  "params": {
    "title": "Fix: $issue_data.title",
    "body": "Fixes #$issue_data.number\n\n## Summary\n$implementation_result.summary\n\n## Changes\n$implementation_result.files_changed",
    "branch": "$branch_name",
    "base": "$base_branch"
  }
}
```
Outputs: `pr_url`, `pr_number`

### 5. Review PR Internally
This uses workflow composition!
```json
{
  "id": "review_pr",
  "type": "workflow",
  "params": {
    "workflow_ref": "~/.pflow/workflows/review-pr.json",
    "param_mapping": {
      "pr_number": "$pr_number",
      "repo": "$repo_name"
    },
    "output_mapping": {
      "review_comments": "pr_review",
      "approval_status": "review_status"
    }
  }
}
```
Outputs: `pr_review`, `review_status`

### 6. Notify User
```json
{
  "id": "notify",
  "type": "output-result",
  "params": {
    "message": "PR created: $pr_url\n\nReview Status: $review_status\n\nComments:\n$pr_review"
  }
}
```

## Complete Workflow IR

```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "issue_number": {
      "description": "GitHub issue number to fix",
      "required": true,
      "type": "number"
    },
    "repo_name": {
      "description": "Repository name (owner/repo)",
      "required": true,
      "type": "string"
    },
    "base_branch": {
      "description": "Base branch for PR",
      "required": false,
      "type": "string",
      "default": "main"
    }
  },
  "outputs": {
    "pr_url": {
      "description": "URL of created pull request",
      "type": "string"
    },
    "pr_number": {
      "description": "PR number",
      "type": "number"
    },
    "review_status": {
      "description": "Review approval status",
      "type": "string"
    }
  },
  "nodes": [
    // ... nodes from above ...
  ],
  "edges": [
    {"from": "get_issue", "to": "setup_workspace"},
    {"from": "setup_workspace", "to": "implement_fix"},
    {"from": "implement_fix", "to": "create_pr"},
    {"from": "create_pr", "to": "review_pr"},
    {"from": "review_pr", "to": "notify"}
  ]
}
```

## Advanced Features Demonstrated

### 1. Workflow Composition
- Uses `type: "workflow"` to invoke the review-pr workflow
- Shows parameter and output mapping between workflows

### 2. Complex Prompting
- Structured output requirements for Claude Code
- Sub-agent usage for complex implementation tasks
- Contextual information threading through the workflow

### 3. External System Integration
- GitHub API integration (issues, PRs)
- Git operations (worktree, branches)
- AI-powered code generation

### 4. Data Flow
- Issue data flows through the entire pipeline
- Each step enriches the context for subsequent steps
- Final output aggregates results from all steps

## Optional Enhancement: Auto-Fix Review Comments

Could extend with conditional logic (v2.0 feature):
```json
{
  "id": "check_review",
  "type": "conditional",
  "params": {
    "condition": "$review_status != 'approved'"
  },
  "on_true": "fix_comments",
  "on_false": "complete"
}
```

Then invoke another workflow to address review comments:
```json
{
  "id": "fix_comments",
  "type": "workflow",
  "params": {
    "workflow_ref": "~/.pflow/workflows/fix-review-comments.json",
    "param_mapping": {
      "pr_number": "$pr_number",
      "comments": "$pr_review"
    }
  }
}
```

## Why This is Perfect for pflow

1. **Reusability**: Once created, can fix any GitHub issue with:
   ```bash
   pflow fix-github-issue --issue_number=123 --repo_name=owner/repo
   ```

2. **Modularity**: The review-pr workflow is reusable in other contexts

3. **Transparency**: Each step is clear and auditable

4. **Extensibility**: Easy to add steps or modify behavior

5. **AI Integration**: Shows how pflow can orchestrate AI agents effectively

## Implementation Notes

### Required Nodes
- `github-get-issue` - Already exists in many workflows
- `git-worktree` - Would need to be created
- `claude-code` - Complex node with sub-agent support
- `github-create-pr` - Common GitHub integration
- `output-result` - Simple output node

### Key Challenges
1. **Claude Code Integration**: Need robust prompting and output parsing
2. **Error Handling**: What if implementation fails?
3. **State Management**: Worktree cleanup on failure
4. **Review Quality**: Ensuring meaningful automated reviews

### Benefits
1. **Automation**: Completely automated issue resolution
2. **Quality**: Built-in review process
3. **Traceability**: Full audit trail of changes
4. **Scalability**: Can handle multiple issues in parallel

This workflow perfectly demonstrates pflow's vision of composable, reusable automation that combines AI capabilities with traditional tooling!
