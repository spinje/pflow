# Generate Changelog Workflow — Progress Log

## Background

This workflow generates pflow's own changelogs — it's dogfooding. The
user treats it as a real tool, not a demo. It was originally written
before the Python code node existed (Task 104), using shell nodes with
jq pipelines. Session 1 modernized it to `.pflow.md` format with code
nodes where appropriate. Session 2 focused on making it self-documenting.

## User's Mental Model

The user cares about:

- **Practical correctness** — "did we lose any functionality?" is always
  the first concern after changes
- **Output quality** — they examine all three output files carefully
- **File integrity** — changelogs accumulate, prepend behavior matters.
  Never overwrite these files by copying from /tmp or similar
- **Cost awareness** — create a tag near HEAD for testing instead of
  running against hundreds of commits. ~$0.003 per commit for
  classification, ~$0.06 for a 25-commit run
- **Style consistency** — the `get-style-reference` node feeds existing
  Mintlify entries to the LLM as style examples. This feedback loop is
  intentional and valued
- **Documentation in code** — prefers self-documenting outputs and node
  descriptions over separate prose documentation

## Key Knowledge

**Code nodes in this workflow:**
- Output key is `.result` (not `.stdout`). Every downstream reference
  must use this.
- Type annotations are mandatory on all inputs and the `result` variable.
- Inputs are native Python objects (auto-parsed). Declare `data: list`,
  not `data: str`.
- `subprocess` works fine — used for git/gh in `gather-commit-data`
  and `get-docs-diff`. No sandboxing restrictions.
- Conditional result assignment: use a temp variable, assign
  `result: str = temp` at the end. Don't put `result: str = ...` in
  both branches of if/else. See `update-mintlify-file` for the pattern.

**`format-draft-entries` feeds both LLMs and context file:**
Added in Session 5. Formats each draft entry as structured markdown
with matched task reviews nested under entries. Both `render-changelogs`
and `save-release-context` consume this output. `save-release-context`
no longer does its own formatting — it just assembles sections.
Task links are only included when a review exists — entries without
reviews show `Task: N` (no link), entries with reviews show
`Task: [N](.taskmaster/tasks/task_N/task-review.md)`. The format LLM
copies what it sees.

**`summarize-docs-diff` is a batch LLM node (changed Session 6):**
Processes doc diffs in parallel chunks. `get-docs-diff` groups files
into chunks (300-line threshold, greedy bin-packing, never splits a
file) and outputs a list. `summarize-docs-diff` processes each chunk
in parallel. `join-docs-summary` concatenates the results back into a
single string for `render-changelogs` and `save-release-context`.
Moved before `render-changelogs` in Session 5 — the clean summaries
give better results than raw diffs.

**Full commit messages (`%B`):**
`gather-commit-data` uses `--format=%H|%B%x00` (null byte record
separator) to capture the full commit message including body. For merge
commits this adds one line (the PR title). For direct commits it adds
the full body with context the classifier needs. Changed in Session 5.

**The `get-style-reference` node (was `get-recent-updates`):**
Was orphaned in the original workflow (output unused). Now wired into
the `render-changelogs` mintlify prompt as a "Style Reference" section
and uses the `${mintlify_file}` input instead of a hardcoded path.

**Timeout on `gather-commit-data`:**
Set to 60s (default is 30s) because `gh` API calls can be slow.

**Testing tips:**
- Verify changes with a real end-to-end run, not just `--validate-only`.
  Ask the user before running — each run costs ~$0.07, writes to
  output files (CHANGELOG.md, docs/changelog.mdx, releases/), and
  stacks entries on uncommitted files. Run from the project directory
  so the user can review output. Never run in /tmp/.
- Create a tag near HEAD for cheap test runs: `since_tag=v0.7.0` or
  similar.

## Known Edge Cases

**`get-task-reviews` anachronistic reviews (fixed Session 4):**
Previously loaded reviews from the current filesystem based on task
numbers extracted from commit messages. A commit like "feat: add
Task 107" would cause the review to be loaded even though the task
wasn't implemented in the range — and the review file didn't even
exist at the target ref. Fixed by using `git diff --name-only` to
find which `task-review.md` files were actually committed in the
range, and `git show` to read content at the correct ref.

