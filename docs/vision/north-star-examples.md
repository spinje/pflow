# North Star Examples for pflow Natural Language Planning

## Primary Example: Generate Changelog 🌟

First time generating this workflow, we need to be a bit more specific about what exactly the workflow should do.

```bash
pflow "generate a changelog for version 1.3 from the last 20 closed issues from github, generating a changelog from them and then writing it to versions/1.3/CHANGELOG.md and checkout a new branch called create-changelog-version-1.3 and committing the changes."
```


**Generated Workflow**
```bash
github-list-issues --state=${issue}-state --limit=${issue}-limit >>
llm --prompt="Generate a CHANGELOG.md entry from these issues: ${issues}" >>
write-file --path=versions/${version}/CHANGELOG.md >>
git-checkout --branch="${branch}-name" >>
git-commit --message="Create changelog for version: ${version}" >>
github-create-pr --title="Create CHANGELOG.md for version: ${version}" --base=main --head="${branch}-name"
```

Which with template variables from workflow INPUTS resolved would look like this:

```bash
github-list-issues --state=closed --limit=20 >>
llm --prompt="Generate a CHANGELOG.md entry from these issues: ${issues}" >>
write-file --path=versions/1.3/CHANGELOG.md >>
git-checkout --branch="create-changelog-version-1.3" >>
git-commit --message="Create changelog for version: 1.3" >>
github-create-pr --title="Create CHANGELOG.md for version: 1.3" --base=main --head="create-changelog-version-1.3"
```

Then we can reuse it with simple prompt like:

```bash
pflow "generate a changelog for version 1.4"
```

### Strengths
1. **Real Developer Pain Point** - Every project needs changelogs, often done manually
2. **Complex Enough** - Multiple nodes, data transformation, file I/O, git operations
3. **Simple Enough** - Linear flow, no branching, clear data pipeline
4. **Showcases Templates** - `${issues}` array, nested access like `${issues}[0].title`
5. **Reusable Value** - Save once, run before every release
6. **Testable** - Clear input/output, easy to verify success

Can be improved in the future by:

To further integrate the changelog (not part of the MVP, no current nodes for this):

- `github-get-latest-tag` → Get the latest tag from GitHub to indicate the last version
- `github-list-issues --since=${latest}-tag-date` → List issues since the latest tag
- `slack-send-message` → Notify #release channel
- `github-release-create` → Attach changelog to a GitHub Release
- `create-release-post` → Pipe changelog into a blog template

## Alternative North Star Examples

### 1. Create Weekly Project Summary

First time use:

```bash
pflow "get the last 50 merged PRs and closed issues from github and combine the result into a weekly summary of them. THen write the result to reports/week_${week}-number_report.md and commit the changes."
```

**Generated workflow:**
```bash
github-list-issues --state=closed --limit=50 --since=${since}-date >> # Would need --since input
github-list-prs --state=merged --limit=50 >>  # Would need this node
llm --prompt="Create weekly summary for week ${week}-number, Issues: ${issues}, PRs: ${prs}" >>
write-file --path=reports/week_${week}-number_report.md >>
git-commit --message="Add weekly summary for week ${week}-number"
```

Reuse:

```bash
pflow "create a weekly github summary"
```

**Problem**: We don't have `github-list-prs` yet

### 2. Generate Issue Triage Report ✅

First time use:

```bash
pflow "create a triage report for all open issues by fetching the the last 50 open issues from github, categorizing them by priority and type and then write them to to triage-reports/2025-08-07-triage-report.md then commit the changes. Replace 2025-08-07 with the current date and mention the date in the commit message."
```

**Generated workflow:**
```bash
github-list-issues --state=open --limit=50 >>
llm --prompt="Categorize these issues by priority and type: ${issues}" >>
write-file --path="${date}-triage-report.md" >>
git-commit --message="Update triage report ${date}"
```

Reuse:

```bash
pflow "create a triage report for all open issues"
```

**Status**: This works with current nodes!

### 3. Create Release Notes from Closed Issues ✅

First time use:

```bash
pflow "generate release notes from the last 30 closed issues on github, group them by type (bug/feature/enhancement), write the result to RELEASE_NOTES.md, commit the changes with 'Add release notes for upcoming release', and open a PR titled 'Release notes for v<TODAY>' using today's date."
```


**Generated workflow:**
```bash
github-list-issues --state=closed --limit=30 >>
llm --prompt="Create release notes in markdown. Group by type (bug/feature/enhancement): ${issues}" >>
write-file --path=RELEASE_NOTES.md >>
git-commit --message="Add release notes for upcoming release" >>
github-create-pr --title="Release notes for version-${date}"
```

Reuse:

```bash
pflow "generate release notes from issues closed since last tag"
```

**Status**: This also works!

## Recommended Three-Tier Example Strategy

Use **THREE complementary examples** throughout Task 17:

### 1. Primary (Complex): "Generate changelog from closed issues" 🌟
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
llm --prompt="Summarize in 3 bullets: ${issue_data}" >>
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


## Insights

The less defined the prompt is, the more likely is it that the user is trying to run a workflow that currently exists than to create a new one.
We can assume that user will be fairly explicit about what they want to create a workflow for since it would not make much sense trying to give instructions to create a new workflow where there is extreme ambiguity.
