# Proxy Mapping Implementation Context - Post-MVP Feature

## Executive Summary

This document captures all context and decisions about proxy mappings for the implementing agent. Proxy mappings are a post-MVP feature that complements template variables by handling specific use cases that template variables cannot address, primarily output collision avoidance.

**Critical Context**: The MVP implements template variables with path support (e.g., `$issue_data.user.login`), which handles most data access needs. Proxy mappings are only needed for specific advanced scenarios.

## Why Proxy Mappings Still Matter (Post-MVP)

Despite template variables with path support handling most use cases, proxy mappings remain necessary for:

### 1. **Output Collision Avoidance** (Primary Use Case)
When multiple nodes of the same type write to the same shared store key:

```json
// Problem: Both API calls write to shared["response"]
{
  "nodes": [
    {"id": "api1", "type": "api-call", "params": {"endpoint": "/users"}},
    {"id": "api2", "type": "api-call", "params": {"endpoint": "/posts"}},
    {"id": "compare", "type": "llm", "params": {
      "prompt": "Compare $response and $response"  // Which response?!
    }}
  ]
}

// Solution: Proxy mappings rename outputs
{
  "mappings": {
    "api1": {"output_mappings": {"response": "users_response"}},
    "api2": {"output_mappings": {"response": "posts_response"}}
  },
  "nodes": [
    {"id": "api1", "type": "api-call", "params": {"endpoint": "/users"}},
    {"id": "api2", "type": "api-call", "params": {"endpoint": "/posts"}},
    {"id": "compare", "type": "llm", "params": {
      "prompt": "Compare $users_response and $posts_response"
    }}
  ]
}
```

### 2. **Type Preservation**
Template variables convert everything to strings. When actual types matter:

```json
// Problem: Template variables stringify everything
{"params": {"retries": "$retry_count"}}  // "3" not 3

// Solution: Proxy mappings preserve types
{
  "mappings": {
    "processor": {"input_mappings": {"retries": "global_retry_count"}}
  }
}
// Node receives actual integer 3, not string "3"
```

### 3. **Interface Adaptation**
When node interfaces don't align naturally:

```json
// youtube-transcript writes to shared["transcript"]
// llm expects shared["prompt"]

// Without proxy mappings, you'd need:
{"params": {"prompt": "$transcript"}}  // Works but converts to string

// With proxy mappings:
{
  "mappings": {
    "analyzer": {"input_mappings": {"prompt": "transcript"}}
  }
}
// More elegant when you need the exact data structure
```

## Critical Implementation Constraints

### Order of Operations (MUST be maintained)
```
1. Proxy mappings applied FIRST (renames keys)
2. Template resolution applied SECOND (uses renamed keys)
```

This order is critical because template variables might reference the renamed keys:
```json
{
  "mappings": {
    "api1": {"output_mappings": {"data": "user_data"}}
  },
  "nodes": [
    {"id": "api1", "type": "fetch-user"},
    {"id": "process", "type": "llm", "params": {
      "prompt": "Process user: $user_data.name"  // References mapped key!
    }}
  ]
}
```

### Integration with Existing Template System

The MVP already has:
- `TemplateResolver` - handles `$variable.path` resolution
- `TemplateAwareNodeWrapper` - wraps nodes for template support
- Resolution happens at `_run()` interception point

Proxy mappings must:
1. Work at the same interception point
2. Apply BEFORE template resolution
3. Be transparent to nodes
4. Compose cleanly with templates

## Implementation Architecture

### Conceptual Design

```python
# The layered approach:
execute_node(node, shared, initial_params):
    # Layer 1: Apply proxy mappings (if any)
    if has_proxy_mappings(node):
        proxy_shared = create_proxy_store(shared, mappings)
    else:
        proxy_shared = shared

    # Layer 2: Apply template resolution (if any)
    # This already exists in MVP - just passes proxy_shared instead of shared
    return node._run(proxy_shared)
```

### NodeAwareSharedStore (Proxy Implementation)

```python
class NodeAwareSharedStore(dict):
    """A proxy that intercepts get/set operations to remap keys."""

    def __init__(self, inner_store, input_mappings=None, output_mappings=None):
        self._inner = inner_store
        self._input_mappings = input_mappings or {}
        self._output_mappings = output_mappings or {}

    def __getitem__(self, key):
        # Remap on read (input mapping)
        mapped_key = self._input_mappings.get(key, key)
        return self._inner[mapped_key]

    def __setitem__(self, key, value):
        # Remap on write (output mapping)
        mapped_key = self._output_mappings.get(key, key)
        self._inner[mapped_key] = value
```

### Path-Based Mappings (Advanced Feature)

While MVP template variables support paths for reading (`$data.user.name`), proxy mappings could support path-based extraction:

