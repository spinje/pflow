# Auto-Parse JSON Strings Implementation Progress Log

## 2026-01-01 09:00 - Starting Implementation

Reading the feature request in `scratchpads/feature-request-json-string-nested-access.md`. The problem is clear: `${node.stdout.field}` fails when `stdout` is a JSON string like `'{"field": "value"}'`.

Three options were proposed:
- **Option A**: Auto-parse during path traversal (recommended)
- **Option B**: Explicit `${json(x).field}` function
- **Option C**: New `stdout_json` output on shell nodes

User prefers Option A. Makes sense - it's intuitive and matches existing auto-parse behavior.

---

## 2026-01-01 09:15 - Verifying Assumptions (Critical Step!)

Before implementing, launched 8 parallel pflow-codebase-searcher agents to verify ALL assumptions. This was critical.

### Key Findings:

1. **Existing auto-parse is REAL but different**
   - Located in `node_wrapper.py:745-780`
   - Works at TARGET side (when param expects dict/list)
   - Our change is SOURCE side (during path traversal)
   - **Insight**: These are different code paths in different files!

2. **Shell node does NOT strip whitespace**
   - Tests explicitly call `.strip()` on stdout
   - **Insight**: We MUST strip before JSON detection

3. **Array access syntax already works**
   - `${items[0].name}` fully supported
   - No additional work needed

4. **JSON parsing duplicated 7 times across codebase**
   - `cli/main.py`, `success_formatter.py`, `node_output_formatter.py`
   - `node_wrapper.py`, `batch_node.py`
   - `nodes/mcp/node.py`, `nodes/llm/llm.py`
   - **Decision**: Extract shared utility as part of this task

5. **Performance is not a concern**
   - Resolution happens once per node execution
   - JSON parsing ~1ms vs node execution ~100-1000ms

6. **Validation consistency is critical**
   - `resolve_value()` and `_traverse_path_part()` MUST stay in sync
   - Otherwise validation says "exists" but resolution returns None

---

## 2026-01-01 10:00 - Phase 1: Creating Shared JSON Utility

### 10:05 - Designing the API

Key decision: **Two-value return** `(success, result)` instead of just returning parsed/original.

Why? Need to distinguish:
- `"null"` parsed successfully to `None` → `(True, None)`
- `"invalid"` failed to parse → `(False, "invalid")`

This matters for template resolution where `None` is a valid value.

### 10:15 - Implementation

Created `src/pflow/core/json_utils.py` with:
- `try_parse_json(value, max_size)` → `(bool, Any)`
- `parse_json_or_original(value, max_size)` → `Any`

Key features:
- Strips whitespace (handles shell output newlines)
- Quick rejection for non-JSON prefixes
- 10MB size limit (security)

### 10:30 - Writing Tests

User emphasized: **Optimize for high-value tests, not coverage**.

Focused on:
1. Valid JSON object/array parsing (main use case)
2. Invalid JSON graceful fallback (UX critical)
3. Whitespace/newlines (shell output reality)
4. Size limit enforcement (security)
5. Distinguishing parsed-None from parse-failure (API correctness)
6. Real-world scenarios (curl, jq output)

Skipped low-value tests:
- Individual primitive types (json.loads handles these)
- Unicode (Python handles this)
- Non-string input (trivial guard)

### 10:45 - Phase 1 Complete ✅
- 16 tests, all passing
- `make check` passes

---

## 2026-01-01 11:00 - Phase 2: Template Resolver Enhancement

### 11:05 - Adding Helper Method

Created `_try_parse_json_for_traversal()` that:
- Only parses if value is a string
- Only returns parsed result if it's a dict or list (traversable)
- Otherwise returns original value

### 11:15 - Updating resolve_value()

Modified the "regular property access" block (line ~280):

```python
# Before: Only handled dict access
if isinstance(value, dict) and part in value:
    value = value[part]
else:
    return None

# After: Try JSON parse if value is string
if isinstance(value, dict) and part in value:
    value = value[part]
elif isinstance(value, str):
    parsed = _try_parse_json_for_traversal(value)
    if isinstance(parsed, dict) and part in parsed:
        value = parsed[part]
    else:
        return None
else:
    return None
```

### 11:25 - Updating _traverse_path_part() (Critical!)

This function is used by `variable_exists()` for validation. **Must match resolve_value() logic exactly**.

Same pattern applied.

### 11:35 - Updating Array Access

For `${node.stdout[0]}` where stdout is `'[1, 2, 3]'`:
- After getting base value, call `_try_parse_json_for_traversal()`
- Enables array access on JSON string arrays

### 11:45 - First Test Run

21 tests written, all pass! 🎉

But...

### 11:50 - PROBLEM: Cyclomatic Complexity

