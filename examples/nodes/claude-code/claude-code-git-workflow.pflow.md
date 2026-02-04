# Claude Code Git Workflow

Analyze git changes and commit history with Claude Code to automatically
generate a comprehensive pull request description.

## Steps

### git_diff

Get the diff of current changes against main branch.

- type: git-diff
- target: main

### git_log

Get recent commit history.

- type: git-log
- limit: 10
- format: oneline

### analyze_changes

Analyze the git changes and commit history to understand what was implemented.

- type: claude-code
- max_turns: 3

```yaml context
diff: ${git_diff.diff}
commits: ${git_log.commits}
```

```yaml output_schema
summary:
  type: str
  description: One-line summary of changes
type_of_change:
  type: str
  description: "Type: feature/bugfix/refactor/docs/test"
components_affected:
  type: list
  description: List of components or modules affected
breaking_changes:
  type: bool
  description: Whether there are breaking changes
testing_suggestions:
  type: list
  description: Suggested test scenarios
```

- task: Analyze these git changes and commit history to understand what was implemented

### generate_pr

Generate a comprehensive pull request description based on the analysis.

- type: claude-code
- max_turns: 2
- system_prompt: You are a senior developer writing clear, professional PR descriptions. Use markdown formatting and be concise but thorough.
- task: Generate a comprehensive pull request description based on this analysis

```yaml context
analysis: ${analyze_changes.result}
diff_stats: ${git_diff.stats}
```

```yaml output_schema
title:
  type: str
  description: PR title following conventional commits
description:
  type: str
  description: Detailed PR description in markdown
checklist:
  type: list
  description: PR checklist items
```

### save_pr

Save the generated PR description to a template file.

- type: write-file
- path: .github/pull_request_template.md
- content: "# ${generate_pr.result.title}\n\n${generate_pr.result.description}\n\n## Checklist\n${generate_pr.result.checklist}\n\n---\n**Type of change:** ${analyze_changes.result.type_of_change}\n**Breaking changes:** ${analyze_changes.result.breaking_changes}\n**Components affected:** ${analyze_changes.result.components_affected}\n\n## Testing\n${analyze_changes.result.testing_suggestions}"

### cost_report

Display a cost report for the workflow execution.

- type: echo
- message: "\nWorkflow Cost Report:\n- Analysis: $${analyze_changes._claude_metadata.total_cost_usd} (${analyze_changes._claude_metadata.duration_ms}ms)\n- PR Generation: $${generate_pr._claude_metadata.total_cost_usd} (${generate_pr._claude_metadata.duration_ms}ms)\n- Total Cost: ~$${analyze_changes._claude_metadata.total_cost_usd + generate_pr._claude_metadata.total_cost_usd}\n- Total Turns Used: ${analyze_changes._claude_metadata.num_turns + generate_pr._claude_metadata.num_turns}"
