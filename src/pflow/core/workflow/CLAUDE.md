# Workflow Subdirectory

Workflow lifecycle management: save, load, validate, discover, publish.

## Module Structure

```
core/workflow/
├── __init__.py              # Package docstring only — import from submodules (no re-exports)
├── manager.py               # WorkflowManager: save/load/list/delete workflows (folder-based)
├── save_service.py          # Shared save operations for CLI + MCP (with dependency bundling)
├── dependency_discovery.py  # Recursive file dependency scanner for bundling
├── sub_workflow_resolver.py # Shared sub-workflow resolution (file path or saved name)
├── validator.py             # Unified 10-step validation orchestrator
├── data_flow.py             # Execution order (topological sort) and dependency validation
├── loop_validation.py        # check_loop_polarity: shared while/until exactly-one-of rule (compiler + validate path)
├── graph/                   # Renderer-agnostic workflow graph model + renderers
│   ├── __init__.py          # Re-exports build_graph, render_mermaid, model dataclasses
│   ├── model.py             # GraphModel, NodeId, Node/Edge/Container dataclasses
│   ├── build.py             # The only IR walk: IR -> GraphModel
│   ├── scope.py             # Pure template ref extraction helpers
│   └── renderers/
│       ├── mermaid.py       # GraphModel -> Mermaid syntax
│       └── react_flow.py    # GraphModel -> React Flow JSON contract (Task 168)
├── mermaid/                 # Compatibility shim for generate_mermaid
│   └── __init__.py          # Delegates to graph.build_graph + graph.render_mermaid
├── status.py                # WorkflowStatus enum: SUCCESS/DEGRADED/FAILED
├── skill_service.py         # Publish workflows as AI agent skills (symlinks)
├── context.py               # Build workflow context for discovery (build_workflows_context)
├── discovery.py             # LLM-powered workflow discovery (find_workflow → WorkflowMatch)
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
  ├── data_flow.py               (lazy import in _validate_data_flow())
  └── sub_workflow_resolver.py   (lazy import in _load_child_workflow())

sub_workflow_resolver.py
  ├── file_resolver.py           (lazy import)
  ├── markdown_parser.py         (lazy import)
  └── manager.py                 (lazy import)

graph/build.py
  └── sub_workflow_resolver.py   (top-level import for SubWorkflowResult type)

mermaid/
  ├── graph/                     (top-level import for build_graph/render_mermaid)
  └── sub_workflow_resolver.py   (top-level import for SubWorkflowResult type)

skill_service.py
  └── manager.py         (top-level import)
```

No cycles. All heavy imports are lazy (inside functions).

## Key Symbols by File

| File | Key Exports |
|------|-------------|
| `manager.py` | `WorkflowManager` |
| `save_service.py` | `load_and_validate_workflow`, `save_workflow_with_options`, `validate_workflow_name`, `delete_draft_safely`, `generate_workflow_metadata` |
| `dependency_discovery.py` | `Dependency`, `discover_dependencies` |
| `sub_workflow_resolver.py` | `resolve_sub_workflow`, `SubWorkflowResult` |
| `validator.py` | `WorkflowValidator` (static `.validate()` method — 10-step pipeline) |
| `data_flow.py` | `validate_data_flow`, `build_execution_order`, `CycleError` |
| `graph/` | `build_graph`, `render_mermaid`, `render_react_flow`, `GraphModel`, `NodeId`, `EdgeKind` |
| `mermaid/` | `generate_mermaid` |
| `status.py` | `WorkflowStatus` (enum: SUCCESS, DEGRADED, FAILED) |
| `skill_service.py` | `SkillInfo`, `enrich_workflow`, `create_skill_symlink`, `find_pflow_skills`, `remove_skill`, `re_enrich_if_skill` |

## External Consumers

| Consumer | Uses |
|----------|------|
| `cli/commands/run.py` | `WorkflowManager` |
| `cli/commands/list.py`, `describe.py`, `history.py`, `save.py` | `WorkflowManager`, save_service functions |
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

