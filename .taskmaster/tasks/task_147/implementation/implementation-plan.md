# Plan: Validator Produces Diagnostics Natively (Issue #219)

**Branch**: `fix/workflow-validator-return-type`
**Worktree**: `/Users/andfal/projects/pflow-fix-workflow-validator-return-type`
**GitHub issue**: spinje/pflow#219

---

## Context

`WorkflowValidator.validate()` currently returns `tuple[list[str], list[Diagnostic]]` — errors as flat strings, warnings as Diagnostics. Every internal helper builds error strings that discard already-computed structural data (paths, fuzzy matches, available options, concrete fixes). The consumer (`runner.py`) then **fabricates** generic Diagnostics from those strings and **reverse-engineers** suggestions via `generate_validation_suggestions()` pattern matching. A `# type: ignore[arg-type]` at `runner.py:393` papers over the mismatch with `WorkflowValidationError.validation_errors: list[str | tuple]` — a tuple form nobody uses structurally.

This is the completion of the three-task arc:
- **Task 141** — consolidated the **exception hierarchy** under `PflowError`
- **Task 143** — consolidated the **output type** (3 warning types → `Diagnostic`)
- **Task 144** — consolidated the **rendering** (6 paths → 1; central 13-branch converter → polymorphic `to_diagnostics()` on exceptions)

