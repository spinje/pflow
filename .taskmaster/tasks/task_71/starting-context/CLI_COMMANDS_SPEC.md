# CLI Commands Specification for Task 71

## Overview

This specification defines CLI commands that enable AI agents to discover pflow capabilities through intelligent, LLM-powered discovery. The key innovation is that agents provide rich descriptions of what they want to build, and receive complete, detailed information about relevant components - mirroring how the planner works internally. Critically, this includes pre-flight validation to catch errors before execution.

## Command 1: `pflow workflow discover`

### Purpose
Discover existing workflows that match a task description through intelligent LLM selection.

### Location
`src/pflow/cli/commands/workflow.py` (add to existing workflow command group)

### Specification

#### Command Syntax
```bash
pflow workflow discover QUERY
```

#### Arguments
- `QUERY`: Rich natural language description of the task (e.g., "I need to analyze pull requests")

#### Implementation Approach

Reuses WorkflowDiscoveryNode directly:
1. Create WorkflowDiscoveryNode instance
2. Setup shared dict with user_input
3. Run node with `node.run(shared)`
4. Display discovery results

#### Output Format

Returns matching workflows with metadata:

```markdown
## pr-analyzer
**Description**: Comprehensive PR analysis workflow
**Node Flow**: github-get-pr >> llm >> write-file
**Inputs**:
  - repo: str (required) - GitHub repository
  - pr_number: int (required) - Pull request number
**Outputs**:
  - report_path: str - Path to generated report
**Capabilities**:
  - Analyzes code changes
  - Identifies potential issues
**Confidence**: 95%
```

### Implementation Code Structure

```python
@workflow.command(name="discover")
@click.argument('query')
def discover_workflows(query):
    """Discover workflows that match your task description.

    Uses LLM to intelligently find relevant existing workflows
    based on a natural language description of what you want to do.
    """
    from pflow.planning.nodes import WorkflowDiscoveryNode
    from pflow.core.workflow_manager import WorkflowManager

    # Setup and run node
    node = WorkflowDiscoveryNode()
    shared = {
        "user_input": query,
        "workflow_manager": WorkflowManager(),
    }

    action = node.run(shared)

    # Display results
    if action == "found_existing":
        result = shared['discovery_result']
        workflow = shared.get('found_workflow')
        # Format and display workflow details
    else:
        click.echo("No matching workflows found.")
```

---

## Command 2: `pflow registry discover`

### Purpose
Discover nodes needed for a specific task through intelligent LLM selection, returning complete interface details.

### Location
`src/pflow/cli/commands/registry.py` (add to existing registry command group)

### Specification

#### Command Syntax
```bash
pflow registry discover QUERY
```

#### Arguments
- `QUERY`: Rich natural language description of the task (e.g., "I need to fetch GitHub issues and analyze them")

#### Implementation Approach

Reuses ComponentBrowsingNode directly:
1. Create ComponentBrowsingNode instance
2. Setup shared dict with user_input
3. Run node with `node.run(shared)`
4. Display planning context with full details

#### Output Format

Returns complete node specifications:

```markdown
## GitHub Operations

### github-get-issue
**Description**: Fetch a specific GitHub issue
**Inputs**:
  - repo: str (required) - Repository in owner/repo format
  - issue_number: int (required) - Issue number
**Outputs**:
  - issue_title: str - Title of the issue
  - issue_body: str - Full issue description
  - issue_state: str - Current state (open/closed)

## AI/LLM Operations

### llm
**Description**: Process text using a language model
**Inputs**:
  - prompt: str (required) - The prompt to send to the LLM
  - model: str (optional, default: "gpt-4") - Model to use
**Outputs**:
  - response: str - The LLM's response
[... complete details for all relevant nodes ...]
```

### Implementation Code Structure

