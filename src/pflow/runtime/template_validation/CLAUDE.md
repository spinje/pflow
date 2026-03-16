# Template Validation Package

Pre-execution validation of template variables (`${...}`) in workflows. Validates path existence, type compatibility, shell safety, and batch item field access before any node executes.

## File Structure

```
template_validation/
├── __init__.py              # Public API re-exports
├── validator.py             # Orchestrator — runs all passes, aggregates errors/warnings
├── path_validation.py       # Pass 5: path existence + all path error formatting
├── type_validation.py       # Passes 6+7: type matching + shell command safety
├── batch_item_validation.py # Pass 8: ${item.field} against inferred item structure
├── utils.py                 # Shared: ValidationWarning, path splitting, display helpers
└── type_checker.py          # Type compatibility matrix and inference
```

## Public API (via `__init__.py`)

```python
from pflow.runtime.template_validation import (
    validate_workflow_templates,   # Main entry point (orchestrator)
    extract_node_outputs,          # Builds node_outputs dict (also used by compiler)
    ValidationWarning,             # Dataclass for runtime-validated warnings
    flatten_output_structure,      # Recursive path flattening (used by formatters)
    split_template_path,           # Dot-splitting that preserves ${...} nesting
    sanitize_for_display,          # Security: strips control chars for error messages
    MAX_DISPLAYED_FIELDS,          # Display limit constant (20)
)

# Test-only (import directly from submodule, not re-exported via __init__):
from pflow.runtime.template_validation.validator import _extract_all_templates
```

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

## External Consumers

| File | What it imports |
|------|----------------|
| `runtime/compiler.py` | `validate_workflow_templates`, `extract_node_outputs`, `ValidationWarning` |
| `core/workflow_validator.py` | `validate_workflow_templates` (lazy) |
| `execution/formatters/node_output_formatter.py` | `flatten_output_structure` |
| `execution/executor_service.py` | `MAX_DISPLAYED_FIELDS` (lazy) |

## `node_outputs` Dict Shape

All passes consume the `node_outputs` dict built by `extract_node_outputs()` in `validator.py`. Three shapes exist — distinguished by flags:

```python
# Standard node output (namespaced)
node_outputs["fetch.stdout"] = {
    "type": "str", "node_id": "fetch", "node_type": "shell",
    "structure": {},  # nested fields if present
}

# Batch node output (has is_batch_output flag + items with inner structure)
node_outputs["process.results"] = {
    "type": "array", "node_id": "process", "node_type": "llm",
    "is_batch_output": True,
    "items": {"type": "dict", "structure": {"response": {"type": "any"}, "item": {"type": "any"}}},
}

# Batch item alias (injected so ${item.field} resolves during validation)
node_outputs["item"] = {
    "type": "any", "node_id": "process", "node_type": "llm",
    "is_batch_item": True,
}
```

Passes use `is_batch_output` and `is_batch_item` to branch behavior. Workflow nodes get special handling — `validator.py` tries to resolve child workflow outputs at validation time via `_resolve_child_workflow_outputs()`.

**Note:** `validator.py` has dual responsibility — it orchestrates validation passes AND builds the `node_outputs` dict (`extract_node_outputs`, also used by `compiler.py`). Agents looking for output-related code need to look here, not just in the passes.

## Key Behaviors

- Malformed template detection runs first and **returns early** — passes 5-8 don't run if malformed syntax found
- Each module owns both detection logic AND error formatting for its concern
- Error messages include "Did you mean?" suggestions via substring matching
- Shell validation has a single-quote escape hatch: `'${var}'` signals user accepts JSON coercion
- `flatten_output_structure` shows array access patterns: `result.messages[0].text`
- `ValidationWarning` emitted when str-type output needs JSON auto-parsing at runtime
