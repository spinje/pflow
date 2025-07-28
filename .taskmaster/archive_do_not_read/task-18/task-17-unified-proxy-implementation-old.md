# Template Variables and Proxy Mappings: MVP Implementation Architecture

## Executive Summary

This document guides the implementation of template variable support (Task 18) for pflow's MVP. Template variables enable the "Plan Once, Run Forever" philosophy by allowing workflows to be reused with different parameters.

This document also clarifies the relationship between template variables and proxy mappings - two orthogonal features that together provide flexible workflow composition.

## The Fallback Pattern Foundation

Before understanding template variables and proxy mappings, it's crucial to understand the universal pattern that every pflow node implements:

```python
# In EVERY node's prep() method:
value = shared.get("key") or self.params.get("key")
```

This fallback pattern means **any input can be provided via params instead of the shared store**. This dramatically reduces the need for complex mappings and enables elegant workflow composition.

## Two Orthogonal Features

### Feature 1: Template Variables (Task 18 Focus)
Template variables allow dynamic parameter substitution:

```json
// Workflow definition:
{"params": {"prompt": "Fix issue: $issue_data"}}

// At runtime:
// - $issue_data is replaced with value from shared["issue_data"]
// - Node sees: {"params": {"prompt": "Fix issue: {bug details}"}}
```

**Use Cases:**
- Reusable workflows with different CLI parameters
- Accessing shared store values in parameters
- String composition with dynamic content

### Feature 2: Proxy Mappings (Existing Feature)
Proxy mappings redirect shared store keys to avoid collisions and enable data routing:

```json
{
  "mappings": {
    "api_node_1": {"output_mappings": {"response": "api1_response"}},
    "api_node_2": {"output_mappings": {"response": "api2_response"}}
  }
}
```

**Primary Use Case:**
- Output collision avoidance when multiple nodes write to the same key

**Secondary Use Cases:**
- Path-based data extraction (future enhancement)
- Complex key transformations

## How These Features Reduce Complexity

### Before: Complex Proxy Mappings
```json
// Without fallback pattern + templates:
{
  "nodes": [
    {"id": "fetch", "type": "youtube-transcript"},
    {"id": "analyze", "type": "llm"}
  ],
  "mappings": {
    "analyze": {
      "input_mappings": {"prompt": "transcript"}  // Because llm expects 'prompt'
    }
  }
}
```

### After: Simplified with Templates
```json
// With fallback pattern + templates:
{
  "nodes": [
    {"id": "fetch", "type": "youtube-transcript"},
    {"id": "analyze", "type": "llm", "params": {"prompt": "$transcript"}}
  ]
}
// No proxy mapping needed! The fallback pattern checks params when prompt not in shared
```

## When You Still Need Proxy Mappings

Despite the power of the fallback pattern + templates, proxy mappings remain essential for:

### 1. Output Collision Avoidance (Primary Use Case)
```json
{
  "nodes": [
    {"id": "api1", "type": "api-call"},  // Writes to shared["response"]
    {"id": "api2", "type": "api-call"}   // Also writes to shared["response"]!
  ],
  "mappings": {
    "api1": {"output_mappings": {"response": "api1_response"}},
    "api2": {"output_mappings": {"response": "api2_response"}}
  }
}
```

### 2. Type Preservation (MVP Limitation)
Template variables convert everything to strings:
```json
// shared["retry_count"] = 3 (integer)
{"params": {"max_retries": "$retry_count"}}  // Becomes "3" (string!)

// Need proxy mapping to preserve type:
{"input_mappings": {"max_retries": "retry_count"}}  // Preserves integer
```

## MVP Implementation Architecture

### Order of Operations
1. **Proxy mappings applied first** (renames shared store keys)
2. **Template variables resolved second** (references renamed keys)

This order ensures template variables can reference the post-mapping key names.

### Architectural Separation
These features should be implemented as separate concerns:

1. **NodeAwareSharedStore**: Handles proxy mappings only
2. **TemplateResolver**: Handles template variable substitution
3. **NodeWrapper**: Coordinates both features during execution

### Implementation Strategy

#### Phase 1: Template Resolution
```
TemplateResolver
├── Detects $variables in params
├── Resolves from two sources:
│   ├── CLI parameters (--key=value)
│   └── Shared store values
└── Returns resolved params (strings only for MVP)
```

