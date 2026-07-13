# Git Worktree Task Creator

Sets up an isolated development environment for a new task. Given a natural-language task description, this workflow generates a conventional branch name (feat/fix/docs/refactor/test), creates a git worktree so work happens in a separate directory without touching your current checkout, and opens your editors pointed at the new worktree — ready to code.

The worktree branches from main by default. When run from a feature branch, you must explicitly specify which branch to base from — this prevents accidentally building on unmerged work.

## Inputs

### task_description

Natural-language description of the task, e.g. "Add retry logic to HTTP node" or "Bug: template variables not resolved in batch mode". Used by the LLM to generate a branch name and passed as context to the selected coding agent when it opens.

- type: string
- required: true

### base_branch

Git branch to base the new worktree on. Defaults to main when you're already on main. If you're on a feature branch and omit this, the workflow errors to prevent accidentally branching from unmerged work — pass `base_branch=main` explicitly in that case.

- type: string
- required: false
- default: ""

### copy_folder

Path (relative to repo root) of a folder to copy into the new worktree, e.g. `scratchpads/my-research`. Useful for carrying over gitignored research notes or scratchpads that wouldn't exist in a fresh checkout. Directory structure is preserved. Silently skips if the folder doesn't exist.

- type: string
- required: false
- default: ""

### open_cursor

Open Cursor IDE in the new worktree directory after creation.

- type: boolean
- required: false
- default: true

### open_cli

Whether to launch a coding agent in a new Terminal window with task context after creation. Acts as the on/off gate for the launch step regardless of which agent is selected (see `agent`); set `open_cli=false` to create the worktree without opening any agent. The launched agent receives the branch name and task description so it has immediate context.

- type: boolean
- required: false
- default: true

### work_type

Whether the description refers to a pflow `.taskmaster` task or a standalone GitHub issue. Set `issue` for GitHub issues so a bare issue number (e.g. `443`) isn't treated as a task id and no task scaffolding is created; `task` (the default) is for ordinary `.taskmaster` tasks.

- type: string
- required: false
- default: "task"

### agent

Which coding agent to launch in the worktree's Terminal. `claude` (the default) runs Claude Code; `codex` runs OpenAI's Codex CLI, which auto-executes commands inside a workspace sandbox (no per-command approval prompts). Both receive the same task-context prompt. Whether an agent launches at all is gated by `open_cli`.

- type: string
- required: false
- default: "claude"

### mode

Which agentic skill the launched agent starts with. `explore` (the default) → `/start-work`: investigate the task and produce a plan first — use when no plan exists yet. `implement` → `/implement-plan`: execute an existing plan directly, without re-planning. In `implement` mode, pass the bare task/issue number as `task_description` so the skill can resolve the plan file (e.g. `task_description=177 mode=implement`).

- type: string
- required: false
- default: "explore"

### phases

Phase scope for `mode=implement` — implements only these phases of the plan, then stops. Give the numbers as a range or list: `1`, `1-2`, `1,3`. Empty (default) implements the whole plan. Errors in `explore` mode (there is no plan to scope).

- type: string
- required: false
- default: ""

### model

Optional model for the launched agent, passed through as `--model` (both `claude` and `codex` accept it) — an alias like `opus`/`sonnet`, or a full id like `claude-opus-4-8`. Empty (the default) uses the agent's own default model.

- type: string
- required: false
- default: ""

### overwrite

Whether to replace an existing worktree/branch at the computed path. Defaults to false: if a worktree or branch with the computed name already exists, the workflow errors instead of destroying it — preventing a name collision between two *different* tasks from silently force-resetting (and losing) prior work. Set `overwrite=true` only when you intentionally want to re-run the **same** task and discard the old worktree and branch.

- type: boolean
- required: false
- default: false

## Steps

### get-repo-root

Resolves the absolute path of the **main** repository root via `git rev-parse --git-common-dir` (the common `.git` is shared by all worktrees, so this is correct even when the workflow is run from inside an existing worktree — unlike `basename $(pwd)`). The worktree path is built from this so every worktree lands in a sibling `<repo-root>-worktrees/` folder (e.g. `../pflow-worktrees/`), keeping the parent projects directory uncluttered.

- type: shell
- cache: false

```shell command
dirname "$(git rev-parse --path-format=absolute --git-common-dir)"
```

### get-branch

Detects the current git branch so the parse-result step can enforce the base branch safety check — erroring if you're on a feature branch without an explicit `base_branch`.

- type: shell
- cache: false