```python
@registry.command(name="discover")
@click.argument('query')
def discover_nodes(query):
    """Discover nodes needed for a specific task.

    Uses LLM to intelligently select relevant nodes based on
    a natural language description of what you want to build.
    """
    from pflow.planning.nodes import ComponentBrowsingNode

    # Setup and run node
    node = ComponentBrowsingNode()
    shared = {"user_input": query}

    action = node.run(shared)

    # Display planning context
    if "planning_context" in shared:
        click.echo(shared["planning_context"])
    else:
        click.echo("No relevant nodes found.")
```

---

## Flag 3: `--validate-only`

### Purpose
Validate a workflow before execution to catch errors early without side effects.

### Location
`src/pflow/cli/main.py` (add to main CLI command)

### Specification

#### Command Syntax
```bash
pflow --validate-only WORKFLOW [PARAMS...]
```

#### Arguments
- `WORKFLOW`: Path to workflow file or saved workflow name
- `PARAMS`: Parameters as key=value pairs (same as normal execution)

#### Implementation Approach

Reuses ValidatorNode's 4-layer validation:
1. Schema validation (IR structure)
2. Template resolution (with provided params)
3. Compilation check (can build Flow object)
4. Runtime validation (ready for execution)

#### Output Format

```
✓ Schema validation passed
✓ Template resolution passed
✓ Compilation check passed
✓ Runtime validation passed

Workflow is ready for execution!
```

Or with errors:

```
✗ Template resolution failed

Error in node 'process-data':
  Template variable ${input_file} is not resolved
  Available variables: output_dir, model_name

Fix the template variables and try again.
```

### Implementation Code

```python
# In src/pflow/cli/main.py, add flag around line 2792:
@click.option("--validate-only", is_flag=True, help="Validate workflow without executing")

# Then in workflow_command function, after loading workflow:
if validate_only:
    from pflow.planning.nodes import ValidatorNode

    # Load and validate workflow
    workflow_ir = load_workflow(workflow_arg)  # existing logic

    # Run validation using ValidatorNode
    node = ValidatorNode()
    shared = {
        "generated_workflow": workflow_ir,
        "workflow_inputs": params  # parsed from command line
    }

    action = node.run(shared)
    validation_result = shared.get("validation_result", {})

    if validation_result.get("valid", False):
        click.echo("✓ Schema validation passed")
        click.echo("✓ Template resolution passed")
        click.echo("✓ Compilation check passed")
        click.echo("✓ Runtime validation passed")
        click.echo("\nWorkflow is ready for execution!")
        ctx.exit(0)
    else:
        # Display specific errors
        for error in validation_result.get("errors", []):
            click.echo(f"✗ {error}", err=True)
        ctx.exit(1)
```

---

## Command 4: `pflow workflow save`

### Purpose
Save a draft workflow file to the global library for reuse across projects.

### Location
`src/pflow/cli/commands/workflow.py` (add to existing workflow command group)

### Specification

#### Command Syntax
```bash
pflow workflow save FILE_PATH NAME DESCRIPTION [OPTIONS]
```

#### Arguments
- `FILE_PATH`: Path to the workflow JSON file to save
- `NAME`: Name for the saved workflow (lowercase with hyphens, max 30 chars)
- `DESCRIPTION`: Human-readable description of what the workflow does

#### Options
- `--delete-draft`: Delete the source file after successful save
- `--force`: Overwrite if workflow with same name exists
- `--generate-metadata`: Use MetadataGenerationNode to create rich discovery metadata

#### Implementation Code

```python
@workflow.command(name="save")
@click.argument('file_path', type=click.Path(exists=True, readable=True))
@click.argument('name')
@click.argument('description')
@click.option('--delete-draft', is_flag=True, help='Delete source file after save')
@click.option('--force', is_flag=True, help='Overwrite existing workflow')
@click.option('--generate-metadata', is_flag=True, help='Generate rich discovery metadata')
def save_workflow(file_path, name, description, delete_draft, force, generate_metadata):
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
    import re
    from pathlib import Path

    # Validate name format
    if not re.match(r'^[a-z0-9-]+$', name):
        click.echo(f"Error: Name must be lowercase with hyphens only", err=True)
        raise click.Abort()

    if len(name) > 30:
        click.echo(f"Error: Name must be 30 characters or less", err=True)
        raise click.Abort()

    # Load and validate workflow
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        click.echo(f"Error: Invalid JSON in {file_path}: {e}", err=True)
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
        from pflow.planning.nodes import MetadataGenerationNode
        node = MetadataGenerationNode()
        shared = {"validated_workflow": validated_ir}
        node.run(shared)
        metadata = shared.get("workflow_metadata", {})

    # Save to library
    manager = WorkflowManager()

    if manager.exists(name) and not force:
        click.echo(f"Error: Workflow '{name}' already exists. Use --force to overwrite.", err=True)
        raise click.Abort()

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
```