```json
{
  "mappings": {
    "processor": {
      "input_mappings": {
        "author": "issue_data.user.login",  // Extract nested value
        "urgent": "issue_data.labels[?name=='urgent']"  // JSONPath query
      }
    }
  }
}
```

This requires:
- JSONPath parser
- Structure documentation (already implemented in Tasks 14/15)
- Careful handling of missing paths

## Integration Points

### 1. IR Schema Extension
Already supports mappings:
```json
{
  "mappings": {
    "<node_id>": {
      "input_mappings": {"<node_expects>": "<shared_has>"},
      "output_mappings": {"<node_writes>": "<shared_wants>"}
    }
  }
}
```

### 2. Compiler Modifications
The compiler needs to:
1. Parse mappings from IR
2. Store them with nodes
3. Apply them during execution

### 3. Execution Flow
```python
# In Flow execution or compiler
if node_id in mappings:
    proxy = NodeAwareSharedStore(
        shared,
        mappings[node_id].get('input_mappings'),
        mappings[node_id].get('output_mappings')
    )
    # Node executes with proxy
else:
    # Node executes with original shared
```

## Design Decisions and Rationale

### Why Not in MVP?

1. **Template paths solve 80% of use cases** - Most workflows just need to access nested data
2. **Complexity vs value** - Adds significant complexity for relatively rare scenarios
3. **Learning curve** - Users need to understand when to use which feature
4. **Clean MVP** - Template variables alone provide clear value

### Why Proxy Over Other Solutions?

1. **Node isolation** - Nodes remain unaware of mappings
2. **Type preservation** - Can pass non-string values
3. **Powerful abstraction** - Can handle complex transformations
4. **Clean separation** - From template variable concerns

### Design Principles

1. **Composability** - Works with templates, not instead of
2. **Transparency** - Nodes don't know about proxies
3. **Fail-safe** - Missing mappings just use original keys
4. **Debuggability** - Clear what's being mapped

## Common Use Cases and Examples

### 1. Multiple API Calls
```json
{
  "nodes": [
    {"id": "github", "type": "api-call", "params": {"url": "https://api.github.com/..."}},
    {"id": "gitlab", "type": "api-call", "params": {"url": "https://gitlab.com/api/..."}},
    {"id": "compare", "type": "llm", "params": {
      "prompt": "Compare GitHub: $github_data vs GitLab: $gitlab_data"
    }}
  ],
  "mappings": {
    "github": {"output_mappings": {"response": "github_data"}},
    "gitlab": {"output_mappings": {"response": "gitlab_data"}}
  }
}
```

### 2. Workflow Composition
When composing workflows that weren't designed to work together:

```json
{
  "mappings": {
    "tweet_analyzer": {
      "input_mappings": {"text": "tweet_content"},
      "output_mappings": {"sentiment": "tweet_sentiment"}
    },
    "email_writer": {
      "input_mappings": {"sentiment_score": "tweet_sentiment.score"}
    }
  }
}
```

### 3. Legacy Node Adaptation
Adapting older nodes with fixed interfaces:

```json
{
  "mappings": {
    "legacy_processor": {
      "input_mappings": {
        "input_file": "source_path",
        "output_file": "dest_path"
      }
    }
  }
}
```

## Testing Considerations

### Unit Tests
- Proxy store behavior in isolation
- Mapping application correctness
- Type preservation
- Path-based extraction

### Integration Tests
- Proxy + template interaction
- Order of operations
- Real node execution with mappings
- Complex workflow scenarios

### Edge Cases
- Circular mappings
- Missing source keys
- Null/undefined handling
- Deep nesting limits

## Implementation Strategy

### Phase 1: Basic Key-to-Key Mapping
- Simple string key remapping
- No path support
- Focus on collision avoidance

### Phase 2: Type Preservation
- Detect when to preserve types
- Handle non-string values

### Phase 3: Path-Based Mappings
- JSONPath support
- Integration with structure docs
- Advanced extraction

## Relationship with Planner

The Natural Language Planner needs to:
1. Detect when multiple nodes write to same key
2. Generate appropriate output_mappings
3. Update template variables to use mapped keys
4. Understand when proxy mappings are necessary

## Open Questions for Implementation

1. **Syntax for path mappings**: JSONPath? Dot notation? Custom?
2. **Error handling**: What if mapped key doesn't exist?
3. **Performance**: Proxy overhead for large shared stores?
4. **Debugging**: How to make mappings visible during execution?
5. **Validation**: How to validate mappings at compile time?

## Key Takeaways

1. **Proxy mappings complement templates** - They solve different problems
2. **Order matters** - Proxy first, then template resolution
3. **Rare but important** - Needed for specific scenarios
4. **Post-MVP priority** - Not needed for initial release
5. **Clean architecture** - Transparent proxy pattern at same interception point

This feature enables advanced workflow composition while maintaining pflow's clean architecture. The implementing agent should focus on the basic key-to-key mapping first, with path-based mappings as a future enhancement.
