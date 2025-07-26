# Template Variable System - Complete Usage Guide

## What is the Template System?

The template variable system enables **"Plan Once, Run Forever"** - you can create reusable workflows with placeholder variables that get filled in at runtime. This is the foundation that makes workflows truly reusable.

## Basic Usage

### 1. Creating a Workflow with Templates

```python
# Define a reusable workflow with $variable placeholders
workflow_ir = {
    "ir_version": "0.1.0",
    "nodes": [
        {
            "id": "reader",
            "type": "read-file",
            "params": {
                "file_path": "$input_file",      # Simple variable
                "encoding": "$encoding"           # Another variable
            }
        },
        {
            "id": "processor",
            "type": "llm",
            "params": {
                "prompt": "Summarize this: $content",  # Embedded in string
                "model": "$config.model",              # Path traversal
                "temperature": "$config.temperature"    # Nested access
            }
        },
        {
            "id": "writer",
            "type": "write-file",
            "params": {
                "file_path": "$output_file",
                "content": "$summary"    # Will come from shared store
            }
        }
    ],
    "edges": [
        {"from": "reader", "to": "processor"},
        {"from": "processor", "to": "writer"}
    ]
}
```

### 2. Compiling with Initial Parameters

```python
from pflow.runtime.compiler import compile_ir_to_flow
from pflow.registry import Registry

# Parameters from user input (in future, from Task 17 planner)
initial_params = {
    "input_file": "/path/to/document.txt",
    "output_file": "/path/to/summary.txt",
    "encoding": "utf-8",
    "config": {
        "model": "gpt-4",
        "temperature": 0.7
    }
}

# Compile the workflow with template resolution
registry = Registry()
flow = compile_ir_to_flow(workflow_ir, registry, initial_params=initial_params)

# Run the workflow
shared = {}
flow.run(shared)
```

## Template Syntax

### Simple Variables
```python
"file_path": "$input_file"          # Resolves from initial_params or shared store
"message": "Hello $name!"           # Embedded in string
"multiple": "$first and $second"    # Multiple templates
```

### Path Traversal (Dotted Notation)
```python
"value": "$data.field"              # Access nested dict: data["field"]
"deep": "$config.server.host"       # Multiple levels: config["server"]["host"]
"item": "$results.items.0.name"     # NOT SUPPORTED - no array indexing
```

## Resolution Priority

Templates are resolved from two sources with clear priority:

1. **initial_params** (HIGHER PRIORITY) - Values from planner/CLI
2. **shared store** (LOWER PRIORITY) - Runtime data between nodes

```python
# If both have 'message':
initial_params = {"message": "From params"}  # This wins
shared = {"message": "From shared"}          # This is ignored

# Resolution context is built as:
context = dict(shared)              # Start with shared
context.update(initial_params)      # Override with params
```

## Current Usage Patterns

### Pattern 1: Direct API Usage (Available Now)

```python
import json
from pflow.runtime.compiler import compile_ir_to_flow
from pflow.registry import Registry

def run_workflow_with_params(workflow_path, **params):
    """Run a workflow with specific parameters."""
    # Load workflow
    with open(workflow_path) as f:
        workflow_ir = json.load(f)

    # Compile with parameters
    registry = Registry()
    flow = compile_ir_to_flow(
        workflow_ir,
        registry,
        initial_params=params
    )

    # Execute
    shared = {}
    result = flow.run(shared)
    return shared

# Use it
result = run_workflow_with_params(
    "workflows/process_document.json",
    input_file="/tmp/doc.txt",
    output_file="/tmp/summary.txt",
    model="gpt-4"
)
```

### Pattern 2: Future CLI Usage (When Planner is Ready)

```bash
# Natural language invocation (Task 17 will enable this)
pflow run "summarize the document at /tmp/report.pdf and save to summary.txt"

# The planner will extract:
# - input_file: "/tmp/report.pdf"
# - output_file: "summary.txt"
# And pass these as initial_params
```

### Pattern 3: Programmatic Workflow Building

```python
def create_reusable_workflow():
    """Create a parameterized workflow for reuse."""
    return {
        "ir_version": "0.1.0",
        "nodes": [{
            "id": "api_call",
            "type": "http-request",
            "params": {
                "url": "$api.endpoint",
                "method": "POST",
                "headers": {
                    "Authorization": "Bearer $api.token"
                },
                "body": {
                    "query": "$user_query",
                    "limit": "$config.max_results"
                }
            }
        }],
        "edges": []
    }

# Run same workflow with different configs
for env in ["dev", "staging", "prod"]:
    flow = compile_ir_to_flow(
        create_reusable_workflow(),
        registry,
        initial_params={
            "api": {
                "endpoint": f"https://{env}.api.com/search",
                "token": os.environ[f"{env.upper()}_TOKEN"]
            },
            "user_query": "test query",
            "config": {"max_results": 10}
        }
    )
    flow.run({})
```

## Real-World Examples

### Example 1: GitHub Issue Processor

```python
github_workflow = {
    "nodes": [{
        "id": "fetch_issue",
        "type": "github-api",
        "params": {
            "repo": "$repo",
            "issue_number": "$issue_number",
            "token": "$github_token"
        }
    }, {
        "id": "analyze",
        "type": "llm",
        "params": {
            "prompt": "Analyze this issue and suggest labels: $issue_content",
            "model": "$llm_model"
        }
    }, {
        "id": "update_issue",
        "type": "github-api",
        "params": {
            "action": "add_labels",
            "repo": "$repo",
            "issue_number": "$issue_number",
            "labels": "$suggested_labels"
        }
    }]
}

# Reuse for different issues
for issue_num in [123, 456, 789]:
    flow = compile_ir_to_flow(
        github_workflow,
        registry,
        initial_params={
            "repo": "myorg/myrepo",
            "issue_number": str(issue_num),
            "github_token": os.environ["GITHUB_TOKEN"],
            "llm_model": "gpt-4"
        }
    )
    flow.run({})
```

