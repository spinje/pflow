# Template System: What's Available NOW vs Coming Soon

## 🟢 Available NOW (Task 18 Complete)

### Core Template Engine ✅
```python
from pflow.runtime.compiler import compile_ir_to_flow
from pflow.registry import Registry

# Define workflow with templates
workflow = {
    "nodes": [{
        "id": "processor",
        "type": "some-node",
        "params": {
            "input": "$input_file",           # Simple variable
            "config": "$settings.timeout",    # Path traversal
            "message": "Processing $name"     # Embedded template
        }
    }]
}

# Compile with parameters
registry = Registry()
flow = compile_ir_to_flow(
    workflow,
    registry,
    initial_params={
        "input_file": "/path/to/file",
        "settings": {"timeout": 30},
        "name": "MyData"
    }
)

# Run it
flow.run({})
```

### What You Can Do Today

1. **Create Reusable Workflows**
   - Define workflows with `$variable` placeholders
   - Save as JSON files
   - Run with different parameters each time

2. **Use Path Traversal**
   - Access nested data: `$config.server.host`
   - Works with complex parameter structures

3. **Mix Static and Dynamic Values**
   - Initial params from compile time
   - Runtime values from shared store
   - Priority: initial_params > shared store

4. **Validate Templates**
   - Automatic validation before execution
   - Clear error messages for missing params
   - Optional validation bypass for runtime params

### Current Usage Pattern
```python
# 1. Load your workflow
with open("my_workflow.json") as f:
    workflow = json.load(f)

# 2. Prepare parameters (from anywhere)
params = {
    "input": get_user_input(),
    "output": calculate_output_path(),
    "config": load_config()
}

# 3. Compile and run
flow = compile_ir_to_flow(workflow, registry, initial_params=params)
result = flow.run({})
```

## 🟡 Coming Soon (Other Tasks)

### Task 17: Natural Language Planner
```bash
# Instead of manually specifying parameters...
pflow run workflow.json --param input=/path/to/file --param output=/path/to/output

# You'll be able to say:
pflow run "process the file at /path/to/file and save results"
# Planner extracts: {"input": "/path/to/file", "output": "results"}
```

### Enhanced CLI Support
```bash
# Direct parameter passing
pflow run workflow.json --input-file data.txt --model gpt-4

# From config file
pflow run workflow.json --params config.yaml

# Interactive mode
pflow run workflow.json --interactive
> Enter input_file: data.txt
> Enter output_format: json
```

### Workflow Management
```bash
# Save workflows with metadata
pflow workflow save my-processor --description "Processes documents"

# List available workflows
pflow workflow list

# Run saved workflows
pflow run my-processor --doc report.pdf
```

## 🔴 NOT Implemented (Out of Scope)

### Advanced Template Features
```python
# These DON'T work:
"$items[0]"              # Array indexing
"$count + 1"             # Expressions
"$name.upper()"          # Method calls
"$var || 'default'"      # Default values
"${variable}"            # Brace syntax
```

### Template Usage in Other Fields
```json
{
    "id": "$node_id",        # ❌ Templates in ID
    "type": "$node_type",    # ❌ Templates in type
    "edges": [{
        "from": "$source",   # ❌ Templates in edges
        "to": "$target"
    }]
}
```

## Real Example: Using Templates Today

Here's a complete, working example you can run right now:

```python
#!/usr/bin/env python3
"""Working example of template system usage."""

import json
import tempfile
import os
from pathlib import Path

from pflow.runtime.compiler import compile_ir_to_flow
from pflow.registry import Registry


# Step 1: Create a reusable workflow
DOCUMENT_PROCESSOR = {
    "ir_version": "0.1.0",
    "nodes": [
        {
            "id": "reader",
            "type": "read-file",
            "params": {
                "file_path": "$source_document",
                "encoding": "$encoding"
            }
        },
        {
            "id": "writer",
            "type": "write-file",
            "params": {
                "file_path": "$target_document",
                "content": "$content",  # From shared store
                "encoding": "$encoding"
            }
        }
    ],
    "edges": [
        {"from": "reader", "to": "writer"}
    ]
}


def process_documents(doc_list):
    """Process multiple documents with the same workflow."""
    registry = Registry()

    for doc_info in doc_list:
        print(f"\nProcessing: {doc_info['name']}")

        # Parameters for this specific run
        params = {
            "source_document": doc_info["input"],
            "target_document": doc_info["output"],
            "encoding": doc_info.get("encoding", "utf-8")
        }

        # Compile workflow with these parameters
        flow = compile_ir_to_flow(
            DOCUMENT_PROCESSOR,
            registry,
            initial_params=params
        )

        # Execute
        shared = {}
        flow.run(shared)

        print(f"  ✓ Saved to: {doc_info['output']}")


def main():
    """Demonstrate the template system."""

    # Create test documents
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create source files
        for i in range(3):
            path = Path(tmpdir) / f"document_{i}.txt"
            path.write_text(f"This is document {i}")

        # Process them all with different parameters
        documents = [
            {
                "name": "Document 0 - UTF8",
                "input": str(Path(tmpdir) / "document_0.txt"),
                "output": str(Path(tmpdir) / "processed_0.txt"),
                "encoding": "utf-8"
            },
            {
                "name": "Document 1 - ASCII",
                "input": str(Path(tmpdir) / "document_1.txt"),
                "output": str(Path(tmpdir) / "processed_1.txt"),
                "encoding": "ascii"
            },
            {
                "name": "Document 2 - UTF8",
                "input": str(Path(tmpdir) / "document_2.txt"),
                "output": str(Path(tmpdir) / "processed_2.txt")
                # encoding will use default
            }
        ]

        # Run the same workflow with different parameters
        process_documents(documents)

        # Verify results
        print("\n--- Results ---")
        for doc in documents:
            output_path = Path(doc["output"])
            if output_path.exists():
                content = output_path.read_text()
                print(f"{doc['name']}: {content}")


if __name__ == "__main__":
    main()
```

## Migration Path

### Today (Manual Parameters)
```python
params = {
    "repo": "myorg/myrepo",
    "issue": "123",
    "token": os.environ["GITHUB_TOKEN"]
}
flow = compile_ir_to_flow(workflow, registry, initial_params=params)
```

### Tomorrow (With Planner)
```python
# Natural language input
user_input = "check github issue 123 in myorg/myrepo"

# Planner extracts parameters automatically
params = planner.extract_params(user_input)
# Returns: {"repo": "myorg/myrepo", "issue": "123", "token": "<from context>"}

flow = compile_ir_to_flow(workflow, registry, initial_params=params)
```

### Future (Full Integration)
```bash
# One command, natural language
pflow run "check github issue 123 in myorg/myrepo"

# Or with saved workflows
pflow run github-checker --issue 123 --repo myorg/myrepo
```

## Summary

The template system is **fully implemented and ready to use**. You can:

- ✅ Create reusable workflows today
- ✅ Use templates in your node parameters
- ✅ Run workflows with different parameters
- ✅ Build workflow libraries and tools

What's coming later is just more convenient ways to:
- 🟡 Extract parameters from natural language
- 🟡 Pass parameters via CLI
- 🟡 Manage workflow libraries

The foundation is solid and production-ready. Start building reusable workflows now!
