# Generate Changelog

Automatically produce a versioned changelog from your git history. Run it
before a release to get three outputs: a CHANGELOG.md entry with PR links,
a Mintlify changelog component for your docs site, and a release context
file for pre-release verification.

The workflow analyzes commits since your last tag, uses an LLM to separate
user-facing changes from internal work, computes a semantic version bump,
and formats the results in both formats simultaneously.

**Requirements**: Git repository with at least one tag, GitHub CLI (`gh`)
authenticated, and an LLM configured via `llm`.

**Usage**

```bash
# Generate changelog since latest tag
pflow examples/real-workflows/generate-changelog/workflow.pflow.md

# Specify starting tag
pflow examples/real-workflows/generate-changelog/workflow.pflow.md since_tag=v0.5.0

# Skip Mintlify output
pflow examples/real-workflows/generate-changelog/workflow.pflow.md mintlify_file=""

# Custom output paths
pflow examples/real-workflows/generate-changelog/workflow.pflow.md \
  changelog_file=RELEASE_NOTES.md releases_dir=release-notes
```

**Limitations**

* LLM may occasionally misclassify changes — review the context file
* Cost scales with commit count (~$0.003 per commit for classification)
* Task reviews require `.taskmaster/tasks/task_N/task-review.md` structure
* Docs diff requires a `docs/` directory in the repository

## Inputs

### since_tag

Starting tag for the changelog range. When left empty, the workflow
automatically uses the most recent git tag. Set this to generate a
changelog for a specific range, e.g. `since_tag=v0.5.0`.

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

Directory for release context files. Each run creates a
`{version}-context.md` containing the changelog, skipped changes,
task reviews, docs diff, and raw draft entries for pre-release auditing.

- type: string
- required: false
- default: releases

## Steps

### get-latest-tag

Detect the most recent git tag to use as the changelog baseline.
Falls back to `v0.0.0` if no tags exist.

- type: shell

```shell command
git describe --tags --abbrev=0 2>/dev/null || echo 'v0.0.0'
```

### resolve-tag

Pick the starting tag for the changelog range: either the user-provided
`since_tag` or the auto-detected latest tag. Downstream nodes reference
this single resolved value.

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

Extract documentation file changes since the tag, grouped by file with
commit refs. The format LLM uses this to write accurate parameter names
and feature descriptions instead of guessing from commit messages alone.
Excludes changelog.mdx to avoid circular references.

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

Load the last 2 entries from the existing Mintlify changelog as a style
reference. The format LLM matches this tone and structure when generating
the new entry.

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

Build a rich context object for each commit in the tag range. Includes
PR titles and bodies (for understanding what changed), file paths (so
the classifier can identify internal-only changes like `.taskmaster/` or
`tests/`), and task numbers (to load implementation reviews). Uses
`--first-parent` to avoid duplicates from PR branch commits.

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

    # Fallback: extract task number from task-review.md in file paths
    if c['task_number'] is None:
        for f in file_changes.get(h, []):
            review_m = re.search(r'\.taskmaster/tasks/task_(\d+)/task-review\.md', f)
            if review_m:
                c['task_number'] = int(review_m.group(1))
                break

    body = c['pr_body']
    if body:
        sections = body.split('\n## ')
        summaries = [s for s in sections if s.startswith('Summary')]
        if summaries:
            c['pr_summary'] = '\n\n'.join(summaries[0].split('\n\n')[:2])[:800]

result: list = commits
```

### get-task-reviews

Load `task-review.md` files for any tasks referenced in commits or PRs.
These reviews contain implementation details, key decisions, and files
modified — giving the format LLM accurate context that goes beyond what
a commit message conveys.

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

Classify each commit as user-facing or internal. Runs in parallel across
all commits. Each call receives the commit message, PR data, and file
paths, and outputs either a draft changelog entry or SKIP with the
original message preserved for the verification file.

- type: llm

```yaml batch
items: ${get-commits-enriched.result}
parallel: true
max_concurrent: 70
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

Split the classification results into two lists: included entries
(user-facing drafts) and skipped entries (internal changes). The
included list carries the original array index so prepare-context can
rejoin each draft with its source commit.

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

Pair each draft changelog entry with its original commit context (PR
link, title, body, files, task number). The format LLM needs this to
merge duplicates, add correct PR links, and refine descriptions using
the full PR body rather than the one-line draft.

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

Determine the next version number. Entries starting with Removed/Changed
trigger a major bump, Added triggers minor, anything else is patch.
Also captures today's date in both ISO and human-readable formats for
the changelog headers.

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

Produce both output formats in parallel. Each receives the full context
(draft entries, task reviews, docs diff) and independently deduplicates,
sorts by verb (Removed > Changed > Added > Fixed > Improved), and
standardizes terminology. The markdown format includes PR links; the
Mintlify format groups entries into themes without links.

- type: llm

