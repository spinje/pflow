# Task 130: Workflow Bundling on Save

## Description

Change `pflow workflow save` to package workflows and all their file dependencies (sub-workflows, external prompt files, code files) into a self-contained folder. Fixes an existing bug where saved workflows with sub-workflow references break, and supports the new file references from Task 129.

## Status
done

## Completed
2026-03-22

## Priority

high

## Problem

`pflow workflow save` copies a single `.pflow.md` file to `~/.pflow/workflows/`. This breaks when the workflow references other files:

1. **Sub-workflow references already break today**: `- workflow: ./sub-workflow.pflow.md` resolves relative to the saved location (`~/.pflow/workflows/`), where the sub-workflow doesn't exist. This is an existing bug.
2. **File references (Task 129) would also break**: `- prompt: ./prompts/foo.md` would fail for the same reason.
3. **Skills publishing inherits the problem**: Skills are symlinks to saved workflows, so broken saved workflows mean broken skills.

The music-generation project has 4 workflow files that must move together: `lyrics-generator.pflow.md` (orchestrator) + 3 sub-workflows. Saving the orchestrator alone produces a broken workflow.

## Solution

Save workflows as folders instead of single files. `pflow workflow save my-workflow` creates:

```
~/.pflow/workflows/my-workflow/
├── my-workflow.pflow.md              # entry point (named after workflow)
├── fetch-source.pflow.md             # sub-workflow dependency
├── song-creator.pflow.md             # sub-workflow dependency
├── prompts/                          # preserved directory structure
│   └── write-lyrics.prompt.md
└── scripts/
    └── build-file-list.py
```

The dependency tree is discovered by parsing the workflow and its dependencies recursively, collecting all referenced files. The relative path structure from the original project is preserved so all references keep working without path rewriting.

## Design Decisions

- **Always a folder, even for single-file workflows**: Avoids `WorkflowManager` needing two code paths (file vs. folder) for every operation. Avoids migration when a workflow later gains dependencies. The "wasteful" empty folder for simple workflows is invisible — users interact via `pflow workflow list`, not `ls`.
- **`{name}.pflow.md` entry point, not `WORKFLOW.pflow.md`**: The filename carries meaning in logs, error messages, and when referenced outside the folder context. The "tooling simplicity" argument for a canonical name was examined and found to be negligible — one string concatenation vs. one constant.
- **Preserve relative structure, don't enforce layout**: If the original project has `./prompts/foo.md`, the saved copy has `./prompts/foo.md`. No path rewriting, no reorganization. What works locally works when saved.
- **Sub-workflows saved by reference (name), not bundled**: If a sub-workflow is referenced by name (`- workflow: my-helper`), it's a shared dependency that lives in its own saved folder. It is NOT copied into the parent's bundle. Only file-path references (`- workflow: ./helper.pflow.md`) are bundled. This avoids duplication and ensures edits to the shared workflow propagate.
- **Recursive dependency discovery**: Parse the workflow, find all file references and sub-workflow file references, recursively parse those, collect the full dependency tree. Detect circular references.

## Dependencies

- Task 129: External File References — Defines the file reference mechanism that this task needs to discover and bundle. Can be developed in parallel (bundling logic for sub-workflows is independent of file references), but full integration requires Task 129.

## Requirements

### Save Operation

