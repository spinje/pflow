# Task 145 Review: Mermaid Workflow Visualization

## Metadata

- Implementation Date: 2026-04-04 to 2026-04-05
- Post-implementation code review: 2026-04-05 (3 findings, all fixed)

## Executive Summary

Extracted duplicated sub-workflow resolution logic (~180 lines) from validator and executor into a shared resolver, then built a mermaid flowchart generator and CLI command on top. The resolver deduplication was the harder half — it required updating mock paths and exception types across 6 test files. The mermaid generator and CLI were straightforward but caught two design bugs during code review (global visited-set instead of recursion stack, hyphen-to-underscore ID collisions).

## Why This Task Exists

The `.pflow.md` format makes individual nodes clear but hides the graph. Edges are scattered across nodes via `- next:`, `- on-error:`, and AST-scanned `next: str = "literal"` — you have to mentally reconstruct the flow shape. For conditional branching workflows, the topology is invisible without reading every node's routing metadata.

The initial idea was to explore switching to a mermaid-based workflow *authoring* format. After analysis, that was rejected — mermaid can't express node configuration (params, code blocks, prompts), and splitting node definitions across a mermaid graph and separate config sections would create a sync problem. Instead, mermaid is used as a *view* (generated from IR), not a *source* (authored by users).

**Why mermaid specifically**: Renders natively in GitHub, VS Code, and any markdown viewer — zero tooling. A browser-based interactive visualizer was also discussed but is a much larger investment. Mermaid ships fast and doesn't compete with building a browser visualizer later — the same IR-to-graph logic feeds both.

## Key Design Decisions (with rationale)

### CLI-only output, not auto-embedded in saved workflows

Two options were considered:
- **A) CLI command only** (`pflow visualize`) — outputs mermaid to stdout
- **B) Auto-embed a `## Flow` section** in saved workflows via `WorkflowManager.save()`

Chose A because B adds integration risk: the parser would need to handle an existing `## Flow` section on re-save without duplicating it, and any bug in the save pipeline affects all workflow saves. A is self-contained with zero risk to existing code. B is a potential future enhancement.

### Extract shared resolver (not just build on top)

The simpler approach was to let the visualizer call `parse_markdown()` directly and leave the validator/executor untouched. The resolver extraction was prioritized because: (1) the duplication was real (~180 lines of near-identical three-way dispatch), (2) a third consumer (the visualizer) would make it worse, and (3) simplicity of the final code was explicitly prioritized over ease of implementation.

### Callback-based resolver in the mermaid generator

`generate_mermaid()` takes `resolve_child` as a callback rather than importing `resolve_sub_workflow` directly. This makes the generator a pure function with no filesystem access — tests pass a lambda or `None` instead of creating temp files. If the resolver were imported directly, every test would need temp files or mocks.

### `dependency_discovery.py` intentionally not refactored

This module is a third consumer of sub-workflow resolution logic, but it only handles file references (no saved names, no inline IR) and serves a different purpose (bundling for `workflow save`, not loading for execution/validation). Forcing it through the shared resolver would over-fit — the bundling path needs `Dependency` objects with provenance metadata, not just IR dicts.

## Implementation Overview

### What Was Built

Three deliverables, as planned:

1. **`sub_workflow_resolver.py`** — shared 3-way dispatch (inline IR / file reference / saved name) used by validator, executor, and mermaid generator. ~135 lines replacing ~180 lines of duplicated logic.

2. **`mermaid.py`** — pure function that walks workflow IR and produces Mermaid flowchart syntax. Supports sub-workflow expansion via `subgraph` blocks, cycle detection via recursion stack, and graceful degradation when resolution fails.

3. **`visualize` CLI command** — `pflow visualize workflow.pflow.md [--depth N] [--direction LR|TD]`. Validates first (same pipeline as `--validate-only`), outputs mermaid to stdout, diagnostics to stderr.

### Deviations from Spec

1. **`WorkflowNotFoundError` propagates instead of `ValueError`**: The spec didn't explicitly address this. The old executor caught all exceptions from `WorkflowManager` and wrapped them in `ValueError("Failed to load workflow...")`. The shared resolver lets the original structured exception propagate. This is better — `WorkflowNotFoundError` carries `similar_names` for "Did you mean?" suggestions. Verified safe because the Runner catches `except Exception`.

