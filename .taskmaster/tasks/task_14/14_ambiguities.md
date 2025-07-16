# Task 14: Structured Output Metadata - Critical Ambiguities

## Executive Summary

While Task 14's goal is clear (enable the planner to see data structures), several implementation details need clarification before coding can begin. This document identifies each ambiguity with concrete options and recommendations.

## 1. Exact Docstring Format Specification - Decision importance (5)

The task shows an example format, but many variations are possible and each has trade-offs.

### The Ambiguity:
- Should we use JSON-like, YAML-like, or Python-dict-like syntax?
- How to represent types (Python types vs JSON types vs strings)?
- How to handle optional fields?
- How to represent arrays of objects?

### Options:

- [ ] **Option A: JSON-like with Python types**
  ```python
  """
  Outputs:
  - issue_data: {
      "id": int,
      "title": str,
      "user": {"login": str, "id": int},
      "labels": [{"name": str, "color": str}]
    }
  """
  ```
  - Pros: Familiar to Python developers, clear type info
  - Cons: Not valid JSON, types aren't strings

- [x] **Option B: Simplified Python-dict notation**
  ```python
  """
  Outputs:
  - issue_data: dict
    - id: int
    - title: str
    - user: dict
      - login: str
      - id: int
    - labels: list[dict]
      - name: str
      - color: str
  """
  ```
  - Pros: Clean indentation-based, no brace matching needed
  - Cons: New format to learn

- [ ] **Option C: Type annotation style**
  ```python
  """
  Outputs:
  - issue_data: Dict[str, Any] with structure:
    {
      id: int,
      title: str,
      user: {login: str, id: int},
      labels: List[{name: str, color: str}]
    }
  """
  ```
  - Pros: Pythonic, type-hint familiar
  - Cons: Verbose, mixing formats

**Recommendation**: Option B - Indentation-based is easiest to parse and write, avoiding complex brace matching while remaining readable.

## 2. Type System Representation - Decision importance (4)

How should we represent types in the structure documentation?

### The Ambiguity:
- Use Python types (int, str, dict, list)?
- Use JSON types (number, string, object, array)?
- Use simplified types (text, number, object, array)?
- How to handle None/null, Any, Union types?

### Options:

- [x] **Option A: Python built-in types only**
  - Types: `str`, `int`, `float`, `bool`, `dict`, `list`, `None`
  - Simple and familiar to Python developers
  - Sufficient for MVP needs

- [ ] **Option B: JSON Schema types**
  - Types: `string`, `number`, `boolean`, `object`, `array`, `null`
  - More standard but less Pythonic
  - Might confuse Python developers

- [ ] **Option C: Rich type system**
  - Include Optional, Union, Any, custom types
  - More expressive but complex to parse
  - Overkill for MVP

**Recommendation**: Option A - Python built-in types are familiar and sufficient. We can always extend later.

## 3. Array Representation Ambiguity - Decision importance (4)

How to represent arrays of structured objects?

### The Ambiguity:
- How to show the structure of items in an array?
- Support homogeneous arrays only or mixed types?
- How to indicate "array of X"?

### Options:

- [x] **Option A: list[type] with example structure**
  ```python
  """
  Outputs:
  - labels: list[dict]
    - name: str
    - color: str
  """
  ```
  - Shows one example structure for all items
  - Assumes homogeneous arrays

- [ ] **Option B: JSON-style array notation**
  ```python
  """
  Outputs:
  - labels: [{"name": str, "color": str}]
  """
  ```
  - More compact but harder to parse

- [ ] **Option C: Explicit array documentation**
  ```python
  """
  Outputs:
  - labels: array
    items:
      - name: str
      - color: str
  """
  ```
  - Very explicit but verbose

**Recommendation**: Option A - Clear and consistent with the indentation-based approach.

## 4. Parsing Strategy - Decision importance (5)

How should we parse these structured docstrings?

### The Ambiguity:
- Use regex with state machine?
- Write a simple parser?
- Use existing parsing library?
- How to handle malformed structures?

### Options:

- [ ] **Option A: Enhanced regex parsing**
  - Extend existing regex approach
  - Add state tracking for nesting
  - Pros: Consistent with current code
  - Cons: Regex complexity explosion

- [x] **Option B: Simple indentation-based parser**
  - Parse based on indentation levels
  - Similar to YAML parsing
  - Pros: Clean, maintainable
  - Cons: New code pattern

- [ ] **Option C: Use existing library**
  - Use YAML parser with preprocessing
  - Pros: Robust parsing
  - Cons: New dependency, format constraints

**Recommendation**: Option B - Indentation-based parsing is simple and maintainable for our specific format.

## 5. Backward Compatibility Details - Decision importance (5)

How exactly do we maintain compatibility with existing simple format?

### The Ambiguity:
- How to detect which format is being used?
- Can both formats exist in same docstring?
- What about nodes with mixed simple/structured outputs?

### Options:

- [x] **Option A: Format detection by structure**
  - If line has `:` followed by type → structured
  - If comma-separated list → simple
  - Never mix formats in one section
  ```python
  # Simple format (existing):
  Outputs: key1, key2, key3

  # Structured format (new):
  Outputs:
  - key1: str
  - key2: dict
    - field: str
  ```

- [ ] **Option B: Explicit format marker**
  ```python
  Outputs (structured):
  - key: {...}
  ```
  - More explicit but breaks existing nodes