```
ruff: C901 `_traverse_path_part` is too complex (12 > 10)
ruff: C901 `resolve_value` is too complex (12 > 10)
```

**Deviation from plan**: Needed to refactor to reduce complexity.

### 12:00 - Solution: Extract _get_dict_value() Helper

Created shared helper that both functions use:

```python
@staticmethod
def _get_dict_value(value: Any, key: str) -> tuple[bool, Any]:
    """Get a key from a dict, with JSON string auto-parsing."""
    if isinstance(value, dict) and key in value:
        return True, value[key]
    if isinstance(value, str):
        parsed = TemplateResolver._try_parse_json_for_traversal(value)
        if isinstance(parsed, dict) and key in parsed:
            return True, parsed[key]
    return False, None
```

This:
- Reduces duplication between resolve_value() and _traverse_path_part()
- Brings complexity under the limit
- Makes the code more readable

### 12:15 - Phase 2 Complete ✅
- All 73 template resolver tests pass
- All 3253 project tests pass
- `make check` passes

---

## 2026-01-01 13:00 - Phase 3: Consolidating Duplicates

### 13:05 - Identifying Files to Update

5 files with simple replacements:
1. `cli/main.py` - `_parse_if_json()`
2. `success_formatter.py` - `_parse_if_json()`
3. `node_output_formatter.py` - `_try_parse_json_string()`
4. `node_wrapper.py` - inline logic
5. `batch_node.py` - inline logic

2 files to KEEP SEPARATE:
- `nodes/mcp/node.py` - has `ast.literal_eval` fallback for non-compliant MCP servers
- `nodes/llm/llm.py` - handles markdown code block extraction

### 13:10 - Simple Replacements

`cli/main.py` and `success_formatter.py` were identical:
- Remove function definition
- Add import: `from pflow.core.json_utils import parse_json_or_original`
- Replace all calls

### 13:20 - node_output_formatter.py

This one was different - it parses JSON then flattens the result for structure display.

Kept the function but simplified the parsing:

```python
# Before
if not (isinstance(value, str) and value.strip().startswith(("{", "["))):
    return None
try:
    parsed_value = json.loads(value)
    return flatten_runtime_value(...)
except:
    return None

# After
success, parsed_value = try_parse_json(value)
if success:
    return flatten_runtime_value(...)
return None
```

### 13:30 - node_wrapper.py

More complex - has type validation after parsing.

Kept the type validation, just replaced the parsing:

```python
# Before: 36 lines with size checks, prefix checks, try/except
if len(trimmed) > MAX_JSON_SIZE:
    logger.warning(...)
elif trimmed.startswith("{"):
    try:
        parsed = json.loads(trimmed)
        if isinstance(parsed, dict):
            resolved_value = parsed
    except:
        pass

# After: 14 lines
success, parsed = try_parse_json(resolved_value)
type_matches = (expected_type in ("dict", "object") and isinstance(parsed, dict)) or (
    expected_type in ("list", "array") and isinstance(parsed, list)
)
if success and type_matches:
    resolved_value = parsed
```

### 13:35 - PROBLEM: Nested If Lint Error

```
ruff: SIM102 Use a single `if` statement instead of nested `if` statements
```

Originally wrote:
```python
if success:
    if type_matches:
        resolved_value = parsed
```

**Fix**: Extract `type_matches` as a variable, combine into single `if success and type_matches`.

### 13:40 - batch_node.py

Simplest refactor - went from 23 lines to 6:

```python
# Before: Size checks, prefix checks, try/except, logging
if len(trimmed) > MAX_JSON_SIZE:
    logger.warning(...)
elif trimmed.startswith("["):
    try:
        parsed = json.loads(trimmed)
        if isinstance(parsed, list):
            items = parsed
    except:
        pass

# After
success, parsed = try_parse_json(items)
if success and isinstance(parsed, list):
    items = parsed
```

### 13:50 - Phase 3 Complete ✅
- ~65 lines of duplicate code removed
- All 3253 tests pass
- `make check` passes

---

## Key Insights & Lessons Learned

### 1. Verify Assumptions Before Coding
Launching 8 parallel search agents before writing any code saved hours. Discovered:
- The change location was different than expected (template_resolver, not node_wrapper)
- Validation consistency requirement I would have missed
- Opportunity to consolidate 7 duplicate implementations

### 2. Two-Value Return for Parse Functions
`(success, result)` is better than just returning result because:
- Distinguishes "parsed to None" from "failed to parse"
- Caller can make informed decisions
- No need for sentinel values

### 3. Cyclomatic Complexity Limits Force Good Design
The ruff C901 error forced me to extract `_get_dict_value()`, which:
- Reduced duplication between two functions
- Made the code more readable
- Ensured validation and resolution stay in sync

