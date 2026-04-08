# Task 147 Follow-up: Remove Test-Helper Splits (spinje/pflow#238)

> **Agent: read this file in full before taking any action. Then read the GitHub issue before writing any code.**

---

## START HERE — Required reading (in order)

1. **The GitHub issue** — this is the authoritative problem statement:
   ```bash
   gh issue view 238 --repo spinje/pflow
   ```
   Read it completely. Pay special attention to the "Why This Is A Smell" and "Proposed Fix" sections.

2. **Task 147 progress log — the mechanical deviation section**:
   `.taskmaster/tasks/task_147/implementation/progress-log.md`
   - Search for `"2026-04-07 — Implementation step 5: consumer cleanup"` — this is where the helper pattern was introduced.
   - Search for `"Test migration approach (intentional deviation in mechanics, not in outcome)"` — this is the original justification.
   - Search for `"Smell 1: 19 test-helper splits"` — this is the verification-round finding that became issue #238.

3. **Task 147 implementation plan — Section 10 "Test rewrite patterns"**:
   `.taskmaster/tasks/task_147/implementation/implementation-plan.md`
   - Search for `"7 mechanical patterns"` — the original plan for how tests should have been rewritten. This follow-up implements that original plan for the 19 files that took the helper shortcut.

4. **One representative test file** to internalise the actual call-site shape:
   `tests/test_runtime/test_template_validation/test_validator.py`
   (lines 1–20 for the helper definition, 215–280 for typical assertion patterns)

**Do not skip step 1.** The issue text is the contract for this work. If the plan below appears to contradict the issue, the issue wins — tell the user before proceeding.

---

## Context — why this exists

