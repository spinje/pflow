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
git describe --tags --abbrev=0 2>/dev/null || echo 'v0.0.0'
```

### resolve-tag

Use provided tag or default to latest.

- type: code
- inputs:
    since_tag: ${since_tag}
    latest_tag: ${get-latest-tag.stdout}

```python code
since_tag: str
latest_tag: str

result: str = since_tag.strip() if since_tag.strip() else latest_tag.strip()
```

### get-docs-diff

Get documentation changes since tag, grouped by file with commit refs.
Excludes changelog.mdx itself to avoid circular references.

- type: code
- inputs:
    tag: ${resolve-tag.result}

```python code
tag: str

import subprocess

diff_output = subprocess.run(
    ['git', 'diff', f'{tag}..HEAD', '--name-only', '--', 'docs/'],
    capture_output=True, text=True
).stdout
files = [
    f for f in diff_output.strip().split('\n')
    if f and 'changelog.mdx' not in f
]

sections = []
for file in files:
    commits = subprocess.run(
        ['git', 'log', f'{tag}..HEAD', '--oneline', '--', file],
        capture_output=True, text=True
    ).stdout.strip().replace('\n', ', ')

    diff = subprocess.run(
        ['git', 'diff', f'{tag}..HEAD', '--', file],
        capture_output=True, text=True
    ).stdout
    change_lines = [
        line for line in diff.split('\n')
        if line.startswith(('+', '-')) and not line.startswith(('+++', '---'))
    ][:50]

    sections.append(
        f'## {file}\nCommits: {commits}\nChanges:\n' + '\n'.join(change_lines)
    )

result: str = '\n\n'.join(sections)
```

### get-recent-updates

Get last 2 Update blocks from Mintlify changelog as style reference for
the LLM generating the Mintlify format output.

- type: code
- inputs:
    mintlify_file: ${mintlify_file}

```python code
mintlify_file: str

import re
from pathlib import Path

path = Path(mintlify_file)
if not path.exists():
    updates_text = ''
else:
    content = path.read_text()
    updates = re.findall(r'<Update.*?</Update>', content, re.DOTALL)
    updates_text = '\n\n'.join(updates[:2])

result: str = updates_text
```

### get-commits-enriched

Fetch commits since tag with PR metadata, file paths, and task numbers.
Joins commit messages with GitHub PR data for rich classification context.

- type: code
- inputs:
    tag: ${resolve-tag.result}
- timeout: 60

```python code
tag: str

import subprocess, json, re

repo = subprocess.run(
    ['gh', 'repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'],
    capture_output=True, text=True, check=True
).stdout.strip()

log_out = subprocess.run(
    ['git', 'log', '--first-parent', f'{tag}..HEAD', '--format=%H|%s'],
    capture_output=True, text=True
).stdout
commits = []
for line in log_out.strip().split('\n'):
    if not line:
        continue
    hash_val, msg = line.split('|', 1)
    commits.append({'hash': hash_val, 'commit_message': msg})

file_log = subprocess.run(
    ['git', 'log', '--first-parent', f'{tag}..HEAD', '--format=HASH:%H', '--name-only'],
    capture_output=True, text=True
).stdout
file_changes: dict = {}
current_hash = None
for line in file_log.strip().split('\n'):
    if line.startswith('HASH:'):
        current_hash = line[5:]
    elif line.strip() and current_hash:
        file_changes.setdefault(current_hash, []).append(line.strip())

pr_out = subprocess.run(
    ['gh', 'pr', 'list', '--state', 'merged', '--limit', '200',
     '--json', 'number,title,body'],
    capture_output=True, text=True
).stdout
prs = json.loads(pr_out) if pr_out.strip() else []
pr_by_num = {pr['number']: pr for pr in prs}

