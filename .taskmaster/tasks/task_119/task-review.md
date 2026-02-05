# Task 119 Review: Publish Workflows as Claude Code Skills

## Metadata
- **Implementation Date**: 2026-02-05
- **Final Test Count**: 3663 passed, 516 skipped

## Executive Summary

Added `pflow skill` CLI command group that publishes saved workflows as AI agent skills. Skills are symlinks from tool-specific directories (Claude Code, Cursor, Codex, Copilot) to saved workflows in `~/.pflow/workflows/`. The workflow file is enriched with a `## Usage` section and frontmatter metadata. Also added `pflow workflow history` command for retrieving execution history.

## Implementation Overview

### What Was Built

1. **`pflow skill save <name> [--personal] [--cursor] [--codex] [--copilot]`**
   - Enriches saved workflow with `name`/`description` frontmatter and `## Usage` section
   - Creates symlink: `{tool}/.skills/{name}/SKILL.md` → `~/.pflow/workflows/{name}.pflow.md`
   - Idempotent: if skill exists, just re-enriches (no `--force` needed)
   - Multi-target: combine flags to save to multiple tools in one command

2. **`pflow skill list`**
   - Scans all tool directories for pflow-managed symlinks
   - Groups output by workflow name
   - Shows broken links with fix commands

3. **`pflow skill remove <name> [--personal] [--cursor] [--codex] [--copilot]`**
   - Removes symlinks from specified tool directories
   - Leaves saved workflow enrichment intact

4. **`pflow workflow history <name>`**
   - Shows execution count, last run timestamp, status
   - Displays last used inputs (for parameter reuse)

5. **Re-save detection hook**
   - After `pflow workflow save --force`, re-enriches if workflow is a skill
   - Prevents `## Usage` loss when overwriting

### Key Deviation from Spec

**Removed `--force` flag**: Original spec required `--force` to overwrite existing skills. This was wrong because:
- Symlinks point to the same file — removing and recreating is a no-op
- The enrichment (`## Usage` injection) is idempotent — replaces, doesn't duplicate
- Simpler UX: `skill save` just works

**Added multi-target support**: Extended beyond Claude Code to support Cursor, Codex, and Copilot. Same symlink pattern, different directories.

## Files Modified/Created

### Core Changes

| File | Change |
|------|--------|
| `src/pflow/core/skill_service.py` | **NEW** — All business logic: enrichment, symlinks, scanning (~430 lines) |
| `src/pflow/cli/skills.py` | **NEW** — CLI command group with target_options decorator (~300 lines) |
| `src/pflow/cli/main_wrapper.py` | Added `"skill"` routing block |
| `src/pflow/core/workflow_manager.py` | Added `"skill"` to RESERVED_NAMES, frontmatter name override in `load()`/`list_all()` |
| `src/pflow/core/workflow_save_service.py` | Added `"skill"` to reserved names, re-enrich hook after save |
| `src/pflow/execution/formatters/history_formatter.py` | Added `format_workflow_history()` function |
| `src/pflow/cli/commands/workflow.py` | Added `history` subcommand |

### Test Files

| File | Coverage |
|------|----------|
| `tests/test_core/test_skill_service.py` | 24 tests — enrichment, symlinks, scanning, re-enrichment |
| `tests/test_cli/test_skills.py` | 14 tests — CLI commands with mocked services |
| `tests/test_execution/formatters/test_history_formatter.py` | 2 tests — formatter behavior |
| `tests/test_cli/test_workflow_commands.py` | 3 new tests — history CLI command |

## Integration Points & Dependencies

### Incoming Dependencies

- **AI coding tools** → skill files via symlinks (`SKILL.md`)
- **`pflow workflow save --force`** → `re_enrich_if_skill()` hook

### Outgoing Dependencies

