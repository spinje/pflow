# Generate Changelog

Generate a changelog from git history with PR enrichment, LLM classification,
task review cross-referencing, and dual-format output (markdown + Mintlify).
Computes semantic version bumps and saves a full release context file for
AI agents and verification.

## Inputs

### since_tag

Tag to start from. Defaults to the latest git tag if not specified.

- type: string
- required: false
- default: ""

### changelog_file

Path to the markdown changelog file to prepend the new entry to.

- type: string
- required: false
- default: CHANGELOG.md

### mintlify_file

Path to Mintlify changelog file. Pass empty string to skip Mintlify output.

- type: string
- required: false
- default: docs/changelog.mdx

### releases_dir

Directory for release context files containing full verification data.

- type: string
- required: false
- default: releases

## Steps

### get-latest-tag

Get latest git tag as baseline for changelog range.

- type: shell

```shell command
tag=$(git describe --tags --abbrev=0 2>/dev/null || echo 'v0.0.0'); printf '{"latest_tag": {"name": "%s"}}' "$tag"
```

### resolve-tag

Use provided tag or default to latest. Strips trailing newline for clean
template interpolation in downstream nodes.

- type: shell

```shell command
provided='${since_tag}'
latest='${get-latest-tag.stdout.latest_tag.name}'
if [ -n "$provided" ]; then echo "$provided"; else echo "$latest"; fi | tr -d '\n'
```

### get-docs-diff

Get documentation changes since tag, grouped by file with commit refs.
Excludes changelog.mdx itself to avoid circular references.

- type: shell

```shell command
tag='${resolve-tag.stdout}'
for file in $(git diff "$tag"..HEAD --name-only -- docs/ 2>/dev/null | command grep -v changelog.mdx); do
  echo "## $file"
  echo "Commits: $(git log "$tag"..HEAD --oneline -- "$file" | paste -sd ', ' -)"
  echo "Changes:"
  git diff "$tag"..HEAD -- "$file" | command grep '^[+-]' | command grep -v -E '^\+\+\+|^---' | head -50
  echo ""
done
```

### get-recent-updates

Get last 2 Update blocks from Mintlify changelog as style reference for
the LLM generating the Mintlify format output.

- type: shell

```shell command
awk '/<Update/,/<\/Update>/{print; if(/<\/Update>/){count++; if(count==2) exit}}' docs/changelog.mdx 2>/dev/null || echo ''
```

### get-commits-enriched

Fetch commits since tag with PR metadata, file paths, and task numbers.
Joins commit messages with GitHub PR data for rich classification context.

- type: shell

```shell command
tag='${resolve-tag.stdout}'
repo=$(gh repo view --json nameWithOwner -q '.nameWithOwner')

# Get commits with proper JSON escaping
commits=$(git log --first-parent "$tag"..HEAD --format='%H|%s' | while IFS='|' read -r hash msg; do jq -n --arg hash "$hash" --arg msg "$msg" '{hash: $hash, commit_message: $msg}'; done | jq -s '.')

# Get file changes per commit
file_changes=$(git log --first-parent "$tag"..HEAD --format='HASH:%H' --name-only | \
  awk '/^HASH:/{hash=substr($0,6); next} NF{files[hash]=files[hash] $0 ","} END{for(h in files) print h "|" files[h]}' | \
  jq -Rs 'split("\n") | map(select(length>0) | split("|") | {key: .[0], value: (.[1] // "" | split(",") | map(select(length>0)) | join(", "))}) | from_entries')

# Get PRs
prs=$(gh pr list --state merged --limit 200 --json number,title,body 2>/dev/null || echo '[]')

# Combine all data
echo "$commits" | jq --argjson prs "$prs" --argjson files "$file_changes" --arg repo "$repo" '
  map(. + {
    pr_number: null, pr_title: "", pr_body: "", pr_link: "", is_merge: false,
    files_changed: ($files[.hash] // ""),
    task_number: null
  } |
  # Extract task number from commit message or PR body
  (if .commit_message | test("[Tt]ask[- ]?[0-9]+") then
    (.commit_message | capture("[Tt]ask[- ]?(?<num>[0-9]+)").num | tonumber)
  else null end) as $task_from_commit |
  . + {task_number: $task_from_commit} |
  # Enrich with PR data
  if .commit_message | test("^Merge pull request #[0-9]+") then
    (.commit_message | capture("#(?<num>[0-9]+)").num | tonumber) as $prnum |
    ($prs | map(select(.number == $prnum)) | first // {}) as $pr |
    (if ($pr.body // "") | test("[Tt]ask[- _]?[0-9]+") then
      (($pr.body // "") | capture("[Tt]ask[- _]?(?<num>[0-9]+)").num | tonumber)
    else .task_number end) as $task_from_pr |
    . + {
      pr_number: $prnum,
      pr_title: ($pr.title // ""),
      pr_body: ($pr.body // ""),
      pr_link: "https://github.com/\($repo)/pull/\($prnum)",
      is_merge: true,
      task_number: ($task_from_pr // .task_number)
    }
  elif .commit_message | test("\\(#[0-9]+\\)") then
    (.commit_message | capture("\\(#(?<num>[0-9]+)\\)").num | tonumber) as $prnum |
    . + {pr_number: $prnum, pr_link: "https://github.com/\($repo)/pull/\($prnum)"}
  else . end
  # Add pr_summary (truncated for classification)
  | . + {pr_summary: (if .pr_body and (.pr_body | length) > 0 then (.pr_body | split("\n## ") | map(select(startswith("Summary"))) | first // "") | split("\n\n")[0:2] | join("\n\n") | .[0:800] else "" end)}
  )'
```