```shell command
git branch --show-current
```

### resolve-description

Resolves a bare number into a real, human-readable title so the branch name describes the work instead of being just a number. When `task_description` is a bare integer (a GitHub issue number or a taskmaster task id) it looks up the title: `work_type=issue` fetches it via `gh issue view`, `work_type=task` reads it from `./scripts/tasks`. Resolution is best-effort — if the lookup tool is missing (e.g. running outside the repo, no `gh`), not authenticated, times out, errors, or returns an empty title, it falls back to the raw description so the workflow never breaks. Prose descriptions (anything that isn't a bare integer) pass through untouched. Also surfaces the detected `number` so `parse-result` can carry it into the branch name for traceability.

- type: code
- cache: false
- timeout: 30
- inputs:
    task_description: ${task_description}
    work_type: ${work_type}

```python code
import re
import subprocess

task_description: str
work_type: str

raw = (task_description or '').strip()
work = (work_type or 'task').strip().lower()

# Recognize an issue/task reference as either a bare integer (e.g. "492") or a
# GitHub issue/PR URL (e.g. ".../issues/492" or ".../pull/492"). Anything else is
# a natural-language description, used verbatim. Extracting the number from URLs
# is critical: without it the title lookup below is skipped, the raw URL is fed to
# the LLM (which can't fetch it and confabulates a generic name), AND the
# number-anchored prefix in parse-result is lost -- which is exactly what made
# every issue-URL run collapse onto the same hallucinated branch and force-reset
# each other's work.
if re.fullmatch(r'\d+', raw):
    number = raw
else:
    m = re.search(r'/(?:issues|pull)/(\d+)', raw)
    number = m.group(1) if m else ''
description = raw
title_resolved = False


def _run(cmd: list) -> str:
    # Best-effort: any failure (missing binary, non-zero exit, timeout) -> ''.
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except Exception:
        return ''
    if proc.returncode != 0:
        return ''
    return proc.stdout.strip()


if number:
    if work == 'issue':
        title = _run(['gh', 'issue', 'view', number, '--json', 'title', '--jq', '.title'])
    else:
        # `./scripts/tasks N` prints e.g. "## Task 162: Loop Config ..." on line 1.
        out = _run(['./scripts/tasks', number])
        first = out.splitlines()[0] if out else ''
        title = re.sub(r'^#+\s*Task\s+\d+:\s*', '', first).strip()
    if title:
        description = title
        title_resolved = True

# title_resolved tells parse-result whether `description` is a real human title
# (safe to feed the LLM for a descriptive slug) or just the raw number/URL (in
# which case parse-result must NOT trust the LLM's confabulated name and instead
# anchor the branch on the number alone).
result: dict = {'description': description, 'number': number, 'title_resolved': title_resolved}
```

### analyze-task

Uses an LLM to classify the resolved description into a branch type (feat/fix/docs/refactor/test) and generate a short kebab-case branch name. Reads the title resolved by `resolve-description` (not the raw input) so issue/task numbers become descriptive names. Only determines the type and name — path construction and validation happen deterministically in the next step.

- type: llm
- cache: false

```markdown prompt
Analyze the task description and generate git branch information.

Task: ${resolve-description.result.description}

Determine:
1. Branch type:
   - 'implement', 'add', 'create', 'build' → feat
   - 'fix', 'bug', 'repair', 'resolve' → fix
   - 'document', 'docs', 'readme' → docs
   - 'refactor', 'restructure', 'reorganize' → refactor
   - 'test', 'testing', 'spec' → test
   - Default: feat

2. Branch name (kebab-case, 2-4 key words, remove articles like 'a', 'an', 'the')

Respond ONLY with this exact format (two lines, nothing else):
BRANCH_TYPE=type
BRANCH_NAME=name
```
- model: gemini-2.5-flash-lite
- temperature: 0.3

### parse-result

Central logic node. Parses the LLM's KEY=VALUE response, validates the base branch (erroring if on a feature branch without explicit input), classifies the work as a pflow task or a GitHub issue (deriving the `work_label`) and selects the launched agent's entry skill from `mode` (deriving the `agent_hint` used in the launch-cli prompt — `/start-work` for `explore`, `/implement-plan` for `implement`), constructs the worktree path and full branch name deterministically, prepends a tracker-labelled reference (`issue-<n>` / `task-<n>`) to the branch name for traceability (e.g. `fix/issue-382-shrink-trace-content-interning`), and escapes the task description through two quoting layers (shell single-quote inside AppleScript double-quote) so it can be safely embedded in the launch-cli osascript command.

- type: code
- inputs:
    response: ${analyze-task.response}
    repo_root: ${get-repo-root.stdout}
    current_branch: ${get-branch.stdout}
    base_branch: ${base_branch}
    description: ${task_description}
    work_type: ${work_type}
    mode: ${mode}
    phases: ${phases}
    issue_number: ${resolve-description.result.number}
    title_resolved: ${resolve-description.result.title_resolved}
    agent: ${agent}
    model: ${model}
    copy_folder: ${copy_folder}

```python code
import re

response: str
repo_root: str
current_branch: str
base_branch: str
description: str
work_type: str
mode: str
phases: str
issue_number: str
title_resolved: bool
agent: str
model: str
copy_folder: str

# Classify work as a pflow task or a standalone GitHub issue. This drives how
# the launched Claude session is told to interpret the description, so a bare
# issue number isn't mistaken for a task id by the /start-work skill.
work_type = (work_type or 'task').strip().lower()
if work_type not in ('task', 'issue'):
    raise ValueError(f"work_type must be 'task' or 'issue', got '{work_type}'")

# Which agentic skill the launched agent is pointed at:
#   'explore'   -> /start-work    (investigate + produce a plan; no plan exists yet)
#   'implement' -> /implement-plan (a plan already exists; execute it directly)
mode = (mode or 'explore').strip().lower()
if mode not in ('explore', 'implement'):
    raise ValueError(f"mode must be 'explore' or 'implement', got '{mode}'")

# Optional phase scope forwarded to /implement-plan (which implements ONLY the
# named phase(s) and stops). Restricted to digits/spaces/commas/hyphens because
# it is inlined UNESCAPED into agent_hint -> the launch step's AppleScript +
# shell quoting layers; a quote/$/backtick would break them. Only meaningful in
# implement mode -- there is no plan to scope while exploring.
phases = (phases or '').strip()
if phases:
    if mode != 'implement':
        raise ValueError("phases only applies when mode=implement (there is no plan to scope in explore mode)")
    if not re.fullmatch(r'[0-9][0-9,\- ]*', phases):
        raise ValueError(
            f"phases must contain only digits, spaces, commas, and hyphens (e.g. '1', '1-2', '1,3'), got '{phases}'"
        )

work_label = 'GitHub issue' if work_type == 'issue' else 'Task'
issue_scaffolding_note = (
    ' This is a GitHub issue, NOT a pflow task -- do not create taskmaster scaffolding.'
    if work_type == 'issue' else ''
)

if mode == 'implement':
    # A plan already exists -- point the agent at /implement-plan, not the
    # exploratory /start-work skill. When phases is set, forward it as the skill's
    # phase-scope argument so only those phases run.
    scope_arg = f' phases {phases}' if phases else ''
    if work_type == 'task':
        # Tasks live in .taskmaster; a bare task number resolves the plan file for
        # /implement-plan. issue_number is guaranteed digit-only (or empty) by
        # resolve-description's regex, so it is safe to inline unescaped here.
        ref = (issue_number or '').strip()
        if ref:
            target = f'Run /implement-plan {ref}{scope_arg}.'
        else:
            target = f"Run /implement-plan on the task's implementation-plan.md{scope_arg}."
    else:
        # A GitHub issue number is NOT a task id, and issues have no .taskmaster
        # plan -- so do NOT feed the number to /implement-plan (it would resolve to a
        # nonexistent task_<n>). The launched agent has the issue context and locates
        # the issue's existing plan itself.
        target = f'Run /implement-plan on the existing plan for this issue{scope_arg}.'
    # Empty phases means "the whole plan". /implement-plan otherwise ASKS before
    # implementing a whole plan when no scope is given; the worktree's implement
    # mode is an explicit "execute it directly" request, so tell it to proceed.
    if phases:
        directive = f' Implement ONLY phase(s) {phases} and stop after that scope.'
    else:
        directive = ' Implement the whole plan directly -- no need to ask before starting.'
    agent_hint = (
        'A plan already exists -- do NOT explore or re-plan. If an /implement-plan '
        f'skill is available, use it to implement the plan directly. {target}'
        f'{directive}{issue_scaffolding_note}'
    )
elif work_type == 'issue':
    agent_hint = (
        'This is a GitHub issue, NOT a pflow task -- do not create taskmaster task '
        'scaffolding. If a /start-work skill is available, use it to begin and pass '
        'this as a GitHub issue so it fetches the details via gh.'
    )
else:
    agent_hint = 'If a /start-work skill is available, use it to begin.'

# If a folder was copied into the worktree (gitignored briefing/research docs that
# won't exist in a fresh checkout), point the agent at it. The launch prompt otherwise
# never mentions the copied folder, so the agent has no way to know it exists. Plain
# text + a controlled path, so it rides the launch step's quoting layers like
# agent_hint. Tell it to read EVERY file -- the folder's contents/names vary
# (brief, braindump, research), so don't assume a single filename.
copy_folder = (copy_folder or '').strip()
folder_hint = (
    f'IMPORTANT: briefing/research docs were copied into this worktree at {copy_folder}/ '
    f'-- read ALL files in {copy_folder}/ FIRST, before starting work. They are the curated '
    'context for this task (what to read, locked decisions, constraints, pre-flight).'
) if copy_folder else ''

# Validate base branch
if base_branch:
    effective_base = base_branch
elif current_branch == 'main':
    effective_base = 'main'
else:
    raise ValueError(
        f"Currently on '{current_branch}', not main. "
        f"Specify base_branch explicitly (e.g., base_branch=main)"
    )

lines = dict(line.split('=', 1) for line in response.strip().splitlines() if '=' in line)
branch_type = lines.get('BRANCH_TYPE', 'feat').strip()
branch_name = lines.get('BRANCH_NAME', 'task').strip()
if branch_type not in ('feat', 'fix', 'docs', 'refactor', 'test'):
    raise ValueError(f"branch_type must be feat, fix, docs, refactor, or test, got {branch_type!r}")
if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', branch_name):
    raise ValueError(f"branch_name must be lowercase kebab-case, got {branch_name!r}")

# Anchor the branch on the issue/task number so it is unique and traceable, and
# labelled by tracker so a bare number isn't ambiguous between a GitHub issue and
# a taskmaster task -- e.g. fix/issue-382-shrink-trace-content-interning.
# work_type is already normalized to 'task'/'issue' above. issue_number is empty
# for prose input (no number upstream), in which case the LLM's name is kept as-is.
#
# When we have a number but NO resolved title (title_resolved is False -- e.g. a
# URL/number whose `gh`/scripts lookup failed or was unavailable), the LLM only
# ever saw the opaque number/URL and confabulated a generic name (the root of the
# cross-issue collision bug). In that case do NOT trust the LLM name: anchor on
# the number alone (e.g. fix/issue-492), which is honest and guaranteed unique.
# Only when a real title was resolved do we append the LLM-derived descriptive slug.
issue_number = (issue_number or '').strip()
if issue_number:
    ref = f'{work_type}-{issue_number}'  # e.g. issue-382 / task-162
    if not title_resolved:
        branch_name = ref
    elif branch_name != ref and not branch_name.startswith(f'{ref}-'):
        branch_name = f'{ref}-{branch_name}'

# Escape description for embedding in: osascript <<APPLESCRIPT ... do script "...claude '...DESC...'" ... APPLESCRIPT
# Layer 2 (innermost): inner shell single-quote context (' → '\'' )
safe = description.replace("'", "'\\''" )
# Layer 1: AppleScript double-quote context (\ → \\, " → \")
safe = safe.replace('\\', '\\\\').replace('"', '\\"')
# Layer 0 (outermost): outer bash unquoted heredoc context (\ → \\, ` → \`, $ → \$)
safe = safe.replace('\\', '\\\\').replace('`', '\\`').replace('$', '\\$')

# Select which coding agent the launch step starts in the worktree's Terminal.
# 'claude' mirrors the original behaviour (--dangerously-skip-permissions);
# 'codex' runs OpenAI's Codex CLI with --sandbox workspace-write
# --ask-for-approval never (auto-executes inside the workspace sandbox, no
# per-command prompts). Both take the context prompt as a positional argument, so
# the launch step only needs to swap this command prefix.
agent = (agent or 'claude').strip().lower()
if agent not in ('claude', 'codex'):
    raise ValueError(f"agent must be 'claude' or 'codex', got '{agent}'")
if agent == 'codex':
    agent_cmd = 'codex --sandbox workspace-write --ask-for-approval never'
    agent_label = 'Codex'
else:
    agent_cmd = 'claude --dangerously-skip-permissions'
    agent_label = 'Claude'

# Optional model override, passed through to the launched agent as `--model
# <model>` (both `claude` and `codex` accept it). Empty -> omit the flag so the
# agent uses its own configured default. Validated against a strict model-token
# allowlist because agent_cmd is inlined *unescaped* into the launch step's
# AppleScript `do script` string -- a stray quote/space/$/backtick in the model
# value would break the heredoc + AppleScript quoting layers (unlike
# safe_description, agent_cmd is not run through the escaping above).
model = (model or '').strip()
if model:
    if not re.fullmatch(r'[A-Za-z0-9._:-]+', model):
        raise ValueError(
            f"model must contain only letters, digits, and . _ - : characters, got '{model}'"
        )
    agent_cmd = f'{agent_cmd} --model {model}'

# Codex has a repo-local pflow-sandbox-testing skill for running pflow's test
# suite from sandbox mode; point Codex at it (skill-neutral so it applies whether
# the agent is exploring or implementing). Claude has no such skill, so this is
# codex-only. Named in plain text (no '$' prefix, no apostrophes/quotes) so it
# survives the launch step's heredoc + AppleScript + inner-single-quote layers,
# which agent_hint -- unlike safe_description -- is not escaped through.
if agent == 'codex':
    agent_hint += ' Use the pflow-sandbox-testing skill directly when you run pflow tests.'

result: dict = {
    'branch_type': branch_type,
    'branch_name': branch_name,
    'worktree_path': f'{repo_root}-worktrees/{branch_type}-{branch_name}',
    'full_branch': f'{branch_type}/{branch_name}',
    'base_branch': effective_base,
    'safe_description': safe,
    'work_label': work_label,
    'agent_hint': agent_hint,
    'folder_hint': folder_hint,
    'agent_cmd': agent_cmd,
    'agent_label': agent_label,
}
```

### create-worktree

Creates the git worktree inside the `<repo-root>-worktrees/` folder (e.g. `../pflow-worktrees/fix-issue-382-shrink-trace-interning`) with a new branch based on the validated base branch. `mkdir -p` ensures the worktrees folder exists on first use (and is harmless if it already does).

Overwrite handling is concentrated here (this step absorbed the former separate cleanup step). By default (`overwrite=false`) it is **non-destructive**: it refuses — with an actionable error naming the conflict and the `overwrite=true` escape hatch — if a branch or worktree with the computed name already exists, and creates the branch with lowercase `-b` (which itself fails if the branch exists). This prevents a name collision between two *different* tasks from silently discarding prior work — the failure mode where several issue-URL runs collapsed onto one hallucinated name and force-reset each other. Pass `overwrite=true` to intentionally re-run the **same** task: that path removes any existing worktree at the target and uses `-B` to reset the branch to the base, restoring the old convenience behavior on explicit opt-in.

- type: shell

```shell command
WT="${parse-result.result.worktree_path}"
BR="${parse-result.result.full_branch}"
BASE="${parse-result.result.base_branch}"
mkdir -p "$(dirname "$WT")"
if [ '${overwrite}' = 'true' ] || [ '${overwrite}' = 'True' ] || [ '${overwrite}' = '1' ]; then
  git worktree remove "$WT" 2>/dev/null || true
  git worktree add "$WT" -B "$BR" "$BASE"
else
  if git show-ref --verify --quiet "refs/heads/$BR"; then
    echo "ERROR: branch '$BR' already exists -- refusing to overwrite. A different task may have produced the same name, or you're re-running the same task. Pass overwrite=true to reset it, or give a more specific task_description." >&2
    exit 1
  fi
  if [ -e "$WT" ]; then
    echo "ERROR: worktree path '$WT' already exists -- refusing to overwrite. Pass overwrite=true to replace it." >&2
    exit 1
  fi
  git worktree add "$WT" -b "$BR" "$BASE"
fi
```

### copy-folder

Copies an optional folder (typically a gitignored scratchpad with research notes) into the new worktree, preserving its directory structure. Useful because worktrees are fresh checkouts that only contain tracked files. Warns on stderr if the folder doesn't exist; skips entirely if `copy_folder` was not provided.

- type: shell
- ignore_errors: true

```shell command
FOLDER='${copy_folder}' && ROOT='${get-repo-root.stdout}' && WORKTREE='${parse-result.result.worktree_path}' && if [ -n "$FOLDER" ]; then if [ -d "$ROOT/$FOLDER" ]; then PARENT=$(dirname "$FOLDER") && mkdir -p "$WORKTREE/$PARENT" && cp -r "$ROOT/$FOLDER" "$WORKTREE/$PARENT/" && echo "Copied $FOLDER to worktree"; else echo "Warning: folder '$FOLDER' not found under repo root, skipping" >&2; fi; else echo 'No folder to copy'; fi
```

### output-status

Emits the primary workflow output — a confirmation message with the worktree path that downstream consumers (CLI, skills, agents) can parse or display.

- type: shell

```shell command
echo "✅ Worktree created at ${parse-result.result.worktree_path}"
```

### launch-cursor

Opens Cursor IDE pointed at the new worktree directory. Skipped when `open_cursor` is false. Errors are ignored so a missing Cursor installation doesn't fail the workflow.

- type: shell
- ignore_errors: true

```shell command
if [ '${open_cursor}' != 'false' ] && [ '${open_cursor}' != 'False' ] && [ '${open_cursor}' != '0' ]; then open -a "Cursor" "${parse-result.result.worktree_path}" && echo 'Cursor launched'; else echo 'Skipping Cursor'; fi
```

### launch-cli

Opens a new Terminal window, cd's into the worktree, and starts the selected coding agent (`claude` or `codex`, per the `agent` input) with the description and branch name as initial context. The launch command prefix (`claude --dangerously-skip-permissions` or `codex --sandbox workspace-write --ask-for-approval never`) is derived in `parse-result` as `agent_cmd`; both agents take the context prompt as a positional argument, so only this prefix differs. The absolute worktree path is inlined **directly** into the `do script` command as a resolved `${parse-result.result.worktree_path}` value — NOT passed via a bash variable. This matters: `do script` runs in a brand-new Terminal window whose shell never inherited the workflow's variables, so a `cd $VAR` there would expand to empty and silently land in `$HOME` (the bug that previously launched Claude in the home folder with a stray trust dialog and no project `.claude/` context). A guard refuses to launch (and reports on stderr) if the worktree dir is missing, so it can never fall back to home. `activate` brings Terminal above the Cursor window opened by the prior node, and the window created by `do script` is automatically Terminal's frontmost window — so the Claude session lands on top without any manual window-raising. The description is labelled `Task:` or `GitHub issue:` per `work_type`, and the agent is pointed at its entry skill per `mode` — `/start-work` (explore) or `/implement-plan` (implement) — with issues explicitly told not to create taskmaster scaffolding. When `agent=codex`, the prompt additionally tells Codex to use the repo-local `pflow-sandbox-testing` skill when running pflow tests (Claude has no such skill, so it's added only for codex; named in plain text to stay safe through the quoting layers, which `agent_hint` is not escaped through). The description is pre-escaped by parse-result to handle quotes safely through the AppleScript and shell quoting layers. Skipped when `open_cli` is false.

- type: shell
- ignore_errors: true

```shell command
if [ '${open_cli}' = 'false' ] || [ '${open_cli}' = 'False' ] || [ '${open_cli}' = '0' ]; then
  echo 'Skipping ${parse-result.result.agent_label}'
elif [ ! -d "${parse-result.result.worktree_path}" ]; then
  echo "ERROR: worktree directory not found, not launching ${parse-result.result.agent_label}: ${parse-result.result.worktree_path}" >&2
else
  osascript <<APPLESCRIPT
tell application "Terminal"
    activate
    do script "cd '${parse-result.result.worktree_path}' && ${parse-result.result.agent_cmd} 'You have been assigned to work in a dedicated git worktree. Worktree: ${parse-result.result.worktree_path}, Branch: ${parse-result.result.full_branch}, ${parse-result.result.work_label}: ${parse-result.result.safe_description}. All changes here are separate from main. ${parse-result.result.agent_hint} ${parse-result.result.folder_hint}'"
end tell
APPLESCRIPT
  echo '${parse-result.result.agent_label} launched in Terminal'
fi
```

## Outputs

### status

Human-readable confirmation message with the worktree path, e.g. "Worktree created at ../pflow-worktrees/fix-issue-382-shrink-trace-interning". This is the primary output streamed to stdout.

- source: ${output-status.stdout}
- stdout: true

### worktree_creation_status

Raw stdout from the worktree creation command — git's checkout confirmation, e.g. "HEAD is now at <sha> <commit subject>". Note: git writes the branch-creation line ("Preparing worktree (new branch '...')") to stderr, not stdout, so it does not appear here; the derived branch name is available in `branch_analysis.full_branch`.

- source: ${create-worktree.stdout}

### branch_analysis

Structured dict with all derived values: `branch_type`, `branch_name`, `worktree_path`, `full_branch`, `base_branch`, and `safe_description`. Useful for downstream automation that needs to act on the created worktree.

- source: ${parse-result.result}