**`get-style-reference` empty path:** `Path("")` becomes `Path(".")`
which is a directory. Fixed in Session 3 to check `mintlify_file` is
truthy and `path.is_file()` before reading.

**`get-style-reference` regex:** The `r'<Update.*?</Update>'` with
`re.DOTALL` could break if Mintlify content contains a literal
`</Update>` string. Works in practice.

**`split-classifications` SKIP parsing:** If the LLM outputs "SKIP"
without a colon, it falls through to the included list instead of
skipped. Minor edge case — the LLM consistently outputs `SKIP: message`.

**`update-mintlify-file` frontmatter detection:** Splits on `---` to
find YAML frontmatter boundaries. Would break if content between the
fences contains `---` on its own line. Unlikely in practice.

**`parse_json_response` destroying LLM output (fixed in pflow):**
The LLM node's `parse_json_response()` (`llm.py:47-78`) looked for
` ```json ` or ` ``` ` fences in responses and extracted JSON from
them. When `summarize-docs-diff` produced a valid markdown summary
that included JSON code examples from the docs, the parser found a
code block, extracted the JSON, and **replaced the entire 3000-token
response** with just that fragment. The LLM didn't hallucinate — its
output was destroyed by the parser. Fixed in pflow code (Session 5).
The complex-template escape hatch (`"${var} "`) can't help because
parsing happens in the LLM node's `post()` method before template
resolution.

**Zero commits in range:** Not tested. The LLM batch with 0 items
might error or produce empty results if the tag is at HEAD.

**PR list scope:** `gh pr list --state merged --limit 200` pulls
recent merged PRs globally, not scoped to the tag date range. Could
miss relevant PRs on very active repos.

**No dry-run mode:** Every run writes to CHANGELOG.md, changelog.mdx,
and the releases directory. The user is aware and reviews before
committing.

**No error recovery:** If `gh` isn't authenticated, `gather-commit-data`
fails with `check=True` and the workflow stops. Same behavior as the
original shell version.

---

## Session 1: Modernization (2026-02-06 morning)

Rewrote from JSON IR to `.pflow.md` format. Converted shell+jq nodes
to Python code nodes. Merged `compute-bump-type`, `compute-next-version`,
and `get-dates` into single `compute-version` node. Wired orphaned
`get-recent-updates` into mintlify prompt. Reduced from 17 to 15 nodes.

Two successful end-to-end runs verified all nodes work.

## Session 2: Self-documenting workflow (2026-02-06 afternoon)

### Goal

Transfer valuable documentation from README into the workflow itself,
making it self-documenting so the README can be deleted.

### Changes Made

**1. Transferred README documentation into workflow description**

Added **Usage** section with corrected CLI examples (was referencing
`workflow.json`) and **Limitations** section from README. Kept the
existing description paragraphs and requirements line unchanged.

Dropped from README (intentionally):
- "Why This Exists" — implicit in the description
- "What It Does" 13-step summary — redundant with node descriptions
- "pflow Features Demonstrated" — outdated meta-documentation
- Architecture diagram — outdated node names, step order is self-documenting
- Design decisions 1-8 — already in node descriptions
- Design decisions 9-11 — outdated (JSON IR, object stdin, old template paths)
- Performance metrics — stale, changes every run
- Semantic versioning table — already in compute-version node description

**2. Made outputs self-documenting**

Changed write nodes (`update-changelog-file`, `update-mintlify-file`,
`save-release-context`) to return file paths instead of message strings.

Enriched `create-summary` runtime output with "Created files:" header
and per-file descriptions. Every run now teaches the user what was
produced.

Added blockquote format descriptions to write node prose:
- `update-changelog-file` — describes verb sorting, PR links, deduplication
- `update-mintlify-file` — describes themed grouping, no PR links, Accordion

Removed the "Output formats" prose section from the description — the
code and node descriptions now carry all format documentation.

**3. Renamed and simplified `## Outputs` section**

