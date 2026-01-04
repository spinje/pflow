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
4. **Finds task references** from commits and PR bodies, loads full task review files
5. **Gathers docs context** by extracting documentation changes since the tag
6. **Analyzes each change** in parallel using truncated PR summaries (not full bodies) for efficient classification
7. **Filters internal changes** (docs, tests, `.claude/`, `.taskmaster/`) for verification
8. **Computes semantic version** based on change types
9. **Formats both outputs in parallel** - markdown and Mintlify run as 2 parallel LLM calls
10. **Refines entries** - both formatters dedupe, sort by verb, and standardize terminology
11. **Adds breaking changes** accordion with migration guidance (for major versions)
12. **Saves context file** with full task reviews, docs diff, and skipped changes for review
13. **Outputs summary** showing version, file paths, and counts for verification

## pflow Features Demonstrated

This workflow showcases several key pflow capabilities:

| Feature | Usage |
|---------|-------|
| **Batch processing** | Parallel LLM analysis of 50+ commits |
| **Inline array batch** | Two different format prompts run in parallel |
| **Object stdin** | Combining multiple data sources |
| **Nested template access** | `${get-dates.stdout.iso}` accesses JSON fields |
| **Batch result indexing** | `${format-both.results[0].response}` accesses specific batch results |
| **Git integration** | `git-get-latest-tag` node |
| **GitHub integration** | PR enrichment via `gh` CLI |
| **Docs diff context** | Uses documentation changes to improve accuracy |
| **Task review context** | Reads task-review.md files for implementation details |
| **File path classification** | Uses changed file paths to identify internal changes |

## Workflow Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────┐     ┌───────────────────┐
│ get-latest-tag  │ ──▶ │ resolve-tag  │ ──▶ │ get-docs-diff│ ──▶ │ get-recent-updates│
└─────────────────┘     └──────────────┘     └──────────────┘     └─────────┬─────────┘
                                                                            ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│ get-commits-enriched (with file paths, task numbers, pr_summary)                      │
└───────────────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│ get-task-reviews (reads task-review.md for referenced tasks)                          │
└───────────────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│ analyze-commits (BATCH LLM, 10 concurrent) → filter-and-format                        │
└───────────────────────────────────────────────────────────────────────────────────────┘
                                              │
                                              ▼
┌───────────────────┐     ┌────────────────────┐     ┌────────────────────┐     ┌───────────┐
│ prepare-context   │ ──▶ │ compute-bump-type  │ ──▶ │ compute-next-ver   │ ──▶ │ get-dates │
└───────────────────┘     └────────────────────┘     └────────────────────┘     └─────┬─────┘
                                                                                      ▼
                                                                        ┌────────────────────┐
                                                                        │ format-both (BATCH LLM, 2 items parallel)                             │
                                                                        │ [0] markdown, [1] mintlify - both refine + format                    │
                                                                        └─────────┬──────────┘
                                                                                  ▼
                                ┌─────────────────────────┐
                                │ save-release-context    │
                                │ (releases/<ver>.md)     │
                                └────────────┬────────────┘
                                             │
                                             ▼
                                ┌────────────────────┐
                                │ update-changelog   │
                                │ (CHANGELOG.md)     │
                                └─────────┬──────────┘
                                          │
                                          ▼
                                ┌────────────────────┐
                                │ update-mintlify    │
                                │ (changelog.mdx)    │
                                └─────────┬──────────┘
                                          │
                                          ▼
                                ┌────────────────────┐
                                │ create-summary     │
                                │ (CLI output)       │
                                └────────────────────┘
```

**17 nodes total** - includes file path extraction, task review loading, docs diff, release context generation, and summary output.

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

# Custom releases directory for context files
pflow generate-changelog releases_dir=release-notes
```

### Prerequisites

- Git repository with at least one tag
- GitHub CLI (`gh`) authenticated
- The repository must be a GitHub repo (for PR enrichment)

## Output Formats

### Markdown (CHANGELOG.md)

Technical changelog with PR links for developers (internal changes go to context file):

```markdown
## v1.0.0 (2026-01-04)

- Removed parameter fallback pattern to prevent namespace collisions [#28](url)
- Changed claude-code node: renamed `task` to `prompt`, `working_directory` to `cwd` [#10](url)
- Added batch processing with parallel execution [#11](url)
- Fixed shell node silent failure on unconsumed stdin [#26](url)
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

### Release Context (releases/v1.0.0-context.md)

Full context file for AI agents and pre-release verification:

```markdown
# v1.0.0 Release Context

Generated: 2026-01-04
This file contains implementation context for AI agents and release verification.

---

## Changelog

## v1.0.0 (2026-01-04)

