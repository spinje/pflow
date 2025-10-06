# Task 76: Detailed Implementation Plan - Registry Run Command

**Command Name**: `pflow registry run` (changed from "execute" per user request)
**Estimated Time**: 3 hours
**Complexity**: Medium (extensive reuse of existing components)

---

## Overview

Implement a `pflow registry run` command that allows executing individual nodes in isolation for testing purposes. This enables agents and users to:
- Test node parameters before building workflows
- Discover output structures for `Any` types
- Verify credentials and authentication
- Reduce workflow development iteration time by ~50%

---

## Phase 1: Command Registration and Basic Structure (30 minutes)

### 1.1 Add Command to Registry CLI

**File**: `src/pflow/cli/registry.py`
**Location**: After line ~722 (after `discover_nodes` command)

```python
@registry.command(name="run")
@click.argument("node_type")
@click.argument("params", nargs=-1)
@click.option("--output-format", type=click.Choice(["text", "json"]), default="text",
              help="Output format (text or json)")
@click.option("--show-structure", is_flag=True,
              help="Show flattened output structure for template usage")
@click.option("--timeout", type=int, default=60,
              help="Execution timeout in seconds")
@click.option("--verbose", "-v", is_flag=True,
              help="Show detailed execution information")
def run_node(
    node_type: str,
    params: tuple[str, ...],
    output_format: str,
    show_structure: bool,
    timeout: int,
    verbose: bool
) -> None:
    """Run a single node with provided parameters for testing.

    Examples:
        pflow registry run read-file file_path=/tmp/test.txt

        pflow registry run llm prompt="Hello world" --output-format json

        pflow registry run mcp-slack-fetch channel=C123 --show-structure

    This command is useful for:
    - Testing node parameters before building workflows
    - Discovering output structure for nodes with 'Any' types
    - Verifying credentials and authentication
    - Quick iteration during workflow development
    """
    from pflow.cli.registry_run import execute_single_node

    execute_single_node(
        node_type=node_type,
        params=params,
        output_format=output_format,
        show_structure=show_structure,
        timeout=timeout,
        verbose=verbose
    )
```

### 1.2 Create Main Implementation Module

**New File**: `src/pflow/cli/registry_run.py`

```python
"""Implementation of registry run command for single node execution."""

import json
import sys
import time
from typing import Any

import click

from pflow.registry import Registry
from pflow.runtime.compiler import import_node_class, _inject_special_parameters
from pflow.cli.main import parse_workflow_params
from pflow.core.validation_utils import is_valid_parameter_name
from pflow.runtime.template_validator import TemplateValidator
from pflow.core.user_errors import MCPError


def execute_single_node(
    node_type: str,
    params: tuple[str, ...],
    output_format: str,
    show_structure: bool,
    timeout: int,
    verbose: bool
) -> None:
    """Execute a single node with provided parameters."""
    # Implementation in subsequent phases
    pass
```

---

## Phase 2: Core Execution Logic (45 minutes)

### 2.1 Parameter Parsing and Validation

**Location**: `src/pflow/cli/registry_run.py` - Add to `execute_single_node`

```python
def execute_single_node(...) -> None:
    """Execute a single node with provided parameters."""

    # Step 1: Parse parameters
    execution_params = parse_workflow_params(params)

    # Step 2: Validate parameter names
    invalid_keys = [k for k in execution_params if not is_valid_parameter_name(k)]
    if invalid_keys:
        click.echo(f"❌ Invalid parameter name(s): {', '.join(invalid_keys)}", err=True)
        click.echo("   Parameter names cannot contain shell special characters ($, |, >, <, &, ;)", err=True)
        sys.exit(1)

    # Step 3: Load registry and validate node exists
    registry = Registry()
    nodes = registry.load()

    # Step 4: Normalize node ID (handle MCP short forms)
    from pflow.cli.registry import _normalize_node_id
    resolved_node = _normalize_node_id(node_type, set(nodes.keys()))

    if not resolved_node or resolved_node not in nodes:
        _handle_unknown_node(node_type, nodes)
        sys.exit(1)

    # Continue to execution...
```

### 2.2 Node Loading and Instantiation

**Location**: Continue in `execute_single_node`