Unified pre-execution orchestrator — returns `list[Diagnostic]` directly. Every helper builds `Diagnostic` objects at the detection site with `context["path"]`, `similar_names`, `available_fields`, and `suggestions` populated by the producer. No string intermediates, no pattern-matching post-processing.

**10-step validation pipeline** (plus a reserved-literal-name guard that runs after step 1 passes, before step 2):
1. Structural (IR schema) — always runs
   - *Reserved-literal-name guard* (`_reject_reserved_literal_names`): runs once structural validation passes, before the semantic steps below. Rejects inputs/node IDs named `true`/`false`/`null` — after literal-operand support (`${a ?? 0}`, bare `${0}`), `${true}` resolves to the boolean literal, so such a name is unreachable. Loud error rather than silent shadowing.
2. Stdin inputs — only one `stdin: true` allowed per workflow
3. Stdout outputs — only one `stdout: true` allowed per workflow
4. Data flow (execution order, dependencies) — always runs
5. Templates (variable resolution) — if params provided
6. Node types (registry verification) — unless `skip_node_types=True`
7. Output sources — validates `${node.key}` refs in outputs via `_validate_template_in_source`. Uses `TemplateResolver.extract_root_node_id()` to support bracket syntax like `${data[0].x}`. Provides fuzzy "did you mean?" suggestions.
8. Unknown param errors — hard errors for params not in node interface metadata, with fuzzy-matched valid keys. Workflow nodes bypass the registry but declare their allowed top-level fields via `WorkflowExecutor.ALLOWED_PARAMS` (a class attribute); Step 8 reads this and rejects unknown top-level fields the same way it rejects unknown params on any other node.
9. Node-specific static parameter semantics — per-node-type param checks (e.g. claude-code structured-output schema preflight).
10. Sub-workflow validation — recursive validation of referenced child workflows (file or saved name). Checks the parent→child input boundary in both directions: missing required inputs AND undeclared extras in the parent's `inputs:` dict (the silent-drop fix). Opaque template inputs (`inputs: ${item}`) skip the static check — runtime defense-in-depth in `WorkflowExecutor._validate_child_params` catches the mismatch per-item.