Renamed outputs to match what they return:
- `markdown_section` → `changelog_file` (was content, now path)
- `mintlify_section` → `mintlify_file` (was content, now path)

Simplified output descriptions to match their actual values (paths,
not content).

**4. Updated `create-summary` to source paths from write nodes**

Instead of reconstructing file paths from inputs, the summary node
now sources paths directly from write nodes. Single source of truth.

**5. Converted format-both prompts to YAML multiline**

Converted the two massive single-line YAML strings in the `format-both`
batch config to YAML `|` (literal block scalar) format. Same parsed
result, dramatically better readability and editability.

## Verification

- Workflow parsed and executed successfully after description changes
  (all 15 nodes passed, $0.06)
- YAML `|` multiline conversion not yet test-run (structurally valid
  YAML, parsed by yaml.safe_load)

## Open Items

- ~~Delete `README.md`~~ — done
- ~~Delete handoff file~~ — done
- ~~Test run to verify YAML `|` multiline prompts~~ — verified (Session 3 run)
- ~~v0.5.0 tag cleanup~~ — tag removed
- ~~Group release context by entry~~ — done (Session 3)
- Consider saving as named workflow (`pflow workflow save`)
- Tags v0.5.0 and v0.6.0 are local only — push to origin if keeping
- v0.7.0 tag exists at `792fdea` (pushed to origin) — may need
  adjustment before a real release
- Generated files (CHANGELOG.md, docs/changelog.mdx, releases/) are
  uncommitted and contain multiple test runs stacked on each other
- Run v0.6.0→v0.7.0 and v0.7.0→HEAD to complete the backfill
- `create-summary` node still says "task reviews" count but the
  context file no longer has a separate reviews section

---

## Session 4: Fix anachronistic task reviews (2026-02-06)

### Goal

Fix `get-task-reviews` loading reviews that don't belong to the
release range.

### Root Cause

`get-task-reviews` extracted task numbers from ALL commit messages
and loaded reviews from the current filesystem. This caused two
problems:

1. A commit mentioning a task (e.g., "feat: add Task 107") doesn't
   mean the task was implemented in this range — it might just add
   the task spec file.
2. Reading from the filesystem gives the current version of the
   review, not the version at `to_ref`. For historical runs, this
   loaded reviews written long after the release.

The correct signal: a task review belongs to a release if and only
if `task-review.md` was added or modified within `tag..to_ref`.

### Changes Made

**Rewrote `get-task-reviews` node:**

- Changed inputs from `commits` to `tag` + `to_ref`
- Uses `git diff --name-only tag..to_ref -- .taskmaster/tasks/` to
  find which `task-review.md` files were committed in the range
- Reads content with `git show to_ref:path` for correctness in
  historical runs
- Extracts task numbers from file paths (not commit messages)

**No other nodes changed.** `save-release-context` still matches
reviews to entries by task number. `format-both` still receives
reviews. Both just get a cleaner, accurate set.

**Side effects:**
- "Additional Task Reviews" section now only fires when a task was
  genuinely implemented in the range but all its commits were
  classified as internal (useful for verification, not noise)
- `format-both` no longer receives irrelevant reviews (fewer wasted
  tokens)

### Verification

- Not yet test-run

---

## Session 5: Structured LLM input (2026-02-06)

### Goal

Give the format LLMs clean structured markdown instead of serialized
Python dicts. The same data was already being formatted into readable
markdown for the context file — just formatted too late for the LLMs
to benefit.

### Changes Made

**1. Added `format-draft-entries` node** (new, 1 node added)

Placed between `compute-version` and `format-both`. Formats each draft
entry as a markdown section with commit info, PR details, files, and
matched task review nested under its entry. Outputs `{entries, unmatched_reviews}`.

Logic moved directly from `save-release-context`. No data changes —
same fields, same formatting, just done earlier.

**2. Updated `format-both` prompts**

Both markdown and mintlify prompts now reference
`${format-draft-entries.result.entries}` instead of the raw
`${prepare-context.result}` dict. Removed separate `## Task Reviews`
sections — reviews are now embedded in their matching entries.

