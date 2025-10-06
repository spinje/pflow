# Task 76 Research Findings: Registry Execute Command

**Research completed**: 2025-01-06
**Purpose**: Comprehensive investigation for implementing `pflow registry execute` command

---

## Executive Summary

Task 76 aims to add a `pflow registry execute` command that allows testing individual nodes in isolation before integrating them into workflows. This research confirms the feature is **highly valuable**, **technically feasible**, and can be implemented in **2-3 hours** by reusing existing components.

**Key Finding**: No existing functionality provides single-node execution at the CLI level. This is a genuine gap that forces agents to build complete workflows just to test nodes.

---

## 1. Core Discovery: The Exploration Pattern

### The Problem Agents Face

Agents need to **explore and understand** tools through a discovery workflow before using them in production. For complex tools like Replicate's `CREATE_PREDICTION`, agents must:

1. **Discover available models** (`COLLECTIONS_LIST`)
2. **Understand model requirements** (`MODELS_GET`, `MODELS_README_GET`)
3. **Test with real data** (`CREATE_PREDICTION` with test inputs)
4. **Build production workflow** with confidence

Currently, each exploration step requires building a throwaway workflow, costing 2-5 minutes per investigation.

### How `registry execute` Solves This

```bash
# Rapid exploration without workflows
pflow registry execute mcp-replicate-COLLECTIONS_LIST --show-structure
pflow registry execute mcp-replicate-MODELS_GET model_name=sdxl --show-structure
pflow registry execute mcp-replicate-CREATE_PREDICTION input='{"prompt":"test"}' --show-structure
```

This transforms the workflow: **DISCOVER → DESCRIBE → TEST → BUILD** (with confidence)

---

## 2. Technical Architecture

### 2.1 Node Loading and Instantiation

**Key Function**: `import_node_class()` in `src/pflow/runtime/compiler.py:103-237`

```python
from pflow.runtime.compiler import import_node_class
from pflow.registry import Registry

registry = Registry()
node_class = import_node_class("read-file", registry)  # Returns class
node = node_class()  # Instantiate with NO parameters
```

**Critical Patterns**:
- Nodes are **always instantiated with no constructor parameters**
- Parameters are set **after instantiation** via `node.set_params(params)`
- MCP nodes require special parameters: `__mcp_server__` and `__mcp_tool__`

### 2.2 Minimal Execution Context

**Finding**: Nodes require minimal shared store - even empty `{}` works!

```python
# Absolute minimum
shared = {}

# With parameters (preferred)
shared = {
    "file_path": "/tmp/test.txt",
    "encoding": "utf-8"
}

# Execute
action = node.run(shared)  # Returns: "default", "error", etc.
```

**What's NOT needed**:
- Workflow metadata
- Execution tracking (`__execution__`)
- Node wrappers (template, namespace, instrumentation)
- Edge connections

### 2.3 Parameter Parsing

**Reuse Existing**: `infer_type()` in `src/pflow/cli/main.py:2005-2042`

```python
def infer_type(value: str) -> Any:
    """Type inference order:
    1. Boolean: "true"/"false" (case-insensitive)
    2. Integer: No decimal point
    3. Float: Has decimal or 'e' notation
    4. JSON: Starts with [ or {
    5. String: Everything else
    """
```

**Security Validation**: `is_valid_parameter_name()` in `src/pflow/core/validation_utils.py`
- Allows: hyphens, dots, underscores
- Forbids: `$|><&;` and shell special characters

### 2.4 Output Structure Flattening

**Reuse Existing**: `_flatten_output_structure()` in `src/pflow/runtime/template_validator.py:193-292`

```python
# Converts nested structures to template paths:
{"messages": [{"text": "hi"}]}
# Becomes:
[
    ("messages", "array"),
    ("messages[0].text", "string")
]
```

Perfect for `--show-structure` mode to help agents discover `Any` type outputs.

---

## 3. MCP Node Special Considerations

### 3.1 No Pre-Execution Validation

**Critical Finding**: Cannot check if MCP servers are "running" before execution:
- **Stdio servers**: Start fresh subprocess for each execution
- **HTTP servers**: Connection validated only at execution time
- **No persistent connections**: Each call is independent

### 3.2 MCP Parameter Injection

```python
if node_type.startswith("mcp-"):
    server, tool = _parse_mcp_node_type(node_type)
    params["__mcp_server__"] = server
    params["__mcp_tool__"] = tool
```

### 3.3 Error Handling

MCP nodes provide rich error context via `MCPError`:
```python
from pflow.core.user_errors import MCPError

# Structured error with title, explanation, suggestions
raise MCPError(
    title="MCP tools not available",
    explanation="The workflow tried to use MCP tools that aren't registered.",
    suggestions=[
        "Check your MCP servers: pflow mcp list",
        "Sync MCP tools: pflow mcp sync --all"
    ]
)
```

---

## 4. Command Interface Design

### 4.1 Command Syntax

```bash
pflow registry execute <node-type> [param1=value1] [param2=value2] ...
```

### 4.2 Options

```
--output-format FORMAT    Output format: text (default) or json
--show-structure         Display flattened output structure for Any types
--timeout SECONDS        Override default timeout (default: 60)
--verbose, -v           Show detailed execution information
```

### 4.3 Output Modes

#### Text Mode (Default)
```
✓ Node executed successfully

Outputs:
  content: "File contents here..."
  file_size: 1234
  encoding: "utf-8"

Execution time: 45ms
```

#### JSON Mode
```json
{
  "success": true,
  "node_type": "read-file",
  "outputs": {
    "content": "File contents here...",
    "file_size": 1234
  },
  "execution_time_ms": 45
}
```