```python
    # Step 5: Import node class
    try:
        node_class = import_node_class(resolved_node, registry)
    except Exception as e:
        click.echo(f"❌ Failed to load node '{resolved_node}': {e}", err=True)
        sys.exit(1)

    # Step 6: Create node instance
    node = node_class()

    # Step 7: Inject special parameters (MCP nodes need server/tool)
    enhanced_params = _inject_special_parameters(
        resolved_node,
        resolved_node,  # node_id same as node_type for single execution
        execution_params,
        registry
    )

    # Step 8: Set parameters on node
    if enhanced_params:
        node.set_params(enhanced_params)
```

### 2.3 Node Execution with Timing

**Location**: Continue in `execute_single_node`

```python
    # Step 9: Create minimal shared store
    shared_store = {}
    # Add execution params to shared (nodes can read from either params or shared)
    shared_store.update(execution_params)

    # Step 10: Execute node with timing
    start_time = time.perf_counter()

    try:
        if verbose:
            click.echo(f"🔄 Running node '{resolved_node}'...")
            if execution_params:
                click.echo("   Parameters:")
                for key, value in execution_params.items():
                    click.echo(f"     {key}: {_format_param_value(value)}")

        # Execute node
        action = node.run(shared_store)

        # Calculate execution time
        execution_time_ms = int((time.perf_counter() - start_time) * 1000)

        # Extract outputs (node writes to shared_store[node_type] by convention)
        outputs = shared_store.get(resolved_node, {})

        # Display results based on mode
        _display_results(
            node_type=resolved_node,
            action=action,
            outputs=outputs,
            shared_store=shared_store,
            execution_time_ms=execution_time_ms,
            output_format=output_format,
            show_structure=show_structure,
            registry=registry,
            verbose=verbose
        )

    except MCPError as e:
        # MCP-specific user-friendly errors
        click.echo(e.format_for_cli(verbose=verbose), err=True)
        sys.exit(1)
    except Exception as e:
        # Generic execution errors
        _handle_execution_error(resolved_node, e, verbose)
        sys.exit(1)
```

---

## Phase 3: Output Formatting (30 minutes)

### 3.1 Result Display Router

**Location**: `src/pflow/cli/registry_run.py` - New function

```python
def _display_results(
    node_type: str,
    action: str,
    outputs: dict[str, Any],
    shared_store: dict[str, Any],
    execution_time_ms: int,
    output_format: str,
    show_structure: bool,
    registry: Registry,
    verbose: bool
) -> None:
    """Display execution results based on output format and options."""

    # Check for error action
    if action == "error":
        error_msg = shared_store.get("error", "Unknown error")
        if output_format == "json":
            _display_json_error(node_type, error_msg, execution_time_ms)
        else:
            _display_text_error(node_type, error_msg, execution_time_ms)
        sys.exit(1)

    # Success cases
    if show_structure:
        _display_structure_output(node_type, outputs, shared_store, registry)
    elif output_format == "json":
        _display_json_output(node_type, outputs, execution_time_ms)
    else:
        _display_text_output(node_type, outputs, execution_time_ms, verbose)
```

### 3.2 Text Output Mode

```python
def _display_text_output(
    node_type: str,
    outputs: dict[str, Any],
    execution_time_ms: int,
    verbose: bool
) -> None:
    """Display results in human-readable text format."""
    click.echo("✓ Node executed successfully\n")

    if outputs:
        click.echo("Outputs:")
        for key, value in outputs.items():
            # Format value for display
            value_str = _format_output_value(value, max_length=200)
            click.echo(f"  {key}: {value_str}")
    else:
        click.echo("No outputs returned")

    click.echo(f"\nExecution time: {execution_time_ms}ms")

    if verbose:
        click.echo(f"Action returned: '{action}'")


def _format_output_value(value: Any, max_length: int = 200) -> str:
    """Format output value for display, truncating if needed."""
    if isinstance(value, dict):
        if len(value) > 3:
            return f"dict with {len(value)} keys"
        return str(value)
    elif isinstance(value, list):
        if len(value) > 3:
            return f"list with {len(value)} items"
        return str(value)
    elif isinstance(value, str):
        if len(value) > max_length:
            return f"{value[:max_length-3]}..."
        return value
    else:
        value_str = str(value)
        if len(value_str) > max_length:
            return f"{value_str[:max_length-3]}..."
        return value_str
```

### 3.3 JSON Output Mode

