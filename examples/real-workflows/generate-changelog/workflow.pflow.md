# Generate Changelog

Automatically produce a versioned changelog from your git history. Run it
before a release to get three outputs: a CHANGELOG.md entry with PR links,
a Mintlify changelog component for your docs site, and a release context
file for pre-release verification.

This workflow generates pflow's own changelogs — it's the dogfooding
entry point invoked by the `/release` skill.

The workflow analyzes commits between two git refs, uses an LLM to separate
user-facing changes from internal work, determines the version (computed
from entries or extracted from a target tag), and formats the results in
both formats simultaneously.

**Requirements**: Git repository with at least one tag, GitHub CLI (`gh`)
authenticated, and an LLM configured via `llm`.

**Usage**

```bash
# Preview cost and plan without running LLMs or writing files
pflow examples/real-workflows/generate-changelog/workflow.pflow.md \
  is_major_release=false --dry-run

# Standard minor/patch release (auto-detects minor vs patch from entries)
pflow examples/real-workflows/generate-changelog/workflow.pflow.md is_major_release=false

# Major release (breaking changes, or declaratory e.g. v1.0.0)
pflow examples/real-workflows/generate-changelog/workflow.pflow.md is_major_release=true

# Specify starting tag
pflow examples/real-workflows/generate-changelog/workflow.pflow.md \
  is_major_release=false since_tag=v0.5.0

# Skip Mintlify output
pflow examples/real-workflows/generate-changelog/workflow.pflow.md \
  is_major_release=false mintlify_file=""

# Historical changelog for a specific tag range
pflow examples/real-workflows/generate-changelog/workflow.pflow.md \
  is_major_release=false since_tag=v0.5.0 to_ref=v0.6.0

# Custom output paths
pflow examples/real-workflows/generate-changelog/workflow.pflow.md \
  is_major_release=false changelog_file=RELEASE_NOTES.md releases_dir=release-notes
```

**Limitations**

* LLM may occasionally misclassify changes — review the context file
* Cost scales with commit count (~$0.003 per commit for classification)
* Task reviews require `.taskmaster/tasks/task_N/task-review.md` structure
* Docs diff requires a `docs/` directory in the repository
* Major bumps require explicit `is_major_release=true`. The LLM can
  never pick major — it's a human/agent decision. If breaking entries
  are detected but `is_major_release=false`, the workflow ships as
  minor and surfaces a prominent warning for review.
* Zero-commit ranges are not tested — LLM batch with 0 items may error
* `gh pr list --limit 200` is not date-scoped — very active repos may
  miss older merged PRs relevant to the tag range
* Every run writes to CHANGELOG.md, docs/changelog.mdx, and releases/
  (use `--dry-run` to preview cost/plan without side effects)

## Inputs

### since_tag

Starting tag for the changelog range. When left empty, the workflow
automatically uses the most recent git tag. Set this to generate a
changelog for a specific range, e.g. `since_tag=v0.5.0`.

- type: string
- required: false
- default: ""

### to_ref

Git ref for the end of the changelog range (tag, branch, or commit).
Defaults to HEAD for normal releases. Set to a tag like `v0.7.0` to
generate a historical changelog. When set to a tag, the version and
date are extracted from the tag instead of being computed.

- type: string
- required: false
- default: HEAD

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

### slack_channel

Slack channel for release notification. Posts a summary and the rendered
changelog entries after all files are written.

- type: string
- required: false
- default: releases

### is_major_release

Explicit decision on whether this is a major release. Required — the
LLM/classifier can never pick major; it must always be a human or
agent decision.

When `true`, the workflow bumps to the next major version (e.g.
v0.11.0 → v1.0.0, v1.4.2 → v2.0.0). Use this for releases with
breaking changes users must adapt to, or for declaratory stability
bumps like v1.0.0.

When `false`, the workflow auto-detects minor vs patch from entries
(Added → minor, else patch) and never bumps major. If breaking
entries are detected anyway, the release still ships but a prominent
warning is surfaced in the summary and release context file.

- type: boolean
- required: true

## Steps

### get-latest-tag

Detect the most recent git tag to use as the changelog baseline.
Falls back to `v0.0.0` if no tags exist.

- type: shell
- cache: false

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

### gather-commit-data