---

## Command 5: `pflow registry describe`

### Purpose
Get detailed information about specific nodes, showing complete interface specifications.

### Location
`src/pflow/cli/commands/registry.py` (add to existing registry command group)

### Specification

#### Command Syntax
```bash
pflow registry describe NODE_ID [NODE_ID...]
```

#### Arguments
- `NODE_ID`: One or more node IDs to get detailed information about

#### Implementation Approach

Uses build_planning_context() directly to get full interface details:
1. Load registry metadata
2. Call build_planning_context() with specified node IDs
3. Display complete specifications

#### Output Format

```markdown
### github-get-pr
**Description**: Fetch pull request details from GitHub
**Inputs**:
  - repo: str (required) - Repository in owner/repo format
  - pr_number: int (required) - Pull request number
  - include_diff: bool (optional, default: false) - Include diff content
**Outputs**:
  - pr_title: str - Title of the pull request
  - pr_body: str - Description/body of the PR
  - pr_state: str - Current state (open/closed/merged)
  - diff_content: str - Diff if requested
**Parameters**:
  - github_token: str (optional) - GitHub API token for authentication
**Example**:
  Input: {"repo": "owner/repo", "pr_number": 123}
  Output: {"pr_title": "Fix bug", "pr_body": "...", "pr_state": "open"}
```

### Implementation Code

```python
@registry.command(name="describe")
@click.argument('node_ids', nargs=-1, required=True)
def describe_nodes(node_ids):
    """Get detailed information about specific nodes.

    Shows complete interface specifications including inputs,
    outputs, parameters, and examples.

    Example:
        pflow registry describe github-get-pr llm write-file
    """
    from pflow.registry.registry import Registry
    from pflow.planning.context_builder import build_planning_context

    # Load registry
    registry = Registry()
    registry_metadata = registry.load()

    # Validate node IDs exist
    available_nodes = {node["id"] for node in registry_metadata}
    invalid_nodes = [nid for nid in node_ids if nid not in available_nodes]

    if invalid_nodes:
        click.echo(f"Error: Unknown nodes: {', '.join(invalid_nodes)}", err=True)
        click.echo(f"\nUse 'pflow registry list' to see available nodes.", err=True)
        raise click.Abort()

    # Build detailed context
    context = build_planning_context(
        selected_node_ids=list(node_ids),
        selected_workflow_names=[],
        registry_metadata=registry_metadata
    )

    click.echo(context)
```

---

## Enhancement: Rich Error Output

### Purpose
Display detailed error context when workflow execution fails, especially with --no-repair flag.

### Location
`src/pflow/cli/main.py` (enhance existing error display logic)

### Implementation
Enhance the CLI to show ExecutionResult.errors details instead of generic messages:

```python
# When execution fails, display rich error context:
if result.errors:
    for error in result.errors:
        click.echo(f"✗ Workflow execution failed at node: {error.get('node_id')}", err=True)
        click.echo(f"  Error category: {error.get('category')}", err=True)
        click.echo(f"  Message: {error.get('message')}", err=True)

        if error.get('attempted'):
            click.echo(f"  Attempted: {', '.join(error['attempted'])}", err=True)

        if error.get('available'):
            click.echo(f"  Available fields: {', '.join(error['available'])}", err=True)

        if error.get('fixable'):
            click.echo(f"  Fixable: Yes (enable repair with default flag)", err=True)
```

