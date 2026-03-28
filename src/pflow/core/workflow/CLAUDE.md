# Workflow Subdirectory

Workflow lifecycle management: save, load, validate, discover, publish.

## Module Structure

```
core/workflow/
├── __init__.py              # Re-exports all public symbols
├── manager.py               # WorkflowManager: save/load/list/delete workflows (folder-based)
├── save_service.py          # Shared save operations for CLI + MCP (with dependency bundling)
├── dependency_discovery.py  # Recursive file dependency scanner for bundling
├── validator.py             # Unified 7-step validation orchestrator
├── data_flow.py             # Execution order (topological sort) and dependency validation
├── status.py                # WorkflowStatus enum: SUCCESS/DEGRADED/FAILED
├── skill_service.py         # Publish workflows as AI agent skills (symlinks)
├── context.py               # Build workflow context for discovery (build_workflows_context)
├── discovery.py             # LLM-powered workflow discovery (discover_workflow → WorkflowMatch)
├── prompts/
│   └── discovery.md         # Workflow discovery prompt template
└── CLAUDE.md
```

## Internal Dependencies

```
save_service.py
  ├── manager.py              (top-level import)
  ├── validator.py            (lazy import in _validate_and_normalize_ir())
  ├── dependency_discovery.py (lazy import in _discover_and_bundle_deps())
  └── skill_service.py        (lazy import in save_workflow_with_options())

validator.py
  └── data_flow.py       (lazy import in _validate_data_flow())

skill_service.py
  └── manager.py         (top-level import)
```

No cycles. `save_service → validator` and `save_service → skill_service` are lazy (inside functions).

## Key Symbols by File

| File | Key Exports |
|------|-------------|
| `manager.py` | `WorkflowManager` |
| `save_service.py` | `load_and_validate_workflow`, `save_workflow_with_options`, `validate_workflow_name`, `delete_draft_safely`, `generate_workflow_metadata` |
| `dependency_discovery.py` | `Dependency`, `discover_dependencies` |
| `validator.py` | `WorkflowValidator` (static `.validate()` method — 8-step pipeline) |
| `data_flow.py` | `validate_data_flow`, `build_execution_order`, `CycleError` |
| `status.py` | `WorkflowStatus` (enum: SUCCESS, DEGRADED, FAILED) |
| `skill_service.py` | `SkillInfo`, `enrich_workflow`, `create_skill_symlink`, `find_pflow_skills`, `remove_skill`, `re_enrich_if_skill` |

## External Consumers

| Consumer | Uses |
|----------|------|
| `cli/main.py` | `WorkflowManager`, `WorkflowValidator` |
| `cli/commands/workflow.py` | `WorkflowManager`, save_service functions |
| `cli/commands/skills.py` | Most of skill_service |
| `execution/` | `WorkflowManager`, `WorkflowValidator`, `WorkflowStatus` |
| `runtime/` | `WorkflowManager` |
| `mcp_server/` | `WorkflowManager`, `WorkflowValidator`, save_service functions |

Import from specific modules: `from pflow.core.workflow.manager import WorkflowManager`.

## Non-Obvious Details

### manager.py

**Storage format**: Folder-based at `~/.pflow/workflows/{name}/{name}.pflow.md`. Each workflow is a directory containing its entry point and any bundled file dependencies (sub-workflows, prompts, scripts):
```
~/.pflow/workflows/
└── my-workflow/
    ├── my-workflow.pflow.md      # entry point (with YAML frontmatter)
    ├── prompts/
    │   └── system.md             # bundled file dependency
    └── sub-task.pflow.md         # bundled sub-workflow
```

The entry point has YAML frontmatter for system metadata (timestamps, execution stats). The markdown body is preserved exactly as the author wrote it.

- Metadata is flat (no `rich_metadata` wrapper)
- Workflow `name` is the directory name
- `description` extracted from H1 prose during `load()`, not stored separately in metadata
- `load()` returns flat metadata dict with parsed IR; `load_ir()` returns just the IR dict (for execution)
- Atomic operations: `tempfile.mkdtemp()` + `os.rename()` for creates, `os.replace()` for metadata updates
- Path helpers: `_workflow_dir(name)` returns dir, `_entry_point(name)` returns entry point file
- `save()` accepts optional `dependencies: list[tuple[str, Path]]` for bundling files into the folder

### validator.py

Unified validation orchestrator. Replaces scattered validation that previously existed in multiple places.

**8-step validation pipeline**:
1. Structural (IR schema) — always runs
2. Stdin inputs — only one `stdin: true` allowed per workflow
3. Data flow (execution order, dependencies) — always runs
4. Templates (variable resolution) — if params provided
5. Node types (registry verification) — unless `skip_node_types=True`
6. Output sources — validates `${node.key}` refs in outputs, with fuzzy "did you mean?" suggestions
7. Unknown param warnings — flags params not in node interface metadata (warnings, not errors)
8. Sub-workflow validation — recursive validation of referenced child workflows (file, saved name, inline IR)

### data_flow.py

Uses Kahn's algorithm for topological sort. Catches: forward references, circular dependencies, references to non-existent nodes, undefined input parameters.

**Pflow vs bash syntax**: Uses positive pattern matching (`_PFLOW_VAR_RE` compiled from `TemplateResolver._VAR_NAME_PATTERN`) to identify valid pflow variable refs. Refs that don't match (bash syntax like `${#array[@]}`, `${var:-default}`, `${var%%pattern}`, or truncated nested templates) are skipped. Supports a `check_inputs` parameter: `True` (default, used by `WorkflowValidator`) checks undefined inputs; `False` (used by compiler) skips input checks since the compiler has `initial_params` not visible to data flow validation.

### save_service.py

**Reserved workflow names**: `null`, `undefined`, `none`, `test`, `settings`, `registry`, `workflow`, `mcp`, `skill`.

**`generate_workflow_metadata()`**: Stub — returns None unconditionally (planning module removed).

### skill_service.py

Publishes workflows as AI agent skills for Claude Code, Cursor, Codex, Copilot. **Symlink-based**: `{tool}/skills/{name}/SKILL.md` → `~/.pflow/workflows/{name}.pflow.md`.

**`enrich_workflow()`**: Injects `## Usage` section (with example command) and adds `name`/`description` to frontmatter.

**`re_enrich_if_skill()`**: Auto-called by `save_workflow_with_options()` after `--force` saves. Restores enrichment lost when the file was replaced.

### status.py

Tri-state: `SUCCESS` (all nodes clean), `DEGRADED` (completed with warnings, e.g., unresolved templates in permissive mode), `FAILED` (errors).

## Known Issues

**⚠️ Bug**: Claude Code requires `description` in frontmatter for skill discovery (workaround in `skill_service.py`).

## Key Lessons

**Race condition (Task 24)**: Initial tests were too shallow. Only proper concurrent tests discovered a critical race condition in `WorkflowManager.save()`. Fixed with atomic `os.link()`. Lesson: always test with real threads for file I/O. See `.taskmaster/tasks/task_24/task-review.md`.

**Content preservation**: Save operations store original markdown with YAML frontmatter prepended. The markdown body is never modified by metadata updates.

**Data flow validation gap**: Tests had execution order validation that production lacked — workflows passed validation but failed at runtime. Now unified in `WorkflowValidator`.