2. **Hyphen preservation in mermaid IDs**: The spec included `_to_mermaid_id` with `replace("-", "_")`. Code review found this causes ID collisions. Fixed to return IDs unchanged — hyphens are valid in Mermaid bracket syntax.

3. **Recursion-stack `seen` set**: The spec used a global visited-set pattern (same as the validator's dedup set). Code review found this suppresses sibling expansion. Fixed to add-on-enter/remove-on-exit pattern.

## Files Modified/Created

### Core Changes

- `src/pflow/core/workflow/sub_workflow_resolver.py` — **CREATED**. The load-bearing new abstraction. Three consumers depend on it.
- `src/pflow/core/workflow/mermaid.py` — **CREATED**. Pure function, no I/O. The `seen` add/discard lifecycle in `_render_workflow` is the most subtle part.
- `src/pflow/cli/commands/visualize.py` — **CREATED**. Thin CLI wrapper.
- `src/pflow/cli/main_wrapper.py` — Added `visualize` to routing table.
- `src/pflow/core/workflow/validator.py` — Replaced `_load_child_workflow` body (~60 lines), deleted `_load_child_from_file` (~70 lines). Kept `seen`/`ir_cache` management.
- `src/pflow/runtime/workflow_executor.py` — Replaced `_load_workflow` body (~50 lines), deleted 5 helper methods (~100 lines). Removed `parse_markdown` and `WorkflowManager` imports.
- `src/pflow/runtime/template_validation/validator.py` — Changed import from `WorkflowExecutor._is_file_reference` to `is_workflow_file_reference` directly.

### Test Files

- `tests/test_core/test_sub_workflow_resolver.py` — **CREATED**. 10 tests. All critical — they're the only tests for the shared resolver in isolation.
- `tests/test_core/test_mermaid.py` — **CREATED**. 15 tests (13 original + 2 from code review). `test_cycle_detection` and `test_sibling_same_child_both_expand` are the critical pair — they verify the recursion-stack `seen` set works correctly.
- `tests/test_cli/test_visualize.py` — **CREATED**. 6 tests covering happy path, errors, flags, and nested expansion.
- `tests/test_runtime/test_workflow_executor/test_workflow_name.py` — Mock paths updated, exception types changed.
- `tests/test_runtime/test_workflow_executor/test_workflow_executor.py` — `test_circular_dependency_detection` rewritten with real temp file.
- `tests/test_runtime/test_workflow_executor/test_workflow_executor_comprehensive.py` — 3 tests updated for deleted methods.
- `tests/test_integration/test_workflow_manager_integration.py` — Mock paths updated, exception types changed.

## Integration Points & Dependencies

### Incoming Dependencies

- `validator.py:_load_child_workflow()` → `resolve_sub_workflow()` (lazy import)
- `workflow_executor.py:_load_workflow()` → `resolve_sub_workflow()` (lazy import)
- `mermaid.py:_render_workflow()` → `resolve_sub_workflow` passed as callback
- `visualize.py` → `resolve_sub_workflow` passed to `generate_mermaid()`

### Outgoing Dependencies

- `resolve_sub_workflow()` → `is_workflow_file_reference()` from `file_resolver.py`
- `resolve_sub_workflow()` → `parse_markdown()` from `markdown_parser.py`
- `resolve_sub_workflow()` → `WorkflowManager` from `workflow/manager.py`
- `visualize` command → `resolve_workflow()` from `execution/workflow_resolver.py`
- `visualize` command → `WorkflowRunner.validate()` from `execution/runner.py`

All resolver dependencies are lazy imports (inside function bodies) to avoid circular imports.

## Architectural Decisions & Tradeoffs

### Resolver raises exceptions, callers wrap

The three consumers have incompatible error handling: validator collects error strings, executor lets exceptions propagate, mermaid generator swallows everything. Making the resolver return error tuples would have forced one consumer into an unnatural pattern. Raising and letting each caller wrap is cleaner.

### Validator `seen` check happens after resolution (performance trade-off)

The old validator checked `seen` before file I/O. The new code resolves first (reads + parses), then checks `seen`. For duplicate sub-workflow references, the file gets read twice before the second is discarded. Accepted because: workflow files are small, sub-workflow references are few, and avoiding this would require duplicating the resolver's dispatch logic.

### Validate-before-visualize

The `visualize` command runs full validation before generating mermaid. Alternative was to skip validation and render whatever IR we have. Chose validate-first because broken workflows produce misleading graphs.

### `_to_mermaid_id` is a no-op

Hyphens are valid in Mermaid bracket syntax (`id["label"]`). The function exists as a named indirection point in case future output formats need sanitization, but it currently returns the input unchanged.

## Unexpected Discoveries

### The `seen` set bug was in the original spec

The implementation plan specified a global `seen` set pattern (matching the validator's dedup set). This was wrong for the mermaid generator's use case — dedup and cycle detection are different concerns. The code review caught it. The fix (add-on-enter/remove-on-exit) is 4 lines but changes the semantics fundamentally.

### Inline IR code blocks need two-word syntax

` ```yaml workflow_ir ` (two words) produces `params["workflow_ir"]` as a dict. Single-word ` ```yaml ` produces `params["yaml"]` as a raw string. The resolver checks `isinstance(inline_ir, dict)`, so only the two-word form triggers inline IR expansion. This is correct parser behavior but non-obvious.

### Cycle detection ordering changed in executor

Old: resolve path → check cycle → load file. New: resolve + load (single call) → check cycle. A non-existent file in the cycle stack now raises `FileNotFoundError` instead of `ValueError("Circular workflow reference")`. Harmless — a non-existent file can't form a real cycle.

## Patterns Established

### Shared resolver pattern

When multiple consumers need the same resolution logic with different error handling, extract a function that raises exceptions and let each caller wrap in its own try/except. Don't force error tuples or result objects — they make at least one consumer worse.

### Recursion-stack cycle detection

For tree/graph traversal where siblings should independently visit the same node: add to `seen` before recursing, `discard` after returning. This is different from the validator's `seen` set (which is a permanent dedup set for performance). Don't conflate the two.

### CLI error handling via diagnostic pipeline

Use `exception_to_diagnostics(e)` + `format_diagnostic()` instead of `str(e)`. This preserves structured fields like `similar_names` and produces output consistent with the rest of the CLI.

## Breaking Changes

### Behavioral Changes

`WorkflowExecutor.prep()` now raises `WorkflowNotFoundError` (subclass of `PflowError`) instead of `ValueError("Failed to load workflow '...'")` when a saved workflow name is not found. Any code catching `ValueError` for this case must be updated. The Runner's `except Exception` boundary is unaffected.

## AI Agent Guidance

### Quick Start for Related Tasks

Read in this order:
1. `src/pflow/core/workflow/sub_workflow_resolver.py` — the shared resolver (135 lines, self-contained)
2. `src/pflow/core/workflow/mermaid.py` — the generator (155 lines, pure function)
3. `src/pflow/core/workflow/validator.py:680-757` — how the validator wraps the resolver
4. `src/pflow/runtime/workflow_executor.py:407-461` — how the executor wraps the resolver

### Common Pitfalls

1. **Mock path trap**: Patch `pflow.core.workflow.manager.WorkflowManager`, not `pflow.core.workflow.sub_workflow_resolver.WorkflowManager`. The resolver uses lazy imports — the class is never a module-level attribute.

2. **Don't re-add hyphen sanitization to `_to_mermaid_id`**: Hyphens are valid in Mermaid bracket syntax. Sanitizing them causes collisions with underscore IDs.

3. **Don't move `seen.add`/`seen.discard` into `_try_resolve_child`**: The add/discard must bracket the `_render_workflow` recursion call in the caller. Moving them into the resolver function reintroduces the sibling suppression bug.

4. **Inline IR needs `yaml workflow_ir` (two words)**: Single-word `yaml` produces a raw string, not a dict. The resolver only recognizes the dict form.

### Test-First Recommendations

When modifying the resolver or mermaid generator, run these first:
```bash
uv run pytest tests/test_core/test_sub_workflow_resolver.py tests/test_core/test_mermaid.py -v
uv run pytest tests/test_core/test_sub_workflow_validation.py -v
uv run pytest tests/test_runtime/test_workflow_executor/ -v
```

The sub-workflow validation tests (18 tests) are the best integration canary — they exercise the resolver through the validator without mocking.

---

*Generated from implementation context of Task 145*
