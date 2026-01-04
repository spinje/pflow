# Generate Changelog

Generate a professional changelog from git history with automatic PR enrichment and classification.

## What it does

1. Gets commits since the last git tag
2. Fetches PR data from GitHub (title, body, link)
3. Classifies each commit as user-facing or internal using LLM
4. Generates a formatted changelog with PR links
5. Creates a context file for verification before committing

## Usage

```bash
# Or run from file
pflow examples/real-workflows/generate-changelog-simple/workflow.json \
  github_token="$(gh auth token)"
```

## Inputs

| Input | Required | Default | Description |
|-------|----------|---------|-------------|
| `github_token` | Yes | - | GitHub token for API access. Use `$(gh auth token)` |
| `repo` | No | from git remote | Repository in `owner/repo` format |
| `changelog_path` | No | `CHANGELOG.md` | Path to changelog file |

## Outputs

| Output | Description |
|--------|-------------|
| `summary` | Summary of what was generated |
| `changelog` | Generated changelog markdown |
| `version` | Computed new version number (e.g., v0.6.0) |
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

## Cost

~$0.10-0.15 per run (depends on number of commits)

- Batch LLM calls for classification (~$0.002 per commit)
- Single LLM call for refinement (~$0.05-0.08)
