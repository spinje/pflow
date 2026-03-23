# Task 128: Branch Convergence for Conditional Workflows

## Description

Add first-class support for branch convergence — the ability for a downstream node to reference the output of "whichever branch ran" after conditional branching. Without this, conditional branching (Task 38) is severely limited: every convergence point requires 2-3 workaround nodes, and workflows with 3+ branches balloon in complexity.

## Status
done

## Completed
2026-03-15

## Priority

high

## Problem

When two or more conditional branches converge at a common downstream node, there is no way for that node to reference the output of whichever branch actually executed. Referencing a non-executed node's output causes a template resolution error:

```
Unresolved variables in parameter 'content': ${fetch-youtube.stdout}
```

**Root cause**: PocketFlow's execution model is a simple `while curr:` loop following successor edges. Non-taken branches never execute, so their namespace is entirely absent from the shared store — not `None`, not `""`, just missing. The strict template resolver then raises `ValueError`.

The convergence *wiring* works fine — both branches can point to the same next node via `- next: use-result`. The problem is purely in template resolution at the convergence point.

**Workaround**: Each branch writes to a temp file, then a shell node reads it back. This adds 2-3 extra nodes per convergence point, is fragile (hardcoded paths, breaks batch), and unintuitive.

**Real-world example**: A lyrics workflow that fetches from YouTube (yt-dlp), web (Jina), local files, or raw text. Each produces `stdout`, but the downstream LLM can't reference any without knowing which branch ran. The workaround turned 5 nodes into 9.

See `scratchpads/branch-convergence-no-fallback/BUG-REPORT.md` for full reproduction and analysis.

## Solution

Two complementary mechanisms (phased delivery):

**Phase 1 — Optional Inputs on Code Nodes** (implemented):
Code nodes declare inputs as `str | None` or `Optional[str]`. When the source node didn't execute, `None` is injected instead of erroring. Convergence logic lives in user code.

```markdown
### merge-result
- type: code
- inputs:
    high: ${branch-high.stdout}
    low: ${branch-low.stdout}

```python code
high: str | None
low: str | None

result: str = high or low or "nothing"
```
```

**Phase 2 — `??` Coalesce Operator in Templates** (in progress):
Any node type can write `${branch-high.stdout ?? branch-low.stdout}` inline. No extra merge node needed.

```markdown
### use-result
- type: shell

```shell command
echo "Result: ${branch-high.stdout ?? branch-low.stdout}"
```
```

Neither alone covers everything. Phase 1 handles complex cases (type normalization, logic). Phase 2 handles the common case (same-type branches) with zero boilerplate.

## Design Decisions

- **`??` semantics = "root node absent", not "value is None"**: A node that didn't execute has no namespace in the shared store (`"node_id" not in shared`). A node that executed has at least `shared["node_id"] = {}`. This distinction lets us catch typos: if `branch-high` DID execute and you wrote `${branch-high.stddout ?? ...}`, the root IS present, so the typo is caught — we don't silently fall through.

- **Python type annotations as the declaration of intent (Phase 1)**: No new syntax like `?` markers. `str | None` in the code IS the signal. The code node already parses annotations; we extended `_get_outer_type()` to decompose `Optional[T]` and `T | None` into `(T, type(None))`.

- **Compiler extracts optional keys, passes as metadata**: Keeps `TemplateAwareNodeWrapper` generic — no code-node coupling. Any future node type could opt into optional inputs by having the compiler set `optional_input_keys`.

- **Refactor `_resolve_simple_template` out of `node_wrapper.py` (Phase 2)**: This method duplicated `TemplateResolver.resolve_template()`'s simple-template path. Verified by parallel subagents that eliminating it and computing `is_simple` independently via `TemplateResolver.is_simple_template()` produces identical behavior. This makes `resolve_template()` the single resolution path — coalesce only needs to be added in one place.