```yaml batch
items:
  - format: markdown
    prompt: |
      Refine and format these changelog entries as a markdown section
      for CHANGELOG.md.

      ## Input
      Version: ${compute-version.result.next_version}
      Date: ${compute-version.result.date_iso}

      ## Draft Entries with Context
      Each entry has a `draft` field and a `context.pr_link` field with
      the full GitHub URL.
      ${prepare-context.result}

      ## Task Reviews (for accuracy)
      ${get-task-reviews.result}

      ## Documentation Changes (for parameter accuracy)
      ${get-docs-diff.result}

      ## Refinement Tasks
      1. Merge duplicates → combine PR links
      2. Standardize verbs: Allow→Added, Enable→Added, Update→Changed/Improved
      3. Sort by: Removed > Changed > Added > Fixed > Improved
      4. Use docs diff for accurate parameter names
      5. Use task reviews for accurate feature descriptions

      ## Output Format
      ## v1.0.0 (2026-01-04)

      - Removed X [#10](https://github.com/owner/repo/pull/10)
      - Changed Y [#11](https://github.com/owner/repo/pull/11)
      - Added Z [#12](https://github.com/owner/repo/pull/12), [#13](https://github.com/owner/repo/pull/13)
      - Fixed W [#14](https://github.com/owner/repo/pull/14)

      ## Rules
      - Use version and date exactly as provided
      - Each entry as bullet with `- `
      - CRITICAL: Use the FULL pr_link URL from context, not just the PR number
      - Format: [#N](full_url) where full_url is from context.pr_link
      - Combine PR links when merging duplicates
      - Start with ## - no code fences
      - Output ONLY the markdown section
  - format: mintlify
    prompt: |
      Generate a Mintlify changelog <Update> component.

      ## Input
      Version: ${compute-version.result.next_version}
      Month/Year: ${compute-version.result.date_month_year}
      Bump Type: ${compute-version.result.bump_type}

      ## Draft Entries
      ${prepare-context.result}

      ## Task Reviews
      ${get-task-reviews.result}

      ## Documentation Changes
      ${get-docs-diff.result}

      ## Style Reference (match this format)
      ${get-recent-updates.result}

      ## Required Format
      You MUST output exactly this structure (with your content):

      <Update label="MONTH YEAR" description="VERSION" tags={["New releases", "Bug fixes"]}>
        ## Theme Title

        Brief description.

        **Highlights**
        - Feature one
        - Feature two

        ## Another Theme

        Description.

        **Highlights**
        - Feature three
      </Update>

      ## Tasks
      1. Group entries into 2-4 themes
      2. Merge duplicates
      3. Standardize verbs (Allow→Added, Enable→Added)
      4. No PR links (user-facing changelog)
      5. Add <Accordion title="Breaking changes"> if bump type is major

      ## CRITICAL
      - Output ONLY the <Update>...</Update> component
      - First character must be <
      - Last characters must be </Update>
      - NO JSON, NO code fences, NO explanations
parallel: true
```

```prompt
${item.prompt}
```

### save-release-context

Write a release context file for pre-release verification. Contains five
sections: the rendered changelog, skipped changes to audit for
misclassification, task implementation reviews, documentation diffs, and
the raw draft entries with full commit context.

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
result: str = str(outfile)
````

### update-changelog-file

Prepend the new changelog section to the existing file. Inserts after
the H1 header if present, preserving all previous entries below.

> Writes a flat list sorted by verb (Removed, Changed, Added, Fixed,
> Improved), each entry with PR links. Duplicates merged and
> terminology standardized by the format-both LLM.

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
result: str = changelog_file
```

### update-mintlify-file

Prepend the new Update component to the Mintlify changelog. Inserts
after the YAML frontmatter, preserving all previous entries below.

> Writes a Mintlify `<Update>` component with entries grouped into 2-4
> themes, no PR links. Includes `<Accordion>` for breaking changes on
> major bumps.

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
    msg = mintlify_file

result: str = msg
```

### create-summary

Build the CLI output summary showing the version, bump type, and
created files with descriptions.

- type: code
- inputs:
    entries: ${prepare-context.result}
    skipped: ${filter-and-format.result.skipped}
    task_reviews: ${get-task-reviews.result}
    next_version: ${compute-version.result.next_version}
    bump_type: ${compute-version.result.bump_type}
    date_iso: ${compute-version.result.date_iso}
    changelog_path: ${update-changelog-file.result}
    mintlify_path: ${update-mintlify-file.result}
    context_path: ${save-release-context.result}

```python code
entries: list
skipped: list
task_reviews: dict
next_version: str
bump_type: str
date_iso: str
changelog_path: str
mintlify_path: str
context_path: str

lines = [
    '## Release Summary\n',
    f'Version: {next_version} ({bump_type})',
    f'Date: {date_iso}\n',
    'Created files:',
    f'  {changelog_path}',
    f'    {len(entries)} entries with PR links (sorted: Removed > Changed > Added > Fixed > Improved)',
]

if mintlify_path:
    lines.append(f'  {mintlify_path}')
    lines.append('    Same entries as Mintlify <Update> component, grouped by theme')

lines.append(f'  {context_path}')
lines.append(f'    {len(skipped)} skipped changes + {len(task_reviews)} task reviews — review before committing')

result: str = '\n'.join(lines)
```

## Outputs

### summary

Release summary displayed after execution. Shows version, bump type,
and created files with descriptions.

- source: ${create-summary.result}

### suggested_version

Next version from semantic versioning rules: any Removed or Changed
entry triggers major, any Added triggers minor, otherwise patch.

- source: ${compute-version.result.next_version}

### changelog_file

Path to the updated changelog file.

- source: ${update-changelog-file.result}

### mintlify_file

Path to the updated Mintlify changelog file. Empty string if skipped.

- source: ${update-mintlify-file.result}

### context_file

Path to the release context file for pre-release verification.

- source: ${save-release-context.result}
