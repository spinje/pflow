# Template Validation Package

Pre-execution validation of template variables (`${...}`) in workflows. Validates path existence, type compatibility, shell safety, and batch item field access before any node executes.

## File Structure

```
template_validation/
├── __init__.py              # Public API re-exports
├── validator.py             # Orchestrator — runs all passes, aggregates errors/warnings
├── path_validation.py       # Pass 5: path existence + all path error formatting
├── type_validation.py       # Passes 6+7+9: type matching + shell command safety + code-node input annotations
├── batch_item_validation.py # Pass 8: ${item.field} against inferred item structure
├── utils.py                 # Shared: path splitting and display helpers
└── type_checker.py          # Type compatibility matrix and inference
```

## Public API (via `__init__.py`)

```python
from pflow.runtime.template_validation import (
    validate_workflow_templates,   # Main entry point (orchestrator)
    extract_node_outputs,          # Builds node_outputs dict (also used by compiler)
    flatten_output_structure,      # Recursive path flattening (used by formatters)
    split_template_path,           # Dot-splitting that preserves ${...} nesting
    sanitize_for_display,          # Security: strips control chars for error messages
    MAX_DISPLAYED_FIELDS,          # Display limit constant (20)
)

# Test-only (import directly from submodule, not re-exported via __init__):
from pflow.runtime.template_validation.validator import (
    _extract_all_templates,                  # Node-param + batch.items templates
    _extract_cache_templates_for_unused_check,  # Workflow-level ## Cache items only;
                                                 # used ONLY for the unused-input check
)
```

## Cache template extraction — split-extractor contract (Task 159)

Workflow-level `## Cache` chunk vars (`workflow_ir["cache"]["items"][i]["var"]`) live in `_extract_cache_templates_for_unused_check` and are kept OUT of the template sets that flow into the validation passes. Cache var resolution is owned by `core/workflow/data_flow.py::_validate_cache_block`, which emits richer "Cache chunk 'X' references..." diagnostics with similar-name suggestions and source-line metadata. If both extractors fed the same set, the user would see two errors for one mistake.

The union of `_extract_all_templates` + cache templates is computed inline at the call site in `validate_workflow_templates` and passed ONLY to `_validate_unused_inputs` so cache-only inputs aren't flagged as unused. Pass 5 (path validation) instead receives `_field_checkable_templates()` (excludes `??`-chain operands — see "Coalesce operands" below). Passes 6-9 re-extract from the IR themselves and do not consume either set.

## Dependency Graph (no cycles)

```
validator.py (orchestrator)
  ├── path_validation → utils
  ├── type_validation → type_checker
  └── batch_item_validation → path_validation, utils
```

## Validation Passes