**3. Simplified `save-release-context`**

Removed `task_reviews` and `draft_entries` inputs, the 40-line
formatting loop, and unmatched review tracking. Now receives
pre-formatted `formatted_entries` and `unmatched_reviews` strings.
~60 lines of code → ~35. Also downgraded from 4-backtick to 3-backtick
fence (no longer needed).

### Key Insight

The format LLMs were receiving:
```
[{'draft': 'Added X', 'index': 0, 'context': {'hash': '733a114', ...}}]
```
Now they receive:
```markdown
### [1/6] Added X
*Commit: `733a114` feat: add X*
PR: #17 — Add X (https://github.com/...)
Files: src/...
**Task 96 Review**
...review content...
```

Same data, dramatically better readability for the LLM.

**4. Discovered and fixed `parse_json_response` bug**

During v0.5.0→v0.6.0 testing, the Documentation Changes section
showed a JSON fragment instead of the summary. Investigation revealed
the LLM node's `parse_json_response()` was finding ` ```json ` code
blocks inside the prose response, extracting JSON from them, and
replacing the entire response with just that fragment. The LLM's
2969-token markdown summary was destroyed — only a 50-token JSON
example survived. Fixed in pflow code by removing the aggressive
code block extraction from `parse_json_response()`.

**5. Moved `summarize-docs-diff` before `format-both`**

Originally placed after `format-both` (Session 3) so the format LLM
got raw diffs. In practice, the 16KB of raw `+`/`-` lines was noisy
input — the ~4KB clean summary with code snippets gives better
results. Both format LLMs now reference `${summarize-docs-diff.response}`
instead of `${get-docs-diff.result}`.

**6. Switched to full commit messages (`%B`)**

Changed `get-commits-enriched` from `--format=%H|%s` (subject only)
to `--format=%H|%B%x00` (full message with null byte separator).
Parsing updated from line-by-line to record-by-record split on `\0`.

For merge commits: adds one line (the PR title, redundant with
`gh pr list`). For direct commits: adds the full body with valuable
context the classifier was missing. Result: 21 included entries vs 17
before for v0.5.0→v0.6.0 — the richer context helped the classifier
recognize more changes as user-facing.

**7. Task links only when review exists**

Updated `format-draft-entries` to include task links only for entries
with a matching task review:
- With review: `Task: [96](.taskmaster/tasks/task_96/task-review.md)`
- Without review: `Task: 96` (no link)

The format LLM copies what it sees — no need for it to decide.
Updated the markdown prompt's output format examples and rules to
show all four entry variants (PR+task, PR only, task only, neither).

**8. Added tone and style guidance to format LLM prompts**

Both prompts now include user-facing focus: "describe what changed for
users, not how it was implemented." The mintlify prompt adds tone
guidance: calm, understated, specific, no hype. Both include: "never
invent details — if an entry is too vague to understand, drop it."

**9. Updated prose descriptions across 5 nodes**

- `get-docs-diff` — now says it feeds `summarize-docs-diff`
- `get-commits-enriched` — mentions full commit message (`%B`)
- `analyze-commits` — "full commit message"
- `format-both` — reflects pre-formatted entries and docs summaries
- `update-changelog-file` — mentions task review links

### Verification

- Full end-to-end run (HEAD): all 17 nodes passed, $0.07
- Historical run (v0.5.0→v0.6.0): all 17 nodes passed, $0.14-0.17
- Documentation Changes section now shows clean markdown summaries
  with code snippets (previously showed garbage JSON from
  `parse_json_response` bug)
- Format LLMs confirmed receiving structured markdown entries and
  docs summaries via trace inspection
- Context file format unchanged (same structured markdown)
- Workflow is still 17 nodes (no count change from Session 5 start)

---

## Session 3: Historical changelog + context file overhaul (2026-02-06)

### Goal

1. Support generating changelogs for historical tag ranges (e.g.,
   `v0.5.0→v0.6.0`) instead of only `tag→HEAD`.
2. Overhaul the release context file to be human-readable — replace
   the JSON dump with structured markdown, add LLM-summarized docs,
   and nest task reviews under their related entries.

