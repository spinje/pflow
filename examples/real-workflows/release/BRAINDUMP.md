# Release Workflow - Complete Context Braindump

This document captures the full context of a conversation about building a complete release workflow for pflow. Another agent should be able to read this and continue brainstorming or building.

## Background: Why This Workflow Exists

### The Marketing Page Context

The user is preparing to launch pflow publicly and needs compelling examples for the marketing website. The site has three tabs for showcasing different use cases:

| Tab | Workflow | Purpose |
|-----|----------|---------|
| **Automation** | `release-announcements` | Multi-model LLM + MCP orchestration |
| **CI/CD** | `generate-changelog-simple` | Batch LLM classification |
| **Developers** | `webpage-to-markdown` | Batch vision AI processing |

### The Two-Workflow Pattern

We established that releases should be TWO separate workflows:

1. **`generate-changelog`** (exists) → Human reviews → Approves
2. **`release`** (this document) → Executes the actual release

The human review step between them is intentional - you don't want to auto-publish without reviewing the changelog.

### Simple vs Full Versions

Following the pattern of other workflows:

| Workflow | Simple (marketing showcase) | Full (actual use) |
|----------|----------------------------|-------------------|
| Changelog | `generate-changelog-simple` ✅ | `generate-changelog` ✅ |
| Release | `release-announcements` ✅ | `release` ❌ **this one** |

`release-announcements` was built as the "simple" showcase - just the announcement portion (9 LLM calls, 2 MCP integrations). This document is about the FULL release workflow.

---

## Key Insight: What pflow Adds vs Traditional CI/CD

**Traditional CI/CD (GitHub Actions, etc.) already does well:**
- Version bumping
- Building packages
- Publishing to PyPI
- Creating git tags
- Running tests

**What pflow uniquely adds:**
- LLM orchestration (changelog generation, announcement writing)
- MCP integrations without schema loading overhead
- Easy workflow creation (JSON vs YAML)
- Multi-provider model orchestration

**Implication for this workflow:** The interesting parts are the LLM/MCP steps (announcements). The mechanical parts (bump, build, publish) are standard but included for completeness.

---

## The Full Release Workflow

### Decided: Overall Flow

```
[Pre-condition: changelog already generated and reviewed]
    ↓
check-git-clean (fail if uncommitted changes)
    ↓
validate-version-format (semver check)
    ↓
check-pypi-available (fail if version already exists)
    ↓
run-tests (make test)
    ↓
bump-version-files
    ├── pyproject.toml
    ├── src/pflow/__init__.py
    └── (any others?)
    ↓
commit ("chore: release vX.Y.Z")
    ↓
create-tag (vX.Y.Z)
    ↓
push (main + tags)
    ↓
build-package (uv build or python -m build)
    ↓
upload-pypi (twine upload dist/*)
    ↓
create-github-release (with changelog as body)
    ↓
run release-announcements OR inline the announcement steps
    ↓
output-summary
```

### Decided: Order of Operations

**Push BEFORE build/publish** - We discussed whether code needs to be on remote before building. Conclusion:

