# Task 119 Implementation Progress Log

## Starting Implementation
Read spec, implementation plan, and all key source files.

### Plan Summary
1. Phase 1: Skill service core (`src/pflow/core/skill_service.py`)
2. Phase 2: Name derivation consolidation in `workflow_manager.py`
3. Phase 3: CLI command group (`src/pflow/cli/skills.py`) + router update
4. Phase 4: Re-save integration hook in `workflow_save_service.py`
5. Phase 5: Tests

## Phase 1: skill_service.py
- Created `src/pflow/core/skill_service.py` with all business logic
- Functions: `generate_usage_section`, `_inject_or_replace_usage`, `enrich_workflow`, `create_skill_symlink`, `remove_skill`, `find_pflow_skills`, `find_skill_for_workflow`, `re_enrich_if_skill`
- SkillInfo dataclass for scan results
- Used existing `_split_frontmatter_and_body` / `_serialize_with_frontmatter` from WorkflowManager (they don't use self)
- Atomic file writes via tempfile + os.replace pattern

## Phase 2: Name derivation consolidation
- Updated `WorkflowManager.load()` line: `"name": fm.get("name", name)` — frontmatter name overrides filename
- Same change in `WorkflowManager.list_all()`
- Added "skill" to RESERVED_NAMES in workflow_manager.py

## Phase 3: CLI command group + routing
- Created `src/pflow/cli/skills.py` with `skill` Click group
- Commands: `save`, `list`, `remove`
- `--personal` flag (default is project scope)
- Added routing block in `main_wrapper.py` for `first_arg == "skill"`
- Added "skill" to RESERVED_WORKFLOW_NAMES in workflow_save_service.py

## Phase 4: Re-save integration
- Added post-save hook in `save_workflow_with_options()` that calls `re_enrich_if_skill(name)`
- Lazy import to avoid circular deps
- try/except ensures save never fails due to enrichment

## Phase 5: Tests
- `tests/test_core/test_skill_service.py` — 21 tests covering all service functions
- `tests/test_cli/test_skills.py` — 11 tests covering CLI commands
- Total: 32 new tests

## Manual End-to-End Testing (Round 1)
- `pflow skill --help` — shows save/list/remove commands
- `pflow skill save nonexistent-workflow` — clear error with save suggestion
- `pflow skill save directory-file-lister` — created symlink + enriched file
- Verified enriched file has name/description in frontmatter and ## Usage section
- `pflow directory-file-lister -p` — workflow still executes correctly after enrichment
- `pflow skill list` — shows skill with status
- `pflow skill save release-announcements` — shows required params in usage command
- `pflow skill remove release-announcements` — removes symlink
- `pflow workflow save --name skill` — blocked by reserved name

## DEVIATION: Removed --force flag

**Original plan**: `--force` flag required to overwrite existing skill

**Why it was wrong**: The symlink points to the same file, so removing and recreating it is a no-op. The only real effect is re-running enrichment, which is idempotent (replaces ## Usage, doesn't duplicate).

**New behavior**: `skill save` is idempotent
- If skill doesn't exist → creates symlink + enriches → "Published"
- If skill exists → just re-enriches → "Updated"

**Lesson**: The `--force` flag implied destructive behavior that didn't exist. Simpler is better.

## Manual End-to-End Testing (Round 2 — Gap Coverage)
- `--personal` flag — ✓ Creates symlink in ~/.claude/skills/
- Same workflow in both scopes — ✓ Both shown in list
- Remove from wrong scope — ✓ Shows "not found in X scope"
- Broken symlink detection — ✓ Shows "x (broken link)"
- Re-save detection — ✓ ## Usage restored with updated params after `workflow save --force`
- ## Usage replacement (not duplication) — ✓ Only 1 heading after re-enrichment
- Idempotent save — ✓ Second `skill save` shows "Updated" message

## Code Quality Fixes
- Fixed ruff SIM108: ternary operators for if-else blocks
- Fixed ruff SIM105: contextlib.suppress instead of try-except-pass
- Fixed ruff C901: extracted `_resolve_symlink_target()` and `_is_pflow_skill()` helpers to reduce complexity

## Final Verification
- `make test` — 3657 passed, 516 skipped
- `make check` — all linting, type checking, formatting pass
- No regressions

## Files Created (4)
- `src/pflow/core/skill_service.py` — Business logic (~280 lines)
- `src/pflow/cli/skills.py` — CLI commands (~100 lines)
- `tests/test_core/test_skill_service.py` — Service tests (~320 lines)
- `tests/test_cli/test_skills.py` — CLI tests (~200 lines)

## Files Modified (3)
- `src/pflow/cli/main_wrapper.py` — Added "skill" routing block
- `src/pflow/core/workflow_manager.py` — Added "skill" to RESERVED_NAMES, frontmatter name override in load()/list_all()
- `src/pflow/core/workflow_save_service.py` — Added "skill" to RESERVED_WORKFLOW_NAMES, re-enrich hook after save

## Self-Review and Additional Tests

After reviewing the spec carefully, added these additional tests to ensure comprehensive coverage:

### Re-enrichment tests (test_skill_service.py - TestReEnrichment class):
- `test_re_enrich_restores_usage_section_after_resave` — verifies enrichment is restored after workflow save --force
- `test_re_enrich_replaces_usage_not_duplicates` — verifies ## Usage section is replaced, not duplicated on multiple re-enrichments
- `test_re_enrich_no_op_when_no_skill` — verifies re-enrich does nothing when workflow has no skill

### Frontmatter name override tests (test_workflow_manager.py):
- `test_frontmatter_name_overrides_filename_in_load` — verifies frontmatter 'name' field takes precedence over filename
- `test_frontmatter_name_overrides_filename_in_list_all` — verifies list_all() uses frontmatter name
- `test_load_falls_back_to_filename_when_no_frontmatter_name` — verifies fallback behavior

### Re-save hook tests (test_workflow_save_service.py):
- `test_re_enriches_skill_after_save` — verifies re_enrich_if_skill is called after successful save
- `test_re_enrich_failure_does_not_fail_save` — verifies enrichment errors don't block save

## Final Test Count
- Total new tests: 41 (21 skill service + 12 CLI + 3 re-enrichment + 3 frontmatter override + 2 re-save hook)
- All 3658 tests pass
- All linting/type checks pass

## Additional Feature: `pflow workflow history` Command

Added `pflow workflow history <name>` command for agents to retrieve execution history and last used inputs.

### Files Modified
- `src/pflow/execution/formatters/history_formatter.py` — Added `format_workflow_history()` function
- `src/pflow/cli/commands/workflow.py` — Added `history` subcommand
- `src/pflow/core/skill_service.py` — Added history command hint to Usage section template
- `tests/test_execution/formatters/test_history_formatter.py` — Added 7 tests for `format_workflow_history()`
- `tests/test_cli/test_workflow_commands.py` — Added 6 tests for history CLI command
- `tests/test_core/test_skill_service.py` — Added assertion for history hint in Usage section

### Output Format
```
Execution History: release-announcements

Runs: 5
Last run: 2026-02-05 02:22:06
Status: Success

Last used inputs:
  slack_channel: C09ABC123
  version: 1.2.0
```

### Tests Added: 5 new tests (focused on behavior, not coverage)
- 2 formatter tests (TestFormatWorkflowHistory class)
- 3 CLI tests (TestWorkflowHistoryCommand class)

## Multi-Target Support Enhancement

Added support for multiple AI tools beyond Claude Code:

### New Targets
| Target | Project | Personal |
|--------|---------|----------|
| Claude Code (default) | `.claude/skills/` | `~/.claude/skills/` |
| Cursor | `.cursor/skills/` | `~/.cursor/skills/` |
| Codex | `.agents/skills/` | `~/.agents/skills/` |
| Copilot | `.github/skills/` | `~/.copilot/skills/` |

### New CLI Flags
```bash
pflow skill save my-workflow [--personal] [--cursor] [--codex] [--copilot]
# Default: Claude Code only
# Flags combine: --cursor --copilot saves to both

pflow skill list
# Shows all targets (scans all directories)

pflow skill remove my-workflow [--personal] [--cursor] [--codex] [--copilot]
# Default: Claude Code only
```

### Implementation Changes
- Added `SKILL_TARGETS` and `TARGET_LABELS` dicts in `skill_service.py`
- Updated `_get_skills_base_dir()` to take `target` parameter
- Updated `create_skill_symlink()`, `remove_skill()` to take `target`
- Updated `find_pflow_skills()` to scan all targets by default
- Added `target` field to `SkillInfo` dataclass
- CLI collects flags into list, loops over targets
- Error handling: continues with remaining targets if one fails

### Test Updates
- Updated all tests to use new `target` parameter
- Added `test_skill_save_multiple_targets` - verifies multi-target save
- Added `test_skill_remove_multiple_targets` - verifies multi-target remove
- Added `test_find_pflow_skills_finds_all_targets` - verifies scanning all targets

### Manual Testing
- `pflow skill save directory-file-lister --cursor --copilot` → created both symlinks
- `pflow skill list` → shows skills with target labels (Cursor, Copilot)
- `pflow skill remove directory-file-lister --cursor --copilot` → removed both

### Final Count
- 3666 tests pass, 516 skipped
- All linting/type checks pass

## UX Improvements to `skill list`

### Before
```
pflow skills:

  release-announcements     Copilot      project    + (ok)
  release-announcements     Cursor       project    + (ok)
```

### After
```
pflow skills:

  release-announcements
    → Copilot (project)
    → Cursor (project)
```

### Changes
- Grouped by workflow name (the thing that matters)
- Removed redundant `+ (ok)` — only show `[broken link]` when broken
- Added specific fix commands for broken links:
```
Broken link: the source workflow 'temp-broken' was deleted.
  To restore: pflow workflow save <file> --name temp-broken --force
  To remove:  pflow skill remove temp-broken --cursor --personal
```

## Improved Help Text

Updated `pflow skill --help` to show all supported tools upfront:
```
Supported tools (use flags like --cursor, --copilot):

  Claude Code (default)    .claude/skills/       ~/.claude/skills/
  Cursor                   .cursor/skills/       ~/.cursor/skills/
  Codex                    .agents/skills/       ~/.agents/skills/
  Copilot                  .github/skills/       ~/.copilot/skills/
```

Made `remove` command options consistent with `save` (added directory paths).

## DRY Refactor

Eliminated repetition between `save` and `remove` commands:

### New helpers
- `target_options(action)` decorator — adds `--personal`, `--cursor`, `--codex`, `--copilot` flags
- `_get_target_help(target, action)` — generates help text from `SKILL_TARGETS` config
- `_build_group_help()` — builds group help text dynamically from config

### Benefits
- Single source of truth: `SKILL_TARGETS` and `TARGET_LABELS` in `skill_service.py`
- Adding a new tool = update dicts + add one line in decorator
- Help text always in sync with actual behavior
- Directory paths derived from config, not hardcoded twice

## CLI Help Text Updates

Updated `pflow --help` to reflect Task 119 changes and hide gated features:

### Added to help
- `skill` command in Commands section: "Publish workflows as AI agent skills"
- Updated `workflow` description to mention `history`
- Skill examples in Examples section

### Hidden from help (gated features - still functional)
- `--trace-planner`, `--planner-timeout`, `--cache-planner`, `--planner-model` (planner gated)
- `--auto-repair`, `--no-update` (repair gated)
- `--save/--no-save` (planner-related)
- Removed Natural Language example and references

### Fixed formatting
- Examples section was broken due to Click's text wrapping
- Changed to compact format: `command    description` on same line
- Now renders cleanly at any terminal width

### Files modified
- `src/pflow/cli/main.py` — Help text and hidden options
- `tests/test_cli/test_main.py` — Updated assertions for new help text

## Test Review and Consolidation

Reviewed all Task 119 tests to ensure we're testing **important behavior**, not implementation details.

### Tests Removed (8 redundant tests)
Formatter tests removed:
- `test_with_failed_status` — Just testing "Failed" vs "Success" string, covered by happy path
- `test_without_inputs` — Subset of no-history case
- `test_with_empty_metadata` — Same behavior as no-history
- `test_with_none_metadata` — Same behavior as no-history
- `test_shows_redacted_values` — We're not doing sanitization, just displaying

CLI tests removed:
- `test_history_failed_status` — Same as happy path with different string
- `test_history_without_inputs` — Subset of happy path
- `test_history_shows_redacted_values` — Passthrough behavior, not our responsibility

### High-Value Test Added
Added `test_skill_symlink_readable_as_valid_skill` in TestSkillEndToEnd class:
- Tests the **full agent experience**: save → enrich → create symlink → read via symlink → valid skill content
- Verifies: name/description in frontmatter, ## Usage section with commands, workflow still parses and has inputs
- This is exactly what Claude Code does when reading a skill

### Tests Already Covered (no changes needed)
- Reserved name "skill" — Dynamically tested via `for reserved in RESERVED_WORKFLOW_NAMES` loop
- Re-enrichment hook — Tested in test_workflow_save_service.py
- Enriched workflow still parses — Tested in TestEnrichWorkflow

### Final Test Count
- 3663 tests pass, 516 skipped
- All linting/type checks pass
- Net change: -7 redundant tests, +1 high-value end-to-end test
