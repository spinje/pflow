# Generate Changelog (Simple)

Generate a changelog from git history with PR enrichment and LLM classification.
Classifies commits as user-facing or internal, computes semantic version bumps,
and formats a proper changelog entry with PR links.

## Inputs

### repo

Repository in owner/repo format (e.g., 'owner/repo'). Defaults to current git remote.

- type: string
- required: false
- default: ""

### changelog_path

Path to the changelog file to prepend the new entry to.

- type: string
- required: false
- default: CHANGELOG.md

## Steps

### resolve-repo

Get repo from input or detect from git remote origin URL.

- type: shell

```shell command
if [ -n '${repo}' ]; then printf '%s' '${repo}'; else git remote get-url origin 2>/dev/null | sed -E 's|.*github.com[:/]||' | sed 's/.git$//' | tr -d '\n'; fi
```

### get-latest-tag

Get the most recent git tag to determine changelog range.

- type: shell

```shell command
tag=$(git describe --tags --abbrev=0 2>/dev/null || echo 'v0.0.0'); printf '{"latest_tag": {"name": "%s"}}' "$tag"
```

### get-commits

Get commits since last tag using --first-parent to avoid PR merge duplicates.

- type: shell

```shell command
git log ${get-latest-tag.stdout.latest_tag.name}..HEAD --first-parent --format='%H|%h|%s|%an|%aI' | while IFS='|' read -r sha short subj author date; do jq -n --arg sha "$sha" --arg short "$short" --arg subj "$subj" --arg author "$author" --arg date "$date" '{sha: $sha, short_sha: $short, subject: $subj, author: $author, date: $date}'; done | jq -s '.'
```

### get-today

Get today's date for changelog header.

- type: shell

```shell command
date +%Y-%m-%d
```

### get-docs-diff

Get documentation changes since last tag for accuracy context.

- type: shell

```shell command
git diff ${get-latest-tag.stdout.latest_tag.name}..HEAD -- docs/ 2>/dev/null | head -200 || echo 'No docs changes'
```

### extract-pr-info

Extract PR numbers from commit messages and prepare API requests.

- type: shell
- stdin: ${get-commits.stdout}

```shell command
jq '[.[] | {sha: .sha, short_sha: .short_sha, subject: .subject, author: .author, date: .date, pr_number: ((.subject | capture("#(?<num>[0-9]+)") // {num: null}).num | tonumber? // null)}]'
```

### filter-commits-with-prs

Filter to only commits that have PR numbers for GitHub API enrichment.

- type: shell
- stdin: ${extract-pr-info.stdout}

```shell command
jq '[.[] | select(.pr_number)]'
```

### fetch-pr-data

Fetch PR details from GitHub using gh CLI for commits with PR references.
Runs in parallel for speed, continues on errors (private repos, rate limits).

- type: shell

```yaml batch
items: ${filter-commits-with-prs.stdout}
as: commit
parallel: true
max_concurrent: 30
error_handling: continue
```

```shell command
gh pr view ${commit.pr_number} --repo '${resolve-repo.stdout}' --json title,body,url 2>/dev/null || echo '{"title": null, "body": null, "url": null}'
```

### get-file-changes

Get list of changed files for each commit to help classify user-facing vs internal.

- type: shell

```yaml batch
items: ${extract-pr-info.stdout}
as: commit
parallel: true
max_concurrent: 40
```

```shell command
git diff-tree --no-commit-id --name-only -r ${commit.sha} 2>/dev/null | jq -R -s 'split("\n") | map(select(length > 0))'
```

### combine-commit-data

Merge commit info, PR data, and file changes. Extract PR summary for classification.

- type: shell

```yaml stdin
commits: ${extract-pr-info.stdout}
pr_commits: ${filter-commits-with-prs.stdout}
pr_results: ${fetch-pr-data.results}
file_results: ${get-file-changes.results}
```

```shell command
jq '([.pr_commits, .pr_results] | transpose | map({key: (.[0].pr_number | tostring), value: (.[1].stdout | if type == "string" then fromjson else . end)}) | from_entries) as $pr_map | [range(0; .commits | length) as $i | .commits[$i] as $c | ($pr_map[$c.pr_number | tostring] // null) as $pr | { commit: $c, pr_full: $pr, pr_title: ($pr.title // null), pr_summary: (($pr.body // "") | split("## ")[0:2] | join(" ") | gsub("[\\n\\r]+"; " ") | .[0:500]), pr_url: ($pr.url // null), files: (.file_results[$i].stdout // []) }]'
```

### classify-commits

Classify each commit as user-facing or internal based on content and file paths.

- type: llm

```yaml batch
items: ${combine-commit-data.stdout}
as: entry
parallel: true
max_concurrent: 100
```

````prompt
Classify this commit as user-facing or internal.

Commit: ${entry.commit.subject}
PR Title: ${entry.pr_title}
PR Summary: ${entry.pr_summary}
Files Changed: ${entry.files}

Classification rules:
- Internal: changes only in tests/, docs/, .taskmaster/, internal tooling, CI/CD, refactoring with no behavior change
- User-facing: new features, bug fixes, API changes, CLI changes, anything users would notice

Respond with ONLY a JSON object:
{"classification": "user-facing" or "internal", "category": "Added" or "Changed" or "Fixed" or "Removed" or "Improved", "summary": "one-line description for changelog"}
````

### split-by-classification

Split into user-facing and internal entries, joined with full PR data.

- type: shell

```yaml stdin
classifications: ${classify-commits.results}
original_data: ${combine-commit-data.stdout}
```

