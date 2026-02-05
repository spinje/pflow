# Task 119: Publish Workflows as Claude Code Skills

## Description

A `pflow skill` command group that publishes saved workflows as Claude Code skills. Enriches the saved workflow file (frontmatter + `## Usage` section) and creates a symlink from the Claude Code skills directory. Skills auto-update when the saved workflow changes because the symlink points to the canonical copy.

## Status

not started

## Priority

high

## Problem

There's no bridge between pflow workflows and Claude Code's skill system. Users who build useful workflows can't make them discoverable by Claude Code without manually creating `SKILL.md` files, duplicating content, and keeping them in sync. The workflow IS the documentation — it should be the skill too.

## Solution

New `pflow skill` CLI command group with three commands:

```
pflow skill save <workflow-name> [--personal] [--project] [--force]
pflow skill list
pflow skill remove <workflow-name> [--personal] [--project]
```

### `pflow skill save` flow

1. Validate workflow exists in `~/.pflow/workflows/<name>.pflow.md`
2. Read the saved workflow file
3. Enrich the file in-place:
   a. Add `name` and `description` to YAML frontmatter (alongside existing system metadata)
   b. Inject `## Usage` section after H1 prose, before first `##` section
4. Write back atomically (same pattern as `update_metadata()`)
5. Create directory: `.claude/skills/<name>/` (project) or `~/.claude/skills/<name>/` (personal)
6. Create symlink: `SKILL.md` → `~/.pflow/workflows/<name>.pflow.md`

### `pflow skill list` flow

1. Scan `.claude/skills/*/SKILL.md` (project) for symlinks resolving to `~/.pflow/workflows/`
2. Scan `~/.claude/skills/*/SKILL.md` (personal) for symlinks resolving to `~/.pflow/workflows/`
3. Display: name, scope, target path, status (ok/broken)

Only shows pflow-managed skills (symlinks to `~/.pflow/workflows/`). Non-pflow skills are ignored.

### `pflow skill remove` flow

1. Find the symlink in the appropriate skills directory
2. Remove the symlink and its parent directory
3. Leave the saved workflow's enrichment intact (harmless — `## Usage` is ignored by parser, frontmatter fields don't interfere)

### Re-save detection

When `pflow workflow save --force <name>` overwrites a saved workflow, the enrichment (`## Usage` + frontmatter fields) is lost because the save pipeline replaces the file with new content + standard frontmatter. After save, scan both skills directories for symlinks pointing to `~/.pflow/workflows/<name>.pflow.md`. If found, re-enrich automatically.

## Design Decisions

- **Symlink, not copy**: The symlink means changes to the saved workflow propagate to Claude Code automatically. One source of truth. The `## Usage` section and frontmatter enrichment are part of the saved file, so they survive metadata updates (which only touch frontmatter).

- **Enrich the saved workflow, not a separate file**: We modify the body of `~/.pflow/workflows/<name>.pflow.md` to inject `## Usage`. This breaks the Task 107 convention that "the body is never modified during metadata updates" — but this is a one-time enrichment during skill publishing, not a metadata update. The `## Usage` section is silently ignored by the parser (unknown `##` sections are skipped), so it doesn't affect workflow execution.

- **`--project` is the default scope**: Matches Anthropic's recommendation. Project skills (`.claude/skills/`) are version-controllable and team-shareable. `--personal` (`~/.claude/skills/`) is opt-in for cross-project skills.

- **Anthropic terminology**: "personal" and "project" — not "user" and "project". Matches Claude Code docs.

- **`description` in frontmatter is intentional + workaround**: Claude Code uses `description` for auto-invocation (long-term correct), AND there's currently a bug requiring it for skill discovery (short-term workaround). When the bug is fixed, description remains useful. Comment the workaround aspect in code so a future agent can remove the note, not the field.

- **Symlink scanning for re-save detection, no frontmatter markers**: The filesystem (symlinks) is the single source of truth for "is this workflow a skill?" No `skill: true` marker in frontmatter to drift out of sync. Scanning two directories for symlinks is negligible overhead.

