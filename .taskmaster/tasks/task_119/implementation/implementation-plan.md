# Task 119: Implementation Plan

## Architecture Overview

```
pflow skill save release-announcements [--personal] [--force]
        │
        ▼
┌─ src/pflow/cli/skills.py ─────────────────────┐
│  Click command group (skill save/list/remove)  │
└────────────────┬───────────────────────────────┘
                 │
                 ▼
┌─ src/pflow/core/skill_service.py ──────────────┐
│  Business logic:                                │
│  - enrich_workflow()     (frontmatter + usage)  │
│  - create_skill_symlink()                       │
│  - find_pflow_skills()   (scan for symlinks)    │
│  - remove_skill()                               │
│  - re_enrich_if_skill()  (post-save hook)       │
│  - generate_usage_section() (from IR inputs)    │
└────────────────┬───────────────────────────────┘
                 │ uses
                 ▼
┌─ src/pflow/core/workflow_manager.py ───────────┐
│  Existing: _split_frontmatter_and_body()       │
│  Existing: _serialize_with_frontmatter()       │
│  Existing: load(), exists(), get_path()        │
│  Modified: _name_from_path() → delegates       │
│  Modified: load(), list_all() → name override  │
└────────────────────────────────────────────────┘
```

## Verified Assumptions (post-codebase-search)

