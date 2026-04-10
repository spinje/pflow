# Task 145: Mermaid Workflow Visualization

## Description

Generate mermaid flowchart diagrams from workflow IR, including recursive sub-workflow expansion as `subgraph` blocks. Extracts sub-workflow resolution into a shared utility to eliminate existing duplication between validator and executor.

## Status

done

## Priority

medium

## Problem

Two problems, one feature:

**1. Workflow topology is invisible.** The `.pflow.md` format makes individual nodes clear but hides the graph. In `conditional-branching.pflow.md`, you reconstruct the flow mentally from scattered `- next:`, `- on-error:`, and AST-scanned `next: str =` directives across nodes. There's no way to see the shape of a workflow at a glance.

**2. Sub-workflow resolution is duplicated.** The validator (`_load_child_workflow` + `_load_child_from_file`, ~100 lines in `validator.py:681-810`) and the executor (`_load_workflow` + helpers, ~70 lines in `workflow_executor.py:412-521`) both implement the same three-way dispatch: inline IR / file reference / saved name. They differ only in error handling (validator collects strings, executor raises). A third consumer (the visualizer) would make this worse without extraction.

## Solution

**Phase 1: Extract shared sub-workflow resolution** into `core/workflow/resolver.py`. Refactor validator and executor to call it. This fixes existing duplication and provides the foundation for visualization.

**Phase 2: Pure mermaid generator** — a function that takes an IR and the shared resolver, walks the graph (including sub-workflows), and produces a mermaid flowchart string.

**Phase 3: CLI command** — `pflow visualize workflow.pflow.md` runs the standard parse-validate pipeline (same as `--validate-only`), then generates mermaid. Invalid workflows get the normal diagnostic output, not visualizer-specific error handling.

## Design Decisions

- **CLI command only (option A), not auto-embedded in saved workflows**: `pflow visualize` outputs mermaid to stdout. No modification to the save pipeline or parser. Auto-embedding in a `## Flow` section is a future enhancement if wanted.
- **Shared resolver, not replication**: The three-way dispatch (inline/file/saved) is extracted once. Validator, executor, and visualizer all call it. This is an architectural improvement, not just a feature addition.
- **Validation before visualization**: `pflow visualize` runs the same 9-step validation pipeline as execution. If validation fails, you get diagnostics. No separate error handling in the visualizer. The visualizer only runs on valid workflows.
- **Configurable expansion depth** (`--depth N`, default 1): Sub-workflows expand one level by default. `--depth 0` shows opaque boxes. `--depth 3` expands deeply. Prevents unreadable output for deeply nested workflows.
- **Mermaid generator is a pure function**: IR + resolver callable in, string out. No filesystem access, no validation logic. Trivially testable.

## Dependencies

None. All required infrastructure (IR schema, parser, validator, sub-workflow support) exists.

## Requirements

### Shared Resolver (`core/workflow/resolver.py`)

- Function: `load_sub_workflow_ir(params, base_path) -> (ir, path, warnings)`
- Handles all three resolution modes: inline IR (`workflow_ir` param), file reference (`workflow` param pointing to file), saved workflow name (`workflow` param with name)
- Template references (`${dynamic}`) return `None` (unresolvable statically)
- Raises on failure (callers wrap in their own error handling)
- Relative paths resolved against `base_path`

### Validator Refactor

- `_load_child_workflow` and `_load_child_from_file` refactored to call `load_sub_workflow_ir`
- Validator's error-collection and seen/cache semantics preserved (those are validator concerns, not resolver concerns)
- All 18 existing sub-workflow test classes pass without modification (behavior unchanged)

### Executor Refactor

- `_load_workflow`, `_load_workflow_from_reference`, `_load_workflow_by_name` refactored to call `load_sub_workflow_ir`
- Executor's runtime concerns preserved (shared store path resolution, exception raising, cycle detection via `_pflow_stack`)
- All existing executor tests pass without modification

### Mermaid Generator (`core/visualization.py`)

- Function: `ir_to_mermaid(ir, resolve_child, *, max_depth=1) -> str`
- Produces valid mermaid `graph` syntax (renders correctly in GitHub, VS Code, mermaid.live)
- Node labels include type: `fetch-data["fetch-data (shell)"]`
- Edge types visually distinguished:
  - Default/document-order edges: plain arrows (`-->`)
  - Named action edges: labeled arrows (`-->|action-name|`)
  - Error edges: labeled (`-->|error|`), dashed style