- Added batch processing with parallel execution [#17](url)
- Fixed shell node crash on empty stdin [#26](url)

---

## Skipped Changes (Verification)

Review these to ensure nothing was incorrectly classified as internal:

- docs: sync CLAUDE.md task list
- remove statusline from project
- add task for OAuth authentication

---

## Task Implementation Reviews

### Task 96

# Task 96 Review: Support Batch Processing in Workflows

## Metadata
- **Implementation Date**: 2024-12-23 to 2024-12-27
- **Branch**: `feat/batch-processing`

## Executive Summary
Task 96 implemented both sequential and parallel batch processing...

## Implementation Overview
...

## Files Modified/Created
...

---

## Documentation Changes

## docs/reference/nodes/claude-code.mdx
Commits: 8f84825 feat(claude-code): migrate to Agent SDK
Changes:
-| `task` | str | Yes |
+| `prompt` | str | Yes |
+- **Batch processing** — process arrays of items

---

## Draft Entries with Context

```json
[
  {
    "draft": "Added batch processing with parallel execution [#11](url)",
    "index": 43,
    "context": {
      "commit_message": "Merge pull request #11 from spinje/feat/batch-processing",
      "task_number": 96,
      "files_changed": "src/pflow/core/ir_schema.py, src/pflow/runtime/batch_node.py, ... and 4 more files",
      "pr_title": "feat: add batch processing with sequential and parallel execution",
      "pr_body": "## Summary\n\nAdds batch processing capability...",
      "pr_link": "https://github.com/spinje/pflow/pull/11",
      "pr_number": 11
    }
  }
]
```
```

### CLI Summary Output

When the workflow completes, it displays a summary showing what was generated:

```
## Release Summary

Version: v1.0.0 (major)
Date: 2026-01-04

CHANGELOG.md
  17 user-facing entries

docs/changelog.mdx
  Mintlify format (same entries)

releases/v1.0.0-context.md
  32 skipped changes (for verification)
  4 task reviews
```

This makes it clear where each type of content goes - user-facing entries in the changelogs, and internal changes + task reviews in the context file for verification.

## Key Design Decisions

### 1. Using `--first-parent` to Avoid Duplicates

When a PR is merged, git history contains both the merge commit AND all individual commits. Using `--first-parent` shows only the main line, eliminating duplicates automatically.

### 2. Streamlined LLM Approach

**Classification Pass (Parallel)**: Analyzes each commit using truncated PR summaries (not full bodies) to determine if it's user-facing. Fast parallel execution with 10 concurrent calls.

**Formatting Pass (Parallel)**: Both markdown and Mintlify formatters run in parallel as a batch node with 2 items. Each formatter receives full context (task reviews, docs diff, PR bodies) and performs its own refinement (deduping, sorting, verb standardization) before formatting.

### 3. File Paths for Classification

Each commit includes the list of files changed. This helps the LLM correctly classify internal changes:

```
Files changed: .claude/settings.json, .claude/status-lines/status-line.js
```

The LLM sees `.claude/` and correctly skips it as internal dev tooling.

### 4. Task Reviews for Accurate Descriptions

The workflow extracts task numbers from PR bodies and loads the **full** task-review.md files. This includes:
- Executive summary
- Implementation details
- Key decisions and deviations from spec
- Files modified
- Integration points

This gives the aggregator LLM rich context about what was actually built, enabling accurate changelog entries that reflect the true implementation.

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

### 6. Entry Refinement

Both formatters perform the same refinement steps:
- Merge duplicate entries (combining PR links)
- Standardize verbs (Allow→Added, Enable→Added, Update→Changed)
- Sort by: Removed > Changed > Added > Fixed > Improved
- Use task reviews and docs diff for accurate descriptions

### 7. Breaking Changes Accordion

For major version bumps, the workflow automatically adds a `<Accordion title="Breaking changes">` section with migration guidance, extracted from Removed/Changed entries.

### 8. Dual Format with Different Focus

| Format | Audience | PR Links | Style |
|--------|----------|----------|-------|
| CHANGELOG.md | Developers | Yes | Technical, flat list |
| changelog.mdx | Users | No | Grouped themes, polished |

The same workflow generates both - demonstrating pflow's ability to run multiple outputs in parallel.

### 9. Inline Array Batch for Parallel Formats

The `format-both` node uses an inline array to run two different prompts in parallel. Each item contains its own prompt, and results are accessed by index:

```json
"batch": {
  "items": [
    {"format": "markdown", "prompt": "Refine and format as markdown..."},
    {"format": "mintlify", "prompt": "Refine and format as Mintlify..."}
  ],
  "parallel": true
},
"params": {
  "prompt": "${item.prompt}"
}
```

Results are accessed via `${format-both.results[0].response}` (markdown) and `${format-both.results[1].response}` (mintlify).

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

Typical run on a repository with ~50 commits:

| Metric | Value |
|--------|-------|
| Commits analyzed | 51 |
| Task reviews loaded | 4 |
| Entries included | 17 |
| Entries skipped | 34 |
| Total time | ~45 seconds |
| LLM cost | ~$0.13 |

**Architecture**: Classification uses truncated PR summaries for efficiency. Both format outputs run in parallel as a batch node, with each receiving full context for refinement.

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
