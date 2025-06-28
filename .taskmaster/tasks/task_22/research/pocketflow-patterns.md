# PocketFlow Patterns for Task 22: Implement Named Workflow Execution

## Task Context

- **Goal**: Enable execution of saved workflows by name with parameters
- **Dependencies**: Task 20 (workflow storage), Task 21 (lockfile system)
- **Constraints**: Core user-facing feature delivering "Plan Once, Run Forever"

## Overview

Task 22 implements the execution side of pflow's core value proposition. Users can save workflows once and reuse them forever with different parameters. This transforms natural language planning from an every-time cost to a one-time investment.

## Core Patterns from Advanced Analysis

### Pattern: Workflow as Reusable Template
**Found in**: All 7 repositories reuse flows with different inputs
**Why It Applies**: Templates + parameters = infinite reusability

```python
# First time: Plan the workflow
pflow "fix github issue 123"
# Save as: fix-issue

# Forever after: Just execute with parameters
pflow fix-issue --issue=456
pflow fix-issue --issue=789 --priority=high
pflow fix-issue --issue=1011 --assign="@teammate"
```

### Pattern: Parameter Resolution at Runtime
**Found in**: Cold Email Personalization, Tutorial-Cursor
**Why It Applies**: Template variables get resolved with actual values

```python
# Saved workflow has template:
# "Fix this issue: $issue"

# Runtime provides value:
# --issue=123

# Resolved at execution:
# "Fix this issue: #123 - Login button not working"
```

### Pattern: Lazy Loading for Performance
**Found in**: Large-scale flows load resources as needed
**Why It Applies**: Fast startup, efficient memory usage

```python
def load_workflow_metadata(name: str) -> Dict:
    """Load only metadata first for validation"""
    # Don't load full workflow until needed
    metadata_path = f"~/.pflow/workflows/{name}.meta.json"
    return json.load(open(metadata_path))

def load_full_workflow(name: str) -> Dict:
    """Load complete workflow when ready to execute"""
    workflow_path = f"~/.pflow/workflows/{name}.json"
    return json.load(open(workflow_path))
```

## Relevant Cookbook Examples

- `cookbook/pocketflow-flow`: Flow execution patterns
- `cookbook/pocketflow-agent`: Parameter handling in complex flows
- `cookbook/AI-Paul-Graham`: Workflow reuse with different content

## Implementation Patterns

### Pattern: Named Workflow Execution