for c in commits:
    h, msg = c['hash'], c['commit_message']
    c['files_changed'] = ', '.join(file_changes.get(h, []))
    c['pr_number'] = None
    c['pr_title'] = ''
    c['pr_body'] = ''
    c['pr_link'] = ''
    c['pr_summary'] = ''
    c['is_merge'] = False
    c['task_number'] = None

    task_m = re.search(r'[Tt]ask[- ]?(\d+)', msg)
    if task_m:
        c['task_number'] = int(task_m.group(1))

    merge_m = re.match(r'^Merge pull request #(\d+)', msg)
    squash_m = re.search(r'\(#(\d+)\)', msg)

    if merge_m:
        pr_num = int(merge_m.group(1))
        pr = pr_by_num.get(pr_num, {})
        body = pr.get('body', '') or ''
        c.update({
            'pr_number': pr_num,
            'pr_title': pr.get('title', ''),
            'pr_body': body,
            'pr_link': f'https://github.com/{repo}/pull/{pr_num}',
            'is_merge': True,
        })
        body_task = re.search(r'[Tt]ask[- _]?(\d+)', body)
        if body_task:
            c['task_number'] = int(body_task.group(1))
    elif squash_m:
        pr_num = int(squash_m.group(1))
        c['pr_number'] = pr_num
        c['pr_link'] = f'https://github.com/{repo}/pull/{pr_num}'

    body = c['pr_body']
    if body:
        sections = body.split('\n## ')
        summaries = [s for s in sections if s.startswith('Summary')]
        if summaries:
            c['pr_summary'] = '\n\n'.join(summaries[0].split('\n\n')[:2])[:800]

result: list = commits
```

### get-task-reviews

Read task-review.md files for referenced tasks to provide implementation
context for accurate changelog entry refinement.

- type: code
- inputs:
    commits: ${get-commits-enriched.result}

```python code
commits: list

from pathlib import Path

task_nums = sorted({
    c['task_number'] for c in commits
    if c.get('task_number') is not None
})

reviews = {}
for num in task_nums:
    path = Path(f'.taskmaster/tasks/task_{num}/task-review.md')
    if path.exists():
        content = path.read_text().strip()
        if content:
            reviews[str(num)] = content

result: dict = reviews
```

### analyze-commits

Classify each commit as user-facing or internal based on commit message,
PR data, and file paths.

- type: llm

```yaml batch
items: ${get-commits-enriched.result}
parallel: true
max_concurrent: 40
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

- type: code
- inputs:
    results: ${analyze-commits.results}

```python code
results: list

included = []
skipped = []
for i, entry in enumerate(results):
    response = entry.get('response')
    if not response or not isinstance(response, str):
        continue
    if response.startswith('SKIP'):
        raw = response.split(':', 1)[1].strip() if ':' in response else response
        skipped.append(raw)
    elif response.strip():
        included.append({'index': i, 'response': response})

result: dict = {'included': included, 'skipped': skipped}
```

### prepare-context

Join draft entries with original commit context for the refinement step.

- type: code
- inputs:
    included: ${filter-and-format.result.included}
    commits: ${get-commits-enriched.result}

```python code
included: list
commits: list

entries = []
for entry in included:
    idx = entry['index']
    commit = commits[idx] if idx < len(commits) else {}
    files = commit.get('files_changed', '')
    file_list = [f.strip() for f in files.split(',') if f.strip()] if files else []
    if len(file_list) > 5:
        files_display = ', '.join(file_list[:5]) + f' ... and {len(file_list) - 5} more files'
    else:
        files_display = ', '.join(file_list)

    entries.append({
        'draft': entry['response'],
        'index': entry['index'],
        'context': {
            'commit_message': commit.get('commit_message', ''),
            'task_number': commit.get('task_number'),
            'files_changed': files_display,
            'pr_title': commit.get('pr_title', ''),
            'pr_body': commit.get('pr_body', ''),
            'pr_link': commit.get('pr_link', ''),
            'pr_number': commit.get('pr_number'),
        }
    })

result: list = entries
```

### compute-version

Determine semver bump type, calculate next version, and get formatted dates.
Combines bump analysis, version arithmetic, and date formatting in one step.

- type: code
- inputs:
    entries: ${prepare-context.result}
    current_tag: ${resolve-tag.result}

```python code
entries: list
current_tag: str

from datetime import datetime

drafts = [e['draft'] for e in entries]
has_breaking = any(d.startswith(('Removed', 'Changed')) for d in drafts)
has_features = any(d.startswith('Added') for d in drafts)

if has_breaking:
    bump_type = 'major'
elif has_features:
    bump_type = 'minor'
else:
    bump_type = 'patch'

version = current_tag.lstrip('v')
major, minor, patch_num = (int(x) for x in version.split('.'))

if bump_type == 'major':
    next_version = f'v{major + 1}.0.0'
elif bump_type == 'minor':
    next_version = f'v{major}.{minor + 1}.0'
else:
    next_version = f'v{major}.{minor}.{patch_num + 1}'

now = datetime.now()
result: dict = {
    'bump_type': bump_type,
    'next_version': next_version,
    'date_iso': now.strftime('%Y-%m-%d'),
    'date_month_year': now.strftime('%B %Y'),
}
```

### format-both

