# Task 128 Review: Branch Convergence for Conditional Workflows

## Metadata

- **Implementation Date**: 2026-03-15
- **Status**: Complete (pending commit)
- **Depends on**: Task 38 (Conditional Branching)

## Executive Summary

Added two complementary mechanisms for branch convergence: (1) code nodes accept `Optional[T]`/`T | None` inputs with `None` injection for non-executed branches, and (2) a `??` coalesce operator in template syntax (`${a ?? b}`) usable by any node type. Together they make conditional branching practically useful — previously, every convergence point required 2-3 workaround nodes.

## Implementation Overview

### What Was Built

**Phase 1 — Optional Inputs on Code Nodes**: When a code node declares an input as `str | None`, the compiler extracts this from the code's AST annotations and passes `optional_input_keys` to the template wrapper. At runtime, if the source node didn't execute (absent from shared store), `None` is injected instead of raising a `ValueError`. Non-optional inputs still error. Typos still error (root present but path wrong).

**Phase 2 — `??` Coalesce Operator**: Extended the template regex grammar to support `${a.stdout ?? b.stdout}`. The resolver tries each operand left-to-right; if an operand's root node is absent from context (didn't execute), it skips to the next. First match wins. Works inline in any template position — shell commands, LLM prompts, inputs dicts.

**Refactor — Eliminated `_resolve_simple_template`**: The node wrapper had a method that duplicated `TemplateResolver.resolve_template()`'s simple-template path. Deleting it made `resolve_template()` the single resolution entry point. Coalesce logic only needed to be added in one place.

**Fix — Bracket-only nested index pre-processor**: The old `NESTED_INDEX_PATTERN` matched the full `${outer[${inner}]rest}` structure. This didn't compose with coalesce (`${results[${__index__}].field ?? fallback}` failed). Replaced with a simpler `_BRACKET_INDEX_PATTERN` that matches only `[${var}]` — context-free, composes with any outer syntax.

### Deviations from Original Spec

The bug report (`scratchpads/branch-convergence-no-fallback/BUG-REPORT.md`) proposed only `??`. The two-phase approach emerged from design discussion:
- User concern: `??` is the first inline operator inside `${...}` — a grammar precedent
- User insight: Python type annotations (`str | None`) are the declaration of intent — no new syntax needed for code nodes
- User question: "what if the values are not the same type?" — dot access is the normalization mechanism, but code nodes handle complex cases
- Decision: both approaches are complementary, not competing

## Files Modified/Created

### Core Changes

- `src/pflow/runtime/template_resolver.py` — `_COALESCE_EXPR_PATTERN` regex, `split_coalesce_operands()`, `is_coalesce_expression()`, `resolve_coalesce()`, updated `extract_variables()` and `resolve_template()`, extracted `_resolve_complex_match()`, `_ROOT_SPLIT_PATTERN`, `_BRACKET_INDEX_PATTERN`
- `src/pflow/runtime/node_wrapper.py` — Deleted `_resolve_simple_template`, simplified `_resolve_template_parameter`, added `optional_input_keys` param, `_all_variables_from_absent_nodes()`, `_inject_none_for_optional_inputs()`
- `src/pflow/runtime/compiler.py` — Extracts optional keys from code annotations, passes through `_apply_template_wrapping()`
- `src/pflow/nodes/python/python_code.py` — `_is_optional_type()`, `_get_inner_optional_type()`, fixed `_get_outer_type()` for Optional decomposition, `extract_optional_input_keys()`, added `typing`/`Optional` to exec namespace
- `src/pflow/runtime/template_validator.py` — Updated `_PERMISSIVE_PATTERN`, consolidated coalesce split in `_extract_all_templates`
- `src/pflow/core/workflow_data_flow.py` — `_split_coalesce()` helper, split operands before `_validate_template_reference`
- `src/pflow/core/workflow_validator.py` — Split coalesce operands in `_validate_template_in_source`

### Test Files

- `tests/test_integration/test_branch_convergence.py` — **New**. 12 tests: IR-based, markdown pipeline, coalesce in shell nodes, Phase 1+2 interaction
- `tests/test_runtime/test_template_coalesce.py` — **New**. 67 tests across 7 classes: regex, splitting, detection, extraction, resolution semantics, type preservation, end-to-end
- `tests/test_nodes/test_python/test_python_code.py` — 15 tests for Optional type support
- `tests/test_runtime/test_node_wrapper_template_validation.py` — 7 tests for optional injection
- `tests/test_runtime/test_template_resolver.py` — 1 test for `extract_variables` with coalesce