- `pflow workflow save <name>` creates `~/.pflow/workflows/<name>/` directory
- Entry point file is `<name>.pflow.md` inside the directory
- All file dependencies (sub-workflows by path, external prompts/code/scripts) are copied preserving relative directory structure
- Sub-workflows referenced by name are NOT bundled (they're independent saved workflows)
- YAML frontmatter is prepended to the entry point file (same as current behavior)
- Atomic save operation (don't leave partial directories on failure)
- `--force` overwrites existing saved workflow folder

### Dependency Discovery

- Parse workflow IR to find all file references (Task 129's resolved params + `- workflow: ./path` references)
- Recursively parse sub-workflows to find their dependencies
- Detect circular references and error clearly
- Report the full dependency tree to the user during save

### Load Operation

- `WorkflowManager.load()` handles folder-based workflows: looks for `<name>/<name>.pflow.md`
- `WorkflowManager.load_ir()` returns IR from the entry point file
- `_pflow_workflow_file` is set to the saved entry point path, so relative references resolve correctly within the saved folder

### List and Delete

- `pflow workflow list` works with folder-based workflows (lists directory names)
- `pflow workflow delete` removes the entire folder
- Metadata operations (update execution count, etc.) modify the entry point file's frontmatter

### Skills Integration

- Skill symlinks point to `~/.pflow/workflows/<name>/<name>.pflow.md` (updated path)
- `re_enrich_if_skill()` works with the new folder structure
- Published skills with file dependencies work correctly

### Migration

- Existing single-file saved workflows continue to work (load checks both locations)
- OR: provide a one-time migration that wraps existing files in folders
- Decision point: migrate automatically on first access, or provide a migration command

### Scope Boundaries

- **In scope**: Save, load, list, delete, skills integration for folder-based workflows
- **In scope**: Dependency discovery for sub-workflows and file references
- **Out of scope**: Versioning of saved workflows
- **Out of scope**: Deduplication of shared dependencies across workflows
- **Out of scope**: Remote/registry publishing (future feature)

## Implementation Notes

### Key Files to Modify

- `src/pflow/core/workflow/manager.py` — `WorkflowManager`: save/load/list/delete all need folder awareness
- `src/pflow/core/workflow/save_service.py` — `save_workflow_with_options()`: dependency discovery and bundling
- `src/pflow/core/workflow/skill_service.py` — symlink paths need updating
- `src/pflow/cli/commands/workflow.py` — CLI save command may need to show dependency tree
- `src/pflow/runtime/workflow_executor.py` — verify `_pflow_workflow_file` resolves correctly from saved folders

### Dependency Discovery Algorithm

```python
def discover_dependencies(ir: dict, base_dir: Path, seen: set[Path]) -> list[Path]:
    """Recursively discover all file dependencies of a workflow."""
    deps = []
    for node in ir["nodes"]:
        # Sub-workflow file references
        if node.get("type") == "workflow" or "workflow" in node.get("params", {}):
            ref = node["params"].get("workflow", "")
            if is_file_reference(ref):
                path = (base_dir / ref).resolve()
                if path not in seen:
                    seen.add(path)
                    deps.append(path)
                    # Recursively discover sub-workflow deps
                    child_ir = parse_markdown(path.read_text()).ir
                    deps.extend(discover_dependencies(child_ir, path.parent, seen))

        # File references in params (Task 129)
        for param_value in node.get("params", {}).values():
            if is_file_reference(param_value):
                path = (base_dir / param_value).resolve()
                deps.append(path)

        # File references in inline batch items
        batch = node.get("batch", {})
        if isinstance(batch.get("items"), list):
            for item in batch["items"]:
                for v in item.values():
                    if isinstance(v, str) and is_file_reference(v):
                        path = (base_dir / v).resolve()
                        deps.append(path)
    return deps
```

### Migration Consideration

The simplest migration: on `load()`, if `~/.pflow/workflows/<name>.pflow.md` exists (old format) but `~/.pflow/workflows/<name>/` doesn't, transparently wrap it in a folder. This is a one-time operation per workflow.

## Verification

- Save a workflow with sub-workflow references → all files bundled in folder
- Save a workflow with file references (Task 129) → prompt/code files bundled
- Run a saved workflow with dependencies → all references resolve correctly
- `pflow workflow list` shows folder-based workflows correctly
- `pflow workflow delete` removes entire folder
- Skills publishing works with folder-based workflows
- Circular sub-workflow references detected and reported
- `--force` save overwrites existing folder cleanly
- Existing single-file saved workflows still load (migration or backwards compat)
- Sub-workflows referenced by name (not path) are NOT bundled

## References

- Current save implementation: `src/pflow/core/workflow/manager.py:191-235`
- Current save service: `src/pflow/core/workflow/save_service.py:252-309`
- Skill service: `src/pflow/core/workflow/skill_service.py`
- Workflow executor path resolution: `src/pflow/runtime/workflow_executor.py:260-267`
- File reference detection: `src/pflow/runtime/workflow_executor.py:181-183`
- Real-world test case: `~/projects/music-generation/workflows/` (4 workflow files with sub-workflow references)
- Discussion context: `scratchpads/prompt-file-references/README.md`