```python
# src/pflow/cli/execute.py
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

class WorkflowExecutor:
    """Execute saved workflows by name with runtime parameters"""

    def __init__(self, workflow_storage, ir_compiler, runtime):
        self.storage = workflow_storage
        self.compiler = ir_compiler
        self.runtime = runtime
        self.workflows_dir = Path.home() / ".pflow" / "workflows"

    def execute_named_workflow(self, name: str, params: Dict[str, Any]) -> Any:
        """Main entry point for named workflow execution"""

        # 1. Load workflow
        workflow = self.load_workflow(name)

        # 2. Validate lockfile (if exists)
        if self.has_lockfile(name):
            self.validate_lockfile(name, workflow)

        # 3. Apply runtime parameters
        resolved_workflow = self.apply_parameters(workflow, params)

        # 4. Compile to executable form
        flow = self.compiler.compile_ir_to_flow(resolved_workflow)

        # 5. Initialize shared store with params
        shared = self.initialize_shared_store(params, workflow)

        # 6. Execute with runtime
        return self.runtime.execute_flow(flow, shared)

    def load_workflow(self, name: str) -> Dict:
        """Load saved workflow by name"""
        workflow_path = self.workflows_dir / f"{name}.json"

        if not workflow_path.exists():
            # Try fuzzy matching
            similar = self.find_similar_workflows(name)
            if similar:
                raise ValueError(
                    f"Workflow '{name}' not found. "
                    f"Did you mean: {', '.join(similar)}?"
                )
            else:
                raise ValueError(
                    f"Workflow '{name}' not found. "
                    f"List available workflows with: pflow list"
                )

        return json.loads(workflow_path.read_text())

    def apply_parameters(self, workflow: Dict, params: Dict[str, Any]) -> Dict:
        """Apply runtime parameters to workflow templates"""

        # Deep copy to avoid modifying saved workflow
        import copy
        resolved = copy.deepcopy(workflow)

        # Resolve template inputs
        if "template_inputs" in resolved:
            resolved = self.resolve_templates(resolved, params)

        # Apply parameter overrides to nodes
        resolved = self.apply_node_params(resolved, params)

        # Validate all required params provided
        self.validate_required_params(resolved, params)

        return resolved

    def resolve_templates(self, workflow: Dict, params: Dict[str, Any]) -> Dict:
        """Resolve template variables with runtime values"""

        # Get variable mappings
        variable_values = self.build_variable_values(workflow, params)

        # Resolve each template
        for node_id, templates in workflow.get("template_inputs", {}).items():
            for input_key, template in templates.items():
                if isinstance(template, str):
                    # Replace $variables with values
                    resolved = self.resolve_template_string(
                        template,
                        variable_values
                    )

                    # Update node params with resolved value
                    for node in workflow["nodes"]:
                        if node["id"] == node_id:
                            if "params" not in node:
                                node["params"] = {}
                            node["params"][input_key] = resolved
                            break

        return workflow

    def resolve_template_string(self, template: str, values: Dict[str, str]) -> str:
        """Resolve a single template string"""
        import re

        def replacer(match):
            var_name = match.group(1)
            if var_name not in values:
                raise ValueError(
                    f"Missing value for template variable '${var_name}'. "
                    f"Provide it with --{var_name}=VALUE"
                )
            return values[var_name]

        # Replace $var and ${var} patterns
        return re.sub(r'\$\{?(\w+)\}?', replacer, template)

    def build_variable_values(self, workflow: Dict, params: Dict) -> Dict:
        """Build complete variable value mapping"""
        values = {}

        # 1. Start with CLI parameters
        values.update(params)

        # 2. Add defaults from workflow
        if "parameter_defaults" in workflow:
            for key, default in workflow["parameter_defaults"].items():
                if key not in values:
                    values[key] = default

        # 3. Add special variables
        values["timestamp"] = datetime.now().isoformat()
        values["run_id"] = str(uuid.uuid4())[:8]

        return values

    def initialize_shared_store(self, params: Dict, workflow: Dict) -> Dict:
        """Initialize shared store with runtime data"""
        shared = {}

        # 1. Check for piped input
        if not sys.stdin.isatty():
            shared["stdin"] = sys.stdin.read()

        # 2. Add data parameters (vs node params)
        data_params = self.categorize_parameters(params, workflow)
        shared.update(data_params["data"])

        # 3. Add workflow metadata
        shared["_workflow_name"] = workflow.get("name", "unnamed")
        shared["_workflow_version"] = workflow.get("version", "1.0.0")

        return shared

    def categorize_parameters(self, params: Dict, workflow: Dict) -> Dict:
        """Categorize parameters as data vs node params"""
        categorized = {"data": {}, "node_params": {}}

        # Get node parameter names from workflow
        node_param_names = set()
        for node in workflow.get("nodes", []):
            if "params" in node:
                node_param_names.update(node["params"].keys())

        # Categorize each parameter
        for key, value in params.items():
            if key in node_param_names:
                categorized["node_params"][key] = value
            else:
                # Assume data parameter for shared store
                categorized["data"][key] = value

        return categorized

    def validate_lockfile(self, name: str, workflow: Dict):
        """Validate workflow against lockfile"""
        lockfile_path = self.workflows_dir / f"{name}.lock"

        if not lockfile_path.exists():
            return  # No lockfile, skip validation

        lockfile = json.loads(lockfile_path.read_text())

        # Validate IR hash
        current_hash = self.compute_workflow_hash(workflow)
        if current_hash != lockfile.get("ir_hash"):
            raise ValueError(
                f"Workflow '{name}' has been modified since lockfile creation. "
                f"Regenerate lockfile with: pflow lock {name}"
            )

        # Validate node versions (if tracking)
        if "node_versions" in lockfile:
            self.validate_node_versions(lockfile["node_versions"])

    def apply_node_params(self, workflow: Dict, params: Dict) -> Dict:
        """Apply parameter overrides to specific nodes"""

        # Look for node-specific parameters (e.g., --llm.temperature=0.5)
        for key, value in params.items():
            if "." in key:
                node_id, param_name = key.split(".", 1)

                # Find node and update param
                for node in workflow["nodes"]:
                    if node["id"] == node_id:
                        if "params" not in node:
                            node["params"] = {}
                        node["params"][param_name] = value
                        break

        return workflow

    def validate_required_params(self, workflow: Dict, params: Dict):
        """Ensure all required parameters are provided"""

        # Extract all template variables
        required_vars = set()

        for templates in workflow.get("template_inputs", {}).values():
            for template in templates.values():
                if isinstance(template, str):
                    import re
                    variables = re.findall(r'\$\{?(\w+)\}?', template)
                    required_vars.update(variables)

        # Remove variables that have sources in workflow
        if "variable_flow" in workflow:
            for var in list(required_vars):
                if var in workflow["variable_flow"]:
                    required_vars.remove(var)

        # Check if all required are provided
        missing = required_vars - set(params.keys())

        if missing:
            raise ValueError(
                f"Missing required parameters: {', '.join(missing)}\n"
                f"Provide them with: {' '.join(f'--{p}=VALUE' for p in missing)}"
            )

    def find_similar_workflows(self, name: str) -> List[str]:
        """Find workflows with similar names"""
        if not self.workflows_dir.exists():
            return []

        all_workflows = [
            f.stem for f in self.workflows_dir.glob("*.json")
            if not f.name.endswith(".lock.json")
        ]

        # Simple similarity check
        similar = []
        for workflow in all_workflows:
            if name.lower() in workflow.lower() or workflow.lower() in name.lower():
                similar.append(workflow)

        return similar[:3]  # Top 3 matches

    def compute_workflow_hash(self, workflow: Dict) -> str:
        """Compute hash of workflow for validation"""
        import hashlib

        # Normalize workflow for consistent hashing
        normalized = json.dumps(workflow, sort_keys=True)
        return hashlib.sha256(normalized.encode()).hexdigest()
```

