# North Star Examples for pflow Natural Language Planning

## Primary Example: Generate Changelog

```bash
pflow "generate a changelog from the last 20 closed issues"
```

### Generated Workflow

```bash
github-list-issues --state=closed --limit=20 >>
llm --prompt="Generate a CHANGELOG.md entry from these issues: $issues" >>
write-file --path=CHANGELOG.md >>
git-commit --message="Update changelog for release" >>
github-create-pr --title="Update CHANGELOG.md" --base=main
```

### Strengths
1. **Real Developer Pain Point** - Every project needs changelogs, often done manually
2. **Complex Enough** - Multiple nodes, data transformation, file I/O, git operations
3. **Simple Enough** - Linear flow, no branching, clear data pipeline
4. **Showcases Templates** - `$issues` array, nested access like `$issues[0].title`
5. **Reusable Value** - Save once, run before every release
6. **Testable** - Clear input/output, easy to verify success

## Alternative North Star Examples

### 1. Create Weekly Project Summary

```bash
pflow "create a weekly summary of all merged PRs and closed issues"
```

**Generated workflow:**
```bash
github-list-issues --state=closed --limit=50 >>
github-list-prs --state=merged --limit=50 >>  # Would need this node
llm --prompt="Create weekly summary. Issues: $issues, PRs: $prs" >>
write-file --path=reports/week-$(date +%U).md >>
git-commit --message="Add weekly summary for week $(date +%U)"
```

**Problem**: We don't have `github-list-prs` yet

### 2. Document Recent API Changes

```bash
pflow "analyze recent commits and document API changes"
```

**Generated workflow:**
```bash
git-log --limit=50 >>  # Would need this node
llm --prompt="Identify API changes from these commits: $commits" >>
write-file --path=docs/api-changes.md --append=true >>
git-commit --message="Document API changes"
```

**Problem**: We don't have `git-log` node

### 3. Generate Issue Triage Report ✅

```bash
pflow "create a triage report for all open issues"
```

**Generated workflow:**
```bash
github-list-issues --state=open --limit=100 >>
llm --prompt="Categorize these issues by priority and type: $issues" >>
write-file --path=triage-report.md >>
git-commit --message="Update triage report $(date +%Y-%m-%d)"
```

**Status**: This works with current nodes!

### 4. Create Release Notes from Closed Issues ✅

```bash
pflow "generate release notes from issues closed since last tag"
```

**Generated workflow:**
```bash
github-list-issues --state=closed --limit=30 >>
llm --prompt="Create release notes in markdown. Group by type (bug/feature/enhancement): $issues" >>
write-file --path=RELEASE_NOTES.md >>
git-commit --message="Add release notes for upcoming release" >>
github-create-pr --title="Release notes for v$(date +%Y.%m.%d)"
```

**Status**: This also works!

## Recommended Three-Tier Example Strategy

Use **THREE complementary examples** throughout Task 17:

### 1. Primary (Complex): "Generate changelog from closed issues"
- Full pipeline, PR creation, maximum value

### 2. Secondary (Medium): "Create issue triage report"
- Simpler, no PR needed, still valuable

### 3. Tertiary (Simple): "Summarize a specific issue"

```bash
pflow "summarize github issue 1234"
```

**Generated workflow:**
```bash
github-get-issue --issue=1234 >>
llm --prompt="Summarize in 3 bullets: $issue_data" >>
write-file --path=summary.md
```

- Minimal but useful, good for testing

## Criteria: What Makes a Good Planner Example

1. **Realistic** - Something developers actually do
2. **Valuable** - Saves real time/effort
3. **Reusable** - Worth saving as a workflow
4. **Data-rich** - Shows template variable power
5. **Linear** - MVP doesn't support branching
6. **Available** - Uses only implemented nodes

## Documentation Updates Needed

Replace all "fix github issue" examples with:

- **Changelog generation** (primary example)
- **Issue triage reports** (analysis example)
- **Release notes creation** (automation example)

These examples better demonstrate pflow's actual value proposition: automating repetitive developer tasks that involve data gathering, AI analysis, and structured output.