### Changes Made

**1. Added `to_ref` input** (default: `HEAD`)

New input that sets the end of the git range. When set to a tag, the
workflow extracts the version and date from the tag instead of
computing them. Updated usage examples in workflow description.

**Modified 3 nodes for `to_ref`:**

- `get-docs-diff` — added `to_ref` input, replaced `HEAD` with
  `{to_ref}` in all 3 git commands
- `get-commits-enriched` — added `to_ref` input, replaced `HEAD`
  with `{to_ref}` in 2 git commands
- `compute-version` — added `to_ref` input with conditional logic:
  if `to_ref` is a tag, extracts version from tag name and date from
  `git log -1 --format=%ai`; otherwise keeps current computation.
  Updated node description to reflect both modes.

**2. Created artificial tags for testing**

Placed two tags at meaningful milestone commits:
- `v0.5.0` at `34697a8` (PR #39, Jan 3) — JSON auto-parsing features
- `v0.6.0` at `5d8d1d8` (PR #65, Jan 14) — batch indexing + 12 fixes
- `v0.7.0` already existed at `792fdea` (PR #84, Feb 5)

Tags are local only (not pushed to origin).

**3. Added `summarize-docs-diff` LLM node** (new, 1 node added)

Summarizes raw git diffs of documentation files into human-readable
bullet points per file. Originally placed after `format-both` so the
format LLM got raw diffs for parameter accuracy. Moved before
`format-both` in Session 5 — the clean summary with code snippets
gives better results than raw diffs.

Prompt rules include: focus on conceptual changes, group related
add/remove into "Changed X to Y", include actual code snippets when
code examples change, no JSON wrapping.

**4. Added `hash` and `pr_summary` to `prepare-context`**

Pass commit short hash (7 chars) and PR summary through so the
context file can show them.

**5. Rewrote `save-release-context` — complete format overhaul**

Old format:
- Changelog, Skipped, Task Reviews, Docs (raw diffs), Draft Entries
  (JSON blob)

New format:
- Changelog, Skipped Changes, Documentation Changes (LLM-summarized),
  Draft Entries with Context (structured markdown)

Draft entries are now individual H3 sections with:
- `[N/total]` numbering in heading for navigation
- Commit hash + message (italic)
- Task number, PR number + title + link, files (only when non-empty)
- Full PR description body
- Task review nested under matching entry (matched by task_number)
- `━━━` thick Unicode separator between entries

Removed:
- "Included Commits" section (redundant with draft entries)
- Separate "Task Implementation Reviews" section (now nested under
  entries; unmatched reviews go to "Additional Task Reviews" fallback)
- JSON dump of draft entries
- `import json` (no longer needed)

**6. Fixed `get-recent-updates` crash on empty `mintlify_file`**

`Path("")` becomes `Path(".")` which is a directory.
`path.read_text()` throws `IsADirectoryError`. Fixed to check
`mintlify_file` is truthy and `path.is_file()` before reading.

**7. Defensive type handling for `docs_summary`**

LLM response may get auto-parsed from string to dict by pflow's
auto-JSON parsing feature. Declared `docs_summary: object` and
coerce with `str()`. Added "no JSON wrapping" to LLM prompt.

### Key Insight: LLM Node JSON Parsing

The LLM node's `parse_json_response()` aggressively extracts JSON
from code blocks in responses. When an LLM response contains JSON
code examples (common in docs summaries), the parser can destroy the
response by extracting a code block fragment. This was fixed in pflow
code during Session 5. Separately, pflow also auto-parses simple
templates (`${node.response}`) — defense is to declare input as
`object` and `str()` coerce, but this only helps at the template
level, not the node level.

### Verification

- 5 successful end-to-end runs during development
- Default `to_ref=HEAD`: all 16 nodes passed, ~$0.06
- Historical `since_tag=v0.5.0 to_ref=v0.6.0`: all 16 nodes passed,
  ~$0.15 (58 commits, larger range)
- Context file format verified: numbered entries, thick separators,
  nested task reviews, LLM-summarized docs with code snippets,
  no JSON anywhere
- Workflow is now 17 nodes (was 15, then 16 after Session 3)

---

## Session 6: Chunked docs summarization (2026-02-07)

### Goal

Remove the 50-line-per-file truncation in `get-docs-diff` by splitting
doc diffs into chunks for parallel LLM summarization, so no diff content
is lost.

### Changes Made

**1. Rewrote `get-docs-diff` output from `str` to `list`**

Removed the `[:50]` per-file truncation. Now collects full diffs per
file and groups them into chunks using greedy bin-packing: files are
added to the current chunk until the total exceeds 300 diff lines, then
a new chunk starts. A file is never split — even a 700-line file gets
its own chunk. Output changed from a single concatenated string to a
list of chunk strings.

**2. Converted `summarize-docs-diff` to batch LLM node**

Added `yaml batch` config with `items: ${get-docs-diff.result}` and
`parallel: true`. Changed prompt from `${get-docs-diff.result}` to
`${item}`. Updated the "What you're given" section to explain that
input is a batch chunk with variable file count. Added code block
example to the output format section.

**3. Added `join-docs-summary` code node** (new, 1 node added)

Placed between `summarize-docs-diff` and `format-both`. Concatenates
the per-chunk `.response` values into a single string. Downstream
consumers (`format-both` and `save-release-context`) receive the same
single-string interface they had before.

**4. Updated 3 template references**

Changed `${summarize-docs-diff.response}` to `${join-docs-summary.result}`
in both `format-both` prompts (markdown and mintlify) and in
`save-release-context`.

### Key Insight

The original 50-line cap existed to keep total input size manageable for
a single LLM call. Chunked batching removes that constraint — each
chunk gets its own call with a generous line budget, so no diff content
is truncated. Small releases stay as 1 chunk (same cost as before);
large releases split into 2-4 parallel calls.

**5. Updated `summarize-docs-diff` prompt**

Added note that input is a batch chunk with variable file count. Added
code block example to the output format section (bash CLI example, not
source code — these are doc file diffs).

### Verification

- Full end-to-end run (v0.7.0→HEAD): all 18 nodes passed, $0.10
- `summarize-docs-diff` processed 4 chunks in parallel (12 doc files)
- Workflow is now 18 nodes (was 17)

---

## Session 6b: Node reordering and renaming (2026-02-07)

### Goal

Improve workflow readability by grouping nodes by pipeline and renaming
vague node names.

### Changes Made

**1. Reordered nodes into logical groups**

Moved `get-docs-diff` from position 3 to position 10 (right before
`summarize-docs-diff`) and `get-recent-updates` from position 4 to
position 13 (right before `render-changelogs`). Each producer now sits
next to its consumer instead of being defined 9-10 nodes away.

New order reads as four clear phases:
- **Tag resolution** (1-2): get-latest-tag, resolve-tag
- **Commit pipeline** (3-9): gather, classify, split, enrich, compute,
  format
- **Docs pipeline** (10-12): get-docs-diff, summarize, join
- **Format & output** (13-18): style reference, render, save, write,
  summary

No functional change — pflow executes top-to-bottom regardless, and
all dependency constraints are satisfied in the new order.

**2. Renamed 6 nodes for clarity**

| Old name | New name | Why |
|----------|----------|-----|
| `get-commits-enriched` | `gather-commit-data` | "enriched" is jargon |
| `analyze-commits` | `classify-commits` | It classifies as user-facing vs internal |
| `filter-and-format` | `split-classifications` | It splits, doesn't format |
| `prepare-context` | `enrich-drafts` | It enriches drafts with commit context |
| `get-recent-updates` | `get-style-reference` | Communicates purpose (style examples for LLM) |
| `format-both` | `render-changelogs` | "both" was meaningless |

All template references (`${old-name.*}`) and prose references updated.

### Verification

- Full end-to-end run (v0.7.0→HEAD): all 18 nodes passed, $0.09
- Execution output now reads as a clear narrative:
  gather → classify → split → enrich → compute → format →
  get-docs-diff → summarize → join → style-ref → render → save
