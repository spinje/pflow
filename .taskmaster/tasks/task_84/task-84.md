# Task 84: Implement Schema-Aware Type Checking for Template Variables

## Description
Create compile-time type validation that catches type mismatches in template variables before workflow execution, preventing runtime errors from dict→str mismatches and other type incompatibilities. This addresses the bug where dict values passed to string parameters cause cryptic errors in MCP tools and external APIs.

## Status
done

## Completed
2025-10-20

## Dependencies
None

## Priority
high

## Details

The Schema-Aware Type Checking system validates that template variable types match expected parameter types at **compile-time** rather than runtime, providing clear, actionable error messages with suggestions.

### Problem Statement

Currently, type mismatches in template variables only surface at runtime:

**Example Bug**:
```json
{
  "nodes": [
    {"id": "llm", "type": "llm", "params": {"prompt": "Return JSON"}},
    {"id": "slack", "type": "mcp-slack-SEND_MESSAGE", "params": {
      "markdown_text": "${llm.response}"  // dict → str mismatch
    }}
  ]
}
```

**Runtime Error** (cryptic):
```
Error: MCP tool failed: Input should be a valid string
[type=string_type, input_value={'message': 'hello'}, input_type=dict]
```

This causes:
1. Errors discovered too late (after workflow starts)
2. Cryptic error messages from downstream systems
3. Error cascades with literal template strings in external systems
4. Trial-and-error for AI agents building workflows

### Solution Architecture

#### 1. Type Compatibility Matrix (`type_checker.py`)

Comprehensive type compatibility rules with alias support:

