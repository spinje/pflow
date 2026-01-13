Generate a changelog from git history.

The problem: writing changelogs manually is tedious and things get missed. Internal refactoring gets mixed with user-facing features. PR links are forgotten.

Workflow:

1. Resolve repo from git remote (auto-detect owner/repo from origin, or use input if provided)

2. Get commits since the last git tag using `--first-parent` (avoids duplicates from PR merges)

3. Fetch PR data from GitHub (title, body, link) for commits that have PR references in their message

4. Extract file paths changed per commit (helps classify internal vs user-facing)

5. Get documentation changes since the tag (helps catch parameter renames, new features)

6. Batch-classify each commit in PARALLEL. Each call receives: commit subject, PR title, PR summary (first 500 chars of body), file paths. Output: classification (user-facing/internal), category (Added/Changed/Fixed/Removed/Improved), one-line summary. Use file paths as signal (tests/, docs/, .taskmaster/ = internal)

7. Split results: user-facing entries go to refinement, internal entries go to a separate output

8. Format the user-facing entries into changelog markdown: group by category, sort (Removed > Changed > Added > Fixed > Improved), add PR links. One entry per commit.

9. Compute version bump (simple rule): any Removed/Changed = major, any Added = minor, else patch

10. Assemble context file from the structured outputs - changelog, skipped changes, docs diff - for verification before committing

11. Update the changelog file

12. Output a summary showing what was generated

Output format:
```
## [v1.0.0] - 2026-01-13

### Changed
- Entry description ([#10](https://github.com/owner/repo/pull/10))

### Added
- Another entry ([#11](https://github.com/owner/repo/pull/11))
```

End result:
A professional changelog plus a context file where you can verify nothing was misclassified. Run it before each release.