---

## Complete Agent Workflow Example

### 1. Discovery Phase
```bash
# Agent wants to build GitHub PR analysis
$ pflow workflow discover "I need to analyze pull requests"

# Returns existing workflows that match

$ pflow registry discover "I need to fetch GitHub data and analyze it"

# Returns relevant nodes with complete interface details
```

### 2. Detail Gathering
```bash
# Get specific node details if needed
$ pflow registry describe github-get-pr llm write-file

# Returns full specifications for these exact nodes
```

### 3. Creation Phase
```bash
# Agent creates workflow based on discovered information
$ mkdir -p .pflow/workflows
# Creates: .pflow/workflows/pr-analyzer-draft.json
```

### 4. Validation Phase (CRITICAL)
```bash
# Validate BEFORE execution
$ pflow --validate-only .pflow/workflows/pr-analyzer-draft.json repo=owner/repo pr_number=123

# If errors, fix and re-validate
# No side effects, pure validation
```

### 5. Testing Phase
```bash
# Test with explicit file path
$ pflow --no-repair .pflow/workflows/pr-analyzer-draft.json repo=owner/repo pr_number=123

# Enhanced error output helps debug if failures occur
```

### 6. Save to Library
```bash
$ pflow workflow save .pflow/workflows/pr-analyzer-draft.json custom-pr-analyzer "My custom PR analyzer" --generate-metadata --delete-draft

✓ Saved workflow 'custom-pr-analyzer' to library
  Location: /Users/andfal/.pflow/workflows/custom-pr-analyzer.json
  Execute with: pflow custom-pr-analyzer
✓ Deleted draft: .pflow/workflows/pr-analyzer-draft.json
```

### 7. Reuse Anywhere
```bash
$ cd /different/project
$ pflow custom-pr-analyzer repo=other/repo pr_number=456
```

---

## Key Implementation Considerations

### Direct Node Reuse
All discovery commands reuse planner nodes directly:
1. Create node instance
2. Setup shared dict with minimal inputs
3. Call `node.run(shared)`
4. Access results from shared dict
5. No extraction or wrapper functions needed

### LLM Integration
Discovery commands require:
1. Access to the same LLM service used by the planner
2. Direct reuse of nodes handles all LLM logic
3. Error handling for LLM failures built into nodes

### Performance
- Discovery commands should complete within 2 seconds (including LLM call)
- Validation should be near-instant (no LLM needed)
- Consider caching LLM responses for common queries

### Error Handling
- LLM service unavailable: Nodes handle gracefully
- No matches found: Provide helpful suggestions
- Query too vague: Return broader set with explanation
- Validation errors: Return specific, actionable feedback

---

## Testing Requirements

### Discovery Commands
1. Rich queries return only relevant components
2. Full details are included (not just names)
3. LLM failures are handled gracefully
4. Direct node execution works correctly

### Validation Command
1. All 4 validation layers work independently
2. Template resolution validates with partial params
3. No side effects occur during validation
4. Clear error messages for each validation layer

### Save Command
1. Name validation works correctly
2. Files are saved to correct location
3. --generate-metadata creates rich metadata
4. --delete-draft removes source file
5. --force overwrites existing

### Registry Describe
1. Multiple node IDs work
2. Unknown nodes error gracefully
3. Full interface details displayed
4. Examples included when available

### Integration
1. Complete workflow from discovery to save works
2. Agents can build workflows using discovered information
3. Validation catches errors before execution
4. Saved workflows are executable from any location

---

## File Organization Reference

**Local Drafts** (project-specific):
```
./my-project/
└── .pflow/
    └── workflows/
        └── draft.json    # Agent creates/edits here
```

**Global Library** (reusable everywhere):
```
~/.pflow/
└── workflows/
    └── saved-workflow.json  # After using workflow save
```

**File Path Resolution** (already works in execute):
- Contains `/` or ends with `.json` → File path
- Otherwise → Saved workflow name