Build a rich context object for each commit in the tag range. Captures
the full commit message (`%B`), PR titles and bodies, file paths (so
the classifier can identify internal-only changes like `.taskmaster/`
or `tests/`), and task numbers. Uses `--first-parent` to avoid
duplicates from PR branch commits.

Timeout is raised above the 30s default because `gh pr list` over 200
merged PRs can be slow on active repos.

- type: code
- inputs:
    tag: ${resolve-tag.result}
    to_ref: ${to_ref}
- timeout: 60

```python code
tag: str
to_ref: str

import subprocess, json, re

repo = subprocess.run(
    ['gh', 'repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'],
    capture_output=True, text=True, check=True
).stdout.strip()

log_out = subprocess.run(
    ['git', 'log', '--first-parent', f'{tag}..{to_ref}', '--format=%H|%B%x00'],
    capture_output=True, text=True
).stdout
commits = []
for record in log_out.split('\0'):
    record = record.strip()
    if not record or '|' not in record:
        continue
    hash_val, msg = record.split('|', 1)
    commits.append({'hash': hash_val.strip(), 'commit_message': msg.strip()})

file_log = subprocess.run(
    ['git', 'log', '--first-parent', f'{tag}..{to_ref}', '--format=HASH:%H', '--name-only'],
    capture_output=True, text=True
).stdout
file_changes = {}
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

if not commits:
    raise ValueError(f'No commits found between {tag} and {to_ref} — check that both refs exist')

result: list = commits
```

### get-task-reviews

Load `task-review.md` files that were added or modified within the tag
range. Only reviews committed in this range belong to this release —
a commit mentioning a task number doesn't mean the review existed yet.
Reads content from the git tree at `to_ref` for correctness in
historical runs.

- type: code
- inputs:
    tag: ${resolve-tag.result}
    to_ref: ${to_ref}

```python code
tag: str
to_ref: str

import subprocess, re

diff_output = subprocess.run(
    ['git', 'diff', '--name-only', f'{tag}..{to_ref}', '--',
     '.taskmaster/tasks/'],
    capture_output=True, text=True
).stdout

reviews = {}
for line in diff_output.strip().split('\n'):
    if not line or 'task-review.md' not in line:
        continue
    m = re.search(r'task_(\d+)/task-review\.md', line)
    if not m:
        continue
    num = m.group(1)
    content = subprocess.run(
        ['git', 'show', f'{to_ref}:{line}'],
        capture_output=True, text=True
    ).stdout.strip()
    if content:
        reviews[num] = content

result: dict = reviews
```

### classify-commits

Classify each commit as user-facing or internal, and capture what changed.
Runs in parallel across all commits. Returns structured output —
`user_facing` (the include/skip decision), `entry` (a draft changelog line,
refined later by `render-changelogs`), and `reason` (a one-sentence audit
trail, especially for borderline calls).

The rubric lives in `./prompts/classify-commit.prompt.md`: static
instructions and few-shot examples first, the per-item `${item.*}` context
last. That ordering lets `prewarm: true` cache the shared rubric prefix
across the parallel batch. Prewarm is self-gating — it fires only when the
rendered prefix clears the chosen model's cache minimum (~1,024 tokens for
Sonnet and Gemini Flash; the rubric clears it on both) and is a no-op
otherwise.

- type: llm
- model: gemini/gemini-2.5-flash
- prewarm: true
- prompt: ./prompts/classify-commit.prompt.md

```yaml output_schema
type: object
properties:
  user_facing:
    type: boolean
  entry:
    type: string
  reason:
    type: string
required:
  - user_facing
  - reason
```

```yaml batch
items: ${gather-commit-data.result}
parallel: true
max_concurrent: 90
error_handling: continue
```

### split-classifications

Split the structured classification results into two lists: included entries
(user-facing drafts) and skipped entries (internal changes). Reads the
`user_facing` boolean from each result's structured response; the skipped
message comes from the original commit (`item`), not from parsing the LLM
output. The included list carries the original array index so enrich-drafts
can rejoin each draft with its source commit.

- type: code
- inputs:
    results: ${classify-commits.results}