Refine and format changelog in two parallel formats: standard markdown
for CHANGELOG.md and Mintlify Update component for docs/changelog.mdx.

- type: llm

```yaml batch
items:
  - format: markdown
    prompt: "Refine and format these changelog entries as a markdown section for CHANGELOG.md.\n\n## Input\nVersion: ${compute-version.result.next_version}\nDate: ${compute-version.result.date_iso}\n\n## Draft Entries with Context\nEach entry has a `draft` field and a `context.pr_link` field with the full GitHub URL.\n${prepare-context.result}\n\n## Task Reviews (for accuracy)\n${get-task-reviews.result}\n\n## Documentation Changes (for parameter accuracy)\n${get-docs-diff.result}\n\n## Refinement Tasks\n1. Merge duplicates \u2192 combine PR links\n2. Standardize verbs: Allow\u2192Added, Enable\u2192Added, Update\u2192Changed/Improved\n3. Sort by: Removed > Changed > Added > Fixed > Improved\n4. Use docs diff for accurate parameter names\n5. Use task reviews for accurate feature descriptions\n\n## Output Format\n## v1.0.0 (2026-01-04)\n\n- Removed X [#10](https://github.com/owner/repo/pull/10)\n- Changed Y [#11](https://github.com/owner/repo/pull/11)\n- Added Z [#12](https://github.com/owner/repo/pull/12), [#13](https://github.com/owner/repo/pull/13)\n- Fixed W [#14](https://github.com/owner/repo/pull/14)\n\n## Rules\n- Use version and date exactly as provided\n- Each entry as bullet with `- `\n- CRITICAL: Use the FULL pr_link URL from context, not just the PR number\n- Format: [#N](full_url) where full_url is from context.pr_link\n- Combine PR links when merging duplicates\n- Start with ## - no code fences\n- Output ONLY the markdown section"
  - format: mintlify
    prompt: "Generate a Mintlify changelog <Update> component.\n\n## Input\nVersion: ${compute-version.result.next_version}\nMonth/Year: ${compute-version.result.date_month_year}\nBump Type: ${compute-version.result.bump_type}\n\n## Draft Entries\n${prepare-context.result}\n\n## Task Reviews\n${get-task-reviews.result}\n\n## Documentation Changes\n${get-docs-diff.result}\n\n## Style Reference (match this format)\n${get-recent-updates.result}\n\n## Required Format\nYou MUST output exactly this structure (with your content):\n\n<Update label=\"MONTH YEAR\" description=\"VERSION\" tags={[\"New releases\", \"Bug fixes\"]}>\n  ## Theme Title\n\n  Brief description.\n\n  **Highlights**\n  - Feature one\n  - Feature two\n\n  ## Another Theme\n\n  Description.\n\n  **Highlights**\n  - Feature three\n</Update>\n\n## Tasks\n1. Group entries into 2-4 themes\n2. Merge duplicates\n3. Standardize verbs (Allow\u2192Added, Enable\u2192Added)\n4. No PR links (user-facing changelog)\n5. Add <Accordion title=\"Breaking changes\"> if bump type is major\n\n## CRITICAL\n- Output ONLY the <Update>...</Update> component\n- First character must be <\n- Last characters must be </Update>\n- NO JSON, NO code fences, NO explanations"
parallel: true
```

```prompt
${item.prompt}
```

### save-release-context

Save full context to version-named file for AI agents and verification.
Includes changelog, skipped entries, task reviews, and documentation changes.

- type: code
- inputs:
    changelog: ${format-both.results[0].response}
    skipped: ${filter-and-format.result.skipped}
    task_reviews: ${get-task-reviews.result}
    docs_diff: ${get-docs-diff.result}
    draft_entries: ${prepare-context.result}
    next_version: ${compute-version.result.next_version}
    date_iso: ${compute-version.result.date_iso}
    releases_dir: ${releases_dir}

````python code
changelog: str
skipped: list
task_reviews: dict
docs_diff: str
draft_entries: list
next_version: str
date_iso: str
releases_dir: str

import json
from pathlib import Path

Path(releases_dir).mkdir(parents=True, exist_ok=True)
outfile = Path(releases_dir) / f'{next_version}-context.md'

skipped_lines = '\n'.join(f'- {s}' for s in skipped)
review_sections = '\n'.join(
    f'### Task {k}\n\n{v}\n' for k, v in task_reviews.items()
)
json_fence = '`' * 3