Task 144's review explicitly names #219 as known debt:
> `format_validation_failure()` accepts `list[Any]` — should be `list[Diagnostic]` once `WorkflowValidator.validate()` returns Diagnostics (spinje/pflow#219).

The architectural principle established by 144 is: **"producers are self-describing"**. Exceptions don't go through a central dispatcher — they implement `to_diagnostics()`. We apply the same principle to validation checks: each check site knows the structured data, so it builds a `Diagnostic` directly. No string intermediate. No wrapper step. Symmetry with how exceptions, parser warnings, and runtime events already work.

**Outcome**: A validation error on a non-existent node reference currently renders as:
```
✗ Validation failed (2 errors):
  1. Node 'broken' references non-existent node 'nonexistant' in parameter 'command'
  2. Template variable ${nonexistant.stdout} has no valid source - '${nonexistant}' ...
  ℹ Check template syntax: ${node.output}          ← generic pattern-matched fallback
```

After this change, it renders as:
```
Error 1: Validation Error

Node 'broken' references non-existent node 'nonexistant' in parameter 'command'.
  At: node 'broken', nodes[1].params.command

Did you mean one of these?
  - valid_node

  → Reorder nodes or fix the reference to point at an existing node.
```

All of the location, fuzzy match, and suggestion data is already computed inside the validator — we just stop flattening it.

---

## Plan review corrections (added 2026-04-07)

This plan was reviewed by 4 specialized agents (review-plan, review-impact-completeness, review-feature-interactions, review-validation-consistency) before implementation. Their findings produced the following corrections, all of which are integrated into the relevant sections below:

1. **CRITICAL — `format_validation_failure()` rewrite added to scope**: the dominant CLI/MCP text path's formatter (validation_formatter.py) only renders 3 fields per error (message, path, suggestions[0]). Without rewriting it to delegate to `format_diagnostic()`, the user-visible improvement promised by issue #219 captures only the JSON output mode. See "src/pflow/execution/formatters/validation_formatter.py — REVIEW ADDITION" section.

2. **CRITICAL — `WorkflowExecutor._propagate_child_parser_warnings:337` fix added**: runtime parser-warning propagation uses `node_id=step_id` (always overwrites), validator path uses `d.node_id or step_id` (preserves child's). After this PR's V16 conversion, errors flow through the validator path with the child-preserving policy, but runtime warnings still use the overwriting policy. Different node_ids → different `Diagnostic.__hash__` → no dedup → duplicate diagnostics if validation and runtime hit the same workflow. One-line fix at workflow_executor.py:337. See "src/pflow/runtime/workflow_executor.py:337 — REVIEW ADDITION" section.

3. **CONFIRMED — compile_validation.py needs explicit error filter**: the plan originally described the compiler consumer update as a "one-line change `e` → `d.message`". The truthiness check `if data_flow_diagnostics:` doesn't filter to errors. Currently dormant (no warnings come from data_flow.py today) but creates latent regression. Fix is two lines instead of one. See "Compiler consumer update" section.

4. **CONFIRMED — full conversions added for V9 and V11**: validator.py:`_format_node_not_found_error` and `_format_template_node_error` are multi-section helpers that the plan originally described in table cells only. Both now have full before/after code, matching the level of detail in V12. See "V9" and "V11" sections.

5. **CONFIRMED — 6 documentation files added to scope**: `src/pflow/mcp_server/services/CLAUDE.md:82`, `src/pflow/core/CLAUDE.md:58, 77 + validation_utils.py paragraph`, `architecture/reference/template-variables.md:439-450, 1598`. Old signatures need updating.

6. **CONFIRMED — pre-implementation grep audit added**: catches missed sites before coding begins. See "Before implementation begins" section.

7. **CONFIRMED — `_validate_data_flow` wrapper is load-bearing, not dead code**: the plan originally described `except Exception` wrappers as "becomes dead code" after conversion. They actually catch `TypeError` from `Diagnostic.__post_init__` when a producer accidentally passes `suggestions="string"` instead of `suggestions=["string"]`. Keep them in place. See Risk 8.

**Disputed findings** (verified false during review, NOT applied to plan):

- ❌ "Tests substring-match against multi-line rendered text (Available outputs / Did you mean / Items come from)" — verified zero matches in actual test files. Tests assert on individual error message content, which the 7 mechanical patterns cover correctly.
- ❌ "CycleError signature change breaks external callers" — verified only one call site (`data_flow.py:93` itself). Safe to change.
- ❌ "Dropping `Data flow error:` prefix breaks substring tests" — verified both grep matches are comments, not assertions.
- ❌ "`test_workflow_save_service.py:334` substring depends on V11" — V11's new message preserves the `non-existent node 'X'` substring. Test passes naturally.

---

## User-approved decisions (already settled)

1. **Option D** — full conversion across all three validator layers in one PR.
2. **Single list return** — `WorkflowValidator.validate() -> list[Diagnostic]` (not a tuple). Severity is a field on `Diagnostic`.
3. **`WorkflowValidationError.validation_errors: list[Diagnostic]`** — the tuple/string union is deleted.
4. **Delete `generate_validation_suggestions()`** in full.
5. **Use `format_child_provenance()`** for sub-workflow error propagation (symmetry with warnings path established in Task 143).
6. All three validator layers (`WorkflowValidator.validate`, `validate_workflow_templates`, `validate_data_flow`) converted together in one PR.
7. **Keep `WorkflowValidationError(summary=str)` single-string constructor** unchanged — only `validation_errors` field type changes.
8. **Sub-workflow provenance**: keep child's `context["path"]` untouched (it's relative to the child IR), add `context["sub_workflow_step"] = step_id` + `context["sub_workflow_path"] = ref_label` for parent context.

---

## Scope

### In scope

| File | Change kind |
|---|---|
| `src/pflow/core/workflow/data_flow.py` | Convert `validate_data_flow()` to return `list[Diagnostic]` + all helpers |
| `src/pflow/runtime/template_validation/validator.py` | Convert `validate_workflow_templates()` + 2 helpers |
| `src/pflow/runtime/template_validation/path_validation.py` | Convert 15 producers (highest-value file — `format_enhanced_node_error` is the biggest win) |
| `src/pflow/runtime/template_validation/type_validation.py` | Convert 3 producers (shell command error with 4 fix options) |
| `src/pflow/runtime/template_validation/batch_item_validation.py` | Convert 2 producers |
| `src/pflow/core/workflow/validator.py` | Convert 9 helpers + orchestrator return type |
| `src/pflow/core/diagnostic.py` | ONE change: broaden `available_fields` gate (rename `_format_template_error_lines` → `_format_available_fields_block`) |
| `src/pflow/core/exceptions.py` | `WorkflowValidationError.validation_errors: list[Diagnostic]`, simplify `to_diagnostics()` |
| `src/pflow/execution/runner.py` | Simplify (delete fabrication + reverse-engineered suggestions + `type: ignore`) |
| `src/pflow/core/workflow/save_service.py` | Rebuild error aggregation from Diagnostics instead of string joining |
| `src/pflow/cli/main.py:631-640` | Rewrite invalid-parameter-names path to construct Diagnostic |
| `src/pflow/runtime/compilation/compile_validation.py:115-125` | Update `.message` extraction from new `validate_data_flow()` return + **filter to errors** (see Section "compile_validation.py filter requirement") |
| `src/pflow/core/validation_utils.py` | **Delete** `generate_validation_suggestions()` function |
| **`src/pflow/execution/formatters/validation_formatter.py`** | **(REVIEW ADDITION)** Rewrite `format_validation_failure()` to delegate to `format_diagnostic()` so the dominant CLI/MCP text path actually shows the new structured fields. **WITHOUT THIS, the user-visible improvement is captured only in JSON output mode.** |
| **`src/pflow/runtime/workflow_executor.py:337`** | **(REVIEW ADDITION)** Change `node_id=step_id` → `node_id=d.node_id or step_id` to align runtime parser-warning propagation with validator path. Fixes a latent dedup asymmetry that the plan would otherwise lock in for errors. |
| **`src/pflow/mcp_server/services/CLAUDE.md`** | **(REVIEW ADDITION)** Update line 82 example from `errors, warnings = WorkflowValidator.validate(...)` to single-list pattern |
| **`src/pflow/core/CLAUDE.md`** | **(REVIEW ADDITION)** Update line 77 exception usage table (drop `[(msg, path, suggestion)]` tuple form), update `validation_utils.py` paragraph (remove `generate_validation_suggestions` description) |
| **`architecture/reference/template-variables.md`** | **(REVIEW ADDITION)** Update `validate_workflow_templates` signature docs (lines 439-450) and example code (line 1598) for single-list return |
| Tests (~20 files, ~309 assertions) | Rewrite per patterns in Section 10 |
| `.taskmaster/tasks/task_144/research/capture_baselines.py` | Rewrite `WorkflowValidationError` fixture to use Diagnostics |

### Out of scope (explicitly)

- **`prepare_inputs()` in `ir_preparation.py`** — produces tuples that route through `SchemaValidationError`, not `WorkflowValidationError`. A separate code path. Don't touch.
- **`_raise_input_validation_errors()` in `compile_validation.py:40-66`** — currently aggregates multiple input errors into a single `SchemaValidationError` with a combined message, losing per-error structure. Fixing this would improve compiler input error quality but is orthogonal to #219. Leave alone.
- **`SchemaValidationError`** — already self-describing via Task 144 `to_diagnostics()`. Don't touch.
- **Adding structured-output test assertions to every rewritten test** — prefer mechanical `.message` rewrites; add structure assertions (`.context["path"]`, `.suggestions`) to ~5 representative high-value tests.
- **Adding a `Registry.get_all_node_types()` method** for fuzzy-matching unknown node types against the full registry. The validator currently only loads metadata for queried types; broadening fuzzy matching is a nice-to-have but out of scope. For now, fuzzy match against the queried subset (`registry_types` set).

---

## Architectural principle

**Three layers** (the model established by Task 144):

```
Producer                         Data type              Rendering
───────────────                  ─────────              ─────────
Exception class                  Diagnostic             format_diagnostic()
  .to_diagnostics()    ───────►                ───────►   (ONE format)
Validation check                 list[Diagnostic]
  returns directly     ───────►
Runtime event
  emits directly       ───────►
```

The validator is stuck at "Layer 1.5" today — it has domain knowledge but represents it as strings, forcing the consumer to reverse-engineer structure via pattern matching. This PR moves it fully into Layer 1 (producer).

**Principle from Task 143/144**: _"The call site owns the context"_. When the validator's `_validate_unknown_params` helper discovers a typo, it **already computed** `find_similar_items()` fuzzy matches, the valid keys set, and the affected node_id. Emit that as structure, not as interpolated message text.

---

## New signatures

```python
# src/pflow/core/workflow/data_flow.py
def validate_data_flow(
    workflow_ir: dict[str, Any],
    check_inputs: bool = True,
) -> list[Diagnostic]: ...

class CycleError(Exception):
    def __init__(self, nodes_in_cycle: set[str]) -> None:
        self.nodes_in_cycle = sorted(nodes_in_cycle)  # NEW: structured attribute
        super().__init__(f"Circular dependency detected involving nodes: {', '.join(self.nodes_in_cycle)}")

# src/pflow/runtime/template_validation/validator.py
def validate_workflow_templates(
    workflow_ir: dict[str, Any],
    available_params: dict[str, Any],
    registry: Registry,
) -> list[Diagnostic]: ...  # Single list. Severity distinguishes errors from warnings.

# src/pflow/runtime/template_validation/path_validation.py
def validate_template_paths(...) -> list[Diagnostic]: ...  # Merged errors + warnings

# src/pflow/runtime/template_validation/type_validation.py
def validate_template_types(...) -> list[Diagnostic]: ...
def validate_shell_command_types(...) -> list[Diagnostic]: ...

# src/pflow/runtime/template_validation/batch_item_validation.py
def validate_batch_item_fields(...) -> list[Diagnostic]: ...

# src/pflow/core/workflow/validator.py
class WorkflowValidator:
    @staticmethod
    def validate(...) -> list[Diagnostic]: ...  # Single list. No tuple.
    # All 9 internal _validate_* helpers → list[Diagnostic]

# src/pflow/core/exceptions.py
class WorkflowValidationError(PflowError):
    def __init__(
        self,
        summary: str = "Workflow validation failed",
        validation_errors: list[Diagnostic] | None = None,  # was list[str | tuple[str, str, str]]
    ): ...
    def to_diagnostics(self) -> list[Diagnostic]:
        return self.validation_errors or [Diagnostic(
            severity=Severity.ERROR,
            message=self.summary,
            title="Validation Error",
            source="validation",
            context={"category": "validation"},
        )]
```

### Note on single-list vs tuple

Tests currently unpack `errors, warnings = WorkflowValidator.validate(...)` at ~30+ sites. After the change, they write:
```python
diagnostics = WorkflowValidator.validate(...)
errors = [d for d in diagnostics if d.severity == Severity.ERROR]
```

For tests that only care about errors (the majority), this is one extra line of filter. For tests that distinguish both severities, two extra lines. Mechanical, no semantic changes.

---

## The ONE required renderer change

**File**: `src/pflow/core/diagnostic.py`

The renderer currently gates the `available_fields` block on `context.get("category") == "template_error"` at line 207:
```python
# Current (line 194-213)
def _format_all_context_blocks(diagnostic: Diagnostic, context: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    lines.extend(_format_compilation_context_lines(context))
    lines.extend(_format_similar_names_block(context))
    lines.extend(_format_exception_type_line(context))

    if (raw := context.get("raw_response")) and isinstance(raw, dict):
        lines.extend(_format_api_response_lines(raw))

    if (mcp_error := context.get("mcp_error")) and isinstance(mcp_error, dict):
        lines.extend(_format_mcp_error_lines(mcp_error))

    if context.get("category") == "template_error":       # ← THIS GATE
        lines.extend(_format_template_error_lines(context))

    if "shell_command" in context:
        lines.extend(_format_shell_error_lines(context))

    return lines
```

**Change**: Remove the `template_error` gate. `available_fields` is a generic concept (valid parameters, valid nodes, valid inputs, valid batch item fields) — gating it on one category was an accident of initial implementation. After conversion, many non-template validators want to populate `available_fields` (e.g., unknown parameters → list valid params, unknown input → list declared inputs).

```python
# New
def _format_all_context_blocks(diagnostic: Diagnostic, context: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    lines.extend(_format_compilation_context_lines(context))
    lines.extend(_format_similar_names_block(context))
    lines.extend(_format_exception_type_line(context))

    if (raw := context.get("raw_response")) and isinstance(raw, dict):
        lines.extend(_format_api_response_lines(raw))

    if (mcp_error := context.get("mcp_error")) and isinstance(mcp_error, dict):
        lines.extend(_format_mcp_error_lines(mcp_error))

    lines.extend(_format_available_fields_block(context))  # Unconditional

    if "shell_command" in context:
        lines.extend(_format_shell_error_lines(context))

    return lines
```

**Also rename** the helper from `_format_template_error_lines` to `_format_available_fields_block` to reflect its actual purpose. Its body is unchanged; only the name + call site change.

The renamed function's early-return on `if not available:` preserves backward compatibility — diagnostics without `available_fields` render nothing, same as before.

**Validation**: Run `uv run python .taskmaster/tasks/task_144/research/capture_baselines.py before` before the change and `after` + `compare` afterwards. All existing fixtures should be identical; new fixtures (validator-produced diagnostics) should show the `available_fields` block.

---

## Diagnostic producer pattern (boilerplate every validator error follows)

```python
from pflow.core.diagnostic import Diagnostic, Severity

Diagnostic(
    severity=Severity.ERROR,                # Severity.ERROR for blocking errors, WARNING for lints
    source="validator",                     # Convention: "validator" for all validator-produced diagnostics
    title="Validation Error",               # or "Template Error" for template-class errors
    message="Concise human-readable problem statement (one sentence, no newlines).",
    node_id="fetch-data",                   # Optional — the affected node ID when known
    suggestions=[                           # Optional — list[str]. BARE STRING RAISES TypeError
        "Primary fix action",
        "Alternative fix action",
    ],
    context={
        # REQUIRED: category drives title fallback + future category-specific blocks
        "category": "validation",           # or "template_error" (no other value for validator)

        # STRONGLY RECOMMENDED: path as JSON-pointer location
        "path": "nodes[0].params.command",  # renders in "At:" line

        # FREE WINS (renderer already supports these):
        "node_type": "shell",               # renders "  Node type: shell"
        "sub_workflow_path": "./child.pflow.md",  # renders "  Sub-workflow: ./child.pflow.md"
        "similar_names": ["shell", "http"],       # renders "Did you mean one of these?" (YOU truncate to ~5)
        "available_fields": ["key1", "key2"],     # renders "Available fields..." block (after gate broadening)
        "available_fields_total": 12,              # used by the block header
        "available_fields_truncated": False,       # True appends "complete list in trace file" hint

        # TOOLING-ONLY (carried to JSON, not rendered in text):
        "template": "${variable}",          # for structured consumers
        # Any domain-specific key you want to preserve
    },
)
```

### Keys validator producers MUST NEVER set

| Key | Why |
|---|---|
| `phase` | Compilation-only. Renders "Phase: X" — misleading in validation context. |
| `exception_type` | Runtime wrapped-exception path. Renders "Type: X" — suggests unhandled exception. |
| `raw_response` | HTTP runtime only. |
| `mcp_error` | MCP runtime only. |
| `shell_command`, `shell_stdout`, `shell_stderr` | Shell runtime only. **Gotcha**: `shell_command` uses `in context` presence check — setting it to `None` still triggers the whole block. |
| `line` | Parser errors only. Validators don't know source lines. |

### Warnings vs errors — important gotcha

Warning and info severity diagnostics are rendered by `_format_warning_or_info_diagnostic` (diagnostic.py:117), which **only reads `message`, `node_id`, and `suggestions`**. The entire `context` block is ignored for warnings. This means:

- A warning with `context={"path": "nodes[0].type"}` will NOT render the path.
- A warning with `context={"available_fields": [...]}` will NOT render the fields.

If you want rich warning output, you must embed it in `message` or `suggestions`. The existing `_warn_inputless_shell_nodes` (validator.py:742-794) is the reference pattern — it puts the full explanation in the message.

---

## Renderer context-key dictionary (authoritative reference)

| Key | Type | Read by (`diagnostic.py`) | Renders as | Gating |
|---|---|---|---|---|
| `category` | str | `_format_error_diagnostic:140`, `_format_all_context_blocks:207` | Drives title fallback via `_CATEGORY_TITLES` | — |
| `path` | str | `_format_location:187` | `At: ... , nodes[0].params.x` | Suppressed when `== "root"` |
| `line` | int | `_format_location:189` | `At: ... , line 42` | `is not None` (0 renders) |
| `phase` | str | `_format_compilation_context_lines:219` | `  Phase: <value>` | Any truthy string |
| `node_type` | str | `_format_compilation_context_lines:221` | `  Node type: <value>` | Any truthy string |
| `sub_workflow_path` | str | `_format_compilation_context_lines:223` | `  Sub-workflow: <path>` | Any truthy string |
| `similar_names` | list[str] | `_format_similar_names_block:228-236` | `Did you mean one of these?` list | Truthy list (renderer does NOT truncate — YOU must) |
| `exception_type` | str | `_format_exception_type_line:239-243` | `  Type: <name>` | Any truthy string |
| `available_fields` | list[str] | `_format_template_error_lines:246-265` (rename to `_format_available_fields_block`) | `Available fields in node (showing N of M):` block | **Currently** `category == "template_error"`; **AFTER THIS PR** unconditional |
| `available_fields_total` | int | Same | Block header count | Defaults to `len(available_fields)` |
| `available_fields_truncated` | bool | Same | Appends "complete list in trace file" hint | — |
| `raw_response` | dict | `_format_api_response_lines:268-287` | `API Response:` block (sanitized) | `isinstance(_, dict)` |
| `mcp_error` | dict | `_format_mcp_error_lines:290-304` | `MCP Tool Error:` block (sanitized) | `isinstance(_, dict)` |
| `shell_command`, `shell_stdout`, `shell_stderr` | str | `_format_shell_error_lines:307-319` | `Shell details:` block | `"shell_command" in context` (presence check) |
| `technical_details` | str | `_format_error_diagnostic:170-177` | Verbose mode shows full; non-verbose shows hint | Always (hint always printed) |

### `_CATEGORY_TITLES` (verbatim, diagnostic.py:322-335)

```python
_CATEGORY_TITLES: dict[str, str] = {
    "compilation":       "Compilation Failed",
    "max_visits":        "Infinite Loop Detected",
    "validation":        "Validation Error",
    "parse_error":       "Parse Error",
    "not_found":         "Workflow Not Found",
    "file_not_found":    "File Not Found",
    "permission_denied": "Permission Denied",
    "execution_failure": "Execution Failed",
    "api_validation":    "API Validation Error",
    "template_error":    "Template Error",
    "mcp":               "MCP Error",
    "cli":               "Error",
}
```

Validator producers use `"validation"` (generic) or `"template_error"` (template-class errors that want the fields block rendered). No other values.

---

## Per-producer conversion specification

This is the authoritative per-call-site spec. Representative examples are shown in full; simpler sites follow the same pattern (enumerated in the tables).

### Layer 1 — `src/pflow/core/workflow/data_flow.py` (6 producers)

**Return type changes**: `validate_data_flow(...) -> list[Diagnostic]`
**Helper signatures**: `_check_param_value` / `_validate_node_params` / `_validate_template_reference` / `_check_forward_reference` take/return `list[Diagnostic]` or `Optional[Diagnostic]`.

**Add to `CycleError`** (top of file):
```python
class CycleError(Exception):
    def __init__(self, nodes_in_cycle: set[str]) -> None:
        self.nodes_in_cycle = sorted(nodes_in_cycle)
        super().__init__(f"Circular dependency detected involving nodes: {', '.join(self.nodes_in_cycle)}")
```
Then update `build_execution_order` to raise `CycleError(remaining)` instead of `CycleError(f"... {', '.join(sorted(remaining))}")`.

#### DF1: `validate_data_flow` line ~254 (CycleError catch)

```python
# Before
except CycleError as e:
    errors.append(f"Data flow error: {e!s}")
    return errors

# After
except CycleError as e:
    diagnostics.append(Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        message=f"Circular dependency detected involving nodes: {', '.join(e.nodes_in_cycle)}",
        suggestions=["Remove or reorder edges to break the cycle."],
        context={
            "category": "validation",
            "cycle_nodes": e.nodes_in_cycle,  # tooling-only; not rendered
        },
    ))
    return diagnostics
```

#### DF2: `_check_forward_reference` line ~120-123

Refactor to return `Optional[Diagnostic]` and accept `param_name` as a new argument (so the diagnostic carries the full path):

```python
def _check_forward_reference(
    node_id: str,
    param_name: str,  # NEW
    ref_node_id: str,
    node_position: int,
    node_positions: dict[str, int],
    loop_forward_limits: dict[str, int],
) -> Optional[Diagnostic]:
    if ref_node_id not in node_positions:
        return None
    ref_position = node_positions[ref_node_id]
    if ref_position < node_position:
        return None
    max_allowed = loop_forward_limits.get(node_id)
    if max_allowed is not None and ref_position <= max_allowed:
        return None
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' references '{ref_node_id}' in parameter '{param_name}', "
            f"but '{ref_node_id}' comes after this node in execution order "
            f"(position {ref_position} >= {node_position})."
        ),
        suggestions=[f"Reorder nodes so '{ref_node_id}' appears before '{node_id}'."],
        context={
            "category": "validation",
            "path": f"nodes[id={node_id}].params.{param_name}",
            "referenced_node": ref_node_id,
        },
    )
```

Update `_validate_template_reference` caller to pass `param_name`.

#### DF3: `_validate_template_reference` line ~172 (non-existent node)

```python
# Before
return f"Node '{node_id}' references non-existent node '{ref_node_id}' in parameter '{param_name}'"

# After
from pflow.core.suggestion_utils import find_similar_items
candidates = sorted(set(nodes_by_id.keys()) | declared_inputs)
similar = find_similar_items(ref_node_id, candidates, max_results=3, method="fuzzy")

return Diagnostic(
    severity=Severity.ERROR,
    source="validator",
    title="Validation Error",
    node_id=node_id,
    message=f"Node '{node_id}' references non-existent node '{ref_node_id}' in parameter '{param_name}'.",
    suggestions=([f"Did you mean '{similar[0]}'?"] if similar else None),
    context={
        "category": "validation",
        "path": f"nodes[id={node_id}].params.{param_name}",
        "available_fields": sorted(nodes_by_id.keys()),  # renders after gate broadening
        "available_fields_total": len(nodes_by_id),
        "similar_names": similar or None,
    },
)
```

#### DF4: `_validate_template_reference` line ~182-185 (undefined input, case-insensitive match)

```python
# Before
if close_matches:
    return (
        f"Node '{node_id}' references undefined input '${{{ref}}}' "
        f"in parameter '{param_name}' - did you mean '${{{close_matches[0]}}}'?"
    )

# After
if close_matches:
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=f"Node '{node_id}' references undefined input '${{{ref}}}' in parameter '{param_name}'.",
        suggestions=[f"Did you mean '${{{close_matches[0]}}}'?"],
        context={
            "category": "validation",
            "path": f"nodes[id={node_id}].params.{param_name}",
            "template": f"${{{ref}}}",
            "similar_names": [f"${{{m}}}" for m in close_matches[:3]],
        },
    )
```

#### DF5: `_validate_template_reference` line ~187-190 (undefined input, no inputs declared)

```python
# Before
if not declared_inputs:
    return (
        f"Node '{node_id}' references '${{{ref}}}' in parameter '{param_name}' "
        f"but no inputs are declared in this workflow"
    )

# After
if not declared_inputs:
    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        node_id=node_id,
        message=(
            f"Node '{node_id}' references '${{{ref}}}' in parameter '{param_name}' "
            f"but no inputs are declared in this workflow."
        ),
        suggestions=[
            f"Declare '{ref}' under '## Inputs' or use a node output reference like ${{node_id.field}}.",
        ],
        context={
            "category": "validation",
            "path": f"nodes[id={node_id}].params.{param_name}",
            "template": f"${{{ref}}}",
        },
    )
```

#### DF6: `_validate_template_reference` line ~191-195 (undefined input with declared list)

```python
# After
sorted_inputs = sorted(declared_inputs)
return Diagnostic(
    severity=Severity.ERROR,
    source="validator",
    title="Validation Error",
    node_id=node_id,
    message=f"Node '{node_id}' references undefined input '${{{ref}}}' in parameter '{param_name}'.",
    context={
        "category": "validation",
        "path": f"nodes[id={node_id}].params.{param_name}",
        "template": f"${{{ref}}}",
        "available_fields": sorted_inputs,          # renders after gate broadening
        "available_fields_total": len(sorted_inputs),
    },
)
```

#### Compiler consumer update — `compile_validation.py:115-125`

**REVIEW CORRECTION**: The plan originally described this as "one-line change `e` → `d.message`". That was wrong — the `if data_flow_diagnostics:` truthiness check needs an explicit error filter. Without it, any future warning-severity producer in `data_flow.py` would silently start raising `CompilationError`.

```python
# Before
data_flow_errors = validate_data_flow(ir_dict, check_inputs=False)
if data_flow_errors:
    lines = [f"  - {e}" for e in data_flow_errors[:5]]
    if len(data_flow_errors) > 5:
        lines.append(f"  ... and {len(data_flow_errors) - 5} more errors")
    error_msg = "Data flow validation failed:\n" + "\n".join(lines)
    raise CompilationError(
        message=error_msg,
        phase="data_flow_validation",
    )

# After (CORRECTED — explicit filter, not just .message)
from pflow.core.diagnostic import Severity

data_flow_diagnostics = validate_data_flow(ir_dict, check_inputs=False)
errors = [d for d in data_flow_diagnostics if d.severity == Severity.ERROR]
if errors:
    lines = [f"  - {d.message}" for d in errors[:5]]
    if len(errors) > 5:
        lines.append(f"  ... and {len(errors) - 5} more errors")
    error_msg = "Data flow validation failed:\n" + "\n".join(lines)
    raise CompilationError(
        message=error_msg,
        phase="data_flow_validation",
    )
```

The filter is defensive — currently `validate_data_flow()` only produces errors, but locking in the filter prevents future regression when warning-severity producers are added. Same defensive filter pattern applies anywhere downstream consumers do truthiness checks on validator return values (already correct in `runner.py:_validate()` and `save_service.py` per the plan).

---

### Layer 2 — `src/pflow/runtime/template_validation/`

#### File 2a — `path_validation.py` (15 producers, highest-value file)

**Key architectural change**: Every helper that currently returns `str` becomes a helper that returns `Diagnostic`. Rename to `_build_*_diagnostic`. The dispatcher `create_template_error()` becomes `create_template_diagnostic()` returning `Diagnostic`. `_append_source_file_hint()` becomes `_attach_source_file_hint()` — a post-processor that takes and returns `Diagnostic`.

**Also add renderer block for `source_file`** in `diagnostic.py`:

```python
# In _format_all_context_blocks (after _format_compilation_context_lines or similar)
if source_file := context.get("source_file"):
    lines.append(f"  Loaded from file: {source_file}")
```

Alternatively, inline `source_file` into `_format_compilation_context_lines` since it's semantically similar. **Recommend**: new dedicated 3-line block for readability.

**Conversion table** (all 15 producers):

| ID | Function (current line) | Pattern | Rename to |
|---|---|---|---|
| PV1 | `_create_node_reference_error` (~479) — missing output key | "Just node ID, needs .key" | keep, return Diagnostic |
| PV2 | `_create_node_reference_error` (~488) — node not found fallback | Defensive fallback | keep, return Diagnostic |
| PV3 | `format_enhanced_node_error` (~562) — **HIGHEST VALUE** | 4-section error | `_build_enhanced_node_diagnostic` |
| PV4 | `_create_batch_error` (~741) — field doesn't exist | Delegates to PV3 | keep wrapper, delegate to `_build_enhanced_node_diagnostic` |
| PV5 | `_format_batch_inner_field_error` (~750) — inner field exists | Multi-line batch explainer | `_build_batch_inner_field_diagnostic` |
| PV6 | `_get_node_outputs_description` (~688) — no outputs | Simple fallback | return Diagnostic |
| PV7 | `_get_node_outputs_from_registry` (~704) — defensive | Simple fallback | return Diagnostic |
| PV8 | `_create_path_template_error` (~506) — initial_params runtime-dependent | Possibly dead code | return Diagnostic (defensive) |
| PV9 | `_create_path_template_error` (~512) — required input + path | Input description context | return Diagnostic |
| PV10 | `_create_path_template_error` (~519) — no source (namespacing on) | With fuzzy match | return Diagnostic |
| PV11 | `_create_path_template_error` (~524) — no source (namespacing off) | No fuzzy match | return Diagnostic |
| PV12 | `_create_simple_template_error` (~544) — required input | Input description context | return Diagnostic |
| PV13 | `_create_simple_template_error` (~551) — node ID misuse | Simple | return Diagnostic |
| PV14 | `_create_simple_template_error` (~556) — generic no source | Simple | return Diagnostic |
| PV15 | `_append_source_file_hint` (~414) — provenance | **POST-PROCESSOR** | `_attach_source_file_hint` (takes/returns Diagnostic) |

**PV3 full conversion** (highest-value case, `format_enhanced_node_error` at line ~562):

```python
# New signature and body
def _build_enhanced_node_diagnostic(
    node_id: str,
    node_type: str,
    attempted_key: str,
    available_paths: list[tuple[str, str]],
    base_var: str,
) -> Diagnostic:
    safe_node_id = sanitize_for_display(node_id)
    safe_node_type = sanitize_for_display(node_type)
    safe_attempted_key = sanitize_for_display(attempted_key)
    safe_base_var = sanitize_for_display(base_var)

    # Build available_fields list in full ${node.path} (type) form
    available_fields_display: list[str] = []
    for path, type_str in available_paths[:MAX_DISPLAYED_FIELDS]:
        safe_path = sanitize_for_display(path)
        safe_type = sanitize_for_display(type_str)
        full_path = f"{safe_base_var}.{safe_path}" if safe_base_var not in safe_path else safe_path
        available_fields_display.append(f"${{{full_path}}} ({safe_type})")

    # Build suggestions: first entry is the "Change X to Y" fix, then alternatives
    similar = find_similar_paths(attempted_key, available_paths)
    suggestions: list[str] = []
    if similar:
        fix_path, _ = similar[0]
        full_fix = f"{base_var}.{fix_path}" if base_var not in fix_path else fix_path
        suggestions.append(f"Change ${{{base_var}.{attempted_key}}} to ${{{full_fix}}}")
        for sugg_path, _ in similar[1:]:
            safe_sugg_path = sanitize_for_display(sugg_path)
            full_sugg = f"{safe_base_var}.{safe_sugg_path}" if safe_base_var not in safe_sugg_path else safe_sugg_path
            suggestions.append(f"Or use ${{{full_sugg}}}")
    elif available_paths:
        first_path, _ = available_paths[0]
        full_first = f"{base_var}.{first_path}" if base_var not in first_path else first_path
        suggestions.append(f"Try ${{{full_first}}}")

    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Template Error",
        node_id=node_id,
        message=f"Node '{safe_node_id}' (type: {safe_node_type}) does not output '{safe_attempted_key}'.",
        suggestions=suggestions or None,
        context={
            "category": "template_error",
            "node_type": node_type,
            "available_fields": available_fields_display,
            "available_fields_total": len(available_paths),
            "available_fields_truncated": len(available_paths) > MAX_DISPLAYED_FIELDS,
            "similar_names": [
                f"${{{safe_base_var}.{p}}}" if safe_base_var not in p else f"${{{p}}}"
                for p, _ in similar
            ] or None,
        },
    )
```

**PV15 (`_attach_source_file_hint`)** — convert from string-appender to Diagnostic post-processor:

```python
# New signature
def _attach_source_file_hint(
    diagnostic: Diagnostic,
    template: str,
    workflow_ir: dict[str, Any],
) -> Diagnostic:
    """Add source file provenance to a diagnostic's context if the template came from an external file."""
    source_file = _find_template_source_file(template, workflow_ir)
    if not source_file:
        return diagnostic
    from dataclasses import replace
    new_context = {**(diagnostic.context or {}), "source_file": source_file}
    return replace(diagnostic, context=new_context)
```

**Dispatcher update** (`create_template_error` at line ~315, rename to `create_template_diagnostic`):

```python
def create_template_diagnostic(
    template: str,
    available_params: dict[str, Any],
    workflow_ir: dict[str, Any],
    node_outputs: dict[str, Any],
    registry: Registry,
) -> Diagnostic:
    """Create appropriate diagnostic for missing template variable."""
    parts = split_template_path(template)
    base_var = parts[0]
    enable_namespacing = workflow_ir.get("enable_namespacing", True)

    if enable_namespacing and "." in template:
        node_ids = get_node_ids(workflow_ir)
        if base_var in node_ids:
            diag = _create_node_reference_diagnostic(base_var, parts, template, workflow_ir, node_outputs, registry)
            return _attach_source_file_hint(diag, template, workflow_ir)

    if "." in template:
        diag = _create_path_template_diagnostic(template, base_var, available_params, workflow_ir)
        return _attach_source_file_hint(diag, template, workflow_ir)

    diag = _create_simple_template_diagnostic(template, workflow_ir)
    return _attach_source_file_hint(diag, template, workflow_ir)
```

**Top-level `validate_template_paths` update**:

```python
# New signature
def validate_template_paths(
    all_templates: set[str],
    available_params: dict[str, Any],
    node_outputs: dict[str, Any],
    workflow_ir: dict[str, Any],
    registry: Registry,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []

    for template in sorted(all_templates):
        is_valid, warning = validate_template_path(template, available_params, node_outputs, workflow_ir, registry)

        if warning:
            diagnostics.append(warning)  # warnings are already Diagnostic objects

        if not is_valid:
            diagnostics.append(
                create_template_diagnostic(template, available_params, workflow_ir, node_outputs, registry)
            )

    return diagnostics
```

For the other PV producers (PV1, PV2, PV6-14): apply the producer pattern from Section 4, using their existing message content as the `message=` field and promoting any fuzzy-match / available-list data to context. Full examples for each are straightforward mechanical applications of the pattern — no surprises.

#### File 2b — `type_validation.py` (3 producers)

**TY1: `_check_string_template_types` line ~148-156 (type mismatch)**

Refactor `_generate_type_fix_suggestion` (line 303) from returning a pre-formatted string to returning structured data:

```python
# NEW helper signature
def _generate_type_fix_suggestions(
    template: str,
    node_outputs: dict[str, Any],
    expected_type: str,
) -> tuple[list[str], list[str]]:
    """Returns (suggestions, available_fields)."""
    # ... existing logic to find matching_fields ...
    if matching_fields:
        return (
            [f"Use ${{{template}.{f}}}" for f in matching_fields[:5]],
            [f"${{{template}.{f}}}" for f in matching_fields],
        )
    return (["Access a nested field or serialize to JSON."], [])
```

Then at the call site:

```python
# Before
error_msg = (
    f"Type mismatch in node '{node_id}' parameter '{param_name}': "
    f"template ${{{template}}} has type '{inferred_type}' "
    f"but parameter expects '{expected_type}'"
)
if inferred_type in ["dict", "list", "object"] and expected_type in ["str", "string"]:
    error_msg += _generate_type_fix_suggestion(template, node_outputs, expected_type)
errors.append(error_msg)

# After
suggestions: list[str] | None = None
available_fields: list[str] = []
if inferred_type in ["dict", "list", "object"] and expected_type in ["str", "string"]:
    suggestions, available_fields = _generate_type_fix_suggestions(template, node_outputs, expected_type)

diagnostics.append(Diagnostic(
    severity=Severity.ERROR,
    source="validator",
    title="Validation Error",
    node_id=node_id,
    message=(
        f"Type mismatch in parameter '{param_name}': template ${{{template}}} has "
        f"type '{inferred_type}' but parameter expects '{expected_type}'."
    ),
    suggestions=suggestions,
    context={
        "category": "validation",
        "path": f"nodes[id={node_id}].params.{param_name}",
        "template": f"${{{template}}}",
        "inferred_type": inferred_type,
        "expected_type": expected_type,
        "available_fields": available_fields or None,
        "available_fields_total": len(available_fields) if available_fields else None,
    },
))
```

**TY2: `validate_shell_command_types` line ~249-264 (single blocked template)**

```python
# After — 3 fix options become suggestions list
diagnostics.append(Diagnostic(
    severity=Severity.ERROR,
    source="validator",
    title="Validation Error",
    node_id=node_id,
    message=(
        f"Shell node '{node_id}': cannot use ${{{template}}} (type: {blocked_type}) "
        f"in command parameter — embedded {blocked_type} breaks shell parsing."
    ),
    suggestions=[
        f"Access a specific field: ${{{template}.fieldname}}",
        f'Use stdin for the whole object: stdin: "${{{template}}}", command: "jq \'.field\'"',
        f"Quote to accept JSON coercion: '${{{template}}}'",
    ],
    context={
        "category": "validation",
        "path": f"nodes[id={node_id}].params.command",
        "template": f"${{{template}}}",
        "blocked_type": blocked_type,
        "shell_command": command,  # renders via _format_shell_error_lines — free win
    },
))
```

**Gotcha**: setting `shell_command` triggers the whole shell block renderer. That's the desired behavior here — it shows `Shell details: Command: <truncated command>` automatically. This is a free win.

**TY3: `validate_shell_command_types` line ~267-293 (multiple blocked templates)**

```python
# After
template_list = ", ".join(f"${{{t}}} ({typ})" for t, typ in blocked_templates)
diagnostics.append(Diagnostic(
    severity=Severity.ERROR,
    source="validator",
    title="Validation Error",
    node_id=node_id,
    message=(
        f"Shell node '{node_id}': multiple structured data templates in command: {template_list}. "
        f"Shell commands can only receive ONE data source via stdin."
    ),
    suggestions=[
        "Use temp files: write each data source via write-file nodes, then read in shell.",
        "Process each data source in separate shell nodes, then combine results.",
        "Pass one via stdin and reference another via file.",
        "Quote templates to accept JSON coercion: '${var}'",
    ],
    context={
        "category": "validation",
        "path": f"nodes[id={node_id}].params.command",
        "shell_command": command,
        "blocked_templates": [
            {"template": f"${{{t}}}", "type": typ} for t, typ in blocked_templates
        ],
    },
))
```

**Note on lost fidelity**: The original had a multi-line YAML example for "Use temp files" with `### save-a / ### save-b / ### process`. This embedded example is dropped in the conversion — it doesn't fit the structured suggestion model. Acceptable tradeoff; users get the same information via shorter text.

#### File 2c — `batch_item_validation.py` (2 producers)

**BV1: `_format_batch_item_field_error` line ~170-212**

Rename to `_build_batch_item_field_diagnostic`, return `Diagnostic`:

```python
def _build_batch_item_field_diagnostic(
    node_id: str,
    item_alias: str,
    items_template: Any,
    first_field: str,
    full_template: str,
    item_structure: dict[str, Any],
) -> Diagnostic:
    safe_node_id = sanitize_for_display(node_id)
    safe_alias = sanitize_for_display(item_alias)
    items_source = items_template if isinstance(items_template, str) else str(items_template)
    safe_source = sanitize_for_display(items_source)

    available_fields: list[str] = []
    for field_name, field_info in item_structure.items():
        field_type = field_info.get("type", "any") if isinstance(field_info, dict) else "any"
        available_fields.append(f"${{{safe_alias}.{field_name}}} ({field_type})")

    available_paths = [
        (f"{safe_alias}.{f}", info.get("type", "any") if isinstance(info, dict) else "any")
        for f, info in item_structure.items()
    ]
    similar = find_similar_paths(first_field, available_paths)

    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Template Error",
        node_id=node_id,
        message=(
            f"Node '{safe_node_id}': ${{{full_template}}} references field '{first_field}' "
            f"which is not available on batch items (items come from: {safe_source})."
        ),
        suggestions=([f"Use ${{{p}}}" for p, _ in similar] if similar else None),
        context={
            "category": "template_error",
            "template": f"${{{full_template}}}",
            "available_fields": available_fields,
            "available_fields_total": len(available_fields),
            "similar_names": [f"${{{p}}}" for p, _ in similar] or None,
            "items_source": safe_source,
            "batch_alias": safe_alias,
        },
    )
```

**BV2: `_format_batch_item_nested_error` line ~215-280**

Rename to `_build_batch_item_nested_diagnostic`, keep the depth-walking logic verbatim, produce Diagnostic:

```python
def _build_batch_item_nested_diagnostic(
    node_id: str,
    item_alias: str,
    parts: list[str],
    full_template: str,
    field_info: dict[str, Any],
) -> Diagnostic:
    safe_node_id = sanitize_for_display(node_id)
    safe_alias = sanitize_for_display(item_alias)

    # Keep existing depth-walking logic verbatim — it computes:
    # parent_path, bad_field, parent_name, parent_type, nested_structure
    current_info = field_info
    valid_depth = 0
    for part in parts[1:-1]:
        sub = current_info.get("structure", {}) if isinstance(current_info, dict) else {}
        if part in sub and isinstance(sub[part], dict):
            current_info = sub[part]
            valid_depth += 1
        else:
            break

    parent_path = f"{safe_alias}.{'.'.join(parts[: 1 + valid_depth])}"
    bad_field = parts[1 + valid_depth].split("[")[0]
    parent_name = parts[valid_depth]
    parent_type = current_info.get("type", "any") if isinstance(current_info, dict) else "any"
    nested_structure = current_info.get("structure", {}) if isinstance(current_info, dict) else {}

    available_fields: list[str] = []
    similar: list[tuple[str, str]] = []
    if nested_structure:
        for field_name, sub_info in nested_structure.items():
            sub_type = sub_info.get("type", "any") if isinstance(sub_info, dict) else "any"
            available_fields.append(f"${{{parent_path}.{field_name}}} ({sub_type})")
        available_paths = [
            (f"{parent_path}.{f}", i.get("type", "any") if isinstance(i, dict) else "any")
            for f, i in nested_structure.items()
        ]
        similar = find_similar_paths(bad_field, available_paths)

    suggestions: list[str] | None
    if similar:
        suggestions = [f"Use ${{{p}}}" for p, _ in similar]
    elif not nested_structure:
        suggestions = [f"'{parent_name}' has no known sub-fields. Nested access may fail at runtime."]
    else:
        suggestions = None

    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Template Error",
        node_id=node_id,
        message=(
            f"Node '{safe_node_id}': ${{{full_template}}} — "
            f"'{bad_field}' does not exist on '{parent_name}' ({parent_type})."
        ),
        suggestions=suggestions,
        context={
            "category": "template_error",
            "template": f"${{{full_template}}}",
            "available_fields": available_fields or None,
            "available_fields_total": len(available_fields) if available_fields else None,
            "similar_names": [f"${{{p}}}" for p, _ in similar] or None,
            "parent_path": parent_path,
            "parent_type": parent_type,
        },
    )
```

Update `validate_batch_item_fields` return type to `list[Diagnostic]` and calls to return these builder functions.

#### File 2d — `template_validation/validator.py` (orchestrator + 2 helpers)

**Main entry point signature change**:

```python
# Before
def validate_workflow_templates(
    workflow_ir: dict[str, Any],
    available_params: dict[str, Any],
    registry: Registry,
) -> tuple[list[str], list[Diagnostic]]: ...

# After
def validate_workflow_templates(
    workflow_ir: dict[str, Any],
    available_params: dict[str, Any],
    registry: Registry,
) -> list[Diagnostic]: ...
```

Implementation: accumulate `diagnostics: list[Diagnostic] = []` instead of separate `errors: list[str]` and `warnings: list[Diagnostic]`. All sub-pass calls return `list[Diagnostic]` which extend the accumulator. The malformed-templates early return uses `list[Diagnostic]` too.

**TV1: `_validate_unused_inputs` line ~196**

```python
# After
sorted_unused = sorted(unused_inputs)
diagnostics.append(Diagnostic(
    severity=Severity.ERROR,
    source="validator",
    title="Validation Error",
    message=f"Declared input(s) never used as template variable: {', '.join(sorted_unused)}",
    suggestions=[
        "Remove unused declarations from '## Inputs' or reference them in a node parameter.",
    ],
    context={
        "category": "validation",
        "path": "inputs",
        "unused_inputs": sorted_unused,
    },
))
```

**TV2: `_validate_malformed_templates` line ~240-245**

```python
# After
diagnostics.append(Diagnostic(
    severity=Severity.ERROR,
    source="validator",
    title="Template Error",
    node_id=node_id,
    message=(
        f"Malformed template syntax: found {dollar_brace_count} '${{' "
        f"but only {len(valid_matches)} valid template(s)."
    ),
    suggestions=["Check for missing '}' or empty templates like '${}'."],
    context={
        "category": "template_error",
        "path": f"nodes[id={node_id}].params.{param_path}" if param_path else f"nodes[id={node_id}].params",
        "template": value if isinstance(value, str) else None,
    },
))
```

---

### Layer 3 — `src/pflow/core/workflow/validator.py` (9 helpers + orchestrator)

**Orchestrator signature change**:

```python
@staticmethod
def validate(
    workflow_ir: dict[str, Any],
    extracted_params: Optional[dict[str, Any]] = None,
    registry: Optional[Registry] = None,
    skip_node_types: bool = False,
    workflow_file: Optional[Path] = None,
    _seen: Optional[set[str]] = None,
    _ir_cache: Optional[dict[str, tuple[dict[str, Any], Optional[Path]]]] = None,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    diagnostics.extend(WorkflowValidator._validate_structure(workflow_ir))
    diagnostics.extend(WorkflowValidator._validate_stdin_inputs(workflow_ir))
    diagnostics.extend(WorkflowValidator._validate_data_flow(workflow_ir))

    if extracted_params is not None:
        if registry is None:
            registry = Registry()
        diagnostics.extend(WorkflowValidator._validate_templates(workflow_ir, extracted_params, registry))

    if not skip_node_types:
        if registry is None:
            registry = Registry()
        diagnostics.extend(WorkflowValidator._validate_node_types(workflow_ir, registry))

    diagnostics.extend(WorkflowValidator._validate_output_sources(workflow_ir, registry))

    if registry is not None:
        diagnostics.extend(WorkflowValidator._validate_unknown_params(workflow_ir, registry))

    diagnostics.extend(WorkflowValidator._validate_sub_workflows(
        workflow_ir, extracted_params, registry, _seen, _ir_cache, skip_node_types, workflow_file
    ))

    diagnostics.extend(WorkflowValidator._warn_inputless_shell_nodes(workflow_ir))

    if any(d.severity == Severity.ERROR for d in diagnostics):
        logger.debug(f"Validation found {sum(1 for d in diagnostics if d.severity == Severity.ERROR)} errors")
    elif any(d.severity == Severity.WARNING for d in diagnostics):
        logger.debug(f"Validation passed with {sum(1 for d in diagnostics if d.severity == Severity.WARNING)} warnings")
    else:
        logger.debug("Validation passed")

    return diagnostics
```

**Helper conversion table** (9 helpers):

| ID | Helper | Current line | Pattern |
|---|---|---|---|
| V1 | `_validate_structure` (SchemaValidationError catch) | ~163 | **`return list(e.to_diagnostics())`** — SchemaValidationError already self-describes |
| V2 | `_validate_structure` (generic Exception) | ~165 | Simple wrap with `exception_type` |
| V3 | `_validate_stdin_inputs` (multiple stdin) | ~184 | Message + suggestion + path="inputs" |
| V4 | `_validate_data_flow` (generic Exception wrapper) | ~206 | Defensive wrap (becomes dead code) |
| V5 | `_validate_templates` (generic Exception wrapper) | ~230 | Defensive wrap |
| V6 | `_validate_node_types` (unknown node type) | ~262 | node_id + similar_names + node_type + path |
| V7 | `_validate_node_types` (registry Exception) | ~264 | Simple wrap |
| V8 | `_validate_output_sources` (empty source) | ~316 | Simple + path=`outputs.X.source` |
| V9 | `_format_node_not_found_error` (helper, ~397) | — | Rename, return Diagnostic with similar_names + available_fields — **see full conversion below** |
| V10 | `_validate_template_in_source` (malformed) | ~368 | Simple + `category="template_error"` |
| V11 | `_format_template_node_error` (helper, ~421) | — | Rename, return Diagnostic with available_fields + similar_names — **see full conversion below** |
| V12 | `_validate_unknown_params` | ~543-549 | **MAJOR**: node_id + similar_names + available_fields |
| V13 | `_validate_sub_workflows` (file_resolver catch) | ~621 | + `sub_workflow_path` context |
| V14 | `_check_required_inputs` | ~667-672 | + `sub_workflow_path` + `available_fields` for child inputs |
| V15 | `_load_child_workflow` (load exception) | ~706-710 | 4th tuple element becomes `list[Diagnostic]` |
| V16 | `_validate_sub_workflows` (child error wrapping) | ~644-645 | **USE `format_child_provenance()` + `_add_child_provenance` helper** |
| V17 | `_warn_inputless_shell_nodes` | ~742 | **REFERENCE PATTERN** — already produces Diagnostic |

**V1 — SchemaValidationError free win**:

```python
# Before
try:
    validate_ir(workflow_ir)
    return []
except SchemaValidationError as e:
    return [f"Structure: {e}"]
except Exception as e:
    return [f"Structure: Unexpected error during validation: {e}"]

# After
try:
    validate_ir(workflow_ir)
    return []
except SchemaValidationError as e:
    return list(e.to_diagnostics())  # Exception already self-describes
except Exception as e:
    return [Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        message=f"Unexpected error during structural validation: {e}",
        context={"category": "validation", "exception_type": type(e).__name__},
    )]
```

**V6 — Unknown node type** (needs loop restructure to have access to node index):

```python
# After
type_diagnostics: list[Diagnostic] = []
try:
    compiler_special_types = {"workflow", "pflow.runtime.workflow_executor"}
    node_types = {node.get("type") for node in workflow_ir.get("nodes", []) if node.get("type")}
    registry_types = node_types - compiler_special_types

    if registry_types:
        metadata = registry.get_nodes_metadata(registry_types)
        unknown_types = registry_types - set(metadata.keys())

        # Build similar-name suggestions from the queried metadata (best-effort)
        known_types = sorted(metadata.keys())

        # Emit one diagnostic per node instance with an unknown type (not per type string)
        for i, node in enumerate(workflow_ir.get("nodes", [])):
            node_type = node.get("type")
            if node_type in unknown_types:
                from pflow.core.suggestion_utils import find_similar_items
                similar = find_similar_items(node_type, known_types, max_results=3, method="fuzzy") if known_types else []
                type_diagnostics.append(Diagnostic(
                    severity=Severity.ERROR,
                    source="validator",
                    title="Validation Error",
                    node_id=node.get("id", "unknown"),
                    message=f"Unknown node type: '{node_type}'",
                    suggestions=([f"Did you mean '{similar[0]}'?"] if similar else None),
                    context={
                        "category": "validation",
                        "path": f"nodes[{i}].type",
                        "node_type": node_type,
                        "similar_names": similar or None,
                    },
                ))
except Exception as e:
    type_diagnostics.append(Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        message=f"Registry validation error: {e}",
        context={"category": "validation", "exception_type": type(e).__name__},
    ))
return type_diagnostics
```

**V9 — `_format_node_not_found_error` → `_build_node_not_found_diagnostic`** (full conversion, helper at validator.py:~397):

```python
# Before — returns string with 4 sections
@staticmethod
def _format_node_not_found_error(output_name: str, node_id: str, nodes_map: dict[str, Any]) -> str:
    available = sorted(nodes_map.keys())
    lines = [f"Output '{output_name}' references non-existent node '{node_id}'."]
    if available:
        lines.append(f"\nAvailable nodes: {', '.join(available)}")
        from pflow.core.suggestion_utils import find_similar_items
        similar = find_similar_items(node_id, available, max_results=3, method="fuzzy")
        if similar:
            lines.append("\nDid you mean?")
            for suggestion in similar:
                lines.append(f"  - {suggestion}")
    else:
        lines.append("\nWorkflow has no nodes.")
    return "\n".join(lines)
```

```python
# After — returns Diagnostic with structured fields
@staticmethod
def _build_node_not_found_diagnostic(
    output_name: str,
    missing_node_id: str,
    nodes_map: dict[str, Any],
) -> Diagnostic:
    from pflow.core.suggestion_utils import find_similar_items
    available = sorted(nodes_map.keys())
    similar = find_similar_items(missing_node_id, available, max_results=3, method="fuzzy") if available else []

    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Validation Error",
        message=f"Output '{output_name}' references non-existent node '{missing_node_id}'.",
        suggestions=([f"Did you mean '{similar[0]}'?"] if similar else None),
        context={
            "category": "validation",
            "path": f"outputs.{output_name}.source",
            "available_fields": available,
            "available_fields_total": len(available),
            "similar_names": similar or None,
        },
    )
```

Update the call site at validator.py:336 (`error_msg = WorkflowValidator._format_node_not_found_error(...)`) to call the renamed builder and append the Diagnostic directly. Note: the message preserves the substring `"non-existent node 'X'"` so `pytest.raises(WorkflowValidationError, match="nonexistent_node")` in test_workflow_save_service.py:334 keeps passing.

**V11 — `_format_template_node_error` → `_build_template_node_diagnostic`** (full conversion, helper at validator.py:~421):

```python
# Before — returns multi-section string with Problem / Available / Did you mean / Concrete fix
@staticmethod
def _format_template_node_error(
    output_name: str,
    source: str,
    node_id: str,
    output_key: str | None,
    nodes_map: dict[str, Any],
) -> str:
    # ... 4-section string building ...
```

```python
# After — returns Diagnostic with all sections promoted to fields/context
@staticmethod
def _build_template_node_diagnostic(
    output_name: str,
    source: str,
    missing_node_id: str,
    output_key: str | None,
    nodes_map: dict[str, Any],
) -> Diagnostic:
    from pflow.core.suggestion_utils import find_similar_items
    available = sorted(nodes_map.keys())
    similar = find_similar_items(missing_node_id, available, max_results=3, method="fuzzy") if available else []

    suggestions: list[str] = []
    if similar:
        # First item: concrete fix
        best = similar[0]
        corrected = f"${{{best}.{output_key}}}" if output_key else f"${{{best}}}"
        suggestions.append(f'Change "{source}" to "{corrected}"')
        # Additional items: alternative corrections
        for s in similar[1:]:
            alt = f"${{{s}.{output_key}}}" if output_key else f"${{{s}}}"
            suggestions.append(f"Or use {alt}")

    return Diagnostic(
        severity=Severity.ERROR,
        source="validator",
        title="Template Error",
        message=f"Output '{output_name}' source references non-existent node '{missing_node_id}'.",
        suggestions=suggestions or None,
        context={
            "category": "template_error",
            "path": f"outputs.{output_name}.source",
            "template": source,
            "available_fields": available,
            "available_fields_total": len(available),
            "similar_names": similar or None,
        },
    )
```

Update the call site at validator.py:389 (`error_msg = WorkflowValidator._format_template_node_error(...)`) to call the renamed builder and append directly.

**V12 — Unknown parameter** (highest-value conversion in this file):

```python
# After — inside the existing nested loops, at the `if param_key not in known_keys` site:
from pflow.core.suggestion_utils import find_similar_items
sorted_known = sorted(known_keys)
similar = find_similar_items(param_key, sorted_known, max_results=2, method="fuzzy")
suggestions: list[str] = []
if similar:
    suggestions.append(f"Did you mean '{similar[0]}'?")

diagnostics.append(Diagnostic(
    severity=Severity.ERROR,
    source="validator",
    title="Validation Error",
    node_id=node_id,
    message=f"Unknown parameter '{param_key}' on node '{node_id}' (type: {node_type}).",
    suggestions=suggestions or None,
    context={
        "category": "validation",
        "path": f"nodes[id={node_id}].params.{param_key}",
        "node_type": node_type,
        "available_fields": sorted_known,        # renders after gate broadening
        "available_fields_total": len(sorted_known),
        "similar_names": similar or None,
    },
))
```

This is the error type that motivated #219 — an agent typing `promt: "..."` currently gets "unknown parameter, did you mean 'prompt'? Valid parameters: prompt, model..." as one flat string. After this change, the title, path, suggestion, and full valid list render through the unified format.

**V16 — Sub-workflow error provenance** (use `format_child_provenance`, matching the warnings path):

```python
# Before (line ~644-645)
for err in child_errors:
    errors.append(f"In sub-workflow '{ref_label}' (step '{node_id}'): {err}")

# After
from dataclasses import replace
from pflow.core.diagnostic import format_child_provenance

for child_diag in child_diagnostics:
    # Symmetry with _add_child_provenance helper at validator.py:19-33 (warnings path)
    diagnostics.append(replace(
        child_diag,
        message=format_child_provenance(node_id, child_diag.message),
        node_id=child_diag.node_id or node_id,
        context={
            **(child_diag.context or {}),
            "sub_workflow_path": ref_label,
            "sub_workflow_step": node_id,  # NEW — parent context for tooling
        },
    ))
```

**Then unify `_add_child_provenance` helper** (currently only for warnings at lines 19-33) to work on both errors and warnings:

```python
# Before
def _add_child_provenance(warnings: list[Diagnostic] | tuple[Diagnostic, ...], step_id: str) -> list[Diagnostic]:
    from dataclasses import replace
    return [
        replace(w, message=format_child_provenance(step_id, w.message), node_id=w.node_id or step_id)
        for w in warnings
    ]

# After — same signature but rename to reflect generality
def _add_child_provenance(
    child_diagnostics: list[Diagnostic] | tuple[Diagnostic, ...],
    step_id: str,
    ref_label: str | None = None,
) -> list[Diagnostic]:
    """Add sub-workflow provenance to child diagnostics (errors AND warnings)."""
    from dataclasses import replace
    result: list[Diagnostic] = []
    for d in child_diagnostics:
        new_context = {**(d.context or {}), "sub_workflow_step": step_id}
        if ref_label:
            new_context["sub_workflow_path"] = ref_label
        result.append(replace(
            d,
            message=format_child_provenance(step_id, d.message),
            node_id=d.node_id or step_id,
            context=new_context,
        ))
    return result
```

**Call sites** in `_validate_sub_workflows` use this helper for both child errors and child warnings:

```python
# Instead of the current parallel paths (string prefix for errors, helper for warnings):
diagnostics.extend(_add_child_provenance(child_parser_warnings, node_id, ref_label))
# ... later ...
child_diagnostics = WorkflowValidator.validate(...)  # returns list[Diagnostic]
diagnostics.extend(_add_child_provenance(child_diagnostics, node_id, ref_label))
```

Full symmetry with the warnings path. Dedup works naturally because `Diagnostic.__hash__` includes the prefixed message.

---

## Exception changes — `src/pflow/core/exceptions.py`

### WorkflowValidationError

```python
# Before (lines 70-120)
class WorkflowValidationError(PflowError):
    """Raised when workflow validation fails."""

    def __init__(
        self,
        summary: str = "Workflow validation failed",
        validation_errors: list[str | tuple[str, str, str]] | None = None,
    ):
        self.summary = summary
        self.validation_errors = validation_errors or []
        super().__init__(summary)

    def to_diagnostics(self) -> list[Diagnostic]:
        diagnostics: list[Diagnostic] = []
        for error in self.validation_errors:
            if isinstance(error, tuple):
                message = error[0] if len(error) >= 1 else str(self)
                path = error[1] if len(error) >= 2 else ""
                suggestion_str = error[2] or None if len(error) >= 3 else None
                ctx: dict[str, Any] = {"category": "validation"}
                if path:
                    ctx["path"] = path
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        message=message,
                        title="Validation Error",
                        suggestions=[suggestion_str] if suggestion_str else None,
                        source="validation",
                        context=ctx,
                    )
                )
            else:
                diagnostics.append(
                    Diagnostic(
                        severity=Severity.ERROR,
                        message=str(error),
                        title="Validation Error",
                        source="validation",
                        context={"category": "validation"},
                    )
                )
        return diagnostics or [
            Diagnostic(
                severity=Severity.ERROR,
                message=str(self),
                title="Validation Error",
                source="validation",
                context={"category": "validation"},
            )
        ]
```

```python
# After — simplified to list[Diagnostic] pass-through
class WorkflowValidationError(PflowError):
    """Raised when workflow validation fails."""

    def __init__(
        self,
        summary: str = "Workflow validation failed",
        validation_errors: list[Diagnostic] | None = None,
    ):
        self.summary = summary
        self.validation_errors = validation_errors or []
        super().__init__(summary)

    def to_diagnostics(self) -> list[Diagnostic]:
        return self.validation_errors or [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.summary,
                title="Validation Error",
                source="validation",
                context={"category": "validation"},
            )
        ]
```

**30 lines deleted**. The tuple/str branching dead code is gone. The empty-list fallback remains so single-string-summary construction sites (`WorkflowValidationError("Workflow name cannot be empty")`) continue to produce a valid diagnostic.

---

## Consumer updates

### `src/pflow/execution/runner.py` (4 sites)

**Site 1 — `validate()` method (lines ~283-316)**: delete the entire fabrication loop + post-hoc suggestion generation.

```python
# Before
errors, warnings = WorkflowValidator.validate(
    workflow_ir=ir,
    extracted_params=dummy_params,
    registry=registry,
    skip_node_types=False,
    workflow_file=Path(file_path) if file_path else None,
)
diagnostics = [
    *resolved.diagnostics,
    *warnings,
    *[
        Diagnostic(
            severity=Severity.ERROR,
            message=error,
            title="Validation Error",
            source="validation",
            context={"category": "validation"},
        )
        for error in errors
    ],
]
if errors:
    from pflow.core.validation_utils import generate_validation_suggestions

    for suggestion in generate_validation_suggestions([
        {"message": error, "type": "validation"} for error in errors
    ]):
        diagnostics.append(
            Diagnostic(
                severity=Severity.INFO,
                message=suggestion,
                source="validation",
            )
        )

return ValidationResult(
    valid=len(errors) == 0,
    diagnostics=deduplicate_diagnostics(diagnostics),
)
```

```python
# After
validator_diagnostics = WorkflowValidator.validate(
    workflow_ir=ir,
    extracted_params=dummy_params,
    registry=registry,
    skip_node_types=False,
    workflow_file=Path(file_path) if file_path else None,
)
all_diagnostics = [*resolved.diagnostics, *validator_diagnostics]

return ValidationResult(
    valid=not any(d.severity == Severity.ERROR for d in all_diagnostics),
    diagnostics=deduplicate_diagnostics(all_diagnostics),
)
```

**Site 2 — `_validate()` method (lines ~376-397)**: change from tuple unpack + wrap-as-exception to clean filter + raise.

```python
# Before
def _validate(self, ir: dict[str, Any], params: dict[str, Any]) -> list[Diagnostic]:
    """Run WorkflowValidator once. Returns validation warnings."""
    from pflow.core.workflow.validator import WorkflowValidator
    from pflow.registry import Registry

    wf_path = params.get("_pflow_workflow_file")
    registry = Registry()
    errors, warnings = WorkflowValidator.validate(
        workflow_ir=ir,
        extracted_params=params,
        registry=registry,
        skip_node_types=False,
        workflow_file=Path(wf_path) if wf_path else None,
    )

    if errors:
        # errors is list[str]; WorkflowValidationError accepts list[str | tuple]
        error = WorkflowValidationError(validation_errors=errors)  # type: ignore[arg-type]
        error._pflow_validation_warnings = list(warnings)  # type: ignore[attr-defined]
        raise error

    return warnings
```

```python
# After
def _validate(self, ir: dict[str, Any], params: dict[str, Any]) -> list[Diagnostic]:
    """Run WorkflowValidator once. Returns validation warnings."""
    from pflow.core.workflow.validator import WorkflowValidator
    from pflow.registry import Registry

    wf_path = params.get("_pflow_workflow_file")
    registry = Registry()
    diagnostics = WorkflowValidator.validate(
        workflow_ir=ir,
        extracted_params=params,
        registry=registry,
        skip_node_types=False,
        workflow_file=Path(wf_path) if wf_path else None,
    )

    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    warnings = [d for d in diagnostics if d.severity == Severity.WARNING]

    if errors:
        exc = WorkflowValidationError(validation_errors=errors)
        exc._pflow_validation_warnings = list(warnings)  # type: ignore[attr-defined]
        raise exc

    return warnings
```

`# type: ignore[arg-type]` is deleted. One `type: ignore[attr-defined]` remains for the dynamic attribute assignment pattern (used elsewhere in the codebase, orthogonal to #219).

**Site 3 — imports**: remove `from pflow.core.validation_utils import generate_validation_suggestions` lazy import (line 305).

**Site 4 — Severity import**: add `Severity` to existing `from pflow.core.diagnostic import` at the top of the file if not already imported.

### `src/pflow/core/workflow/save_service.py` (line ~131-143)

```python
# Before
errors, _ = WorkflowValidator.validate(
    workflow_ir=workflow_ir,
    extracted_params=dummy_params,
    registry=registry,
    skip_node_types=False,
    workflow_file=source_path,
)

if errors:
    error_msg = f"{source_desc} - Validation errors:\n"
    for i, error in enumerate(errors, 1):
        error_msg += f"  {i}. {error}\n"
    raise WorkflowValidationError(error_msg.rstrip())
```

```python
# After
from pflow.core.diagnostic import Severity

validator_diagnostics = WorkflowValidator.validate(
    workflow_ir=workflow_ir,
    extracted_params=dummy_params,
    registry=registry,
    skip_node_types=False,
    workflow_file=source_path,
)
errors = [d for d in validator_diagnostics if d.severity == Severity.ERROR]

if errors:
    # Preserve structured diagnostics on the exception; the summary provides a one-line overview.
    summary = f"{source_desc} - Validation errors:\n" + "\n".join(
        f"  {i}. {d.message}" for i, d in enumerate(errors, 1)
    )
    raise WorkflowValidationError(summary=summary, validation_errors=errors)
```

### `src/pflow/execution/formatters/validation_formatter.py` — REVIEW ADDITION

**Why this is in scope** (added during plan review): The plan's "Manual reproduction" verification section promised that running `pflow workflow.pflow.md --validate-only` on a broken workflow would render the full structured format with `Error 1: Validation Error / message / At: ... / Did you mean one of these? / → suggestion`. But verification of the current `format_validation_failure()` body shows it only renders 3 fields per error (`message`, `context["path"]`, `suggestions[0]`) — title, node_id, available_fields, similar_names, additional suggestions, and the unified `Error N:` header are all dropped.

**This is the dominant text path for both CLI (`cli/main.py:420`) and MCP (`mcp_server/services/execution_service.py:298`)**. Without rewriting this formatter, the user-visible improvement promised by the plan happens only in JSON output mode.

```python
# Before (validation_formatter.py:31-56)
def format_validation_failure(errors: list[Diagnostic]) -> str:
    error_count = len(errors)
    lines = [f"✗ Validation failed ({error_count} error{'s' if error_count != 1 else ''}):", ""]

    for i, error in enumerate(errors[:5], 1):
        lines.append(f"  {i}. {error.message}")
        context = error.context or {}
        if (path := context.get("path")) and path != "root":
            lines.append(f"     At: {path}")
        if error.suggestions:
            lines.append(f"     → {error.suggestions[0]}")

    if error_count > 5:
        remaining = error_count - 5
        lines.append("")
        lines.append(f"  ... and {remaining} more error{'s' if remaining != 1 else ''}")

    return "\n".join(lines)
```

```python
# After — delegates to format_diagnostic for full unified rendering
from pflow.core.diagnostic import Diagnostic, format_diagnostic

def format_validation_failure(errors: list[Diagnostic]) -> str:
    error_count = len(errors)
    lines = [f"✗ Validation failed ({error_count} error{'s' if error_count != 1 else ''}):", ""]

    for i, error in enumerate(errors[:5], 1):
        lines.append(format_diagnostic(error, error_number=i))
        lines.append("")  # Blank line between errors

    if error_count > 5:
        remaining = error_count - 5
        lines.append(f"  ... and {remaining} more error{'s' if remaining != 1 else ''}")

    return "\n".join(lines).rstrip()
```

`format_diagnostic()` is the unified renderer at `src/pflow/core/diagnostic.py:102` — same renderer that text-mode CLI errors and MCP tool errors already go through. After this change, validate-only output is identical in shape to runtime/compilation errors. This is the consistency Task 144 was building toward and the user-visible win promised by issue #219.

**Test impact**: `tests/test_execution/formatters/test_validation_formatter.py` (~15 tests) need updating because the output shape changes. The new format is the unified format from `format_diagnostic()`. The tests should assert on the rendered output containing the expected sections (title line, message, At line, suggestions). Since `format_diagnostic()` is already exhaustively tested in `tests/test_core/test_diagnostic.py`, the formatter tests can simplify to "delegates correctly + truncates at 5".

**Run the baseline comparison after this change** (`uv run python .taskmaster/tasks/task_144/research/capture_baselines.py compare`) to verify the rendering improves but stays semantically equivalent for existing fixtures.

### `src/pflow/runtime/workflow_executor.py:337` — REVIEW ADDITION

**Why this is in scope** (added during plan review): The plan extends `_add_child_provenance` to handle errors symmetrically with warnings, claiming "Full symmetry with the warnings path. Dedup works naturally because `Diagnostic.__hash__` includes the prefixed message."

But verification reveals the runtime parser-warning propagation path uses a DIFFERENT `node_id` policy than the validator's `_add_child_provenance`:

```python
# src/pflow/runtime/workflow_executor.py:336-338 (CURRENT)
parser_diagnostics.append(
    replace(d, message=format_child_provenance(step_id, d.message), node_id=step_id)  # ALWAYS overwrites
)

# src/pflow/core/workflow/validator.py:32 (CURRENT — and the plan's V16 keeps this)
replace(w, message=format_child_provenance(step_id, w.message), node_id=w.node_id or step_id)  # PRESERVES child's
```

The runtime path always overwrites `node_id` with the parent step ID. The validator path preserves the child's own `node_id` if set. After conversion, two different `node_id` values for the same logical warning produce different `Diagnostic.__hash__` values → no dedup → duplicate diagnostics if a workflow run hits both validation AND runtime paths for the same child.

**This is a latent bug today** (already breaks dedup for warnings between validation phase and runtime parser-warning propagation). The plan would lock it in for errors too.

```python
# Fix at src/pflow/runtime/workflow_executor.py:337
parser_diagnostics.append(
    replace(d, message=format_child_provenance(step_id, d.message), node_id=d.node_id or step_id)
)
```

One-line change. Aligns runtime path with validator path. Preserves child's `node_id` when set. After this fix, both paths produce identical `(severity, source, node_id, message)` tuples for the same logical warning, and `Diagnostic.__hash__` collapses them via `deduplicate_diagnostics()`.

**Test verification**: Run `tests/test_execution/test_runner.py::test_sibling_child_parser_warnings_not_collapsed_by_dedup` and `tests/test_execution/test_runner.py::test_child_cache_lint_warning_propagates_to_parent_validation` after this fix. They should still pass — the change preserves sibling differentiation (different `step_id` → different prefixed message → different hash) while collapsing identical-content warnings from the dual paths.

### `src/pflow/cli/main.py:631-640`

```python
# Before
raise WorkflowValidationError(
    summary="Invalid parameter names",
    validation_errors=[
        (
            f"Invalid parameter name(s): {', '.join(invalid_keys)}",
            "",
            "Parameter names cannot contain shell special characters ($, |, >, <, &, ;, etc.)",
        )
    ],
)
```

```python
# After
from pflow.core.diagnostic import Diagnostic, Severity  # add to existing imports

raise WorkflowValidationError(
    summary="Invalid parameter names",
    validation_errors=[
        Diagnostic(
            severity=Severity.ERROR,
            source="validation",
            title="Validation Error",
            message=f"Invalid parameter name(s): {', '.join(invalid_keys)}",
            suggestions=[
                "Parameter names cannot contain shell special characters ($, |, >, <, &, ;, etc.)",
            ],
            context={"category": "validation"},
        )
    ],
)
```

### `src/pflow/runtime/compilation/compile_validation.py:115-125`

Already specified in Layer 1 section. One-line change: `e` → `d.message`.

---

## Deletions

### 1. `src/pflow/core/validation_utils.py` — delete `generate_validation_suggestions()`

Remove lines 93-132 entirely. The function and its docstring.

### 2. `tests/test_core/test_workflow_data_flow.py` — delete `TestValidationSuggestions` class

Remove lines 857-908 (the entire class with 4 test methods):
- `test_no_template_suggestion_for_no_inputs_error`
- `test_template_suggestion_suppressed_when_no_inputs_with_multiple_errors`
- `test_no_template_suggestion_for_declared_inputs_error`
- `test_no_template_suggestion_for_did_you_mean_error`

Also remove the import: `from pflow.core.validation_utils import generate_validation_suggestions` (line 5).

These tests verify the pattern-matching fallback behavior we're removing. They have no analog in the new system because suggestions come from the validator directly at the source.

### 3. `src/pflow/execution/runner.py:290-316`

Already specified in Consumer updates. The entire fabrication loop + post-hoc suggestion generation + `generate_validation_suggestions` lazy import is deleted.

### 4. `src/pflow/execution/runner.py:392-393` — `# type: ignore[arg-type]`

Already specified. Removed by virtue of the type actually matching after the field change.

### 5. `src/pflow/core/exceptions.py:82-111` — tuple/str branches in `to_diagnostics`

Already specified in Exception changes section. 30 lines → 8 lines.

---

## Test update strategy

### Mechanical rewrite patterns

**Pattern 1 — Direct index**:
```python
# Before
assert "foo" in errors[0]
# After
assert "foo" in errors[0].message
```

**Pattern 2 — Substring in for loop**:
```python
# Before
assert any("foo" in e for e in errors)
# After
assert any("foo" in d.message for d in errors)
```

**Pattern 3 — String join**:
```python
# Before
error_text = "\n".join(errors)
# After
error_text = "\n".join(d.message for d in errors)
```

**Pattern 4 — List comprehension filter**:
```python
# Before
typed_errors = [e for e in errors if "foo" in e]
# After
typed_errors = [d for d in errors if "foo" in d.message]
```

**Pattern 5 — Tuple unpack → single list + filter**:
```python
# Before
errors, warnings = WorkflowValidator.validate(workflow, ...)
# After (only errors needed)
diagnostics = WorkflowValidator.validate(workflow, ...)
errors = [d for d in diagnostics if d.severity == Severity.ERROR]

# After (both needed)
diagnostics = WorkflowValidator.validate(workflow, ...)
errors = [d for d in diagnostics if d.severity == Severity.ERROR]
warnings = [d for d in diagnostics if d.severity == Severity.WARNING]
```

**Pattern 6 — Variable assignment shortcut**:
```python
# Before
error = errors[0]
assert "foo" in error
assert "bar" in error
# After
error = errors[0].message
assert "foo" in error
assert "bar" in error
```

**Pattern 7 — Set comprehension**:
```python
# Before
error_messages = set(errors)
# After
error_messages = {d.message for d in errors}
```

Every test change is one of these 7 patterns. No semantic changes except the 1 test in test_diagnostic.py (see below).

### Required import additions

Tests that use Pattern 5 need to import `Severity`:

```python
from pflow.core.diagnostic import Severity
```

### File-by-file checklist (from Agent B's enumeration)

| File | Assertions | Complexity | Notes |
|---|---|---|---|
| `tests/test_core/test_workflow_validator.py` | 25 | Low | Dominant: Pattern 2 (substring in for-loop) |
| `tests/test_core/test_output_source_validation.py` | 15 | Low | Dominant: Pattern 1 (direct index) |
| `tests/test_core/test_sub_workflow_validation.py` | 26 | Low | Dominant: Pattern 2 |
| `tests/test_core/test_unknown_param_validation.py` | 12 | Low | **Also**: `_validate_unknown_params` signature now returns `list[Diagnostic]` — test calls at lines 42, 64, 84, 105, 125, 154 adjust |
| `tests/test_core/test_workflow_validator_outputs.py` | 11 | Low | Dominant: Pattern 3 (string join) |
| `tests/test_core/test_cache_lint_warning.py` | 0 | None | Already uses Diagnostic fields for warnings; errors are `== 0` checks — but tuple→list change requires filter, see test_cache_lint section below |
| `tests/test_core/test_file_resolver_integration.py` | 2 | Low | Pattern 3 |
| `tests/test_core/test_workflow_data_flow.py` | 35 + 4 delete | Low | + delete `TestValidationSuggestions` class |
| `tests/test_core/test_workflow_save_service.py` | 0 | None | `pytest.raises(..., match=...)` against summary (unchanged) |
| `tests/test_core/test_diagnostic.py` | 1 | **Medium (semantic)** | Rewrite `test_exception_to_diagnostics_workflow_validation_error_fans_out` — see below |
| `tests/test_execution/test_runner.py` | 0 | None | `wraps=` pattern unchanged |
| `tests/test_execution/formatters/test_validation_formatter.py` | 0 | None | Already `list[Diagnostic]` |
| `tests/test_cli/test_workflow_output_handling.py` | 0 or 1 | Low | Line 119 `mock.return_value = ([], [])` — change to `mock.return_value = []` for single-list return |
| `tests/test_cli/test_validate_only.py` | 0 | None | CLI subprocess output |
| `tests/test_cli/test_unified_error_output.py` | 0 | None | Uses `exception_to_diagnostics` |
| `tests/test_mcp_server/test_mcp_warnings.py` | 0 | None | Patches `_validate`, return shape unchanged (still `list[Diagnostic]` warnings) |
| `tests/test_integration/test_unused_inputs.py` | 12 | Low | Patterns 1, 2 |
| `tests/test_integration/test_template_resolution_hardening.py` | 0 | None | Uses `result.errors[0].message` already |
| `tests/test_runtime/test_template_integration.py` | 1 | Low | Pattern 2 |
| `tests/test_runtime/test_template_validation/test_validator.py` | 30 | Low-Medium | Pattern 6 dominant (`error = errors[0]` assignments) |
| `tests/test_runtime/test_template_validation/test_types.py` | 60 | Medium | Pattern 4 dominant (list comprehensions). Biggest file. |
| `tests/test_runtime/test_template_validation/test_enhanced_errors.py` | 9 | Low | Pattern 7 (one set comprehension) |
| `tests/test_runtime/test_template_validation/test_batch_item_validation.py` | 30 | Low | Pattern 1 dominant |
| `tests/test_runtime/test_template_validation/test_malformed.py` | 20 | Low | Pattern 1 dominant |
| `tests/test_runtime/test_template_validation/test_unused_inputs.py` | 20 | Low | Patterns 1, 3 |
| `tests/test_runtime/test_template_validation/test_array_notation.py` | 0 | None | Only `isinstance` check |
| `tests/test_runtime/test_template_validation/test_union_types.py` | 0 | None | Only `len() == 0` |
| `tests/test_runtime/test_template_validation/test_warnings.py` | 0 | None | Only `len()` |
| `tests/test_runtime/test_settings_env_integration.py` | 0 | None | Out of scope (tests `prepare_inputs`) |
| **TOTAL** | **~309** | | |

### test_cache_lint_warning.py tuple→single-list adjustment

This file uses the pattern `errors, warnings = WorkflowValidator.validate(ir, skip_node_types=True)` to access warnings. Since cache lint produces warnings in the same list as potential errors now, this pattern needs updating:

```python
# Before
errors, warnings = WorkflowValidator.validate(ir, skip_node_types=True)
assert len(errors) == 0
assert len(warnings) == 1
assert warnings[0].node_id == "get-branch"
assert "cache: false" in warnings[0].message

# After
from pflow.core.diagnostic import Severity

diagnostics = WorkflowValidator.validate(ir, skip_node_types=True)
errors = [d for d in diagnostics if d.severity == Severity.ERROR]
warnings = [d for d in diagnostics if d.severity == Severity.WARNING]
assert len(errors) == 0
assert len(warnings) == 1
assert warnings[0].node_id == "get-branch"
assert "cache: false" in warnings[0].message
```

Apply to all 9 test methods in the file.

### test_diagnostic.py — the one semantic rewrite

**File**: `tests/test_core/test_diagnostic.py:148-163`

```python
# Before
def test_exception_to_diagnostics_workflow_validation_error_fans_out() -> None:
    """WorkflowValidationError produces one Diagnostic per validation error tuple."""
    diagnostics = exception_to_diagnostics(
        WorkflowValidationError(
            validation_errors=[
                ("Missing input", "inputs.name", "Declare the input."),
                "Unknown node type",
            ]
        )
    )

    assert len(diagnostics) == 2
    assert diagnostics[0].message == "Missing input"
    assert diagnostics[0].suggestions == ["Declare the input."]
    assert (diagnostics[0].context or {}).get("path") == "inputs.name"
    assert diagnostics[1].message == "Unknown node type"
```

```python
# After — same test renamed to reflect new contract
def test_exception_to_diagnostics_workflow_validation_error_passes_through() -> None:
    """WorkflowValidationError carries Diagnostics through unchanged."""
    input_diagnostics = [
        Diagnostic(
            severity=Severity.ERROR,
            message="Missing input",
            title="Validation Error",
            suggestions=["Declare the input."],
            source="validation",
            context={"category": "validation", "path": "inputs.name"},
        ),
        Diagnostic(
            severity=Severity.ERROR,
            message="Unknown node type",
            title="Validation Error",
            source="validation",
            context={"category": "validation"},
        ),
    ]
    result = exception_to_diagnostics(
        WorkflowValidationError(validation_errors=input_diagnostics)
    )

    assert len(result) == 2
    assert result[0].message == "Missing input"
    assert result[0].suggestions == ["Declare the input."]
    assert (result[0].context or {}).get("path") == "inputs.name"
    assert result[1].message == "Unknown node type"
```

### Test infrastructure update — `capture_baselines.py`

**File**: `.taskmaster/tasks/task_144/research/capture_baselines.py:134-147`

```python
# Before
fixtures.append(
    Fixture(
        name="workflow-validation-error",
        description="WorkflowValidationError with 3 errors (paths + suggestions)",
        exception=WorkflowValidationError(
            summary="Workflow validation failed",
            validation_errors=[
                ("Unknown node type 'httpp'", "nodes[0].type", "Use 'shell', 'http', 'llm', 'file', or 'mcp'"),
                ("Missing required field 'type'", "nodes[1]", "Every node must have a 'type' field"),
                ("Undefined template variable '${api_key}'", "nodes[2].params.url", None),
            ],
        ),
        expected_context={
            "category": "The error category (validation)",
            "path": "Location in workflow IR (e.g., nodes[0].type)",
        },
    )
)
```

```python
# After
from pflow.core.diagnostic import Diagnostic, Severity

fixtures.append(
    Fixture(
        name="workflow-validation-error",
        description="WorkflowValidationError with 3 errors (paths + suggestions)",
        exception=WorkflowValidationError(
            summary="Workflow validation failed",
            validation_errors=[
                Diagnostic(
                    severity=Severity.ERROR,
                    message="Unknown node type 'httpp'",
                    title="Validation Error",
                    suggestions=["Use 'shell', 'http', 'llm', 'file', or 'mcp'"],
                    source="validation",
                    context={"category": "validation", "path": "nodes[0].type"},
                ),
                Diagnostic(
                    severity=Severity.ERROR,
                    message="Missing required field 'type'",
                    title="Validation Error",
                    suggestions=["Every node must have a 'type' field"],
                    source="validation",
                    context={"category": "validation", "path": "nodes[1]"},
                ),
                Diagnostic(
                    severity=Severity.ERROR,
                    message="Undefined template variable '${api_key}'",
                    title="Validation Error",
                    source="validation",
                    context={"category": "validation", "path": "nodes[2].params.url"},
                ),
            ],
        ),
        expected_context={
            "category": "The error category (validation)",
            "path": "Location in workflow IR (e.g., nodes[0].type)",
        },
    )
)
```

Run `uv run python .taskmaster/tasks/task_144/research/capture_baselines.py before` **before** any other changes to establish the pre-change baseline, then `after` + `compare` after all changes are in place.

---

## Structured-output assertions (the 5% non-mechanical additions)

For 5 high-value tests, add explicit structure assertions to prove the Diagnostic carries the path, suggestions, context fields end-to-end. These are NEW assertions added alongside the mechanical `.message` rewrites, not replacements.

| Test | New assertion | Why |
|---|---|---|
| `test_workflow_validator.py::test_node_type_validation_errors` | `assert errors[0].context.get("path") == "nodes[0].type"` + `assert errors[0].context.get("node_type") == "unknown-node-type"` | Guards node_type producer V6 |
| `test_unknown_param_validation.py::test_suggests_similar_param` | `assert "prompt" in errors[0].suggestions[0]` + `assert errors[0].context["similar_names"] == ["prompt"]` | Guards unknown params producer V12 |
| `test_workflow_validator_outputs.py::test_typo_shows_fuzzy_match` | `assert errors[0].context["similar_names"] == ["generate_story"]` | Guards output-source fuzzy match |
| `test_sub_workflow_validation.py::test_missing_required_input_detected` | `assert errors[0].context.get("sub_workflow_path") is not None` + `assert errors[0].context.get("sub_workflow_step") is not None` | Guards sub-workflow provenance V16 |
| `test_template_validation/test_validator.py::test_node_outputs_suggestions` (or equivalent) | `assert errors[0].context["available_fields"]` is populated + `assert errors[0].context["category"] == "template_error"` | Guards `format_enhanced_node_error` → `_build_enhanced_node_diagnostic` conversion |

These 5 assertions prove the structure actually flows through end-to-end. They're cheap and catch future regressions in the producer logic.

---

## Commit structure (suggested reviewable order)

Each commit is internally consistent (tests pass on it, even if assertions in later-touched files are still raw strings until the final commit). Keep them atomic for review.

### Commit 1: Broaden `available_fields` renderer gate

**Scope**: `src/pflow/core/diagnostic.py` only.
**Change**: Remove `category == "template_error"` gate. Rename `_format_template_error_lines` to `_format_available_fields_block`. Add `source_file` renderer block.
**Tests**: No test changes. Existing tests pass because the renamed function's `if not available: return []` early return preserves behavior for diagnostics without `available_fields`.
**Verification**: `uv run python .taskmaster/tasks/task_144/research/capture_baselines.py before` (capture first), then `after` + `compare` after this commit. All existing fixtures identical.

### Commit 2: Convert `data_flow.py` + compiler consumer

**Scope**:
- `src/pflow/core/workflow/data_flow.py` (validate_data_flow + helpers + CycleError)
- `src/pflow/runtime/compilation/compile_validation.py:115-125` (extract .message)
- `src/pflow/core/workflow/validator.py:_validate_data_flow` (caller, still routes through the intermediate string interface if needed for transition)
- `tests/test_core/test_workflow_data_flow.py` (35 assertions + delete TestValidationSuggestions class)

**Subtle**: validator.py:_validate_data_flow currently calls `validate_data_flow()` and wraps its string result. After this commit, validate_data_flow returns `list[Diagnostic]` directly — _validate_data_flow just passes it through.

### Commit 3: Convert template validation layer

**Scope**:
- `src/pflow/runtime/template_validation/path_validation.py` (15 producers)
- `src/pflow/runtime/template_validation/type_validation.py` (3 producers)
- `src/pflow/runtime/template_validation/batch_item_validation.py` (2 producers)
- `src/pflow/runtime/template_validation/validator.py` (orchestrator + 2 helpers)
- All tests/test_runtime/test_template_validation/* (~200 assertions)
- tests/test_integration/test_unused_inputs.py (12)
- tests/test_runtime/test_template_integration.py (1)

**Subtle**: validate_workflow_templates now returns `list[Diagnostic]`. The caller in `core/workflow/validator.py:_validate_templates` routes it through — same change pattern as step 2.

### Commit 4: Convert `WorkflowValidator` outer layer + exception

**Scope**:
- `src/pflow/core/workflow/validator.py` (9 helpers + orchestrator signature change)
- `src/pflow/core/exceptions.py` (WorkflowValidationError.validation_errors: list[Diagnostic], simplified to_diagnostics)
- `tests/test_core/test_workflow_validator.py` (25 assertions)
- `tests/test_core/test_output_source_validation.py` (15)
- `tests/test_core/test_sub_workflow_validation.py` (26)
- `tests/test_core/test_unknown_param_validation.py` (12)
- `tests/test_core/test_workflow_validator_outputs.py` (11)
- `tests/test_core/test_cache_lint_warning.py` (tuple→single-list adjustment for 9 methods)
- `tests/test_core/test_file_resolver_integration.py` (2)
- `tests/test_core/test_diagnostic.py` (1 semantic rewrite)

This is the biggest commit. It changes the outer signature and all its direct test consumers.

### Commit 5: Simplify consumers + delete dead code

**Scope**:
- `src/pflow/execution/runner.py` (fabrication loop + suggestion reverse-engineering + type: ignore)
- `src/pflow/core/workflow/save_service.py` (error aggregation)
- `src/pflow/cli/main.py:631-640` (invalid params rewrite)
- `src/pflow/core/validation_utils.py` (delete generate_validation_suggestions)
- `.taskmaster/tasks/task_144/research/capture_baselines.py` (update fixture)
- `tests/test_cli/test_workflow_output_handling.py` (mock adjustment if needed)

This commit is the "cleanup" — everything that becomes trivial or deletable after the validator is structured.

### Commit 6 (optional): Add structured assertions to high-value tests

**Scope**: 5 tests specified in Section 10 "Structured-output assertions". Adds new assertions without removing existing ones.

### Rationale for this order

1. Renderer change first — isolated, zero-impact, enables all downstream producers.
2. Data flow second — bottom-up, independent primitive.
3. Template validation third — depends on bottom-up, independent of outer validator.
4. Outer validator + exception fourth — largest commit, depends on previous layers.
5. Consumer cleanup fifth — all the downstream simplification becomes possible only after the validator is structured.

Each commit passes `make test` independently (subject to the "caller still routes strings through in transition" caveat for commits 2 and 3 — see each commit's subtle note).

**Alternative**: Merge commits 2+3+4 into one big commit if the transition-state routing proves awkward. Either approach works; separate commits are easier to review.

---

## Verification

### Before implementation begins — pre-implementation grep audit

```bash
cd /Users/andfal/projects/pflow-fix-workflow-validator-return-type

# 1. Capture rendering baseline (MANDATORY — Task 144 review's "run after ANY rendering change" rule)
uv run python .taskmaster/tasks/task_144/research/capture_baselines.py before

# 2. Pre-implementation grep audit — counts must match plan's enumeration
# Tuple-unpack patterns (tests should rewrite to single list + filter):
grep -rn "errors,\s*warnings\s*=\s*WorkflowValidator" tests/ src/
grep -rn "errors,\s*_warnings\s*=\s*WorkflowValidator" tests/ src/
grep -rn "errors,\s*_\s*=\s*WorkflowValidator" tests/ src/
grep -rn "errors,\s*warnings\s*=\s*validate_workflow_templates" tests/ src/
grep -rn "errors,\s*_warnings\s*=\s*validate_workflow_templates" tests/ src/
grep -rn "errors\s*=\s*validate_data_flow" tests/ src/

# WorkflowValidationError construction sites (should match plan's enumeration of 21 prod + 3 test):
grep -rn "WorkflowValidationError(" src/ tests/

# generate_validation_suggestions consumers (should be exactly 1 prod + 1 test class, both deleted):
grep -rn "generate_validation_suggestions" src/ tests/

# CycleError external callers (verified zero — only data_flow.py:93 itself):
grep -rn "CycleError(" src/ tests/

# 3. Verify current test suite passes
make test  # establish baseline; some existing tests on this branch may already be broken

# 4. Verify mypy passes on untouched files
make check
```

**Save the grep output as `before-grep.txt`.** After all commits, re-run the same greps and diff against `before-grep.txt`. Each remaining occurrence must be intentional (e.g., the `wraps=` mock in `test_execution/test_runner.py:88` survives unchanged).

### During implementation

Per commit:
```bash
# After each commit
make test
make check

# Run the subset of tests most likely affected by this commit
uv run pytest tests/test_core/test_workflow_validator.py tests/test_core/test_workflow_data_flow.py -xvs

# Targeted template validation
uv run pytest tests/test_runtime/test_template_validation/ -xvs
```

### After all commits

```bash
# 1. Full test suite
make test

# 2. All checks (lint, type, etc.)
make check

# 3. Baseline comparison — must show validator-produced diagnostics are SAME-OR-BETTER
uv run python .taskmaster/tasks/task_144/research/capture_baselines.py after
uv run python .taskmaster/tasks/task_144/research/capture_baselines.py compare

# 4. Verify type ignore count decreased
grep -rn "type: ignore\[arg-type\]" src/pflow/execution/runner.py
# (should return no matches for this specific ignore)

# 5. Verify deletion of generate_validation_suggestions
grep -rn "generate_validation_suggestions" src/
# (should return no matches in src/)

# 6. Verify tuple/str branches removed from WorkflowValidationError
grep -n "isinstance(error, tuple)" src/pflow/core/exceptions.py
# (should return no matches)
```

### Manual reproduction of the live symptom

Create a workflow with an unknown node reference:

```bash
cat > /tmp/broken.pflow.md << 'EOF'
# Broken Workflow

This workflow references a non-existent node.

## Steps

### broken
Runs a command using a non-existent upstream node.

- type: shell
- command: echo ${nonexistant.stdout}
EOF

uv run pflow /tmp/broken.pflow.md --validate-only
```

**Expected output after change** (rough shape):
```
Error 1: Validation Error

Node 'broken' references non-existent node 'nonexistant' in parameter 'command'.
  At: node 'broken', nodes[0].params.command

  → Did you mean '...'?    (if there's a close match in declared inputs/nodes)
```

**Must NOT contain**:
- Generic "ℹ Check template syntax: ${node.output}" fallback line (would indicate `generate_validation_suggestions` leak)
- Flat "Node 'broken' references non-existent node 'nonexistant'" without `At:` line (would indicate unstructured fallback)

### JSON output check

```bash
uv run pflow /tmp/broken.pflow.md --validate-only --output-format json | jq '.diagnostics[0]'
```

**Expected**:
```json
{
  "severity": "error",
  "message": "Node 'broken' references non-existent node 'nonexistant' in parameter 'command'.",
  "source": "validator",
  "title": "Validation Error",
  "suggestions": ["..."] | null,
  "node_id": "broken",
  "context": {
    "category": "validation",
    "path": "nodes[0].params.command",
    "available_fields": [...],
    "similar_names": [...] | null
  }
}
```

This is the acceptance criterion — structured `context.path`, `context.available_fields`, `context.similar_names` fields present in JSON output.

---

## Critical files to read before implementation

The implementing agent should read these files in full before touching anything:

1. `src/pflow/core/diagnostic.py` — the data type, renderer, `format_child_provenance` helper
2. `src/pflow/core/exceptions.py` — exception hierarchy, especially `WorkflowValidationError`
3. `src/pflow/core/workflow/validator.py` — outer validator (the orchestrator being changed)
4. `src/pflow/core/workflow/data_flow.py` — primitive data flow validator
5. `src/pflow/runtime/template_validation/validator.py` — template orchestrator
6. `src/pflow/runtime/template_validation/path_validation.py` — 15 producers live here (read ALL)
7. `src/pflow/runtime/template_validation/type_validation.py` — 3 producers
8. `src/pflow/runtime/template_validation/batch_item_validation.py` — 2 producers
9. `src/pflow/execution/runner.py` — consumer with the fabrication loop to delete
10. `.taskmaster/tasks/task_141/task-review.md` — exception hierarchy consolidation context
11. `.taskmaster/tasks/task_143/task-review.md` — unified diagnostic system context
12. `.taskmaster/tasks/task_144/task-review.md` — rendering redesign context (most relevant)
13. `src/pflow/core/CLAUDE.md` — canonical exception usage table
14. `src/pflow/core/workflow/CLAUDE.md` — 9-step validator pipeline description
15. `src/pflow/runtime/template_validation/CLAUDE.md` — template validation design decisions

Task 144's review specifically warns: _"Run `capture_baselines.py` after ANY rendering change"_. This PR makes one renderer change (the gate broadening) so the baseline run is mandatory.

---

## Reused helpers (do NOT recreate)

The implementing agent must reuse these existing helpers:

| Helper | Location | Used for |
|---|---|---|
| `Diagnostic`, `Severity` | `src/pflow/core/diagnostic.py` | The type every producer builds |
| `format_child_provenance(step_id, message)` | `src/pflow/core/diagnostic.py:93` | Sub-workflow error/warning provenance prefix — symmetry across propagation paths |
| `find_similar_items(target, candidates, max_results, method="fuzzy")` | `src/pflow/core/suggestion_utils.py` | Fuzzy matching for "did you mean" suggestions |
| `sanitize_for_display(value)` | `src/pflow/runtime/template_validation/utils.py` | Strips control characters from user-controlled strings (template injection prevention) |
| `find_similar_paths(attempted, available_paths)` | `src/pflow/runtime/template_validation/utils.py` | Fuzzy matching over (path, type) tuples |
| `build_paths_from_entries(node_entries)` | `src/pflow/runtime/template_validation/utils.py` | Builds (path, type) list from node outputs dict |
| `MAX_DISPLAYED_FIELDS` | `src/pflow/runtime/template_validation/utils.py` | Truncation constant for `available_fields` |
| `deduplicate_diagnostics(list)` | `src/pflow/core/diagnostic.py:82` | Already used in runner.py — no changes |
| `_add_child_provenance(diagnostics, step_id)` | `src/pflow/core/workflow/validator.py:19` | **Extend** to accept optional `ref_label` and handle both errors and warnings |
| `SchemaValidationError.to_diagnostics()` | `src/pflow/core/exceptions.py:165` | **Call directly** from V1 — exception already self-describes |

Do not recreate any of these.

---

## Risks and mitigations

### Risk 1: Missed consumer breaks integration somewhere unexpected

**Mitigation**: Agent D's enumeration covers all 21 `WorkflowValidationError` construction sites, all 3 mock patterns, all ~90 direct test call sites. Running `make test` between commits catches regressions quickly.

### Risk 2: Template validation test_types.py has 60 pattern 4 rewrites — hand rewriting risks typos

**Mitigation**: The pattern is uniform: `[e for e in errors if "..." in e]` → `[d for d in errors if "..." in d.message]`. Use repeated `Edit` with `replace_all=False` (for safety) or sed-like mass edit, but verify visually after each file.

### Risk 3: Baseline comparison shows rendering drift for existing exception fixtures

**Mitigation**: The renderer gate broadening is additive — it only ADDS rendering for `available_fields` when present. Existing fixtures don't set `available_fields`, so they render identically. If the baseline shows drift, investigate — it indicates an unintended side-effect.

### Risk 4: Sub-workflow provenance dedup breaks

Task 143 discovered that dual-propagation-path dedup requires identical message formats between validation and runtime paths. Since we're using `format_child_provenance` (the same helper used by the warnings path and the `WorkflowExecutor._propagate_child_parser_warnings` runtime path), dedup should work naturally.

**Mitigation**: Run `tests/test_execution/test_runner.py::test_sibling_child_parser_warnings_not_collapsed_by_dedup` explicitly. If this test fails, the provenance format diverged.

### Risk 5: `_add_child_provenance` helper signature change breaks its existing caller

The existing helper takes `(warnings, step_id)`. Adding optional `ref_label` is backward compatible. Calls that don't pass `ref_label` get `sub_workflow_path` not set — acceptable since the existing warnings-only path doesn't need it.

**Mitigation**: Verify with `tests/test_execution/test_runner.py::test_child_parser_warning_survives_prep_failure` and related sub-workflow warning tests.

### Risk 6: `validate_data_flow` change breaks the compiler path

The compiler's `_validate_data_flow_at_compile_time` wraps `validate_data_flow` strings into a `CompilationError`. After the change, it extracts `.message` from diagnostics. If the extraction doesn't match the current user-visible format exactly, compile-time error messages change.

**Mitigation**: Run `tests/test_runtime/test_compilation/` specifically after Commit 2. Spot-check that compile errors still render sensibly.

### Risk 7: Performance impact

Building `Diagnostic` objects is slightly more expensive than appending strings to a list. For workflows with hundreds of validation errors, this adds allocations.

**Mitigation**: Validation is not a hot path. Performance impact is negligible. No mitigation needed.

### Risk 8: `_validate_data_flow` defensive wrapper is NOT dead code

The plan originally said "V4: defensive wrap (becomes dead code)". **Correction from review**: this `except Exception` wrapper is **load-bearing**, not dead. It catches `TypeError` raised by `Diagnostic.__post_init__` when a producer accidentally passes `suggestions="bare string"` instead of `suggestions=["bare string"]`. The plan should describe it as a **safety net for malformed Diagnostic construction** and keep it in place.

```python
@staticmethod
def _validate_data_flow(workflow_ir: dict[str, Any]) -> list[Diagnostic]:
    from pflow.core.workflow.data_flow import validate_data_flow
    try:
        return validate_data_flow(workflow_ir)
    except Exception as e:
        # Load-bearing: catches TypeError from malformed Diagnostic construction
        # (e.g., suggestions="string" instead of suggestions=["string"]).
        return [Diagnostic(
            severity=Severity.ERROR,
            source="validator",
            title="Validation Error",
            message=f"Data flow validation error: {e!s}",
            context={"category": "validation", "exception_type": type(e).__name__},
        )]
```

The same applies to the other `except Exception` wrappers in V2, V5, V7. **Do not delete them**.

---

## Out-of-scope items (explicitly noted, do NOT touch)

1. **`_raise_input_validation_errors()` at `compile_validation.py:40-66`** — aggregates multiple input errors into a single `SchemaValidationError`. Fixing this to preserve per-error structure is a separate improvement. Leave alone.
2. **`prepare_inputs()` in `ir_preparation.py`** — produces tuples routed through `SchemaValidationError`. Separate code path. Don't touch.
3. **`SchemaValidationError`** — already self-describing via Task 141. V1 in validator.py simply calls `e.to_diagnostics()` directly. Don't modify `SchemaValidationError` itself.
4. **Adding `Registry.get_all_node_types()`** for better fuzzy matching. Current behavior (fuzzy match against queried subset) is acceptable.
5. **Adding renderer blocks for `conflicting_inputs`, `cycle_nodes`, `blocked_type`, `unused_inputs`, `items_source`, etc.** — these remain tooling-only (carried to JSON but not rendered in text). The message already contains the information humans need.
6. **Rewriting `test_workflow_save_service.py` tests** — they use `pytest.raises(..., match=)` against `summary`, which is unchanged.
7. **Changing `ValidationResult.diagnostics`** — already correctly typed as `list[Diagnostic]` from Task 144.
8. **Changing `ExecutionResult.diagnostics`** — same, correctly typed from Task 143.

---

## Summary

- **Scope** (after review additions): 13 production files (incl. validation_formatter.py and workflow_executor.py one-line fix) + 6 documentation files, ~20 test files, ~309 assertion updates, ~15 validation_formatter test rewrites, 1 class deletion, 1 renderer block addition, 1 semantic test rewrite.
- **Deletions**: `generate_validation_suggestions()` function, 4-test `TestValidationSuggestions` class, 26 lines of fabrication loop in runner.py, 30 lines of tuple/str branching in `WorkflowValidationError.to_diagnostics`, 1 `type: ignore[arg-type]`.
- **Architectural principle**: "Producers are self-describing" — extends Task 144's exception pattern to validator checks. Three-layer model (Producer → Diagnostic → Renderer) now applies to the full error pipeline.
- **User-visible improvement**: Validate-only errors gain titles, `At:` location lines, structured suggestions, fuzzy-matched "Did you mean", and `Available fields` blocks — matching what runtime and compilation errors already show. **The `format_validation_failure()` rewrite (review addition) is what actually delivers this in text mode**; without it, the improvement only reaches JSON consumers.
- **Review surface**: Manageable in 5 commits, each internally consistent with passing tests.

**Critical review findings integrated**:
- `format_validation_failure()` rewrite (Agent 3 / review-feature-interactions) — without this, the dominant text path stays bare
- `WorkflowExecutor._propagate_child_parser_warnings:337` `node_id` alignment (Agent 3 + Agent 4) — fixes latent dual-propagation-path dedup bug
- Compiler consumer error filter (Agent 4 / review-validation-consistency) — defensive against future warning-severity producers in data_flow.py
- Full V9/V11 conversions (Agent 1 / review-plan)
- 6 documentation files added to scope (Agent 2 / review-impact-completeness)
- Pre-implementation grep audit (Agent 1 + Agent 2)
