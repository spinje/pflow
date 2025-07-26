## Purpose

Enable workflow reusability by detecting and resolving `$variable` placeholders (with optional path traversal like `$data.field.subfield`) in node parameters at runtime, converting them to string values from planner-extracted parameters and shared store data.

## Functional Rules

1. **R1**: Template variables use format `$identifier` where identifier matches `[a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+)*`
2. **R2**: Templates are detected only in string values within node `params` field
3. **R3**: Resolution context combines shared store (lower priority) and initial_params (higher priority) where initial_params values override shared store keys
4. **R4**: Path traversal splits on `.` and traverses dict keys sequentially, stopping if non-dict encountered
5. **R5**: All resolved values convert to strings using: `None→""`, `""→""`, `0→"0"`, `False→"False"`, `[]→"[]"`, `{}→"{}"`, others via `str()`
6. **R6**: Unresolvable templates remain unchanged in output (e.g., `$missing` stays `$missing`)
7. **R7**: Node wrapping occurs only when node params contain at least one template variable
8. **R8**: Template resolution happens during `_run()` execution, never during compilation
9. **R9**: Wrapped nodes delegate all attributes except `inner_node`, `node_id`, `initial_params`, `template_params`, `static_params` to inner node
10. **R10**: Validation checks all base variables (before first `.`) referenced in templates exist in available parameters
11. **R11**: Validation distinguishes CLI parameters (must exist) from shared store variables (validated at runtime only)
12. **R12**: Compiler raises `ValueError` with message "Template validation failed:" followed by specific errors if validation fails

## Edge Cases & Error Behavior

1. **E1**: Malformed syntax (`$.var`, `$var.`, `$var..field`, `$$var`, lone `$`) → template remains unchanged
2. **E2**: Path traversal on non-dict (`$string_value.field` where string_value="hello") → template remains unchanged
3. **E3**: Null/None in path (`$parent.null_field.child` where null_field=None) → traversal stops, template unchanged
4. **E4**: Multiple templates in single string (`"$var1 and $var2"`) → each resolved independently
5. **E5**: Template as complete value (`"$url"`) vs embedded (`"Video: $url"`) → both resolve identically
6. **E6**: Non-string parameter values → ignored, no template detection attempted
7. **E7**: Missing base variable during validation → error message "Missing required parameter: --{param_name}"
8. **E8**: Circular references → not detected, last write wins in shared store

## Non-Goals & Scope

**Excluded from implementation:**
- Array indexing syntax (`$items.0.name`)
- Expression evaluation (`$count + 1`)
- Method calls (`$name.upper()`)
- Default values (`$var|default`)
- Type preservation (all values become strings)
- Proxy mappings or key renaming
- Compile-time resolution
- `${var}` brace syntax
- Template variables in non-params fields (id, type, edges)

## Integration Points

1. **Compiler (`compile_ir_to_flow`)**:
   - Accepts `initial_params` dict containing planner-extracted values
   - Calls `TemplateValidator.validate_workflow_templates()` before compilation
   - Wraps nodes containing templates with `TemplateAwareNodeWrapper`
   - Propagates validation errors as `ValueError`

2. **Node Execution**:
   - Wrapper intercepts at `_run()` method only
   - Temporarily modifies `inner_node.params` with resolved values
   - Restores original params after execution (though node copy is discarded)

3. **CLI Integration**:
   - Passes planner's `parameter_values` as `initial_params` to compiler
   - Displays validation errors to user before execution

## Performance & Resource Constraints

1. **Resolution complexity**: O(n*m) where n=template string length, m=path depth
2. **Memory**: No caching, stateless resolution per execution
3. **Compilation overhead**: One regex scan per parameter value during node creation

## Test Criteria

**Template Detection & Resolution:**
- T1: Verify `$variable` format detected in string params (R1, R2)
- T2: Verify non-string params ignored (E6)
- T3: Verify path traversal resolves `$data.field.subfield` correctly (R4)
- T4: Verify initial_params override shared store values (R3)
- T5: Verify type conversions match specified rules (R5)
- T6: Verify missing variables remain as templates (R6)
- T7: Verify malformed syntax remains unchanged (E1)
- T8: Verify path traversal stops at non-dict (E2)
- T9: Verify null in path stops traversal (E3)
- T10: Verify multiple templates in one string resolve independently (E4)
- T11: Verify complete vs embedded templates resolve identically (E5)