```python
def _display_json_output(
    node_type: str,
    outputs: dict[str, Any],
    execution_time_ms: int
) -> None:
    """Display results in JSON format for programmatic consumption."""
    result = {
        "success": True,
        "node_type": node_type,
        "outputs": outputs,
        "execution_time_ms": execution_time_ms
    }

    # Use custom serializer for special types
    from pflow.cli.main import json_serializer

    try:
        output = json.dumps(result, indent=2, ensure_ascii=False, default=json_serializer)
        click.echo(output)
    except (TypeError, ValueError) as e:
        # Fallback for serialization issues
        error_result = {
            "success": False,
            "error": f"JSON serialization failed: {str(e)}",
            "node_type": node_type
        }
        click.echo(json.dumps(error_result, indent=2))
```

### 3.4 Structure Output Mode

```python
def _display_structure_output(
    node_type: str,
    outputs: dict[str, Any],
    shared_store: dict[str, Any],
    registry: Registry
) -> None:
    """Display flattened output structure for template variable discovery."""
    click.echo("✓ Node executed successfully\n")

    # Show actual output values (abbreviated)
    if outputs:
        click.echo("Outputs:")
        for key, value in outputs.items():
            value_str = _format_output_value(value, max_length=50)
            click.echo(f"  {key}: {value_str}\n")

    # Get node metadata for interface structure
    nodes_metadata = registry.get_nodes_metadata([node_type])
    if node_type not in nodes_metadata:
        click.echo("Note: Output structure not available for this node")
        return

    interface = nodes_metadata[node_type].get("interface", {})
    outputs_spec = interface.get("outputs", [])

    # Flatten output structure
    all_paths = []
    for output in outputs_spec:
        if isinstance(output, dict):
            key = output.get("key", output.get("name", "unknown"))
            output_type = output.get("type", "any")
            structure = output.get("structure", {})

            # Add base path
            all_paths.append((key, output_type))

            # Flatten nested structure if present
            if structure:
                nested_paths = TemplateValidator._flatten_output_structure(
                    base_key=key,
                    base_type=output_type,
                    structure=structure
                )
                # Skip first as it's the base key we already added
                all_paths.extend(nested_paths[1:])

    # Display available paths
    if all_paths:
        click.echo("Available template paths:")
        MAX_DISPLAYED_FIELDS = 20

        for path, type_str in all_paths[:MAX_DISPLAYED_FIELDS]:
            click.echo(f"  ✓ ${{{node_type}.{path}}} ({type_str})")

        if len(all_paths) > MAX_DISPLAYED_FIELDS:
            remaining = len(all_paths) - MAX_DISPLAYED_FIELDS
            click.echo(f"  ... and {remaining} more paths")

        click.echo("\nUse these paths in workflow templates.")
    else:
        click.echo("No structured outputs defined for this node")
```

---

## Phase 4: Error Handling and User Messages (30 minutes)

### 4.1 Unknown Node Error

```python
def _handle_unknown_node(node_type: str, nodes: dict[str, Any]) -> None:
    """Handle unknown node with helpful suggestions."""
    click.echo(f"❌ Unknown node type: '{node_type}'", err=True)

    # Find similar nodes
    similar = []
    search_term = node_type.lower()

    for name in nodes:
        if search_term in name.lower():
            similar.append(name)
            if len(similar) >= 5:
                break

    if similar:
        click.echo("\nDid you mean:", err=True)
        for name in similar:
            click.echo(f"  - {name}", err=True)
    else:
        # Show first 10 available nodes
        click.echo("\nAvailable nodes:", err=True)
        for i, name in enumerate(sorted(nodes.keys())):
            if i >= 10:
                click.echo(f"  ... and {len(nodes) - 10} more", err=True)
                break
            click.echo(f"  - {name}", err=True)

    click.echo("\nUse 'pflow registry list' to see all nodes.", err=True)
```

### 4.2 Execution Error Handler