```python code
results: list

included = []
skipped = []
for i, entry in enumerate(results):
    resp = entry.get('response')
    if not isinstance(resp, dict):
        continue  # parse failure — belongs to neither list
    if resp.get('user_facing'):
        line = (resp.get('entry') or '').strip()
        if line:
            included.append({'index': i, 'response': line})
    else:
        item = entry.get('item') or {}
        msg = (item.get('commit_message') or '').strip().split('\n')[0]
        if msg:
            skipped.append(msg)

result: dict = {'included': included, 'skipped': skipped}
```

### enrich-drafts

Pair each draft changelog entry with its original commit context (PR
link, title, body, files, task number). The format LLM needs this to
merge duplicates, add correct PR links, and refine descriptions using
the full PR body rather than the one-line draft.

- type: code
- inputs:
    included: ${split-classifications.result.included}
    commits: ${gather-commit-data.result}

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
            'hash': commit.get('hash', '')[:7],
            'commit_message': commit.get('commit_message', ''),
            'task_number': commit.get('task_number'),
            'files_changed': files_display,
            'pr_title': commit.get('pr_title', ''),
            'pr_body': commit.get('pr_body', ''),
            'pr_summary': commit.get('pr_summary', ''),
            'pr_link': commit.get('pr_link', ''),
            'pr_number': commit.get('pr_number'),
        }
    })

result: list = entries
```

### compute-version

Determine the next version number and release date. When `to_ref` is
a tag, version and date are extracted from it directly.

The LLM/classifier never picks major — `is_major_release` is always
the deciding input. When `is_major_release=false`, minor vs patch
auto-detects from entries (Added → minor, else patch).

Mismatch warnings (breaking entries vs is_major_release) are emitted
downstream by `check-warnings`, which scans the rendered CHANGELOG
output where canonical Removed/Changed verbs have been applied.

- type: code
- inputs:
    entries: ${enrich-drafts.result}
    current_tag: ${resolve-tag.result}
    to_ref: ${to_ref}
    is_major_release: ${is_major_release}

```python code
entries: list
current_tag: str
to_ref: str
is_major_release: bool

import subprocess
from datetime import datetime

drafts = [e['draft'] for e in entries]
has_features = any(d.startswith('Added') for d in drafts)

if is_major_release:
    bump_type = 'major'
elif has_features:
    bump_type = 'minor'
else:
    bump_type = 'patch'

if to_ref != 'HEAD':
    # Historical mode: version and date from the target tag
    next_version = to_ref if to_ref.startswith('v') else f'v{to_ref}'
    tag_date_str = subprocess.run(
        ['git', 'log', '-1', '--format=%ai', to_ref],
        capture_output=True, text=True
    ).stdout.strip()
    tag_date = datetime.strptime(tag_date_str[:10], '%Y-%m-%d')
    date_iso = tag_date.strftime('%Y-%m-%d')
    date_month_year = tag_date.strftime('%B %Y')
else:
    # Normal mode: compute version from entries
    version = current_tag.lstrip('v')
    major, minor, patch_num = (int(x) for x in version.split('.'))

    if bump_type == 'major':
        next_version = f'v{major + 1}.0.0'
    elif bump_type == 'minor':
        next_version = f'v{major}.{minor + 1}.0'
    else:
        next_version = f'v{major}.{minor}.{patch_num + 1}'

    now = datetime.now()
    date_iso = now.strftime('%Y-%m-%d')
    date_month_year = now.strftime('%B %Y')

result: dict = {
    'bump_type': bump_type,
    'next_version': next_version,
    'date_iso': date_iso,
    'date_month_year': date_month_year,
}
```

### format-draft-entries

Format each draft changelog entry as structured markdown with its full
commit context and matched task review. Both the format LLM and the
release context file consume this output, giving the LLM clean readable
input instead of serialized Python data structures.

- type: code
- inputs:
    entries: ${enrich-drafts.result}
    task_reviews: ${get-task-reviews.result}

```python code
entries: list
task_reviews: dict

