# Template Variables in pflow

Complete reference guide for template variables in pflow workflows.

> **Note on examples**: JSON code blocks throughout this document show the **internal IR dict structure** that all workflows compile to. Users write `.pflow.md` markdown files, which `parse_markdown()` converts to this IR structure. Template syntax (`${node.output}`) works identically in both the authored markdown format and the internal IR.

## Table of Contents

- [Overview](#overview)
- [Syntax and Format](#syntax-and-format)
- [Resolution Process](#resolution-process)
- [Where Templates Can Be Used](#where-templates-can-be-used)
- [Validation System](#validation-system)
- [Type Checking](#type-checking)
- [Namespacing Integration](#namespacing-integration)
- [Error Handling](#error-handling)
- [Examples](#examples)
- [Performance and Security](#performance-and-security)
- [Configuration](#configuration)
- [Best Practices](#best-practices)
- [Advanced Features](#advanced-features)
- [Debugging](#debugging)

---

## Overview

Template variables allow dynamic data flow between nodes in pflow workflows. They enable you to reference:
- Workflow inputs
- Outputs from previous nodes
- Runtime data from the shared store

**Core principle**: Template variables are resolved at runtime, transforming static workflow definitions into dynamic, data-driven pipelines.

**Related tasks**:
- Task 18: Initial template variable system
- Task 35: Migration from `$variable` to `${variable}` syntax
- Task 84: Schema-aware type checking
- Task 85: Runtime template resolution hardening

---

## Syntax and Format

### Current Syntax

Since Task 35, pflow uses **explicit curly braces** for template variables:

```
${variable}
```

**Why the change?**: The old `$variable` syntax had ambiguous boundaries causing parsing failures in complex strings like `data_$timestamp.json`.

### Pattern Recognition

The template parser uses this regex pattern:

```python
r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:(?:\[[\d]+\])?(?:\.[a-zA-Z_][\w-]*(?:\[[\d]+\])?)*)?)\}"
```

This supports:
- Simple variables
- Nested object paths
- Array access
- Combined patterns

### Supported Patterns

#### Simple Variables

```json
{
  "file_path": "${input_file}",
  "user_name": "${user_name}",
  "api-key": "${api-key}"
}
```

**Note**: Hyphens (`-`) are supported in variable names!

#### Nested Paths (Dot Notation)

```json
{
  "email": "${user.profile.email}",
  "count": "${response.data.metadata.count}"
}
```

#### Array Access

```json
{
  "first_item": "${items[0]}",
  "name": "${users[5].name}",
  "text": "${messages[0].text}"
}
```

#### Combined Nested and Array

```json
{
  "title": "${fetch-data.items[0].title}",
  "value": "${api-response.data[2].field.subfield}"
}
```

### Character Rules

| Part | Rule | Examples |
|------|------|----------|
| **Start** | Letter or underscore | `${a}`, `${_temp}`, `${User}` |
| **Middle** | Letters, digits, underscores, **hyphens** | `${user_id}`, `${api-key}`, `${item2}` |
| **Invalid** | Cannot start with digit, no special chars except `-` and `_` | ❌ `${123}`, ❌ `${@var}`, ❌ `${my$var}` |

### Escaping Literals

To output literal `${...}` text without resolution:

```json
{
  "message": "$${variable}"
}
```

**Output**: `${variable}` (literal string, not resolved)

**Limitation**: No backslash escape (`\${var}`) - this is known technical debt.

---

## Resolution Process

### Resolution Order (Priority)

Template variables are resolved in this order:

1. **`initial_params`** - From planner extraction or CLI arguments
2. **Shared store** - Runtime data from node outputs
3. **Workflow inputs** - Declared inputs with defaults

**Example**:

```python
# If both exist, initial_params wins
initial_params = {"user_id": "from_cli"}
shared = {"user_id": "from_node"}
inputs = {"user_id": {"default": "default_value"}}

# Resolution: "${user_id}" → "from_cli"
```

### Core Resolution Logic

Located: `src/pflow/runtime/template_resolver.py`

```python
class TemplateResolver:
    @staticmethod
    def resolve_template(template: str, context: dict[str, Any]) -> str:
        """Resolve all template variables in a string.

        Variables that cannot be resolved are left unchanged.

        Args:
            template: String possibly containing ${var} patterns
            context: Dictionary containing variable values

        Returns:
            String with all resolvable templates replaced

        Example:
            >>> resolve_template("Hello ${name}", {"name": "Alice"})
            "Hello Alice"

            >>> resolve_template("${missing}", {})
            "${missing}"  # Left as-is if not found
        """
```

### Path Traversal

#### Dot Notation

```python
# Template: ${user.profile.email}
#
# Traversal:
# 1. Split on dots: ["user", "profile", "email"]
# 2. Navigate: context["user"]["profile"]["email"]
# 3. Return final value
```

#### Array Access

```python
# Template: ${items[0].name}
#
# Traversal:
# 1. Split: ["items[0]", "name"]
# 2. Extract index from "items[0]" → index=0
# 3. Navigate: context["items"][0]["name"]
# 4. Return final value
```

#### Complex Example

```python
# Template: ${api.endpoints[2].routes[0].path}
#
# Context:
{
  "api": {
    "endpoints": [
      ...,
      ...,
      {
        "routes": [
          {"path": "/users"},
          ...
        ]
      }
    ]
  }
}
#
# Resolution: "/users"
```

### Type Preservation (Critical!)

This is one of the most important features of the template system:

#### Simple Template → Type Preserved

```python
context = {
    "count": 42,
    "enabled": True,
    "price": 19.99,
    "data": {"key": "value"},
    "items": [1, 2, 3],
    "nothing": None
}

# Resolve entire parameter as template
resolve_value("count", context)    # → 42 (int)
resolve_value("enabled", context)  # → True (bool)
resolve_value("price", context)    # → 19.99 (float)
resolve_value("data", context)     # → {"key": "value"} (dict)
resolve_value("items", context)    # → [1, 2, 3] (list)
resolve_value("nothing", context)  # → None
```

#### Complex Template → Always String

```python
# Template is part of larger string
resolve_template("Count: ${count}", context)       # → "Count: 42" (str)
resolve_template("Status: ${enabled}", context)    # → "Status: True" (str)
resolve_template("Data: ${data}", context)         # → "Data: {\"key\": \"value\"}" (str)
```

#### Conversion Rules for String Context

When a template is embedded in a string:

| Python Type | String Representation |
|-------------|----------------------|
| `None` | `""` (empty string) |
| `True` | `"True"` |
| `False` | `"False"` |
| `0` | `"0"` |
| `42` | `"42"` |
| `[]` | `"[]"` |
| `{}` | `"{}"` |
| `{"a": 1}` | `"{\"a\": 1}"` (valid JSON) |
| `[1, 2]` | `"[1, 2]"` (valid JSON) |

**Why this matters**: Nodes can receive the correct type without manual parsing!

```json
{
  "id": "process",
  "type": "llm",
  "params": {
    "max_tokens": "${token_limit}",
    "stream": "${enable_streaming}"
  }
}
```

If `token_limit=100` (int) and `enable_streaming=False` (bool), the LLM node receives:
- `max_tokens=100` (int, not "100")
- `stream=False` (bool, not "False")

### Inline Object Type Preservation (Task 103)

Prior to v0.6.0, simple templates inside nested structures were incorrectly stringified:

**Before (v0.5.x - Bug):**
```python
context = {"config": {"key": "value"}}
resolve_nested({"setting": "${config}"}, context)
# → {"setting": "{\"key\": \"value\"}"}  ❌ Double-serialized!
```

**After (v0.6.0+ - Fixed):**
```python
context = {"config": {"key": "value"}}
resolve_nested({"setting": "${config}"}, context)
# → {"setting": {"key": "value"}}  ✅ Type preserved!
```

This enables powerful patterns like combining multiple data sources:

```json
{
  "stdin": {"a": "${data-a}", "b": "${data-b}"},
  "command": "jq '.a + .b'"
}
```

**Rules:**
- Simple template (`${var}`) → Type preserved (dict, list, int, bool, None)
- Complex template (`"text ${var}"`) → String (unchanged behavior)

---

## Where Templates Can Be Used

### Supported Locations

✅ **Node parameters** - Any string parameter
✅ **Workflow inputs** - When calling workflows
✅ **Nested dictionaries** - Recursively resolved
✅ **Lists/arrays** - Each item resolved

### Node Parameter Examples

```json
{
  "nodes": [
    {
      "id": "read-file",
      "type": "file.read",
      "params": {
        "file_path": "${input_file}"
      }
    },
    {
      "id": "process",
      "type": "llm",
      "params": {
        "prompt": "Summarize: ${read-file.content}",
        "model": "${llm_model}",
        "max_tokens": "${max_tokens}"
      }
    }
  ]
}
```

### Nested Dictionary Example

```json
{
  "id": "api-call",
  "type": "http",
  "params": {
    "method": "POST",
    "url": "${api_endpoint}",
    "headers": {
      "Authorization": "Bearer ${api_token}",
      "Content-Type": "application/json",
      "X-User-ID": "${user_id}"
    },
    "body": {
      "user": "${user_name}",
      "data": "${payload.data}",
      "metadata": {
        "timestamp": "${timestamp}",
        "version": "${api_version}"
      }
    }
  }
}
```

All templates in nested structures are resolved recursively.

### Array Example

```json
{
  "id": "send-emails",
  "type": "email.send_batch",
  "params": {
    "recipients": [
      "${admin_email}",
      "${user_email}",
      "${backup_email}"
    ],
    "subject": "Report for ${date}",
    "body": "${email_body}"
  }
}
```

### Workflow Input Example

```json
{
  "workflow": "saved-workflow-name",
  "inputs": {
    "user_id": "${current_user}",
    "config": "${app_config}",
    "items": "${filtered_items}"
  }
}
```

---

## Validation System

pflow uses **two-phase validation** to ensure template correctness:

1. **Compile-time validation** - Before execution starts
2. **Runtime validation** - During execution

### Phase 1: Compile-Time Validation

Located: `src/pflow/runtime/template_validator.py`

```python
def validate_workflow_templates(
    workflow_ir: dict,
    available_params: dict,
    registry: Registry
) -> tuple[list[str], list[ValidationWarning]]:
    """Validates all template variables before execution.

    Returns:
        (errors, warnings) - Errors prevent execution, warnings don't
    """
```

#### Checks Performed

**1. Malformed Syntax**

Detects:
- `${unclosed` - Missing closing brace
- `${}` - Empty template
- `${ }` - Whitespace-only template
- `${123}` - Invalid identifier (starts with digit)

**2. Path Existence**

Verifies that referenced paths exist in node interfaces:

```json
{
  "id": "fetch",
  "type": "http",
  "params": {
    "url": "https://api.example.com"
  }
},
{
  "id": "process",
  "type": "llm",
  "params": {
    "prompt": "${fetch.response.items[0].title}"
    //        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    //        Validator checks: Does http node output 'response'?
    //                          Is 'response' an object with 'items'?
    //                          Is 'items' an array?
    //                          Do array items have 'title'?
  }
}
```

**3. Type Compatibility**

Checks if template type matches parameter expectation:

```json
{
  "id": "count-items",
  "type": "shell",
  "params": {
    "command": "echo ${fetch.response}"
    //         ^^^^^^^^^^^^^^^^^^^^
    //         ERROR: fetch.response is 'dict' but 'command' expects 'str'
  }
}
```

**4. Unused Inputs**

Warns if declared inputs are never used:

```json
{
  "inputs": {
    "user_id": {"type": "str", "required": true},
    "api_key": {"type": "str", "required": true}
  },
  "nodes": [
    {
      "params": {
        "user": "${user_id}"
        // Warning: 'api_key' is declared but never used
      }
    }
  ]
}
```

### Phase 2: Runtime Validation

Located: `src/pflow/runtime/node_wrapper.py`

Runtime validation happens **after** template resolution, detecting:

#### Complete Unresolution

```python
# Original: {"url": "${api_endpoint}"}
# Resolved: {"url": "${api_endpoint}"}  (unchanged!)
#
# Error: Template variable ${api_endpoint} has no valid source
```

#### Partial Resolution

```python
# Original: {"message": "User ${name} has ${count} items"}
# Resolved: {"message": "User Alice has ${count} items"}
#
# Error: Partial template resolution detected
#        (${count} was not resolved)
```

This is detected by comparing template variables before and after resolution using set intersection.

#### False Positive Handling

Some nodes legitimately output data containing `${...}` patterns:

```python
# MCP node returns: {"text": "Cost is ${price}"}
# This is DATA, not a template!
#
# Detection: Check if original param was a template
#            If not, don't validate resolution
```

### Resolution Modes

#### Strict Mode (Default)

```python
# Fail immediately on unresolved templates
try:
    execute_node(params)
except ValueError as e:
    # Triggers repair system (currently gated — Task 107 Decision 26)
    repair_workflow(workflow_ir, error=e)
```

**When to use**: Production workflows, API calls with required fields

#### Permissive Mode

```python
# Log warning, continue execution
if unresolved_templates:
    shared["__template_errors__"] = {
        "node_id": unresolved_templates
    }
    logger.warning(f"Unresolved templates: {unresolved_templates}")
# Continue execution
```

**When to use**: Exploratory workflows, optional parameters

---

## Type Checking

### Schema-Aware Type Validation

Located: `src/pflow/runtime/type_checker.py`

pflow validates that template types match parameter expectations using node interface schemas.

#### Type Compatibility Matrix

```python
TYPE_COMPATIBILITY_MATRIX = {
    "str": ["any", "str", "string", "dict", "object", "list", "array"],
    "int": ["any", "int", "integer", "float", "number", "str", "string"],
    "float": ["any", "float", "number", "str", "string"],
    "bool": ["any", "bool", "boolean", "str", "string"],
    "dict": ["any", "dict", "object", "str", "string"],  # dict serializes to JSON
    "list": ["any", "list", "array", "str", "string"],   # list serializes to JSON
    "NoneType": ["any", "null", "none", "str", "string"],
}
```

**Interpretation**:
- `str` can be used where `str`, `dict`, `list`, or `any` is expected (because of JSON auto-parsing)
- `int` can be used where `int`, `float`, `number`, or `str` is expected
- `dict` and `list` can be used where `str` is expected (auto-serializes to JSON)

#### Type Inference

```python
def infer_template_type(
    template: str,
    workflow_ir: dict,
    node_outputs: dict
) -> str:
    """Infer the type of a template variable.

    Examples:
        ${node.result} → "dict"
        ${node.result.count} → "int"
        ${node.items[0].name} → "str"
        ${node.enabled} → "bool"
    """
```

**Type inference uses**:
1. Node interface schemas from registry
2. Path traversal through nested structures
3. Array element type information

#### Type Mismatch Error Messages

When type checking fails, pflow provides actionable error messages:

```
Type mismatch in node 'send-msg' parameter 'markdown_text':
  template ${fetch.response} has type 'dict' but parameter expects 'str'

Available outputs from 'fetch':
  ✓ ${fetch.response} (dict)
  ✓ ${fetch.response.messages} (array)
  ✓ ${fetch.response.messages[0]} (dict)
  ✓ ${fetch.response.messages[0].text} (string)  ← Try this!

Did you mean: ${fetch.response.messages[0].text}?

Common fix: Change ${fetch.response} to ${fetch.response.messages[0].text}
```

This guides users to the correct template path. (The repair system, which also uses these suggestions, is currently gated — Task 107 Decision 26.)

### Type Checking Examples

#### Valid Type Usage

```json
{
  "nodes": [
    {
      "id": "fetch",
      "type": "http",
      "outputs": {
        "response": {
          "type": "dict",
          "structure": {
            "count": {"type": "int"},
            "items": {
              "type": "array",
              "items": {"type": "dict"}
            }
          }
        }
      }
    },
    {
      "id": "process",
      "type": "llm",
      "params": {
        "max_tokens": "${fetch.response.count}",
        // ✓ Valid: int → int

        "prompt": "Process ${fetch.response.items[0]}",
        // ✓ Valid: dict → str (serialized)

        "stream": "${enable_streaming}"
        // ✓ Valid: bool → bool
      }
    }
  ]
}
```

#### Invalid Type Usage

```json
{
  "id": "shell",
  "type": "shell",
  "params": {
    "command": "echo ${fetch.response}"
    // ✗ ERROR: dict cannot be used directly
    //          Use ${fetch.response.specific_field} instead
  }
}
```

```json
{
  "id": "api-call",
  "type": "http",
  "params": {
    "body": "${user_name}"
    // ✗ ERROR: str → dict mismatch
    //          'body' expects dict, not str
  }
}
```

---

## Namespacing Integration

By default, pflow uses **automatic namespacing** (Task 9) to prevent shared store collisions.

### Namespaced References

When `enable_namespacing: true` (default):

```json
{
  "nodes": [
    {
      "id": "fetch-data",
      "type": "http",
      "params": {"url": "https://api.example.com"}
    },
    {
      "id": "process",
      "type": "llm",
      "params": {
        "prompt": "Process ${fetch-data.response.data}"
        //                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^
        //                  node-id.output-key.field
      }
    }
  ]
}
```

**How it works**:
1. Node `fetch-data` outputs: `shared["fetch-data"] = {"response": {...}}`
2. Template `${fetch-data.response.data}` resolves to: `shared["fetch-data"]["response"]["data"]`

### Without Namespacing

When `enable_namespacing: false`:

```json
{
  "enable_namespacing": false,
  "nodes": [
    {
      "id": "fetch",
      "type": "http",
      "params": {"url": "..."}
    },
    {
      "id": "process",
      "type": "llm",
      "params": {
        "prompt": "${response.data}"
        //        ^^^^^^^^^^^^^^^^^
        //        Direct shared store key
      }
    }
  ]
}
```

**Warning**: Without namespacing, nodes can overwrite each other's data!

### Special Bypass Keys

These keys **always** go to the root shared store (bypassing namespaces):

- `__execution__` - Checkpoint tracking
- `__llm_calls__` - LLM usage tracking
- `__cache_hits__` - Cache hit tracking
- `__warnings__` - API warnings
- `__template_errors__` - Template resolution errors
- `__modified_nodes__` - Repair tracking (repair system gated — Task 107 Decision 26)
- `__non_repairable_error__` - Skip repair flag (repair system gated)
- `__progress_callback__` - Progress updates

**Why?**: These are system-level metadata, not node outputs.

---

## Error Handling

### Error Categories

#### 1. Variable Not Found

**Strict Mode (Default)**:

```python
# Template: ${missing_variable}
# Context: {}
#
# Error: Template variable ${missing_variable} has no valid source
# → Raises ValueError
# → Triggers repair system (currently gated — Task 107 Decision 26)
```

**Permissive Mode**:

```python
# Template: ${missing_variable}
# Context: {}
#
# Warning: Template variable ${missing_variable} could not be resolved
# → Logs warning
# → Stores in shared["__template_errors__"]
# → Continues execution
```

#### 2. Type Mismatch

```python
# Node parameter expects: str
# Template provides: dict
#
# Error:
# Type mismatch in node 'send-message' parameter 'text':
#   template ${api_response} has type 'dict' but parameter expects 'str'
#
# → Fails compilation
# → Shows available fields with correct types
```

#### 3. Invalid Syntax

```python
# Malformed templates
"${unclosed"  → "Malformed template syntax: missing '}'"
"${}"         → "Empty template variable"
"${ }"        → "Empty template variable"
"${123var}"   → "Invalid identifier: cannot start with digit"
"${my@var}"   → "Invalid identifier: illegal character '@'"
```

#### 4. Partial Resolution

Introduced in Task 85 (GitHub #96):

```python
# Original template: "User ${name} has ${count} items"
# Available data: {"name": "Alice"}
#
# Resolution attempt: "User Alice has ${count} items"
#
# Detection:
# - Before: {"name", "count"}  (2 variables)
# - After:  {"count"}           (1 variable remains)
# - Intersection: {"count"}     (unresolved)
#
# Error: Partial template resolution detected
#        The following variables could not be resolved: ${count}
```

This prevents silent failures where some data is missing.

### Error Recovery

pflow integrates template validation with the **repair system** (currently gated pending markdown format prompt rewrites — Task 107 Decision 26):

```
┌─────────────────────────────────────┐
│ 1. Compile Workflow                 │
│    ↓                                │
│    Template Validation              │
│    └→ Errors found?                 │
│       └→ Return errors              │
└─────────────────────────────────────┘
         ↓ Errors
┌─────────────────────────────────────┐
│ 2. Repair Service                   │
│    ↓                                │
│    Send to LLM with:                │
│    - Original workflow IR           │
│    - Validation errors              │
│    - Available node interfaces      │
│    ↓                                │
│    LLM fixes template references    │
│    └→ Returns repaired IR           │
└─────────────────────────────────────┘
         ↓ Repaired IR
┌─────────────────────────────────────┐
│ 3. Re-validate                      │
│    ↓                                │
│    Template Validation (again)      │
│    └→ Fixed? Execute!               │
│       └→ Still broken? Fail.        │
└─────────────────────────────────────┘
```

---

## Examples

### Test Examples

From `tests/test_runtime/test_template_resolver.py`:

#### Simple Resolution

```python
context = {"url": "https://example.com"}
assert resolve_template("Visit ${url}", context) == "Visit https://example.com"
```

#### Nested Paths

```python
context = {"data": {"title": "Test", "count": 42}}
assert resolve_template("Title: ${data.title}", context) == "Title: Test"
assert resolve_value("data.count", context) == 42  # Type preserved!
```

#### Unresolved Variables

```python
context = {}
assert resolve_template("Missing: ${undefined}", context) == "Missing: ${undefined}"
# Left as-is for debugging
```

#### Array Access

```python
context = {
    "items": [
        {"name": "Alice", "age": 30},
        {"name": "Bob", "age": 25}
    ]
}
assert resolve_value("items[0].name", context) == "Alice"
assert resolve_value("items[1].age", context) == 25
```

#### Type Preservation

```python
context = {
    "count": 42,
    "enabled": True,
    "data": {"key": "value"},
    "empty": None
}

# Simple template preserves type
assert resolve_value("count", context) == 42        # int, not "42"
assert resolve_value("enabled", context) is True    # bool, not "True"
assert resolve_value("data", context) == {"key": "value"}  # dict
assert resolve_value("empty", context) is None      # None, not ""

# Complex template becomes string
assert resolve_template("Count: ${count}", context) == "Count: 42"
assert resolve_template("Status: ${enabled}", context) == "Status: True"
```

### Real Workflow Examples

#### File Operations

```json
{
  "inputs": {
    "source_dir": {"type": "str"},
    "dest_dir": {"type": "str"},
    "file_name": {"type": "str"}
  },
  "nodes": [
    {
      "id": "read-source",
      "type": "file.read",
      "params": {
        "file_path": "${source_dir}/${file_name}"
      }
    },
    {
      "id": "write-dest",
      "type": "file.write",
      "params": {
        "file_path": "${dest_dir}/${file_name}",
        "content": "${read-source.content}"
      }
    }
  ]
}
```

#### API Workflow with Error Handling

```json
{
  "nodes": [
    {
      "id": "fetch-data",
      "type": "http",
      "params": {
        "method": "GET",
        "url": "${api_endpoint}/users/${user_id}",
        "headers": {
          "Authorization": "Bearer ${api_token}"
        }
      }
    },
    {
      "id": "validate",
      "type": "llm",
      "params": {
        "prompt": "Validate this response: ${fetch-data.response}",
        "model": "claude-3-5-sonnet-20241022"
      }
    },
    {
      "id": "process",
      "type": "shell",
      "params": {
        "command": "jq '.name' <<< '${fetch-data.response.user}'"
      }
    }
  ]
}
```

#### LLM with Dynamic Configuration

```json
{
  "inputs": {
    "task": {"type": "str"},
    "model": {"type": "str", "default": "claude-3-5-sonnet-20241022"},
    "max_tokens": {"type": "int", "default": 1000},
    "temperature": {"type": "float", "default": 0.7}
  },
  "nodes": [
    {
      "id": "execute-task",
      "type": "llm",
      "params": {
        "prompt": "${task}",
        "model": "${model}",
        "max_tokens": "${max_tokens}",
        "temperature": "${temperature}"
      }
    }
  ]
}
```

Note: Type preservation ensures `max_tokens` receives `1000` (int), not `"1000"` (str).

#### MCP Integration

```json
{
  "nodes": [
    {
      "id": "generate-summary",
      "type": "llm",
      "params": {
        "prompt": "Summarize: ${input_text}",
        "model": "claude-3-5-sonnet-20241022"
      }
    },
    {
      "id": "send-slack",
      "type": "mcp-slack-composio-SLACK_SEND_MESSAGE",
      "params": {
        "channel": "${slack_channel}",
        "markdown_text": "${generate-summary.response.message}"
      }
    }
  ]
}
```

#### GitHub Workflow

```json
{
  "nodes": [
    {
      "id": "get-pr",
      "type": "github.get_pull_request",
      "params": {
        "owner": "${repo_owner}",
        "repo": "${repo_name}",
        "pr_number": "${pr_number}"
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "params": {
        "prompt": "Analyze this PR: ${get-pr.pull_request.title}\n\n${get-pr.pull_request.body}"
      }
    },
    {
      "id": "comment",
      "type": "github.create_issue_comment",
      "params": {
        "owner": "${repo_owner}",
        "repo": "${repo_name}",
        "issue_number": "${pr_number}",
        "body": "${analyze.response.message}"
      }
    }
  ]
}
```

#### Claude Code Integration with Cost Tracking

```json
{
  "nodes": [
    {
      "id": "generate",
      "type": "claude-code",
      "params": {
        "content": "${user_request}",
        "message": "Generate code for: ${user_request}"
      }
    },
    {
      "id": "report",
      "type": "file.write",
      "params": {
        "file_path": "output.txt",
        "content": "Code: ${generate.response}\n\nCost: $${generate._claude_metadata.total_cost_usd}"
      }
    }
  ]
}
```

Note: `$${...}` escapes to literal `${...}` in the output.

---

## Performance and Security

### Performance Characteristics

| Operation | Complexity | Typical Time |
|-----------|------------|--------------|
| Template detection | O(1) string check | ~0.001ms |
| Simple resolution | O(1) dict lookup | ~0.01ms |
| Nested path resolution | O(n) where n=path depth | ~0.05ms |
| Array access | O(1) list index | ~0.01ms |
| Full workflow validation | O(t) where t=template count | ~1-10ms |

**Optimization**: Template detection uses fast string prefix check (`"${"` in string) before regex.

### Security Considerations

#### No Code Execution

```python
# Safe: Pure string substitution
"${user_input}" → "'; DROP TABLE users; --"
# No SQL injection risk - just a string value

# pflow does NOT use:
eval()   # ✗ Never used
exec()   # ✗ Never used
```

#### Size Limits

From Task 85:

```python
# Auto-parsing JSON strings limited to 10MB
if len(json_string) > 10 * 1024 * 1024:
    raise ValueError("JSON string too large to auto-parse")
```

**Why**: Prevents memory exhaustion from malicious/accidental large payloads.

#### Error Message Sanitization

```python
# User input in error messages is sanitized
error_msg = f"Template {template!r} failed"
# Uses !r to safely escape special characters
```

**Why**: Prevents log injection attacks.

#### No Arbitrary Code

```python
# Templates can ONLY reference data
"${node.output}"  # ✓ Data reference
"${eval('ls')}"   # ✗ Not supported - literal string
```

There is no mechanism to execute code through templates.

---

## Configuration

### Workflow-Level Configuration

```json
{
  "enable_namespacing": true,
  "template_resolution_mode": "strict",
  "inputs": {
    "user_id": {
      "type": "str",
      "required": true,
      "description": "User identifier"
    },
    "count": {
      "type": "int",
      "default": 10,
      "description": "Number of items to process"
    }
  },
  "nodes": [...]
}
```

**Fields**:
- `enable_namespacing`: `true` (default) | `false`
- `template_resolution_mode`: `"strict"` (default) | `"permissive"`
- `inputs`: Declare expected inputs with types and defaults

### Global Settings

File: `~/.pflow/settings.json`

```json
{
  "runtime": {
    "template_resolution_mode": "strict",
    "enable_namespacing": true
  },
  "validation": {
    "strict_type_checking": true
  }
}
```

### Environment Variables

```bash
# Override template resolution mode
export PFLOW_TEMPLATE_RESOLUTION_MODE=permissive

# Include test nodes (useful for development)
export PFLOW_INCLUDE_TEST_NODES=true
```

### Configuration Hierarchy

**Priority (lowest to highest)**:

1. **Default**: `"strict"` mode, namespacing enabled
2. **Environment**: `PFLOW_TEMPLATE_RESOLUTION_MODE`
3. **Global settings**: `~/.pflow/settings.json`
4. **Workflow IR**: `template_resolution_mode` field
5. **Runtime parameter**: `initial_params["__template_resolution_mode__"]`

**Example**:

```bash
# Environment
export PFLOW_TEMPLATE_RESOLUTION_MODE=permissive

# Workflow IR overrides environment
{
  "template_resolution_mode": "strict",  # This wins
  "nodes": [...]
}
```

---

## Best Practices

### ✅ Good Patterns

#### Use Specific Nested Fields

```json
// Good: Use specific field
"${fetch.response.data.items[0].title}"

// Bad: Use entire dict (likely type mismatch)
"${fetch.response}"
```

#### Combine Multiple Templates

```json
{
  "file_path": "${project}-${env}-config.json",
  "url": "${api_base}/v${api_version}/users/${user_id}"
}
```

#### Natural File Naming

```json
{
  "output_file": "report_${date}_${version}.pdf",
  "backup_path": "${backup_dir}/${timestamp}_${file_name}.bak"
}
```

#### Use Hyphens for Readability

```json
{
  "user_id": "${user-id}",
  "api_key": "${api-key}",
  "base_url": "${base-url}"
}
```

#### Declare Inputs Explicitly

```json
{
  "inputs": {
    "api_token": {
      "type": "str",
      "required": true,
      "description": "API authentication token"
    },
    "max_retries": {
      "type": "int",
      "default": 3,
      "description": "Maximum retry attempts"
    }
  }
}
```

### ❌ Anti-Patterns

#### Using Whole Dict Where String Expected

```json
// Bad: Type error
{
  "command": "echo ${api_response}"
  //              ^^^^^^^^^^^^^^^^^
  //              api_response is dict, command expects str
}

// Good: Use specific field
{
  "command": "echo ${api_response.status}"
}
```

#### Using Node ID Without Output Key

```json
// Bad: What output?
"${fetch-data}"

// Good: Specify output
"${fetch-data.response}"
```

#### Deep Nesting Without Validation

```json
// Bad: Fragile, might fail at any level
"${api.data.items.results.user.profile.email.primary}"

// Good: Validate interface has this structure
// OR: Use intermediate nodes to extract data
```

#### Assuming Types

```json
// Bad: Assumes number is string
{
  "command": "echo count_${fetch.count}"
  //                      ^^^^^^^^^^^^
  //                      If count=42 (int), this works,
  //                      but if count=null, becomes "count_"
}

// Good: Use type-aware parameters
{
  "max_items": "${fetch.count}"  // Preserves int type
}
```

### Shell Command Limitations

When embedding arrays or dicts in shell commands, pflow serializes them to JSON. However, **certain characters in JSON can break shell parsing**:

| Character | Problem |
|-----------|---------|
| `'` (apostrophe) | Breaks single-quoted strings |
| `` ` `` (backtick) | Triggers command substitution |
| `$(...)` | Triggers command substitution |

#### Example Problem

```json
{
  "command": "echo '${data}' | jq '.'"
}
```

If `data = {"message": "it's working"}`, the command becomes:

```bash
echo '{"message": "it's working"}' | jq '.'
#                    ^ Shell sees this as end of string!
```

**This will fail with a shell syntax error.**

#### Safe Alternative: Use `stdin`

For data that might contain shell-unsafe characters, use the `stdin` parameter:

```json
{
  "id": "process",
  "type": "shell",
  "params": {
    "stdin": "${data}",
    "command": "jq '.message'"
  }
}
```

The `stdin` parameter passes data through a pipe, completely bypassing shell parsing.

#### When JSON in Commands is Safe

- Data you control (no user input)
- Data without apostrophes, backticks, or `$` characters
- Simple arrays of strings/numbers without special chars

**pflow will warn** if it detects potentially unsafe JSON patterns in shell commands.

---

### Migration from Old Syntax

**Before (pre-Task 35)**:

```json
{
  "file_path": "$source_dir/$file_name",
  //           ^^^^^^^^^^^^^^^^^^^^^^^^
  //           Ambiguous boundaries!

  "message": "data_$timestamp.json"
  //         ^^^^^^^^^^^^^^^^^^^^
  //         Fails parsing - where does $timestamp end?
}
```

**After (Task 35+)**:

```json
{
  "file_path": "${source_dir}/${file_name}",
  //           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  //           Clear boundaries!

  "message": "data_${timestamp}.json"
  //         ^^^^^^^^^^^^^^^^^^^^^^^
  //         Works perfectly!
}
```

**Migration checklist**:
- [ ] Replace all `$var` with `${var}`
- [ ] Add braces around compound names: `$user_id` → `${user_id}`
- [ ] Update nested paths: `$data.field` → `${data.field}`
- [ ] Test workflows with `pflow --validate-only workflow.pflow.md`

---

## Advanced Features

### Auto-Parsing JSON Strings

pflow automatically parses JSON strings to dicts/lists at several points during template resolution and type coercion. For the complete inventory of all auto-parse points, design principles, and how they interact, see [Data Type Coercion](../core-concepts/data-type-coercion.md).

**Quick reference** — the escape hatch when you want to keep a JSON string as a string:

```
"message": "Data: ${shell.stdout}"
           ^^^^^^
           Complex template (prefix + variable) → stays as string
```

Simple templates (`${var}` as the entire value) may be auto-parsed to containers. Complex templates (any surrounding text) always stay as strings.

### Tri-State Workflow Status

Introduced in Task 85 for nuanced execution outcomes:

```python
class WorkflowStatus(Enum):
    SUCCESS = "success"     # All good
    DEGRADED = "degraded"   # Completed with warnings
    FAILED = "failed"       # Execution failed
```

**SUCCESS**: Clean execution, no warnings

```python
# All nodes executed successfully
# No unresolved templates
# No warnings
→ Status: SUCCESS
```

**DEGRADED**: Completed but has warnings

```python
# Execution completed
# BUT: shared["__warnings__"] contains entries
#
# Example: API returned warning header
shared["__warnings__"] = {
    "fetch-data": "Rate limit warning: 10 requests remaining"
}
→ Status: DEGRADED
```

**FAILED**: Could not complete

```python
# Unresolved templates (strict mode)
# Node execution error
# Validation failure
→ Status: FAILED
```

**Why this matters**: Allows automation to distinguish between "perfect", "acceptable", and "broken".

---

## Debugging

### Enable Template Logging

```bash
# Set debug logging
export PFLOW_LOG_LEVEL=DEBUG

# Run workflow
uv run pflow my-workflow

# Output shows:
# DEBUG - Resolving template: ${user.name}
# DEBUG - Found in shared store: user.name=Alice
# DEBUG - Resolved to: Alice
```

### Inspect Template Validation

```python
from pflow.runtime.template_validator import TemplateValidator
from pflow.registry import Registry

registry = Registry.load()
workflow_ir = {...}
available_params = {"user_id": "123"}

errors, warnings = TemplateValidator.validate_workflow_templates(
    workflow_ir, available_params, registry
)

print(f"Errors: {errors}")
print(f"Warnings: {warnings}")

# Extract all templates
templates = TemplateValidator._extract_all_templates(workflow_ir)
print(f"Found templates: {templates}")
```

### Common Debug Scenarios

#### Template Not Resolving

**Symptoms**:
```
Template variable ${api_token} has no valid source
```

**Checks**:
1. Is variable in `initial_params`?
   ```bash
   pflow --param api_token=secret my-workflow
   ```

2. Is variable in workflow inputs?
   ```json
   {
     "inputs": {
       "api_token": {"type": "str", "required": true}
     }
   }
   ```

3. Is variable from previous node?
   ```json
   {
     "id": "setup",
     "outputs": {"api_token": "..."}
   }
   ```

4. Check spelling and case sensitivity:
   ```
   ${api_token} ≠ ${API_TOKEN} ≠ ${apiToken}
   ```

#### Type Mismatch Error

**Symptoms**:
```
Type mismatch: template ${response} has type 'dict' but parameter expects 'str'
```

**Solution**:
1. Read error message for available fields:
   ```
   Available outputs:
     ${response} (dict)
     ${response.message} (str) ← Try this!
   ```

2. Use specific field:
   ```json
   "text": "${response.message}"
   ```

3. Or serialize dict manually:
   ```json
   "text": "Response: ${response}"
   ```

#### Partial Resolution

**Symptoms**:
```
Partial template resolution detected
Original: "User ${name} has ${count} items"
Resolved: "User Alice has ${count} items"
```

**Solution**:
1. Check if all variables exist:
   ```python
   # name exists, count doesn't
   available_params = {"name": "Alice"}
   ```

2. Add missing variable:
   ```bash
   pflow --param count=5 my-workflow
   ```

3. Or switch to permissive mode:
   ```json
   {"template_resolution_mode": "permissive"}
   ```

#### False Positive Detection

**Symptoms**:
```
Unresolved template ${price} but it's actually data!
```

**Solution**:
1. Check if node legitimately outputs `${...}` patterns
2. Verify original parameter wasn't a template
3. File issue if false positive detected

### Test Your Workflows

```bash
# Validate without running
uv run pflow --validate-only workflow.pflow.md

# Run with verbose logging
uv run pflow --log-level DEBUG workflow.pflow.md

# Run with trace file
uv run pflow --trace workflow.pflow.md
# → Outputs: ~/.pflow/debug/workflow-trace-YYYYMMDD-HHMMSS.json

# Check specific parameter
uv run pflow --param test_value=123 workflow.pflow.md
```

---

## Related Documentation

- **IR Schema**: [ir-schema.md](./ir-schema.md) - Complete IR specification
- **Shared Store**: [shared-store.md](../core-concepts/shared-store.md) - Inter-node communication
- **Node Interfaces**: [enhanced-interface-format.md](./enhanced-interface-format.md) - Interface format for pflow nodes
- **Architecture**: [architecture.md](../architecture.md#execution-pipeline) - Execution pipeline and lifecycle

---

## Version History

| Version | Task | Changes |
|---------|------|---------|
| 1.0 | Task 18 | Initial template variable system with `$variable` syntax |
| 2.0 | Task 35 | Migration to `${variable}` syntax for clear boundaries |
| 3.0 | Task 84 | Schema-aware type checking and validation |
| 4.0 | Task 85 | Runtime hardening, auto-parsing, partial resolution detection |
| 5.0 | Task 103 | Inline object type preservation - fixes double-serialization in nested structures |

---

## Summary

**Template variables are the backbone of data flow in pflow workflows**. They enable:

1. **Dynamic composition** - Build workflows that adapt to input
2. **Type safety** - Catch errors before execution
3. **Clear debugging** - Unresolved templates are immediately visible
4. **Seamless integration** - MCP, GitHub, LLM, file operations all use the same system

**Key principles**:
- Use `${variable}` syntax with explicit braces
- Let type preservation do its magic (simple templates preserve types)
- Validate early with strict mode (catch errors before API calls)
- Use namespacing to avoid collisions
- Reference specific fields, not entire dicts
- Test your workflows before deploying

**When in doubt**: Read the error message - pflow provides actionable guidance!
