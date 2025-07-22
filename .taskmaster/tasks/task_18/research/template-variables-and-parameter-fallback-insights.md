# Template Variables and Parameter Fallback Pattern: Critical Insights

## Executive Summary

This document captures critical insights about how template variables, the exclusive parameter fallback pattern, and proxy mappings interact in pflow. These insights fundamentally affect how the planner generates workflows and reveals that the system is more flexible than initially understood.

## Table of Contents

1. [The Exclusive Parameter Fallback Pattern](#the-exclusive-parameter-fallback-pattern)
2. [Template Variables in JSON IR](#template-variables-in-json-ir)
3. [How Template Variables Resolve](#how-template-variables-resolve)
4. [When Proxy Mappings Are Still Needed](#when-proxy-mappings-are-still-needed)
5. [The Planning vs Execution Separation](#the-planning-vs-execution-separation)
6. [Architectural Implications](#architectural-implications)

## The Exclusive Parameter Fallback Pattern

### Core Pattern

Every pflow node implements a universal fallback pattern in its `prep()` method:

```python
# From actual node implementations (verified in codebase)
value = shared.get("key") or self.params.get("key")
```

This pattern means:
1. First check: `shared["key"]` (dynamic value from previous nodes)
2. Fallback: `self.params["key"]` (static value or template variable)

### What This Enables

**ALL inputs can be provided as parameters**, not just the "exclusive parameters" shown in the context builder output.

Example from `src/pflow/nodes/file/read_file.py`:
```python
def prep(self, shared: dict) -> tuple[str, str]:
    # Check shared store first, then params
    file_path = shared.get("file_path") or self.params.get("file_path")
    if not file_path:
        raise ValueError("Missing required 'file_path' in shared store or params")
```

### Context Builder Output vs Reality

The context builder shows only "exclusive parameters" to reduce redundancy:
```markdown
### write-file
**Inputs**: `content`, `file_path`, `encoding`
**Outputs**: `written`, `error` (error)
**Parameters**: `append`  # Only 'append' shown - it's exclusive!
```

But the planner can use ANY input as a parameter:
```json
{
  "type": "write-file",
  "params": {
    "file_path": "/tmp/output.txt",  // Works even though not listed in Parameters!
    "content": "Hello World",         // Also works!
    "append": true                    // The exclusive parameter
  }
}
```

### Evidence

This pattern is documented in `.taskmaster/knowledge/patterns.md` as "Shared Store Inputs as Automatic Parameter Fallbacks" and is implemented universally across all pflow nodes.

## Template Variables in JSON IR

### Where Template Variables Live

Template variables can **ONLY** appear in the `params` field of nodes in the JSON IR:

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "node-id",
      "type": "node-type",
      "params": {"key": "$variable"}  // ONLY place for template variables
    }
  ]
}
```

### What's NOT in the IR

The JSON IR does **NOT** contain:
- Explicit "reads" or "writes" fields
- Interface definitions
- Data flow specifications

These are defined in the node's Python implementation and documented in its docstring. The IR is purely an execution format.

### Template Variable Syntax

Template variables use the `$variable` or `${variable}` syntax:
- `$issue_number` - Simple variable reference
- `${issue_number}` - Alternative syntax (equivalent)
- `"Fix issue #$issue_number"` - Variables within strings

## How Template Variables Resolve

### Direct Mapping to Shared Store

Template variables map directly to shared store keys:
- `$foo` resolves to `shared["foo"]`
- `$bar` resolves to `shared["bar"]`

### Resolution Process

From `.taskmaster/tasks/task_18/task-17-template-variable-implementation-guide.md`:

1. **Compile-time resolution**: Initial parameters from CLI are substituted
2. **Runtime resolution**: Shared store references are resolved during execution

Example flow:
```json
// Node 1 writes to shared["issue_data"]
// Node 2 can reference it with $issue_data
{
  "nodes": [
    {"id": "get", "type": "github-get-issue"},  // Writes to shared["issue_data"]
    {"id": "fix", "type": "llm", "params": {"prompt": "Fix: $issue_data"}}
  ]
}
```

### The Power of Combining Patterns

The fallback pattern + template variables enables flexible data routing:

```json
// Scenario: path-generator writes to shared["path"]
// read-file needs file_path

// Option 1: Use proxy mapping
{
  "mappings": {
    "read": {"input_mappings": {"file_path": "path"}}
  }
}

// Option 2: Use template variable in params (simpler!)
{
  "nodes": [
    {"id": "read", "type": "read-file", "params": {"file_path": "$path"}}
  ]
}
```

## When Proxy Mappings Are Still Needed

### 1. Output Collision Avoidance (Primary Use Case)

When multiple nodes of the same type write to the same shared store key:

```json
{
  "nodes": [
    {"id": "api1", "type": "api-call"},  // Writes to shared["response"]
    {"id": "api2", "type": "api-call"},  // Also writes to shared["response"]!
  ],
  "mappings": {
    "api1": {"output_mappings": {"response": "api1_response"}},
    "api2": {"output_mappings": {"response": "api2_response"}}
  }
}
```

Template variables CANNOT solve this because they only affect inputs, not outputs.

### 2. Path-Based Data Extraction

Current template variables don't support path-based access (though they could be extended):

```json
// Node writes complex structure:
shared["issue_data"] = {
  "user": {"login": "john"},
  "labels": [{"name": "bug"}]
}

// To extract just the username, need proxy mapping:
{
  "mappings": {
    "analyze": {"input_mappings": {"author": "issue_data.user.login"}}
  }
}

// Future possibility: $issue_data.user.login
```

### 3. Complex Data Transformations

When simple substitution isn't enough:
- Array to string conversion
- Data filtering or aggregation
- Computed values

### Key Insight: Collision Avoidance is Primary

Most input mapping needs can be handled by template variables in params. The core remaining use case for proxy mappings is **output collision avoidance** when running multiple instances of the same node type.

## The Planning vs Execution Separation

### Planning Time Knowledge

The planner knows what nodes read/write from the **context builder output**:

```markdown
### read-file
Read content from a file and add line numbers for display.

**Inputs**: `file_path`, `encoding`
**Outputs**: `content`, `error` (error)
**Parameters**: none
```

This information comes from:
1. Node docstrings (source of truth)
2. Metadata extractor (parses docstrings)
3. Context builder (formats for LLM)

### Execution Time Structure

The JSON IR contains only execution instructions:
```json
{
  "nodes": [{"id": "n1", "type": "read-file", "params": {...}}],
  "edges": [{"from": "n1", "to": "n2"}]
}
```

No interface information is needed at execution time.

### Planning Process Example

```
User: "read a file and analyze it"

Planner sees from context:
- read-file: Outputs: content
- llm: Inputs: prompt

Planner thinks:
1. read-file writes "content"
2. llm needs "prompt"
3. Mismatch! Options:
   a) Proxy mapping: {"llm": {"input_mappings": {"prompt": "content"}}}
   b) Template in params: {"params": {"prompt": "$content"}}
   c) Template with text: {"params": {"prompt": "Analyze this: $content"}}