used_reviews = set()
total = len(entries)
sections = []
for i, e in enumerate(entries, 1):
    ctx = e['context']
    lines = [f'### [{i}/{total}] {e["draft"]}', '']
    if ctx.get('hash'):
        lines.append(f'*Commit: `{ctx["hash"]}` {ctx["commit_message"]}*')
    elif ctx.get('commit_message'):
        lines.append(f'*Commit: {ctx["commit_message"]}*')
    task_num = ctx.get('task_number')
    has_review = task_num and str(task_num) in task_reviews
    if task_num and has_review:
        lines.append(f'Task: [{task_num}](.taskmaster/tasks/task_{task_num}/task-review.md)')
    elif task_num:
        lines.append(f'Task: {task_num}')
    if ctx.get('pr_number'):
        pr_line = f'PR: #{ctx["pr_number"]}'
        if ctx.get('pr_title'):
            pr_line += f' — {ctx["pr_title"]}'
        if ctx.get('pr_link'):
            pr_line += f' ({ctx["pr_link"]})'
        lines.append(pr_line)
    lines.append(f'Files: {ctx["files_changed"]}')
    if ctx.get('pr_body'):
        lines.append(f'\n**PR Description**\n\n{ctx["pr_body"]}')
    if has_review:
        review = task_reviews[str(task_num)]
        lines.append(f'\n**Task {task_num} Review**\n\n{review}')
        used_reviews.add(str(task_num))
    sections.append('\n'.join(lines))

entries_md = '\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n'.join(sections)

unmatched = '\n'.join(
    f'### Task {k}\n\n{v}\n' for k, v in task_reviews.items()
    if k not in used_reviews
)

result: dict = {'entries': entries_md, 'unmatched_reviews': unmatched}
```

### get-docs-diff

Extract documentation file changes since the tag, grouped by file with
commit refs. Outputs a list of chunks for parallel summarization — files
are grouped greedily until a chunk exceeds 300 diff lines, then a new
chunk starts. Files are never split across chunks. Excludes
`changelog.mdx` to avoid circular references.

- type: code
- inputs:
    tag: ${resolve-tag.result}
    to_ref: ${to_ref}

```python code
tag: str
to_ref: str

import subprocess

diff_output = subprocess.run(
    ['git', 'diff', f'{tag}..{to_ref}', '--name-only', '--', 'docs/'],
    capture_output=True, text=True
).stdout
files = [
    f for f in diff_output.strip().split('\n')
    if f and 'changelog.mdx' not in f
]

file_sections = []
for file in files:
    commits = subprocess.run(
        ['git', 'log', f'{tag}..{to_ref}', '--oneline', '--', file],
        capture_output=True, text=True
    ).stdout.strip().replace('\n', ', ')

    diff = subprocess.run(
        ['git', 'diff', f'{tag}..{to_ref}', '--', file],
        capture_output=True, text=True
    ).stdout
    change_lines = [
        line for line in diff.split('\n')
        if line.startswith(('+', '-')) and not line.startswith(('+++', '---'))
    ]

    section = f'## {file}\nCommits: {commits}\nChanges:\n' + '\n'.join(change_lines)
    file_sections.append({'text': section, 'lines': len(change_lines)})

max_lines = 300
chunks = []
current_chunk = []
current_lines = 0

for fs in file_sections:
    if current_chunk and current_lines + fs['lines'] > max_lines:
        chunks.append('\n\n'.join(s['text'] for s in current_chunk))
        current_chunk = []
        current_lines = 0
    current_chunk.append(fs)
    current_lines += fs['lines']

if current_chunk:
    chunks.append('\n\n'.join(s['text'] for s in current_chunk))

result: list = chunks
```

### summarize-docs-diff

Summarize raw documentation diffs into human-readable bullet points per
file. Processes diff chunks in parallel — each chunk contains one or
more files grouped by the `get-docs-diff` chunking logic. The release
context file and format LLMs consume the joined output.

- type: llm
- model: gemini/gemini-2.5-flash
- prompt: ./prompts/summarize-docs-diff.prompt.md

```yaml batch
items: ${get-docs-diff.result}
parallel: true
```


### join-docs-summary

Concatenate the per-chunk documentation summaries into a single string.
Downstream nodes (`render-changelogs` and `save-release-context`) receive the
same joined output they did before the batch split.

- type: code
- inputs:
    results: ${summarize-docs-diff.results}

```python code
results: list

parts = [r.get('response', '') for r in results if r.get('response')]
result: str = '\n\n'.join(parts)
```

### get-style-reference

Load up to 4 entries from the existing Mintlify changelog as style
examples. The format LLM matches this tone, structure, and component
usage when generating the new entry.

- type: code
- inputs:
    mintlify_file: ${mintlify_file}

```python code
mintlify_file: str