### Example 2: Data Processing Pipeline

```python
etl_workflow = {
    "nodes": [{
        "id": "extract",
        "type": "read-csv",
        "params": {
            "file_path": "$input.path",
            "encoding": "$input.encoding",
            "delimiter": "$input.delimiter"
        }
    }, {
        "id": "transform",
        "type": "data-transform",
        "params": {
            "operations": "$transform.operations",
            "filters": "$transform.filters"
        }
    }, {
        "id": "load",
        "type": "write-database",
        "params": {
            "connection_string": "$db.connection",
            "table": "$db.table",
            "mode": "$db.write_mode"
        }
    }]
}

# Run daily with different parameters
def run_daily_etl(date):
    flow = compile_ir_to_flow(
        etl_workflow,
        registry,
        initial_params={
            "input": {
                "path": f"/data/raw/{date}.csv",
                "encoding": "utf-8",
                "delimiter": ","
            },
            "transform": {
                "operations": ["normalize_dates", "clean_nulls"],
                "filters": {"date": date}
            },
            "db": {
                "connection": os.environ["DB_CONN"],
                "table": "daily_metrics",
                "write_mode": "append"
            }
        }
    )
    return flow.run({})
```

## Template Validation

### Understanding Validation Errors

```python
workflow = {
    "nodes": [{
        "id": "node1",
        "type": "some-node",
        "params": {
            "required": "$missing_param",    # Will cause validation error
            "optional": "$another_missing"   # Also missing
        }
    }]
}

try:
    flow = compile_ir_to_flow(workflow, registry, initial_params={})
except ValueError as e:
    print(e)
    # Output:
    # Template validation failed:
    #   - Missing required parameter: --missing_param
    #   - Missing required parameter: --another_missing
```

### Disabling Validation (Use Carefully)

```python
# For workflows where params come from shared store at runtime
flow = compile_ir_to_flow(
    workflow,
    registry,
    initial_params={},
    validate=False  # Skip validation
)
```

## How Nodes See Templates

Nodes don't know about templates! They see fully resolved values:

```python
# In workflow:
"params": {
    "file": "$input_file",
    "format": "$output_format"
}

# Node's prep() method sees:
self.params = {
    "file": "/actual/path/to/file.txt",  # Resolved
    "format": "json"                     # Resolved
}
```

This is why ALL pflow nodes must implement the fallback pattern:
```python
def prep(self, shared):
    # Check shared store first, then params
    file_path = shared.get("file_path") or self.params.get("file_path")
```

## Debugging Templates

### 1. Enable Debug Logging

```bash
export PFLOW_LOG_LEVEL=DEBUG
python your_script.py
```

You'll see:
```
DEBUG: Template $input_file resolved to: /path/to/file.txt
WARNING: Template in param 'missing' could not be fully resolved: '$missing_var'
```

### 2. Check What Gets Resolved

```python
# Templates that can't be resolved remain as-is
initial_params = {"name": "Alice"}
"greeting": "Hello $name!"          # → "Hello Alice!"
"missing": "Value: $undefined"      # → "Value: $undefined" (unchanged)
```

### 3. Inspect Wrapped Nodes

```python
from pflow.runtime.node_wrapper import TemplateAwareNodeWrapper

# After compilation
node = flow.start_node
if isinstance(node, TemplateAwareNodeWrapper):
    print("Template params:", node.template_params)
    print("Static params:", node.static_params)
```

## Limitations & Edge Cases

### What Works ✅
- Simple variables: `$var`
- Path traversal: `$parent.child.field`
- Multiple templates: `$var1 and $var2`
- Embedded templates: `Hello $name!`
- Type conversion: All values → strings

### What Doesn't Work ❌
- Array indexing: `$items.0`
- Expressions: `$count + 1`
- Methods: `$name.upper()`
- Defaults: `$var|default`
- Brace syntax: `${var}`
- Templates in node IDs/types

### Edge Case Handling
```python
# None in path stops traversal
params = {"parent": {"child": None}}
"$parent.child.field" → "$parent.child.field" (unchanged)

# Non-dict traversal fails
params = {"text": "hello"}
"$text.field" → "$text.field" (unchanged)

# Malformed syntax ignored
"$" → "$"
"$$var" → "$$var"
"$var." → "$var."
```

## Best Practices

1. **Name Templates Clearly**
   ```python
   # Good
   "$input_file", "$github_token", "$db.host"

   # Bad
   "$file", "$token", "$h"
   ```

2. **Validate Early**
   ```python
   # Always validate unless params come from runtime
   compile_ir_to_flow(ir, registry, params, validate=True)
   ```

3. **Document Required Parameters**
   ```python
   """
   Workflow: process_document
   Required parameters:
   - input_file: Path to input document
   - output_format: Output format (json, xml, text)
   - model: LLM model to use
   """
   ```

4. **Use Nested Structures**
   ```python
   # Organize related params
   {
       "api": {"endpoint": "...", "token": "..."},
       "config": {"retries": 3, "timeout": 30}
   }
   ```

## Future Integration (Coming Soon)

When Task 17 (Planner) is complete:

```bash
# Natural language with automatic parameter extraction
pflow run "analyze the sales report from yesterday and email results to team@company.com"

# Planner extracts:
# - report_date: "yesterday" → "2024-01-24"
# - report_type: "sales"
# - email_to: "team@company.com"
```

The template system is the bridge between static workflow definitions and dynamic execution. It's ready and waiting for the planner to unlock its full potential!