**Node Wrapping:**
- T12: Verify nodes without templates are not wrapped (R7)
- T13: Verify wrapped nodes delegate attributes correctly (R9)
- T14: Verify resolution happens during `_run()` not compilation (R8)
- T15: Verify original params restored after execution

**Validation:**
- T16: Verify missing CLI parameters cause validation error (R10, R11)
- T17: Verify shared store variables don't cause validation errors (R11)
- T18: Verify validation error format matches specification (R12, E7)
- T19: Verify validation can be skipped with `validate=False` parameter

**Integration:**
- T20: End-to-end test with planner parameters flowing through to execution
- T21: Verify backwards compatibility with non-template workflows
- T22: Verify circular references use last-write-wins behavior (E8)

## Validation & Monitoring

- Validation errors logged with specific parameter names
- Unresolved templates visible in node execution for debugging
- No runtime performance monitoring required for MVP

## Dependencies & Assumptions

**Dependencies:**
- Python 3.8+ for dict traversal and string formatting
- All pflow nodes implement fallback pattern: `value = shared.get("key") or self.params.get("key")`
- Registry provides node classes for instantiation
- Planner provides `parameter_values` dict with extracted values

**Assumptions:**
- Nodes don't modify their own params during execution
- PocketFlow's node copying behavior remains unchanged
- Template syntax `$var` is reserved and not used literally in workflows

## Open Questions

- None

## Glossary

- **initial_params**: Parameters extracted by planner from natural language (e.g., `{"issue_number": "1234"}` from "fix issue 1234")
- **template variable**: Placeholder in format `$identifier` that gets replaced with actual values at runtime
- **path traversal**: Dot-notation access to nested data (e.g., `$data.field.subfield`)
- **fallback pattern**: Node implementation pattern where values are read from shared store first, then params

## Epistemic Appendix

### Assumptions & Unknowns

1. **Assumption**: All existing pflow nodes implement the fallback pattern consistently. If false, some nodes may not work with template resolution.
2. **Assumption**: Planner will always provide string values in parameter_values dict. If false, type conversion rules may need adjustment.
3. **Unknown**: Exact behavior when very deep paths (>10 levels) are used. Assumed to work but not explicitly tested.

### Conflicts & Resolutions

1. **Conflict**: Document states fallback pattern is in "EVERY node's prep() method" but this is a pflow convention, not PocketFlow framework feature.
   - **Resolution**: Acknowledged as pflow-specific pattern, doesn't affect wrapper implementation.

### Decision Log / Tradeoffs

1. **String conversion vs type preservation**:
   - **Options**: Preserve types with complex serialization vs convert everything to strings
   - **Tradeoff**: Simplicity and predictability vs type fidelity
   - **Decision**: Convert to strings (MVP simplicity, covers 90% of use cases)

2. **Validation timing**:
   - **Options**: Validate at compile time vs runtime vs both
   - **Tradeoff**: Early error detection vs implementation complexity
   - **Decision**: Validate before execution (fail fast) with option to skip

3. **Missing variable behavior**:
   - **Options**: Raise error vs use empty string vs leave template unchanged
   - **Tradeoff**: Debugging visibility vs silent failures
   - **Decision**: Leave unchanged (aids debugging, matches planner validation)

### Epistemic Audit

1. **Which assumptions did I make that weren't explicit?**
   - That node params are always dicts (not None or other types)
   - That the shared store is always a dict throughout execution

2. **What would break if they're wrong?**
   - Wrapper's `set_params()` would fail if params is None
   - Resolution would fail if shared is not a dict

3. **Did I optimize elegance over robustness?**
   - No, chose explicit error handling and simple string conversion over elegant type preservation

4. **Did every Rule map to at least one Test (and vice versa)?**
   - Yes, verified mapping: R1→T1, R2→T1,T2, R3→T4, R4→T3, R5→T5, R6→T6, R7→T12, R8→T14, R9→T13, R10→T16, R11→T16,T17, R12→T18

5. **What ripple effects or invariants might this touch?**
   - Node execution timing (params modified during `_run()`)
   - Error messages shown to users (validation errors)
   - Workflow portability (templates enable reuse)

6. **What remains uncertain, and how confident am I?**
   - Performance impact on workflows with many templates (80% confident it's negligible)
   - Edge cases with extremely nested data structures (70% confident current approach handles them)
   - Integration with future BatchFlow support (60% confident current design is compatible)