#### Structure Mode (`--show-structure`)
```
Available template paths in 'result':
  ✓ ${node.result.messages} (array)
  ✓ ${node.result.messages[0].text} (string)
  ✓ ${node.result.messages[0].user} (string)
  ✓ ${node.result.has_more} (boolean)

Use these paths in workflow templates.
```

---

## 5. Implementation Blueprint

### Phase 1: Command Registration (30 min)

**File**: `src/pflow/cli/registry.py`

Add after existing commands:
```python
@registry.command(name="execute")
@click.argument("node_type")
@click.argument("params", nargs=-1)
@click.option("--output-format", type=click.Choice(["text", "json"]), default="text")
@click.option("--show-structure", is_flag=True)
@click.option("--timeout", type=int, default=60)
@click.option("--verbose", "-v", is_flag=True)
def execute_node(...):
    """Execute a single node with provided parameters."""
```

### Phase 2: Core Execution Logic (45 min)

```python
def _execute_single_node(node_type: str, params: dict[str, Any], registry: Registry):
    # 1. Import node class (reuse compiler.import_node_class)
    node_class = import_node_class(node_type, registry)

    # 2. Instantiate
    node = node_class()

    # 3. Handle MCP nodes
    if node_type.startswith("mcp-"):
        params = _inject_special_parameters(node_type, node_type, params, registry)

    # 4. Set parameters
    if params:
        node.set_params(params)

    # 5. Create minimal shared store
    shared = params.copy()

    # 6. Execute
    action = node.run(shared)

    return action, shared, node_type
```

### Phase 3: Output Formatting (30 min)

Implement three display functions:
- `_display_text_output()` - Human-readable
- `_display_json_output()` - Structured for agents
- `_display_structure_output()` - Template paths with types

### Phase 4: Error Handling (30 min)

```python
# Unknown node
if node_type not in registry.load():
    click.echo(f"Error: Unknown node type: '{node_type}'", err=True)
    _display_available_nodes(registry.load()[:20])
    sys.exit(1)

# Missing parameters
if missing_required:
    click.echo(f"Error: Missing required parameter: '{param}'", err=True)
    _display_node_schema(node_type, interface)
    sys.exit(1)

# Execution errors
try:
    action = node.run(shared)
except MCPError as e:
    click.echo(e.format_for_cli(verbose=False), err=True)
    sys.exit(1)
```

### Phase 5: Testing (45 min)

Create `tests/test_cli/test_registry_execute.py`:
- Command registration tests
- Parameter parsing tests (all types)
- Node execution tests (simple, LLM, MCP)
- Output formatting tests (3 modes)
- Error handling tests

---

## 6. Critical Decisions Needed

### Decision 1: Parameter Syntax

**Option A** ✅: `key=value` pairs (matches workflow execution)
```bash
pflow registry execute read-file file_path=/tmp/test.txt
```

**Option B**: JSON input
```bash
pflow registry execute read-file --json '{"file_path": "/tmp/test.txt"}'
```

**Recommendation**: Option A for consistency with existing workflow execution syntax.

### Decision 2: Output Truncation

**Option A** ✅: No truncation in MVP (defer to future if needed)
**Option B**: Add `--max-output` flag with default 10,000 chars

**Recommendation**: Option A - start simple, add if users report issues.

### Decision 3: Stdin Support

**Option A** ✅: MVP without stdin support (can add later)
**Option B**: Support piping data to shared store

**Recommendation**: Option A - not critical for initial agent use case.

---

## 7. Documentation Requirements

### MUST Update: `.pflow/instructions/AGENT_INSTRUCTIONS.md`

1. **Pre-Build Checklist** (line ~695):
   - Add "Critical Nodes Tested" section
   - Explain when to test nodes first

2. **Testing & Debugging** (line ~900):
   - Add "Testing Individual Nodes" section
   - Include examples for common scenarios

3. **Discovery Workflow Pattern**:
   - Document the explore → understand → test → build pattern
   - Show how to use for unfamiliar tools

### CLI Help Text

Update `pflow registry --help` to include execute command.

---

## 8. Risk Analysis

### Low Risk Factors
- ✅ Reuses proven components (parameter parsing, node loading)
- ✅ Simple execution model (no workflow complexity)
- ✅ Clear scope (single node, no edges, no flow)
- ✅ Existing error handling patterns

### Potential Issues
- ⚠️ MCP nodes may timeout (mitigated with --timeout flag)
- ⚠️ Large outputs could flood terminal (defer truncation to post-MVP)
- ⚠️ Complex nested parameters harder to specify (rare for testing)

---

## 9. Time Estimate

**Total: 2.5-3 hours**

| Phase | Time | Confidence |
|-------|------|------------|
| Command registration | 30 min | High |
| Core execution | 45 min | High |
| Output formatting | 30 min | High |
| Error handling | 30 min | High |
| Testing | 45 min | Medium |
| Documentation | 30 min | High |

---

## 10. Success Metrics

Task 76 is complete when:

✅ Command executes any node with parameters
✅ Three output modes work (text/json/structure)
✅ Error messages are agent-friendly
✅ MCP nodes execute successfully
✅ Tests cover simple/LLM/MCP nodes
✅ AGENT_INSTRUCTIONS.md updated with examples
✅ Agents can test nodes before building workflows

---

## Conclusion

This research confirms Task 76 is:
- **Necessary**: Fills a genuine gap in the agent workflow
- **Feasible**: Can reuse existing components extensively
- **Valuable**: Reduces workflow building time by ~50%
- **Low-risk**: Simple implementation with clear boundaries

The implementation should follow the "ruthless reuse" principle - leverage existing parameter parsing, node loading, and output formatting rather than creating new abstractions. This keeps the implementation time to 2-3 hours while ensuring consistency with existing patterns.

**Ready to proceed with implementation** once user approves the approach and resolves the three decision points.