```python
def _handle_execution_error(node_type: str, exc: Exception, verbose: bool) -> None:
    """Handle node execution errors with context."""
    error_type = type(exc).__name__

    # Common error patterns
    if isinstance(exc, FileNotFoundError):
        click.echo(f"❌ File not found: {exc}", err=True)
        click.echo("\nVerify the file path exists and is accessible.", err=True)
    elif isinstance(exc, PermissionError):
        click.echo(f"❌ Permission denied: {exc}", err=True)
        click.echo("\nCheck file permissions and access rights.", err=True)
    elif isinstance(exc, ValueError) and "required" in str(exc).lower():
        click.echo(f"❌ Missing required parameter: {exc}", err=True)
        click.echo("\nUse 'pflow registry describe {node_type}' to see required parameters.", err=True)
    elif "timeout" in str(exc).lower():
        click.echo(f"❌ Node execution timed out", err=True)
        click.echo("\nTry increasing timeout with --timeout option.", err=True)
    else:
        # Generic error
        click.echo(f"❌ Node execution failed", err=True)
        click.echo(f"\nNode: {node_type}", err=True)
        click.echo(f"Error: {exc}", err=True)

        if verbose:
            click.echo(f"Error type: {error_type}", err=True)

            # For MCP nodes, provide specific guidance
            if node_type.startswith("mcp-"):
                click.echo("\nFor MCP nodes:", err=True)
                click.echo("  1. Check if server is configured: pflow mcp list", err=True)
                click.echo("  2. Sync the server: pflow mcp sync <server-name>", err=True)
                click.echo("  3. Verify credentials are set (environment variables)", err=True)
```

### 4.3 Helper Functions

```python
def _format_param_value(value: Any) -> str:
    """Format parameter value for display."""
    if isinstance(value, bool):
        return str(value).lower()
    elif isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    elif isinstance(value, str) and len(value) > 50:
        return f"{value[:47]}..."
    return str(value)


def _display_text_error(node_type: str, error_msg: str, execution_time_ms: int) -> None:
    """Display error in text format."""
    click.echo("❌ Node execution failed\n", err=True)
    click.echo(f"Node: {node_type}", err=True)
    click.echo(f"Error: {error_msg}", err=True)
    click.echo(f"\nExecution time: {execution_time_ms}ms", err=True)


def _display_json_error(node_type: str, error_msg: str, execution_time_ms: int) -> None:
    """Display error in JSON format."""
    error_output = {
        "success": False,
        "node_type": node_type,
        "error": error_msg,
        "execution_time_ms": execution_time_ms
    }
    click.echo(json.dumps(error_output, indent=2))
```

---

## Phase 5: Testing Infrastructure (45 minutes)

### 5.1 Unit Tests

**New File**: `tests/test_cli/test_registry_run.py`

```python
"""Tests for pflow registry run command."""

import json
import pytest
from click.testing import CliRunner

from pflow.cli.main import cli


class TestRegistryRun:
    """Test registry run command functionality."""

    def test_command_exists(self):
        """Test that registry run command is registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["registry", "--help"])
        assert "run" in result.output
        assert result.exit_code == 0

    def test_run_simple_node(self, tmp_path):
        """Test running a simple file read node."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, world!")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "registry", "run", "read-file",
            f"file_path={test_file}"
        ])

        assert result.exit_code == 0
        assert "✓ Node executed successfully" in result.output
        assert "content: Hello, world!" in result.output

    def test_run_with_json_output(self, tmp_path):
        """Test JSON output format."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "registry", "run", "read-file",
            f"file_path={test_file}",
            "--output-format", "json"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["success"] is True
        assert output["node_type"] == "read-file"
        assert "content" in output["outputs"]

    def test_parameter_type_inference(self):
        """Test that parameters are correctly type-inferred."""
        runner = CliRunner()

        # Test with shell node (safe for testing)
        result = runner.invoke(cli, [
            "registry", "run", "shell",
            "command=echo test",
            "timeout=5",
            "check=true",
            "--output-format", "json"
        ])

        if result.exit_code == 0:
            output = json.loads(result.output)
            # Verify types were inferred correctly
            # timeout should be int, check should be bool

    def test_unknown_node_error(self):
        """Test error handling for unknown node."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "registry", "run", "nonexistent-node"
        ])

        assert result.exit_code == 1
        assert "Unknown node type" in result.output
        assert "Available nodes:" in result.output or "Did you mean:" in result.output

    def test_missing_required_parameter(self):
        """Test error when required parameter is missing."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "registry", "run", "read-file"
            # Missing file_path parameter
        ])

        assert result.exit_code == 1
        assert "Missing required" in result.output or "Error" in result.output

    def test_invalid_parameter_name(self):
        """Test validation of parameter names."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "registry", "run", "read-file",
            "$invalid=test"  # Invalid character
        ])

        assert result.exit_code == 1
        assert "Invalid parameter name" in result.output

    def test_show_structure_mode(self):
        """Test structure output mode."""
        runner = CliRunner()

        # Use a node with known structure
        result = runner.invoke(cli, [
            "registry", "run", "shell",
            "command=echo test",
            "--show-structure"
        ])

        if result.exit_code == 0:
            assert "Available template paths" in result.output
            assert "${" in result.output  # Template syntax

    @pytest.mark.skipif(
        not pytest.config.getoption("--mcp"),
        reason="MCP tests require --mcp flag"
    )
    def test_mcp_node_execution(self):
        """Test MCP node execution (requires MCP setup)."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "registry", "run", "mcp-filesystem-list_directory",
            "path=/tmp",
            "--output-format", "json"
        ])

        # Should either succeed or fail with MCP-specific error
        if result.exit_code != 0:
            assert "MCP" in result.output or "server" in result.output
```

