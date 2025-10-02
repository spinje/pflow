# CLI Commands Specification for Task 71

## Overview

This specification defines CLI commands that enable AI agents to discover pflow capabilities through intelligent, LLM-powered discovery. The key innovation is that agents provide rich descriptions of what they want to build, and receive complete, detailed information about relevant components - mirroring how the planner works internally.

## Command 1: `pflow discover-nodes`

### Purpose
Discover all nodes needed for a specific task through intelligent LLM selection, returning complete interface details.

### Location
`src/pflow/cli/commands/discover.py` (new file)

### Specification

#### Command Syntax
```bash
pflow discover-nodes QUERY
```

#### Arguments
- `QUERY`: Rich natural language description of the task (e.g., "I need to analyze GitHub PRs and create reports")

#### Implementation Approach

Reuses ComponentBrowsingNode pattern:
1. Load all nodes from Registry
2. Build context with all node descriptions
3. Send to LLM with query for selection
4. Return full interface details for selected nodes

#### Output Format

Returns complete node specifications grouped by category:

```markdown
## GitHub Operations

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
**Example**:
  Input: {"repo": "owner/repo", "pr_number": 123}
  Output: {"pr_title": "Fix bug", "pr_body": "...", "pr_state": "open"}

### github-list-prs
**Description**: List pull requests for a repository
[... complete interface details ...]

## AI/LLM Operations

### llm
**Description**: Process text using a language model
**Inputs**:
  - prompt: str (required) - The prompt to send to the LLM
  - model: str (optional, default: "gpt-4") - Model to use
  - temperature: float (optional, default: 0.7) - Sampling temperature
**Outputs**:
  - response: str - The LLM's response
  - tokens_used: int - Number of tokens consumed
[... complete details for all relevant nodes ...]
```

### Implementation Code Structure

```python
@click.command(name="discover-nodes")
@click.argument('query')
def discover_nodes(query):
    """Discover nodes needed for a specific task.

    Uses LLM to intelligently select relevant nodes based on
    a natural language description of what you want to build.
    """
    from pflow.registry.registry import Registry
    from pflow.planning.context_builder import build_nodes_context
    from pflow.planning.nodes import ComponentBrowsingNode

    # Load all nodes
    registry = Registry()
    all_nodes = registry.load()

    # Use ComponentBrowsingNode logic for LLM selection
    # (This would need to be extracted/reused)
    selected_node_ids = select_nodes_with_llm(query, all_nodes)

    # Build detailed context for selected nodes
    detailed_context = build_nodes_context(
        node_ids=selected_node_ids,
        registry_metadata=all_nodes,
        include_full_details=True  # May need enhancement
    )

    click.echo(detailed_context)
```

---

## Command 2: `pflow discover-workflows`

### Purpose
Discover existing workflows that match a task description through intelligent LLM selection, returning complete workflow metadata.

### Location
`src/pflow/cli/commands/discover.py`

### Specification

#### Command Syntax
```bash
pflow discover-workflows QUERY
```

#### Arguments
- `QUERY`: Rich natural language description of the task (e.g., "I need to analyze pull requests")

#### Implementation Approach

Reuses WorkflowDiscoveryNode pattern:
1. Load all workflows from WorkflowManager
2. Build context with workflow descriptions and capabilities
3. Send to LLM with query for selection
4. Return complete metadata for selected workflows

#### Output Format

Returns complete workflow details:

```markdown
## pr-analyzer
**Description**: Comprehensive pull request analysis workflow
**Version**: 1.2.0
**Created**: 2024-01-15
**Node Flow**: github-get-pr >> extract-diff >> llm >> format-report >> write-file
**Inputs**:
  - repo: str (required) - GitHub repository (owner/repo format)
  - pr_number: int (required) - Pull request number to analyze
  - output_format: str (optional, default: "markdown") - Report format
**Outputs**:
  - report_path: str - Path to generated analysis report
  - summary: str - Brief summary of the analysis
  - issues_found: int - Number of potential issues identified
**Capabilities**:
  - Analyzes code changes for potential issues
  - Identifies security vulnerabilities
  - Suggests improvements for code quality
  - Generates detailed reports in multiple formats
**Keywords**: github, pr, pull-request, code-review, analysis, automation
**Example Usage**:
  pflow execute pr-analyzer --param repo="owner/repo" --param pr_number=123
**Execution Statistics**:
  - Total executions: 47
  - Average duration: 3.2 seconds
  - Last executed: 2024-01-20 14:30:00
  - Success rate: 95.7%

## code-reviewer
**Description**: Automated code review workflow
[... complete details for all relevant workflows ...]
```

### Implementation Code Structure

```python
@click.command(name="discover-workflows")
@click.argument('query')
def discover_workflows(query):
    """Discover workflows that match your task description.

    Uses LLM to intelligently find relevant existing workflows
    based on a natural language description of what you want to do.
    """
    from pflow.core.workflow_manager import WorkflowManager
    from pflow.planning.context_builder import build_workflows_context
    from pflow.planning.nodes import WorkflowDiscoveryNode

    # Load all workflows
    wm = WorkflowManager()
    all_workflows = wm.list_all()

    # Use WorkflowDiscoveryNode logic for LLM selection
    # (This would need to be extracted/reused)
    selected_workflows = select_workflows_with_llm(query, all_workflows)

    # Build detailed context for selected workflows
    detailed_context = build_workflows_context(
        workflow_names=[w['name'] for w in selected_workflows],
        workflow_manager=wm,
        include_full_details=True  # Include all metadata
    )

    click.echo(detailed_context)
```