**Short-circuit on structural errors** (issue #237): if step 1 produces any `Severity.ERROR`, steps 2–10 are skipped and the pipeline returns immediately. Semantic validators assume a structurally-valid IR; running them on a malformed IR produces misleading cascades (e.g. `batch: ${items}` as a string would crash data-flow and template validators with `AttributeError` on `.get()`). Only `_validate_structure` retains a defensive `except Exception` wrapper — it's the boundary to the third-party `jsonschema` library. Downstream validators' producer bugs propagate to the outer CLI/MCP exception boundary, which converts them to structured Diagnostics via `exception_to_diagnostics`.

**Pipeline order is load-bearing**: step 5 (templates) runs BEFORE step 6 (node types). Template validation silently skips unknown node types via `_register_node_outputs_from_registry` — step 6 produces the rich "Unknown node type" diagnostic. Reversing the order or making step 5 raise on unknown types produces duplicate diagnostics.

**`_add_child_provenance` first-write-wins semantics** — sub-workflow diagnostics flow recursively up through nested parents. `sub_workflow_step` and `sub_workflow_path` use `dict.setdefault()` so the innermost wrapping (closest to the error) wins as recursion unwinds. This keeps structured provenance aligned with `node_id` and `context["path"]` (both of which already point at the deepest level). Regressing to overwrite semantics silently breaks 3-level nested workflows.

**Dual-propagation-path dedup invariant** — child workflow warnings flow through BOTH this validator path (`_add_child_provenance`) AND the runtime path (`WorkflowExecutor._propagate_child_parser_warnings`). Both MUST use `format_child_provenance()` for the message, `node_id=d.node_id or step_id` for differentiating siblings, and `setdefault` for context keys. Divergence on any of these breaks `Diagnostic.__hash__` equality and dedup silently duplicates warnings.

### data_flow.py

Uses Kahn's algorithm for topological sort. Catches: forward references, circular dependencies, references to non-existent nodes, undefined input parameters.

**Cache structural validation lives here too** (DD#20 in task-159.md). `_validate_cache_block` is the canonical home for `## Cache` block + per-node `prompt_cache:` rules: non-LLM rejection (`cache.invalid-on-non-llm`), declaration-order enforcement (`cache.order-mismatch`), unused-chunk warnings (`cache.unused-chunk`), prompt-body/cache overlap detection (`cache.prompt-body-duplicates-cache`, `cache.prompt-body-shadows-cache`), plus reference-resolution errors that flow through the existing diagnostic pipeline without their own catalog ID. Both `WorkflowValidator` and the compile-time validator call `validate_data_flow()`, so cache rules run at both entry points without duplication. `pflow analyze-cache` consumes the same producer through the unified `WorkflowValidator.validate()` pipeline; see `prompt_cache_analysis/CLAUDE.md` "Validator delegation".

**Pflow vs bash syntax**: Uses positive pattern matching (`_PFLOW_VAR_RE` compiled from `TemplateResolver._VAR_NAME_PATTERN`) to identify valid pflow variable refs. Refs that don't match (bash syntax like `${#array[@]}`, `${var:-default}`, `${var%%pattern}`, or truncated nested templates) are skipped. Supports a `check_inputs` parameter: `True` (default, used by `WorkflowValidator`) checks undefined inputs; `False` (used by compiler) skips input checks since the compiler has `initial_params` not visible to data flow validation.

### save_service.py

**Reserved workflow names**: Single source of truth is `RESERVED_WORKFLOW_NAMES` frozenset in this file. Includes CLI command names and guide topic names. See the frozenset definition for the full list.

**`save_workflow_with_options()`** is now the save-time trust boundary: it parses markdown, normalizes IR, runs the full `WorkflowValidator`, then performs dependency bundling and persistence. Callers must pass raw markdown, not pre-validated IR. The return value is `(saved_path, bundled_files, validated_ir)`.

**`generate_workflow_metadata()`**: Stub — returns None unconditionally (planning module removed).

### skill_service.py

Publishes workflows as AI agent skills for Claude Code, Cursor, Codex, Copilot. **Symlink-based**: `{tool}/skills/{name}/SKILL.md` → the folder-based entry point `~/.pflow/workflows/{name}/{name}.pflow.md`.

**`enrich_workflow()`**: Injects `## Usage` section (with example command) and adds `name`/`description` to frontmatter.

**`re_enrich_if_skill()`**: Auto-called by `save_workflow_with_options()` after `--force` saves. Restores enrichment lost when the file was replaced.

### status.py

Tri-state: `SUCCESS` (all nodes clean), `DEGRADED` (completed with warnings, e.g., unresolved templates in permissive mode), `FAILED` (errors).

## Known Issues

- **Claude Code requires `description` in frontmatter** for skill discovery (workaround in `skill_service.py`).

## Key Lessons

**Concurrent save safety**: `WorkflowManager.save()` uses atomic `os.rename()` for the final rename (tempdir + `os.rename()` for creates, `os.replace()` for metadata updates) so two parallel saves of the same name don't produce a half-written directory. When testing file-I/O code in this package, use real threads (not `ThreadPoolExecutor` mocks) — single-threaded tests don't exercise the race conditions that tempfile+rename code paths are designed to guard against.

**Content preservation**: Save operations store original markdown with YAML frontmatter prepended. The markdown body is never modified by metadata updates.

**Data flow validation parity**: Compiler validation and `WorkflowValidator` must stay in sync — workflows used to pass save-time validation and fail at compile time. The data_flow validator is now shared between both via lazy import.