- **`pflow skill save` requires a saved workflow**: The argument is a workflow name (not a file path). The workflow must already be saved via `pflow workflow save`. This matches the intended pflow workflow: iterate on a file → save when it works → publish as skill.

- **Consolidate name derivation to one function**: Currently 3+ locations independently do `Path.stem` + strip `.pflow` (`WorkflowManager._name_from_path()`, `cli/main.py:_setup_workflow_execution()`, `planning/context_builder.py`). Extract to a single `derive_workflow_name()` that all callers use. This also becomes the natural place to add frontmatter `name` override — one change, all callers get it. The override is needed beyond skills: when the file is `SKILL.md`, the filename-derived name would be wrong.

## Dependencies

- Task 107: Markdown Workflow Format — completed and merged. Provides the markdown parser, frontmatter handling, WorkflowManager with `.pflow.md` support, and the `_split_frontmatter_and_body()` / `_serialize_with_frontmatter()` patterns this task builds on.

## Implementation Notes

### `## Usage` section generation

Generated from the workflow's parsed IR. Template:

````markdown
## Usage

If you are unsure this is exactly what the user wants to execute, ask the user if they want to run this workflow. If any required inputs are missing, ask the user to provide them.
Always ask the user before modifying or extending the workflow or reading the instructions.

```bash
# Execute this workflow directly:
pflow <workflow-name> <required_param1>=<value> <required_param2>=<value>

# To modify or extend - read all 3 parts IN FULL (do not truncate):
pflow instructions create --part 1
pflow instructions create --part 2
pflow instructions create --part 3
```

> Pflow and all dependencies should be installed, working and ready to use.

---
````

Required params are extracted from `ir["inputs"]` — any input where `required` is `True` (or missing, since default is `True`). Optional params are omitted from the example command.

Existing pattern to follow: `workflow_describe_formatter.py:_format_example_usage_section()` already builds `pflow {name} {param}=<value>` commands from IR inputs.

### `## Usage` injection and replacement

**Injection point**: After H1 prose (description), before first `##` section.

**On re-enrichment** (re-save detection): Find existing `## Usage` heading in the body. If found, replace everything from `## Usage` up to (but not including) the next `##` heading. If not found, inject at the standard position.

### Frontmatter enrichment

