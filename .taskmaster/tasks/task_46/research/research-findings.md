# Task 46 Research Findings: Workflow Export to Zero-Dependency Code

## Executive Summary

This document contains comprehensive research gathered from the pflow codebase to inform the implementation of Task 46 (Workflow Export to Zero-Dependency Code). The research covers IR schema, runtime compilation, node implementations, template resolution, workflow management, security considerations, and existing code generation patterns.

**Key Finding**: pflow has a well-structured IR format and robust runtime system that can be systematically transformed into standalone Python code. The export feature should follow the existing formatter pattern (return-based, type-safe) and leverage the compiler's reverse process.

---

## 1. IR Schema Format (Foundation for Export)

### Complete Structure

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "unique-id",
      "type": "node-type",
      "purpose": "description",
      "params": {
        "key": "value",
        "nested": "${template}"
      }
    }
  ],
  "edges": [
    {
      "from": "source-node-id",
      "to": "target-node-id",
      "action": "default"
    }
  ],
  "inputs": {
    "param_name": {
      "description": "Human-readable description",
      "required": true,
      "type": "string",
      "default": "default-value"
    }
  },
  "outputs": {
    "output_name": {
      "description": "Output description",
      "type": "string",
      "source": "${node_id.output_key}"
    }
  },
  "mappings": {
    "node_id": {
      "input_mappings": {"node_expected": "shared_key"},
      "output_mappings": {"node_output": "shared_key"}
    }
  },
  "enable_namespacing": true,
  "template_resolution_mode": "strict"
}
```

### Key Fields for Export

1. **`nodes`** - Array of node definitions to transform into Python functions/classes
2. **`edges`** - Flow control to transform into function calls or if/else routing
3. **`inputs`** - Workflow parameters to transform into function arguments
4. **`outputs`** - Return values to extract from shared store
5. **`enable_namespacing`** - Affects variable naming (namespaced vs flat)
6. **Template variables** - `${var}` syntax needs Python f-string or `.format()` conversion

### Examples Found

- **Minimal**: Single node, no edges
- **Pipeline**: Sequential nodes with edges
- **Templates**: Heavy use of `${variable}` throughout
- **Error handling**: Action-based routing with "error" edges
- **Nested workflows**: `workflow` node type calling sub-workflows

---

## 2. Runtime Compilation Process (What to Reverse)

### 11-Step Compilation Pipeline

The `compile_ir_to_flow()` function transforms IR → executable Flow:

1. Parse IR (JSON → dict)
2. Validate structure (schema + business logic)
3. Instantiate nodes (with wrapper chain)
4. Wire nodes (using `>>` operator)
5. Identify start node
6. Create Flow object
7. Wrap flow.run() for outputs

**For Export**: We reverse steps 3-6 to generate Python code instead of PocketFlow objects.

### Node Instantiation Pattern

```python
# Current: Create wrapped node instance
node_instance = NodeClass()
node_instance = TemplateAwareNodeWrapper(node_instance, ...)
node_instance = NamespacedNodeWrapper(node_instance, ...)
node_instance = InstrumentedNodeWrapper(node_instance, ...)

# Export: Generate Python function
def node_id():
    """Node purpose/description"""
    # Resolve templates
    param1 = resolve_variable("variable")

    # Execute node logic
    result = subprocess.run([...])

    # Store results
    shared["node_id"] = {"output": result.stdout}
    return "default"  # or "error"
```

### Wrapper Chain Mapping

| Wrapper | Export Equivalent |
|---------|-------------------|
| **TemplateAwareNodeWrapper** | Inline template resolution code |
| **NamespacedNodeWrapper** | Namespaced dict keys (`shared["node_id"]["key"]`) |
| **InstrumentedNodeWrapper** | Optional: timing/logging code |

### Edge Wiring Pattern

```python
# Current IR:
{"from": "fetch", "to": "process", "action": "default"}
{"from": "fetch", "to": "error_handler", "action": "error"}

# Export to:
fetch_action = fetch()
if fetch_action == "error":
    error_handler()
else:
    process()
