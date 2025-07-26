# Template System Integration - Required Code

## Core Components Needed to Use Templates

### 1. Workflow Definition (JSON or Python dict)

```python
# workflows/github_automation.json
{
    "ir_version": "0.1.0",
    "nodes": [
        {
            "id": "fetch",
            "type": "github-fetch",
            "params": {
                "repo": "$github.repo",
                "issue": "$github.issue_number",
                "token": "$github.token"
            }
        }
    ],
    "edges": []
}
```

### 2. Parameter Provider (Current Options)

#### Option A: Direct Python API
```python
from pflow.runtime.compiler import compile_ir_to_flow
from pflow.registry import Registry

def run_workflow(workflow_path, **params):
    with open(workflow_path) as f:
        workflow = json.load(f)

    registry = Registry()
    flow = compile_ir_to_flow(workflow, registry, initial_params=params)

    shared = {}
    flow.run(shared)
    return shared
```

#### Option B: Configuration File
```python
# config.yaml
github:
  repo: "myorg/myrepo"
  token: "${GITHUB_TOKEN}"  # From environment
  issue_number: "123"

# Usage
import yaml
import os

def load_params(config_path):
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Resolve environment variables
    def resolve_env(obj):
        if isinstance(obj, dict):
            return {k: resolve_env(v) for k, v in obj.items()}
        elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
            return os.environ.get(obj[2:-1], obj)
        return obj

    return resolve_env(config)

params = load_params("config.yaml")
flow = compile_ir_to_flow(workflow, registry, initial_params=params)
```

#### Option C: CLI Arguments (Manual)
```python
import argparse

def create_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("workflow", help="Path to workflow JSON")
    parser.add_argument("--param", "-p", action="append",
                       help="Parameters in key=value format")
    return parser

def parse_params(param_list):
    """Convert ['key=value', 'nested.key=value'] to nested dict."""
    params = {}
    for param in param_list or []:
        key, value = param.split("=", 1)

        # Handle nested keys
        parts = key.split(".")
        current = params
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    return params

# Usage
args = create_cli().parse_args()
params = parse_params(args.param)
```

### 3. Node Implementation Requirements

All nodes MUST implement the fallback pattern:

```python
from pocketflow import Node

class MyNode(Node):
    """Example node that works with templates."""

    def prep(self, shared):
        # CRITICAL: Check shared first, then params
        input_file = shared.get("input_file") or self.params.get("input_file")
        encoding = shared.get("encoding") or self.params.get("encoding", "utf-8")

        if not input_file:
            raise ValueError("Missing required 'input_file'")

        return {
            "input_file": input_file,
            "encoding": encoding
        }

    def exec(self, prep_res):
        # Use resolved values
        with open(prep_res["input_file"], "r", encoding=prep_res["encoding"]) as f:
            return f.read()

    def post(self, shared, prep_res, exec_res):
        shared["content"] = exec_res
        return "default"
```

### 4. Registry Setup

The registry must be able to find your nodes:

```python
# src/pflow/nodes/my_nodes.py
class ProcessorNode(Node):
    """
    Node metadata.

    Interface:
        Inputs:
            - data: Data to process
            - format: Output format
        Outputs:
            - result: Processed data
    """
    pass

# The registry will automatically discover this via:
registry = Registry()
nodes = registry.load()  # Scans and finds all nodes
```

## Complete Working Example

Here's everything you need in one place:

```python
#!/usr/bin/env python3
"""Complete example of using the template system."""

import json
import os
from pathlib import Path

from pflow.runtime.compiler import compile_ir_to_flow
from pflow.registry import Registry


class WorkflowRunner:
    """Helper class for running templated workflows."""

    def __init__(self):
        self.registry = Registry()

    def run(self, workflow_path, params=None, shared=None):
        """Run a workflow with parameters."""
        # Load workflow
        workflow = self._load_workflow(workflow_path)

        # Compile with templates
        flow = compile_ir_to_flow(
            workflow,
            self.registry,
            initial_params=params or {},
            validate=True  # Ensure all templates have values
        )

        # Execute
        shared = shared or {}
        flow.run(shared)

        return shared

    def _load_workflow(self, path):
        """Load workflow from file or dict."""
        if isinstance(path, dict):
            return path

        with open(path) as f:
            return json.load(f)


# Example workflow
example_workflow = {
    "ir_version": "0.1.0",
    "nodes": [
        {
            "id": "reader",
            "type": "read-file",
            "params": {
                "file_path": "$input_file"
            }
        },
        {
            "id": "writer",
            "type": "write-file",
            "params": {
                "file_path": "$output_file",
                "content": "$content"  # From shared store
            }
        }
    ],
    "edges": [
        {"from": "reader", "to": "writer"}
    ]
}


def main():
    runner = WorkflowRunner()

    # Run with specific parameters
    result = runner.run(
        example_workflow,
        params={
            "input_file": "input.txt",
            "output_file": "output.txt"
        }
    )

    print("Workflow completed!")
    print(f"Result: {result}")


if __name__ == "__main__":
    main()
```