## Integration Points & Dependencies

### Load-Bearing Invariant

The entire convergence system depends on this shared store invariant:

```
Node didn't run  →  "node_id" not in shared  (absent)
Node ran         →  "node_id" in shared      (at minimum {})
```

This is guaranteed by `NamespacedSharedStore.__init__` (`namespaced_store.py:39-41`) which always creates `shared[namespace] = {}` during `_run()`. If this invariant breaks, both `??` and Optional inputs produce wrong results silently.

### Incoming Dependencies

- `extract_variables()` — called by `node_wrapper.py` (error messages, optional injection, partial resolution), `error_context.py` (upstream stderr), `template_validator.py` (type checking), `planning/nodes.py` (template tracking). All now receive individual operands from coalesce expressions.
- `TEMPLATE_PATTERN` / `SIMPLE_TEMPLATE_PATTERN` — used throughout the codebase. Now include `_COALESCE_EXPR_PATTERN`.
- `_PERMISSIVE_PATTERN` in `template_validator.py` — independently defined, manually synced. Must be updated whenever the resolver patterns change.

### Outgoing Dependencies

- `NamespacedSharedStore.__init__` — the "root absent = didn't execute" invariant
- `_extract_annotations()` in `python_code.py` — AST parsing for code node type annotations
- PocketFlow's `Flow._orch()` — the simple `while curr:` execution model that makes non-taken branches absent

## Architectural Decisions & Tradeoffs

### Key Decisions

1. **`??` semantics = "root absent" not "value is None"** → Preserves typo detection. If `branch-high` ran and you wrote `${branch-high.stddout ?? branch-low.stdout}`, the root IS present, so the path error is caught. If we used "value is None", typos would silently fall through.

2. **Python annotations as declaration of intent** → No new syntax for Phase 1. `str | None` in the code IS the signal. The compiler extracts it at compile time and passes it as metadata. The wrapper is generic — any future node type could opt in.

3. **Compiler extracts, wrapper consumes** → `optional_input_keys` is metadata set by the compiler, not by the wrapper inspecting inner node types. This keeps `TemplateAwareNodeWrapper` generic.

4. **Single resolution entry point** → Deleting `_resolve_simple_template` and routing everything through `TemplateResolver.resolve_template()` means coalesce logic exists in one place. The `is_simple` flag is computed independently via `is_simple_template()`.

5. **Bracket-only nested index pattern** → Matches `[${var}]` anywhere instead of the full `${outer[${inner}]rest}` structure. Context-free, composes with coalesce (and any future syntax).

### Technical Debt

- **Three copies of coalesce split logic**: `template_resolver.py` (canonical), `workflow_data_flow.py` (mirrors, commented), `template_validator.py` (consolidated to use canonical). The `workflow_data_flow.py` copy exists because the file has zero pflow imports. Acceptable for now.
- **Phase 1+2 interaction is emergent, not designed**: Two independently-written guards (`all()` in `_all_variables_from_absent_nodes` and `input_value != input_template`) happen to align correctly. Documented with comment and regression tests, but fragile under refactoring.

## Testing Implementation

### Critical Test Cases

- `test_optional_input_receives_none_for_skipped_branch` — Core Phase 1: verifies None injection when source node absent
- `test_non_optional_input_still_errors` — Ensures non-optional inputs aren't silently swallowed
- `test_typo_in_field_still_errors_despite_optional` — Typo detection preserved: root present + wrong path = error
- `test_root_present_as_empty_dict_counts_as_present` — Validates the store invariant: executed-but-empty node is NOT "absent"
- `test_path_error_on_second_operand` — Coalesce skips absent first root, catches typo on second
- `test_coalesce_in_optional_input_both_absent_gets_none` — Phase 1+2 interaction: when both coalesce operands AND the input are optional, None is correctly injected
- `test_shell_node_coalesce_low_branch` / `_high_branch` — End-to-end: shell node with `??`, both directions

## Unexpected Discoveries