### 4. Test for Behavior, Not Coverage
User's emphasis on "high-value tests" was key:
- Shell output with newlines (real-world scenario)
- Invalid JSON graceful fallback (UX critical)
- Recursive JSON parsing (edge case that matters)
- Skipped trivial tests that just exercise json.loads()

### 5. Keep Specialized Parsers Separate
MCP node's `ast.literal_eval` fallback and LLM node's markdown extraction are specialized. Forcing them to use the generic utility would break functionality.

---

## Files Changed

### New Files
- `src/pflow/core/json_utils.py` - Shared JSON parsing utility
- `tests/test_core/test_json_utils.py` - 16 utility tests
- `tests/test_runtime/test_template_resolver_json_parsing.py` - 21 feature tests

### Modified Files
- `src/pflow/runtime/template_resolver.py` - Core feature (3 new methods, ~50 lines)
- `src/pflow/cli/main.py` - Replaced `_parse_if_json`
- `src/pflow/execution/formatters/success_formatter.py` - Replaced `_parse_if_json`
- `src/pflow/execution/formatters/node_output_formatter.py` - Simplified `_try_parse_json_string`
- `src/pflow/runtime/node_wrapper.py` - Simplified auto-parse logic
- `src/pflow/runtime/batch_node.py` - Simplified auto-parse logic

### Not Modified (Intentionally)
- `src/pflow/nodes/mcp/node.py` - Keeps ast.literal_eval fallback
- `src/pflow/nodes/llm/llm.py` - Keeps markdown extraction

---

## 2026-01-01 14:00 - Phase 4: Validator Integration & E2E Tests

### 14:05 - The Validator Problem Discovered

Wrote E2E tests expecting them to work. They failed:

```
ValueError: Template validation failed:
  - Node 'nested-json' (type: shell) does not output 'stdout'
  Available outputs from 'nested-json':
    ✓ ${nested-json.stdout} (str)
```

**Root Cause**: The compile-time template validator and runtime resolver have different views:
- **Validator**: Sees `stdout: str` → "You can't access `.field` on a string"
- **Runtime**: Sees `stdout = '{"field": "value"}'` → Parses JSON, returns `"value"`

The validator runs at compile time and only sees static type metadata. It doesn't know the string will contain JSON at runtime.

### 14:15 - Options Considered

1. **Use `validate=False` in tests** - Workaround, poor UX for users
2. **Update shell node to `stdout: any`** - Inaccurate, `any` means "could be anything"
3. **Add `json` type** - Adds type system complexity
4. **Relax validator for `str` types** - Allow nested access, defer to runtime

### 14:20 - Key Insight: LLM Node Already Works