### 5.2 Integration Tests

**New File**: `tests/test_integration/test_registry_run_integration.py`

```python
"""Integration tests for registry run command."""

import json
import os
import pytest
from click.testing import CliRunner

from pflow.cli.main import cli


class TestRegistryRunIntegration:
    """Integration tests for registry run with real nodes."""

    def test_llm_node_execution(self):
        """Test LLM node execution (requires API key)."""
        if not os.environ.get("ANTHROPIC_API_KEY"):
            pytest.skip("LLM test requires ANTHROPIC_API_KEY")

        runner = CliRunner()
        result = runner.invoke(cli, [
            "registry", "run", "llm",
            "prompt=Say hello in one word",
            "--output-format", "json"
        ])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["success"] is True
        assert "response" in output["outputs"]

    def test_git_node_execution(self, tmp_path):
        """Test git node execution."""
        # Initialize git repo
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            os.system("git init")
            os.system("git config user.email 'test@example.com'")
            os.system("git config user.name 'Test User'")

            # Create and add file
            test_file = "test.txt"
            with open(test_file, "w") as f:
                f.write("test content")
            os.system(f"git add {test_file}")

            # Run git-commit node
            result = runner.invoke(cli, [
                "registry", "run", "git-commit",
                "message=Test commit",
                "--output-format", "json"
            ])

            if result.exit_code == 0:
                output = json.loads(result.output)
                assert "commit_sha" in output["outputs"]

    def test_workflow_building_pattern(self, tmp_path):
        """Test the explore -> test -> build pattern."""
        runner = CliRunner()

        # Step 1: Discover nodes
        result = runner.invoke(cli, [
            "registry", "discover",
            "read a file and count words"
        ])
        # Should suggest read-file and possibly text processing nodes

        # Step 2: Test read-file node
        test_file = tmp_path / "sample.txt"
        test_file.write_text("one two three four five")

        result = runner.invoke(cli, [
            "registry", "run", "read-file",
            f"file_path={test_file}",
            "--show-structure"
        ])

        assert result.exit_code == 0
        assert "${read-file.content}" in result.output

        # Step 3: Now agent knows the structure and can build workflow
        # (This demonstrates the value of the run command)
```

---

## Phase 6: Documentation Updates (30 minutes)

### 6.1 Update AGENT_INSTRUCTIONS.md

**File**: `.pflow/instructions/AGENT_INSTRUCTIONS.md`

#### Add to Pre-Build Checklist (after line ~695)

```markdown
### ✅ Critical Nodes Tested (Strongly Recommended)

Before building workflows with unfamiliar nodes, test them individually:

- [ ] I've tested MCP nodes with `pflow registry run` to verify parameters work
- [ ] I've confirmed authentication/credentials work for external services
- [ ] I've seen exact output structure for nodes with `Any` types
- [ ] I'm confident about parameter formats (especially arrays/objects)

**Why test nodes first?**
- **Catch errors early**: Parameter format issues, auth problems, etc.
- **See real output**: No guessing about structure, especially for `Any` types
- **Build with confidence**: Fewer workflow iterations, faster development
- **Save time**: Testing takes seconds, debugging workflows takes minutes

**Quick test examples:**
```bash
# Test basic node
pflow registry run read-file file_path=/tmp/test.txt

# See output structure for Any types
pflow registry run mcp-slack-fetch channel=C123 --show-structure

# Test with complex parameters
pflow registry run github-create-issue repo=owner/repo title="Bug" assignees='["user1","user2"]'
```
```