Add to existing frontmatter (don't replace):

```yaml
---
created_at: "..."       # existing
updated_at: "..."       # existing
version: "1.0.0"        # existing
name: release-announcements     # NEW — added by skill save
description: "Creates release..." # NEW — extracted from H1 prose (workaround for Claude Code discovery bug)
execution_count: 5      # existing
---
```

Uses the existing `_split_frontmatter_and_body()` → modify → `_serialize_with_frontmatter()` pattern from `WorkflowManager`.

### CLI routing

Add `skill` to `main_wrapper.py` pre-parser routing:

```python
elif first_arg == "skill":
    from .skills import skill
    skill()
```

New file: `src/pflow/cli/skills.py` with `@click.group` and three commands.

### Symlink scanning utility

Core function needed by `skill list`, `skill remove`, and re-save detection:

```python
def find_pflow_skills(project_dir: Path | None = None) -> list[SkillInfo]:
    """Scan project and personal skill directories for pflow-managed symlinks."""
```

Returns list of dataclass/namedtuple with: name, scope (project/personal), symlink_path, target_path, is_valid (symlink resolves).

`project_dir` defaults to `Path.cwd()`. Scans `{project_dir}/.claude/skills/*/SKILL.md` and `~/.claude/skills/*/SKILL.md`.

### Name derivation consolidation

Extract to shared utility (e.g., `src/pflow/core/name_utils.py` or add to existing `validation_utils.py`):

```python
def derive_workflow_name(path: Path, metadata: dict | None = None) -> str:
    """Derive workflow name from path, with optional frontmatter override."""
    if metadata and metadata.get("name"):
        return metadata["name"]
    name = path.stem
    return name[:-6] if name.endswith(".pflow") else name
```

Update `WorkflowManager._name_from_path()` to delegate. Update `WorkflowManager.load()` and `list_all()` to check frontmatter `name` field.

### Files to create

- `src/pflow/cli/skills.py` — CLI command group
- `src/pflow/core/skill_service.py` — Business logic (enrich, scan, symlink management)
- `tests/test_cli/test_skills.py` — CLI command tests
- `tests/test_core/test_skill_service.py` — Service unit tests

### Files to modify

- `src/pflow/cli/main_wrapper.py` — Add `skill` routing
- `src/pflow/core/workflow_save_service.py` — Post-save re-enrichment hook
- `src/pflow/core/workflow_manager.py` — Name derivation consolidation + frontmatter name override in `load()`/`list_all()`

### Edge cases

- **Workflow not saved**: Clear error with suggestion to save first
- **Skill already exists**: Error unless `--force` (removes existing symlink + directory, re-creates)
- **Both `--personal` and `--project`**: Mutually exclusive flags. Error if both provided.
- **`.claude/skills/` directory doesn't exist**: Create it (including parent `.claude/` if needed)
- **Broken symlink**: `skill list` shows it as broken. `skill save --force` replaces it.
- **Workflow has no inputs**: Example command is just `pflow <name>` with no params. Still useful.
- **Same workflow published to both scopes**: Allowed — different symlinks, same target.

### Out of scope

- `pflow skill update` — re-running `pflow skill save --force` is sufficient
- Supporting files in skill directory (templates, scripts) — just `SKILL.md` for v1
- MCP tool for skill publishing — CLI only for now
- Automatic skill creation during `pflow workflow save` — always explicit
- Skill-specific frontmatter fields beyond `name`/`description` (e.g., `allowed-tools`, `argument-hint`) — can be added later

## Verification

### Core functionality
- `pflow skill save my-workflow` creates enriched file + symlink at `.claude/skills/my-workflow/SKILL.md`
- `pflow skill save my-workflow --personal` creates symlink at `~/.claude/skills/my-workflow/SKILL.md`
- Symlink resolves correctly to `~/.pflow/workflows/my-workflow.pflow.md`
- Enriched file has `name` + `description` in frontmatter
- Enriched file has `## Usage` section with correct example command
- `pflow my-workflow` still executes correctly (enrichment doesn't break execution)

### Skill list
- `pflow skill list` shows pflow-managed skills with scope and status
- Broken symlinks shown as broken
- Non-pflow skills in `.claude/skills/` are not shown

### Skill remove
- `pflow skill remove my-workflow` removes symlink + directory
- Saved workflow is unchanged (enrichment left intact)

### Re-save detection
- `pflow workflow save ./updated.pflow.md --name my-workflow --force` re-enriches if skill symlink exists
- `## Usage` section is replaced (not duplicated) on re-enrichment
- Frontmatter `name`/`description` are re-added after re-save

### Name derivation
- `WorkflowManager.load()` returns frontmatter `name` when present
- `WorkflowManager.list_all()` uses frontmatter `name` when present
- Fallback to filename-derived name when no frontmatter `name`

### Error handling
- `pflow skill save nonexistent` → clear error with save suggestion
- `pflow skill save my-workflow` when skill exists → error unless `--force`
- `pflow skill save my-workflow --personal --project` → mutual exclusion error

## Context

- Task 107 format spec: `.taskmaster/tasks/task_107/starting-context/format-specification.md`
- Task 107 review: `.taskmaster/tasks/task_107/task-review.md`
- Claude Code skill docs: `name`, `description`, `argument-hint`, `allowed-tools`, `disable-model-invocation`, `user-invocable`, `model`, `context`, `agent`, `hooks` are supported frontmatter fields
- Anthropic terminology: "personal" (not "user") and "project" for skill scopes
- Existing example command pattern: `src/pflow/execution/formatters/workflow_describe_formatter.py:_format_example_usage_section()`
- Existing rerun command pattern: `src/pflow/cli/rerun_display.py:format_rerun_command()`
- WorkflowManager frontmatter handling: `_split_frontmatter_and_body()`, `_serialize_with_frontmatter()`, `_build_frontmatter()` in `src/pflow/core/workflow_manager.py`