Checked how LLM node handles this:
- LLM declares `response: any`
- Validator allows nested access on `any` (can't validate, defer to runtime)
- Shell declares `stdout: str`
- Validator blocks nested access on `str` (strings don't have fields)

**The difference is the declared type, not the runtime behavior.**

### 14:30 - Design Decision: Warning Behavior by Type

User feedback led to refined approach:

| Type | Nested Access | Warning | Rationale |
|------|--------------|---------|-----------|
| `dict` | ✅ Allowed | No | Trusted structured data |
| `any` | ✅ Allowed | No | Explicit declaration by node author |
| `str` | ✅ Allowed | **Yes** | JSON auto-parsing is implicit/magical |

**Key insight**: `any` is an *explicit* declaration saying "this could be anything". Warning about it is noise since the node author intentionally chose that type. Only `str` deserves a warning because JSON auto-parsing is the "surprising" case.

### 14:45 - Implementing Validator Changes

Created `_check_type_allows_traversal()` helper in `template_validator.py`:

```python
def _check_type_allows_traversal(output_type, path_parts, ...):
    types_in_union = [t.strip().lower() for t in output_type.split("|")]

    # Check if ANY type allows traversal
    traversable = ["dict", "object", "any", "str", "string"]
    traversable_types = [t for t in types_in_union if t in traversable]

    if not traversable_types:
        return (False, None)

    # dict/object and any are trusted - no warning
    trusted = ["dict", "object", "any"]
    if any(t in trusted for t in traversable_types):
        return (True, None)

    # Only str/string - warn about JSON auto-parsing
    if any(t in ["str", "string"] for t in traversable_types):
        warning = ValidationWarning(
            reason=f"Output type '{output_type}' - nested access will use JSON auto-parsing at runtime",
            ...
        )
        return (True, warning)
```

### 15:00 - Also Fixed: Array Index Handling

Discovered validator didn't handle `${node.stdout[0].field}` correctly.

Added `_strip_array_indices()` helper to extract base key from array notation:
- `stdout[0]` → `stdout`
- `items[0][1]` → `items`

Then pass the stripped key for validation but keep full path for traversal.

### 15:15 - Updating Warning Tests

Rewrote `test_template_validator_warnings.py`:

**Before**: Tests focused on `any` type generating warnings
**After**: Tests focus on:
- `str` type → WARNING (JSON auto-parsing is implicit)
- `any` type → NO WARNING (explicit declaration)
- `dict` type → NO WARNING (trusted)
- Direct access (no nesting) → NO WARNING

### 15:30 - E2E Tests Now Work WITH Validation

The key win: E2E tests run with `validate=True` (the default):

```python
# This now works without validate=False!
flow = compile_ir_to_flow(workflow_ir, registry=registry)
shared = {}
flow.run(shared)
assert "iso value: 2026-01-01" in shared["test-nested"]["stdout"]
```

Users will see a warning in the console:
```
⚠ Warning: Output type 'str' - nested access will use JSON auto-parsing at runtime
```

But the workflow compiles and runs successfully.

### 15:45 - Phase 4 Complete ✅
- 9 E2E tests pass (with validation enabled)
- 7 warning behavior tests updated
- All 3263 project tests pass
- `make check` passes

---

## Critical Insight: Two-System Coordination

This feature required coordinating TWO systems:

1. **Runtime Template Resolver** (`template_resolver.py`)
   - Parses JSON strings during path traversal
   - Pure runtime behavior
   - Implementation was straightforward

2. **Compile-time Template Validator** (`template_validator.py`)
   - Checks template paths against static metadata
   - Can only see declared types, not runtime values
   - Had to be relaxed to allow `str` nested access

**Lesson**: When adding runtime magic, always check if compile-time validation needs updating. The validator and resolver must agree on what's valid.

---

## Final Architecture

```
Compile Time                          Runtime
     │                                    │
     ▼                                    ▼
┌─────────────────┐              ┌─────────────────┐
│ TemplateValidator│              │ TemplateResolver│
│                 │              │                 │
│ ${shell.stdout. │              │ ${shell.stdout. │
│  field}         │              │  field}         │
│       │         │              │       │         │
│       ▼         │              │       ▼         │
│ stdout: str     │              │ stdout = '{"f": │
│ Type allows     │              │  "v"}'          │
│ traversal? YES  │──WARNING──▶  │ Parse JSON      │
│ (with warning)  │              │ Access field    │
└─────────────────┘              └─────────────────┘
```

---

## Files Changed in Phase 4

### Modified Files
- `src/pflow/runtime/template_validator.py` - Relaxed `str` type validation with warnings
- `tests/test_runtime/test_template_validator_warnings.py` - Updated for new warning behavior
- `tests/test_runtime/test_template_validator_union_types.py` - Minor updates

### New Files
- `tests/test_integration/test_json_nested_access_e2e.py` - 9 E2E tests

---

## 2026-01-01 23:00 - Test Quality Review

### Principle Applied
Optimize for high-value tests that verify real behavior, not coverage metrics.

### Tests Removed (6)
| Test | Why Removed |
|------|-------------|
| `test_non_string_input_returns_unchanged` | Tests wrong type input - not a runtime scenario |
| `test_quick_rejection_for_obvious_non_json` | Tests implementation optimization, not behavior |
| `TestParseJsonOrOriginal` (2 tests) | Trivial wrapper tests - underlying function already tested |
| `test_triple_nested_json` | If double nesting works, triple works |
| `test_no_warnings_for_empty_workflow` | Trivial edge case |

### Test Added (1)
| Test | Why Added |
|------|-----------|
| `test_json_primitives_null_and_bool` | High value - APIs frequently return null/bool, must verify type preservation |

### Key Insight
The distinction between "tests implementation" vs "tests behavior" is crucial:
- **Implementation test**: "Does the quick rejection optimization work?" → Low value, couples tests to implementation
- **Behavior test**: "Does null become Python None?" → High value, documents expected behavior

---

## Acceptance Criteria Verified ✅

All 8 criteria passed via CLI execution:
1. `${node.stdout.field}` resolves → `iso value: 2026-01-01`
2. `${node.stdout[0]}` resolves → `First: first, Second ID: 2`
3. Invalid JSON graceful error → `Unresolved variables` with suggestion
4. Deep nesting → `Deep: deep-value`
5. Mixed access → `First: Alice, Count: 2`
6. No performance regression → 320-341ms (consistent)
7. Backward compatible → `Raw stdout: {"field": "value"}`
8. Debug logging → Code has `logger.debug("Auto-parsed JSON...")`

---

## Final State

- 40 feature-specific tests (down from 46)
- 3661 total project tests pass
- All linting/type checks pass
- Ready to commit