#### Add to Testing & Debugging Section (after line ~900)

```markdown
## Testing Individual Nodes

The `pflow registry run` command lets you test nodes in isolation before building workflows.

### Basic Usage

```bash
pflow registry run <node-type> param1=value1 param2=value2
```

### Output Modes

**Text (default)** - Human-readable output:
```bash
pflow registry run read-file file_path=/tmp/test.txt

✓ Node executed successfully

Outputs:
  content: "File contents here..."
  file_size: 42
  encoding: "utf-8"

Execution time: 12ms
```

**JSON** - For programmatic processing:
```bash
pflow registry run read-file file_path=/tmp/test.txt --output-format json

{
  "success": true,
  "node_type": "read-file",
  "outputs": {
    "content": "File contents here...",
    "file_size": 42,
    "encoding": "utf-8"
  },
  "execution_time_ms": 12
}
```

**Structure** - Discover template paths for `Any` types:
```bash
pflow registry run mcp-slack-fetch channel=C123 --show-structure

✓ Node executed successfully

Outputs:
  result: dict with 2 keys

Available template paths:
  ✓ ${mcp-slack-fetch.result} (dict)
  ✓ ${mcp-slack-fetch.result.messages} (array)
  ✓ ${mcp-slack-fetch.result.messages[0].text} (string)
  ✓ ${mcp-slack-fetch.result.messages[0].user} (string)
  ✓ ${mcp-slack-fetch.result.has_more} (boolean)

Use these paths in workflow templates.
```

### Common Testing Scenarios

#### 1. Exploring MCP Tools

When working with unfamiliar MCP tools, use the exploration pattern:

```bash
# Step 1: List available resources
pflow registry run mcp-replicate-COLLECTIONS_LIST --show-structure

# Step 2: Get details about specific resource
pflow registry run mcp-replicate-MODELS_GET model_name=sdxl owner=stability-ai --show-structure

# Step 3: See examples
pflow registry run mcp-replicate-MODELS_EXAMPLES_LIST model_name=sdxl owner=stability-ai

# Step 4: Test actual operation
pflow registry run mcp-replicate-CREATE_PREDICTION deployment=sdxl input='{"prompt":"cat"}'

# Now build workflow with confidence!
```

#### 2. Verifying Authentication

Before building workflows with authenticated services:

```bash
# Test GitHub authentication
pflow registry run github-get-issue repo=anthropics/pflow issue=1

# Test Slack MCP
pflow registry run mcp-slack-SLACK_SEND_MESSAGE channel=general text="Test"

# If auth fails, fix credentials BEFORE building workflow
```

#### 3. Testing Parameter Formats

Ensure complex parameters work correctly:

```bash
# Arrays
pflow registry run github-create-issue \
  repo=owner/repo \
  title="Test" \
  assignees='["user1","user2"]'  # JSON array format

# Objects
pflow registry run custom-node \
  config='{"retry":3,"timeout":30}'  # JSON object format

# Booleans and numbers
pflow registry run shell \
  command="echo test" \
  check=true \
  timeout=30
```

### Parameter Type Inference

The run command automatically infers parameter types:

| Input | Inferred Type | Example |
|-------|--------------|---------|
| `true`, `false` | Boolean | `verbose=true` → `True` |
| Integers | Number | `count=5` → `5` |
| Decimals | Float | `temperature=0.7` → `0.7` |
| `[...]` | Array | `items='["a","b"]'` → `["a","b"]` |
| `{...}` | Object | `cfg='{"k":"v"}'` → `{"k":"v"}` |
| Everything else | String | `name=test` → `"test"` |

### Tips for Efficient Testing

1. **Start simple**: Test with minimal parameters first
2. **Use --show-structure**: Essential for nodes with `Any` return types
3. **Check auth early**: Test credential-required nodes before complex workflows
4. **Save working params**: Document working parameter combinations
5. **Test edge cases**: Empty inputs, large data, special characters

### When to Use Registry Run

✅ **ALWAYS test when:**
- Working with MCP nodes (especially new ones)
- Node returns `Any` type
- Using complex parameter formats
- Node requires authentication
- Exploring unfamiliar tools

❌ **Skip testing for:**
- Simple nodes you've used before
- Nodes with clear, simple interfaces
- When you're confident about parameters
```