- [ ] **Option C: Support mixed formats**
  ```python
  Outputs: simple_key1, simple_key2
  - complex_key: dict
    - field: str
  ```
  - Flexible but confusing

**Recommendation**: Option A - Clean detection based on structure, never mix formats.

## 6. Structure Depth Limits - Decision importance (3)

How deep should we allow structures to go?

### The Ambiguity:
- Unlimited nesting depth?
- Practical limit for readability?
- How to handle recursive structures?

### Options:

- [ ] **Option A: Unlimited depth**
  - Parse any depth
  - Risk of huge docstrings
  - Parsing complexity

- [x] **Option B: Practical limit (3-4 levels)**
  - Sufficient for most APIs
  - Use "..." for deeper structures
  - Example:
  ```python
  - data: dict
    - user: dict
      - profile: dict
        - settings: dict  # Max depth
          - ...: Any    # Indicate more nesting
  ```

- [ ] **Option C: Depth limit with references**
  - Define structures separately
  - Reference by name
  - Too complex for MVP

**Recommendation**: Option B - 3-4 levels covers most use cases while keeping docstrings readable.

## 7. Error Handling Strategy - Decision importance (4)

What happens when structure parsing fails?

### The Ambiguity:
- Fail hard and block registry loading?
- Warn and fall back to simple format?
- Silent fallback?

### Options:

- [ ] **Option A: Fail hard**
  - Any parse error stops registry loading
  - Forces immediate fixes
  - Too disruptive

- [x] **Option B: Warn and fallback**
  - Log warning with specific error
  - Treat as simple output list
  - Preserves functionality
  - Example:
  ```python
  logger.warning(f"Failed to parse structure for {node}.outputs: {error}")
  # Fallback to simple format
  ```

- [ ] **Option C: Partial parsing**
  - Parse what we can, skip errors
  - Risk of incorrect structures

**Recommendation**: Option B - Graceful degradation maintains system stability while alerting developers.

## 8. Storage Format in Metadata - Decision importance (3)

How should parsed structures be stored in the metadata dictionary?

### The Ambiguity:
- Store as parsed Python dicts?
- Create a Structure class?
- Keep original text too?

### Options:

- [x] **Option A: Simple dict storage**
  ```python
  metadata = {
      "outputs": ["issue_data", "issue_number"],  # Keep for compatibility
      "output_structures": {
          "issue_data": {
              "type": "dict",
              "fields": {
                  "id": {"type": "int"},
                  "user": {
                      "type": "dict",
                      "fields": {"login": {"type": "str"}}
                  }
              }
          },
          "issue_number": {"type": "int"}
      }
  }
  ```

- [ ] **Option B: Structure classes**
  - Create OutputStructure, Field classes
  - More OOP but overkill for MVP

- [ ] **Option C: Raw format storage**
  - Store unparsed structure text
  - Parse on demand
  - Inefficient

**Recommendation**: Option A - Simple dicts are sufficient and work well with JSON serialization.

## 9. Context Builder Integration Specifics - Decision importance (4)

How exactly should structures appear in the planning context?

### The Ambiguity:
- Full structure every time?
- Abbreviated common paths?
- Example-based format?

### Options:

- [ ] **Option A: Full structure display**
  - Show complete structure in context
  - Risk of context bloat

- [x] **Option B: Path examples approach**
  ```markdown
  ### github-get-issue
  **Outputs**:
  - `issue_data`: Complex object
    - Example paths: `issue_data.id`, `issue_data.user.login`, `issue_data.labels[0].name`
    - Full structure: {...abbreviated...}
  ```
  - Gives LLM quick examples
  - Full structure available if needed

- [ ] **Option C: Interactive expansion**
  - Show top-level only
  - LLM can ask for more
  - Too complex for MVP

**Recommendation**: Option B - Path examples give LLM what it needs without overwhelming context.

## 10. Priority Node Selection - Decision importance (3)

Which nodes should we update first and why?

### The Ambiguity:
- Update all nodes at once?
- Just GitHub nodes?
- Criteria for priority?

### Options:

- [ ] **Option A: All API nodes**
  - Complete coverage
  - Time consuming
  - Risk of errors

- [x] **Option B: Strategic selection**
  Priority order:
  1. `github-get-issue` - Most complex, most used in examples
  2. `github-list-prs` - Array handling example
  3. `claude-code` - Complex output structure
  4. File operations returning metadata
  - Covers main patterns
  - Manageable scope

- [ ] **Option C: On-demand updates**
  - Update as needed
  - Inconsistent state

**Recommendation**: Option B - Strategic nodes provide templates for others to follow.

## Critical Implementation Order

1. **First**: Decide on format (Recommendation: Indentation-based)
2. **Second**: Implement parser with error handling
3. **Third**: Update metadata extractor
4. **Fourth**: Update 2-3 test nodes
5. **Fifth**: Integrate with context builder
6. **Sixth**: Test with full planner flow

## The Most Critical Decision

**Format choice (Ambiguity #1) affects everything else**. The indentation-based format recommended here:
- Easiest to parse
- Natural to write
- No brace matching complexity
- Familiar from YAML/Python

## Risk Mitigation

1. **Start with minimal structure support** - Just one level deep
2. **Test on one node completely** before updating others
3. **Keep backward compatibility** as non-negotiable requirement
4. **Use warning logs** to find issues without breaking system

This should resolve the key ambiguities and enable implementation to begin.
