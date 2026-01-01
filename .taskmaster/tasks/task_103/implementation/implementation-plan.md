# Task 103: Implementation Plan

## Preserve Inline Object Type in Template Resolution

### Executive Summary

Rename `resolve_string()` to `resolve_template()` and add simple template detection to preserve types. This fixes the double-serialization bug where `{"key": "${dict_var}"}` becomes `{"key": "{\"nested\": \"value\"}"}` instead of `{"key": {"nested": "value"}}`.

---

## Problem Statement

**Current behavior (broken):**
```python
context = {"data": {"name": "Alice"}}
resolve_nested({"user": "${data}"}, context)
# Returns: {"user": "{\"name\": \"Alice\"}"}  ← JSON string (WRONG)
```

**Desired behavior:**
```python
context = {"data": {"name": "Alice"}}
resolve_nested({"user": "${data}"}, context)
# Returns: {"user": {"name": "Alice"}}  ← Dict preserved (CORRECT)
```

---

## Design Decisions

### 1. Rename `resolve_string` → `resolve_template`

**Rationale:** The method will now return `Any` (not just `str`), so the name should reflect this. "resolve_template" accurately describes what it does: resolve a template string to its value.

### 2. Simple Template Detection Pattern

**Pattern:** `r"^\$\{([^}]+)\}$"`

**Matches (simple → preserve type):**
- `${var}`
- `${data.field}`
- `${items[0].name}`

**Does NOT match (complex → string interpolation):**
- `Hello ${name}` (prefix)
- `${name}!` (suffix)
- `${a}${b}` (multiple templates)
- ` ${var}` (leading whitespace)

### 3. Shared Helper for DRY

Create `is_simple_template()` static method in `TemplateResolver` to eliminate duplication between `resolve_template()` and `node_wrapper._resolve_simple_template()`.

---

## Existing Functionality to PRESERVE

| Functionality | Location | Status |
|--------------|----------|--------|
| Path traversal (`${data.field}`) | `resolve_value()` | Keep unchanged |
| Array indices (`${items[0]}`) | `resolve_value()` | Keep unchanged |
| Variable existence check | `variable_exists()` | Keep unchanged |
| String conversion rules | `_convert_to_string()` | Keep unchanged |
| Unresolved templates stay as-is | `resolve_string()` → `resolve_template()` | Preserve behavior |
| Complex template string interpolation | `resolve_string()` → `resolve_template()` | Preserve behavior |
| Recursive structure resolution | `resolve_nested()` | Keep structure, change inner call |
| JSON auto-parsing for shell output | `node_wrapper.py:746-781` | Keep unchanged |
| Type validation for simple templates | `node_wrapper.py:783-803` | Keep unchanged |
| TEMPLATE_PATTERN regex | Class constant | Keep unchanged |

---

## Implementation Phases

### Phase 1: Add Helper Method and Modify `resolve_template` (Core Fix)

**File:** `src/pflow/runtime/template_resolver.py`

**Step 1.1: Add `is_simple_template()` helper**

```python
# Add after line 61 (after extract_variables)

# Pattern for detecting simple templates (entire string is one ${var} reference)
SIMPLE_TEMPLATE_PATTERN = re.compile(r"^\$\{([^}]+)\}$")

@staticmethod
def is_simple_template(value: str) -> bool:
    """Check if string is exactly one template variable reference.

    Simple templates like "${var}" preserve the original type when resolved.
    Complex templates like "Hello ${name}" always return strings.

    Args:
        value: String to check

    Returns:
        True if the entire string is a single template reference
    """
    return bool(TemplateResolver.SIMPLE_TEMPLATE_PATTERN.match(value))

@staticmethod
def extract_simple_template_var(value: str) -> Optional[str]:
    """Extract variable name from a simple template.

    Args:
        value: String that is a simple template

    Returns:
        Variable name (with path if present), or None if not a simple template
    """
    match = TemplateResolver.SIMPLE_TEMPLATE_PATTERN.match(value)
    return match.group(1) if match else None
```

