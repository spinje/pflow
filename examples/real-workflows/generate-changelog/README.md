# Generate Changelog Workflow

A pflow workflow that automatically generates professional changelogs from git history. Outputs both markdown (CHANGELOG.md) and Mintlify format (changelog.mdx) using parallel LLM processing.

## Why This Exists

Manual changelog writing is tedious and error-prone:
- Developers forget to document changes
- Internal refactors get mixed with user-facing features
- Duplicates slip through when PRs touch the same feature
- Formatting is inconsistent
- PR links are often missing

This workflow solves all of these problems automatically.

## What It Does

Given a git tag as a starting point, the workflow:

1. **Extracts commits** using `--first-parent` to avoid duplicates from PR branches
2. **Enriches with PR data** by fetching merged PRs from GitHub API
3. **Analyzes each change** in parallel to determine if it's user-facing
4. **Filters internal changes** (docs, tests, refactors) into a collapsible section
5. **Refines entries** with a second LLM pass that merges duplicates and standardizes formatting
6. **Computes semantic version** based on change types
7. **Generates dual output** - markdown and Mintlify formats in parallel
8. **Updates files** by prepending the new sections

## pflow Features Demonstrated

This workflow showcases several key pflow capabilities:

| Feature | Usage |
|---------|-------|
| **Batch processing** | Parallel LLM analysis of 30+ commits |
| **Inline array batch** | Two different prompts run in parallel |
| **Object stdin** | Combining multiple data sources |
| **Nested template access** | `${get-dates.stdout.iso}` accesses JSON fields |
| **Git integration** | `git-get-latest-tag` node |
| **GitHub integration** | PR enrichment via `gh` CLI |

## Workflow Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────────────┐
│ get-latest-tag  │ ──▶ │ resolve-tag  │ ──▶ │ get-commits-enriched │
└─────────────────┘     └──────────────┘     └──────────┬───────────┘
                                                        ▼
┌───────────────────────────────────────────────────────────────────┐
│ analyze (BATCH LLM - parallel, 10 concurrent)                     │
│ For each commit: classify as user-facing or SKIP                  │
└───────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌───────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ filter-and-format │ ──▶ │ prepare-context │ ──▶ │ refine-entries  │
│ (separate SKIPs)  │     │ (join context)  │     │ (polish + sort) │
└───────────────────┘     └─────────────────┘     └────────┬────────┘
                                                           ▼
┌───────────────────┐     ┌────────────────────┐     ┌───────────┐
│ compute-bump-type │ ──▶ │ compute-next-ver   │ ──▶ │ get-dates │
└───────────────────┘     └────────────────────┘     └─────┬─────┘
                                                           ▼
┌───────────────────────────────────────────────────────────────────┐
│ format-both (BATCH LLM - parallel, 2 items)                       │
│ Items: [markdown prompt, mintlify prompt] ← inline array!         │
│ Generates both formats simultaneously                             │
└───────────────────────────────────────────────────────────────────┘
                                    │
                        ┌───────────┴───────────┐
                        ▼                       ▼
            ┌────────────────────┐   ┌────────────────────┐
            │ update-changelog   │   │ update-mintlify    │
            │ (CHANGELOG.md)     │   │ (changelog.mdx)    │
            └────────────────────┘   └────────────────────┘
```

**13 nodes total** - optimized from 17 by using object stdin and inline arrays.

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

```markdown
## v1.0.0 (2026-01-03)

- Removed shared store fallback to prevent namespace collisions [#28](url)
- Changed claude-code node to use Agent SDK [#10](url)
- Added batch processing with parallel execution [#11](url)
- Fixed shell node silent failure on unconsumed stdin [#26](url)

<details>
<summary>14 internal changes not included</summary>

- docs: add workflow limitations
- chore: rename repo references
- fix: resolve race condition
</details>
```

### Mintlify (changelog.mdx)

```mdx
<Update label="January 2026" description="v1.0.0" tags={["New releases", "Bug fixes"]}>
  ## Batch Processing

  Added powerful batch execution with parallel processing and real-time progress.

  **Highlights**
  - Added batch processing with parallel execution [#11]
  - Added real-time progress display [#20]

  ## Core Improvements

  Enhanced template handling and shell node validation.

  **Highlights**
  - Fixed template resolution to preserve types [#32]
  - Improved shell validation with actionable errors [#30]
</Update>
```

## Key Design Decisions

### 1. Using `--first-parent` to Avoid Duplicates

When a PR is merged, git history contains both the merge commit AND all individual commits. Using `--first-parent` shows only the main line, eliminating duplicates automatically.

### 2. Two-Pass LLM Approach

**First Pass (Parallel)**: Analyzes each commit in isolation. Fast but no cross-entry awareness.

**Second Pass (Aggregator)**: Sees ALL entries with context. Enables merging duplicates, consistent formatting, and proper sorting.

### 3. Inline Array Batch for Parallel Formats

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

This generates both output formats simultaneously, saving time.

### 4. Object Stdin for Combining Data

The `prepare-context` node combines data from two earlier nodes using object stdin:

```json
"stdin": {
  "filter": "${filter-and-format.stdout}",
  "commits": "${get-commits-enriched.stdout}"
}
```

Both JSON strings are auto-parsed, enabling direct access in jq.

### 5. Nested Template Access

Templates can access nested JSON fields directly:

```
${get-dates.stdout.iso}        → "2026-01-03"
${get-dates.stdout.month_year} → "January 2026"
```

## Performance

Typical run on a repository with ~30 commits:

| Metric | Value |
|--------|-------|
| Commits analyzed | 30 |
| Entries included | 15-17 |
| Total time | ~55 seconds |
| LLM cost | ~$0.08 |

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
- LLM may occasionally misclassify (review skipped section)
- Cost scales with commits (~$0.002 per commit)