Option b or c is simpler!
```

## Architectural Implications

### 1. Simplified Workflow Generation

The planner can generate cleaner workflows by preferring template variables over proxy mappings:
- Use params with `$variables` for input adaptation
- Only use proxy mappings for output collision avoidance

### 2. Reduced Complexity

Many workflows that seemed to need complex proxy mappings actually don't:
```json
// Complex approach with proxy mappings
{
  "mappings": {
    "node2": {"input_mappings": {"text": "content"}},
    "node3": {"input_mappings": {"data": "result"}}
  }
}

// Simpler approach with template variables
{
  "nodes": [
    {"id": "node2", "type": "process", "params": {"text": "$content"}},
    {"id": "node3", "type": "analyze", "params": {"data": "$result"}}
  ]
}
```

### 3. Future Enhancement Possibility

If template variables were extended to support paths:
- `$issue_data.user.login` - Navigate nested structures
- `$results[0].value` - Array access
- Further reduce need for proxy mappings

### 4. Clear Separation of Concerns

- **Template variables**: Handle input flexibility and data access
- **Proxy mappings**: Handle namespace management and output collision
- **Fallback pattern**: Enables the entire system

## Conclusions

1. **The exclusive parameter fallback pattern is universal** - All nodes implement it, making any input available as a parameter.

2. **Template variables + fallback pattern eliminate many proxy mapping needs** - Most input adaptations can be handled with template variables in params.

3. **Collision avoidance is the primary remaining use case for proxy mappings** - When multiple nodes write to the same key, output mappings are essential.

4. **The system is more elegant than initially apparent** - The combination of patterns creates a flexible, powerful system with minimal complexity.

5. **Planning and execution are cleanly separated** - The planner has full interface knowledge; the IR has only execution instructions.

## References

- Node implementations: `/src/pflow/nodes/`
- Pattern documentation: `/.taskmaster/knowledge/patterns.md`
- Template variable guide: `/.taskmaster/tasks/task_18/task-17-template-variable-implementation-guide.md`
- Context builder: `/src/pflow/planning/context_builder.py`
- IR schema: `/src/pflow/core/ir_schema.py`
- PocketFlow source: `/pocketflow/__init__.py`