#### Phase 2: Node Wrapping
```
During compilation:
├── Detect nodes with templates in params
├── Wrap those nodes with TemplateNodeWrapper
└── Wrapper resolves templates just before execution
```

#### Phase 3: Integration with Existing Proxy
```
Execution flow:
├── NodeAwareSharedStore applies mappings
├── TemplateNodeWrapper resolves templates
└── Node executes with resolved values
```

## Key Design Decisions for MVP

1. **String Conversion is Acceptable**: All template values become strings
2. **No Path-Based Templates**: `$issue_data.user.login` not supported (use proxy mappings)
3. **Simple Variable Names**: Only `$variable` or `${variable}` patterns
4. **Two Resolution Sources**: CLI params and shared store only

## Testing Strategy

### Template Resolution Tests
- Basic substitution: `"Fix: $issue"` → `"Fix: Bug #123"`
- Multiple variables: `"$greeting $name"` → `"Hello Alice"`
- Missing variables: Graceful handling
- Edge cases: Variables at start/end of string

### Integration Tests
- Template + proxy mapping interaction
- Order of operations verification
- Fallback pattern with templates
- Type conversion behavior

### End-to-End Workflow Tests
```json
{
  "nodes": [
    {"id": "get", "type": "github-get-issue", "params": {"issue": "$issue_number"}},
    {"id": "fix", "type": "llm", "params": {"prompt": "Fix: $issue_data"}}
  ]
}
```
With `--issue_number=123`, verify entire flow works correctly.

## Implementation Checklist

- [ ] Template detection in params during compilation
- [ ] Template resolution with string conversion
- [ ] Node wrapper for transparent resolution
- [ ] CLI parameter passing mechanism
- [ ] Integration with existing NodeAwareSharedStore
- [ ] Comprehensive test suite
- [ ] Documentation updates

## Future Enhancements (Post-MVP)

1. **Type-Preserving Templates**: Detect when `$var` is the entire value and preserve type
2. **Path-Based Templates**: Support `$issue_data.user.login` syntax
3. **Array/Object Templates**: Handle complex data structures
4. **Template Functions**: Support transformations like `${upper(name)}`

## Complete Example

Let's trace through a workflow that uses both features:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "fetch1",
      "type": "api-call",
      "params": {"url": "$api_endpoint"}  // Template from CLI
    },
    {
      "id": "fetch2",
      "type": "api-call",
      "params": {"url": "$backup_endpoint"}  // Template from CLI
    },
    {
      "id": "analyze",
      "type": "llm",
      "params": {"prompt": "Compare: $api1_response vs $api2_response"}
    }
  ],
  "mappings": {
    "fetch1": {"output_mappings": {"response": "api1_response"}},
    "fetch2": {"output_mappings": {"response": "api2_response"}}
  }
}
```

**Execution Flow:**
1. CLI provides: `--api_endpoint=https://api1.com --backup_endpoint=https://api2.com`
2. fetch1 executes:
   - Template resolves `$api_endpoint` → `"https://api1.com"`
   - Node writes to `shared["response"]`
   - Proxy mapping redirects to `shared["api1_response"]`
3. fetch2 executes:
   - Template resolves `$backup_endpoint` → `"https://api2.com"`
   - Node writes to `shared["response"]`
   - Proxy mapping redirects to `shared["api2_response"]`
4. analyze executes:
   - Templates resolve: `$api1_response` and `$api2_response` from shared store
   - Node receives fully resolved prompt string

This example shows:
- **Templates**: Enable parameterized, reusable workflows
- **Proxy Mappings**: Prevent collision when both API calls write to "response"
- **Order Matters**: Proxy mappings rename keys first, then templates reference the renamed keys

## Summary

The MVP implementation should treat template variables and proxy mappings as separate but complementary features:

1. **Template Variables** solve the reusability problem by allowing dynamic parameters
2. **Proxy Mappings** solve the collision problem by redirecting shared store keys
3. **The Fallback Pattern** reduces the need for many proxy mappings

Together, these features enable flexible, reusable workflow composition while maintaining node atomicity - the core principle that makes pflow powerful.