- Sub-workflow nodes rendered as `subgraph` blocks containing their internal nodes
- Node IDs namespaced to avoid collisions (e.g., `process_title__transform` when two sub-workflows both have a `transform` node)
- Template/unresolvable sub-workflow refs rendered as opaque nodes (not expanded)
- Cycle-safe: tracks seen workflows, stops expansion on revisit
- `max_depth=0` renders all sub-workflows as opaque boxes (no expansion)

### CLI Command

- `pflow visualize <workflow>` — accepts file path or saved workflow name
- Runs parse + validate (same pipeline as `pflow run --validate-only`)
- On validation errors: show diagnostics, exit non-zero
- On success: print mermaid to stdout
- `--depth N` flag (default 1) controls sub-workflow expansion depth
- Stdout-only output — pipe to file, clipboard, or other tools

## Implementation Notes

### Resolver extraction scope

The shared resolver handles the pure resolution: "given params, load an IR." It does NOT handle:
- Cycle detection (validator uses `seen` set, executor uses `_pflow_stack` — different mechanisms for different contexts)
- Caching (validator uses `_ir_cache` for dedup — that's a validator optimization)
- Error collection vs. raising (caller's responsibility)

What it DOES handle:
- Three-way dispatch (inline / file / saved name)
- Path resolution (relative to `base_path`)
- Template reference detection (returns None)
- Calling `parse_markdown()` and returning the IR + path + parser warnings

### Edge data in the IR

Edges are already fully represented in the IR after parsing. Each edge is `{"from": str, "to": str, "action"?: str}`:
- No `action` key = document-order (implicit sequential)
- `action: "default"` = explicit `- next: target`
- `action: "error"` = `- on-error: handler`
- `action: "some-name"` = conditional routing (from `- next: a, b` or AST-scanned `next: str = "literal"`)

The mermaid generator consumes these directly. No additional edge computation needed.

### Mermaid node ID sanitization

Mermaid allows alphanumeric and hyphens in node IDs. pflow node IDs follow similar rules (validated at parse time). The main concern is namespacing for sub-workflows: prefix child node IDs with `{parent_node_id}__` to guarantee uniqueness.

### Where things live

```
src/pflow/core/workflow/resolver.py    # NEW — shared sub-workflow resolution (~40 lines)
src/pflow/core/visualization.py        # NEW — pure mermaid generator (~120 lines)
src/pflow/cli/commands/visualize.py    # NEW — CLI command (~30 lines)
src/pflow/core/workflow/validator.py   # MODIFIED — use shared resolver
src/pflow/runtime/workflow_executor.py # MODIFIED — use shared resolver
```

## Verification

### Resolver

- Inline IR resolution returns the dict directly
- File reference resolution parses and returns IR + resolved path
- Saved name resolution loads via WorkflowManager
- Template references return None
- Relative paths resolve against base_path
- Missing file raises (not silently returns None)
- All existing validator sub-workflow tests pass (18 test classes in `test_sub_workflow_validation.py`)
- All existing executor tests pass (`test_workflow_executor/`)

### Mermaid output

- Flat workflow (simple-pipeline): correct node declarations and sequential arrows
- Branching workflow (conditional-branching): labeled action edges, error edges with dashed style
- Sub-workflow (document-processor): `subgraph` blocks with namespaced child nodes
- `--depth 0`: sub-workflows shown as opaque nodes
- `--depth 2+`: recursive expansion works
- Cycle in sub-workflows: expansion stops, no infinite loop
- Template sub-workflow ref: rendered as opaque node
- Output is valid mermaid (paste into mermaid.live and it renders)

### CLI integration

- `pflow visualize examples/core/simple-pipeline.pflow.md` outputs mermaid to stdout
- `pflow visualize examples/invalid/missing-type.pflow.md` shows diagnostics, exits non-zero
- `pflow visualize examples/nested/document-processor.pflow.md` shows expanded sub-workflows
- `pflow visualize examples/nested/document-processor.pflow.md --depth 0` shows opaque sub-workflow nodes

## References

- Current markdown format and parser: `src/pflow/core/markdown_parser.py`
- IR schema (edge structure): `src/pflow/core/ir_schema.py:189-206`
- Validator sub-workflow resolution: `src/pflow/core/workflow/validator.py:563-810`
- Executor sub-workflow resolution: `src/pflow/runtime/workflow_executor.py:412-521`
- Nested workflow examples: `examples/nested/document-processor.pflow.md`, `examples/nested/to-uppercase.pflow.md`
- Conditional branching example: `examples/core/conditional-branching.pflow.md`
- Task 107 review (JSON→markdown migration): `.taskmaster/tasks/task_107/task-review.md`
- Validation pipeline: `src/pflow/core/workflow/validator.py` (9-step pipeline)
- CLI command patterns: `src/pflow/cli/commands/` (existing subcommands for structure reference)
