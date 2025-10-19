# Schema-Aware Type Checking - Executive Summary

## Quick Answer

**YES, it's feasible - MEDIUM complexity, 2-3 weeks for complete implementation.**

## What Already Exists

✅ **Rich type information in registry** - Nodes declare parameter types in docstrings
✅ **Template validator infrastructure** - Already validates paths and existence
✅ **Registry access at validation time** - Type metadata available when needed
✅ **Enhanced error message system** - Can provide actionable suggestions
✅ **Nested structure support** - Can validate `${node.data.field[0].name}` paths

## What Needs to Be Built

❌ **Template usage tracking** - Map templates to where they're consumed
❌ **Type compatibility logic** - Define when types are compatible
❌ **Integration with validator** - Extend existing `_validate_template_path()`
❌ **Error formatting** - Create clear type mismatch messages

## Example of What It Would Catch

```python
# Before (Runtime Error):
workflow = {
    "nodes": [
        {"id": "http", "type": "http"},
        {"id": "llm", "type": "llm", "params": {
            "model": "${http.status_code}"  # int used as string!
        }}
    ]
}
# Runtime: Fails when LLM API rejects integer model name

# After (Validation Error):
ValidationError: Type mismatch for template ${http.status_code}

  Source: http outputs type 'int'
  Target: llm.model expects type 'str'

  Suggestion: Status code is numeric - did you mean to use it in a message?
```

## Recommended Implementation

**3-week phased approach:**

**Week 1 - Foundation:**
- Type compatibility checker (exact match + unions + `any`)
- Template usage map builder
- MCP node handling (graceful degradation for `any` types)

**Week 2 - Integration:**
- Extend `TemplateValidator._validate_template_path()`
- Enhanced error messages with type information
- Add `TypeMismatchWarning` for runtime-validated types

**Week 3 - Testing & Refinement:**
- Comprehensive test suite
- Real-world workflow validation
- Documentation updates

## Key Design Decisions

1. **Warnings First**: Start with warnings, not errors (avoid breaking existing workflows)
2. **MCP Special Case**: Emit warnings for MCP nodes with `any` types (can't validate at compile time)
3. **Two-Phase**: Compile-time validation (primary) + optional runtime checks (safety net)
4. **Graceful Degradation**: If type info missing, fall back to existence checking

## Integration Point

```python
# In src/pflow/runtime/template_validator.py

def validate_workflow_templates(workflow_ir, available_params, registry):
    """Existing function - add type checking here."""

    # ... existing path validation ...

    # NEW: Type checking
    type_errors, type_warnings = _validate_template_types(
        workflow_ir, node_outputs, registry
    )
    errors.extend(type_errors)
    warnings.extend(type_warnings)

    return (errors, warnings)
```

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| False positives | High | Start with warnings only |
| MCP dynamic schemas | Medium | Special handling for `any` types |
| Performance overhead | Low | Cache usage map per workflow |
| Breaking existing workflows | High | Opt-in initially, graduate to errors |

## Success Metrics

- ✅ Zero false positives on existing test workflows
- ✅ Catches all definite type mismatches (int → str)
- ✅ Warnings for runtime-dependent types (`any`)
- ✅ Clear error messages with fix suggestions
- ✅ <100ms validation overhead per workflow

## Alternative Approaches Considered

1. **Runtime-only validation** - Too late, errors during execution
2. **Template resolver modification** - Wrong abstraction layer
3. **Node wrapper checks** - Per-node overhead, too granular
4. **Skip entirely** - Misses valuable error catching opportunity

## Recommendation

**Proceed with 3-week implementation.** The infrastructure exists, the value is clear, and the complexity is manageable. This is a natural extension of the existing validation system that will catch real bugs early.

See `feasibility-assessment.md` for detailed analysis.
