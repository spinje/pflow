# Smart Template Variable Formatting

## Executive Summary

This document explores enhancing template variable resolution to automatically format complex data structures (JSON/dict/array) into human-readable text when inserting into strings, particularly for LLM prompts. This would improve usability, reduce token usage, and enhance LLM comprehension without breaking existing functionality.

## Problem Statement

Currently, when template variables containing complex data structures are used in prompts, they're inserted as raw JSON strings:

```bash
# Current behavior:
github-list-issues >> llm --prompt="Summarize: $issues"
# LLM receives: "Summarize: [{"number":123,"title":"Bug in login","author":{"login":"john"}},...]"
```

This creates several issues:
- **Poor readability** for debugging and understanding
- **Higher token usage** due to JSON syntax overhead
- **Suboptimal LLM parsing** - LLMs parse structured text better than raw JSON
- **User friction** - requires intermediate formatting steps

## Proposed Solution

### Core Concept

Automatically format complex data types (dict/list) into readable text **only at template resolution time**, preserving the original data in shared store:

```python
# Shared store remains unchanged:
shared["issues"] = [{"number": 123, "title": "Bug in login", ...}]

# Template resolution becomes smart:
"Summarize: $issues"  # Auto-formats to readable text
"First: $issues[0].title"  # Still evaluates to "Bug in login"
```

### Key Principles

1. **Non-invasive**: Shared store data remains untouched
2. **Context-aware**: Only format when inserting into strings
3. **Property preservation**: `$data.field` access continues working
4. **Backward compatible**: Existing workflows unchanged

## Implementation Options

### Option 1: Automatic Smart Formatting (Recommended for v3.0)

**How it works:**
```python
def resolve_template_variable(value, context_hint=None):
    # Primitives pass through
    if isinstance(value, (str, int, float, bool)):
        return str(value)

    # Complex types get formatted
    if isinstance(value, (dict, list)):
        return to_yaml_like_format(value)  # Human-readable

    return str(value)
```

**Suggested format (YAML-like):**
```yaml
# Single object:
number: 123
title: Bug in login
author:
  login: john
  name: John Doe

# Array of objects:
- number: 123
  title: Bug in login
  author:
    login: john
- number: 124
  title: Add feature
  author:
    login: jane
```

**Escape hatch for raw JSON:**
```bash
llm --prompt="Parse this JSON: $$api_response"  # Double $$ = raw
```

### Option 2: Explicit Formatting Functions (Alternative)

**Template functions syntax:**
```bash
llm --prompt="Summarize: ${markdown($issues)}"
llm --prompt="Schema for: ${json($issues)}"
llm --prompt="Report: ${yaml($issues)}"
llm --prompt="Table: ${table($issues)}"
```

**Pros:**
- Explicit control
- Multiple format options
- No surprises

**Cons:**
- More verbose
- Learning curve
- Breaking change (new syntax)

### Option 3: Format Conversion Node (MVP Workaround)

**Immediate solution using a new node:**
```bash
# New node: format-json
github-list-issues >>
format-json --format=markdown >>
llm --prompt="Summarize: $formatted_data"
```

**Implementation:**
```python
class FormatJsonNode(Node):
    """Formats JSON data for human consumption.

    Interface:
    - Reads: shared["data"]: Any  # Data to format
    - Writes: shared["formatted_data"]: str  # Formatted output
    - Params: format: str  # Format type: markdown, yaml, table
    - Params: input_key: str  # Key to read from (default: "data")
    - Params: output_key: str  # Key to write to (default: "formatted_data")
    """
```

### Option 4: LLM Node Enhancement (Quick Win)

**Add formatting parameter to LLM node:**
```bash
llm --prompt="Summarize: $issues" --input-format=markdown
```

The LLM node internally formats template variables before sending to API.

## Edge Cases and Considerations

### 1. When Raw JSON is Needed

**Scenario:** Teaching LLM about JSON structure
```bash
llm --prompt="Generate TypeScript interface for: $api_response"
```

**Solutions:**
- Escape syntax: `$$api_response` for raw
- Context detection: File extensions (.json keeps raw)
- Explicit control: Format functions

### 2. File Writing Ambiguity

**Scenario:** Writing data to different file types
```bash
write-file --path=data.json --content="$issues"  # Want JSON
write-file --path=report.md --content="$issues"  # Want markdown
```

**Solution:** Detect file extension to determine format

### 3. Format Consistency

**Question:** What exact format for readability?

**Options:**
- YAML-like (recommended): Clean, hierarchical, familiar
- Markdown tables: Good for lists, poor for nested data
- Plain text: Simple but loses structure

