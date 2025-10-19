# Fix 3: Schema-Aware Type Checking - Implementation Plan

**Status**: ✅ Planning Complete - Ready for Implementation
**Created**: 2025-10-20
**Estimated Effort**: 3-5 development days
**Complexity**: Medium
**Risk**: Low

---

## Quick Navigation

📋 **Start Here**:
- [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) - TL;DR and quick facts
- [TASK_CHECKLIST.md](./TASK_CHECKLIST.md) - Detailed implementation checklist

📚 **Deep Dive**:
- [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) - Complete technical specification

🔍 **Background Research**:
- [../type-system-investigation/](../type-system-investigation/) - Type system analysis
- [../type-handling-bug-investigation/](../type-handling-bug-investigation/) - Original bug findings

---

## Problem Statement

Template variables in pflow workflows can resolve to types incompatible with their target parameters, causing:
1. **Runtime failures** instead of compile-time detection
2. **Cryptic error messages** from downstream systems (MCP, APIs)
3. **Error cascades** where literal template strings leak into external systems

**Example of the bug**:
```json
{
  "nodes": [
    {"id": "llm", "type": "llm", "params": {"prompt": "Return JSON"}},
    {"id": "slack", "type": "mcp-slack-SEND_MESSAGE", "params": {
      "markdown_text": "${llm.response}"  // ❌ dict resolved, but str expected
    }}
  ]
}
```

**Current behavior**: Runtime error during MCP execution
**Desired behavior**: Compile-time type mismatch error with clear suggestion

---

## Solution Overview

Implement **compile-time type checking** that validates template variable types match expected parameter types.

### What We're Building

**Core Components** (~400 lines of code):
1. **Type Compatibility Logic** - Rules for matching source → target types
2. **Template Type Inference** - Determine type of `${node.output.field}`
3. **Parameter Type Lookup** - Get expected type from registry metadata
4. **Type Validation Integration** - Wire into existing validation pipeline

**Integration Point**: `src/pflow/runtime/template_validator.py` (existing)

**New File**: `src/pflow/runtime/type_checker.py`

### Expected Output

**Before Fix**:
```
Error: MCP tool failed: Input should be a valid string
[type=string_type, input_value={'message': 'hello'}, input_type=dict]
```

**After Fix**:
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

## Documents in This Folder

### 1. QUICK_REFERENCE.md
**Purpose**: Fast lookup for common questions
**Contents**:
- TL;DR summary
- Key files to modify
- Type compatibility rules
- Phase breakdown
- Example outputs

**When to use**: Quick refresher, reference during implementation

---

### 2. TASK_CHECKLIST.md
**Purpose**: Step-by-step implementation guide
**Contents**:
- Detailed task breakdown by phase
- Acceptance criteria for each task
- Test requirements
- Commands to run
- Checkbox format for tracking progress

**When to use**: Daily implementation tracking, ensuring nothing is missed

---

### 3. IMPLEMENTATION_PLAN.md
**Purpose**: Complete technical specification
**Contents**:
- Executive summary
- Architecture design
- 3-phase implementation plan
- Complete code examples
- Integration strategy
- Testing strategy (unit, integration, E2E)
- Risk mitigation
- Timeline estimates
- Success criteria
- Real-world examples

**When to use**: Deep understanding, architectural questions, design decisions

---

## Implementation Roadmap

### Phase 1: Core Type Logic (2 days)
Build the foundational type checking functions:
- Type compatibility matrix
- Template type inference engine
- Parameter type lookup
- 50+ unit tests

**Output**: `src/pflow/runtime/type_checker.py` (~300 lines)

---

### Phase 2: Integration (1 day)
Wire type checking into existing validation:
- Add `_validate_template_types()` to validator
- Integrate with validation pipeline
- 20+ integration tests

**Output**: Modified `src/pflow/runtime/template_validator.py` (+100 lines)

---

### Phase 3: Testing & Refinement (1-2 days)
Comprehensive validation and polish:
- Edge case tests
- Real-world workflow validation
- Error message refinement
- Performance benchmarking

**Output**: Production-ready type checking system

---

## Key Design Decisions

### 1. Leverage Existing Infrastructure ✅
- Use Enhanced Interface Format type metadata (already in registry)
- Integrate into existing `template_validator.py` (no new validation layer)
- Reuse `TemplateResolver` for template extraction

### 2. Conservative Compatibility Rules ✅
- `any` type is universally compatible (allows MCP nodes)
- Union types use "any match" for targets (permissive)
- Clear matrix for basic types (predictable)

