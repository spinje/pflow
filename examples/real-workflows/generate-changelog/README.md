# Generate Changelog Workflow

A pflow workflow that automatically generates professional changelogs from git history. Outputs markdown (CHANGELOG.md), Mintlify format (changelog.mdx), and a release context file for AI agents and human verification.

## Why This Exists

Manual changelog writing is tedious and error-prone:
- Developers forget to document changes
- Internal refactors get mixed with user-facing features
- Duplicates slip through when PRs touch the same feature
- Formatting is inconsistent
- PR links are often missing
- Breaking changes lack migration guidance

This workflow solves all of these problems automatically.

**Dogfooding**: We use this workflow to maintain pflow's own changelogs. Even as a small project, we get professional dual-format changelogs with zero extra effort - demonstrating exactly what pflow enables.

## What It Does

Given a git tag as a starting point, the workflow:

1. **Extracts commits** using `--first-parent` to avoid duplicates from PR branches
2. **Enriches with PR data** by fetching merged PRs from GitHub API
3. **Extracts file paths** to help classify internal vs user-facing changes
4. **Finds task references** from commits and PR bodies, loads task review summaries
5. **Gathers docs context** by extracting documentation changes since the tag
6. **Analyzes each change** in parallel to determine if it's user-facing
7. **Filters internal changes** (docs, tests, `.claude/`, `.taskmaster/`) for verification
8. **Refines entries** with docs + task review context for accurate descriptions
9. **Computes semantic version** based on change types
10. **Generates triple output**:
    - Markdown (technical, with PR links)
    - Mintlify (user-facing, grouped themes, no links)
    - Release context (AI-readable + verification)
11. **Adds breaking changes** accordion with migration guidance (for major versions)
12. **Saves context file** with task reviews, docs diff, and skipped changes for review

## pflow Features Demonstrated

This workflow showcases several key pflow capabilities:

| Feature | Usage |
|---------|-------|
| **Batch processing** | Parallel LLM analysis of 40+ commits |
| **Inline array batch** | Two different prompts run in parallel |
| **Object stdin** | Combining multiple data sources |
| **Nested template access** | `${get-dates.stdout.iso}` accesses JSON fields |
| **Git integration** | `git-get-latest-tag` node |
| **GitHub integration** | PR enrichment via `gh` CLI |
| **Docs diff context** | Uses documentation changes to improve accuracy |
| **Task review context** | Reads task-review.md files for implementation details |
| **Style reference** | Reads existing changelog for consistent formatting |
| **File path classification** | Uses changed file paths to identify internal changes |

## Workflow Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────┐     ┌───────────────────┐
│ get-latest-tag  │ ──▶ │ resolve-tag  │ ──▶ │ get-docs-diff│ ──▶ │ get-recent-updates│
└─────────────────┘     └──────────────┘     └──────────────┘     └─────────┬─────────┘
                                                                            ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│ get-commits-enriched (with file paths + task numbers)                                 │
└───────────────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│ get-task-reviews (reads task-review.md for referenced tasks)                          │
└───────────────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│ analyze (BATCH LLM, 10 concurrent) → filter-and-format                                │
└───────────────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌───────────────────┐     ┌─────────────────────────────────────────────────────────────┐
│ prepare-context   │ ──▶ │ refine-entries (uses docs diff + task reviews)              │
└───────────────────┘     └─────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌───────────────────┐     ┌────────────────────┐     ┌───────────┐
│ compute-bump-type │ ──▶ │ compute-next-ver   │ ──▶ │ get-dates │
└───────────────────┘     └────────────────────┘     └─────┬─────┘
                                                           ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│ format-both (BATCH LLM - parallel, 2 items)                                           │
│ - Markdown: technical, with PR links                                                  │
│ - Mintlify: user-facing, grouped themes, no PR links                                  │
└───────────────────────────────────────────────────────────────────────────────────────┘
                                    │
                        ┌───────────┴───────────┐
                        ▼                       ▼
            ┌────────────────────┐   ┌────────────────────┐
            │ update-changelog   │   │ update-mintlify    │
            │ (CHANGELOG.md)     │   │ (changelog.mdx)    │
            └────────────────────┘   └──────────┬─────────┘
                                                │
                                                ▼
                                   ┌─────────────────────────┐
                                   │ save-release-context    │
                                   │ (releases/context.md)   │
                                   └─────────────────────────┘
```

**18 nodes total** - includes file path extraction, task review loading, docs diff, style reference, and release context generation.

## Usage

### Basic Usage

```bash
# Generate changelog since latest tag
pflow examples/real-workflows/generate-changelog/workflow.json
```

### With Options

```bash
# Specify starting tag
pflow generate-changelog since_tag=v0.5.0

# Skip Mintlify output (markdown only)
pflow generate-changelog mintlify_file=""

# Custom output files
pflow generate-changelog changelog_file=RELEASE_NOTES.md mintlify_file=docs/updates.mdx
```

### Prerequisites

- Git repository with at least one tag
- GitHub CLI (`gh`) authenticated
- The repository must be a GitHub repo (for PR enrichment)

## Output Formats

### Markdown (CHANGELOG.md)

Technical changelog with PR links for developers:

```markdown
## v1.0.0 (2026-01-04)

