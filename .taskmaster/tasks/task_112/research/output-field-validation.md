# Suggestion: Validate Output Field Access via TypedDict

## Context

When working on the generate-changelog workflow, we noticed that
`${node.result.field_name}` template references are only validated at
the node level — the validator confirms `node` exists as a node ID but
does NOT verify that `field_name` is a valid key in that node's output.

This means a typo like `${compute-version.result.wrong_field}` passes
validation silently and only fails at runtime when the key is missing.

## Current Validation Flow

Template validation happens in `src/pflow/runtime/template_validator.py`.
It is invoked by `src/pflow/core/workflow_validator.py` (WorkflowValidator)
which orchestrates all pre-execution validation.

**What the validator currently checks:**
- `${node_id}` — validates that `node_id` exists as a workflow input or
  node ID in the workflow. Shows "did you mean?" suggestions on typos.
- `${node_id.output_key}` — validates that `node_id` exists, but does
  NOT validate `output_key` against the node's actual output schema.

**What it does NOT check:**
- `${node.result.field}` — the `.field` part is not validated against
  the node's output type. Any field name is accepted.

## How Code Nodes Define Output Types

Code nodes (`src/pflow/nodes/python/python_code.py`) require a type
annotation on the `result` variable:

```python
# Current pattern — type is `dict`, no field information
result: dict = {
    'bump_type': bump_type,
    'next_version': next_version,
    'date_iso': now.strftime('%Y-%m-%d'),
}
```

The code node already parses these annotations at execution time for
type checking (see `src/pflow/runtime/type_checker.py`). But the
annotation `dict` carries no information about which keys exist.

## Opportunity: TypedDict

Python's `TypedDict` declares exact keys with types:

```python
from typing import TypedDict

class VersionResult(TypedDict):
    bump_type: str
    next_version: str
    date_iso: str
    date_month_year: str

result: VersionResult = {
    'bump_type': bump_type,
    'next_version': next_version,
    'date_iso': now.strftime('%Y-%m-%d'),
    'date_month_year': now.strftime('%B %Y'),
}
```

**Verified:** TypedDict works in code nodes today — parses, executes,
and produces correct output. The validator just doesn't read it.

## Suggestion

When implementing Task 112, evaluate whether output field validation
should be included in scope:

1. During validation, parse the code node's Python block with `ast.parse()`
2. Find `ClassDef` nodes that inherit from `TypedDict`
3. If `result` is annotated with a TypedDict class, extract its key names
4. When validating `${node.result.field}`, check `field` against known keys
5. For plain `dict` annotations (no TypedDict), skip field validation

This would catch `${compute-version.result.wrong_field}` at validation
time with a helpful error like "field 'wrong_field' not found in
compute-version output. Available fields: bump_type, next_version,
date_iso, date_month_year."

## How to Reproduce the Gap

```bash
# 1. Take any workflow with a code node that outputs a dict
# 2. Reference a non-existent field in a downstream template
# 3. Run validation — it passes (incorrect)
# 4. Run execution — it fails at runtime (correct but late)

# Example using the generate-changelog workflow:
cp examples/real-workflows/generate-changelog/workflow.pflow.md /tmp/test.pflow.md

# Introduce a wrong field reference
sed -i '' 's/compute-version.result.next_version/compute-version.result.wrong_field/' /tmp/test.pflow.md

# Validation passes (this is the gap):
uv run pflow --validate-only /tmp/test.pflow.md
# Output: ✓ Workflow is valid

# But execution would fail at runtime when the field is accessed
rm /tmp/test.pflow.md
```

## Files Involved

- **Template validator**: `src/pflow/runtime/template_validator.py` — where field validation would be added
- **Workflow validator**: `src/pflow/core/workflow_validator.py` — orchestrator that calls template validation
- **Code node**: `src/pflow/nodes/python/python_code.py` — where TypedDict annotations would be parsed
- **Type checker**: `src/pflow/runtime/type_checker.py` — existing type checking infrastructure
- **Markdown parser**: `src/pflow/core/markdown_parser.py` — already validates Python syntax with `ast.parse()`

## Complexity Assessment

- AST extraction of TypedDict keys is straightforward (find ClassDef
  inheriting from TypedDict, read its annotations)
- The template validator already resolves node references — extending
  it to check field names against a known key set is incremental
- Opt-in by nature: only code nodes with TypedDict annotations benefit;
  plain `dict` annotations work as before with no field validation
- No breaking changes — this is purely additive validation
