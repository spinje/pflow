# Generate Changelog (Simple)

Generate a changelog from git history with automatic PR enrichment and LLM classification.

This is the **simple version** - each commit gets its own entry. See `generate-changelog/` for the advanced version with LLM-powered entry merging and refinement.

## What it does

1. Gets commits since the last git tag
2. Fetches PR data from GitHub using `gh` CLI
3. Classifies each commit as user-facing or internal (LLM batch)
4. Formats changelog with jq (grouped by category, with PR links)
5. Creates a context file for verification before committing

## Usage

```bash
pflow examples/real-workflows/generate-changelog-simple/workflow.json
```

No inputs required - uses `gh` CLI for GitHub auth and auto-detects repo from git remote.

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `repo` | No | from git remote | Repository in `owner/repo` format |
| `changelog_path` | No | `CHANGELOG.md` | Path to changelog file |

## Outputs

| Output | Description |
|--------|-------------|
| `summary` | Summary of what was generated |
| `changelog` | Generated changelog markdown |
| `version` | Computed new version number (e.g., v1.0.0) |
| `version_bump` | Computed bump type (major/minor/patch) |
| `internal_entries` | Skipped internal entries for reference |

## Files created

- **CHANGELOG.md** - New changelog entry prepended to existing file
- **releases/\<version\>-context.md** - Verification context with:
  - Generated changelog
  - User-facing entries with full PR context
  - Skipped (internal) changes
  - Docs diff
  - Verification checklist

## Classification rules

**User-facing**: New features, bug fixes, API changes, CLI changes

**Internal** (skipped): Changes only in `tests/`, `docs/`, `.taskmaster/`, CI/CD, refactoring

## Version bump logic

- Any `Removed` or `Changed` → **major**
- Any `Added` → **minor**
- Otherwise → **patch**

## Cost & Performance

~$0.10-0.15 per run, ~30s (depends on number of commits)

- Batch LLM calls for classification (~$0.002 per commit)
- Formatting done with jq (no LLM)

## Prerequisites

- `gh auth login` (GitHub CLI authenticated)
- Git repository with at least one tag