import re
from pathlib import Path

path = Path(mintlify_file) if mintlify_file else None
if not path or not path.is_file():
    examples_text = ''
else:
    content = path.read_text()
    updates = re.findall(r'<Update.*?</Update>', content, re.DOTALL)
    labeled = [f'Example {i}:\n{u}' for i, u in enumerate(updates[:4], 1)]
    examples_text = '\n\n'.join(labeled)

result: str = examples_text
```

### render-changelogs

Produce both output formats in parallel. Each receives pre-formatted
draft entries (with embedded task reviews) and LLM-summarized docs
changes, then independently deduplicates, sorts by verb
(`Removed` > `Changed` > `Added` > `Fixed` > `Improved`), and
standardizes terminology. The markdown format includes PR and task
links; the Mintlify format groups entries into themes without links.

- type: llm
- model: gemini/gemini-3.5-flash

```yaml batch
items:
  - format: markdown
    prompt: ./prompts/render-changelog-markdown.prompt.md
  - format: mintlify
    prompt: ./prompts/render-changelog-mintlify.prompt.md
parallel: true
```

```prompt
${item.prompt}
```

### check-warnings

Scan the rendered CHANGELOG for canonical Removed/Changed entries and
compare against `is_major_release`. The check runs here, not in
`compute-version`, because the classifier writes drafts with free-form
verbs (Refactored, Consolidated, Implemented, ...) — canonical verbs
only appear after `render-changelogs` standardizes them.

When `is_major_release=false` but Removed/Changed entries exist, or
when `is_major_release=true` with neither, a warning is emitted for
display in the summary and release context file. Warnings are
informational — they do not block the release.

- type: code
- inputs:
    markdown: ${render-changelogs.results[0].response}
    is_major_release: ${is_major_release}

```python code
markdown: str
is_major_release: bool

import re

breaking_lines = [
    line for line in markdown.split('\n')
    if re.match(r'^\s*-\s+(Removed|Changed)\s', line)
]

warnings = []

if is_major_release and not breaking_lines:
    warnings.append(
        'is_major_release=true but no entries start with Removed or Changed '
        'in the rendered changelog. Shipping as a major release anyway — '
        'confirm this is intentional (e.g. a declaratory stability bump '
        'like v1.0.0).'
    )
elif not is_major_release and breaking_lines:
    warnings.append(
        f'{len(breaking_lines)} entries starting with Removed or Changed '
        f'were detected but is_major_release=false. Shipping as a non-major '
        f'release may violate semver — review the CHANGELOG and either '
        f'reclassify the entries or re-run with is_major_release=true if a '
        f'major bump was intended.'
    )

result: dict = {'warnings': warnings}
```

### save-release-context

Write a release context file for pre-release verification. Contains the
rendered changelog, skipped commits for misclassification review,
documentation change summaries, and pre-formatted draft entries with
commit/PR context and matched task reviews.

- type: code
- inputs:
    changelog: ${render-changelogs.results[0].response}
    skipped: ${split-classifications.result.skipped}
    docs_summary: ${join-docs-summary.result}
    formatted_entries: ${format-draft-entries.result.entries}
    unmatched_reviews: ${format-draft-entries.result.unmatched_reviews}
    next_version: ${compute-version.result.next_version}
    date_iso: ${compute-version.result.date_iso}
    warnings: ${check-warnings.result.warnings}
    releases_dir: ${releases_dir}

```python code
changelog: str
skipped: list
docs_summary: str
formatted_entries: str
unmatched_reviews: str
next_version: str
date_iso: str
warnings: list
releases_dir: str

from pathlib import Path

docs_summary = docs_summary.strip() if docs_summary else ''
Path(releases_dir).mkdir(parents=True, exist_ok=True)
outfile = Path(releases_dir) / f'{next_version}-context.md'

skipped_lines = '\n'.join(f'- {s}' for s in skipped)

parts = [
    f'# {next_version} Release Context',
    '',
    f'Generated: {date_iso}',
    'This file contains implementation context for AI agents and release verification.',
    '',
]