### Pattern: CLI Integration

```python
# Extension to src/pflow/cli/main.py
import click

@cli.command()
@click.argument('workflow_name')
@click.option('--trace', is_flag=True, help='Enable execution tracing')
@click.option('--no-cache', is_flag=True, help='Disable node caching')
@click.pass_context
def run(ctx, workflow_name, trace, no_cache, **params):
    """Execute a saved workflow by name.

    Examples:
        pflow run fix-issue --issue=123
        pflow run analyze-repo --repo=owner/name --depth=full
        pflow run daily-report --date=today
    """

    # Parse additional parameters from command line
    runtime_params = parse_runtime_params(ctx.args)

    try:
        # Execute workflow
        executor = WorkflowExecutor(
            storage=ctx.obj['storage'],
            compiler=ctx.obj['compiler'],
            runtime=ctx.obj['runtime']
        )

        # Configure runtime options
        if trace:
            ctx.obj['runtime'].enable_tracing()
        if no_cache:
            ctx.obj['runtime'].disable_cache()

        # Execute with parameters
        result = executor.execute_named_workflow(
            workflow_name,
            runtime_params
        )

        # Display result
        if result.get('output'):
            click.echo(result['output'])
        else:
            click.echo(f"✅ Workflow '{workflow_name}' completed successfully")

    except ValueError as e:
        click.echo(f"❌ {e}", err=True)
        ctx.exit(1)
    except Exception as e:
        click.echo(f"💥 Execution failed: {e}", err=True)
        if trace:
            import traceback
            traceback.print_exc()
        ctx.exit(2)

def parse_runtime_params(args: List[str]) -> Dict[str, Any]:
    """Parse --key=value parameters from remaining args"""
    params = {}

    for arg in args:
        if arg.startswith('--') and '=' in arg:
            key = arg[2:].split('=')[0]
            value = arg.split('=', 1)[1]

            # Try to parse value type
            params[key] = parse_value(value)

    return params

def parse_value(value: str) -> Any:
    """Parse string value to appropriate type"""
    # Try boolean
    if value.lower() in ('true', 'false'):
        return value.lower() == 'true'

    # Try number
    try:
        if '.' in value:
            return float(value)
        return int(value)
    except ValueError:
        pass

    # Default to string
    return value
```

### Pattern: Workflow Discovery

```python
@cli.command()
@click.option('--detailed', '-d', is_flag=True, help='Show detailed info')
def list(detailed):
    """List available workflows."""

    workflows_dir = Path.home() / ".pflow" / "workflows"

    if not workflows_dir.exists():
        click.echo("No workflows saved yet.")
        click.echo("Save a workflow after planning with: pflow save")
        return

    workflows = []
    for workflow_file in workflows_dir.glob("*.json"):
        if workflow_file.name.endswith(".lock.json"):
            continue

        try:
            data = json.loads(workflow_file.read_text())
            workflows.append({
                "name": workflow_file.stem,
                "description": data.get("description", "No description"),
                "parameters": list(data.get("parameter_defaults", {}).keys()),
                "created": workflow_file.stat().st_mtime
            })
        except:
            continue

    if not workflows:
        click.echo("No workflows found.")
        return

    # Sort by name
    workflows.sort(key=lambda w: w["name"])

    if detailed:
        for w in workflows:
            click.echo(f"\n📋 {w['name']}")
            click.echo(f"   {w['description']}")
            if w['parameters']:
                click.echo(f"   Parameters: {', '.join(w['parameters'])}")
            click.echo(f"   Created: {datetime.fromtimestamp(w['created']).strftime('%Y-%m-%d')}")
    else:
        click.echo("Available workflows:")
        for w in workflows:
            params = f" [{', '.join(w['parameters'])}]" if w['parameters'] else ""
            click.echo(f"  • {w['name']}{params}")
        click.echo("\nRun with: pflow <workflow-name> --param=value")
```

## Advanced Patterns

### Pattern: Parameter Validation
**Source**: Robust execution patterns
**Description**: Validate parameters before execution