| Pass | Module | What it checks |
|------|--------|----------------|
| Malformed | validator.py | `${` without matching `}`, empty `${}` |
| Unused inputs | validator.py | Declared inputs never referenced in templates |
| 5: Path existence | path_validation.py | Template paths resolve to node outputs, inputs, or params |
| 6: Type matching | type_validation.py | Source type compatible with parameter's expected type |
| 7: Shell safety | type_validation.py | dict/list blocked in shell `command` (escape: `'${var}'`) |
| 8: Batch items | batch_item_validation.py | `${item.field}` exists on inferred item structure |
| 9: Code-node annotations | type_validation.py | code-node input annotations vs upstream template types |
| 10: Loop conditions | validator.py | `loop: while:`/`until:` typed-output gate + operator rejection; loop carry-ref checks (issue #445) |

## External Consumers

| File | What it imports |
|------|----------------|
| `runtime/compilation/compile_validation.py` | `extract_node_outputs` only — the template passes do NOT run at compile time |
| `core/workflow/validator.py` | `validate_workflow_templates` (lazy) — the ONLY production caller of the template passes |
| `execution/formatters/node_output_formatter.py` | `flatten_output_structure` |
| `execution/executor_service.py` | `MAX_DISPLAYED_FIELDS` (lazy) |

## `node_outputs` Dict Shape

All passes consume the `node_outputs` dict built by `extract_node_outputs()` in `validator.py`. Four shapes exist — distinguished by flags:

```python
# Standard node output (namespaced)
node_outputs["fetch.stdout"] = {
    "type": "str", "node_id": "fetch", "node_type": "shell",
    "structure": {},  # nested fields if present
}

# Batch node output (has is_batch_output flag + items with inner structure)
# error_handling is stored on the results entry so path_validation can block
# index access when continue mode filters out failed items from results.
node_outputs["process.results"] = {
    "type": "array", "node_id": "process", "node_type": "llm",
    "is_batch_output": True, "error_handling": "fail_fast",
    "items": {"type": "dict", "structure": {"response": {"type": "any"}, "item": {"type": "any"}}},
}

# Batch item alias (injected so ${item.field} resolves during validation)
node_outputs["item"] = {
    "type": "any", "node_id": "process", "node_type": "llm",
    "is_batch_item": True,
}

# Inputs-as-context key (injected so ${key} and ${key.field} resolve during validation)
node_outputs["concept_brief"] = {
    "type": "any", "node_id": "consumer", "node_type": "llm",
    "is_inputs_context": True,
}
```

Passes use `is_batch_output` to branch behavior (path_validation uses it to detect batch nodes and to block index access on results when `error_handling` is `"continue"` — results contains only successful items, so positional indices would be wrong). `is_batch_item` and `is_inputs_context` are metadata flags for provenance — not read by any pass currently. Workflow nodes get special handling — `validator.py` tries to resolve child workflow outputs at validation time via `_resolve_child_workflow_outputs()`.

**Note:** `validator.py` has dual responsibility — it orchestrates validation passes AND builds the `node_outputs` dict (`extract_node_outputs`, also used by `compilation/compile_validation.py`). Agents looking for output-related code need to look here, not just in the passes.

## Key Behaviors

- Malformed template detection runs first and **returns early** — passes 5-8 don't run if malformed syntax found
- Each module owns both detection logic AND error formatting for its concern
- Every producer builds a `Diagnostic` directly at the call site and populates `context["path"]`, `available_fields`, `similar_names`, and `suggestions` from the data the check already has — no string intermediates
- Shell validation has a single-quote escape hatch: `'${var}'` signals user accepts JSON coercion
- `flatten_output_structure` shows array access patterns: `result.messages[0].text`
- `Diagnostic(severity=WARNING, source="validator")` emitted when str-type output needs JSON auto-parsing at runtime
- `_register_node_outputs_from_registry` (`validator.py`) **silently skips unknown node types** — the outer `WorkflowValidator._validate_node_types` step produces the rich "Unknown node type" diagnostic. Raising here would crash the whole validator: issue #237 removed the defensive `except Exception` wrapper in `_validate_templates` that previously would have absorbed it. Any exception from this pass now propagates to the outer CLI/MCP exception boundary.

## Producer context conventions

The renderer in `core/diagnostic_render.py` reads specific context keys to produce structured output blocks. Producers MUST populate the right keys for their concern and MUST NOT populate keys that belong to other subsystems.

**Keys every validator producer should populate when the data is available**:

| Key | Type | Renders as |
|---|---|---|
| `category` | `"validation"` or `"template_error"` | drives title fallback |
| `path` | `"nodes[id=X].params.field"` | `At:` location line |
| `node_type` | str | `Node type: X` |
| `similar_names` | `list[str]` (≤5, producer truncates) | `Did you mean one of these?` block |
| `available_fields` | `list[str]` | `Available {label} (showing N of M):` block |
| `available_fields_total` | int | block header count |
| `available_fields_label` | `"outputs"` / `"nodes"` / `"parameters"` / `"inputs"` / `"batch item fields"` / etc. | block header noun. **Defaults to generic `"fields"` if omitted — always set it explicitly** |
| `template` | str | carried to JSON for downstream consumers |

**Keys validators MUST NEVER set** (each triggers a renderer block meant for a different subsystem and produces misleading output in validation context):

- `phase` — compiler-only, renders `Phase: X`
- `exception_type` — runtime-only, renders `Type: X` (makes validation errors look like Python crashes)
- `raw_response` — HTTP runtime only
- `mcp_error` — MCP runtime only
- `shell_command` / `shell_stdout` / `shell_stderr` — shell runtime only (**presence check**, not truthy — setting `shell_command=None` still triggers the block)
- `line` — parser-only

**Warning-severity producers**: `_format_warning_or_info_diagnostic` in the renderer reads ONLY `message`, `node_id`, and `suggestions` — the entire `context` dict is ignored for warnings. If a warning needs rich output, embed it in `message` or `suggestions` directly.

## Design Decisions

### Three regex patterns for template discovery

Three patterns exist, each serving a different purpose:

| | `_PERMISSIVE_PATTERN` (validation) | `TEMPLATE_PATTERN` (runtime) | `TEMPLATE_EXTRACT_PATTERN` (diagnostics) |
|-|-------------------------------------|------------------------------|------------------------------------------|
| Purpose | Path validation (pass 5) | Template resolution | Data flow validation, error messages, trace suggestions |
| Nested `${...}` in brackets | Yes: `${node[${__index__}].field}` | No: captures inner `${__index__}` only | No |
| `$$` escape handling | No lookbehind | Yes: `(?<!\$)` lookbehind | Yes: `(?<!\$)` lookbehind |
| First-char rules | Permissive (`[\w-]*`) | Strict (`[a-zA-Z_][\w-]*`) | None (`[^}]+` — captures everything) |
| Variable name validation | Partial | Full | None (delegates to downstream) |

`_PERMISSIVE_PATTERN` finds all template-like patterns for error messages. `TEMPLATE_PATTERN` matches well-formed templates for resolution. `TEMPLATE_EXTRACT_PATTERN` is for discovery/diagnostics — captures any `${...}` content for data flow analysis, error formatting, and trace suggestions. It replaces 4 formerly ad-hoc inline regex copies. Do not try to unify these — they serve different jobs.

### Coalesce operands are pre-split before passes

`_iter_template_operands()` splits `${a.field ?? b.field}` into individual operands. Two derived sets come from it: `_extract_all_templates()` (every non-literal operand — used for unused-input detection) and `_field_checkable_templates()` (operands eligible for Pass-5 path/field validation).

**Multi-operand `??` chains are NOT field-checked (issue #441).** Because `??` falls through on a missing field at runtime (`resolve_coalesce` skips an operand whose node ran but whose field is absent, then tries the next), field-checking `${ran_node.optional_field ?? "x"}` would hard-error on a legitimately-optional field — a validator/runtime drift. So coalesce operands are excluded from `_field_checkable_templates`; their **root** existence is still validated in `core/workflow/data_flow.py` (`${nonexistent.x ?? "d"}` is still caught), and a **bare** `${node.field}` with no `??` stays fully field-checked (typos caught). This deliberately reverses the older "validate both operands early" tradeoff to match the runtime fall-through semantics.

**JSON-literal operands (Optional A)**: operands can be JSON literals (`${a ?? 0}`, `${a ?? "x"}`, `${a ?? null}`, bare `${0}`). `_PERMISSIVE_PATTERN` embeds `TemplateResolver._LITERAL_PATTERN` so these don't trip the malformed-template check, and every extractor drops literal operands via `TemplateResolver.is_literal_operand` before treating them as variable references (otherwise `0` would be a bogus "no valid source" node). `_LITERAL_PATTERN` must match only what `try_parse_json` + the `??`-splitter can handle at runtime — it forbids leading-zero numbers (`007`) and `??` inside string literals; a mismatch there means a literal validates clean then silently fails to resolve. `_malformed_literal_operand_hint` emits the targeted "literal operand must be a JSON value" error when an operand looks literal-ish but fails the grammar.

### Passes 5 vs 6-7 see different template sets

Pass 5 (path validation) uses `_PERMISSIVE_PATTERN` via `_field_checkable_templates()` with `split_template_path()` — it sees and validates nested bracket templates like `${results[${__index__}].field}` (but excludes `??`-chain operands, see above).

Passes 6-7 (type validation) use `TemplateResolver.extract_variables()` which uses the strict `TEMPLATE_PATTERN` — nested bracket templates are invisible to it (only the inner `${__index__}` is captured). These templates silently skip type checking. This is acceptable because the inner variables (typically `__index__`) resolve to simple types (`int`) that don't cause type conflicts.

When writing new path-traversal code, always use `split_template_path()` from utils.py — never `str.split(".")`, which breaks on dots inside nested `${...}` expressions.

### Type compatibility matrix

`str → dict/list` is compatible (JSON auto-parsing exists at runtime), but `str → int/float/bool` is not (no primitive coercion). Union handling is asymmetric: source unions require ALL member types to be compatible, target unions require ANY. These follow from the runtime's actual coercion capabilities.

### `initial_params` is a validation boundary

Path validation accepts any nested access on user parameters (`${user_param.deeply.nested.path}`) without checking deeper structure — runtime values can't be validated at compile time. Only node output paths (known structure) get full traversal validation.
