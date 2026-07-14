# Agent (Claude) Git Workflow

Analyze git changes and commit history with Claude Code to automatically
generate a comprehensive pull request description.

## Steps

### git_diff

Get the diff of current changes against main branch.

- type: shell

```shell command
git diff main
```

### git_log

Get recent commit history.

- type: shell

```shell command
git log --oneline -10
```

### analyze_changes

Analyze the git changes and commit history to understand what was implemented.

- type: agent
- backend: claude
- max_turns: 3

```yaml output_schema
type: object
properties:
  summary:
    type: string
    description: One-line summary of changes
  type_of_change:
    type: string
    enum: [feature, bugfix, refactor, docs, test, chore]
    description: Type of change
  components_affected:
    type: array
    items:
      type: string
    description: List of components or modules affected
  breaking_changes:
    type: boolean
    description: Whether there are breaking changes
  testing_suggestions:
    type: array
    items:
      type: string
    description: Suggested test scenarios
required: [summary, type_of_change, components_affected, breaking_changes, testing_suggestions]
```

```prompt
Analyze these git changes and commit history to understand what was implemented.

Diff:
${git_diff.stdout}

Recent commits:
${git_log.stdout}
```

### generate_pr

Generate a comprehensive pull request description based on the analysis.

- type: agent
- backend: claude
- max_turns: 2
- system_prompt: You are a senior developer writing clear, professional PR descriptions. Use markdown formatting and be concise but thorough.

```yaml output_schema
type: object
properties:
  title:
    type: string
    description: PR title following conventional commits
  description:
    type: string
    description: Detailed PR description in markdown
  checklist:
    type: array
    items:
      type: string
    description: PR checklist items
required: [title, description, checklist]
```

```prompt
Generate a comprehensive pull request description based on this analysis.

Analysis:
${analyze_changes.result}

Diff stats:
${git_diff.stdout}
```

### save_pr

Save the generated PR description to a template file.

- type: write-file
- file_path: .github/pull_request_template.md
- content: "# ${generate_pr.result.title}\n\n${generate_pr.result.description}\n\n## Checklist\n${generate_pr.result.checklist}\n\n---\n**Type of change:** ${analyze_changes.result.type_of_change}\n**Breaking changes:** ${analyze_changes.result.breaking_changes}\n**Components affected:** ${analyze_changes.result.components_affected}\n\n## Testing\n${analyze_changes.result.testing_suggestions}"

### cost_report

Display a cost report for the workflow execution.

- type: shell

```text command
echo "Workflow Cost Report:\n- Analysis: $${analyze_changes.llm_usage.cost_usd} (${analyze_changes.llm_usage.duration_ms}ms)\n- PR Generation: $${generate_pr.llm_usage.cost_usd} (${generate_pr.llm_usage.duration_ms}ms)"
```
