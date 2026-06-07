# Task 120: Strict Input Type Validation

## Description

Add strict validation in `prepare_inputs()` that fails fast when CLI-provided values cannot be coerced to their declared types, giving users immediate actionable feedback instead of deferring errors to downstream code nodes.

> **Sibling checkpoint (cross-ref added 2026-06-07).** This task and **Task 112 (Pre-execution Type Validation for Literal Parameters)** are two halves of the same idea — "type-check a provided value against its declared type before execution, fail fast with an actionable message" — applied at **two different boundaries**:
> - **This task (120):** *workflow `## Inputs`* (caller-supplied via CLI/stdin) checked against *declared input types*. Lives in `prepare_inputs()` (`src/pflow/runtime/compilation/ir_preparation.py`), which already collects errors and has the declared types.
> - **Task 112:** *node `params`* (author-written, inside the workflow) checked against *node interface metadata*. Lives in the compile/validation pipeline.
>
> They are **not duplicates** (distinct boundary + source of truth) but they **must share one type-compatibility primitive and one error format**. The compatibility matrix already exists in `src/pflow/runtime/template_validation/type_checker.py` (Task 84). **Reuse it instead of hand-rolling a second table** (see the corrected Implementation Notes below). See Task 112's "Sibling checkpoint" note for the symmetric pointer.

> **Stale notes corrected 2026-06-07 (post-Task 154).** Task 154 (Type Vocabulary Coherence, done 2026-04-17) shrank the `## Inputs`/`## Outputs` `type:` vocabulary to **seven canonical JSON-Schema names only** (`string`, `integer`, `number`, `boolean`, `object`, `array`, `any`) and **removed the Python aliases** (`str`, `int`, `float`, `dict`, `list`). The original `TYPE_CHECKS` map and `_normalize_type` references below predate 154 and list those deleted aliases — they are illustrative-but-stale. Implement against the canonical-only vocabulary and reuse `type_checker.py` rather than the snippet's bespoke map. (`_normalize_type` does not exist in the codebase.)

## Status
not started

## Priority

low

## Problem

When type coercion fails (e.g., `enabled="maybe"` for a boolean input), the current behavior:
1. Logs a warning
2. Passes the original value through unchanged
3. Code node type checking eventually fails with "Input 'enabled' expects bool but received str"

This creates a confusing user experience:
- User runs workflow → input validation passes → execution starts → code node fails
- The error message at the code node level lacks context about what valid values were expected
- Debugging requires tracing back to figure out that "maybe" was invalid for boolean

## Solution

Add a validation step after coercion that checks if the result type matches the declared type:
1. After `coerce_input_to_declared_type()` returns, check if result type matches expected
2. If mismatch (coercion failed), add error to `prepare_inputs()` errors list
3. Return clear error message: "Cannot coerce 'maybe' to boolean for input 'enabled'. Valid values: true, false, 1, 0, yes, no"

This aligns with pflow's principles:
- "Ambiguity is a STOP signal"
- "Validate at system boundaries" — CLI input IS a system boundary

## Design Decisions

- **Fail fast, not lenient**: Originally documented as "lenient coercion" but strict validation better matches pflow's philosophy
- **Validation in `prepare_inputs()`**: This is the right place since it already collects errors and has access to declared types
- **Clear error messages**: Include the invalid value, expected type, and valid options where applicable (e.g., boolean valid values)

## Dependencies

None. This builds on the type coercion infrastructure added in the numeric string coercion bug fix (PR #84).

## Implementation Notes

Type checking after coercion:
```python
# ⚠ STALE (pre-Task 154) — see "Stale notes corrected" at top of file.
# The Python aliases ("str", "int", "float", "dict", "list") were REMOVED from
# the input vocabulary by Task 154. Use the 7 canonical JSON-Schema names only,
# and prefer reusing template_validation/type_checker.py over this bespoke map.
# Map declared types to expected Python types
TYPE_CHECKS = {
    "string": str, "str": str,
    "integer": int, "int": int,
    "number": (int, float), "float": (int, float),
    "boolean": bool, "bool": bool,
    "object": dict, "dict": dict,
    "array": list, "list": list,
}

# After coercion, validate result type
expected_types = TYPE_CHECKS.get(_normalize_type(declared_type))
if expected_types and not isinstance(coerced_value, expected_types):
    errors.append((
        f"Cannot coerce '{provided_value}' to {declared_type} for input '{input_name}'",
        f"inputs.{input_name}",
        _get_valid_values_hint(declared_type),  # e.g., "Valid boolean values: true, false, 1, 0, yes, no"
    ))
```

Consider helpful hints for each type:
- boolean: "Valid values: true, false, 1, 0, yes, no"
- integer: "Value must be a valid integer"
- number: "Value must be a valid number"
- object: "Value must be valid JSON object"
- array: "Value must be valid JSON array"

## Verification

Test scenarios:
- `enabled="maybe"` with `type: boolean` → clear error at input validation
- `count="abc"` with `type: integer` → clear error at input validation
- `data="not json"` with `type: object` → clear error at input validation
- Valid values still work (no regression)
- Error messages include the invalid value and valid options

Acceptance criteria:
- Invalid inputs fail at `prepare_inputs()`, not at code node execution
- Error messages are actionable (tell user what's valid)
- Existing workflows with valid inputs continue to work