```shell command
jq '{ user_facing: [range(0; .original_data | length) as $i | select(.classifications[$i].response.classification == "user-facing") | { classification: .classifications[$i].response, commit: .original_data[$i].commit, pr_title: .original_data[$i].pr_title, pr_body: .original_data[$i].pr_full.body, pr_url: .original_data[$i].pr_url, files: .original_data[$i].files }], internal: [range(0; .original_data | length) as $i | select(.classifications[$i].response.classification == "internal") | { classification: .classifications[$i].response, commit: .original_data[$i].commit }] }'
```

### compute-version-bump

Determine version bump from categories: Removed/Changed=major, Added=minor, else patch.

- type: shell
- stdin: ${split-by-classification.stdout.user_facing}

```shell command
jq -r 'map(.classification.category) | if any(. == "Removed" or . == "Changed") then "major" elif any(. == "Added") then "minor" else "patch" end'
```

### compute-new-version

Apply version bump to previous tag to get new version number.

- type: shell

```yaml stdin
prev_tag: ${get-latest-tag.stdout.latest_tag.name}
bump: ${compute-version-bump.stdout}
```

```shell command
jq -r '(.prev_tag | ltrimstr("v") | split(".") | map(tonumber)) as [$major, $minor, $patch] | (.bump | gsub("[\\n\\r]"; "")) as $b | if $b == "major" then "v\($major + 1).0.0" elif $b == "minor" then "v\($major).\($minor + 1).0" else "v\($major).\($minor).\($patch + 1)" end'
```

### format-changelog

Format classified entries into changelog markdown grouped by category.

- type: shell

```yaml stdin
entries: ${split-by-classification.stdout.user_facing}
version: ${compute-new-version.stdout}
date: ${get-today.stdout}
```

```shell command
jq -r '["Removed", "Changed", "Added", "Fixed", "Improved"] as $order | .entries as $entries | .version as $version | .date as $date | ($entries | group_by(.classification.category) | map({key: .[0].classification.category, value: .}) | from_entries) as $by_cat | "## [" + $version + "] - " + $date + "\n\n" + ($order | map($by_cat[.] as $items | if $items then "### " + . + "\n" + ($items | map("- " + .classification.summary + (if .pr_url then " ([#" + (.pr_url | split("/") | last) + "](" + .pr_url + "))" else "" end)) | join("\n")) else empty end) | join("\n\n"))'
```

### generate-context

Assemble context file for verification before committing changes.

- type: shell

```yaml stdin
changelog: ${format-changelog.stdout}
user_facing: ${split-by-classification.stdout.user_facing}
internal: ${split-by-classification.stdout.internal}
docs_diff: ${get-docs-diff.stdout}
```

```shell command
jq -r '(.user_facing | if type == "string" then fromjson else . end) as $uf | (.internal | if type == "string" then fromjson else . end) as $int | "# Release Context\n\n## Generated Changelog\n\n" + .changelog + "\n\n## User-Facing Entries (Full Context)\n\n" + ($uf | map("### " + .commit.subject + "\n\n**Category:** " + .classification.category + "\n**Summary:** " + .classification.summary + "\n**PR:** " + (.pr_url // "N/A") + "\n**Files:** " + (.files | tostring) + "\n\n" + if .pr_body then "<details>\n<summary>PR Body</summary>\n\n" + .pr_body + "\n</details>" else "" end) | join("\n\n---\n\n")) + "\n\n## Skipped Changes (Internal)\n\n" + ($int | map("- " + .commit.subject) | join("\n")) + "\n\n## Documentation Changes\n\n```diff\n" + .docs_diff + "\n```\n\n## Verification Checklist\n\n- [ ] Version number is correct\n- [ ] No user-facing changes missed\n- [ ] PR links are correct\n- [ ] Category assignments are accurate"'
```

### save-context

Save context file for verification before committing.

- type: write-file
- file_path: releases/${compute-new-version.stdout}-context.md
- content: ${generate-context.stdout}

### save-changelog

Prepend new changelog entry to existing changelog file.

- type: shell
- stdin: ${format-changelog.stdout}

```shell command
changelog=$(cat); if [ -f '${changelog_path}' ]; then { echo "$changelog"; echo ''; cat '${changelog_path}'; } > /tmp/changelog.tmp && mv /tmp/changelog.tmp '${changelog_path}'; else echo "$changelog" > '${changelog_path}'; fi && echo 'Updated: ${changelog_path}'
```

### output-summary

Output summary of what was generated including entry counts and files updated.

- type: shell

```yaml stdin
user_facing: ${split-by-classification.stdout.user_facing}
internal: ${split-by-classification.stdout.internal}
version: ${compute-new-version.stdout}
bump: ${compute-version-bump.stdout}
```

```shell command
jq -r '(.version | gsub("[\\n\\r]"; "")) as $v | (.bump | gsub("[\\n\\r]"; "")) as $b | (.internal | if type == "string" then fromjson else . end) as $int | (.user_facing | if type == "string" then fromjson else . end) as $uf | "\n=== Changelog Generated ===\nVersion: " + $v + "\nVersion bump: " + $b + "\nUser-facing entries: " + ($uf | length | tostring) + "\nSkipped (internal): " + ($int | length | tostring) + "\n\nFiles updated:\n- ${changelog_path}\n- releases/" + $v + "-context.md\n\nReview the context file before committing."'
```

## Outputs

### summary

Summary of changelog generation including entry counts and file locations.

- source: ${output-summary.stdout}

### changelog

Generated changelog markdown section ready for inclusion.

- source: ${format-changelog.stdout}

### version

Computed new version number based on semantic versioning.

- source: ${compute-new-version.stdout}

### version_bump

Computed version bump type (major/minor/patch) based on change categories.

- source: ${compute-version-bump.stdout}

### internal_entries

Internal/skipped entries for reference and verification.

- source: ${split-by-classification.stdout.internal}
