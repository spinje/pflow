# Task 112: Pre-execution Type Validation for Literal Parameters

## Description

Add validation that checks literal parameter values against node interface metadata before execution. Currently pflow validates template references (`${node.output}`) but not literal values like `"model": 6` against the expected type (`str`).

## Status
not started

## Priority

medium

## Problem

Today, type mismatches in literal params are only caught at runtime:

```json
{
  "nodes": [
    {
      "id": "test-llm",
      "type": "llm",
      "params": {
        "prompt": "Hello world",
        "model": 6
      }
    }
  ],
  "edges": []
}
```

**Tested behavior (January 2026):**
```
$ pflow test-type-validation.json

❌ Workflow execution failed

Error 1 at node 'test-llm':
  Category: execution_failure
  Message: LLM call failed after 3 attempts. Model: 6. Error: can only concatenate str (not "int") to str
```

The workflow started executing before failing. Validation did not catch that `6` is not a valid `str`.

**Expected behavior:**
- Validation catches: "Parameter 'model' expects str, got int (6)"
- Workflow never starts executing
- No runtime errors, no wasted API calls

## Context: Current State of Typing in pflow

Investigation revealed the following about pflow's current validation:

### What IS Validated Today

| Check | Status | Location |
|-------|--------|----------|
| Template path existence (`${node.output}`) | ✅ | `template_validator.py` |
| Template type compatibility | ✅ | `type_checker.py` (Task 84) |
| Nested template paths (`${node.result.data}`) | ✅ | `template_validator.py` |
| Shell command type safety | ✅ | `template_validator.py` |

### What is NOT Validated Today

| Check | Status | Gap |
|-------|--------|-----|
| Literal param types (`"model": 6`) | ❌ | **This task** |
| IR param schema | ❌ | IR has `additionalProperties: True` |
| MCP output structure | ❌ | Most MCP tools return `any` |

### Type Metadata Available But Not Used for Literals

**Built-in nodes** have rich interface metadata from docstrings:
```python
# From llm.py
"""
Interface:
- Params: prompt: str  # Text prompt to send to model
- Params: model: str  # Model to use (optional)
- Params: temperature: float  # Sampling temperature (optional)
...
"""
```

**MCP tools** have JSON Schema for inputs (captured during registration):
- `src/pflow/mcp/registrar.py:208-257` — registers MCP tools with schema
- `src/pflow/mcp/discovery.py:295-333` — converts JSON Schema to pflow params
- Type mapping: `string` → `str`, `integer` → `int`, `number` → `float`, etc.

**The gap:** This metadata exists but is only used for template validation, not literal param validation.

### IR Schema Allows Anything

From `src/pflow/core/ir_schema.py`:
```python
"params": {
    "type": "object",
    "description": "Parameters for node behavior",
    "additionalProperties": True  # NO TYPE CONSTRAINTS
}
```

The JSON schema itself doesn't enforce types. Validation must happen at compile time.

## Solution

Extend the validation pipeline to check literal param values against node interface metadata.

### Investigation Needed

Before implementing, investigate:

1. **Where does param validation currently happen?**
   - `src/pflow/runtime/compiler.py` — `compile_ir_to_flow()`
   - `src/pflow/core/workflow_validator.py` — validation pipeline
   - Find the right insertion point

2. **How to get interface metadata for a node type?**
   - `registry.get_node_metadata(node_type)` — returns interface info
   - Check what format the metadata is in
   - See `src/pflow/registry/metadata_extractor.py` for parsing

3. **How does template type checking work?**
   - `src/pflow/runtime/type_checker.py` — existing type checking logic
   - Has compatibility matrix (str ↔ dict/list, int → float, etc.)
   - May be reusable for literal checking

4. **MCP tool schema access:**
   - How are MCP tool schemas stored in registry?
   - `src/pflow/mcp/registrar.py` — registration logic
   - Need to validate MCP params against JSON Schema

5. **What about optional params?**
   - If param not provided, don't error (it's optional)
   - Only validate params that ARE provided

### Implementation Approach

1. During validation/compilation, for each node:
   - Get node interface metadata from registry
   - For each literal param value (not a template):
     - Check if param name exists in interface
     - Check if value type matches expected type
     - Use existing type compatibility rules

2. Error format:
   ```
   Validation error at node 'test-llm':
     Parameter 'model' expects type 'str', got 'int' (value: 6)
   ```

3. Type compatibility rules (from `type_checker.py`):
   - Bidirectional JSON: `str` ↔ `dict`/`list` (auto-parse)
   - Numeric widening: `int` → `float` → `str`
   - Universal `any`: compatible with all types

## Design Decisions

- **Scope: literal params only** — Template validation already exists (Task 84)
- **Use existing metadata** — Don't create new schema, use interface metadata
- **Strictness: error, not warning** — Invalid types should fail validation
- **Follow existing patterns** — Extend template_validator or type_checker

## Open Questions

1. **MCP output validation** — Should we validate MCP outputs against `outputSchema` when available? This would be runtime (after tool runs), not pre-execution. Probably separate task.

2. **Unknown params** — Should validation warn about params not in interface? Currently anything is allowed.

3. **Enum validation** — Some params have enum constraints (e.g., `state: open|closed|all`). Should we validate enum values?

## Dependencies

None — builds on existing infrastructure.

## Key Files to Read

Before starting, read these files to understand current validation:

```
src/pflow/runtime/compiler.py          # Where compilation happens
src/pflow/runtime/type_checker.py      # Existing type checking logic
src/pflow/runtime/template_validator.py # Template validation (pattern to follow)
src/pflow/core/workflow_validator.py   # Validation pipeline
src/pflow/registry/metadata_extractor.py # How interface metadata is parsed
src/pflow/mcp/registrar.py             # How MCP tools are registered with schemas
```

## Verification

1. **Literal type mismatch caught:**
   ```json
   {"type": "llm", "params": {"prompt": "Hi", "model": 6}}
   ```
   → Validation error: "Parameter 'model' expects str, got int"

2. **Correct types pass:**
   ```json
   {"type": "llm", "params": {"prompt": "Hi", "model": "gpt-4"}}
   ```
   → Validation passes

3. **Various type mismatches:**
   - `int` where `str` expected → error
   - `str` where `int` expected → error (unless numeric string per compat rules)
   - `dict` where `str` expected → error (unless JSON compat applies)

4. **MCP tools validated:**
   - MCP tool params checked against JSON Schema

5. **Optional params:**
   - Missing optional param → no error
   - Provided optional param with wrong type → error

6. **Existing workflows unaffected:**
   - All current tests pass
   - No false positives
