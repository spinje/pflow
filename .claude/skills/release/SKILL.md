---
name: release
description: Run the pflow release process — generate changelog, bump version, commit, and create GitHub Release
argument-hint: [since_tag]
allowed-tools: Bash(uv run pflow:*), Bash(git:*), Bash(gh:*), Bash(cat:*), Bash(sed:*), Read, Glob, Grep, Edit
---

# Release Process

Run the full pflow release cycle. This skill walks through each step, pausing for review before destructive actions.

## Context

- The changelog workflow source file is `examples/real-workflows/generate-changelog/workflow.pflow.md`
- The GitHub Actions release workflow (`.github/workflows/on-release-main.yml`) triggers on `release: published` events
- CI builds the package from the git tag — it overrides `pyproject.toml` version via sed from the tag name
- PyPI package name is `pflow-cli` (not `pflow`)
- The `pflow` command runs the dev version locally (zsh alias), not the PyPI-installed version
- The Slack notification step requires Composio MCP to be configured. Pass `slack_channel=""` to skip it.

## Steps

### 1. Pre-flight checks

Before anything else, verify the repo is in a clean state:

```bash
git status --short
git fetch --tags
```

- Confirm we're on `main` with no uncommitted changes
- If there are uncommitted changes, ask the user how to handle them before proceeding

### 2. Determine the tag range

If the user provided `$ARGUMENTS`, use it as `since_tag`. Otherwise, detect the latest tag:

```bash
git describe --tags --abbrev=0
```

Show the user what commit range will be analyzed and how many commits are in the range:

```bash
git log --oneline <since_tag>..HEAD | wc -l
```

### 3. Run the changelog workflow

**If you have reason to believe this should be a major release, ask the user** before running:

> "Is this a major release? A major release means breaking changes that
> users must adapt to — removals, renames, or behavior changes — or a
> declaratory stability bump (e.g. v1.0.0). Default is no."

Translate the answer to `is_major_release=true` or `is_major_release=false`. This input is required — the workflow errors out at validation time if not passed. The LLM can never pick major; it's always a human decision.

When `is_major_release=false`, the workflow auto-detects minor vs patch from entries (Added → minor, else patch) and never bumps major. If breaking entries are detected anyway, the release still ships but a **prominent warning** is surfaced in both the summary and the release context file for your review at step 4.

When `is_major_release=true` without any Removed/Changed entries, a warning also appears — confirm the declaratory major is intentional.

Run the workflow:

```bash
uv run pflow examples/real-workflows/generate-changelog/workflow.pflow.md since_tag=<tag> is_major_release=<true|false>
```

To skip the Slack notification, pass an empty channel (the workflow uses conditional branching to skip Slack steps automatically):

```bash
uv run pflow examples/real-workflows/generate-changelog/workflow.pflow.md since_tag=<tag> is_major_release=<true|false> slack_channel=""
```

This produces three file outputs:
- `CHANGELOG.md` — prepended with the new version section
- `docs/changelog.mdx` — Mintlify `<Update>` component
- `releases/<version>-context.md` — full context for verification

The CLI output includes a `suggested_version` (computed from entry verbs: Removed/Changed = major, Added = minor, else patch). Capture this from the output.

### 4. Review

**STOP here.** Show the user:
1. **Any warnings surfaced by the workflow** — the summary and the top of `releases/<version>-context.md` both start with a "⚠ Warnings — Review Before Release" section when `is_major_release` and the classified entries disagree. Relay these verbatim and ask the user whether to adjust `is_major_release` and re-run, reclassify entries, or accept and proceed.
2. The suggested version from the workflow output
3. The changelog entries that were included (read `CHANGELOG.md` to show the new section)
4. A summary of what was skipped (read the "Skipped Changes" section from `releases/<version>-context.md`)
5. Ask: "Does this look correct? Any edits needed? Is the suggested version right?"

Do NOT proceed until the user confirms the version, warnings (if any), and content.

### 5. Bump version

Once the user confirms the version (which may differ from the suggested one), update two locations:

**pyproject.toml** — the package version (without `v` prefix):
```
version = "<confirmed-version>"
```

**src/pflow/cli/main.py** — the hardcoded fallback version (search for the `except Exception` block near `pkg_version("pflow-cli")`):
```python
            ver = "<confirmed-version>"
```

Then update the lockfile and verify:

```bash
uv lock
make check
```

The version bump in `pyproject.toml` makes `uv.lock` stale. CI runs `uv lock --locked` which will fail if the lockfile isn't updated. Always run `make check` before committing to catch this.

### 5b. Check roadmap

Read `docs/roadmap.mdx` and check if any items listed under "Now" or "Next" were completed in this release. If the roadmap looks stale, ask the user if they want to update it before committing.

### 6. Commit

Stage and commit the release artifacts together:

```bash
git add pyproject.toml src/pflow/cli/main.py uv.lock CHANGELOG.md docs/changelog.mdx releases/<version>-context.md
git commit -m "<version> changelog and version bump"
```

Show the user the diff before committing. Do NOT push yet.

### 7. Push

Ask the user for confirmation, then:

```bash
git push origin main
```

### 8. Create GitHub Release

```bash
gh release create v<version> --title "v<version>" --notes "See [CHANGELOG.md](CHANGELOG.md) for details."
```

This triggers the CI workflow which:
1. Overrides pyproject.toml version from the tag (sed)
2. Runs tests
3. Builds and publishes to PyPI via trusted publishing

### 9. Verify

After creating the release:
- Show the GitHub Release URL (from `gh release create` output)
- Check the CI workflow status: `gh run list --limit 3`
- Once CI completes, verify on PyPI: `https://pypi.org/project/pflow-cli/`

## Known issues

- The changelog workflow is **context-blind** — it doesn't know if this is a first release vs. a patch. Review the framing of entries carefully.
- LLM classification occasionally misclassifies changes. Always check the skipped list in the context file.
- The Mintlify docs (`docs.pflow.run`) require separate deployment — changes to `docs/changelog.mdx` won't be live until deployed.
- Cost scales with commit count (~$0.003 per commit for LLM classification).