## Integration Patterns

### Pattern 1: Workflow Library
```python
class WorkflowLibrary:
    """Manage reusable workflows."""

    def __init__(self, workflows_dir):
        self.workflows_dir = Path(workflows_dir)
        self.runner = WorkflowRunner()

    def list_workflows(self):
        """List available workflows."""
        return [f.stem for f in self.workflows_dir.glob("*.json")]

    def get_workflow_params(self, name):
        """Extract required parameters from workflow."""
        path = self.workflows_dir / f"{name}.json"
        workflow = json.loads(path.read_text())

        # Extract all template variables
        from pflow.runtime.template_validator import TemplateValidator
        templates = TemplateValidator.extract_all_templates(workflow)

        return templates

    def run(self, name, **params):
        """Run a workflow by name."""
        path = self.workflows_dir / f"{name}.json"
        return self.runner.run(path, params)
```

### Pattern 2: Batch Processing
```python
def batch_process(workflow, items, base_params=None):
    """Process multiple items with same workflow."""
    runner = WorkflowRunner()
    results = []

    for item in items:
        # Merge item-specific params with base params
        params = {**(base_params or {}), **item}

        result = runner.run(workflow, params)
        results.append(result)

    return results

# Usage
items = [
    {"input_file": "doc1.txt", "output_file": "out1.txt"},
    {"input_file": "doc2.txt", "output_file": "out2.txt"},
]

results = batch_process(example_workflow, items)
```

### Pattern 3: Dynamic Workflow Generation
```python
def create_pipeline(steps):
    """Dynamically create a workflow from steps."""
    nodes = []
    edges = []

    for i, step in enumerate(steps):
        node_id = f"step_{i}"
        nodes.append({
            "id": node_id,
            "type": step["type"],
            "params": step["params"]  # Can contain templates
        })

        if i > 0:
            edges.append({
                "from": f"step_{i-1}",
                "to": node_id
            })

    return {
        "ir_version": "0.1.0",
        "nodes": nodes,
        "edges": edges
    }

# Usage
pipeline = create_pipeline([
    {"type": "read-file", "params": {"file_path": "$input"}},
    {"type": "transform", "params": {"operation": "$transform_op"}},
    {"type": "write-file", "params": {"file_path": "$output"}}
])

runner = WorkflowRunner()
runner.run(pipeline, params={
    "input": "data.csv",
    "transform_op": "normalize",
    "output": "normalized.csv"
})
```

## Error Handling

```python
from pflow.runtime.template_validator import TemplateValidator

def validate_params(workflow, params):
    """Validate all templates have values."""
    errors = TemplateValidator.validate_workflow_templates(workflow, params)

    if errors:
        print("Missing parameters:")
        for error in errors:
            print(f"  - {error}")
        return False

    return True

# Usage
if not validate_params(workflow, params):
    print("Please provide all required parameters")
    sys.exit(1)
```

## Future CLI Integration (Preview)

When the CLI is updated to support templates:

```python
# pflow/cli/main.py (future)
@click.command()
@click.argument("workflow")
@click.option("--param", "-p", multiple=True, help="Template parameters")
def run(workflow, param):
    """Run a workflow with template parameters."""
    params = parse_params(param)

    runner = WorkflowRunner()
    result = runner.run(workflow, params)

    click.echo(f"Workflow completed: {result}")

# Usage:
# pflow run workflow.json -p input_file=data.txt -p output_file=result.txt
```

## Summary

To use the template system today, you need:

1. **Workflow definitions** with `$variable` placeholders
2. **Parameter source** (config file, CLI args, API calls)
3. **The compiler** with `initial_params`
4. **Nodes that follow the fallback pattern**

The system is ready and working. It's just waiting for more convenient interfaces (CLI, planner) to make it easier to use!
