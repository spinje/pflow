# Task 76: Implement Registry Execute Command for Independent Node Testing

## Description
Add a `pflow registry execute` command that allows agents (and users) to test individual nodes in isolation before integrating them into workflows. This enables parameter validation, output structure discovery, and credential testing without building complete workflows, significantly reducing the workflow development iteration cycle.

## Status
done

## Completed
2025-10-06

## Dependencies
- Task 71: Extend CLI Commands with tools for agentic workflow building - The execute command complements the discovery commands by enabling testing after discovery
- Task 10: Create registry CLI - Execute command will be added to the existing registry command group

## Priority
high

## Details

### Problem Statement

Currently, agents building workflows face these pain points:

1. **Output Structure Discovery**: To see what an MCP node returns (especially `result: Any` types), agents must:
   - Create a minimal test workflow JSON
   - Execute the workflow with `--trace`
   - Parse the trace file to extract output structure
   - **Time cost**: 2-5 minutes per investigation

2. **Parameter Validation**: To verify parameter formats are correct:
   - Build complete workflow
   - Run validation
   - Execute workflow
   - Discover wrong parameter format
   - Rebuild workflow
   - **Iteration cost**: 5-10 minutes per mistake

3. **Credential Testing**: To verify MCP server authentication:
   - Build workflow
   - Execute
   - Auth fails
   - Debug credentials separately
   - Rebuild and retry
   - **Debugging cost**: 10-15 minutes

### Solution: `pflow registry execute`

A simple command that executes a single node with provided parameters and shows the output:

```bash
pflow registry execute <node-type> [param1=value1 param2=value2...]
```

**Key Benefits**:
- ✅ Immediate feedback (no workflow overhead)
- ✅ Test parameters before building workflows
- ✅ See exact output structure for `Any` types
- ✅ Verify credentials work before integration
- ✅ Reduce workflow building iterations

### Command Design

#### Basic Usage

```bash
# Execute a simple node
pflow registry execute read-file file_path=/tmp/test.txt

# Execute MCP node with multiple params
pflow registry execute mcp-slack-fetch channel=C123 limit=5

# Show JSON output
pflow registry execute github-get-issue repo=owner/repo issue=1 --output-format json

# Show structure for Any types
pflow registry execute mcp-slack-fetch channel=C123 --show-structure
```

#### Command Options

```
pflow registry execute <node-type> [params...]

Arguments:
  node-type              Node type from registry (e.g., read-file, mcp-slack-fetch)
  params                 Node parameters in key=value format

Options:
  --output-format FORMAT Output format: text (default) or json
  --show-structure       Display flattened output structure for Any types
  --timeout SECONDS      Override default timeout (default: 60)
  --verbose, -v          Show detailed execution information
```

#### Output Formats

**Text mode (default)**:
```
✓ Node executed successfully

Outputs:
  content: "File contents here..."
  file_size: 1234
  encoding: "utf-8"

Execution time: 45ms
```

**JSON mode**:
```json
{
  "success": true,
  "node_type": "read-file",
  "outputs": {
    "content": "File contents here...",
    "file_size": 1234,
    "encoding": "utf-8"
  },
  "execution_time_ms": 45
}
```

**Structure mode (for Any types)**:
```
✓ Node executed successfully

Outputs:
  result: {...}

Available template paths in 'result':
  ✓ ${node.result.messages} (array)
  ✓ ${node.result.messages[0].text} (string)
  ✓ ${node.result.messages[0].user} (string)
  ✓ ${node.result.messages[0].ts} (string)
  ✓ ${node.result.has_more} (boolean)

Use these paths in workflow templates.
```

### Implementation Details

#### 1. Command Location
- **File**: `src/pflow/cli/registry.py`
- **Add**: `@registry.command(name="execute")` after existing commands

#### 2. Execution Flow

```python
def execute_node(node_type: str, params: dict[str, str], options: Options) -> None:
    """Execute a single node with provided parameters."""

    # 1. Load registry and validate node exists
    registry = Registry()
    if node_type not in registry.load():
        click.echo(f"Error: Unknown node type: {node_type}", err=True)
        sys.exit(1)

    # 2. Parse parameters (reuse existing parameter parsing logic)
    parsed_params = _parse_execution_params(params)

    # 3. Create minimal execution context (no workflow)
    shared = {"__execution__": {"completed_nodes": []}}
    shared.update(parsed_params)

    # 4. Instantiate and execute node
    node_class = registry.get_node_class(node_type)
    node = node_class()

    try:
        result = node.run(shared)
        _display_execution_result(node_type, shared, result, options)
    except Exception as e:
        _display_execution_error(node_type, e, options)
        sys.exit(1)
```