### 3. Warnings vs Errors 🔄
- **Initially**: All type mismatches are warnings
- **After validation**: Convert obvious mismatches to errors
- **Escape hatch**: Users can set parameter type to `any`

### 4. Clear Error Messages ✅
- Show both inferred and expected types
- Provide actionable suggestions
- Include context (node ID, parameter name)

---

## Success Metrics

**Functional**:
- ✅ 90%+ type mismatch detection rate
- ✅ Zero false positives on valid workflows
- ✅ Clear, actionable error messages

**Performance**:
- ✅ <100ms validation overhead
- ✅ Scales to 50+ node workflows

**Quality**:
- ✅ 85%+ test coverage
- ✅ All existing tests pass (no regressions)

---

## Risk Assessment

**Overall Risk**: 🟢 Low

### Why Low Risk?

1. **No architectural changes** - Pure addition to validation
2. **Strong foundation** - Type metadata already exists
3. **Isolated implementation** - Single new file, minimal changes
4. **Backward compatible** - Only adds validation, doesn't change runtime
5. **Comprehensive testing** - 80+ tests planned

### Mitigation Strategies

| Risk | Mitigation | Status |
|------|------------|--------|
| False positives | Test against all examples first | Planned |
| Union type complexity | Clear rules + extensive tests | Documented |
| MCP dynamic schemas | `any` type + warnings | Designed |
| Performance overhead | Benchmarking + caching | Planned |

---

## Getting Started

### Step 1: Read the Plan
1. Start with [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) (5 minutes)
2. Review [TASK_CHECKLIST.md](./TASK_CHECKLIST.md) (10 minutes)
3. Deep dive into [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) (30 minutes)

### Step 2: Prepare Environment
```bash
cd /Users/andfal/projects/pflow
git checkout -b feat/schema-aware-type-checking
```

### Step 3: Begin Implementation
```bash
# Create the new file
touch src/pflow/runtime/type_checker.py

# Create test file
touch tests/test_runtime/test_type_checker.py

# Follow TASK_CHECKLIST.md Phase 1, Task 1.1
```

### Step 4: Iterate
- Follow checklist sequentially
- Run tests after each task
- Commit after each phase
- Review and refine

---

## Dependencies

### Internal (All Exist ✅)
- Registry system with type metadata
- Template resolver
- Template validator
- Enhanced Interface Format

### External
- None

---

## Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| Phase 1 | 2 days | Core type logic + unit tests |
| Phase 2 | 1 day | Integration + integration tests |
| Phase 3 | 1-2 days | E2E tests + refinement |
| **Total** | **3-5 days** | Production-ready type checking |

---

## Questions & Answers

**Q**: Will this break existing workflows?
**A**: No - only adds validation, doesn't change runtime behavior. Backward compatible.

**Q**: What about MCP nodes with unknown output types?
**A**: Type `any` allows everything. Warnings issued, not errors.

**Q**: How do we handle false positives?
**A**: Start with warnings only, extensive testing, user feedback loop.

**Q**: What's the performance impact?
**A**: Target <100ms overhead. Will benchmark and optimize if needed.

**Q**: Can we do this incrementally?
**A**: Yes - Phase 1 can ship independently with warnings only.

---

## Related Research

### Background Investigation Documents

1. **Type System Deep Dive** (`../type-system-investigation/`)
   - Complete analysis of pflow's type system
   - Registry format and metadata extraction
   - Template resolution mechanics
   - Gap analysis (what's missing)

2. **Bug Investigation** (`../type-handling-bug-investigation/`)
   - Root cause analysis of original bug
   - Error cascade documentation
   - Why literal templates appear in Slack
   - Proof that template substitution works

3. **Feasibility Assessment** (`../schema-aware-type-checking/`)
   - Initial feasibility study
   - Infrastructure inventory
   - Complexity estimate
   - Risk assessment

---

## Status & Next Steps

**Current Status**: ✅ Planning Complete

**Ready for**:
- Implementation kickoff
- Team review (if applicable)
- Timeline confirmation

**Next Action**: Begin Phase 1, Task 1.1 - Type Compatibility Matrix

**Owner**: TBD

**Started**: Not yet

**Completed**: Not yet

---

## Document History

| Date | Version | Changes |
|------|---------|---------|
| 2025-10-20 | 1.0 | Initial comprehensive plan created |

---

**Ready to implement!** 🚀

For questions or clarifications, refer to the detailed [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md).