- **`_resolve_simple_template` was a full duplication** of `resolve_template()`'s simple path. Both used the exact same three static methods in the same order. The wrapper's version existed solely to return an `is_simple` flag — which can be computed independently.
- **`_get_outer_type("Optional[str]")` returned `None`** (skipping ALL type checks). This was a pre-existing bug — `Optional` wasn't in `_TYPE_MAP`, so the type check was silently skipped. Fixed by decomposing `Optional[T]` → `(T, type(None))`.
- **`_PERMISSIVE_PATTERN` in `template_validator.py` is independently defined** from the resolver's patterns. There's no shared base. Must be manually synced — easy to forget.
- **The nested index pre-processor (`NESTED_INDEX_PATTERN`) didn't compose with coalesce** because it matched the full outer `${...}` template including the closing `}`. The `??` suffix between rest_path and `}` broke the regex.

## Patterns Established

### Compiler-Extracts-Metadata Pattern

The compiler inspects node source (code annotations) and passes metadata (`optional_input_keys`) to the wrapper. The wrapper is generic — it doesn't know about code nodes or Python AST. This pattern is extensible: any future node type could opt into optional inputs by having the compiler set the same metadata.

```python
# In compiler._create_single_node():
if node_type == "code" and "code" in params and isinstance(params.get("inputs"), dict):
    from pflow.nodes.python.python_code import extract_optional_input_keys
    optional_input_keys = extract_optional_input_keys(params["code"], input_keys) or None
```

### Three-Status Return for Resolution

`resolve_coalesce()` returns `(value, "resolved" | "path_error" | "unresolved")` — callers can distinguish success, typo, and "all absent". This is cleaner than returning `None` for both failure modes.

### Root-Absent Check

Extracting the root node from a template path and checking `root in context` is the canonical way to distinguish "branch not taken" from "typo". Used in both `resolve_coalesce` and `_all_variables_from_absent_nodes`.

## Known Limitations

1. **Coalesce inside bracket indices**: `${results[${a ?? b}].field}` — `extract_simple_template_var` returns `"a ?? b"`, but `resolve_value` expects a single path. Extremely rare (inner templates are always `${__index__}`).
2. **Literal fallbacks**: `${a ?? "default"}` — requires parsing quoted strings inside templates. Out of scope.
3. **No static validation for coalesce semantics**: Validator checks each operand is a valid node reference but can't warn "these operands are always both present" (would require branch reachability analysis).
4. **Type mismatch between operands**: `${dict-branch.stdout ?? text-branch.stdout}` gives different types depending on which branch ran. Dot access is the normalization mechanism.

## AI Agent Guidance

### Quick Start for Related Tasks

1. Read `src/pflow/runtime/template_resolver.py` — all template resolution lives here
2. Read `src/pflow/runtime/node_wrapper.py:592-620` — the simplified `_resolve_template_parameter` that delegates to `resolve_template()`
3. Read `src/pflow/runtime/CLAUDE.md` — wrapper chain architecture
4. Understand the shared store invariant: absent = didn't run, present = ran

### Common Pitfalls

- **Don't add operators to `_VAR_NAME_PATTERN`** — it defines individual variable paths. Add new expression syntax to `_COALESCE_EXPR_PATTERN` (or create a new expression-level pattern).
- **`_PERMISSIVE_PATTERN` must be manually synced** with resolver patterns. It's independently defined in `template_validator.py`.
- **Don't change `all()` to `any()` in `_all_variables_from_absent_nodes`** — see the docstring comment explaining why.
- **`resolve_nested()` calls `resolve_template()` for each string value** — coalesce in dict params (like `inputs`) works automatically through this chain. Don't add separate coalesce handling in `resolve_nested`.

### Test-First Recommendations

When modifying template resolution:
1. Run `uv run pytest tests/test_runtime/test_template_coalesce.py -v` — coalesce semantics
2. Run `uv run pytest tests/test_runtime/test_template_resolver.py -v` — core resolution
3. Run `uv run pytest tests/test_integration/test_branch_convergence.py -v` — end-to-end convergence
4. Run `uv run pytest tests/test_runtime/test_node_wrapper_template_validation.py -v` — wrapper behavior
5. Run `make test` — full suite for regressions

---

*Generated from implementation context of Task 128*
