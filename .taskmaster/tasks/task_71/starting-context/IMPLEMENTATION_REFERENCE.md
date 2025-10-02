# Task 71: Implementation Reference

This document provides step-by-step implementation instructions with exact code snippets for all Task 71 components.

## Implementation Order

1. [workflow discover command](#1-workflow-discover-command)
2. [registry discover command](#2-registry-discover-command)
3. [registry describe command](#3-registry-describe-command)
4. [--validate-only flag](#4-validate-only-flag)
5. [workflow save command](#5-workflow-save-command)
6. [Enhanced error output](#6-enhanced-error-output)
7. [AGENT_INSTRUCTIONS.md](#7-agent-instructions)

---

## 1. workflow discover Command

**File**: `src/pflow/cli/commands/workflow.py`

**Add to imports**:
```python
from pflow.planning.nodes import WorkflowDiscoveryNode
```

**Add command** (after existing workflow commands):
```python
@workflow.command(name="discover")
@click.argument('query')
def discover_workflows(query: str) -> None:
    """Discover workflows that match your task description.

    Uses LLM to intelligently find relevant existing workflows
    based on a natural language description of what you want to do.

    Example:
        pflow workflow discover "I need to analyze pull requests"
    """
    from pflow.core.workflow_manager import WorkflowManager

    # Create and run discovery node
    node = WorkflowDiscoveryNode()
    shared = {
        "user_input": query,
        "workflow_manager": WorkflowManager(),
    }

    try:
        action = node.run(shared)
    except Exception as e:
        click.echo(f"Error during discovery: {e}", err=True)
        raise click.Abort()

    # Display results
    if action == "found_existing":
        result = shared.get('discovery_result', {})
        workflow = shared.get('found_workflow')

        if workflow and result:
            click.echo(f"\n## {result.get('workflow_name', 'Unknown')}")

            # Get workflow metadata if available
            if 'metadata' in workflow:
                meta = workflow['metadata']
                click.echo(f"**Description**: {meta.get('description', 'No description')}")
                click.echo(f"**Version**: {meta.get('version', '1.0.0')}")

            # Show node flow
            if 'flow' in workflow.get('ir', workflow):
                flow = workflow.get('ir', workflow).get('flow', [])
                flow_str = ' >> '.join([edge['from'] for edge in flow[:3]])
                if len(flow) > 3:
                    flow_str += ' >> ...'
                click.echo(f"**Node Flow**: {flow_str}")

            # Show inputs/outputs
            ir = workflow.get('ir', workflow)
            if inputs := ir.get('inputs'):
                click.echo("**Inputs**:")
                for key, spec in inputs.items():
                    req = "(required)" if spec.get('required') else "(optional)"
                    click.echo(f"  - {key}: {spec.get('type', 'any')} {req} - {spec.get('description', '')}")

            if outputs := ir.get('outputs'):
                click.echo("**Outputs**:")
                for key, spec in outputs.items():
                    click.echo(f"  - {key}: {spec.get('type', 'any')} - {spec.get('description', '')}")

            # Show confidence
            confidence = result.get('confidence', 0)
            click.echo(f"**Confidence**: {confidence:.0%}")

            # Show reasoning
            if reasoning := result.get('reasoning'):
                click.echo(f"\n*Match reasoning*: {reasoning}")
    else:
        click.echo("No matching workflows found.")
        click.echo("\nTip: Try a more specific query or use 'pflow workflow list' to see all workflows.")
```

---

## 2. registry discover Command

**File**: `src/pflow/cli/commands/registry.py`

**Add to imports**:
```python
from pflow.planning.nodes import ComponentBrowsingNode
```

**Add command** (after existing registry commands):
```python
@registry.command(name="discover")
@click.argument('query')
def discover_nodes(query: str) -> None:
    """Discover nodes needed for a specific task.

    Uses LLM to intelligently select relevant nodes based on
    a natural language description of what you want to build.

    Example:
        pflow registry discover "I need to fetch GitHub data and analyze it"
    """
    # Create and run browsing node
    node = ComponentBrowsingNode()
    shared = {"user_input": query}

    try:
        action = node.run(shared)
    except Exception as e:
        click.echo(f"Error during discovery: {e}", err=True)
        raise click.Abort()

    # Display planning context
    if "planning_context" in shared:
        click.echo(shared["planning_context"])
    elif "browsed_components" in shared:
        # Fallback if planning context not built
        components = shared["browsed_components"]
        if node_ids := components.get("node_ids", []):
            click.echo(f"Found {len(node_ids)} relevant nodes:")
            for nid in node_ids:
                click.echo(f"  - {nid}")
        else:
            click.echo("No relevant nodes found.")
    else:
        click.echo("No relevant nodes found.")
        click.echo("\nTip: Try a more specific query or use 'pflow registry list' to see all nodes.")
```

---

## 3. registry describe Command

**File**: `src/pflow/cli/commands/registry.py`

**Add to imports**:
```python
from pflow.planning.context_builder import build_planning_context
```

**Add command**:
```python
@registry.command(name="describe")
@click.argument('node_ids', nargs=-1, required=True)
def describe_nodes(node_ids: tuple[str]) -> None:
    """Get detailed information about specific nodes.

    Shows complete interface specifications including inputs,
    outputs, parameters, and examples.

    Example:
        pflow registry describe github-get-pr llm write-file
    """
    from pflow.registry.registry import Registry

    # Load registry
    registry = Registry()
    registry_metadata = registry.load()

    # Validate node IDs exist
    available_nodes = {node["id"] for node in registry_metadata}
    invalid_nodes = [nid for nid in node_ids if nid not in available_nodes]

    if invalid_nodes:
        click.echo(f"Error: Unknown nodes: {', '.join(invalid_nodes)}", err=True)
        click.echo(f"\nAvailable nodes:", err=True)
        for node in sorted(available_nodes)[:20]:  # Show first 20
            click.echo(f"  - {node}", err=True)
        if len(available_nodes) > 20:
            click.echo(f"  ... and {len(available_nodes) - 20} more", err=True)
        click.echo(f"\nUse 'pflow registry list' to see all nodes.", err=True)
        raise click.Abort()

    # Build detailed context
    try:
        context = build_planning_context(
            selected_node_ids=list(node_ids),
            selected_workflow_names=[],
            registry_metadata=registry_metadata
        )
        click.echo(context)
    except Exception as e:
        click.echo(f"Error building node details: {e}", err=True)
        raise click.Abort()
```

---

## 4. --validate-only Flag

**File**: `src/pflow/cli/main.py`

**Add flag** (around line 2792, with other flags):
```python
@click.option(
    "--validate-only",
    is_flag=True,
    help="Validate workflow without executing it"
)
```

**Add to workflow_command signature** (around line 2800):
```python
def workflow_command(
    ctx: click.Context,
    workflow: tuple[str, ...],
    # ... existing params ...
    validate_only: bool,  # ADD THIS
    # ... more params ...
) -> None:
```

**Add validation logic** (after workflow loading, around line 2950):
```python
    # After loading workflow_data and before execution
    if validate_only:
        from pflow.planning.nodes import ValidatorNode

        click.echo("Validating workflow...")

        # Run validation using ValidatorNode
        node = ValidatorNode()
        shared = {
            "generated_workflow": workflow_data,  # The loaded IR
            "workflow_inputs": params  # Parsed parameters
        }

        try:
            action = node.run(shared)
        except Exception as e:
            click.echo(f"✗ Validation error: {e}", err=True)
            ctx.exit(1)

        validation_result = shared.get("validation_result", {})

        if validation_result.get("valid", False):
            click.echo("✓ Schema validation passed")
            click.echo("✓ Template resolution passed")
            click.echo("✓ Compilation check passed")
            click.echo("✓ Runtime validation passed")
            click.echo("\nWorkflow is ready for execution!")
            ctx.exit(0)
        else:
            # Display validation errors
            errors = validation_result.get("errors", ["Unknown validation error"])
            click.echo("✗ Validation failed:", err=True)
            for error in errors[:10]:  # Show first 10 errors
                click.echo(f"  - {error}", err=True)
            if len(errors) > 10:
                click.echo(f"  ... and {len(errors) - 10} more errors", err=True)
            ctx.exit(1)
```

---

## 5. workflow save Command

**File**: `src/pflow/cli/commands/workflow.py`

**Add to imports**:
```python
from pathlib import Path
import re
from pflow.planning.nodes import MetadataGenerationNode
```

**Add command**:
```python
@workflow.command(name="save")
@click.argument('file_path', type=click.Path(exists=True, readable=True))
@click.argument('name')
@click.argument('description')
@click.option('--delete-draft', is_flag=True, help='Delete source file after save')
@click.option('--force', is_flag=True, help='Overwrite existing workflow')
@click.option('--generate-metadata', is_flag=True, help='Generate rich discovery metadata')
def save_workflow(file_path: str, name: str, description: str,
                  delete_draft: bool, force: bool, generate_metadata: bool) -> None:
    """Save a workflow file to the global library.

    Takes a workflow JSON file (typically a draft from .pflow/workflows/)
    and saves it to the global library at ~/.pflow/workflows/ for reuse
    across all projects.

    Example:
        pflow workflow save .pflow/workflows/draft.json my-analyzer "Analyzes PRs"
    """
    from pflow.core.workflow_manager import WorkflowManager
    from pflow.core.ir_schema import validate_ir
    import json

    # Validate name format
    if not re.match(r'^[a-z0-9-]+$', name):
        click.echo(f"Error: Name must be lowercase letters, numbers, and hyphens only", err=True)
        click.echo(f"  Got: '{name}'", err=True)
        click.echo(f"  Example: 'my-workflow' or 'pr-analyzer-v2'", err=True)
        raise click.Abort()

    if len(name) > 30:
        click.echo(f"Error: Name must be 30 characters or less (got {len(name)})", err=True)
        raise click.Abort()

    # Load workflow
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        click.echo(f"Error: Invalid JSON in {file_path}: {e}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"Error reading file: {e}", err=True)
        raise click.Abort()

    # Extract IR if wrapped
    workflow_ir = data.get("ir", data)

    # Validate IR structure
    try:
        validated_ir = validate_ir(workflow_ir)
    except Exception as e:
        click.echo(f"Error: Invalid workflow: {e}", err=True)
        raise click.Abort()

    # Generate metadata if requested
    metadata = None
    if generate_metadata:
        click.echo("Generating rich metadata...")
        try:
            node = MetadataGenerationNode()
            shared = {"validated_workflow": validated_ir}
            node.run(shared)
            metadata = shared.get("workflow_metadata", {})
            if metadata:
                click.echo(f"  Generated {len(metadata.get('keywords', []))} keywords")
                click.echo(f"  Generated {len(metadata.get('capabilities', []))} capabilities")
        except Exception as e:
            click.echo(f"Warning: Could not generate metadata: {e}", err=True)
            # Continue without metadata

    # Save to library
    manager = WorkflowManager()

    if not force:
        try:
            if manager.exists(name):
                click.echo(f"Error: Workflow '{name}' already exists.", err=True)
                click.echo(f"  Use --force to overwrite.", err=True)
                raise click.Abort()
        except Exception:
            pass  # If exists check fails, continue with save

    try:
        saved_path = manager.save(name, validated_ir, description, metadata)
    except Exception as e:
        click.echo(f"Error saving workflow: {e}", err=True)
        raise click.Abort()

    # Delete draft if requested
    if delete_draft:
        try:
            Path(file_path).unlink()
            click.echo(f"✓ Deleted draft: {file_path}")
        except Exception as e:
            click.echo(f"Warning: Could not delete draft: {e}", err=True)

    # Success output
    click.echo(f"✓ Saved workflow '{name}' to library")
    click.echo(f"  Location: {saved_path}")
    click.echo(f"  Execute with: pflow {name}")

    if metadata:
        click.echo(f"  Discoverable by: {', '.join(metadata.get('keywords', [])[:3])}...")
```

---

## 6. Enhanced Error Output

**File**: `src/pflow/cli/main.py`

**Step 1: Update _handle_workflow_error signature** (around line 1034):
```python
def _handle_workflow_error(
    ctx: click.Context,
    result: ExecutionResult | None,  # ADD THIS PARAMETER
    workflow_trace: Any | None,
    output_format: str,
    workflow_name: str,
    params: dict[str, Any],
    no_repair: bool,  # ADD THIS TOO
) -> None:
```

**Step 2: Replace error display logic** (in _handle_workflow_error):
```python
    if output_format == "json":
        # For JSON mode, include structured errors
        output: dict[str, Any] = {
            "success": False,
            "error": "Workflow execution failed",
            "is_error": True,
        }

        if result and result.errors:
            output["errors"] = result.errors
            output["failed_node"] = result.errors[0].get("node_id") if result.errors else None

        if workflow_trace:
            output["trace_file"] = workflow_trace

        click.echo(json.dumps(output, indent=2))
    else:
        # For text mode, show detailed errors
        if result and result.errors:
            for i, error in enumerate(result.errors, 1):
                if i == 1:
                    click.echo(f"❌ Workflow execution failed", err=True)

                node_id = error.get('node_id', 'unknown')
                category = error.get('category', 'unknown')
                message = error.get('message', 'Unknown error')

                click.echo(f"\nError {i} at node '{node_id}':", err=True)
                click.echo(f"  Category: {category}", err=True)
                click.echo(f"  Message: {message}", err=True)

                # Show raw API response if available
                if raw := error.get('raw_response'):
                    click.echo("\n  API Response:", err=True)
                    if isinstance(raw, dict):
                        # GitHub/API errors often have 'errors' array
                        if errors_list := raw.get('errors'):
                            for api_err in errors_list[:3]:
                                field = api_err.get('field', 'unknown')
                                msg = api_err.get('message', api_err.get('code', 'error'))
                                click.echo(f"    - Field '{field}': {msg}", err=True)
                        elif msg := raw.get('message'):
                            click.echo(f"    {msg}", err=True)

                        if doc_url := raw.get('documentation_url'):
                            click.echo(f"\n  Documentation: {doc_url}", err=True)

                # Show MCP error details
                if mcp := error.get('mcp_error'):
                    click.echo("\n  MCP Tool Error:", err=True)
                    if isinstance(mcp, dict):
                        if details := mcp.get('details'):
                            click.echo(f"    Field: {details.get('field')}", err=True)
                            click.echo(f"    Expected: {details.get('expected')}", err=True)
                            click.echo(f"    Received: {details.get('received')}", err=True)
                        elif msg := mcp.get('message'):
                            click.echo(f"    {msg}", err=True)

                # Show available fields for template errors
                if category == 'template_error' and (available := error.get('available_fields')):
                    click.echo("\n  Available fields in node:", err=True)
                    for field in available[:5]:
                        click.echo(f"    - {field}", err=True)
                    if len(available) > 5:
                        click.echo(f"    ... and {len(available) - 5} more", err=True)

                # Fixable hint
                if error.get('fixable') and no_repair:
                    click.echo("\n  💡 Tip: Remove --no-repair flag to attempt automatic fix", err=True)
        else:
            # Fallback to original generic message
            click.echo(f"cli: Workflow execution failed - Node returned error action", err=True)
            click.echo(f"cli: Check node output above for details", err=True)
```

**Step 3: Update call site** (around line 1205, in workflow_command):
```python
        _handle_workflow_error(
            ctx=ctx,
            result=result,  # ADD THIS
            workflow_trace=workflow_trace,
            output_format=output_format,
            workflow_name=workflow_name,
            params=params,
            no_repair=no_repair,  # ADD THIS
        )
```

**Step 4: Enhance error extraction** in `src/pflow/execution/executor_service.py`

**Find _extract_error_from_shared** (around line 251) and enhance:
```python
def _extract_error_from_shared(
    shared: dict[str, Any], failed_node: str | None
) -> dict[str, Any]:
    """Extract error information from shared store."""
    # ... existing extraction logic ...

    # After getting basic error info, add raw responses
    error = {
        "source": "runtime",
        "category": category,
        "message": error_msg,
        "node_id": failed_node,
        "fixable": True,
    }

    # ADD: Capture raw HTTP responses
    if "response" in shared:
        error["raw_response"] = shared["response"]
        if "status_code" in shared:
            error["status_code"] = shared["status_code"]

    # ADD: Capture MCP results
    if failed_node and failed_node in shared:
        node_data = shared[failed_node]
        if isinstance(node_data, dict):
            if "result" in node_data and isinstance(node_data["result"], dict):
                if "error" in node_data["result"]:
                    error["mcp_error"] = node_data["result"]["error"]

    # ADD: For template errors, note available fields
    if category == "template_error" and failed_node:
        if node_output := shared.get(failed_node):
            if isinstance(node_output, dict):
                error["available_fields"] = list(node_output.keys())[:20]

    return error
```

---

## 7. AGENT_INSTRUCTIONS.md

**File**: Create `docs/AGENT_INSTRUCTIONS.md`

```markdown
# Agent Instructions for pflow Workflow Building

This guide shows AI agents how to use pflow's CLI commands to discover, build, validate, and execute workflows.

## Quick Start

```bash
# 1. Discover what you need
pflow workflow discover "analyze GitHub pull requests"
pflow registry discover "fetch GitHub data and process it"

# 2. Get details
pflow registry describe github-get-pr llm write-file

# 3. Create workflow
mkdir -p .pflow/workflows
# Create .pflow/workflows/draft.json based on discoveries

# 4. Validate
pflow --validate-only .pflow/workflows/draft.json repo=owner/repo

# 5. Execute
pflow --no-repair .pflow/workflows/draft.json repo=owner/repo

# 6. Save for reuse
pflow workflow save .pflow/workflows/draft.json my-workflow "Description"
```

## Discovery Commands

### Find Existing Workflows
```bash
pflow workflow discover "your task description"
```
Returns workflows that match your needs with full metadata.

### Find Relevant Nodes
```bash
pflow registry discover "what you want to build"
```
Returns nodes with complete interface specifications.

### Get Node Details
```bash
pflow registry describe node-id1 node-id2
```
Returns full interface details for specific nodes.

## Building Workflows

### Workflow Structure
```json
{
  "nodes": [
    {
      "id": "fetch",
      "type": "github-get-pr",
      "inputs": {
        "repo": "${repo}",
        "pr_number": "${pr_number}"
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "inputs": {
        "prompt": "Analyze this PR: ${fetch.pr_body}"
      }
    }
  ],
  "flow": [
    {"from": "fetch", "to": "analyze"}
  ],
  "inputs": {
    "repo": {"type": "string", "required": true},
    "pr_number": {"type": "integer", "required": true}
  },
  "outputs": {
    "analysis": {"type": "string", "value": "${analyze.response}"}
  }
}
```

### Template Variables
- Input parameters: `${param_name}`
- Node outputs: `${node_id.output_field}`
- Nested access: `${node_id.data.items[0].title}`

## Validation

Always validate before execution:
```bash
pflow --validate-only workflow.json param1=value1 param2=value2
```

This checks:
- Schema correctness
- Template resolution
- Node types exist
- Flow is valid

## Error Handling

When execution fails with `--no-repair`:
```bash
❌ Workflow execution failed at node: 'create-issue'
   Category: api_validation
   Message: HTTP 422 - Validation Failed

   API Response:
   - Field 'assignees': should be a list (got: string "alice")
```

The error shows:
1. Which node failed
2. Error category (template_error, api_validation, execution_failure)
3. Detailed message with field-level information
4. Available fields for template errors

### Common Fixes

**API Validation Error**:
- Check the field format in error message
- Update node inputs to match expected format
- Example: Change `"alice"` to `["alice"]` for array fields

**Template Error**:
- Check available fields shown in error
- Fix the template path
- Example: Use `${fetch.issues}` not `${fetch.result.issues}`

## Workflow Library

### Save Workflow
```bash
pflow workflow save draft.json my-workflow "Description" --generate-metadata
```

Options:
- `--generate-metadata`: Add discovery keywords
- `--delete-draft`: Remove source file
- `--force`: Overwrite existing

### Use Saved Workflow
```bash
# From anywhere
pflow my-workflow param1=value1 param2=value2
```

## File Organization

**Local drafts** (project-specific):
```
./project/
└── .pflow/
    └── workflows/
        └── draft.json
```

**Global library** (reusable):
```
~/.pflow/
└── workflows/
    └── my-workflow.json
```

## Complete Example

Building a PR analyzer:

```bash
# 1. Discover components
$ pflow registry discover "analyze GitHub PRs with AI"
# Returns: github-get-pr, llm, write-file nodes

# 2. Create workflow
$ cat > .pflow/workflows/pr-analyzer.json << 'EOF'
{
  "nodes": [
    {
      "id": "fetch-pr",
      "type": "github-get-pr",
      "inputs": {
        "repo": "${repo}",
        "pr_number": "${pr_number}"
      }
    },
    {
      "id": "analyze",
      "type": "llm",
      "inputs": {
        "prompt": "Analyze this PR:\n\nTitle: ${fetch-pr.pr_title}\n\nDescription: ${fetch-pr.pr_body}\n\nProvide a code review."
      }
    },
    {
      "id": "save-report",
      "type": "write-file",
      "inputs": {
        "file_path": "pr-${pr_number}-analysis.md",
        "content": "# PR Analysis\n\n${analyze.response}"
      }
    }
  ],
  "flow": [
    {"from": "fetch-pr", "to": "analyze"},
    {"from": "analyze", "to": "save-report"}
  ],
  "inputs": {
    "repo": {"type": "string", "required": true, "description": "Repository (owner/repo)"},
    "pr_number": {"type": "integer", "required": true, "description": "PR number"}
  },
  "outputs": {
    "report_path": {"type": "string", "value": "${save-report.file_path}"}
  }
}
EOF

# 3. Validate
$ pflow --validate-only .pflow/workflows/pr-analyzer.json repo=owner/repo pr_number=123
✓ Schema validation passed
✓ Template resolution passed
✓ Compilation check passed
✓ Runtime validation passed

# 4. Execute
$ pflow --no-repair .pflow/workflows/pr-analyzer.json repo=owner/repo pr_number=123

# 5. Save for reuse
$ pflow workflow save .pflow/workflows/pr-analyzer.json pr-analyzer "Analyzes GitHub PRs" --generate-metadata
✓ Saved workflow 'pr-analyzer' to library

# 6. Use anywhere
$ pflow pr-analyzer repo=another/repo pr_number=456
```

## Tips for Agents

1. **Start with discovery** - Don't guess node names
2. **Validate early** - Catch errors before execution
3. **Use --no-repair** - See full error details for debugging
4. **Save successful workflows** - Build a library for reuse
5. **Check template paths** - Use error output to see available fields
```

---

## Testing Checklist

After implementation, test:

1. **Discovery commands** work with natural language queries
2. **Validation** catches errors without execution
3. **Error output** shows detailed API responses
4. **Save command** creates reusable workflows
5. **End-to-end** agent workflow from discovery to execution