**Step 1.2: Rename `resolve_string` to `resolve_template` and add type preservation**

```python
@staticmethod
def resolve_template(template: str, context: dict[str, Any]) -> Any:
    """Resolve a template string to its value.

    For simple templates (entire string is "${var}"), preserves the original type.
    For complex templates (text around variables), returns a string.

    Args:
        template: String containing template variables
        context: Dictionary containing values to resolve from

    Returns:
        - For simple templates: The resolved value with original type preserved
        - For complex templates: String with variables interpolated
        - For unresolved templates: The template string unchanged

    Examples:
        >>> context = {"data": {"name": "Alice"}, "count": 42}
        >>> TemplateResolver.resolve_template("${data}", context)
        {"name": "Alice"}  # Dict preserved
        >>> TemplateResolver.resolve_template("${count}", context)
        42  # Int preserved
        >>> TemplateResolver.resolve_template("Count: ${count}", context)
        "Count: 42"  # String (complex template)
    """
    # Check for simple template first - preserve type
    var_name = TemplateResolver.extract_simple_template_var(template)
    if var_name is not None:
        if TemplateResolver.variable_exists(var_name, context):
            return TemplateResolver.resolve_value(var_name, context)
        else:
            # Variable doesn't exist - return template unchanged for debugging
            return template

    # Complex template - do string interpolation (existing logic)
    result = template

    for match in TemplateResolver.TEMPLATE_PATTERN.finditer(template):
        # ... (keep existing logic from resolve_string, lines 312-357)

    return result
```

**Step 1.3: Update `resolve_nested` to call `resolve_template`**

```python
@staticmethod
def resolve_nested(value: Any, context: dict[str, Any]) -> Any:
    """Recursively resolve template variables in nested structures.
    # ... (keep existing docstring)
    """
    if isinstance(value, str):
        if "${" in value:
            return TemplateResolver.resolve_template(value, context)  # Changed from resolve_string
        return value
    elif isinstance(value, dict):
        return {k: TemplateResolver.resolve_nested(v, context) for k, v in value.items()}
    elif isinstance(value, list):
        return [TemplateResolver.resolve_nested(item, context) for item in value]
    else:
        return value
```

**Step 1.4: Keep `resolve_string` as deprecated alias (optional safety)**

```python
@staticmethod
def resolve_string(template: str, context: dict[str, Any]) -> str:
    """DEPRECATED: Use resolve_template() instead.

    This method is kept for backward compatibility but will be removed.
    Note: This forces string return for compatibility with existing callers
    that expect strings.
    """
    result = TemplateResolver.resolve_template(template, context)
    if isinstance(result, str):
        return result
    # Force string conversion for backward compat
    return TemplateResolver._convert_to_string(result)
```

**Decision point:** We said no backward compat needed, so we can skip the alias and just delete `resolve_string`. But keeping it temporarily helps identify any callers we missed.

**Recommendation:** Delete it. Update all callers explicitly.

---

### Phase 2: Update Callers

**File 1:** `src/pflow/runtime/workflow_executor.py` (line 274)

```python
# Before:
resolved[child_param] = TemplateResolver.resolve_string(parent_value, context)

# After:
resolved[child_param] = TemplateResolver.resolve_template(parent_value, context)
```

**File 2:** `src/pflow/runtime/node_wrapper.py` (line 589)

```python
# Before:
resolved_value = TemplateResolver.resolve_string(template, context)

# After:
resolved_value = TemplateResolver.resolve_template(template, context)
```

**Note:** The node_wrapper call is AFTER `_resolve_simple_template()` returns False, so it's only for complex templates. The result will always be a string here. But using `resolve_template` is still correct - it will return a string for complex templates.

---

### Phase 3: Refactor `node_wrapper._resolve_simple_template`

**File:** `src/pflow/runtime/node_wrapper.py`