### get-task-reviews

Read task-review.md files for referenced tasks to provide implementation
context for accurate changelog entry refinement.

- type: shell
- stdin: ${get-commits-enriched.stdout}

```shell command
# Extract unique task numbers
task_nums=$(jq -r '[.[].task_number | select(. != null)] | unique | .[]')

echo '{'
first=true
for num in $task_nums; do
  review_file=".taskmaster/tasks/task_$num/task-review.md"
  if [ -f "$review_file" ]; then
    content=$(cat "$review_file")
    if [ -n "$content" ]; then
      if [ "$first" = true ]; then first=false; else echo ','; fi
      printf '"%s": %s' "$num" "$(printf '%s' "$content" | jq -Rs .)"
    fi
  fi
done
echo '}'
```

### analyze-commits

Classify each commit as user-facing or internal based on commit message,
PR data, and file paths.

- type: llm

```yaml batch
items: ${get-commits-enriched.stdout}
parallel: true
max_concurrent: 90
error_handling: continue
```

````prompt
Analyze this change for a user-facing changelog entry.

## Context
Is PR merge: ${item.is_merge}
Commit message: ${item.commit_message}
Files changed: ${item.files_changed}
PR Number: ${item.pr_number}
PR Title: ${item.pr_title}
PR Summary: ${item.pr_summary}
PR Link: ${item.pr_link}

## Instructions
If this is a PR merge (is_merge=true), use the PR Title and PR Summary to understand what changed.
If this is a direct commit, use the commit message.

## CRITICAL: No guessing or inferring
* ONLY use information explicitly provided in the commit/PR
* If the commit message is minimal (e.g., "fix bug"), keep the changelog entry minimal
* Do NOT invent details, add context, or guess what the change might do
* Do NOT embellish with phrases like "for better performance" unless explicitly stated
* If unclear whether user-facing, default to SKIP
* ALWAYS specify WHAT component/node/feature changed (e.g., "Added timeout parameter to shell node" not just "Added timeout parameter")

STRICT RULES - Output "SKIP: <original commit message>" unless this DIRECTLY affects end users:

✅ INCLUDE (user-facing):
* New CLI commands or features users can use
* New workflow capabilities
* Bug fixes that users would have encountered
* Breaking changes users need to know about
* Performance improvements users would notice

❌ SKIP (not user-facing):
* Internal refactoring or code cleanup
* Developer tooling improvements
* Documentation updates
* Test improvements
* CI/CD changes
* Internal implementation details
* Dependency updates
* Task/planning files (e.g., "add task for X")
* Files in internal paths: .claude/, .taskmaster/, .github/, tests/