```python
def validate_parameter_types(params: Dict, workflow: Dict):
    """Validate parameter types match workflow expectations"""

    if "parameter_schema" in workflow:
        schema = workflow["parameter_schema"]

        for param, spec in schema.items():
            if param in params:
                value = params[param]
                expected_type = spec.get("type", "string")

                if not validate_type(value, expected_type):
                    raise ValueError(
                        f"Parameter '{param}' expects {expected_type}, "
                        f"got {type(value).__name__}"
                    )

            elif spec.get("required", False):
                raise ValueError(f"Required parameter '{param}' not provided")
```

### Pattern: Workflow Versioning
**Source**: Long-term maintenance patterns
**Description**: Handle workflow evolution

```python
def migrate_workflow_version(workflow: Dict) -> Dict:
    """Migrate old workflow formats to current version"""

    version = workflow.get("version", "1.0.0")

    if version == "1.0.0":
        # Current version, no migration needed
        return workflow

    elif version == "0.9.0":
        # Migrate from beta format
        workflow["template_inputs"] = workflow.pop("templates", {})
        workflow["version"] = "1.0.0"
        return workflow

    else:
        raise ValueError(f"Unknown workflow version: {version}")
```

## Testing Approach

```python
def test_named_workflow_execution():
    """Test complete execution flow"""

    # Setup saved workflow
    workflow = {
        "name": "test-flow",
        "nodes": [...],
        "template_inputs": {
            "llm": {"prompt": "Process $data"}
        },
        "parameter_defaults": {
            "model": "gpt-4"
        }
    }

    save_workflow("test-flow", workflow)

    # Execute with parameters
    executor = WorkflowExecutor(...)
    result = executor.execute_named_workflow(
        "test-flow",
        {"data": "test content", "temperature": 0.5}
    )

    assert result["success"]

def test_parameter_resolution():
    """Test template variable resolution"""

    template = "Fix issue: $issue_number in $repo"
    params = {"issue_number": "123", "repo": "owner/name"}

    resolved = resolve_template_string(template, params)
    assert resolved == "Fix issue: 123 in owner/name"

def test_missing_workflow():
    """Test helpful error messages"""

    with pytest.raises(ValueError) as exc:
        executor.execute_named_workflow("fix-isue", {})  # Typo

    assert "Did you mean: fix-issue" in str(exc.value)
```

## Integration Points

### Connection to Task 20 (Workflow Storage)
Task 22 loads workflows saved by Task 20:
```python
# Task 20 saves workflow
storage.save_workflow("fix-issue", workflow_ir)

# Task 22 loads and executes
executor.execute_named_workflow("fix-issue", {"issue": "123"})
```

### Connection to Task 21 (Lockfile System)
Task 22 validates against lockfiles:
```python
# Lockfile ensures deterministic execution
if lockfile_exists(name):
    validate_lockfile(workflow, lockfile)
```

### Connection to Task 17 (Workflow Generation)
Original workflow created by planner:
```python
# Task 17 generates template-driven workflow
workflow = planner.generate_workflow("fix github issue")

# Task 22 executes with different parameters
execute("fix-issue", {"issue": "123"})
execute("fix-issue", {"issue": "456"})
```

## Minimal Test Case

```python
# Save as test_named_execution.py
import json
from pathlib import Path

def test_plan_once_run_forever():
    """Demonstrate core value proposition"""

    # 1. Save a workflow (normally done by planner)
    workflow = {
        "name": "greet",
        "nodes": [
            {"id": "greet", "type": "echo", "params": {}}
        ],
        "template_inputs": {
            "greet": {"message": "Hello, $name!"}
        },
        "start_node": "greet"
    }

    save_path = Path.home() / ".pflow/workflows/greet.json"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(json.dumps(workflow))

    # 2. Execute multiple times with different params
    results = []
    for name in ["Alice", "Bob", "Charlie"]:
        # Simulate execution
        resolved = f"Hello, {name}!"
        results.append(resolved)
        print(f"✓ Executed with name={name}: {resolved}")

    # 3. Verify reusability
    assert len(results) == 3
    assert all("Hello" in r for r in results)
    print("\n✅ Plan Once, Run Forever demonstrated!")

if __name__ == "__main__":
    test_plan_once_run_forever()
```

## Summary

Task 22 delivers pflow's core promise - "Plan Once, Run Forever":

1. **Load saved workflows** - By name with discovery
2. **Apply runtime parameters** - Template resolution
3. **Validate execution** - Lockfile and parameter checks
4. **Execute efficiently** - Reuse planning, just run
5. **Provide great UX** - Clear errors, helpful suggestions

This transforms AI workflow tools from "regenerate every time" to "plan once, parameterize forever" - achieving the 10x efficiency goal.