### 4. Performance Impact

**Concern:** Formatting overhead on large datasets

**Mitigation:**
- Lazy evaluation
- Format caching
- Size limits (truncate if > X KB)

## Benefits

### For Users
- **Simpler workflows**: No intermediate formatting steps
- **Better debugging**: Human-readable data in logs
- **Intuitive behavior**: Works as expected

### For LLMs
- **Reduced tokens**: ~30-50% reduction vs pretty JSON
- **Better comprehension**: LLMs trained on human text
- **Clearer structure**: YAML-like format is self-documenting

### For System
- **Backward compatible**: Existing workflows unchanged
- **Non-invasive**: Shared store unaffected
- **Flexible**: Multiple implementation paths

## Migration Path

### Phase 1: Node-based Solution (v2.1)
- Implement `format-json` node
- Document in cookbook
- Gather usage patterns

### Phase 2: LLM Enhancement (v2.2)
- Add `--input-format` to LLM node
- Automatic format detection
- Measure token savings

### Phase 3: Template Functions (v3.0)
- Implement `${format()}` syntax
- Support multiple formats
- Deprecate format-json node

### Phase 4: Smart Auto-Formatting (v3.1)
- Enable by default with feature flag
- Provide escape syntax
- Monitor for issues

## Example Workflows

### Before Enhancement
```bash
# Verbose and token-heavy:
github-list-issues >>
llm --prompt="Generate changelog from: $issues"
# LLM receives: [{"number":123,"title":"Bug in...},{...}]
```

### After Enhancement
```bash
# Clean and efficient:
github-list-issues >>
llm --prompt="Generate changelog from: $issues"
# LLM receives formatted list:
# - number: 123
#   title: Bug in login
#   author:
#     login: john
```

### Real-World Impact

**Token usage comparison:**
```python
# Raw JSON (current): ~500 tokens
[{"number":123,"title":"Bug in login system","body":"Users cannot...","author":{"login":"johnsmith","name":"John Smith"},"labels":[{"name":"bug"},{"name":"urgent"}],"createdAt":"2024-01-15T10:30:00Z"}]

# Formatted (proposed): ~200 tokens
number: 123
title: Bug in login system
body: Users cannot...
author:
  login: johnsmith
  name: John Smith
labels:
  - bug
  - urgent
createdAt: 2024-01-15T10:30:00Z
```

**60% token reduction** while improving readability!

## Implementation Checklist

When implementing, ensure:

- [ ] Shared store remains unmodified
- [ ] Property access (`$data.field`) still works
- [ ] Performance acceptable for large datasets
- [ ] Format is deterministic and consistent
- [ ] Escape mechanism provided for raw JSON
- [ ] Documentation includes examples
- [ ] Migration path doesn't break existing workflows
- [ ] Token usage metrics collected

## Testing Requirements

### Unit Tests
- Format various data structures
- Verify property access preservation
- Test escape syntax
- Benchmark performance

### Integration Tests
- Full workflow with formatting
- LLM comprehension comparison
- Token usage measurement
- Error handling

### User Acceptance Tests
- Workflow simplification metrics
- User preference surveys
- Documentation clarity

## Alternatives Considered

### Do Nothing
Keep requiring explicit formatting steps.

**Rejected because:** Poor user experience, higher token costs

### Always Format Everything
Format all template variables regardless of type.

**Rejected because:** Breaks string concatenation, surprising behavior

### Node-Only Solution
Only provide format-json node, no template enhancement.

**Rejected because:** Doesn't solve core usability issue

## Recommendations

1. **Start with format-json node** (immediate, low risk)
2. **Enhance LLM node** (quick win, backward compatible)
3. **Implement template functions** (flexible, explicit)
4. **Consider auto-formatting** (best UX, needs careful design)

## Open Questions

1. Should format depend on destination node type?
2. What's the max size before truncation?
3. Should we support custom format templates?
4. How to handle circular references?
5. Should format be configurable globally?

## Success Metrics

- **Token reduction**: >40% for complex data workflows
- **User satisfaction**: Simplified workflow creation
- **LLM accuracy**: Improved prompt comprehension
- **Performance**: <10ms formatting overhead
- **Adoption**: >50% of workflows use formatting

## Conclusion

Smart template formatting would significantly improve pflow's usability, especially for LLM-heavy workflows. The feature can be implemented incrementally, starting with explicit nodes and evolving toward automatic formatting. The key insight is that formatting happens only at template resolution time, preserving all existing functionality while adding valuable convenience.

---

*Document created: 2025-08-03*
*Status: Future Enhancement (v2.1+)*
*Priority: High - Significant UX improvement*