parts = [
    f'# {next_version} Release Context',
    '',
    f'Generated: {date_iso}',
    'This file contains implementation context for AI agents and release verification.',
    '',
    '---',
    '',
    '## Changelog',
    '',
    changelog,
    '',
    '---',
    '',
    '## Skipped Changes (Verification)',
    '',
    'Review these to ensure nothing was incorrectly classified as internal:',
    '',
    skipped_lines,
    '',
    '---',
    '',
    '## Task Implementation Reviews',
    '',
    review_sections,
    '---',
    '',
    '## Documentation Changes',
    '',
    docs_diff,
    '',
    '---',
    '',
    '## Draft Entries with Context',
    '',
    json_fence + 'json',
    json.dumps(draft_entries, indent=2),
    json_fence,
]

outfile.write_text('\n'.join(parts))
result: str = f'Saved context to {outfile}'
````

### update-changelog-file

Prepend new changelog section to existing CHANGELOG.md file.
Inserts after the H1 header if present, otherwise prepends to file.

- type: code
- inputs:
    new_section: ${format-both.results[0].response}
    changelog_file: ${changelog_file}

```python code
new_section: str
changelog_file: str

from pathlib import Path

path = Path(changelog_file)
if path.exists():
    existing = path.read_text()
    lines = existing.split('\n', 1)
    if lines[0].startswith('# '):
        rest = lines[1] if len(lines) > 1 else ''
        content = lines[0] + '\n\n' + new_section + '\n' + rest
    else:
        content = new_section + '\n' + existing
else:
    content = '# Changelog\n\n' + new_section + '\n'

path.write_text(content)
result: str = f'Updated {changelog_file}'
```

### update-mintlify-file

Prepend Update component to Mintlify changelog.mdx file.
Inserts after the YAML frontmatter if present.

- type: code
- inputs:
    new_section: ${format-both.results[1].response}
    mintlify_file: ${mintlify_file}

```python code
new_section: str
mintlify_file: str

from pathlib import Path

if not mintlify_file:
    msg = 'Skipped mintlify (no file specified)'
else:
    path = Path(mintlify_file)
    if path.exists():
        existing = path.read_text()
        lines = existing.split('\n')
        fence_count = 0
        insert_after = -1
        for i, line in enumerate(lines):
            if line.strip() == '---':
                fence_count += 1
                if fence_count == 2:
                    insert_after = i
                    break

        if insert_after >= 0:
            before = '\n'.join(lines[:insert_after + 1])
            after = '\n'.join(lines[insert_after + 1:])
            content = before + '\n\n' + new_section + '\n' + after
        else:
            content = new_section + '\n\n' + existing
    else:
        content = (
            '---\ntitle: "Changelog"\ndescription: "Product updates and announcements"\n'
            'icon: "clock"\nrss: true\n---\n\n' + new_section + '\n'
        )

    path.write_text(content)
    msg = f'Updated {mintlify_file}'

result: str = msg
```

### create-summary

Create release summary for CLI output showing entry counts and files updated.

- type: code
- inputs:
    entries: ${prepare-context.result}
    skipped: ${filter-and-format.result.skipped}
    task_reviews: ${get-task-reviews.result}
    next_version: ${compute-version.result.next_version}
    bump_type: ${compute-version.result.bump_type}
    date_iso: ${compute-version.result.date_iso}
    changelog_file: ${changelog_file}
    mintlify_file: ${mintlify_file}
    releases_dir: ${releases_dir}

```python code
entries: list
skipped: list
task_reviews: dict
next_version: str
bump_type: str
date_iso: str
changelog_file: str
mintlify_file: str
releases_dir: str

lines = [
    '## Release Summary\n',
    f'Version: {next_version} ({bump_type})',
    f'Date: {date_iso}\n',
    changelog_file,
    f'  {len(entries)} user-facing entries\n',
]

if mintlify_file:
    lines.append(mintlify_file)
    lines.append('  Mintlify format (same entries)\n')

lines.append(f'{releases_dir}/{next_version}-context.md')
lines.append(f'  {len(skipped)} skipped changes (for verification)')
lines.append(f'  {len(task_reviews)} task reviews')

result: str = '\n'.join(lines)
```

## Outputs

### summary

Release summary showing entry counts and file locations.

- source: ${create-summary.result}

### suggested_version

Suggested next version based on semantic versioning analysis of changes.

- source: ${compute-version.result.next_version}

### markdown_section

Markdown changelog section ready for inclusion in CHANGELOG.md.

- source: ${format-both.results[0].response}

### mintlify_section

Mintlify Update component for docs/changelog.mdx.

- source: ${format-both.results[1].response}

### context_file

Path to release context file containing full verification data.

- source: ${save-release-context.result}
