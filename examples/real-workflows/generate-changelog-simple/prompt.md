Generate a changelog from git history.

The problem: writing changelogs manually is tedious and things get missed. Internal refactoring gets mixed with user-facing features. PR links are forgotten.

Workflow:

1. Get commits since the last git tag using `--first-parent` (avoids duplicates from PR merges)

2. Enrich each commit with PR data from GitHub - title, body, link

3. Extract file paths changed per commit (helps classify internal vs user-facing)

4. Get documentation changes since the tag (helps catch parameter renames, new features)

5. Analyze each commit in parallel - is it user-facing or internal? Use file paths as a signal (tests/, docs/, .taskmaster/ = internal)

6. Refine the user-facing entries using docs diff for accuracy. Merge duplicates, standardize format, sort by importance (Removed > Changed > Added > Fixed > Improved)

7. Compute version bump: any Removed/Changed = major, any Added = minor, else patch

8. Generate the changelog markdown with PR links

9. Save a context file with the changelog, skipped changes, docs diff, and draft entries with full PR context - for verification before committing

10. Update the changelog file

11. Output a summary showing what was generated

End result:
A professional changelog plus a context file where you can verify nothing was misclassified. Run it before each release.