- **`WorkflowManager`** — `_split_frontmatter_and_body()`, `_serialize_with_frontmatter()` for enrichment
- **markdown parser** — Enriched files must still parse (## Usage is ignored)

### Shared Store Keys

None — this feature doesn't touch execution.

## Architectural Decisions & Tradeoffs

### Key Decisions

| Decision | Reasoning | Alternative |
|----------|-----------|-------------|
| Symlinks not copies | Single source of truth, auto-updates | Copies would drift |
| Enrich saved file, not skill file | Symlink points to saved file, skill IS the saved file | Separate skill files would duplicate |
| No `--force` flag | Symlink recreation is no-op, enrichment is idempotent | Force flag implied destructive behavior that didn't exist |
| Multi-target via flags | One command saves to multiple tools | Separate commands per tool would be tedious |
| `SKILL_TARGETS` dict | Single source of truth for tool configs | Hardcoded paths would diverge |
| `target_options` decorator | DRY — adds same flags to save/remove | Duplicate click.option() calls |

### Frontmatter Position

`name` and `description` are placed **at TOP of frontmatter** using dict merge:
```python
frontmatter = {"name": name, "description": description, **frontmatter}
```
This ensures Claude Code (which reads YAML top-to-bottom) sees skill metadata first.

### Technical Debt

None incurred — implementation is clean and follows existing patterns.

## Testing Implementation

### Test Strategy

- **Service layer**: Direct tests using `tmp_path` for file isolation
- **CLI layer**: Mock service functions at import boundary
- **End-to-end**: `test_skill_symlink_readable_as_valid_skill` — full agent experience

### Critical Test Cases

| Test | What It Validates |
|------|-------------------|
| `test_skill_symlink_readable_as_valid_skill` | Full agent experience: save → enrich → symlink → read via symlink → valid skill content |
| `test_enrich_replaces_existing_usage` | ## Usage replacement (not duplication) on re-enrichment |
| `test_find_pflow_skills_ignores_non_pflow` | Only pflow symlinks returned, not native skills |
| `test_re_enrich_restores_usage_section_after_resave` | Re-save hook actually restores enrichment |

## Unexpected Discoveries

### Gotchas

1. **`_split_frontmatter_and_body()` is effectively static** — Doesn't use `self`, so we can call it on any WorkflowManager instance without initialization concerns.

2. **## Usage is silently ignored by parser** — Unknown `##` sections are skipped during parse, so enrichment doesn't break execution.

3. **Symlink target resolution** — Must handle both absolute and relative targets. Used `os.readlink()` + conditional resolution.

4. **Copilot has different personal/project paths** — `.github/skills/` (project) vs `~/.copilot/skills/` (personal). All other tools use same subdir for both.

### Edge Cases

- **Broken symlinks**: Show `[broken link]` in list, provide fix commands
- **Same workflow in multiple tools/scopes**: All shown, grouped by workflow name
- **Workflow deleted after skill creation**: Symlink becomes broken, detectable via `is_valid`

## Patterns Established

### Config-Driven Target System

```python
SKILL_TARGETS: dict[str, tuple[str, str]] = {
    "claude": (".claude/skills", ".claude/skills"),
    "cursor": (".cursor/skills", ".cursor/skills"),
    "codex": (".agents/skills", ".agents/skills"),
    "copilot": (".github/skills", ".copilot/skills"),
}
TARGET_LABELS: dict[str, str] = {...}
DEFAULT_TARGET = "claude"
```

Adding a new tool = update two dicts + add one line in `target_options` decorator.

### Flag Decorator Pattern

```python
def target_options(action: str) -> Callable[[F], F]:
    """Decorator that adds --personal, --cursor, --codex, --copilot options."""
    def decorator(func: F) -> F:
        func = click.option("--copilot", ...)(func)
        # ... more options
        return func
    return decorator

@skill.command(name="save")
@target_options("Save to")  # Help text varies by action
def save_skill(...):
```

### Idempotent Operations

The `skill save` command demonstrates idempotent design:
- If skill doesn't exist → creates symlink → "Published"
- If skill exists → just re-enriches → "Updated"
- No `--force` needed — the operation is always safe

## Breaking Changes

None — new feature, no existing interfaces modified.

## AI Agent Guidance

### Quick Start for Related Tasks

1. **Read first**: `src/pflow/core/skill_service.py` — all business logic
2. **Then**: `src/pflow/cli/skills.py` — CLI integration
3. **Pattern to follow**: `SKILL_TARGETS` config dict for adding new tools

### How to Add a New Tool Target

1. Add to `SKILL_TARGETS` in `skill_service.py`:
   ```python
   "newtool": (".newtool/skills", ".newtool/skills"),
   ```
2. Add to `TARGET_LABELS`:
   ```python
   "newtool": "New Tool",
   ```
3. Add flag in `target_options()` decorator in `skills.py`:
   ```python
   func = click.option("--newtool", ...)(func)
   ```
4. Add to `_get_targets_from_flags()`:
   ```python
   ("newtool", newtool)
   ```

### Common Pitfalls

1. **Don't use `--force` pattern for symlinks** — Symlinks pointing to same file don't need force semantics
2. **Test with real symlinks** — Don't mock `os.symlink()`, use `tmp_path` for real file operations
3. **Check both symlink existence AND broken state** — `path.exists()` returns False for broken symlinks, use `path.is_symlink()` to detect them

### Test-First Recommendations

When modifying skill functionality:
1. Run `pytest tests/test_core/test_skill_service.py -v` — service logic
2. Run `pytest tests/test_cli/test_skills.py -v` — CLI behavior
3. The end-to-end test `test_skill_symlink_readable_as_valid_skill` is the most important — it validates the full agent experience

---

*Generated from implementation context of Task 119*
