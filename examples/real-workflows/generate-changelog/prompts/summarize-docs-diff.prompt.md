Summarize documentation changes for a release context file.

## What you're given

A batch of raw git diffs of documentation files changed between two
release tags. You may receive one file or several, depending on diff
size. Each file section has the filename, commit refs, and raw diff
lines (lines starting with `+` were added, `-` were removed).

## Raw diffs

${item}

## What to produce

For each file, output an H3 heading with the file path, a commits line,
and 1-5 bullet points describing what changed conceptually.

## Output format

### path/to/file.mdx

*Commits: abc1234, def5678*

- Changed X to Y
- Added section about Z
- Removed deprecated W

### another/file.mdx

*Commits: ghi9012*

- Updated table with new model recommendations
- Added usage example for batch processing:
  ```bash
  pflow my-workflow.pflow.md batch_size=10
  ```

## Rules
- Focus on WHAT changed conceptually, not line-by-line diffs
- Group related added+removed lines into single "Changed X to Y" bullets
- Skip trivial whitespace or formatting-only changes
- Keep bullet points concise (one line each)
- Use commit short hashes only (first 7 chars), not full messages
- If a file has only trivial changes, write "Minor formatting changes"
- If code examples were added or changed, include the actual code snippet
  in a fenced code block so reviewers can see the exact change without
  opening the file
- Output ONLY the markdown sections as plain text, no JSON wrapping,
  no outer code fences, no preamble or explanation