### 6.2 Update CLI Help Text

**File**: `src/pflow/cli/registry.py` - Update module docstring

```python
"""Registry commands for node discovery and testing.

Commands:
    list        List all registered nodes
    search      Search nodes by name
    describe    Show detailed node information
    discover    Find nodes for a task using AI
    run         Execute a node for testing (NEW)
"""
```

---

## Phase 7: Integration Testing and Validation (30 minutes)

### 7.1 Manual Test Checklist

```bash
# 1. Test simple node
echo "test content" > /tmp/test.txt
pflow registry run read-file file_path=/tmp/test.txt

# 2. Test JSON output
pflow registry run read-file file_path=/tmp/test.txt --output-format json

# 3. Test structure mode
pflow registry run shell command="echo test" --show-structure

# 4. Test parameter types
pflow registry run shell command="echo test" timeout=5 check=true --verbose

# 5. Test unknown node
pflow registry run nonexistent-node

# 6. Test missing parameter
pflow registry run read-file

# 7. Test invalid parameter name
pflow registry run read-file '$bad=test'

# 8. Test MCP node (if available)
pflow registry run mcp-filesystem-list_directory path=/tmp --show-structure

# 9. Test LLM node (if API key set)
pflow registry run llm prompt="Say hello" --output-format json

# 10. Test error handling
pflow registry run read-file file_path=/nonexistent/file.txt
```

### 7.2 Automated Test Execution

```bash
# Run unit tests
uv run pytest tests/test_cli/test_registry_run.py -xvs

# Run integration tests
uv run pytest tests/test_integration/test_registry_run_integration.py -xvs

# Run with coverage
uv run pytest tests/test_cli/test_registry_run.py --cov=pflow.cli.registry_run

# Run all registry tests
uv run pytest tests/ -k "registry" -xvs
```

### 7.3 Performance Validation

Expected performance metrics:
- Simple node execution: < 100ms overhead
- MCP node execution: < 500ms overhead (depends on server)
- Output formatting: < 50ms
- Total command overhead: < 200ms

---

## Implementation Checklist

- [ ] Phase 1: Command Registration
  - [ ] Add command to registry.py
  - [ ] Create registry_run.py module
  - [ ] Verify command appears in help

- [ ] Phase 2: Core Execution
  - [ ] Parameter parsing with type inference
  - [ ] Node loading and instantiation
  - [ ] Special parameter injection for MCP
  - [ ] Node execution with timing

- [ ] Phase 3: Output Formatting
  - [ ] Text mode with abbreviated values
  - [ ] JSON mode with custom serializer
  - [ ] Structure mode with template paths
  - [ ] Error display for both modes

- [ ] Phase 4: Error Handling
  - [ ] Unknown node with suggestions
  - [ ] Missing parameter guidance
  - [ ] Execution error messages
  - [ ] MCP-specific error handling

- [ ] Phase 5: Testing
  - [ ] Unit tests for command
  - [ ] Integration tests with real nodes
  - [ ] Parameter type inference tests
  - [ ] Error case coverage

- [ ] Phase 6: Documentation
  - [ ] Update AGENT_INSTRUCTIONS.md
  - [ ] Add to Pre-Build Checklist
  - [ ] Add to Testing & Debugging
  - [ ] Update CLI help text

- [ ] Phase 7: Validation
  - [ ] Manual testing checklist
  - [ ] Performance validation
  - [ ] Agent workflow testing

---

## Success Criteria

✅ Command executes any registered node with parameters
✅ Three output modes work correctly (text/json/structure)
✅ Error messages are helpful and actionable
✅ MCP nodes execute with proper parameter injection
✅ Tests provide good coverage of functionality
✅ Documentation helps agents use the command effectively
✅ Performance meets expectations (< 200ms overhead)

---

## Notes for Implementation

1. **Import Statements**: Some imports may need adjustment based on actual module structure
2. **MCP Testing**: MCP tests require server configuration - mark with skipif decorator
3. **Type Inference**: Reuse exact logic from main.py to ensure consistency
4. **Error Messages**: Keep agent-friendly - what went wrong, why, how to fix
5. **Performance**: Keep overhead minimal - agents will use this frequently
6. **Documentation**: Critical for adoption - agents won't use undocumented features

This implementation plan provides a complete blueprint for adding the `pflow registry run` command in approximately 3 hours of focused development.