```

---

## 3. Node Implementation Survey

### Complete Node Inventory (11 Types)

#### Stdlib-Only Nodes (Phase 1 - Easy)
1. **shell** - `subprocess.run()`
2. **read-file** - `open()` + `.read()`
3. **write-file** - `open()` + `.write()`, atomic with temp file
4. **copy-file** - `shutil.copy2()`
5. **move-file** - `shutil.move()`
6. **delete-file** - `os.remove()`
7. **git-*** - `subprocess.run(['git', ...])`
8. **github-*** - `subprocess.run(['gh', ...])`

#### Nodes Requiring Packages (Phase 2 - Medium)
9. **llm** - `import llm` (pip install llm)
10. **http** - `import requests` (pip install requests)

#### Complex Nodes (Phase 3 - Hard)
11. **mcp-*** - Virtual nodes, async, server config, two transports

### Common Node Pattern

All nodes follow the same lifecycle:

```python
class SomeNode(Node):
    def prep(self, shared: dict) -> dict:
        """Extract and validate parameters."""
        param = shared.get("input") or self.params.get("param")
        return {"param": param}

    def exec(self, prep_res: dict) -> dict:
        """Execute main logic (NO try/except)."""
        result = do_something(prep_res["param"])
        return {"result": result}

    def post(self, shared: dict, prep_res: dict, exec_res: dict) -> str:
        """Store results, return action."""
        shared["output"] = exec_res["result"]
        return "default"
```

### Export Template

```python
def node_id():
    """Node: {node_id} - {purpose}"""
    # prep() → Inline parameter extraction
    param = shared.get("input") or initial_params.get("param")

    # exec() → Inline main logic
    result = subprocess.run([...], capture_output=True, text=True)

    # post() → Store results and return action
    if result.returncode == 0:
        shared["node_id"]["output"] = result.stdout
        return "default"
    else:
        shared["node_id"]["error"] = result.stderr
        return "error"
```

### Binary Data Handling

Nodes use base64 encoding for binary data:

```python
# In exported code:
if not is_text:
    import base64
    shared["node_id"]["content"] = base64.b64encode(data).decode('ascii')
    shared["node_id"]["encoding"] = "base64"
```

---

## 4. Template Variable System

### Syntax: `${variable}`

Supported formats:
- Simple: `${var}`
- Nested: `${data.field.subfield}`
- Array: `${items[0].name}`
- Complex: `${data[5].users[2].email}`

### Resolution Algorithm

**Priority Order**:
1. `initial_params` (CLI flags, planner extraction)
2. Shared store (runtime data from nodes)
3. Workflow inputs (declared defaults)

**Type Preservation**:
- Simple template → Original type preserved
  - `${count}` → `42` (int, not "42")
  - `${enabled}` → `True` (bool, not "True")
  - `${data}` → `{"key": "val"}` (dict)
- Complex template → Always string
  - `"Count: ${count}"` → `"Count: 42"` (string)

### Export Transformation

```python
# IR template: "${fetch.response.items[0].title}"
# Export as Python:

# Option 1: Direct access (if simple)
title = shared["fetch"]["response"]["items"][0]["title"]

# Option 2: Safe traversal (if complex)
def resolve_template(path: str, context: dict) -> Any:
    """Resolve ${path} from context."""
    parts = path.split(".")
    value = context
    for part in parts:
        if "[" in part:  # Array access
            key, idx = part.split("[")
            value = value[key][int(idx.rstrip("]"))]
        else:
            value = value[part]
    return value