## Output Format
If INCLUDE and has PR link: Write entry ending with [#N](link)
  Example: "Added batch processing with parallel execution [#17](https://github.com/owner/repo/pull/17)"

If INCLUDE but no PR: Write entry without link
  Example: "Fixed crash when running with empty input"

If SKIP: Output "SKIP: " followed by the ORIGINAL commit message (not a summary)
  Example: "SKIP: docs: update README" (keep the exact commit message)
  Example: "SKIP: chore: update dependencies"
  Example: "SKIP: test: add unit tests for parser"
  Example: "SKIP: add task for feature X" (planning, not implementation)

Output ONLY the changelog line or SKIP line. Nothing else.
````

### filter-and-format

Separate user-facing entries from skipped internal changes.

- type: shell
- stdin: ${analyze-commits.results}

```shell command
jq '
  # Add index to each item, filter nulls
  [to_entries[] | select(.value.response != null) | {index: .key, response: .value.response}] |

  # Separate included and skipped
  [.[] | select(.response | type == "string") | select(.response | startswith("SKIP") | not) | select(.response != "")] as $included |
  [.[] | select(.response | type == "string") | select(.response | startswith("SKIP")) | .response | sub("^SKIP: "; "")] as $skipped |

  {
    included: $included,
    skipped: $skipped
  }
'
```

### prepare-context

Join draft entries with original commit context for the refinement step.

- type: shell

```yaml stdin
filter: ${filter-and-format.stdout}
commits: ${get-commits-enriched.stdout}
```

```shell command
jq '. as $root | .filter.included | map({draft: .response, index: .index, context: ($root.commits[.index] | {commit_message, task_number, files_changed: ((.files_changed // "") | split(", ") | if length > 5 then (.[0:5] | join(", ")) + " ... and \(length - 5) more files" else . | join(", ") end), pr_title, pr_body, pr_link, pr_number})})'
```

### compute-bump-type

Determine semver bump type based on entry categories.
Removed/Changed = major, Added features = minor, else patch.

- type: shell
- stdin: ${prepare-context.stdout}

```shell command
jq -r 'map(.draft) | (map(select(startswith("Added"))) | length) as $features | (map(select(startswith("Fixed"))) | length) as $fixes | (map(select(startswith("Improved"))) | length) as $improvements | (map(select(startswith("Removed") or startswith("Changed"))) | length) as $breaking | if $breaking > 0 then "major" elif $features > 0 then "minor" else "patch" end'
```

### compute-next-version

Calculate next version number by applying the bump to the current tag.

- type: shell

```shell command
current=$(echo '${resolve-tag.stdout}' | sed 's/^v//')
bump=$(echo '${compute-bump-type.stdout}' | tr -d '\n')
major=$(echo $current | cut -d. -f1)
minor=$(echo $current | cut -d. -f2)
patch=$(echo $current | cut -d. -f3)
case $bump in
  major) printf 'v%d.0.0' $((major + 1)) ;;
  minor) printf 'v%d.%d.0' $major $((minor + 1)) ;;
  patch) printf 'v%d.%d.%d' $major $minor $((patch + 1)) ;;
esac
```

### get-dates

Get current date in both ISO and human-readable formats for changelog headers.

- type: shell

```shell command
printf '{"iso": "%s", "month_year": "%s"}' "$(date +%Y-%m-%d)" "$(date +"%B %Y")"
```

### format-both

Refine and format changelog in two parallel formats: standard markdown
for CHANGELOG.md and Mintlify Update component for docs/changelog.mdx.

- type: llm

```yaml batch
items:
  - format: markdown
    prompt: "Refine and format these changelog entries as a markdown section for CHANGELOG.md.\n\n## Input\nVersion: ${compute-next-version.stdout}\nDate: ${get-dates.stdout.iso}\n\n## Draft Entries with Context\nEach entry has a `draft` field and a `context.pr_link` field with the full GitHub URL.\n${prepare-context.stdout}\n\n## Task Reviews (for accuracy)\n${get-task-reviews.stdout}\n\n## Documentation Changes (for parameter accuracy)\n${get-docs-diff.stdout}\n\n## Refinement Tasks\n1. Merge duplicates \u2192 combine PR links\n2. Standardize verbs: Allow\u2192Added, Enable\u2192Added, Update\u2192Changed/Improved\n3. Sort by: Removed > Changed > Added > Fixed > Improved\n4. Use docs diff for accurate parameter names\n5. Use task reviews for accurate feature descriptions\n\n## Output Format\n## v1.0.0 (2026-01-04)\n\n- Removed X [#10](https://github.com/owner/repo/pull/10)\n- Changed Y [#11](https://github.com/owner/repo/pull/11)\n- Added Z [#12](https://github.com/owner/repo/pull/12), [#13](https://github.com/owner/repo/pull/13)\n- Fixed W [#14](https://github.com/owner/repo/pull/14)\n\n## Rules\n- Use version and date exactly as provided\n- Each entry as bullet with `- `\n- CRITICAL: Use the FULL pr_link URL from context, not just the PR number\n- Format: [#N](full_url) where full_url is from context.pr_link\n- Combine PR links when merging duplicates\n- Start with ## - no code fences\n- Output ONLY the markdown section"
  - format: mintlify
    prompt: "Generate a Mintlify changelog <Update> component.\n\n## Input\nVersion: ${compute-next-version.stdout}\nMonth/Year: ${get-dates.stdout.month_year}\nBump Type: ${compute-bump-type.stdout}\n\n## Draft Entries\n${prepare-context.stdout}\n\n## Task Reviews\n${get-task-reviews.stdout}\n\n## Documentation Changes\n${get-docs-diff.stdout}\n\n## Required Format\nYou MUST output exactly this structure (with your content):\n\n<Update label=\"MONTH YEAR\" description=\"VERSION\" tags={[\"New releases\", \"Bug fixes\"]}>\n  ## Theme Title\n\n  Brief description.\n\n  **Highlights**\n  - Feature one\n  - Feature two\n\n  ## Another Theme\n\n  Description.\n\n  **Highlights**\n  - Feature three\n</Update>\n\n## Tasks\n1. Group entries into 2-4 themes\n2. Merge duplicates\n3. Standardize verbs (Allow\u2192Added, Enable\u2192Added)\n4. No PR links (user-facing changelog)\n5. Add <Accordion title=\"Breaking changes\"> if bump type is major\n\n## CRITICAL\n- Output ONLY the <Update>...</Update> component\n- First character must be <\n- Last characters must be </Update>\n- NO JSON, NO code fences, NO explanations"
parallel: true
```

```prompt
${item.prompt}
```

### save-release-context

Save full context to version-named file for AI agents and verification.
Includes changelog, skipped entries, task reviews, and documentation changes.

- type: shell

```yaml stdin
changelog: ${format-both.results[0].response}
skipped: ${filter-and-format.stdout.skipped}
task_reviews: ${get-task-reviews.stdout}
docs_diff: ${get-docs-diff.stdout}
draft_entries: ${prepare-context.stdout}
```

```shell command
version='${compute-next-version.stdout}'
date='${get-dates.stdout.iso}'
releases_dir='${releases_dir}'

mkdir -p "$releases_dir"
outfile="$releases_dir/$version-context.md"

# Capture stdin to temp file (handles large data)
tmpfile=$(mktemp)
cat > "$tmpfile"

# Build file section by section
printf '%s\n' "# $version Release Context" > "$outfile"
printf '\n%s\n' "Generated: $date" >> "$outfile"
printf '%s\n' "This file contains implementation context for AI agents and release verification." >> "$outfile"
printf '\n%s\n\n' "---" >> "$outfile"

# Changelog section
printf '%s\n\n' "## Changelog" >> "$outfile"
jq -r '.changelog' "$tmpfile" >> "$outfile"
printf '\n%s\n\n' "---" >> "$outfile"

# Skipped changes section
printf '%s\n\n' "## Skipped Changes (Verification)" >> "$outfile"
printf '%s\n\n' "Review these to ensure nothing was incorrectly classified as internal:" >> "$outfile"
jq -r '.skipped[]? // empty | "- " + .' "$tmpfile" >> "$outfile"
printf '\n%s\n\n' "---" >> "$outfile"

# Task reviews section
printf '%s\n\n' "## Task Implementation Reviews" >> "$outfile"
jq -r '.task_reviews | to_entries[]? // empty | "### Task " + .key + "\n\n" + .value + "\n"' "$tmpfile" >> "$outfile"
printf '%s\n\n' "---" >> "$outfile"

# Documentation changes section
printf '%s\n\n' "## Documentation Changes" >> "$outfile"
jq -r '.docs_diff // ""' "$tmpfile" >> "$outfile"
printf '\n%s\n\n' "---" >> "$outfile"

# Draft entries section
printf '%s\n\n' "## Draft Entries with Context" >> "$outfile"
printf '%s\n' '```json' >> "$outfile"
jq '.draft_entries' "$tmpfile" >> "$outfile"
printf '%s\n' '```' >> "$outfile"

rm -f "$tmpfile"
echo "Saved context to $outfile"
```

### update-changelog-file

Prepend new changelog section to existing CHANGELOG.md file.
Inserts after the H1 header if present, otherwise prepends to file.

- type: shell
- stdin: ${format-both.results[0].response}

```shell command
changelog_file='${changelog_file}'
new_section=$(cat)

if [ -f "$changelog_file" ]; then
  if head -1 "$changelog_file" | grep -q '^# '; then
    { head -1 "$changelog_file"; echo ""; printf '%s\n' "$new_section"; tail -n +2 "$changelog_file"; } > /tmp/changelog_new
  else
    { printf '%s\n' "$new_section"; cat "$changelog_file"; } > /tmp/changelog_new
  fi
  mv /tmp/changelog_new "$changelog_file"
else
  { echo "# Changelog"; echo ""; printf '%s\n' "$new_section"; } > "$changelog_file"
fi

echo "Updated $changelog_file"
```

### update-mintlify-file

Prepend Update component to Mintlify changelog.mdx file.
Inserts after the YAML frontmatter if present.

- type: shell
- stdin: ${format-both.results[1].response}

```shell command
mintlify_file='${mintlify_file}'
new_section=$(cat)

# Skip if no mintlify file specified
if [ -z "$mintlify_file" ]; then
  echo "Skipped mintlify (no file specified)"
  exit 0
fi

if [ -f "$mintlify_file" ]; then
  # Find the line after the frontmatter (after second ---)
  frontmatter_end=$(awk '/^---$/{c++; if(c==2){print NR; exit}}' "$mintlify_file")
  if [ -n "$frontmatter_end" ]; then
    { head -n "$frontmatter_end" "$mintlify_file"; echo ""; printf '%s\n' "$new_section"; tail -n +$((frontmatter_end + 1)) "$mintlify_file"; } > /tmp/mintlify_new
  else
    { printf '%s\n' "$new_section"; echo ""; cat "$mintlify_file"; } > /tmp/mintlify_new
  fi
  mv /tmp/mintlify_new "$mintlify_file"
else
  # Create new file with frontmatter
  { echo '---'; echo 'title: "Changelog"'; echo 'description: "Product updates and announcements"'; echo 'icon: "clock"'; echo 'rss: true'; echo '---'; echo ""; printf '%s\n' "$new_section"; } > "$mintlify_file"
fi

echo "Updated $mintlify_file"
```

### create-summary

Create release summary for CLI output showing entry counts and files updated.

- type: shell

```yaml stdin
entries: ${prepare-context.stdout}
skipped: ${filter-and-format.stdout.skipped}
task_reviews: ${get-task-reviews.stdout}
```

```shell command
version=$(printf '%s' '${compute-next-version.stdout}' | tr -d '\n')
bump=$(printf '%s' '${compute-bump-type.stdout}' | tr -d '\n')
date=$(printf '%s' '${get-dates.stdout.iso}' | tr -d '\n')
changelog='${changelog_file}'
mintlify='${mintlify_file}'
releases_dir='${releases_dir}'

# Capture stdin to temp file
tmpfile=$(mktemp)
cat > "$tmpfile"

# Count items
user_facing=$(jq '.entries | length' "$tmpfile")
skipped=$(jq '.skipped | length' "$tmpfile")
task_count=$(jq '.task_reviews | keys | length' "$tmpfile")
rm -f "$tmpfile"

printf '## Release Summary\n\n'
printf 'Version: %s (%s)\n' "$version" "$bump"
printf 'Date: %s\n\n' "$date"
printf '%s\n' "$changelog"
printf '  %d user-facing entries\n\n' "$user_facing"
if [ -n "$mintlify" ]; then
  printf '%s\n' "$mintlify"
  printf '  Mintlify format (same entries)\n\n'
fi
printf '%s/%s-context.md\n' "$releases_dir" "$version"
printf '  %d skipped changes (for verification)\n' "$skipped"
printf '  %d task reviews\n' "$task_count"
```

## Outputs

### summary

Release summary showing entry counts and file locations.

- source: ${create-summary.stdout}

### suggested_version

Suggested next version based on semantic versioning analysis of changes.

- source: ${compute-next-version.stdout}

### markdown_section

Markdown changelog section ready for inclusion in CHANGELOG.md.

- source: ${format-both.results[0].response}

### mintlify_section

Mintlify Update component for docs/changelog.mdx.

- source: ${format-both.results[1].response}

### context_file

Path to release context file containing full verification data.

- source: ${save-release-context.stdout}
