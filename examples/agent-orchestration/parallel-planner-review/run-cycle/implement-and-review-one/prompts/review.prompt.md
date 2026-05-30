Review branch ${branch} against ${base_branch}.

The implementer's summary was:
${summary}

This is a real review — read the diff AND the surrounding code it touches
(callers, tests, related modules), not just the patch in isolation. Run:

    git diff ${base_branch}...${branch}

Check correctness, missing or broken tests, and regressions in the code paths
this change affects. Return verdict "approve" only if it is safe to merge as-is;
otherwise "request-changes" with specific notes.