The `_resolve_simple_template` method (lines 525-559) can now use the shared helper:

```python
def _resolve_simple_template(self, template: str, context: dict[str, Any]) -> tuple[Any, bool]:
    """Resolve a simple template variable like '${var}'.

    Args:
        template: Template string to resolve
        context: Resolution context

    Returns:
        Tuple of (resolved_value, was_simple_template)
    """
    var_name = TemplateResolver.extract_simple_template_var(template)
    if var_name is None:
        return None, False

    # Check if variable exists (even if its value is None)
    if TemplateResolver.variable_exists(var_name, context):
        resolved_value = TemplateResolver.resolve_value(var_name, context)
        logger.debug(
            f"Resolved simple template: ${{{var_name}}} -> {resolved_value!r} "
            f"(type: {type(resolved_value).__name__})",
            extra={"node_id": self.node_id},
        )
        return resolved_value, True
    else:
        # Variable doesn't exist - keep template as-is for debugging
        logger.debug(
            f"Template variable '${{{var_name}}}' not found in context, keeping template as-is",
            extra={"node_id": self.node_id},
        )
        return template, True
```

**Benefits:**
- Single regex pattern (in TemplateResolver)
- Consistent behavior between top-level and nested resolution
- Easier to maintain

---

### Phase 4: Update Tests

**Files to update:**
- `tests/test_runtime/test_template_resolver.py`
- `tests/test_runtime/test_template_resolver_arrays.py`
- `tests/test_runtime/test_template_resolver_nested.py`
- `tests/test_runtime/test_template_array_notation.py`
- `tests/test_nodes/test_mcp/test_json_text_parsing.py`

**Changes needed:**

1. **Rename all `resolve_string` calls to `resolve_template`**

2. **Add new tests for type preservation:**

```python
class TestSimpleTemplateTypePreservation:
    """Test that simple templates preserve original types."""

    def test_simple_template_preserves_dict(self):
        context = {"data": {"key": "value", "count": 42}}
        result = TemplateResolver.resolve_template("${data}", context)
        assert isinstance(result, dict)
        assert result == {"key": "value", "count": 42}

    def test_simple_template_preserves_list(self):
        context = {"items": [1, 2, 3]}
        result = TemplateResolver.resolve_template("${items}", context)
        assert isinstance(result, list)
        assert result == [1, 2, 3]

    def test_simple_template_preserves_int(self):
        context = {"count": 42}
        result = TemplateResolver.resolve_template("${count}", context)
        assert isinstance(result, int)
        assert result == 42

    def test_simple_template_preserves_bool(self):
        context = {"flag": True}
        result = TemplateResolver.resolve_template("${flag}", context)
        assert result is True

    def test_simple_template_preserves_none(self):
        context = {"empty": None}
        result = TemplateResolver.resolve_template("${empty}", context)
        assert result is None

    def test_complex_template_returns_string(self):
        context = {"data": {"key": "value"}}
        result = TemplateResolver.resolve_template("Data: ${data}", context)
        assert isinstance(result, str)
        assert result == 'Data: {"key": "value"}'

    def test_unresolved_simple_template_unchanged(self):
        context = {}
        result = TemplateResolver.resolve_template("${missing}", context)
        assert result == "${missing}"


class TestNestedTemplateTypePreservation:
    """Test that nested templates preserve types correctly."""

    def test_dict_with_simple_template_preserves_inner_type(self):
        context = {"inner": {"nested": "value"}}
        result = TemplateResolver.resolve_nested({"outer": "${inner}"}, context)
        assert result == {"outer": {"nested": "value"}}
        assert isinstance(result["outer"], dict)

    def test_list_with_simple_templates_preserves_types(self):
        context = {"a": {"x": 1}, "b": [1, 2, 3]}
        result = TemplateResolver.resolve_nested(["${a}", "${b}"], context)
        assert result == [{"x": 1}, [1, 2, 3]]
        assert isinstance(result[0], dict)
        assert isinstance(result[1], list)

    def test_deeply_nested_type_preservation(self):
        context = {"data": {"items": [{"id": 1}]}}
        result = TemplateResolver.resolve_nested(
            {"level1": {"level2": "${data}"}},
            context
        )
        assert result == {"level1": {"level2": {"items": [{"id": 1}]}}}
        assert isinstance(result["level1"]["level2"], dict)

    def test_mixed_simple_and_complex_in_dict(self):
        context = {"name": "Alice", "data": {"x": 1}}
        result = TemplateResolver.resolve_nested(
            {"greeting": "Hello ${name}", "info": "${data}"},
            context
        )
        assert result == {"greeting": "Hello Alice", "info": {"x": 1}}
        assert isinstance(result["greeting"], str)
        assert isinstance(result["info"], dict)
```