Task 147 (#219) converted `WorkflowValidator.validate()` and `validate_workflow_templates()` from `tuple[list[str], list[Diagnostic]]` to `list[Diagnostic]` — single list, severity as a field on each diagnostic. The implementer introduced identical local helpers in 19 test files to preserve the old `(errors, warnings) = ...` tuple-unpack ergonomics:

```python
def _split_validator_diagnostics(*args, **kwargs):
    diagnostics = WorkflowValidator.validate(*args, **kwargs)
    from pflow.core.diagnostic import format_diagnostic

    errors = [format_diagnostic(d) for d in diagnostics if d.severity.value == "error"]
    warnings = [d for d in diagnostics if d.severity.value == "warning"]
    return errors, warnings
```

The smell: `errors` is now a `list[str]` of **fully rendered multi-line `format_diagnostic()` output**, not raw messages. Substring assertions that used to match a one-line error message now match against a full rendered block. `"file_pat" in errors[0]` matches in the `Available fields` listing, the `Did you mean` block, the path, **and** the suggestion — a strictly weaker check than matching `.message` alone.

**The architectural goal of task 147 was "producers are self-describing."** The helper silently undoes that at the test boundary: the structural fields (`context["path"]`, `.suggestions`, `.context["available_fields"]`, `.context["similar_names"]`, `.node_id`, `.title`) are not individually checked by any of the 19 helper-using test files. They are absorbed into the rendered string.

**Concrete risk**: a producer regression where `context["path"]` becomes wrong, `.suggestions` becomes empty, or `.context["available_fields"]` becomes incomplete would NOT be caught by the migrated test suite. Only ~13 tests in the whole codebase currently guard the structural contract (the 8 from #219's closing PR plus 5 hardenings S1–S5 from the post-implementation review round).

This follow-up closes that gap **without ballooning scope**. See "Anti-goals" for what this is NOT trying to do.

---

## Goal

1. Remove the 19 duplicated local helpers.
2. Replace them with one canonical shared helper that returns **typed `Diagnostic` objects** (not pre-rendered strings).
3. Sweep the 19 call sites to assert on `.message` (the raw error text) instead of the rendered block.
4. Handle the four known cases where an assertion relied on rendered-block content that isn't in `.message` (converting them to structural assertions that are strictly stronger).
5. Add a handful of **additive** structural assertions to the five highest-value test files, locking in the producer contract for the richest diagnostics.

**Success looks like**: `grep -rn "_split_validator_diagnostics\|_split_template_diagnostics" tests/` returns zero matches. `make test` and `make check` are clean. The diff adds ~150–250 lines net (mostly structural assertions in Phase 3) and removes ~170 lines (19 helper definitions × ~9 lines each).

---

## Anti-goals (things that are explicitly NOT in scope)

Be ruthless about these. Scope creep is the single biggest risk.

1. **Do NOT rewrite all ~309 migrated assertions to structural assertions.** The issue is explicit: "diminishing returns past the high-value producers." Substring matching against `.message` is fine for "error happened with this kind of text" tests. Only promote to structural assertions in the 5 high-value files named below.

2. **Do NOT touch production code.** This is a test-only change. If you find yourself editing `src/pflow/...`, stop and ask. The one exception: if you notice a producer is genuinely missing a structural field while writing Phase 3 assertions, file a follow-up issue, do not fix it in this PR.

3. **Do NOT remove substring matching where it is legitimate.** `assert "Template variable ${url}" in errors[0].message` is a perfectly good assertion. The goal is not "zero substring matches" — the goal is "substring matches are against `.message`, not against multi-line rendered output."

4. **Do NOT add new test files.** This work operates on the 19 existing files plus one new shared helper. Don't invent new test modules.

5. **Do NOT duplicate existing structural guards.** The following tests already lock in the structural contract — do not re-verify the same producers:
   - `tests/test_core/test_unknown_param_validation.py::test_unknown_param_diagnostic_preserves_structure`
   - `tests/test_cli/test_validate_only.py::test_json_rich_validation_error_preserves_context_fields`
   - `tests/test_runtime/test_compiler_basic.py::test_warning_only_data_flow_does_not_raise`
   - `tests/test_core/test_sub_workflow_validation.py::test_three_level_nesting_keeps_innermost_sub_workflow_provenance`
   - `tests/test_core/test_workflow_validator.py::TestDefensiveWrapperDiagnostics` (4 tests)
   - `tests/test_runtime/test_template_validation/test_types.py::test_dict_to_int_mismatch` (S1)
   - `tests/test_runtime/test_template_validation/test_validator.py::test_batch_results_invalid_nested_path_rejected` (S2)
   - `tests/test_core/test_workflow_data_flow.py::test_typo_suggestion` (S3)
   - `tests/test_runtime/test_template_validation/test_enhanced_errors.py::test_path_access_on_declared_input_error` (S4)
   - `tests/test_runtime/test_template_validation/test_types.py::test_shell_blocks_dict_list_union` (S5)

6. **Do NOT try to unify the mock-registry definitions.** Several of the 19 files define local `create_mock_registry()` helpers with file-specific node metadata. The CLAUDE.md for `tests/test_runtime/test_template_validation/` explicitly says "don't extract to conftest." Leave those alone.

7. **Do NOT rename the test classes or reorder tests.** Pure diff hygiene — reviewers will have an easier time if the diff is semantically localized.

---

## Scope — the 19 files (and one new file)

| File | Helper calls | Has rendered-content assertions? | Phase 3 candidate? |
|---|---|---|---|
| `tests/test_core/test_cache_lint_warning.py` | 10 | No | No |
| `tests/test_core/test_file_resolver_integration.py` | 3 | No | No |
| `tests/test_core/test_output_source_validation.py` | 16 | No | No |
| `tests/test_core/test_sub_workflow_validation.py` | 18 | No | No |
| `tests/test_core/test_unknown_param_validation.py` | 5 | **Yes** (`"Did you mean"` × 2) | **No** — S-series already covers it |
| `tests/test_core/test_workflow_validator.py` | 18 | No | **Yes** (V6, V8, V9, V11) |
| `tests/test_core/test_workflow_validator_outputs.py` | 7 | No | No |
| `tests/test_execution/test_runner.py` | 1 | No | No |
| `tests/test_integration/test_unused_inputs.py` | 8 | No | No |
| `tests/test_runtime/test_template_integration.py` | 2 | No | No |
| `tests/test_runtime/test_template_validation/test_array_notation.py` | 2 | No | No |
| `tests/test_runtime/test_template_validation/test_batch_item_validation.py` | 24 | **Yes** (`"Did you mean"` × 2) | **Yes** (BV1, BV2) |
| `tests/test_runtime/test_template_validation/test_enhanced_errors.py` | 9 | No | **Yes** (PV3 / `_build_enhanced_node_diagnostic`) |
| `tests/test_runtime/test_template_validation/test_malformed.py` | 13 | No | No |
| `tests/test_runtime/test_template_validation/test_types.py` | 41 | No | **Yes** (TY1, TY2, TY3) — mostly for the untouched tests, S1/S5 already done |
| `tests/test_runtime/test_template_validation/test_union_types.py` | 14 | No | No |
| `tests/test_runtime/test_template_validation/test_unused_inputs.py` | 22 | No | No |
| `tests/test_runtime/test_template_validation/test_validator.py` | 40 | **Yes** (`"Available outputs"` × 1) | **Yes** (orchestrator end-to-end, excluding S2) |
| `tests/test_runtime/test_template_validation/test_warnings.py` | 7 | No | No |
| **NEW**: `tests/shared/diagnostic_helpers.py` | — | — | — |

**Total**: 260 helper call sites across 19 files. Rendered-content assertions that must be converted to structural: **4 known cases** (listed below in "Known rendered-content traps"). High-value structural promotion: **5 files**.

---

## Approach — three phases, three commits

### Phase 1 — Create the shared helper module

**New file**: `tests/shared/diagnostic_helpers.py`

```python
"""Shared helpers for tests that filter validator/template diagnostics by severity.

These helpers replace 19 identical local copies in test files introduced during
the task 147 test migration. The critical change from the originals: errors are
returned as typed ``Diagnostic`` objects, not pre-rendered ``format_diagnostic()``
strings. Callers should assert on ``errors[0].message`` for substring checks and
on ``errors[0].context[...]`` for structural checks.

See: spinje/pflow#238 (test-helper splits flatten structural assertions).
"""

from __future__ import annotations

from typing import Any

from pflow.core.diagnostic import Diagnostic, Severity


def split_validator_diagnostics(
    *args: Any, **kwargs: Any
) -> tuple[list[Diagnostic], list[Diagnostic]]:
    """Run ``WorkflowValidator.validate`` and split by severity.

    Returns:
        ``(errors, warnings)`` — both are lists of ``Diagnostic`` objects,
        NOT pre-rendered strings. Substring matches should use
        ``errors[0].message`` (raw) instead of the rendered block.
    """
    from pflow.core.workflow.validator import WorkflowValidator

    diagnostics = WorkflowValidator.validate(*args, **kwargs)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    warnings = [d for d in diagnostics if d.severity == Severity.WARNING]
    return errors, warnings


def split_template_diagnostics(
    *args: Any, **kwargs: Any
) -> tuple[list[Diagnostic], list[Diagnostic]]:
    """Run ``validate_workflow_templates`` and split by severity.

    Returns:
        ``(errors, warnings)`` — both are lists of ``Diagnostic`` objects,
        NOT pre-rendered strings. Substring matches should use
        ``errors[0].message`` (raw) instead of the rendered block.
    """
    from pflow.runtime.template_validation import validate_workflow_templates

    diagnostics = validate_workflow_templates(*args, **kwargs)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    warnings = [d for d in diagnostics if d.severity == Severity.WARNING]
    return errors, warnings
```

Key design decisions (justify these to yourself before deviating):

1. **Public names** (`split_validator_diagnostics`, not `_split_...`). These are shared across the test suite — they shouldn't be private. The leading underscore in the original local copies was a Python convention to mark them as "don't import this from another test file" which is no longer relevant.

2. **Return `Diagnostic`, not `str`.** This is the entire point of the fix. Do NOT call `format_diagnostic()` inside the helper.

3. **Lazy imports** of `WorkflowValidator` and `validate_workflow_templates`. Matches the convention in the existing helpers, avoids import-time side effects in test collection.

4. **`*args, **kwargs` passthrough.** Call-site signatures vary across the 19 files (some pass 3 positional args, some use keyword args, some use `extracted_params=` explicitly). Passthrough preserves all of them without per-file decisions.

5. **No docstring examples** of `.message` vs structural access — the convention is spelled out in the CLAUDE.md additions and in this plan, not repeated in every helper.

**Commit 1 message suggestion**:
```
test: add shared diagnostic split helpers for task 147 follow-up (spinje/pflow#238)

Introduce tests/shared/diagnostic_helpers.py with canonical
split_validator_diagnostics and split_template_diagnostics helpers.
Both return typed Diagnostic objects (not pre-rendered strings), so
callers can assert on .message for substring checks and on .context
for structural checks.

Sweep of the 19 local copies follows in a separate commit.

Refs: spinje/pflow#238
```

After this commit: `make check` must pass (the file is syntactically valid and typed correctly). Tests are unchanged and still pass.

---

### Phase 2 — Mechanical sweep of the 19 call sites

**What changes in every file**:

1. Delete the local `_split_validator_diagnostics` / `_split_template_diagnostics` function definition (and the `from pflow.core.diagnostic import format_diagnostic` import inside it, if present).

2. Add an import near the top of the file:
   ```python
   from tests.shared.diagnostic_helpers import (
       split_validator_diagnostics,
       split_template_diagnostics,
   )
   ```
   Import only what the file actually uses — if the file only calls `_split_template_diagnostics`, only import `split_template_diagnostics`.

3. Rename all call sites: `_split_validator_diagnostics(...)` → `split_validator_diagnostics(...)`. Same for template.

4. Update substring assertions: `errors[0]` → `errors[0].message`, and generator forms like `any("X" in e for e in errors)` → `any("X" in d.message for d in errors)`. Preserve the existing string content in the assertion — just change what you're matching against.

5. **Known rendered-content traps** — four call sites match against text that only exists in the RENDERED block, not in `.message`. Handle these as **structural assertions** instead of `.message` substrings:

   | File | Line(s) | Current assertion | Replace with |
   |---|---|---|---|
   | `tests/test_runtime/test_template_validation/test_batch_item_validation.py` | 152 | `assert "Did you mean" in errors[0]` | `assert errors[0].context is not None and errors[0].context.get("similar_names")` |
   | `tests/test_runtime/test_template_validation/test_batch_item_validation.py` | 692 | `assert "Did you mean" in errors[0]` | Same as above |
   | `tests/test_runtime/test_template_validation/test_validator.py` | 746 | `assert "Available outputs" in error, ...` | `assert error.context.get("available_fields") and error.context.get("available_fields_label") == "outputs"` |
   | `tests/test_core/test_unknown_param_validation.py` | 101, 340 | `assert "Did you mean" in error_text` | `assert diagnostic.context.get("similar_names")` (re-name the local variable from `error_text` to `diagnostic`) |

   **Why structural is strictly stronger**: these assertions were testing "the producer populated enough data to make the renderer emit this block." The producer field (`similar_names`, `available_fields`) is the actual source of truth — matching against the rendered header is a proxy for it that can silently break if the renderer ever changes its heading text.

   **Verify the line numbers** — they're from a snapshot at plan-writing time. If the file has drifted, `grep -n '"Did you mean"\|"Available outputs"'` in the file will locate the current lines.

6. **Watch for these assertion patterns** — they all need the same `.message` update:

   ```python
   # Pattern 1 — direct index
   assert "foo" in errors[0]               → assert "foo" in errors[0].message

   # Pattern 2 — substring in generator
   assert any("foo" in e for e in errors)  → assert any("foo" in d.message for d in errors)

   # Pattern 3 — string join (rare but exists)
   "\n".join(errors)                       → "\n".join(d.message for d in errors)

   # Pattern 4 — list filter
   [e for e in errors if "foo" in e]       → [d for d in errors if "foo" in d.message]

   # Pattern 5 — variable assignment
   error = errors[0]                       → error = errors[0]           # variable stays a Diagnostic
   assert "foo" in error                   → assert "foo" in error.message

   # Pattern 6 — set comprehension
   {e for e in errors if ...}              → {d.message for d in errors if ...}  # if you need the strings
                                           → {d for d in errors if ...}          # if you need the Diagnostics
   ```

   These are the 6 patterns from the original task 147 implementation plan section "Test rewrites (~309 assertions)". The original plan called them Patterns 1–7; Pattern 7 ("tuple unpack → single list + filter") no longer applies after Phase 1 introduces the shared helper.

7. **Do NOT** convert `assert len(errors) == N` checks — those are still valid against `list[Diagnostic]`. They change shape implicitly (now counting Diagnostics instead of strings) but the assertion is identical.

8. **Do NOT** change test names, docstrings, or class structure during this phase. Pure mechanical rewrite. Reviewers should see "helper removed + call sites updated" and nothing else.

**Commit 2 message suggestion**:
```
test: sweep 19 callers to use shared diagnostic helpers (spinje/pflow#238)

- Remove 19 local copies of _split_validator_diagnostics /
  _split_template_diagnostics.
- Replace with imports from tests.shared.diagnostic_helpers.
- Update ~260 assertions from matching rendered-block strings to
  matching Diagnostic.message (raw error text).
- Convert 4 rendered-content assertions to structural assertions on
  context fields (similar_names, available_fields) — strictly stronger
  than the original header-substring checks.

No production code changes.

Refs: spinje/pflow#238
```

**Verification after this commit**:
```bash
# Must return ZERO matches in tests/ (pycache hits don't count)
grep -rn --include='*.py' '_split_validator_diagnostics\|_split_template_diagnostics' tests/

# Should show 19 files importing from the shared module
grep -rln --include='*.py' 'from tests.shared.diagnostic_helpers import' tests/ | wc -l
# Expected: 19

# Full test suite must pass
make test

# Lint + types must pass
make check
```

If `make test` fails after this commit, the most likely cause is missing a rendered-content assertion beyond the four known ones. Run the failing test in isolation and check whether it asserts on text that isn't in `.message`. If the text is only in the rendered output, convert to a structural assertion on the producing context field.

---

### Phase 3 — Additive structural assertions in 5 high-value files

This phase makes the architectural contract of task 147 actually enforced by tests. For each file, add 2–4 new structural assertions **alongside** (not replacing) the existing substring tests. The goal is to lock in the producer's promise: "this producer always populates these specific context fields with these specific shapes."

**Important**: before writing any assertion, **run the producer once** to capture the actual Diagnostic shape. The plan's assertion targets are based on reading the producer code, but a 30-second sanity check via `python -c "..."` catches drift that would otherwise cost an iteration. Example:

```bash
uv run python -c "
from pflow.core.workflow.validator import WorkflowValidator
from pflow.registry import Registry
registry = Registry()
ir = {
    'ir_version': '0.1.0',
    'nodes': [{'id': 'n1', 'type': 'nonexistent-type', 'params': {}}],
    'edges': [],
}
for d in WorkflowValidator.validate(ir, registry=registry):
    print(d.severity, d.title, d.node_id, d.message)
    print('  context:', d.context)
    print('  suggestions:', d.suggestions)
"
```

This snippet is your fastest reality check. Use variants of it for each producer before writing its structural assertion.

#### File 3a — `tests/test_core/test_workflow_validator.py`

Target the richest outer-layer producers. Add one new test per producer below, inside the most topically-appropriate test class (or at module level if no class fits).

1. **V6 — Unknown node type** (`_validate_node_types`):
   ```python
   def test_unknown_node_type_diagnostic_preserves_structure(self) -> None:
       """V6 producer must populate node_id, path, node_type, and similar_names."""
       registry = Registry()
       ir = {
           "ir_version": "0.1.0",
           "nodes": [{"id": "n1", "type": "shel", "params": {"command": "echo hi"}}],
           "edges": [],
       }
       errors, _ = split_validator_diagnostics(ir, registry=registry, skip_node_types=False)
       assert len(errors) == 1
       d = errors[0]
       assert d.severity == Severity.ERROR
       assert d.node_id == "n1"
       assert d.context is not None
       assert d.context.get("path") == "nodes[0].type"
       assert d.context.get("node_type") == "shel"
       # similar_names: "shell" should fuzzy-match "shel"
       assert d.context.get("similar_names")
       assert any("shell" in name for name in d.context["similar_names"])
   ```

2. **V8 — Empty output source** (`_validate_output_sources`):
   ```python
   def test_empty_output_source_diagnostic_preserves_path(self) -> None:
       """V8 producer must populate outputs.{name}.source path."""
       ir = {
           "ir_version": "0.1.0",
           "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo hi"}}],
           "outputs": {"result": {"source": ""}},
           "edges": [],
       }
       errors = WorkflowValidator._validate_output_sources(ir)
       assert len(errors) == 1
       d = errors[0]
       assert d.context is not None
       assert d.context.get("path") == "outputs.result.source"
   ```

3. **V9 — `_build_node_not_found_diagnostic`**:
   ```python
   def test_output_source_references_missing_node_preserves_structure(self) -> None:
       """V9 producer must populate available_fields + similar_names + path."""
       ir = {
           "ir_version": "0.1.0",
           "nodes": [
               {"id": "producer", "type": "shell", "params": {"command": "echo hi"}},
           ],
           "outputs": {"result": {"source": "producre"}},  # typo
           "edges": [],
       }
       errors = WorkflowValidator._validate_output_sources(ir)
       assert len(errors) == 1
       d = errors[0]
       assert d.context is not None
       assert d.context.get("path") == "outputs.result.source"
       assert "producer" in d.context.get("available_fields", [])
       assert d.context.get("available_fields_label") == "nodes"
       assert d.context.get("similar_names")
       assert any("producer" in name for name in d.context["similar_names"])
   ```

4. **V11 — `_build_template_node_diagnostic`**:
   ```python
   def test_output_source_template_references_missing_node_preserves_structure(self) -> None:
       """V11 producer must populate template + available_fields + similar_names."""
       ir = {
           "ir_version": "0.1.0",
           "nodes": [
               {"id": "producer", "type": "shell", "params": {"command": "echo hi"}},
           ],
           "outputs": {"result": {"source": "${producre.stdout}"}},  # typo
           "edges": [],
       }
       errors = WorkflowValidator._validate_output_sources(ir)
       assert len(errors) == 1
       d = errors[0]
       assert d.title == "Template Error"
       assert d.context is not None
       assert d.context.get("template") == "${producre.stdout}"
       assert "producer" in d.context.get("available_fields", [])
       assert d.context.get("similar_names")
       assert d.suggestions  # V11 produces "Change X to Y" style suggestions
   ```

Place these tests inside a new class `class TestValidatorProducerStructure:` near the bottom of the file, next to `TestDefensiveWrapperDiagnostics`.

#### File 3b — `tests/test_runtime/test_template_validation/test_enhanced_errors.py`

Target the PV3 producer (`_build_enhanced_node_diagnostic`) — the 76-line highest-value path_validation producer. The existing S2 test covers the batch case; this file should lock in the non-batch case.

Add one test at module level:

```python
def test_enhanced_node_diagnostic_non_batch_preserves_structure(test_registry):
    """PV3 producer must populate available_fields (with ${node.key} format),
    suggestions (with 'Change X to Y' prefix), and similar_names.

    Non-batch case. S2 covers batch.
    """
    workflow_ir = {
        "enable_namespacing": True,
        "inputs": {},
        "nodes": [
            {"id": "producer", "type": "llm", "params": {"prompt": "hi"}},
            {
                "id": "consumer",
                "type": "write-file",
                "params": {
                    "file_path": "out.txt",
                    "content": "${producer.responce}",  # typo
                },
            },
        ],
        "edges": [{"from": "producer", "to": "consumer"}],
    }
    diagnostics = validate_workflow_templates(workflow_ir, {}, test_registry)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    assert len(errors) == 1
    d = errors[0]
    assert d.title == "Template Error"
    assert d.node_id == "producer"
    assert d.context is not None
    assert d.context.get("available_fields_label") == "outputs"
    # Each available_field is formatted as "${producer.X} (type)"
    assert any("${producer.response}" in f for f in d.context.get("available_fields", []))
    # Suggestion should fuzzy-correct typo
    assert d.suggestions
    assert any("response" in s for s in d.suggestions)
```

**Why this matters**: PV3 is explicitly called out in the task 147 spec as "the highest-value conversion." S2 already verifies the batch path; this covers the non-batch path. Together they lock in the producer's contract for both call paths.

#### File 3c — `tests/test_runtime/test_template_validation/test_types.py`

Target TY2 (shell single-template blocked) and TY3 (shell multi-template blocked) — both produce rich structured suggestions with shell_command context. S5 (`test_shell_blocks_dict_list_union`) already covers the union-type path. Add one test for the multi-template case, which S5 does NOT cover:

```python
def test_shell_blocks_multiple_structured_templates_preserves_structure(test_registry):
    """TY3 producer must populate blocked_templates list + shell_command + 4 suggestions."""
    workflow_ir = {
        "enable_namespacing": True,
        "inputs": {},
        "nodes": [
            {"id": "a", "type": "dict-producer", "params": {}},
            {"id": "b", "type": "list-producer", "params": {}},
            {
                "id": "shell-node",
                "type": "shell",
                "params": {"command": "echo ${a.data} ${b.items}"},
            },
        ],
        "edges": [
            {"from": "a", "to": "shell-node"},
            {"from": "b", "to": "shell-node"},
        ],
    }
    diagnostics = validate_workflow_templates(workflow_ir, {}, test_registry)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR and "multiple" in d.message]
    assert len(errors) == 1
    d = errors[0]
    assert d.context is not None
    assert d.context.get("path") == "nodes[id=shell-node].params.command"
    assert "shell_command" in d.context
    # 4 structured fix options per TY3 spec
    assert d.suggestions and len(d.suggestions) == 4
    assert any("temp files" in s for s in d.suggestions)
    assert any("stdin" in s for s in d.suggestions)
    # blocked_templates list preserves each template's type
    blocked = d.context.get("blocked_templates")
    assert isinstance(blocked, list) and len(blocked) == 2
```

**Important**: the `dict-producer` and `list-producer` types need to exist in the file's `test_registry`. If they don't, either reuse `dict-list-union-producer` from S5 with a two-node variant, or add the minimal required mock metadata. Do NOT modify S5.

#### File 3d — `tests/test_runtime/test_template_validation/test_batch_item_validation.py`

Target BV1 (`_build_batch_item_field_diagnostic`) and BV2 (`_build_batch_item_nested_diagnostic`). Existing substring tests verify the messages; add structural assertions for the rich batch-specific context.

Add one test for BV1 (top-level field miss) and one for BV2 (nested field miss):

```python
def test_batch_item_field_miss_preserves_batch_context(test_registry):
    """BV1 producer must populate items_source, batch_alias, and available_fields."""
    workflow_ir = {
        # ... build a workflow where a batch node references a non-existent ${item.X}
        # (see existing tests in this file for the shape)
    }
    diagnostics = validate_workflow_templates(workflow_ir, {}, test_registry)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    assert errors
    d = errors[0]
    assert d.context is not None
    assert d.context.get("batch_alias")  # default "item" or whatever the workflow set
    assert d.context.get("items_source")  # the ${upstream.results} template
    assert d.context.get("available_fields_label") == "batch item fields"
    assert d.context.get("available_fields")  # list of valid ${item.field} (type) entries


def test_batch_item_nested_miss_preserves_parent_path(test_registry):
    """BV2 producer must populate parent_path + parent_type."""
    # Similar shape but with ${item.a.b.missing} where 'a.b' is valid but 'missing' is not
    ...
    d = errors[0]
    assert d.context is not None
    assert d.context.get("parent_path")  # "item.a.b"
    assert d.context.get("parent_type")  # type of 'b'
    assert d.context.get("available_fields_label") == "nested fields"
```

The test bodies need real workflow IRs that trigger the specific validation path. Look at existing tests in this file (the ones that currently use `_split_template_diagnostics`) for the correct workflow shape, then reuse the minimum necessary structure.

#### File 3e — `tests/test_runtime/test_template_validation/test_validator.py`

This is the orchestrator file. Target one end-to-end producer that isn't covered by S2: the **TV1 unused-inputs** producer and the **TV2 malformed-template** producer. These aren't glamorous but they produce unique context keys (`unused_inputs`, `template` with malformed content) that no other test currently locks in.

```python
def test_unused_inputs_diagnostic_preserves_list(self):
    """TV1 producer must populate context['unused_inputs'] with a sorted list."""
    workflow_ir = {
        "inputs": {"used_one": {"type": "str"}, "unused_one": {"type": "str"}, "unused_two": {"type": "str"}},
        "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo ${used_one}"}}],
        "edges": [],
    }
    registry = create_mock_registry()
    diagnostics = validate_workflow_templates(workflow_ir, {"used_one": "x"}, registry)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    assert len(errors) == 1
    d = errors[0]
    assert d.context is not None
    assert d.context.get("path") == "inputs"
    assert d.context.get("unused_inputs") == ["unused_one", "unused_two"]  # sorted
    assert d.suggestions  # "Remove unused declarations..."


def test_malformed_template_diagnostic_preserves_template_text(self):
    """TV2 producer must populate context['template'] with the raw malformed string."""
    workflow_ir = {
        "nodes": [{"id": "n1", "type": "shell", "params": {"command": "echo ${unclosed"}}],
        "edges": [],
    }
    registry = create_mock_registry()
    diagnostics = validate_workflow_templates(workflow_ir, {}, registry)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    assert len(errors) == 1
    d = errors[0]
    assert d.title == "Template Error"
    assert d.context is not None
    assert d.context.get("template") == "echo ${unclosed"
    assert d.context.get("path") == "nodes[id=n1].params.command"
```

**Commit 3 message suggestion**:
```
test: lock in producer structural contract for 5 high-value files (spinje/pflow#238)

Add additive structural assertions on the richest task 147 producers:
- V6/V8/V9/V11 in test_workflow_validator.py (outer validator helpers)
- PV3 non-batch in test_enhanced_errors.py (highest-value path_validation rewrite)
- TY3 multi-template in test_types.py (shell command safety, multi case)
- BV1/BV2 in test_batch_item_validation.py (batch item field validators)
- TV1/TV2 in test_validator.py (unused inputs, malformed templates)

These assertions verify producer.context[...] fields directly, locking
in the producer self-description contract that task 147 established but
the migrated tests didn't individually verify. Together with the 8
existing structural guards and the 5 S-series hardenings, the producer
contract is now covered for every rich diagnostic the task 147 arc
introduced.

Refs: spinje/pflow#238
Closes: spinje/pflow#238
```

---

## Verification — the full checklist

Run these checks in order. Do NOT mark the task done until all of them pass.

### After Commit 1 (new shared helper)

```bash
# Syntax + types
make check

# Test suite unaffected (helpers not yet swept)
make test
```

Expected: both clean. The new file exists and imports resolve, but no tests use it yet.

### After Commit 2 (sweep)

```bash
# Zero remaining local helper definitions
grep -rn --include='*.py' '_split_validator_diagnostics\|_split_template_diagnostics' tests/
# Expected: zero matches

# All 19 files now import from shared
grep -rl --include='*.py' 'from tests.shared.diagnostic_helpers import' tests/ | wc -l
# Expected: 19

# No remaining format_diagnostic imports that were only there for the old helper
grep -rn --include='*.py' 'from pflow.core.diagnostic import format_diagnostic' tests/
# Expected: only legitimate uses (e.g., tests that actually test format_diagnostic itself)

# Full test suite + lint
make test
make check
```

Expected: all clean. `make test` should show the same test count as before (no tests added or removed in Phase 2).

### After Commit 3 (structural promotions)

```bash
# Full test suite + lint
make test
make check

# Count new tests — should be 10–12 new tests (2–4 per file × 5 files)
git diff --stat main..HEAD -- tests/test_core/test_workflow_validator.py
# Expected: ~80–120 lines added (4 new tests × ~20 lines each)
```

### Manual sanity check

Pick two tests at random from the sweep (Phase 2) — one that tests an error case and one that tests a warning case — and verify:
1. The test still asserts meaningfully on the actual producer output.
2. Substring matches land on the raw `.message`, not on rendered block content.
3. No `format_diagnostic()` calls remain in the test file (unless the file explicitly tests the renderer, which none of the 19 do).

### Definition of done

- `grep -rn '_split_validator_diagnostics\|_split_template_diagnostics' tests/` → zero matches (excluding `__pycache__`)
- `make test` → clean
- `make check` → clean (ruff + ruff-format + mypy + deptry)
- All 19 files import from `tests.shared.diagnostic_helpers`
- 10–12 new structural assertions added across the 5 high-value files
- Three logical commits referencing `spinje/pflow#238`
- No production code (`src/pflow/...`) modified

---

## Risks and edge cases

### Risk: undiscovered rendered-content assertions

The plan lists 4 known cases. There may be more. Signs that you've hit an undiscovered case:
- A test that used to pass now fails with "expected substring 'X' in 'Y'" where 'Y' is a short message.
- The substring being matched is a header-like phrase ("Did you mean", "Available", "To fix this", "Error 1", etc.) that comes from `format_diagnostic()`'s templating, not from a producer's `.message`.

**How to handle**: convert to a structural assertion on the producing context field. Don't fall back to re-rendering with `format_diagnostic()` and substring-matching the rendered text — that reintroduces the exact smell this issue is fixing.

### Risk: a test file has a mix of validator and template helpers

`tests/test_core/test_workflow_validator.py` and `tests/test_runtime/test_template_validation/test_validator.py` both have _both_ `_split_validator_diagnostics` AND `_split_template_diagnostics` defined locally. Make sure you import both from the shared module when sweeping these files.

### Risk: the file has a test-only helper that depends on format_diagnostic

Check each file after the sweep for `from pflow.core.diagnostic import format_diagnostic`. If the import is only there because of the old helper, remove it. If it's used for a legitimate renderer test, leave it. Grep for `format_diagnostic(` usage inside the file to tell the difference.

### Risk: mypy complains about `.context` being `Optional[dict]`

`Diagnostic.context: dict[str, Any] | None`. Accessing `.context.get(...)` on a diagnostic that might have `context=None` is fine at runtime (None would AttributeError on `.get`). But mypy will flag it. Handle it with:
```python
assert d.context is not None
# then use d.context.get(...) freely
```
or use the walrus-style guard `if (ctx := d.context) and ctx.get(...)`. Either is fine — pick whichever reads clearer at the call site.

### Risk: Phase 3 assertions depend on producer internals that might change

The structural assertions lock in the producer's *output shape*, which is a public contract (they're what agents consuming JSON see). They're intentionally stronger than substring matches — if a producer's context keys change, these tests SHOULD fail, and someone has to decide whether the change is intentional or a regression. That's the point.

If you find yourself writing an assertion that depends on an implementation detail (e.g., the exact order of items in `available_fields`), back off and assert on set membership instead of list equality.

### Risk: the sweep accidentally removes a `_split_*` call that isn't the task 147 helper

Unlikely (the function names are specific), but grep your final diff to verify:
```bash
git diff main..HEAD | grep '^-' | grep '_split_' | grep -v 'diagnostics'
```
If this returns anything, you've accidentally deleted something unrelated. Inspect and restore.

---

## What NOT to do (repeating for emphasis)

- Do NOT touch `src/pflow/...`.
- Do NOT rewrite substring assertions that are legitimately testing message content. Just point them at `.message`.
- Do NOT add structural assertions outside the 5 high-value files.
- Do NOT duplicate the existing structural guards (S1–S5, the 4 defensive wrapper tests, the 3-level nesting test, the `test_unknown_param_diagnostic_preserves_structure` test, the `test_json_rich_validation_error_preserves_context_fields` test).
- Do NOT try to merge mock-registry definitions across test files.
- Do NOT rename tests, test classes, or test files.
- Do NOT add new test files beyond the shared helper module.
- Do NOT use `format_diagnostic()` inside the shared helper (that's the smell you're fixing).
- Do NOT skip the `gh issue view 238` step at the top.
- Do NOT merge the three commits into one — keep them logical for review.
- Do NOT commit without running `make test && make check` at each commit boundary.

---

## References

- **Issue**: spinje/pflow#238
- **Parent task**: Task 147 (`.taskmaster/tasks/task_147/`)
- **Progress log with original deviation context**:
  `.taskmaster/tasks/task_147/implementation/progress-log.md`
  (search for "2026-04-07 — Implementation step 5" and "Smell 1: 19 test-helper splits")
- **Original test rewrite patterns**:
  `.taskmaster/tasks/task_147/implementation/implementation-plan.md`
  (search for "Test rewrites (~309 assertions)")
- **Architectural principle** (producers are self-describing):
  Tasks 141 → 143 → 144 → 147 arc. Read task 144's review if you want the deep context.

---

## Final note to the implementing agent

This is a test-quality improvement, not a bug fix. The existing tests pass. The code under test works. What's broken is the test suite's **ability to detect a future regression** in producer context fields.

That means:
- The bar for "done" is "the test suite now catches regressions it previously would have missed," not "all tests pass."
- You should deliberately verify, for at least one Phase 3 assertion, that temporarily breaking the producer (e.g., commenting out the `similar_names` key in `_validate_unknown_params`) causes your new test to fail. Then restore the producer and confirm the test passes again. If the test doesn't fail when the producer is broken, the assertion is too weak — rewrite it.
- This mutation-style sanity check is the only way to know the structural contract is actually enforced. Do it at least once before declaring the task done, then mention in the PR description which producer you broke and which assertion caught it.

Good luck.