title = resolve_template("fetch.response.items[0].title", shared)
```

### Validation Points

1. **Compile-time**: Check template paths exist in node interfaces
2. **Runtime**: Detect unresolved/partially-resolved templates
3. **Type checking**: Ensure template type matches parameter expectation

**For Export**: Include validation in generated code or pre-resolve all templates.

---

## 5. Workflow Loading and Management

### Storage Format

```json
{
  "name": "fix-issue",
  "description": "Fixes GitHub issues",
  "ir": {
    "ir_version": "0.1.0",
    "nodes": [...],
    "edges": [...]
  },
  "created_at": "2025-01-29T10:00:00+00:00",
  "updated_at": "2025-01-29T10:00:00+00:00",
  "version": "1.0.0",
  "rich_metadata": {
    "execution_count": 5,
    "last_execution_success": true
  }
}
```

**Location**: `~/.pflow/workflows/*.json`

### Three Loading Methods

1. **By name**: `WorkflowManager.load_ir("fix-issue")`
2. **By path**: Load from file path
3. **By dict**: Use inline IR

### Nested Workflows

```json
{
  "id": "process",
  "type": "workflow",
  "params": {
    "workflow_name": "text-processor",  // or workflow_ref or workflow_ir
    "param_mapping": {"text": "${input}"},
    "output_mapping": {"result": "processed"},
    "storage_mode": "mapped"
  }
}
```

**Export Strategies**:
1. **Inline**: Expand nested workflow into parent code
2. **Function call**: Generate separate function for nested workflow
3. **Import**: Reference external Python module

**Recommendation**: Start with inlining (simpler), add function extraction later.

---

## 6. Security and Secrets Handling

### Current Secret Management

**Storage**: `~/.pflow/settings.json`
```json
{
  "env": {
    "OPENAI_API_KEY": "sk-...",
    "ANTHROPIC_API_KEY": "sk-ant-..."
  }
}
```

**Sensitive Keywords** (19 total):
- password, token, api_key, secret, credential, authorization, etc.

**Masking Layers**:
1. Settings display: First 3 chars + `***`
2. Rerun commands: `<REDACTED>`
3. MCP errors: Sanitized before LLM

### Critical: Secrets NEVER in IR ✅

Workflows use templates: `"api_key": "${OPENAI_API_KEY}"`

Resolution: Settings.env → Template variables → Node params

### Export Strategy: Hybrid Approach

```python
def get_credential(key: str) -> str:
    """Load credential from environment or pflow settings."""
    # 1. Check environment variable (production)
    value = os.environ.get(key)
    if value:
        return value

    # 2. Check ~/.pflow/settings.json (development)
    settings_path = Path.home() / ".pflow" / "settings.json"
    if settings_path.exists():
        with open(settings_path) as f:
            settings = json.load(f)
            value = settings.get("env", {}).get(key)
            if value:
                return value

    raise ValueError(f"Credential '{key}' not found in environment or pflow settings")

# Usage in generated code
api_key = get_credential("OPENAI_API_KEY")
```

**Benefits**:
- ✅ Works in development (pflow settings)
- ✅ Works in production (environment variables)
- ✅ Clear error messages
- ✅ Follows 12-factor app pattern
- ✅ No hardcoded secrets

### Security Header Template

```python
#!/usr/bin/env python3
"""
Generated by pflow v{version} from workflow: {workflow_name}

REQUIRED CREDENTIALS:
  - OPENAI_API_KEY: OpenAI API authentication
  - GITHUB_TOKEN: GitHub API authentication

Setup (choose one):
  # Option 1: Environment variables (recommended for production)
  export OPENAI_API_KEY="sk-..."
  export GITHUB_TOKEN="ghp_..."

  # Option 2: pflow settings (development)
  pflow settings set OPENAI_API_KEY "sk-..."
  pflow settings set GITHUB_TOKEN "ghp_..."

Run:
  python {filename}
"""
```

---

## 7. Existing Code Generation Patterns

### Formatter Pattern (CRITICAL)

**Golden Rule**: Formatters RETURN, never print

```python
# ✅ CORRECT
def format_result(...) -> str:
    return "\n".join(lines)

# ❌ WRONG - Breaks MCP
def format_result(...):
    click.echo("Result")
```

**Location**: `src/pflow/execution/formatters/`

**Key Formatters**:
- `success_formatter.py` - Dict output
- `error_formatter.py` - Error sanitization
- `node_output_formatter.py` - 3 modes (text/json/structure)
- `workflow_describe_formatter.py` - Workflow interface

### Context Builder Pattern

```python
# From planning/context_blocks.py
def build_block(...) -> dict:
    """Build structured text block."""
    lines = []
    lines.append("# Section")
    lines.append("")
    lines.append("Content")

    return {
        "type": "text",
        "text": "\n".join(lines),
        "cache_control": {"type": "ephemeral"}
    }
```

**Pattern**: Immutable block accumulation
- `blocks = blocks + [new]` ✅
- NOT `blocks.append(new)` ❌

### No Existing Export Commands

**Gap**: No existing export/generate/to-code functionality

**Closest**: `pflow workflow describe <name>` shows structure but doesn't export

---

## 8. Implementation Recommendations

### Architecture

```
Workflow IR
    ↓
Export System
    ├─ Parameter Resolver
    ├─ Node Code Generator
    │   ├─ Shell Node Template
    │   ├─ File Node Template
    │   ├─ LLM Node Template
    │   ├─ HTTP Node Template
    │   └─ MCP Node Template
    ├─ Flow Control Generator
    ├─ Credential Manager
    └─ Code Formatter
    ↓
Python Code (str)
```

### Three-Phase Implementation

**Phase 1: Stdlib-Only Nodes** (MVP)
- shell, file ops, git, github
- No external dependencies (except system tools)
- Simple subprocess calls

**Phase 2: Package Nodes**
- llm, http
- Generate requirements.txt
- Import statements

**Phase 3: Complex Nodes**
- MCP nodes
- Async/await
- Server configuration

### Code Structure Template

```python
#!/usr/bin/env python3
"""
Generated by pflow v{version}
Source: {workflow_name}
"""

import subprocess
from pathlib import Path
from typing import Any

# ============================================================================
# Credential Management
# ============================================================================

def get_credential(key: str) -> str:
    """Load credential from environment or pflow settings."""
    # [implementation]

# ============================================================================
# Shared Store
# ============================================================================

shared: dict[str, Any] = {
    # Initial parameters
    "param1": "value1",
}

# ============================================================================
# Node Functions
# ============================================================================

def node_1():
    """Node: node_1 - Description"""
    # prep
    param = shared.get("input")

    # exec
    result = subprocess.run([...])

    # post
    shared["node_1"] = {"output": result.stdout}
    return "default"

def node_2():
    """Node: node_2 - Description"""
    # ...

# ============================================================================
# Flow Control
# ============================================================================

def main():
    """Execute workflow."""
    # Node 1
    action_1 = node_1()

    # Node 2 (conditional)
    if action_1 == "error":
        error_handler()
    else:
        action_2 = node_2()

    # Return outputs
    return {
        "output1": shared["node_1"]["result"],
        "output2": shared["node_2"]["data"]
    }

if __name__ == "__main__":
    result = main()
    print(result)
```

### CLI Integration

```python
# In src/pflow/cli/commands/workflow.py

@workflow.command()
@click.argument("workflow_name")
@click.option("--output", "-o", help="Output file path")
@click.option("--format", type=click.Choice(["python", "typescript", "bash"]), default="python")
def export(workflow_name: str, output: Optional[str], format: str):
    """Export workflow to standalone code.

    Examples:
        pflow workflow export my-workflow
        pflow workflow export my-workflow -o script.py
    """
    from pflow.execution.formatters.export_formatter import export_workflow_to_code

    # Load workflow
    workflow_ir = workflow_manager.load_ir(workflow_name)

    # Export to code
    code = export_workflow_to_code(workflow_ir, format=format)

    # Write to file or stdout
    if output:
        Path(output).write_text(code)
        click.echo(f"Exported to {output}")
    else:
        click.echo(code)
```

---

## 9. Key Challenges and Solutions

### Challenge 1: Template Resolution

**Problem**: IR has `${variable}` that needs Python equivalents

**Solutions**:
1. **Pre-resolve**: Resolve all templates before export (requires all inputs known)
2. **Runtime resolution**: Include template resolver in generated code
3. **Hybrid**: Resolve simple templates, include resolver for complex ones

**Recommendation**: Hybrid approach
- Simple `${var}` → Direct variable access
- Complex `${node.a.b[0]}` → Include resolver function

### Challenge 2: MCP Nodes

**Problem**: MCP nodes require server configuration and async execution

**Solutions**:
1. **Skip**: Don't support MCP nodes in Phase 1
2. **Inline**: Generate MCP client code (complex, async)
3. **Proxy**: Generate code that calls `pflow` CLI as subprocess

**Recommendation**: Phase 3 feature, start with skip + warning

### Challenge 3: Nested Workflows

**Problem**: `workflow` nodes reference other workflows

**Solutions**:
1. **Inline**: Recursively expand into single file (code explosion)
2. **Functions**: Generate function per nested workflow (cleaner)
3. **Modules**: Generate separate .py files (complex imports)

**Recommendation**: Functions approach
- Generate `def nested_workflow_name(): ...`
- Call from parent workflow
- Detect circular dependencies (already done in WorkflowExecutor)

### Challenge 4: Binary Data

**Problem**: Some nodes output binary data (base64 encoded)

**Solution**: Include base64 encoding/decoding in generated code

```python
import base64

# Decode binary data
if shared["read_file"].get("encoding") == "base64":
    content = base64.b64decode(shared["read_file"]["content"])
```

### Challenge 5: Error Handling

**Problem**: Nodes don't have try/except (let exceptions bubble for PocketFlow retry)

**Solution**: Generated code needs try/except for standalone execution

```python
def node_1():
    try:
        # Node logic
        result = subprocess.run([...], check=True)
        shared["node_1"]["output"] = result.stdout
        return "default"
    except Exception as e:
        shared["node_1"]["error"] = str(e)
        return "error"
```

---

## 10. Testing Strategy

### Unit Tests

1. **Template resolution**: `test_template_to_python()`
2. **Node generation**: Test each node type's code template
3. **Flow control**: Test edge routing generation
4. **Credential loading**: Test hybrid approach

### Integration Tests

1. **Export + Execute**: Export workflow, run generated code, compare outputs
2. **Node types**: Test each node type (shell, file, llm, http)
3. **Error handling**: Workflows with error edges
4. **Nested workflows**: Multi-level nesting

### End-to-End Tests

1. **Real workflows**: Export saved workflows from ~/.pflow/workflows/
2. **Compare execution**: `pflow run` vs `python exported.py`
3. **Different environments**: Local, Docker, CI

### Test Workflow Examples

```json
// test_simple_shell.json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "echo", "type": "shell", "params": {"command": "echo hello"}}
  ]
}

// test_file_pipeline.json
{
  "ir_version": "0.1.0",
  "nodes": [
    {"id": "read", "type": "read-file", "params": {"file_path": "input.txt"}},
    {"id": "write", "type": "write-file", "params": {"file_path": "output.txt"}}
  ],
  "edges": [{"from": "read", "to": "write"}]
}

// test_template_resolution.json
{
  "ir_version": "0.1.0",
  "inputs": {"name": {"type": "string", "default": "World"}},
  "nodes": [
    {"id": "greet", "type": "shell", "params": {"command": "echo Hello ${name}"}}
  ]
}
```

---

## 11. Success Criteria

### Functional Requirements

- ✅ Export shell, file, git, github nodes (Phase 1)
- ✅ Generate valid Python 3.9+ code
- ✅ No hardcoded secrets (hybrid credential loading)
- ✅ Equivalent output to `pflow run`
- ✅ Zero pflow runtime dependency

### Non-Functional Requirements

- ✅ Readable code (comments, docstrings)
- ✅ Executable without modifications
- ✅ Single file output (no complex modules)
- ✅ Handles errors gracefully
- ✅ Under 500 lines for typical workflows

### Documentation

- ✅ CLI help text (`pflow workflow export --help`)
- ✅ Generated code includes usage comments
- ✅ Architecture docs in `architecture/features/`
- ✅ Examples in `examples/export/`

---

## 12. Files to Create/Modify

### New Files

1. `src/pflow/execution/formatters/export_formatter.py` - Core export logic
2. `src/pflow/execution/formatters/export_templates/` - Node code templates
   - `shell_template.py`
   - `file_template.py`
   - `git_template.py`
   - `github_template.py`
   - `llm_template.py` (Phase 2)
   - `http_template.py` (Phase 2)
3. `tests/test_execution/formatters/test_export_formatter.py` - Unit tests
4. `tests/test_integration/test_export_execution.py` - Integration tests
5. `examples/export/` - Example exported workflows
6. `architecture/features/workflow-export.md` - Feature documentation

### Modified Files

1. `src/pflow/cli/commands/workflow.py` - Add `export` command
2. `CLAUDE.md` - Update task status

---

## Summary

**Key Insights**:
1. **IR is well-structured** - Clean transformation to Python code
2. **Node patterns are consistent** - Single template per node type
3. **Template system is sophisticated** - Need careful handling of resolution
4. **Security is solid** - Hybrid credential approach maintains safety
5. **Existing patterns exist** - Follow formatter pattern for consistency

**Implementation Path**:
1. Create export formatter following existing patterns
2. Generate node code using templates (one per node type)
3. Handle flow control with if/else based on edges
4. Include hybrid credential loading
5. Add CLI command
6. Test thoroughly (unit + integration + E2E)

**MVP Scope** (Phase 1):
- Python export only
- Stdlib nodes only (shell, file, git, github)
- Single file output
- Readable, commented code
- No optimization, no caching

**Estimated Complexity**: Medium
- **Easier than expected**: Consistent node patterns, clear IR structure
- **Harder than expected**: Template resolution edge cases, nested workflows

The research provides a solid foundation for implementation. All necessary patterns, examples, and integration points are well-documented and understood.