---

## Command 3: `pflow workflow save`

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
- `FILE_PATH`: Path to the workflow JSON file to save (e.g., `.pflow/workflows/draft.json`)
- `NAME`: Name for the saved workflow (lowercase with hyphens, max 30 chars)
- `DESCRIPTION`: Human-readable description of what the workflow does

#### Options
- `--delete-draft`: Delete the source file after successful save
- `--force`: Overwrite if workflow with same name exists

#### Implementation Code

```python
@workflow.command(name="save")
@click.argument('file_path', type=click.Path(exists=True, readable=True))
@click.argument('name')
@click.argument('description')
@click.option('--delete-draft', is_flag=True, help='Delete source file after save')
@click.option('--force', is_flag=True, help='Overwrite existing workflow')
def save_workflow(file_path, name, description, delete_draft, force):
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

    # Save to library
    manager = WorkflowManager()

    if manager.exists(name) and not force:
        click.echo(f"Error: Workflow '{name}' already exists. Use --force to overwrite.", err=True)
        raise click.Abort()

    try:
        saved_path = manager.save(name, validated_ir, description)
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
    click.echo(f"  Execute with: pflow execute {name}")
```

---

## Command 4: `pflow workflow describe --json` (Enhancement)

### Purpose
Add JSON output option to existing describe command for programmatic access.

### Location
`src/pflow/cli/commands/workflow.py` (modify existing command)

### Changes Required

Add `--json` option to existing command:

```python
@workflow.command(name="describe")
@click.argument("name")
@click.option('--json', 'output_json', is_flag=True, help='Output as JSON')  # NEW
def describe_workflow(name: str, output_json: bool) -> None:  # MODIFIED
    """Show workflow details including inputs and outputs."""
    wm = WorkflowManager()

    try:
        metadata = wm.load(name)
    except FileNotFoundError:
        click.echo(f"Error: Workflow '{name}' not found", err=True)
        raise click.Abort()

    if output_json:  # NEW BLOCK
        import json
        output = {
            'name': metadata['name'],
            'description': metadata.get('description', ''),
            'version': metadata.get('version', '1.0.0'),
            'created_at': metadata.get('created_at'),
            'inputs': metadata['ir'].get('inputs', {}),
            'outputs': metadata['ir'].get('outputs', {}),
            'nodes': [n['id'] for n in metadata['ir'].get('nodes', [])],
            'flow': metadata['ir'].get('flow', []),
            'rich_metadata': metadata.get('rich_metadata', {})
        }
        click.echo(json.dumps(output, indent=2))
    else:
        # ... existing text output code ...
```

---

## Complete Agent Workflow Example

### 1. Discovery Phase
```bash
# Agent wants to build GitHub PR analysis
$ pflow discover-nodes "I need to analyze GitHub pull requests and generate reports"

# Returns complete interface details for:
# - github-get-pr, github-list-prs
# - llm (for analysis)
# - write-file (for reports)
# With full input/output specifications

$ pflow discover-workflows "PR analysis"

# Returns any existing workflows that do PR analysis
# With complete flow, capabilities, and usage examples
```

### 2. Creation Phase
```bash
# Agent creates workflow based on discovered information
$ mkdir -p .pflow/workflows
# Creates: .pflow/workflows/pr-analyzer-draft.json
```

### 3. Testing Phase
```bash
# Test with explicit file path
$ pflow execute .pflow/workflows/pr-analyzer-draft.json --param repo="owner/repo" --param pr_number=123

# If error: "Template ${output_format} not resolved"
# Agent fixes the JSON and re-executes
# Checkpoint automatically resumes from failure point
```

### 4. Save to Library
```bash
$ pflow workflow save .pflow/workflows/pr-analyzer-draft.json custom-pr-analyzer "My custom PR analyzer" --delete-draft

✓ Saved workflow 'custom-pr-analyzer' to library
  Location: /home/user/.pflow/workflows/custom-pr-analyzer.json
  Execute with: pflow execute custom-pr-analyzer
✓ Deleted draft: .pflow/workflows/pr-analyzer-draft.json
```

### 5. Reuse Anywhere
```bash
$ cd /different/project
$ pflow execute custom-pr-analyzer --param repo="other/repo" --param pr_number=456
```

---

## Key Implementation Considerations

### LLM Integration
Both discovery commands require:
1. Access to the same LLM service used by the planner
2. Extraction/reuse of selection logic from ComponentBrowsingNode and WorkflowDiscoveryNode
3. Error handling for LLM failures

### Context Building
May need to enhance:
- `build_nodes_context()` to include more complete interface details
- `build_workflows_context()` to include all rich metadata

### Performance
- Discovery commands should complete within 2 seconds (including LLM call)
- Consider caching LLM responses for common queries
- May need to batch/limit results for very large registries

### Error Handling
- LLM service unavailable: Suggest simpler query or list all
- No matches found: Provide helpful suggestions
- Query too vague: Return broader set with explanation

---

## Testing Requirements

### Discovery Commands
1. Rich queries return only relevant components
2. Full details are included (not just names)
3. LLM failures are handled gracefully
4. Performance stays within 2-second target

### Save Command
1. Name validation works correctly
2. Files are saved to correct location
3. `--delete-draft` removes source file
4. `--force` overwrites existing

### Integration
1. Complete workflow from discovery to save works
2. Agents can build workflows using discovered information
3. Saved workflows are executable from any location

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