# Fix 3: Quick Reference Guide

## TL;DR

**What**: Add compile-time type checking for template variables
**Why**: Catch type mismatches before runtime (dict → str, str → int, etc.)
**How**: ~400 lines of type compatibility logic integrated into existing validation
**When**: 3-5 days of implementation

---

## Key Files

### New File
- `src/pflow/runtime/type_checker.py` (~300 lines)
  - `is_type_compatible(source, target) -> bool`
  - `infer_template_type(template, ...) -> Optional[str]`
  - `get_parameter_type(node_type, param, ...) -> Optional[str]`

### Modified Files
- `src/pflow/runtime/template_validator.py` (+100 lines)
  - Add `_validate_template_types()` method
  - Call from `validate_workflow_templates()`

---

## Type Compatibility Rules

```
any      → anything          ✅
str      → str, any          ✅
int      → int, float, any   ✅
float    → float, any        ✅
bool     → bool, str, any    ✅
dict     → dict, any         ✅
list     → list, any         ✅

str      → int               ❌
dict     → str               ❌
list     → dict              ❌
```

### Union Types

**Source Union** (all types must be compatible):
- `dict|str` → `str`: ❌ (dict not compatible with str)
- `str|any` → `str`: ✅ (both str and any compatible)

**Target Union** (any type must be compatible):
- `str` → `str|int`: ✅ (str matches str in union)
- `dict` → `str|int`: ❌ (dict matches neither)

---

## Implementation Phases

### Phase 1: Core Logic (2 days)
- [ ] Type compatibility matrix
- [ ] Template type inference
- [ ] Parameter type lookup
- [ ] Unit tests (50 tests)

### Phase 2: Integration (1 day)
- [ ] Add `_validate_template_types()` to validator
- [ ] Wire into validation pipeline
- [ ] Integration tests (20 tests)

### Phase 3: Testing & Refinement (1-2 days)
- [ ] Comprehensive test suite
- [ ] Real-world validation
- [ ] Error message refinement
- [ ] Documentation

---

## Example Output

**Before**:
```
Error: MCP tool failed: Input should be a valid string [type=string_type, input_value={'message': 'hello'}, input_type=dict]
```

**After**:
```
❌ Type mismatch in node 'slack' parameter 'markdown_text':
   Template ${llm.response} has type 'dict'
   But parameter 'markdown_text' expects type 'str'

💡 Suggestion: Access a specific field instead:
   - ${llm.response.message}
   - ${llm.response.text}
   Or serialize to JSON
```

---

## Testing Checklist

### Unit Tests (~50 tests)
- [x] Type compatibility: exact matches
- [x] Type compatibility: widening (int → float)
- [x] Type compatibility: any type
- [x] Union types: source unions
- [x] Union types: target unions
- [x] Template type inference: simple outputs
- [x] Template type inference: nested structures
- [x] Template type inference: array access
- [x] Parameter type lookup

### Integration Tests (~20 tests)
- [ ] Simple type mismatches detected
- [ ] Compatible types pass
- [ ] Union types handled correctly
- [ ] MCP nodes with `any` outputs
- [ ] Error messages formatted correctly
- [ ] Suggestions generated

### E2E Tests (~10 tests)
- [ ] Real workflow validation
- [ ] GitHub PR analyzer workflow
- [ ] Slack notification workflow
- [ ] HTTP API chaining
- [ ] LLM JSON responses

### Performance Tests
- [ ] <100ms overhead for type checking
- [ ] Scales to 50+ node workflows

---

## Risk Mitigation

| Risk | Mitigation | Status |
|------|------------|--------|
| False positives | Test against all examples | Pending |
| Union type confusion | Clear documentation + examples | Pending |
| MCP dynamic schemas | Warnings not errors for `any` | Planned |
| Performance overhead | Benchmark + caching | Planned |

---

## Success Metrics

- ✅ 90%+ type mismatch detection rate
- ✅ Zero false positives on valid workflows
- ✅ Clear, actionable error messages
- ✅ <100ms validation overhead

---

## Quick Start

1. **Read**: Full implementation plan (`IMPLEMENTATION_PLAN.md`)
2. **Create**: Branch for implementation
3. **Implement**: Phase 1 - Core type logic
4. **Test**: Unit tests + integration tests
5. **Integrate**: Phase 2 - Wire into validator
6. **Validate**: Phase 3 - Real-world testing
7. **Ship**: Merge to main

---

## Questions?

- **Q**: Will this break existing workflows?
- **A**: No - only adds validation, doesn't change runtime behavior

- **Q**: What about MCP nodes with unknown outputs?
- **A**: Type `any` allows everything, warnings issued for runtime validation

- **Q**: How long will this take?
- **A**: 3-5 development days

- **Q**: Can we do this incrementally?
- **A**: Yes - start with warnings only, then convert to errors

---

**Status**: Ready for implementation 🚀
