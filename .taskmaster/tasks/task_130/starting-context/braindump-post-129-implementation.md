# Braindump: Task 130 — Post-Task-129 Implementation Context

## Where I Am

Task 129 (External File References) is fully implemented, reviewed, and all follow-up fixes are done. Task 130 (Workflow Bundling on Save) can now begin. This braindump captures what I learned during the Task 129 implementation that's critical for Task 130. There's a previous braindump in this directory (`braindump-feature-planning.md`) written BEFORE implementation — it covers the design discussion. This one covers what we learned DURING implementation.

## What Task 130 Can Build On

### `has_file_references(ir_dict)` already exists

Built during the Task 129 review follow-up. Located at `src/pflow/core/file_resolver.py`. Scans IR for file references without resolving them. Returns a `list[str]` of detected file path strings. Uses the same `FILE_RESOLVABLE_PARAMS` allowlist and `is_file_reference()` heuristic. Task 130's dependency discovery can reuse this directly.

### `is_file_reference(value)` is a pure predicate

No I/O, no side effects. Safe to call on any string to detect if it's a file reference. Already handles all edge cases (templates, URLs, spaces, newlines, bare filenames).

### The allowlist is authoritative

`FILE_RESOLVABLE_PARAMS = {"command", "code", "prompt", "source", "stdin", "headers", "output_schema"}`. Only these params can contain file references. `batch` is handled separately (at `node["batch"]` top-level, not in `node["params"]`). Any dependency scanner should check the same locations that `resolve_file_references()` and `has_file_references()` check.

## Critical Implementation Knowledge

### Save path sees RAW IR, not resolved IR

The save service (`save_service.py`, `manager.py`) validates but does NOT compile. `resolve_file_references()` runs inside `compile_ir_to_flow()`. So when you save a workflow, the IR still has `- prompt: ./prompts/foo.md` as a literal string — NOT the resolved content. This is CORRECT for bundling — you want to copy the original files, not inline their content.

Task 130's dependency discovery needs to work on raw IR (before file resolution). `has_file_references()` does exactly this.

### Batch file references need recursive discovery

If a workflow has `- batch: ./reviews.yaml`, the YAML file contains items that may themselves have file references (`prompt: ./prompts/reviewer-a.md`). The dependency scanner needs to:
1. Find `./reviews.yaml` as a dependency
2. Read and parse it
3. Scan its items for more file references
4. Add those as dependencies too

This is a two-level dependency (workflow → batch YAML → item prompt files). The existing `has_file_references()` scans the IR, but batch file YAML content isn't in the IR yet — it's a string. You'd need to: read the YAML, parse it, then scan the parsed dict for file references in items.

### Sub-workflow detection uses a DIFFERENT function