#### 3. Parameter Parsing

Reuse existing parameter inference from `src/pflow/cli/main.py`:
- Boolean: `"true"`/`"false"` → `True`/`False`
- Integer: `"123"` → `123`
- Float: `"1.5"` → `1.5`
- JSON: `'["a","b"]'` → `["a", "b"]`
- String: everything else

#### 4. Output Display

**Text mode**: Show outputs in human-readable format
**JSON mode**: Structure output for programmatic use
**Structure mode**: Use existing template validator's `_flatten_output_structure()` logic

#### 5. Error Handling

- Node not found → Show available nodes
- Missing required params → Show node schema
- Execution error → Show error with context (like workflow execution)
- Auth error → Clear message about credentials

### Integration Points

#### With Existing Code

**Reuse**:
- Parameter parsing logic from `main.py:infer_type()`
- Node execution from workflow executor
- Error handling patterns from `_handle_workflow_error()`
- Output structure flattening from `template_validator.py:_flatten_output_structure()`

**New Code**:
- Command registration in `registry.py`
- Single-node execution wrapper (no workflow context)
- Output formatting for 3 modes (text/json/structure)

#### With Task 71 (Discovery Commands)

Complements the agent workflow:
1. `pflow registry discover` → Find relevant nodes
2. `pflow registry describe` → See node interface
3. **`pflow registry execute` → Test node with real data** ← NEW
4. Build workflow with confidence
5. `pflow --validate-only` → Validate structure
6. Execute workflow → Fewer iterations

### Agent Workflow Enhancement

**Before Task 76**:
```
DISCOVER → DESCRIBE → BUILD (guess params) → VALIDATE → EXECUTE → ❌ Fail → Rebuild

Iterations: 3-4 on average
Time: 15-20 minutes
```

**After Task 76**:
```
DISCOVER → DESCRIBE → EXECUTE (test params) → BUILD (confident) → VALIDATE → EXECUTE → ✅ Success

Iterations: 1-2 on average
Time: 8-10 minutes
```

**Time saved**: ~50% reduction in workflow building time

### Documentation Updates

#### 1. AGENT_INSTRUCTIONS.md

Add to "Pre-Build Checklist" section:

```markdown
### ✅ Critical Nodes Tested (Optional but Recommended)
- [ ] I've tested MCP nodes with `pflow registry execute` to verify params
- [ ] I've confirmed auth/credentials work for external services
- [ ] I've seen exact output structure for `Any` type nodes
- [ ] I'm confident about param formats (especially arrays/objects)
```

Add to "Testing & Debugging" section:

```markdown
### Testing Individual Nodes

Before building a workflow, test critical nodes in isolation:

```bash
pflow registry execute node-type param1=value1 param2=value2
```

**When to use**:
- ✅ MCP nodes with `result: Any` (see exact structure)
- ✅ Nodes requiring auth (verify credentials work)
- ✅ Complex parameters (test format is correct)
- ✅ External APIs (confirm endpoints are accessible)

**Examples**:
```bash
# Test Slack MCP node
pflow registry execute mcp-slack-fetch channel=C123 limit=5 --output-format json

# See output structure for Any types
pflow registry execute mcp-slack-fetch channel=C123 --show-structure

# Test GitHub auth
pflow registry execute github-get-issue repo=owner/repo issue=1
```
```

#### 2. CLI Documentation

Update registry command help text to include `execute` command.

### Key Design Decisions

#### 1. Minimal Context Execution

**Decision**: Execute nodes with minimal shared store context (no workflow metadata)

**Rationale**:
- Nodes should be self-contained
- Reduces complexity
- Matches single-node testing mental model

**Trade-off**: Some workflow-specific features won't work (but they shouldn't in isolation anyway)

#### 2. Reuse Existing Infrastructure

**Decision**: Reuse parameter parsing, node execution, and output formatting from existing code

**Rationale**:
- Reduces implementation time (2-3 hours instead of 8-10)
- Ensures consistency with workflow execution
- Leverages tested code