1. `_split_frontmatter_and_body()` and `_serialize_with_frontmatter()` don't use `self` — effectively static. Safe to call on any WorkflowManager instance.
2. After frontmatter split, body starts with `# Title` (leading `\n` stripped by `body.lstrip("\n")`). First `##` section varies (`## Inputs`, `## Steps`, or `## Outputs`).
3. `get_path()` returns absolute resolved path via `.resolve()` — safe as symlink target.
4. Save hook at line 296 in `save_workflow_with_options()` — between `manager.save()` and `return`. Both CLI and MCP callers use this function.
5. Symlinks work on macOS. WorkflowManager never encounters skill symlinks (they're in `.claude/skills/`, not `~/.pflow/workflows/`).
6. `delete_draft_safely()` refuses to delete symlinks — doesn't affect us since skill symlinks are outside the workflows directory.
7. `_format_example_usage_section()` does NOT skip `stdin: true` inputs — our `generate_usage_section()` must handle this explicitly.
8. No `is_likely_workflow_name()` function exists — routing is purely the `if/elif` chain in `main_wrapper.py`.

## Implementation Phases

### Phase 1: Skill service core (`src/pflow/core/skill_service.py`)

This is the brain — all business logic, no CLI concerns. Testable in isolation.

#### 1a. Usage section generation

```python
def generate_usage_section(workflow_name: str, ir: dict[str, Any]) -> str:
```

Builds the `## Usage` markdown section from the workflow's IR inputs. Reuses the pattern from `workflow_describe_formatter.py:_format_example_usage_section()` — iterate `ir["inputs"]`, collect required params (where `required` is `True` or missing), format as `param=<value>`.

**Template** (hardcoded string with one dynamic part — the example command):

````markdown
## Usage

If you are unsure this is exactly what the user wants to execute, ask the user if they want to run this workflow. If any required inputs are missing, ask the user to provide them.
Always ask the user before modifying or extending the workflow or reading the instructions.

```bash
# Execute this workflow directly:
pflow {name} {required_param1}=<value> {required_param2}=<value>

# To modify or extend - read all 3 parts IN FULL (do not truncate):
pflow instructions create --part 1
pflow instructions create --part 2
pflow instructions create --part 3
```

> Pflow and all dependencies should be installed, working and ready to use.

---
````

**Edge cases**:
- No inputs → command is just `pflow {name}` (no params)
- All optional → same, no params shown (optional params are omitted)
- `stdin: true` inputs → skip from command (they're piped, not CLI args). Note: the existing `_format_example_usage_section()` in `workflow_describe_formatter.py` does NOT handle this — it includes stdin inputs as `param=<value>`. Our implementation must explicitly check `config.get("stdin") is True` and exclude those. Pattern: `_find_stdin_input()` in `cli/main.py:3101-3114`.

#### 1b. Workflow enrichment

```python
def enrich_workflow(workflow_path: Path, name: str, description: str, ir: dict[str, Any]) -> None:
```

Read-modify-write on the saved workflow file at `~/.pflow/workflows/{name}.pflow.md`:

1. Read file content
2. `_split_frontmatter_and_body()` → (frontmatter_dict, body_str)
3. Add `name` and `description` to frontmatter dict
4. Inject or replace `## Usage` in body:
   - **Find**: Look for `## Usage` line in body
   - **If found**: Find next `##` line after it (or end of string). Replace everything between.
   - **If not found**: Find first `##` line in body. Insert `## Usage` section + `\n` before it.
   - **If no `##` at all** (edge case — workflow has no sections header visible in body after H1): append at end
5. `_serialize_with_frontmatter()` → reassemble
6. Write atomically (temp file + `os.replace()`)

**Why reuse WorkflowManager helpers**: `_split_frontmatter_and_body()` and `_serialize_with_frontmatter()` are the exact patterns needed. But they're instance methods on WorkflowManager. Two options:
- **Option A**: Instantiate WorkflowManager and call the methods. Simple, but they're "private" (`_` prefix).
- **Option B**: Extract to standalone functions. Cleaner but touches WorkflowManager.

**Decision**: Option A for now. The `_` prefix is a convention, not enforcement. The skill service is a peer module in `core/` — it's an internal consumer. If this bothers us later, we extract.

Actually, looking more carefully: the `_split_frontmatter_and_body` and `_serialize_with_frontmatter` methods don't use `self` at all — they're effectively static. We can call them on any WorkflowManager instance. The skill service already needs a WorkflowManager to check `exists()`, `get_path()`, and `load()`.

#### 1c. Symlink management

```python
def create_skill_symlink(workflow_path: Path, skill_name: str, scope: str, project_dir: Path | None = None) -> Path:
```

- `scope` is `"project"` or `"personal"`
- Project dir defaults to `Path.cwd()`
- Creates: `{base}/.claude/skills/{skill_name}/SKILL.md` → `workflow_path`
- Creates parent directories as needed (`mkdir(parents=True, exist_ok=True)`)
- Returns the symlink path
- Raises if symlink already exists and force not specified (handled by caller)

```python
def remove_skill(skill_name: str, scope: str, project_dir: Path | None = None) -> bool:
```

- Removes symlink and parent directory
- Returns True if removed, False if not found

#### 1d. Symlink scanning

```python
@dataclass
class SkillInfo:
    name: str
    scope: str  # "project" or "personal"
    symlink_path: Path
    target_path: Path
    is_valid: bool  # symlink resolves to existing file

def find_pflow_skills(project_dir: Path | None = None, workflows_dir: Path | None = None) -> list[SkillInfo]:
```

- Scans `.claude/skills/*/SKILL.md` (project) and `~/.claude/skills/*/SKILL.md` (personal)
- Filters to only symlinks whose target is under `~/.pflow/workflows/`
- `is_valid = symlink.resolve().exists()`
- Returns list sorted by (scope, name)

```python
def find_skill_for_workflow(workflow_name: str, project_dir: Path | None = None) -> list[SkillInfo]:
```

- Convenience wrapper: calls `find_pflow_skills()`, filters to those whose target filename matches `{workflow_name}.pflow.md`
- Used by re-save detection

#### 1e. Re-enrichment hook

```python
def re_enrich_if_skill(workflow_name: str, project_dir: Path | None = None) -> None:
```

- Calls `find_skill_for_workflow(workflow_name)`
- If any skills found, re-enriches the saved workflow (calls `enrich_workflow()`)
- Called after `pflow workflow save --force`

---

### Phase 2: Name derivation consolidation

#### 2a. Shared utility function

Add to `src/pflow/core/workflow_manager.py` (or a new `name_utils.py` — but keeping it in workflow_manager avoids a new file for one function):

```python
def derive_workflow_name(path: Path, metadata: dict[str, Any] | None = None) -> str:
    """Derive workflow name, with optional frontmatter name override."""
    if metadata and metadata.get("name"):
        return metadata["name"]
    name = path.stem
    return name[:-6] if name.endswith(".pflow") else name
```

Make it a module-level function (not a method). `_name_from_path` delegates to it.

#### 2b. Update `load()` and `list_all()`

In `WorkflowManager.load()` (line 267):
```python
# Current:
"name": name,
# New:
"name": fm.get("name", name),
```

In `WorkflowManager.list_all()` (line 335):
```python
# Current:
"name": name,
# New:
"name": fm.get("name", name),
```

This is a 1-line change in each method. The `name` parameter/variable serves as the fallback.

#### 2c. Update CLI name derivation

In `cli/main.py:_setup_workflow_execution()` — this path runs before parsing, so it doesn't have frontmatter. Leave as-is. The frontmatter override only applies to `WorkflowManager.load()` and `list_all()` which parse the file.

---

### Phase 3: CLI command group (`src/pflow/cli/skills.py`)

#### 3a. Command group structure

```python
@click.group(name="skill")
def skill() -> None:
    """Manage Claude Code skills."""
    pass

@skill.command(name="save")
@click.argument("workflow_name")
@click.option("--personal", is_flag=True, help="Save to personal skills (~/.claude/skills/)")
@click.option("--project", is_flag=True, default=True, help="Save to project skills (.claude/skills/) [default]")
@click.option("--force", is_flag=True, help="Overwrite existing skill")
def save_skill(workflow_name: str, personal: bool, project: bool, force: bool) -> None:
    ...

@skill.command(name="list")
def list_skills() -> None:
    ...

@skill.command(name="remove")
@click.argument("workflow_name")
@click.option("--personal", is_flag=True)
@click.option("--project", is_flag=True, default=True)
def remove_skill(workflow_name: str, personal: bool, project: bool) -> None:
    ...
```

**Scope flag handling**: `--personal` and `--project` are mutually exclusive. If `--personal` is passed, scope is `"personal"`. Otherwise default is `"project"`. Use `click.option` with a callback or just check in the function body:

```python
if personal and project and personal:  # both explicitly passed
    click.echo("Error: --personal and --project are mutually exclusive", err=True)
    sys.exit(1)
scope = "personal" if personal else "project"
```

Actually, simpler: use a single `--personal` flag. Default is project. No `--project` flag needed (it's the default).

```python
@click.option("--personal", is_flag=True, help="Save to personal skills (~/.claude/skills/) instead of project")
```

#### 3b. `save_skill` flow

1. Validate workflow exists: `WorkflowManager().exists(workflow_name)`
2. Load workflow: `wm.load(workflow_name)` → get IR, description
3. Get file path: `wm.get_path(workflow_name)`
4. Check if skill already exists: `find_skill_for_workflow(workflow_name)` filtered by scope
5. If exists and not `--force`: error
6. If exists and `--force`: `remove_skill()` first
7. Enrich: `enrich_workflow(path, name, description, ir)`
8. Create symlink: `create_skill_symlink(path, name, scope)`
9. Display success message

#### 3c. `list_skills` flow

1. `find_pflow_skills()` → list of SkillInfo
2. If empty: "No pflow skills found."
3. Otherwise: table with name, scope, status

```
pflow skills:

  release-announcements  project   ✓
  my-tool                personal  ✓
  broken-skill           project   ✗ (broken link)
```

#### 3d. `remove_skill` flow

1. Find skill: `find_skill_for_workflow(workflow_name)` filtered by scope
2. If not found: error
3. `remove_skill(workflow_name, scope)`
4. Display success

#### 3e. Reserved names update

Add `"skill"` to BOTH reserved name sets (they must stay in sync):

- `src/pflow/core/workflow_save_service.py:RESERVED_WORKFLOW_NAMES` (line 20)
- `src/pflow/core/workflow_manager.py:RESERVED_NAMES` (line 78)

Without this, `pflow workflow save --name skill` would create a workflow that conflicts with the `pflow skill` command routing.

#### 3f. Router update (`main_wrapper.py`)

Add routing block for `"skill"`:

```python
elif first_arg == "skill":
    from .skills import skill
    original_argv = sys.argv[:]
    try:
        skill_index = sys.argv.index("skill")
        sys.argv = [sys.argv[0], *sys.argv[skill_index + 1:]]
        skill()
    finally:
        sys.argv = original_argv
```

---

### Phase 4: Re-save integration

#### 4a. Hook in `save_workflow_with_options()`

In `src/pflow/core/workflow_save_service.py`, after the successful save in `save_workflow_with_options()`:

```python
# After line 297: return Path(saved_path)

# Re-enrich if this workflow is published as a skill
try:
    from pflow.core.skill_service import re_enrich_if_skill
    re_enrich_if_skill(name)
except Exception:
    logger.warning(f"Failed to re-enrich skill for '{name}'", exc_info=True)
```

The lazy import avoids circular dependencies. The try/except ensures save never fails due to skill enrichment. The re-enrichment is best-effort.

**Important**: This only triggers when `force=True` (because without force, a re-save of an existing workflow raises `FileExistsError` before reaching this point). And `force=True` means delete + save — so the file is fresh and needs re-enrichment.

---

### Phase 5: Tests

#### 5a. `tests/test_core/test_skill_service.py` (~20-25 tests)

Core service tests using `tmp_path` for isolation:

**Usage section generation:**
- `test_generate_usage_with_required_inputs` — required params appear in command
- `test_generate_usage_with_no_inputs` — command has no params
- `test_generate_usage_with_optional_only` — no params shown
- `test_generate_usage_skips_stdin_inputs` — `stdin: true` inputs omitted

**Enrichment:**
- `test_enrich_adds_name_to_frontmatter` — name field added
- `test_enrich_adds_description_to_frontmatter` — description field added
- `test_enrich_injects_usage_section` — `## Usage` appears in body
- `test_enrich_replaces_existing_usage` — re-enrichment replaces, doesn't duplicate
- `test_enrich_preserves_other_frontmatter` — existing metadata fields survive
- `test_enrich_preserves_workflow_body` — `## Steps`, `## Inputs`, etc. unchanged
- `test_enriched_workflow_still_parses` — `parse_markdown()` on enriched file succeeds
- `test_enriched_workflow_still_executes` — IR from enriched file matches original

**Symlink management:**
- `test_create_skill_symlink_project` — creates at `.claude/skills/{name}/SKILL.md`
- `test_create_skill_symlink_personal` — creates at `~/.claude/skills/{name}/SKILL.md`
- `test_symlink_resolves_to_workflow` — symlink target is correct
- `test_remove_skill_deletes_symlink_and_dir` — cleanup works

**Scanning:**
- `test_find_pflow_skills_finds_project_skills` — detects project symlinks
- `test_find_pflow_skills_finds_personal_skills` — detects personal symlinks
- `test_find_pflow_skills_ignores_non_pflow` — non-symlinks and non-pflow targets ignored
- `test_find_pflow_skills_detects_broken_links` — `is_valid=False` for broken
- `test_find_skill_for_workflow` — filters by workflow name

**Re-enrichment:**
- `test_re_enrich_after_save` — enrichment restored after force save

#### 5b. `tests/test_cli/test_skills.py` (~10-15 tests)

CLI integration tests using Click's `CliRunner`:

- `test_skill_save_creates_symlink` — end-to-end save
- `test_skill_save_workflow_not_found` — error message
- `test_skill_save_already_exists` — error without --force
- `test_skill_save_force_overwrites` — --force replaces
- `test_skill_save_personal_flag` — --personal uses home dir
- `test_skill_list_shows_skills` — list output format
- `test_skill_list_empty` — "No pflow skills found"
- `test_skill_remove_deletes` — successful removal
- `test_skill_remove_not_found` — error message

#### 5c. `tests/test_core/test_workflow_manager_name.py` (or add to existing test file)

- `test_load_uses_frontmatter_name` — name from frontmatter overrides filename
- `test_load_falls_back_to_filename` — no frontmatter name → filename
- `test_list_all_uses_frontmatter_name` — list respects override

---

## File Inventory

### New files (4)
| File | Purpose | Approx. lines |
|------|---------|---------------|
| `src/pflow/cli/skills.py` | CLI command group | ~120 |
| `src/pflow/core/skill_service.py` | Business logic | ~200 |
| `tests/test_cli/test_skills.py` | CLI tests | ~150 |
| `tests/test_core/test_skill_service.py` | Service tests | ~300 |

### Modified files (4)
| File | Change | Lines touched |
|------|--------|---------------|
| `src/pflow/cli/main_wrapper.py` | Add `"skill"` routing | ~10 |
| `src/pflow/core/workflow_manager.py` | Name override in `load()`/`list_all()`, extract `derive_workflow_name()`, add `"skill"` to `RESERVED_NAMES` | ~12 |
| `src/pflow/core/workflow_save_service.py` | Post-save re-enrichment hook, add `"skill"` to `RESERVED_WORKFLOW_NAMES` | ~10 |
| Reserved names (2 files above) | Add `"skill"` to both sets — they must stay in sync | ~2 |

### Total estimate: ~800 lines new code + ~28 lines modified

---

## Execution Order

Phases can be partially parallelized:

```
Phase 1 (skill_service.py)  ──→  Phase 3 (CLI)  ──→  Phase 5 (tests)
Phase 2 (name consolidation) ─┘  Phase 4 (hook)  ─┘
```

Phase 1 and 2 are independent. Phase 3 depends on Phase 1. Phase 4 depends on Phase 1. Phase 5 depends on all.

**Recommended serial order**: 1 → 2 → 3 → 4 → 5 (since phases are small enough that parallelization overhead isn't worth it).

---

## `## Usage` Injection — Precise Algorithm

The body string looks like:

```
# Release Announcements\n\nCreates release announcements...\n\n## Inputs\n\n### version\n...
```

**Injection** (no existing `## Usage`):

```python
# Find first ## in body
match = re.search(r'^## ', body, re.MULTILINE)
if match:
    insert_pos = match.start()
    body = body[:insert_pos] + usage_section + "\n\n" + body[insert_pos:]
else:
    # No ## found (unusual — workflow has no sections visible in body?)
    body = body.rstrip() + "\n\n" + usage_section + "\n"
```

**Replacement** (existing `## Usage`):

```python
# Find ## Usage
usage_match = re.search(r'^## Usage\b.*$', body, re.MULTILINE)
if usage_match:
    # Find next ## after ## Usage
    rest = body[usage_match.end():]
    next_section = re.search(r'^## ', rest, re.MULTILINE)
    if next_section:
        end_pos = usage_match.end() + next_section.start()
    else:
        end_pos = len(body)
    body = body[:usage_match.start()] + usage_section + "\n\n" + body[end_pos:].lstrip("\n")
```

This is ~15 lines of logic. Regex on `^## ` with `re.MULTILINE` finds section boundaries reliably.

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| `## Usage` injection corrupts body | High | Test: parse enriched file, verify IR matches original |
| Symlink breaks on Windows | Low | pflow doesn't support Windows (Task 116) |
| Re-enrichment fails silently | Low | Logged warning, save still succeeds |
| `.claude/` dir creation fails (permissions) | Low | Standard `mkdir(parents=True)` with clear error |
| Name in frontmatter diverges from filename | Medium | Frontmatter name only set by skill service, not manually |