3. **Update existing tests that check string output:**

Some tests may expect `resolve_string` to return JSON strings for dict values. These need review:
- If testing complex templates: Keep expecting strings
- If testing simple templates: Update to expect preserved types

---

### Phase 5: Update Documentation

**Files:**
- `src/pflow/runtime/CLAUDE.md` - Update template resolution section
- Docstrings in `template_resolver.py`

**Key documentation updates:**

1. Document the new behavior:
   - Simple templates preserve type
   - Complex templates return strings

2. Update examples in docstrings

3. Add migration note (if we keep the deprecated alias)

---

## Verification Checklist

### Before Implementation
- [ ] Read and understand all affected files
- [ ] Identify all callers of `resolve_string`
- [ ] Review test coverage

### Phase 1 Verification
- [ ] `is_simple_template()` correctly identifies patterns
- [ ] `extract_simple_template_var()` extracts variable names
- [ ] `resolve_template()` preserves types for simple templates
- [ ] `resolve_template()` returns strings for complex templates
- [ ] Unresolved templates remain unchanged
- [ ] `resolve_nested()` uses new method

### Phase 2 Verification
- [ ] `workflow_executor.py` updated and works
- [ ] `node_wrapper.py` updated and works
- [ ] No other callers missed

### Phase 3 Verification
- [ ] `_resolve_simple_template` uses shared helper
- [ ] Logging still works correctly
- [ ] `is_simple_template` flag still correct for JSON auto-parsing
- [ ] `is_simple_template` flag still correct for type validation

### Phase 4 Verification
- [ ] All tests pass
- [ ] New type preservation tests added
- [ ] No regressions in existing behavior

### Phase 5 Verification
- [ ] Documentation updated
- [ ] CLAUDE.md reflects new behavior

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Breaking existing workflows | Extensive test coverage, phase-by-phase implementation |
| Missing a caller | Grep for `resolve_string`, delete the old method to get compile errors |
| Edge cases in regex | Use existing TEMPLATE_PATTERN for variable extraction, simple pattern only for detection |
| JSON auto-parsing breaks | Keep `is_simple_template` flag logic unchanged in node_wrapper |
| Type validation breaks | Keep `is_simple_template` flag logic unchanged in node_wrapper |

---

## Rollback Plan

If issues are discovered:
1. Revert the `resolve_template` changes
2. Keep `resolve_string` as-is
3. Only fix `resolve_nested` with inline simple template detection

This is less elegant but lower risk.

---

## Testing Strategy

1. **Unit tests:** Test `resolve_template` directly with various inputs
2. **Integration tests:** Test `resolve_nested` with nested structures
3. **End-to-end tests:** Run existing workflow tests to catch regressions
4. **Manual testing:** Test the shell node stdin example from task description

**Key test command:**
```bash
make test  # Run full test suite
```

---

## Success Criteria

1. `{"key": "${dict_var}"}` resolves to `{"key": {...}}` (dict preserved)
2. `["${a}", "${b}"]` preserves types of each element
3. `"Hello ${name}"` still returns a string
4. `${missing}` stays as `${missing}`
5. All existing tests pass
6. No performance regression