**Trade-off**: Coupled to existing implementations (but they're stable)

#### 3. Three Output Modes

**Decision**: Support text (default), json, and structure modes

**Rationale**:
- Text: Human-readable for interactive use
- JSON: Programmatic use by agents
- Structure: Discovery of Any types (common need)

**Trade-off**: More code, but high value for each mode

#### 4. Simple Command Interface

**Decision**: Use `key=value` parameter syntax (not JSON file)

**Rationale**:
- Matches workflow execution syntax
- Quick to type for testing
- No file creation overhead

**Trade-off**: Complex nested objects are harder (but rare for testing)

### MVP Scope

**In Scope**:
- ✅ Single node execution
- ✅ Parameter parsing (all types)
- ✅ Three output formats (text/json/structure)
- ✅ Error handling
- ✅ Basic documentation

**Out of Scope** (Future Enhancements):
- ❌ Interactive REPL mode (`pflow registry playground`)
- ❌ Parameter auto-completion
- ❌ Execution history
- ❌ Batch execution of multiple nodes
- ❌ Parameter file input (JSON file)

### Technical Considerations

1. **Node State**: Nodes may have state (prep/exec/post phases). Execute command runs full `node.run()` which handles this.

2. **MCP Servers**: Must be running for MCP nodes to execute. Error message should indicate if server is not running.

3. **Credentials**: Nodes may require environment variables or config files. Execution should use same credential resolution as workflows.

4. **Timeout**: Default 60s timeout, configurable via `--timeout` option.

5. **Output Size**: For large outputs, consider truncation or pagination (can be added later if needed).

## Test Strategy

### Unit Tests

**Location**: `tests/test_cli/test_registry_execute.py`

**Test Coverage**:

1. **Command Registration**:
   - Command appears in `pflow registry --help`
   - Accepts node type and parameters
   - Options are recognized

2. **Parameter Parsing**:
   - String values parsed correctly
   - Boolean values (`true`/`false`)
   - Numeric values (int, float)
   - JSON values (arrays, objects)
   - Type inference matches workflow execution

3. **Node Execution**:
   - Simple node execution (read-file, shell)
   - Node outputs captured correctly
   - Execution result returned

4. **Output Formatting**:
   - Text mode displays outputs correctly
   - JSON mode returns valid JSON
   - Structure mode shows flattened paths

5. **Error Handling**:
   - Unknown node type → helpful error
   - Missing required params → shows schema
   - Node execution error → clear message
   - MCP server not running → specific error

### Integration Tests

**Location**: `tests/test_integration/test_registry_execute_integration.py`

**Test Scenarios**:

1. **Read-File Node**:
   ```bash
   pflow registry execute read-file file_path=/tmp/test.txt
   ```
   - Verify file contents returned
   - Check output structure matches schema

2. **LLM Node**:
   ```bash
   pflow registry execute llm prompt="Say hello"
   ```
   - Verify LLM response returned
   - Check metadata (llm_usage) present

3. **Shell Node**:
   ```bash
   pflow registry execute shell command="echo test"
   ```
   - Verify stdout captured
   - Check exit_code present

4. **MCP Node** (if MCP server available):
   ```bash
   pflow registry execute mcp-filesystem-read_file path=/tmp/test.txt
   ```
   - Verify MCP call succeeds
   - Check result structure

5. **Structure Mode**:
   ```bash
   pflow registry execute llm prompt="test" --show-structure
   ```
   - Verify flattened paths displayed
   - Check types shown for each path

### Manual Testing Checklist

**Before marking complete**:
- [ ] Execute simple node (read-file) → outputs displayed
- [ ] Execute with wrong params → clear error message
- [ ] Execute with `--output-format json` → valid JSON returned
- [ ] Execute with `--show-structure` → paths displayed correctly
- [ ] Execute MCP node → works if server running
- [ ] Execute unknown node → helpful error with suggestions
- [ ] Test all parameter types (string, bool, int, float, json)

### Expected Error Messages

**Unknown node**:
```
Error: Unknown node type: 'nonexistent-node'

Available nodes:
  - read-file
  - write-file
  - llm
  - shell
  ... (show first 20)

Use 'pflow registry list' to see all nodes.
```

**Missing required param**:
```
Error: Missing required parameter: 'file_path'

Node schema:
  file_path (string, required): Path to the file to read
  encoding (string, optional): File encoding (default: utf-8)

Example:
  pflow registry execute read-file file_path=/path/to/file.txt
```

**Execution error**:
```
❌ Node execution failed

Node: read-file
Error: File not found: /nonexistent/file.txt

Tip: Verify the file path exists and is accessible.
```

### Performance Expectations

- Simple node execution: < 100ms
- MCP node execution: < 500ms (depends on MCP server)
- Output formatting: < 50ms
- Total command overhead: < 200ms

## Notes

- This command significantly reduces the feedback loop for agent workflow building
- Complements Task 71's discovery commands perfectly
- Reuses existing infrastructure (low risk, high value)
- Can be extended with interactive REPL mode in future (Task 77?)
- Should be documented prominently in AGENT_INSTRUCTIONS.md as recommended workflow step