- **`_VAR_NAME_PATTERN` stays clean**: New `_COALESCE_EXPR_PATTERN` builds on it with `(?:\s*\?\?\s*_VAR_NAME_PATTERN)*`. Keeps individual var name matching available for code that needs it.

- **Literal fallbacks (`${a ?? "default"}`) are out of scope**: Adds significant parser complexity (quoted strings inside templates). Can be Phase 3 if needed.

## Dependencies

- Task 38: Conditional Branching in Workflows — Must exist first (already completed)

## Implementation Notes

### Phase 1 — Implemented

Files modified:
- `src/pflow/nodes/python/python_code.py` — `_is_optional_type()`, `_get_inner_optional_type()`, fixed `_get_outer_type()` to decompose optionals, `extract_optional_input_keys()`, added `typing`/`Optional` to exec namespace
- `src/pflow/runtime/node_wrapper.py` — `optional_input_keys` constructor param, `_all_variables_from_absent_nodes()` helper, `_inject_none_for_optional_inputs()`, wired into `_run()`
- `src/pflow/runtime/compiler.py` — Extracts optional keys for code nodes, passes through `_apply_template_wrapping()`
- `tests/test_integration/test_branch_convergence.py` — New file, 6 end-to-end tests
- Plus unit tests in `test_python_code.py` and `test_node_wrapper_template_validation.py`

All 3986 tests pass. `make check` clean.

### Phase 2 — In Progress

Full plan at `.claude/plans/sunny-spinning-gem.md`. Key changes:

**Core (template_resolver.py)**:
- Extend regex: `_COALESCE_EXPR_PATTERN` wrapping `_VAR_NAME_PATTERN`
- `split_coalesce_operands()`, `is_coalesce_expression()`, `resolve_coalesce()` — new static methods
- Update `extract_variables()` to split coalesce operands into individual vars
- Update `resolve_template()` to handle coalesce in both simple and complex paths

**Refactor (node_wrapper.py)**:
- Delete `_resolve_simple_template` (duplicated `resolve_template()` logic)
- Simplify `_resolve_template_parameter` to delegate to `resolve_template()` directly

**Validation consumers (4 files)**:
- `template_validator.py` — Update `_PERMISSIVE_PATTERN`, split operands in `_extract_all_templates`
- `workflow_data_flow.py` — Split coalesce operands before `_validate_template_reference`
- `workflow_validator.py` — Split coalesce operands before node ID extraction

**No-change locations** (verified): `repair_service.py`, `ir_schema.py`, `planning/nodes.py`, all `"${" in value` checks, `_QUOTED_TEMPLATE_PATTERN`, `NESTED_INDEX_PATTERN`.

### Shared Store Invariant

The convergence semantics rely on this invariant:
- Node didn't run → `"node_id" not in shared`
- Node ran → `"node_id" in shared` (at minimum `{}`)

This is guaranteed by `NamespacedSharedStore.__init__` which always creates `shared[namespace] = {}` during `_run()`. Verified in `src/pflow/runtime/namespaced_store.py:39-41`.

## Verification

### Phase 1

- Code node with `str | None` inputs: non-executed branch injects `None`, executed branch passes value
- Non-optional input (`str`) still errors when source didn't execute
- Typo in field path still errors despite Optional annotation
- Both `Optional[str]` and `str | None` annotation forms work
- All 3986 existing tests pass, `make check` clean

### Phase 2

- `${a ?? b}` as entire param: type of resolved operand preserved (int, dict, etc.)
- `"text ${a ?? b}"`: converts to string (complex template behavior)
- `${a ?? b ?? c}`: chains work, first executed branch wins
- All roots absent: returns template unchanged, triggers unresolved error
- Root present but path wrong: errors (typo detection preserved)
- Mixed: `"${a ?? b} and ${c}"` — coalesce + regular in same string
- Validation: both operands validated as valid node references
- Integration: shell/llm nodes work with `??` without merge node
- All existing tests pass, `make check` clean