if warnings:
    parts.extend(['---', '', '## ⚠ Warnings — Review Before Release', ''])
    parts.extend(f'- {w}' for w in warnings)
    parts.append('')

parts.extend([
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
    '## Documentation Changes',
    '',
    docs_summary,
    '',
    '---',
    '',
    '## Draft Entries with Context',
    '',
    formatted_entries,
])

if unmatched_reviews:
    parts.extend([
        '',
        '---',
        '',
        '## Additional Task Reviews',
        '',
        unmatched_reviews,
    ])

outfile.write_text('\n'.join(parts))
result: str = str(outfile)
```

### update-changelog-file

Prepend the new changelog section to the existing file. Inserts after
the H1 header if present, preserving all previous entries below.

> Flat list sorted by verb (`Removed`, `Changed`, `Added`, `Fixed`,
> `Improved`), each entry with PR links and task review links where
> available. Duplicates merged and terminology standardized by the
> format LLM.

- type: code
- inputs:
    new_section: ${render-changelogs.results[0].response}
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
    new_section: ${render-changelogs.results[1].response}
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

### check-slack

Route to Slack notification or skip directly to summary based on
whether a Slack channel is configured.

- type: code
- inputs:
    slack_channel: ${slack_channel}

```python code
slack_channel: str
if slack_channel.strip():
    next: str = "format-slack-message"
else:
    next: str = "create-summary"
```

### format-slack-message

Build the Slack notification combining a release header with the rendered
changelog entries.

- type: code
- next: notify-slack
- inputs:
    next_version: ${compute-version.result.next_version}
    bump_type: ${compute-version.result.bump_type}
    date_iso: ${compute-version.result.date_iso}
    changelog: ${render-changelogs.results[0].response}
    entries: ${enrich-drafts.result}

```python code
next_version: str
bump_type: str
date_iso: str
changelog: str
entries: list

header = f"# pflow {next_version}\n\n*{bump_type} bump · {date_iso} · {len(entries)} entries*\n\n---"
result: str = f"{header}\n\n{changelog}"
```

### notify-slack

Post the changelog to Slack. Uses Composio's markdown formatting for
clean rendering in the channel.

- type: mcp-composio-slack-SLACK_SEND_MESSAGE
- next: create-summary
- channel: ${slack_channel}
- markdown_text: ${format-slack-message.result}

### create-summary

Build the CLI output summary showing the version, bump type, and
created files with descriptions.

- type: code
- next: end
- inputs:
    entries: ${enrich-drafts.result}
    skipped: ${split-classifications.result.skipped}
    task_reviews: ${get-task-reviews.result}
    next_version: ${compute-version.result.next_version}
    bump_type: ${compute-version.result.bump_type}
    date_iso: ${compute-version.result.date_iso}
    warnings: ${check-warnings.result.warnings}
    changelog_path: ${update-changelog-file.result}
    mintlify_path: ${update-mintlify-file.result}
    context_path: ${save-release-context.result}
    slack_channel: ${slack_channel}

```python code
entries: list
skipped: list
task_reviews: dict
next_version: str
bump_type: str
date_iso: str
warnings: list
changelog_path: str
mintlify_path: str
context_path: str
slack_channel: str

lines = []

if warnings:
    lines.append('## ⚠ Warnings — Review Before Release\n')
    for w in warnings:
        lines.append(f'- {w}')
    lines.append('')

lines.extend([
    '## Release Summary\n',
    f'Version: {next_version} ({bump_type})',
    f'Date: {date_iso}\n',
    'Created files:',
    f'  {changelog_path}',
    f'    {len(entries)} entries with PR links',
])

if mintlify_path:
    lines.append(f'  {mintlify_path}')

lines.append(f'  {context_path}')
lines.append(f'    {len(skipped)} skipped changes, {len(task_reviews)} — review before committing')

if slack_channel:
    lines.append('')
    lines.append(f'Changelog posted to Slack channel #{slack_channel}')
    lines.append('')

result: str = '\n'.join(lines)
```

## Outputs

### summary

Release summary displayed after execution. Shows version, bump type, and created files.

- source: ${create-summary.result}

### suggested_version

Next version from semantic versioning rules: any Removed or Changed entry triggers major, any Added triggers minor, otherwise patch.

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
