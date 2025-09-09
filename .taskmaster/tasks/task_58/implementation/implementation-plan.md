# Task 58 Implementation Plan

## Current State Analysis

### Mock Nodes to Remove (15 nodes)
1. `git-tag` → Use `shell` with `git tag` command
2. `github-get-latest-tag` → Already exists as `git-get-latest-tag`
3. `github-create-release` → Use `shell` with `gh release create`
4. `slack-notify` → Replace with MCP mock
5. `analyze-code`, `analyze-structure` → Remove completely
6. `validate-links`, `filter-data` → Remove completely
7. `build-project` → Use `shell` with appropriate build command
8. `fetch-data`, `fetch-profile` → Use `http` node instead
9. `run-migrations`, `backup-database`, `verify-data` → Remove completely
10. `claude-code` → Future node, remove

### Available Real Nodes (21 total)
- **File (5)**: read-file, write-file, copy-file, move-file, delete-file
- **Git (6)**: git-commit, git-checkout, git-push, git-log, git-get-latest-tag, git-status
- **GitHub (4)**: github-list-issues, github-list-prs, github-create-pr, github-get-issue
- **Core (5)**: llm, shell, http, mcp, echo
- **Test (1)**: echo

## 15 Test Cases Design

### Category 1: Real Developer Workflows (5 tests)

1. **changelog_from_issues** (North Star ⭐)
   - Input: "Generate a changelog from the last 20 closed issues in github repo anthropic/pflow, categorize by type, write to CHANGELOG.md, and commit the changes"
   - Nodes: github-list-issues → llm → write-file → git-commit
   - Category: `north_star`

2. **pr_summary_generator**
   - Input: "List open PRs, generate executive summary, save to pr-summary.md"
   - Nodes: github-list-prs → llm → write-file
   - Category: `developer_workflow`

3. **test_generator**
   - Input: "Read main.py, generate unit tests, write to test_main.py"
   - Nodes: read-file → llm → write-file
   - Category: `developer_workflow`

4. **documentation_updater**
   - Input: "Read README.md, update with latest API changes from api.json, commit changes"
   - Nodes: read-file → read-file → llm → write-file → git-commit
   - Category: `developer_workflow`

5. **dependency_checker**
   - Input: "Check outdated npm packages, create report, write to deps-report.md"
   - Nodes: shell → llm → write-file
   - Shell command: `npm outdated --json`
   - Category: `developer_workflow`

### Category 2: MCP Integration Tests (5 tests)

6. **slack_qa_automation** (From real trace)
   - Input: "Get last 10 messages from slack channel C09C16NAU5B, answer questions with AI, send back to channel"
   - Nodes: mcp-slack-slack_get_channel_history → llm → mcp-slack-slack_post_message
   - Category: `mcp_integration`

7. **slack_daily_summary**
   - Input: "Fetch 50 messages from channel general, summarize, post summary"
   - Nodes: mcp-slack-slack_get_channel_history → llm → mcp-slack-slack_post_message
   - Category: `mcp_integration`

8. **mcp_http_integration**
   - Input: "Use MCP to fetch weather, process with AI, save report"
   - Nodes: mcp → llm → write-file
   - Category: `mcp_integration`

9. **github_slack_notifier**
   - Input: "Get closed issues from last week, create summary, notify slack channel updates"
   - Nodes: github-list-issues → llm → mcp-slack-slack_post_message
   - Category: `mcp_integration`

10. **file_slack_reporter**
    - Input: "Read error.log, analyze patterns, report to slack channel alerts"
    - Nodes: read-file → llm → mcp-slack-slack_post_message
    - Category: `mcp_integration`

### Category 3: Complex Multi-Step Workflows (3 tests)

11. **full_release_pipeline**
    - Input: "Get commits since last tag, generate release notes, create tag v1.3.0, push tag, create GitHub release, update CHANGELOG.md, commit changes, create PR"
    - Nodes: git-get-latest-tag → git-log → llm → shell → shell → shell → write-file → git-commit → github-create-pr
    - Shell commands: `git tag`, `git push`, `gh release create`
    - Category: `complex_pipeline`

12. **issue_triage_automation**
    - Input: "Fetch 50 open issues, categorize by priority and age, generate triage report with recommendations, save to triage-YYYY-MM-DD.md, commit, create PR with review request"
    - Nodes: github-list-issues → llm → shell → write-file → git-commit → github-create-pr → shell
    - Shell commands: `date +%Y-%m-%d`, `gh pr edit --add-reviewer`
    - Category: `complex_pipeline`

13. **codebase_quality_report**
    - Input: "Run linting, check test coverage, analyze complexity, fetch recent issues, generate quality report, commit to quality-reports branch, push, create PR"
    - Nodes: shell → shell → shell → github-list-issues → llm → write-file → git-checkout → git-commit → git-push → github-create-pr
    - Shell commands: `npm run lint`, `npm test -- --coverage`, `npx complexity-report`
    - Category: `complex_pipeline`

### Category 4: Edge Cases (2 tests)

14. **template_stress_test**
    - Input: "Read ${config_file}, process data for ${environment}, deploy to ${target_server}, notify ${slack_channel}"
    - Nodes: read-file → llm → shell → mcp-slack-slack_post_message
    - Tests heavy template variable usage
    - Category: `edge_case`

15. **validation_recovery_test**
    - Input: "Fetch issues, analyze, generate report" (with intentional validation errors)
    - Nodes: github-list-issues → llm → write-file
    - validation_errors: ["Missing required input: repo_owner"]
    - Tests error recovery
    - Category: `edge_case`

## Implementation Strategy

### Phase 1: Registry Update
1. Remove all 15 mock nodes from `create_test_registry()`
2. Add only 2 Slack MCP mocks:
   - `mcp-slack-slack_get_channel_history`
   - `mcp-slack-slack_post_message`
3. Verify registry loads real nodes correctly

### Phase 2: Test Implementation Order
1. Start with north star (changelog_from_issues)
2. Implement developer workflows (tests 2-5)
3. Add MCP integration tests (tests 6-10)
4. Create complex pipelines (tests 11-13)
5. Add edge cases (tests 14-15)

### Phase 3: Natural Language Patterns
- Brief prompts for common tasks: "generate changelog"
- Detailed prompts for first use: "Generate a changelog from the last 20 closed issues..."
- Include reuse scenarios showing progression

## Shell Workaround Patterns

```python
# Git tag creation
"shell" with params={"command": "git tag v${version} && git push origin v${version}"}

# GitHub release
"shell" with params={"command": "gh release create v${version} --title '${title}' --notes '${notes}'"}

# PR reviewer addition
"shell" with params={"command": "gh pr edit ${pr_number} --add-reviewer ${reviewer}"}

# Date generation
"shell" with params={"command": "date +%Y-%m-%d", "output_key": "current_date"}
```

## Testing Strategy

1. Run individual test: `RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_workflow_generator_prompt.py::test_workflow_generator_prompt[test_name] -v`
2. Run all tests: `RUN_LLM_TESTS=1 pytest tests/test_planning/llm/prompts/test_workflow_generator_prompt.py -v`
3. Check accuracy: `uv run python tools/test_prompt_accuracy.py workflow_generator`
4. Verify with: `make test` and `make check`

## Success Metrics
- ✅ 13/15 tests use only real nodes
- ✅ 2/15 tests use Slack MCP mocks
- ✅ 0 other mock nodes in registry
- ✅ North star test is first
- ✅ Natural language prompts
- ✅ Shell workarounds work correctly
- ✅ All tests pass validation