- `build-package`: Does NOT require remote (builds from local files)
- `upload-pypi`: Does NOT require remote (just uploads dist/*)
- `create-github-release`: REQUIRES tag on remote

**But for trust/reproducibility:**
- Push first, then build/publish
- This ensures the git tag matches what's published
- Users can verify what they installed

**Final order:**
```
commit → tag → push → build → upload → github-release → announce
```

### Decided: No PR Required

For small teams (1-5 devs), direct to main is fine:
- Local review is sufficient
- PRs add overhead without proportional value
- Speed matters more than process
- If something's wrong, you fix it

PRs make sense when:
- Async review across time zones needed
- Audit trail required (compliance)
- Multiple approvers needed

**Decision: This workflow commits directly to main, no PR.**

---

## Inputs

### Decided Inputs

| Input | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `version` | string | Yes | - | e.g., "0.6.0" |

### Undecided/Ambiguous Inputs

| Input | Question | Options |
|-------|----------|---------|
| `changelog_file` | Where to read changelog from? | `CHANGELOG.md` section, or separate file? |
| `pypi_token` | How to handle? | Environment variable? pflow settings? Input? |
| `skip_tests` | Allow skipping tests? | Could be useful for hotfixes, but risky |
| `dry_run` | Preview mode? | Show what would happen without executing |
| `skip_announcements` | Separate release from announcements? | Maybe user just wants to publish, announce later |

---

## Steps: Detailed Analysis

### 1. check-git-clean

**Purpose:** Fail early if working directory has uncommitted changes.

**Implementation:** `shell` node with `git status --porcelain`

**Undecided:** What about untracked files? Should those also fail?
- Strict: Any output from `git status --porcelain` = fail
- Lenient: Only fail on modified/staged files, ignore untracked

### 2. validate-version-format

**Purpose:** Ensure version follows semver.

**Implementation:** Shell node with regex check, or dedicated validation.

**Undecided:**
- Strict semver (X.Y.Z only)?
- Allow pre-release tags (0.6.0-beta.1)?
- Allow build metadata (0.6.0+build.123)?

### 3. check-pypi-available

**Purpose:** Fail early if version already published to PyPI.

**Implementation:** `shell` node with `pip index versions pflow` or PyPI API call.

**Undecided:**
- What if PyPI is down? Fail or warn?
- Should this be optional (for re-releases after failed publish)?

### 4. run-tests

**Purpose:** Don't release broken code.

**Implementation:** `shell` node with `make test`

**Undecided:**
- Full test suite or quick smoke tests?
- What if tests are flaky? Retry logic?
- Allow `skip_tests` input for emergencies?

### 5. bump-version-files

**Purpose:** Update version in all necessary files.

**Files to update for pflow:**
- `pyproject.toml` - `version = "X.Y.Z"`
- `src/pflow/__init__.py` - `__version__ = "X.Y.Z"` (if exists)

**Undecided:**
- Does pflow have `__version__` in `__init__.py`? Need to check.
- Any other files? (docs config, etc.)
- Use shell/sed or dedicated file-edit nodes?

### 6. commit

**Purpose:** Commit the version bump.

**Implementation:** `git` node or `shell` with git commands.

**Decided:** Commit message format: `chore: release vX.Y.Z`

**Undecided:**
- Should commit include changelog updates too, or assume those were committed separately?
- Sign commits? (probably not for MVP)

### 7. create-tag

**Purpose:** Create git tag for the release.

**Implementation:** `git` node or `shell` with `git tag vX.Y.Z`

**Decided:** Tag format: `vX.Y.Z` (with 'v' prefix)

**Undecided:**
- Annotated tag with message, or lightweight tag?
- If annotated, what message? Changelog content?

### 8. push

**Purpose:** Push commit and tag to remote.

**Implementation:** `shell` with `git push && git push --tags` or `git push --follow-tags`

**Undecided:**
- Which remote? Assume `origin`?
- What if push fails? (network, permissions)

### 9. build-package

**Purpose:** Build wheel and sdist.

**Implementation:** `shell` with `uv build` or `python -m build`

**Decided:** Clean dist/ first: `rm -rf dist/`

**Undecided:**
- `uv build` vs `python -m build`? (pflow uses uv)
- Verify build succeeded? Check dist/ contents?

### 10. upload-pypi

**Purpose:** Publish to PyPI.

**Implementation:** `shell` with `twine upload dist/*`

**Undecided:**
- How to handle PYPI_TOKEN?
  - Environment variable (standard)
  - pflow settings system
  - Input parameter (risky - visible in logs?)
- Upload to TestPyPI first? (optional safety step)
- What if upload fails partway? (some files uploaded, some not)

### 11. create-github-release

**Purpose:** Create GitHub release with changelog as body.

**Implementation:** `shell` with `gh release create vX.Y.Z --notes "..."`

**Undecided:**
- Extract changelog section automatically?
- Attach build artifacts (wheel, sdist)?
- Mark as pre-release for beta versions?
- Draft first, then publish? Or publish immediately?

### 12. announcements

**Purpose:** Post to Slack, Discord, X.

**Options:**
1. Run `release-announcements` as nested workflow
2. Inline the announcement steps into this workflow

**Undecided:**
- Inline or nested? Nested is cleaner but adds complexity.
- What inputs does release-announcements need?
  - version ✅ (we have)
  - changelog_section (need to extract)
  - slack_channel (need input or default)
  - discord_channel_id (need input or default)

### 13. output-summary

**Purpose:** Show what was done.

**Implementation:** `shell` node with printf or template.

**Should include:**
- Version released
- PyPI URL
- GitHub release URL
- Announcement status
- X post file location

---

## Open Questions

### Architecture Questions

1. **Nested workflow or monolith?**
   - Should `release` call `release-announcements` as a nested workflow?
   - Or inline all announcement steps?
   - Tradeoff: Modularity vs simplicity

2. **Changelog extraction**
   - How to get the changelog section for this version?
   - Read from `CHANGELOG.md` and parse?
   - Expect it as input?
   - Read from `releases/vX.Y.Z-context.md` (generate-changelog output)?

3. **Error handling**
   - What if PyPI upload succeeds but GitHub release fails?
   - Partial state is messy
   - Should there be rollback logic?

### Security/Credentials Questions

4. **PyPI token handling**
   - Environment variable is standard
   - But pflow has a settings system - should it use that?
   - Never pass as input parameter (logged)

5. **GitHub token**
   - `gh` CLI usually handles this
   - But what if not authenticated?

### UX Questions

6. **~~Dry run mode?~~** - REJECTED
   - Considered but rejected
   - Adds complexity to every step (conditional logic everywhere)
   - Better alternatives exist: TestPyPI for publish testing, test channels for announcements
   - pflow workflows are deterministic - if it worked last time, it works this time
   - The workflow is fixed, only inputs vary - review inputs instead

7. **Interactive confirmation?**
   - "About to publish v0.6.0 to PyPI. Continue? [y/N]"
   - pflow workflows are non-interactive by design
   - But release is high-stakes...

8. **Partial execution?**
   - "Just build, don't publish"
   - "Just publish, already built"
   - Modular steps vs monolithic workflow

---

## Assumptions Made

1. **pflow uses `uv`** - Build with `uv build`
2. **GitHub CLI (`gh`) is available** - For creating releases
3. **Twine is available** - For PyPI upload
4. **Remote is `origin`** - Standard git remote name
5. **Tag format is `vX.Y.Z`** - With 'v' prefix
6. **Commit message is `chore: release vX.Y.Z`** - Conventional commits style
7. **Direct to main** - No PR workflow
8. **Changelog already exists** - From generate-changelog workflow

---

## Insights from the Conversation

### Insight 1: Simple vs Full for Marketing

The marketing page needs simple, understandable examples. The full release workflow is too complex for a 30-second demo. That's why we split:
- `release-announcements` (showcase) - Just the interesting LLM/MCP parts
- `release` (actual use) - Everything including mechanical steps

### Insight 2: pflow's Value in CI/CD

Traditional CI/CD already does version bumping and publishing well. pflow's value is in the LLM orchestration parts. Don't sell pflow as "another way to do CI/CD" - sell it as "adding intelligence to your pipeline."

### Insight 3: The Human Review Step

Releases shouldn't be fully automated. The flow is:
1. `generate-changelog` → outputs changelog
2. Human reviews changelog, makes edits
3. `release` → executes with reviewed changelog

This is intentional, not a limitation.

### Insight 4: Multi-Model Strategy

The `release-announcements` workflow uses three different models:
- Gemini (fast, cheap) for drafts
- GPT (analytical) for critique
- Claude (nuanced writing) for final

This "right model for each step" is a key pflow differentiator.

### Insight 5: Safe vs Public Platforms

Announcements have different risk levels:
- Slack: Safe (internal, can delete)
- Discord: Medium (community, but controlled)
- X: High (public, permanent)

That's why X post is saved to file for review, not auto-posted.

---

## Related Files

### Existing Workflows to Reference

- `/Users/andfal/projects/pflow/examples/real-workflows/release-announcements/workflow.json` - The announcement portion
- `/Users/andfal/projects/pflow/examples/real-workflows/release-announcements/README.md` - Announcement docs
- `/Users/andfal/projects/pflow/examples/real-workflows/release-announcements/prompt.md` - Announcement prompt
- `/Users/andfal/projects/pflow/examples/real-workflows/generate-changelog/workflow.json` - Full changelog
- `/Users/andfal/projects/pflow/examples/real-workflows/generate-changelog-simple/workflow.json` - Simple changelog

### Marketing Context

- `/Users/andfal/projects/pflow/scratchpads/marketing-page-plan.md` - Overall marketing plan
- `/Users/andfal/projects/pflow/scratchpads/main-page-copy.md` - Current site copy

### Project Files to Check

- `/Users/andfal/projects/pflow/pyproject.toml` - Where version is defined
- `/Users/andfal/projects/pflow/src/pflow/__init__.py` - Check if __version__ exists
- `/Users/andfal/projects/pflow/Makefile` - Check existing release targets

---

## Next Steps for Continuation

### If Continuing Brainstorming

1. Resolve the open questions above
2. Decide on input parameters
3. Decide on nested vs inline announcements
4. Decide on error handling strategy

### If Building the Workflow

1. Check which files need version bumping (pyproject.toml, __init__.py, others?)
2. Draft the workflow.json
3. Test each step individually
4. Test the full flow on a test release
5. Document in README.md
6. Create prompt.md for benchmarking

### If Simplifying

Consider splitting into smaller workflows:
- `release-prepare` - bump, commit, tag, push
- `release-publish` - build, upload, github-release
- `release-announcements` - already exists

This would give more flexibility but less "one command" convenience.

---

## Summary

This document captures the full context of designing a complete release workflow for pflow. The key decisions made:

1. Two-step process: generate-changelog → (review) → release
2. Direct to main, no PR
3. Push before build/publish for traceability
4. Announcements as the "interesting" part, mechanical steps for completeness

Key things still undecided:
1. How to handle PyPI token
2. Nested vs inline announcements
3. Dry run mode
4. Error handling/rollback
5. Which files need version bumping

The workflow should be practical for actual pflow releases, not just a demo.