`workflow_executor.py:181-183` has `_is_file_reference()` (note the leading underscore — it's private). This detects sub-workflow references (`- workflow: ./sub.pflow.md`). It's a DIFFERENT function from `file_resolver.is_file_reference()` with different rules (it checks for `.pflow.md` extension, `\` separator, etc.). Task 130 needs BOTH: sub-workflow refs for bundling sub-workflows, AND file refs for bundling prompt/code/script files.

### `_pflow_workflow_file` is now set in MCP execute path

`_inject_workflow_file_path()` in `execution_service.py` sets `_pflow_workflow_file` for "file" and "library" sources. For "library" sources, it calls `WorkflowManager.get_path()` which currently returns `str((self.workflows_dir / f"{name}.pflow.md").resolve())`. When Task 130 changes to folder structure, this path will change to `{name}/{name}.pflow.md`. This is a breaking change point.

### `_resolve_and_validate_workflow()` now returns 4-tuple

Changed in the review follow-up: returns `(workflow_ir, error_response, validated_params, source)`. The `source` is one of `"file"`, `"library"`, `"content"`, `"direct"`. Previously `source` was discarded. If Task 130 needs source info in the save path, it's now available.

## User's Mental Model

The user thinks about this as **"the unit of saving isn't a file, it's a project."** A workflow with dependencies is a directory, not a single file. Key quotes:

- On always-folder: User agreed immediately when I presented the tradeoff. "WorkflowManager has to check two locations" and "upgrading from file to folder becomes a migration" were the convincing arguments.
- On preserving structure: "Preserving the relative structure sounds good" — don't reorganize, don't enforce layout. What works locally works when saved.
- On `{name}.pflow.md` over `WORKFLOW.pflow.md`: User agreed after I admitted the "tooling simplicity" argument was weak.
- On sub-workflows by name: "you cant just bundle it? then it will exist in two places?" — the user's insight that shared workflows should be saved independently and referenced by name.

The user's unstated priority: **agent-first error UX is non-negotiable.** When I tried to defer `_source_files` consumption in error messages, the user pushed back: "having the best possible errors that agents can understand and act upon is THE core feature of pflow." Every error in the bundling/save process should tell the agent what's wrong, where, and what to do about it.

## Assumptions & Uncertainties

ASSUMPTION: The folder structure `~/.pflow/workflows/{name}/{name}.pflow.md` was agreed on but never implemented. The existing tests and code assume single-file format. Migration needs careful thought.

ASSUMPTION: Skill symlinks (`re_enrich_if_skill()` in `skill_service.py`) point to `~/.pflow/workflows/{name}.pflow.md`. These need updating. I haven't verified exactly how skill symlinks work or what breaks when the path changes.

UNCLEAR: How should `pflow workflow list` display folder-based workflows? Currently it lists `.pflow.md` files. With folders, it lists directories. The display format probably doesn't need to change (just the discovery mechanism), but verify.

UNCLEAR: Migration strategy. Options discussed: (1) auto-migrate on load, (2) explicit migration command. We leaned toward auto-migrate on first access but didn't decide definitively.

NEEDS VERIFICATION: Does `WorkflowManager.load_ir()` need to handle both old (single file) and new (folder) formats during transition? Or can we just break the old format since there are no users?

NEEDS VERIFICATION: The `workflow_resolution.py` in CLI — how does it resolve saved workflow names? Does it go through `WorkflowManager` or directly construct paths? If the latter, it needs updating.

## Unexplored Territory

UNEXPLORED: **What happens when you re-save a workflow with different dependencies?** If version 1 had `./prompts/a.md` and version 2 has `./prompts/b.md`, does re-saving remove `a.md` from the bundle? Or do stale files accumulate? Probably should clean and re-create the folder.

UNEXPLORED: **Dependency discovery for sub-workflows is recursive.** A sub-workflow might have its own sub-workflows and file references. The discovery algorithm needs cycle detection (sub-workflows already have this via `_pflow_stack`, but the save process needs its own).

CONSIDER: **The `--force` flag on save.** Currently overwrites the single file. With folders, it should remove the entire folder and recreate. Verify existing behavior and extend.

CONSIDER: **Atomic save operations.** The current save uses `os.link()` for atomic single-file writes. With folders, atomicity is harder — you'd need to write to a temp directory and rename, or accept non-atomic saves with cleanup on failure.

MIGHT MATTER: **The `batch: ./reviews.yaml` case in IR schema validation.** We discovered during Task 129 that a `batch` string value fails standalone IR schema validation (expects object). The save service calls `validate_ir()`. If a workflow with `- batch: ./reviews.yaml` is saved, validation will fail. The save path either needs to resolve file references before validation, or skip batch schema validation for string values, or accept that batch-file-ref workflows can't be saved. This is a real issue we didn't resolve.

MIGHT MATTER: **Skills publishing.** `skill_service.py` creates symlinks. With folder-based saves, the symlink needs to point to the entry point file inside the folder. Verify the entire skill publish/unpublish/list flow.

## What I'd Tell Myself

1. **Start by reading the existing `WorkflowManager` and `save_service.py` thoroughly.** The save/load/list/delete operations all need updating. Don't guess — read the code.

2. **The dependency discovery is the hard part, not the folder structure.** Recursive scanning of sub-workflows and their file references, with cycle detection, batch YAML parsing, and clear error messages — that's where the complexity lives.

3. **Use `has_file_references()` and `is_file_reference()` from `file_resolver.py` as building blocks.** Don't re-implement detection.

4. **The `batch: ./reviews.yaml` schema validation issue is a landmine.** You'll hit it when testing save with batch file references. Decide upfront whether the save path should resolve file references (like compilation does) or handle the schema differently.

5. **Test with the music-generation project** at `~/projects/music-generation/workflows/`. It has 4 workflow files with sub-workflow references — the exact scenario this feature is for.

## Open Threads

- A code-implementer agent is currently running the manual test plan for Task 129 (11 tests). Results not back yet. If any fail, they'd be Task 129 issues, not Task 130.
- The implementation plan for Task 129's review follow-up (items 5-6) is at `.claude/plans/sequential-wishing-manatee.md` — this was completed by a code-implementer agent. The plan is now stale (implemented), but the research context in it about error formatting pipelines is still valuable.

## Relevant Files & References

### For Task 130 implementation
- `src/pflow/core/workflow/manager.py` — `WorkflowManager`: save/load/list/delete. THE main file to modify.
- `src/pflow/core/workflow/save_service.py` — `save_workflow_with_options()`. CLI and MCP save entry points.
- `src/pflow/core/workflow/skill_service.py` — Skill symlinks. Needs path updates.
- `src/pflow/core/file_resolver.py` — `has_file_references()`, `is_file_reference()`, `FILE_RESOLVABLE_PARAMS`. Reuse for dependency discovery.
- `src/pflow/runtime/workflow_executor.py:181-183` — `_is_file_reference()` for sub-workflow detection. Different function from `file_resolver.is_file_reference()`.
- `.taskmaster/tasks/task_130/task-130.md` — The task spec.
- `.taskmaster/tasks/task_130/starting-context/braindump-feature-planning.md` — First braindump from design phase.

### Task 129 artifacts (reference, not to modify)
- `.taskmaster/tasks/task_129/task-review.md` — Comprehensive review with patterns, pitfalls, integration points.
- `.taskmaster/tasks/task_129/implementation/progress-log.md` — Full implementation journey.
- `examples/file-references/TESTING.md` — Manual test plan template to follow for Task 130.

## For the Next Agent

**Start by reading** (in this order):
1. This braindump
2. The first braindump: `.taskmaster/tasks/task_130/starting-context/braindump-feature-planning.md`
3. The task spec: `.taskmaster/tasks/task_130/task-130.md`
4. The current save implementation: `src/pflow/core/workflow/manager.py` (especially `save()`, `load()`, `load_ir()`, `list_all()`, `delete()`, `get_path()`)
5. `src/pflow/core/file_resolver.py` — understand `has_file_references()` and `is_file_reference()` before building dependency discovery

**Don't bother with:**
- Re-reading the design discussion — it's captured in the braindumps and task spec
- Building your own file reference detection — reuse `file_resolver.py`
- Worrying about backward compatibility — zero users, breaking changes are fine

**The user cares most about:**
- Agent-first error messages — every error tells what's wrong, where, and how to fix
- Observed problems, not theorized ones — the sub-workflow save bug is REAL
- Simplicity — don't over-engineer. The music-generation project with 4 files is the test case.

**The user's conversation style:** They ask probing questions to test your reasoning. "Is this really such a big deal?" and "but isn't this solved by X?" are their way of pushing you toward simpler solutions. Don't present weak arguments as strong ones.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