- Removed parameter fallback pattern to prevent namespace collisions [#28](url)
- Changed claude-code node: renamed `task` to `prompt`, `working_directory` to `cwd` [#10](url)
- Added batch processing with parallel execution [#11](url)
- Fixed shell node silent failure on unconsumed stdin [#26](url)

<details>
<summary>27 internal changes not included</summary>

- docs: add workflow limitations
- remove statusline from project
- add task for OAuth authentication
</details>
```

### Mintlify (changelog.mdx)

User-facing changelog with grouped themes, no PR links:

```mdx
<Update label="January 2026" description="v1.0.0" tags={["New releases", "Bug fixes", "Breaking changes"]}>
  ## Batch Execution

  Introduced comprehensive batch processing with parallel execution and real-time progress.

  **Highlights**
  - Advanced batch processing with sequential and parallel execution modes
  - Real-time progress display for batch node execution

  ## Node Integrations

  Major updates to core nodes including Claude SDK migration and shell improvements.

  **Highlights**
  - Upgraded claude-code node with sandbox support and session resume
  - Fixed shell node silent exits and structured data validation

  <Accordion title="Breaking changes">
    - **Parameter Fallback**: Removed implicit fallback. Use explicit template wiring.
    - **Claude Node**: Renamed `task` to `prompt`, `working_directory` to `cwd`.
  </Accordion>
</Update>
```

## Key Design Decisions

### 1. Using `--first-parent` to Avoid Duplicates

When a PR is merged, git history contains both the merge commit AND all individual commits. Using `--first-parent` shows only the main line, eliminating duplicates automatically.

### 2. Two-Pass LLM Approach

**First Pass (Parallel)**: Analyzes each commit in isolation. Fast but no cross-entry awareness.

**Second Pass (Aggregator)**: Sees ALL entries with context. Enables merging duplicates, consistent formatting, and proper sorting.

### 3. File Paths for Classification

Each commit includes the list of files changed. This helps the LLM correctly classify internal changes:

```
Files changed: .claude/settings.json, .claude/status-lines/status-line.js
```

The LLM sees `.claude/` and correctly skips it as internal dev tooling.

### 4. Task Reviews for Accurate Descriptions

The workflow extracts task numbers from PR bodies and loads the corresponding task-review.md executive summaries:

```json
{
  "96": "Task 96 implemented both sequential and parallel batch processing...",
  "102": "Removed the shared store fallback pattern from all 20 platform nodes..."
}
```

This gives the aggregator LLM rich context about what was actually built.

### 5. Docs Diff for Parameter Accuracy

The workflow extracts documentation changes since the tag:

```
## docs/reference/nodes/claude-code.mdx
Commits: 8f84825 feat(claude-code): migrate to Agent SDK
Changes:
-| `task` | str | Yes |
+| `prompt` | str | Yes |
+| `sandbox` | dict |
```

This enables entries like "renamed `task` to `prompt`" instead of vague "updated parameters".

### 6. Style Reference for Consistency

The workflow reads the last 2 `<Update>` blocks from the existing changelog and provides them as a style reference. This ensures new entries match the established format.

### 7. Breaking Changes Accordion

For major version bumps, the workflow automatically adds a `<Accordion title="Breaking changes">` section with migration guidance, extracted from Removed/Changed entries.

### 8. Dual Format with Different Focus

| Format | Audience | PR Links | Style |
|--------|----------|----------|-------|
| CHANGELOG.md | Developers | Yes | Technical, flat list |
| changelog.mdx | Users | No | Grouped themes, polished |

The same workflow generates both - demonstrating pflow's ability to run multiple outputs in parallel.

### 9. Inline Array Batch for Parallel Formats

The `format-both` node uses an inline array to run two different prompts in parallel:

```json
"batch": {
  "items": [
    {"format": "markdown", "prompt": "Format as markdown..."},
    {"format": "mintlify", "prompt": "Format as Mintlify..."}
  ],
  "parallel": true
}
```

### 10. Object Stdin for Combining Data

The `prepare-context` node combines data from two earlier nodes using object stdin:

```json
"stdin": {
  "filter": "${filter-and-format.stdout}",
  "commits": "${get-commits-enriched.stdout}"
}
```

Both JSON strings are auto-parsed, enabling direct access in jq.

### 11. Nested Template Access

Templates can access nested JSON fields directly:

```
${get-dates.stdout.iso}        → "2026-01-04"
${get-dates.stdout.month_year} → "January 2026"
```

## Performance

Typical run on a repository with ~43 commits:

| Metric | Value |
|--------|-------|
| Commits analyzed | 43 |
| Task reviews loaded | 4 |
| Entries included | 16 |
| Entries skipped | 27 |
| Total time | ~50 seconds |
| LLM cost | ~$0.11 |

## Semantic Versioning

Version bump is determined by change types:

| Change Types | Version Bump |
|-------------|--------------|
| Any `Removed` or `Changed` | Major (breaking) |
| Any `Added` (no breaking) | Minor (feature) |
| Only `Fixed`/`Improved` | Patch (bugfix) |

## Limitations

- Requires GitHub (uses `gh` CLI for PR data)
- Requires at least one git tag as starting point
- LLM may occasionally misclassify (review context file before committing)
- Cost scales with commits (~$0.003 per commit)
- Task reviews require `.taskmaster/tasks/task_N/task-review.md` structure
- Docs diff context requires `docs/` folder in repository

## Future Enhancements

- **Group context by PR**: Currently task reviews, docs diff, and entries are separate chunks. Grouping all related context by PR/commit would make the release context file more useful for AI agents (everything about one change together)
- **Version in context filename**: Use `releases/v1.0.0-context.md` instead of `releases/context.md` to preserve history