**Core Rules**:
- `any` → anything (universal type)
- `int` → `int`, `float`, `number` (widening allowed)
- `bool` → `bool`, `str` (can stringify)
- `dict` ↛ `str` (the bug we're fixing!)

**Type Aliases**:
- `str` / `string`
- `int` / `integer`
- `dict` / `object`
- `list` / `array`
- `number` (generic numeric accepting int or float)

**Union Type Handling**:
- Source union: ALL types must be compatible with target
- Target union: Source must match ANY type in union
- Example: `dict|str` → `str` fails (dict incompatible)

#### 2. Template Type Inference

Infer types from workflow structure and registry metadata:

**Capabilities**:
- Workflow input type lookup: `${api_key}` → `string`
- Node output type lookup: `${http.status_code}` → `int`
- Nested structure traversal: `${issue.data.author.login}` → `str`
- Array access: `${items[0].name}` → `str`
- Namespaced outputs: Handles both `node.output` and direct output formats

**Type Sources**:
1. Workflow `inputs` declarations
2. Node output metadata from registry (Enhanced Interface Format)
3. Nested structure metadata for complex types

#### 3. Enhanced Error Messages

Show **actual available fields** instead of generic suggestions:

**Generic Suggestion (Before)**:
```
💡 Suggestion: Access a specific field (e.g., ${node.data.message})
                                                         ^^^^^^^^
                                               (field doesn't exist!)
```

**Specific Suggestions (After)**:
```
💡 Available fields with correct type:
   - ${node.data.author.id}
   - ${node.data.author.login}
   - ${node.data.author.name}
```

**How It Works**:
- Traverses nested structure metadata from registry
- Filters fields by expected type (shows only `str` fields when `str` expected)
- Shows up to 5 suggestions (not overwhelming)
- Falls back to generic suggestion if structure unavailable

#### 4. Integration with Template Validator

Integrated into existing `template_validator.py` validation pipeline:

**Execution Flow**:
1. Syntax validation (malformed templates)
2. Path validation (template exists in outputs)
3. **Type validation** (NEW - types compatible)
4. Return combined errors and warnings

**When Type Checking Runs**:
- After path validation (path must exist first)
- Before workflow compilation
- Part of `validate_workflow_templates()`

**What Gets Validated**:
- ✅ Template variable types vs parameter expected types
- ✅ Nested field access (`${node.data.field}`)
- ✅ Array access (`${items[0].name}`)
- ✅ Workflow inputs (declared types)
- ✅ Union types (`dict|str`)

**What Gets Skipped** (by design):
- ⏭️ MCP nodes with `any` output (dynamic schemas)
- ⏭️ LLM nodes (output type is `any`)
- ⏭️ Parameters with type `any` (accepts anything)

### Key Design Decisions (MVP Approach)

1. **Simple, Clean Architecture**
   - Single new file: `type_checker.py` (221 lines)
   - Minimal changes to existing validator (+115 lines)
   - No breaking changes to runtime

2. **Type Alias Support**
   - Handles both `str` and `string` to avoid false positives
   - Prevents workflows from failing due to naming conventions
   - `number` accepts both `int` and `float` (generic numeric)

3. **Conservative Compatibility**
   - `any` type is universally compatible (allows MCP nodes)
   - Union types use "any match" for targets (permissive)
   - Clear matrix for basic types (predictable behavior)

4. **Error Message Quality**
   - Context-aware suggestions (shows actual available fields)
   - Traverses nested structures to find relevant fields
   - Bounded output (max 5 suggestions)
   - Falls back gracefully when structure unavailable

5. **Performance**
   - <5ms validation overhead (target was <100ms)
   - No caching needed (fast enough as-is)
   - Scales to 50+ node workflows

6. **Backward Compatibility**
   - Zero breaking changes
   - Only adds validation (doesn't change runtime)
   - Existing workflows continue to work
   - New errors catch previously undetected bugs

### Technical Implementation

#### Core Functions (`type_checker.py`)

**`is_type_compatible(source: str, target: str) -> bool`**
- Checks if source type can be used where target type is expected
- Handles union types (both source and target)
- Uses compatibility matrix for basic types
- ~30 lines including comments

**`infer_template_type(template: str, workflow_ir, node_outputs) -> Optional[str]`**
- Infers type of template variable path
- Handles nested paths: `node.output.field`
- Handles array access: `items[0].name`
- Checks workflow inputs first, then node outputs
- Supports both namespaced and direct output formats
- ~70 lines including structure traversal

**`get_parameter_type(node_type: str, param_name: str, registry) -> Optional[str]`**
- Queries registry for parameter expected type
- Uses Enhanced Interface Format metadata
- Returns `None` if parameter not found
- ~20 lines

#### Integration (`template_validator.py`)

**`_validate_template_types(workflow_ir, node_outputs, registry) -> list[str]`**
- Main validation function
- Iterates through all nodes and parameters
- Extracts templates and checks compatibility
- Generates error messages with suggestions
- ~50 lines

**`_generate_type_fix_suggestion(template, node_outputs, expected_type) -> str`**
- Generates context-aware suggestions
- Traverses nested structures to find available fields
- Filters by expected type
- Shows up to 5 relevant suggestions
- ~40 lines including helper function

**`_traverse_to_structure(structure, path) -> Optional[dict]`**
- Helper to navigate nested structure metadata
- Splits path and traverses level by level
- Returns structure at target depth
- ~25 lines

### Real-World Testing

Validated with actual workflow `slack-qa-responder`:
- Found type issue: input `type: "number"` vs parameter expecting `int`
- Fixed by adding `number` type alias compatibility
- All 529 runtime tests continue to pass

### Files Created

1. `src/pflow/runtime/type_checker.py` (221 lines)
   - Type compatibility matrix
   - Type inference engine
   - Parameter type lookup

2. `tests/test_runtime/test_type_checker.py` (286 lines, 25 tests)
   - Type compatibility tests (10 tests)
   - Template type inference tests (11 tests)
   - Parameter lookup tests (4 tests)

3. `tests/test_runtime/test_template_validator_types.py` (216 lines, 9 tests)
   - Integration tests with validator
   - Real workflow scenarios
   - Error message validation

### Files Modified

1. `src/pflow/runtime/template_validator.py` (+115 lines)
   - Imported type checking functions
   - Added `_validate_template_types()` method
   - Added `_generate_type_fix_suggestion()` method
   - Added `_traverse_to_structure()` helper
   - Integrated into validation pipeline

### Documentation Created

**Implementation Planning**:
- `scratchpads/fix-3-implementation-plan/IMPLEMENTATION_COMPLETE.md` - Full report
- `scratchpads/fix-3-implementation-plan/IMPLEMENTATION_PLAN.md` - Technical spec
- `scratchpads/fix-3-implementation-plan/QUICK_REFERENCE.md` - Quick lookup
- `scratchpads/fix-3-implementation-plan/TASK_CHECKLIST.md` - Task tracking
- `scratchpads/fix-3-implementation-plan/README.md` - Navigation hub

**Research & Analysis**:
- `scratchpads/type-system-investigation/` - Type system deep dive
- `scratchpads/schema-aware-type-checking/` - Feasibility assessment
- `scratchpads/type-handling-bug-investigation/` - Bug analysis
- `scratchpads/template-resolution-investigation/` - Template system analysis

### Integration Points

1. **Registry System**
   - Reads node metadata (Enhanced Interface Format)
   - Extracts parameter types: `interface.params[].type`
   - Extracts output types: `interface.outputs[].type`
   - Uses structure metadata for nested field suggestions

2. **Template Validator**
   - Runs after path validation
   - Before workflow compilation
   - Part of `validate_workflow_templates()` flow

3. **Compiler**
   - Validation runs when `validate=True` (default)
   - Errors prevent compilation
   - No changes to runtime behavior

4. **MCP Server**
   - `workflow_validate` tool now includes type checking
   - Returns type errors in validation results
   - AI agents see improved error messages

## Test Strategy

### Unit Tests (25 tests in `test_type_checker.py`)

**Type Compatibility** (10 tests):
- Exact matches: `str` → `str`
- Universal type: `any` → anything
- Widening: `int` → `float`
- No narrowing: `float` ↛ `int`
- Incompatible: `str` ↛ `int`, `dict` ↛ `str`
- Union sources: All must match
- Union targets: Any must match
- Complex unions: Multiple combinations

**Template Type Inference** (11 tests):
- Simple output: `${node.result}`
- Nested fields: `${node.data.count}`
- Deep nesting: `${node.issue.user.login}`
- Array access: `${items[0].name}`
- Unknown fields: Returns `None`
- `any` type: Returns `"any"`
- Union types: Handles `dict|str`
- Workflow inputs: Type from declarations
- Non-traversable: `int` doesn't allow nested access
- Invalid paths: Just node ID without output
- No namespacing: Old workflow format support

**Parameter Type Lookup** (4 tests):
- Get parameter type from registry
- Return `None` for unknown parameter
- Return `None` for unknown node
- Default to `"any"` when type not specified

### Integration Tests (9 tests in `test_template_validator_types.py`)

**Validation Scenarios**:
- Compatible types pass validation
- Dict → string mismatch detected (original bug!)
- Nested field access with correct type passes
- String → int mismatch detected
- Int → int compatible
- Union type compatibility (dict|str → str fails)
- `any` type skips validation
- Multiple type errors detected simultaneously
- Error message format validation

**Error Message Quality**:
- Contains node ID
- Contains parameter name
- Contains template variable
- Contains inferred type
- Contains expected type
- Contains helpful suggestions
- Shows actual available fields

### End-to-End Testing

**Real Workflow Validation**:
- Tested with `slack-qa-responder` workflow
- Found and fixed `number` → `int` compatibility issue
- Validated with test workflows:
  - `test-dict-to-str.json` (catches mismatch)
  - `test-dict-to-str-fixed.json` (passes)
  - `test-int-to-str.json` (compatible)

**Regression Testing**:
- All 529 existing runtime tests pass
- Zero breaking changes
- Backward compatible

### Test Coverage

- **Type checker**: 100% coverage
- **Template validator changes**: 95% coverage
- **Integration tests**: 100% scenarios covered
- **Overall new code**: 98% coverage

### Performance Testing

**Validation Overhead**:
- Target: <100ms
- Actual: <5ms (20x better than target)
- Tested with workflows up to 50 nodes

**Test Execution**:
- 34 type checking tests: ~0.3s
- All 529 runtime tests: ~1.9s
- No performance degradation

### Test Execution Commands

```bash
# Run type checking tests
uv run pytest tests/test_runtime/test_type_checker.py -v
uv run pytest tests/test_runtime/test_template_validator_types.py -v

# Run with coverage
uv run pytest tests/test_runtime/test_type_checker.py --cov=src/pflow/runtime/type_checker
uv run pytest tests/test_runtime/test_template_validator_types.py --cov=src/pflow/runtime/template_validator

# Run all runtime tests
uv run pytest tests/test_runtime/ -q

# Run full test suite
make test
```

### Success Criteria (All Met)

**Functional**:
- ✅ Detect dict → str mismatches
- ✅ Detect str → int mismatches
- ✅ Handle union types correctly
- ✅ Support nested structures
- ✅ Clear, actionable error messages
- ✅ Show actual available fields in suggestions

**Quality**:
- ✅ 98% test coverage (target: 85%+)
- ✅ 529/529 tests passing (zero regressions)
- ✅ Linter clean (ruff)
- ✅ Type checker clean (mypy)

**Performance**:
- ✅ <5ms overhead (target: <100ms)
- ✅ Scales to 50+ node workflows
