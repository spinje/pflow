# Task 76 Handover: Registry Execute Command

**Context window closed on**: 2025-10-03
**Conversation scope**: Task 71 completion + AGENT_INSTRUCTIONS.md improvements + Task 76 creation
**Next agent**: Read this carefully - it contains insights you can't get from code alone

---

## 🎯 The Genesis: Why This Task Exists

### The User's Question

During Task 71 completion, the user asked me directly:

> "Do you think it would help to be able to run a specific tool/mcp tool independently. for example pflow registry execute/run tool-id param1=value1 ..."

This wasn't a random idea. We had just spent 2+ hours improving AGENT_INSTRUCTIONS.md with 739 new lines focused on making agents autonomous workflow builders. The user saw the gap.

### The Analysis That Led Here

I analyzed three specific pain points agents face:

1. **Output Structure Discovery**: 2-5 minutes per investigation
   - Current: Build minimal workflow → execute with --trace → parse JSON → extract structure
   - Problem: Too much overhead just to see what a node returns

2. **Parameter Validation**: 5-10 minutes per mistake
   - Current: Build workflow → validate → execute → wrong format → rebuild
   - Problem: No way to test params before integration

3. **Credential Testing**: 10-15 minutes of debugging
   - Current: Build workflow → execute → auth fails → debug separately → rebuild
   - Problem: Can't isolate auth issues from workflow issues

**The insight**: Agents are building workflows just to test nodes. That's backwards.

**Time savings**: 50% reduction in workflow building iterations (from 3-4 to 1-2)

### The Decision Point

I proposed implementing this in Task 71. User said: **"lets wait and document it as a new task, task 76"**

This was wise. Task 71 was about discovery, Task 76 is about testing. Separate concerns.

---

## 🧩 Critical Context: Task 71 Just Finished

**You MUST understand what Task 71 did** because Task 76 completes it.

### What Task 71 Delivered

We added 6 commands/enhancements to enable agent workflow building:

1. `pflow workflow discover` - LLM-powered workflow search
2. `pflow workflow save` - Save to global library
3. `pflow registry discover` - LLM-powered node selection
4. `pflow registry describe` - Detailed node specs
5. `--validate-only` flag - Static validation
6. Enhanced error output - Rich context on failures

**Plus**: Massive documentation overhaul (739 lines added to AGENT_INSTRUCTIONS.md):
- Pre-Build Checklist (16 items agents must verify)
- Critical Constraints section (sequential execution, template rules)
- Input/Output validation rules (explicit field requirements)
- Node Parameter Philosophy (use defaults, don't over-specify)
- Context Efficiency section (token management)
- Template Decision Tree (visual flowchart for ${} usage)

### The Missing Link

The agent workflow loop was:

```
DISCOVER nodes → DESCRIBE nodes → ??? → BUILD workflow → VALIDATE → EXECUTE
```

The **???** is where agents currently **guess** at parameters and output structures.

Task 76 fills that gap:

```
DISCOVER → DESCRIBE → **TEST** → BUILD (with confidence) → VALIDATE → EXECUTE
```

**This is the natural completion of Task 71.**

---

## 🏗️ Architecture Insights You Must Know

### 1. Reuse Everything (Don't Rebuild)

**Critical Decision**: This task is 2-3 hours ONLY because we reuse existing code.

**What to reuse**:

| Component | Location | Why |
|-----------|----------|-----|
| Parameter parsing | `main.py:infer_type()` line ~1547 | Exact same logic as workflow execution |
| Node execution | `node.run(shared)` pattern | Proven, tested, handles all phases |
| Error handling | `main.py:_handle_workflow_error()` line ~1034 | Agent-friendly messages pattern |
| Output flattening | `template_validator.py:_flatten_output_structure()` line ~162 | Already extracts nested paths |

**Why reuse matters**:
- Consistency: Agents expect same parameter format everywhere
- Speed: Avoid reinventing working code
- Quality: These components are battle-tested

**Anti-pattern**: DON'T create new parameter parsing logic "because execute is simpler". Use the same code.

### 2. Minimal Context Pattern

**Key insight**: Nodes don't need full workflow context to execute.

**Minimal shared store**:
```python
shared = {
    "__execution__": {"completed_nodes": []},
    # ... parsed parameters go here
}
```

**What's NOT needed**:
- ❌ Workflow metadata (`workflow_name`, `workflow_ir`)
- ❌ Execution history (except `__execution__` for state)
- ❌ Other node outputs (single node execution)
- ❌ Repair context (`__modified_nodes__`)

**Why this works**: Nodes are designed to be self-contained. They prep → exec → post using only their params and shared store.

**Test this assumption**: During implementation, verify with various node types (simple, MCP, LLM). If something breaks, it's a node design issue, not your fault.

### 3. The Three Output Modes (Why Each Matters)

This isn't over-engineering. Each mode serves a distinct need:

**Text Mode (default)**:
```
✓ Node executed successfully

Outputs:
  content: "File contents..."
  file_size: 1234
```

**Use case**: Human testing, debugging, quick checks
**Format**: Pretty-printed, human-readable
**Audience**: Developers testing locally

**JSON Mode (`--output-format json`)**:
```json
{
  "success": true,
  "outputs": {"content": "...", "file_size": 1234},
  "execution_time_ms": 45
}
```

**Use case**: Programmatic consumption by agents
**Format**: Structured, parseable
**Audience**: AI agents building workflows

**Structure Mode (`--show-structure`)**:
```
Available template paths in 'result':
  ✓ ${node.result.messages[0].text} (string)
  ✓ ${node.result.messages[0].user} (string)
  ✓ ${node.result.has_more} (boolean)
```

**Use case**: Discovering `Any` type outputs (common with MCP)
**Format**: Flattened paths with types
**Audience**: Agents writing templates

**Why structure mode is critical**: Many MCP nodes return `result: Any`. Agents need to see the actual structure to write templates like `${fetch.result.messages[0].text}`. Without this, they're blind.

---

## 🔗 Integration Points (Where Code Connects)

### Integration 1: Registry CLI

**Location**: `src/pflow/cli/registry.py`

**Existing commands** (study these for patterns):
- `list_nodes()` - Line ~200
- `describe_nodes()` - Line ~747
- `discover_nodes()` - Line ~646

**Your command**:
```python
@registry.command(name="execute")
@click.argument("node_type")
@click.argument("params", nargs=-1)
@click.option("--output-format", type=click.Choice(["text", "json"]), default="text")
@click.option("--show-structure", is_flag=True)
@click.option("--timeout", type=int, default=60)
def execute_node(node_type: str, params: tuple[str, ...], ...) -> None:
    """Execute a single node with provided parameters."""
```

**Pattern to follow**: Look at `describe_nodes()` - it:
1. Loads registry
2. Validates node IDs with `_normalize_node_id()`
3. Shows helpful errors for unknown nodes
4. Displays formatted output

**Your command should feel similar** (validate → execute → display).

### Integration 2: Parameter Parsing

**Critical code**: `src/pflow/cli/main.py` lines ~1547-1600

```python
def infer_type(value: str) -> str | int | float | bool | list | dict:
    """Infer parameter type from string value."""
    # Boolean
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    # Integer
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    # Float
    if "." in value or "e" in value.lower():
        try:
            return float(value)
        except ValueError:
            pass
    # JSON (arrays/objects)
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    # Default: string
    return value
```

**You must reuse this exactly**. Agents expect consistency.

**How to use**:
```python
def _parse_execution_params(params: tuple[str, ...]) -> dict[str, Any]:
    """Parse key=value params into dict with type inference."""
    parsed = {}
    for param in params:
        if "=" not in param:
            raise ValueError(f"Invalid parameter format: {param}")
        key, value = param.split("=", 1)
        parsed[key] = infer_type(value)  # Reuse existing function
    return parsed
```

### Integration 3: Output Structure Flattening

**Critical code**: `src/pflow/runtime/template_validator.py` lines ~162-252

```python
def _flatten_output_structure(
    structure: dict[str, Any],
    prefix: str = "",
    depth: int = 0,
    max_depth: int = 5
) -> list[tuple[str, str]]:
    """Recursively flatten output structure into (path, type) tuples.

    Example:
      {"messages": [{"text": "hi"}]}
      → [("messages", "array"), ("messages[0].text", "string")]
    """
```

**You must reuse this** for `--show-structure` mode.

**How to use**:
```python
if show_structure:
    # Get node outputs from shared store
    node_output = shared.get(node_type, {})

    # Flatten structure
    paths = _flatten_output_structure(node_output, prefix=node_type)

    # Display
    click.echo("\nAvailable template paths:")
    for path, type_name in paths[:20]:  # Limit to 20
        click.echo(f"  ✓ ${{{path}}} ({type_name})")
```

**Why this matters**: This function already handles nested objects, arrays with [0] notation, depth limits. Don't rewrite it.

### Integration 4: Error Handling

**Critical pattern**: Agent-friendly error messages (from Task 71)

**Study**: `src/pflow/cli/main.py` lines ~1034-1124 (`_handle_workflow_error`)

**Key principles**:
1. ❌ NO stack traces for expected errors
2. ✅ Clear problem statement
3. ✅ Actionable fix suggestion
4. ✅ Examples when possible

**Example error messages you need**:

```python
# Unknown node
Error: Unknown node type: 'nonexistent-node'

Available nodes:
  - read-file
  - write-file
  - llm
  ... (first 20)

Use 'pflow registry list' to see all nodes.

# Missing param
Error: Missing required parameter: 'file_path'

Node schema:
  file_path (string, required): Path to the file to read
  encoding (string, optional): File encoding

Example:
  pflow registry execute read-file file_path=/path/to/file.txt

# Execution error
❌ Node execution failed

Node: read-file
Error: File not found: /nonexistent/file.txt

Tip: Verify the file path exists and is accessible.
```

**Pattern**: Problem → Available options/Schema → Example/Tip

---

## ⚠️ Critical Implementation Details

### Detail 1: Node Execution Pattern

**How nodes actually run**:
```python
# This is what you need to do
node_class = registry.get_node_class(node_type)
node = node_class()

# Populate shared store with params
shared = {"__execution__": {"completed_nodes": []}}
shared.update(parsed_params)

# Execute (handles prep/exec/post automatically)
try:
    action = node.run(shared)  # Returns action string ("continue", "success", etc.)
except Exception as e:
    # Handle error
```

**Important**: Don't try to call `node.prep()`, `node.exec()`, `node.post()` separately. The `run()` method handles the entire lifecycle.

**Action results**: Nodes return action strings. For single-node execution, you only care about:
- Exception raised → error
- No exception → success (ignore action string)

### Detail 2: MCP Node Considerations

**MCP nodes have special requirements**:

1. **Server must be running**:
   ```python
   # Check if MCP server is running (implementation detail to figure out)
   # Error message should be specific:
   "Error: MCP server 'slack-composio' is not running.

   Start the server with:
     pflow mcp sync

   Or check server status:
     pflow mcp list"
   ```

2. **Credentials resolution**: MCP nodes use same credential flow as workflows
   - Environment variables (e.g., `SLACK_API_TOKEN`)
   - Config files in `~/.pflow/mcp/`
   - DON'T create new credential system

3. **Output format**: MCP nodes typically return `result: Any`
   - This is why `--show-structure` is critical
   - Test extensively with MCP nodes

### Detail 3: Parameter Edge Cases

**Test these scenarios**:

```bash
# Boolean
pflow registry execute node-type flag=true  # → True

# Array (single quotes to prevent shell expansion)
pflow registry execute node-type items='["a","b","c"]'  # → ["a","b","c"]

# Object
pflow registry execute node-type config='{"key":"value"}'  # → {"key": "value"}

# Number vs String
pflow registry execute node-type count=5  # → 5 (int)
pflow registry execute node-type count=5.0  # → 5.0 (float)

# String with special chars
pflow registry execute node-type text="hello world"  # → "hello world"
```

**Shell escaping matters**: Agents will use this command. They need to know how to escape values. Document examples.

### Detail 4: Output Size Considerations

**Potential issue**: Some nodes return HUGE outputs (e.g., large files, many API results).

**For MVP**: Display full output, no truncation.

**If needed later**: Add `--max-output-size` flag (but defer this - don't implement unless problem occurs).

**Why defer**: Premature optimization. Most testing uses small data. If agents hit this, Task 77 can add truncation.

---

## 📚 Documentation Updates (MANDATORY)

### Why Documentation is Critical

**Hard truth**: If agents don't know about this command, it has ZERO value.

Agents follow AGENT_INSTRUCTIONS.md systematically. They:
1. Read Pre-Build Checklist
2. Follow the 8-step development loop
3. Reference command guides

**If execute isn't documented, agents won't use it.** This entire task would be wasted effort.

### Update 1: Pre-Build Checklist

**Location**: `.pflow/instructions/AGENT_INSTRUCTIONS.md` line ~695

**Add section** (after "Node Discovery Complete"):

```markdown
### ✅ Critical Nodes Tested (Optional but Recommended)
- [ ] I've tested MCP nodes with `pflow registry execute` to verify params
- [ ] I've confirmed auth/credentials work for external services
- [ ] I've seen exact output structure for `Any` type nodes
- [ ] I'm confident about param formats (especially arrays/objects)

**Why test nodes first?**
- Catch parameter errors before building workflows
- See actual output structures (not guessing)
- Verify credentials work independently
- Build workflows with confidence (fewer iterations)

**When to test**:
- ✅ MCP nodes (unknown output structures)
- ✅ Nodes requiring authentication
- ✅ Complex parameter formats (arrays, objects)
- ❌ Simple nodes with known schemas (optional)
```

### Update 2: Testing & Debugging Section

**Location**: `.pflow/instructions/AGENT_INSTRUCTIONS.md` line ~900

**Add subsection** (after "Execute Workflow"):

```markdown
### Testing Individual Nodes (Before Building Workflows)

Before integrating a node into a workflow, test it in isolation:

```bash
pflow registry execute <node-type> param1=value1 param2=value2
```

**Why test nodes first?**
- Verify parameters work before building workflows
- See exact output structure (especially for `Any` types)
- Confirm authentication/credentials
- Catch format errors early

**Common Use Cases**:

**1. Test MCP node with unknown output structure**:
```bash
# See what Slack MCP returns
pflow registry execute mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY \
  channel=C123 limit=5 --show-structure

# Output shows:
# ✓ ${node.result.messages[0].text} (string)
# ✓ ${node.result.messages[0].user} (string)
# ✓ ${node.result.has_more} (boolean)
```

**2. Verify parameter format**:
```bash
# Test if array format works
pflow registry execute github-create-issue \
  repo=owner/repo \
  title="Test" \
  body="Body" \
  assignees='["user1","user2"]'  # Correct format confirmed
```

**3. Test authentication**:
```bash
# Verify GitHub credentials before building workflow
pflow registry execute github-get-issue repo=owner/repo issue=1

# If auth fails, fix credentials BEFORE building workflow
```

**Output Formats**:

**Text (default)** - Human-readable:
```
✓ Node executed successfully

Outputs:
  content: "File contents..."
  file_size: 1234
```

**JSON** - For programmatic use:
```bash
pflow registry execute read-file file_path=/tmp/test.txt --output-format json
```

**Structure** - See nested paths:
```bash
pflow registry execute mcp-slack-fetch channel=C123 --show-structure
```

**When to use each format**:
- Text: Quick testing, debugging
- JSON: Parsing output programmatically
- Structure: Discovering paths for templates
```

**These updates are NOT optional.** The task is incomplete without them.

---

## 🎯 Testing Strategy (Critical Scenarios)

### Test Scenario 1: Simple Node (Baseline)

```bash
# Create test file
echo "test content" > /tmp/test.txt

# Execute read-file node
pflow registry execute read-file file_path=/tmp/test.txt

# Expected output:
✓ Node executed successfully

Outputs:
  content: "test content\n"
  file_size: 13
  encoding: "utf-8"
```

**What this tests**: Basic execution, parameter parsing, output display

### Test Scenario 2: LLM Node (With Metadata)

```bash
pflow registry execute llm prompt="Say hello in one word"

# Expected output:
✓ Node executed successfully

Outputs:
  response: "Hello"
  llm_usage:
    model: "anthropic/claude-sonnet-3.5"
    input_tokens: 15
    output_tokens: 3
    ...
```

**What this tests**: Nodes with complex nested outputs, metadata handling

### Test Scenario 3: MCP Node with Structure Mode

```bash
pflow registry execute mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY \
  channel=C123 limit=1 --show-structure

# Expected output:
✓ Node executed successfully

Outputs:
  result: {...}

Available template paths in 'result':
  ✓ ${node.result.messages} (array)
  ✓ ${node.result.messages[0].text} (string)
  ✓ ${node.result.messages[0].user} (string)
  ✓ ${node.result.messages[0].ts} (string)
  ✓ ${node.result.has_more} (boolean)
```

**What this tests**: MCP node execution, structure flattening, array notation

### Test Scenario 4: Error Cases

```bash
# Unknown node
pflow registry execute nonexistent-node
# Should show available nodes

# Missing required param
pflow registry execute read-file
# Should show schema with example

# Wrong param format
pflow registry execute github-create-issue assignees="user1"  # String not array
# Should show execution error with tip
```

**What this tests**: All error message types are agent-friendly

### Test Scenario 5: JSON Output Mode

```bash
pflow registry execute shell command="echo test" --output-format json

# Expected: Valid JSON
{
  "success": true,
  "node_type": "shell",
  "outputs": {
    "stdout": "test\n",
    "stderr": "",
    "exit_code": 0
  },
  "execution_time_ms": 45
}
```

**What this tests**: JSON formatting, programmatic parsing

---

## 🚨 Potential Pitfalls (Things That Will Bite You)

### Pitfall 1: Over-Engineering the REPL

**Temptation**: "Let's make this interactive! With history! And auto-complete!"

**Reality**: That's a 10+ hour task (Task 77?). This is 2-3 hours.

**MVP Scope**:
- ✅ Execute one node
- ✅ Show output
- ✅ Three format modes
- ❌ NO interactive mode
- ❌ NO history
- ❌ NO auto-completion
- ❌ NO batch execution

**If user asks for REPL features**: Create Task 77.

### Pitfall 2: Creating New Parameter Parsing

**Temptation**: "Execute is simpler, I'll write cleaner parsing logic"

**Reality**: Agents expect consistency. Reuse `infer_type()` exactly.

**Why consistency matters**:
```bash
# In workflows
pflow workflow.json flag=true  # → True

# In execute (MUST match)
pflow registry execute node flag=true  # → True (same logic)
```

**If parsing differs, agents will be confused.**

### Pitfall 3: Not Testing with MCP Nodes

**Temptation**: "I'll just test with simple nodes (read-file, shell)"

**Reality**: MCP nodes are the PRIMARY use case for this command.

**Why MCP matters**:
- Most MCP nodes return `result: Any`
- Agents need `--show-structure` to discover paths
- MCP authentication issues are common
- MCP servers must be running

**Test matrix MUST include**:
- ✅ Simple node (read-file)
- ✅ LLM node (nested outputs)
- ✅ MCP node (Any type)
- ✅ MCP node with --show-structure
- ✅ MCP node with auth error

### Pitfall 4: Forgetting Documentation Updates

**Temptation**: "Code works, I'm done"

**Reality**: Task is incomplete without AGENT_INSTRUCTIONS.md updates.

**Why**: Agents follow instructions. No docs = no usage = wasted effort.

**Verification checklist**:
- [ ] Added to Pre-Build Checklist
- [ ] Added to Testing & Debugging section
- [ ] Included examples for common use cases
- [ ] Explained when to use each output format
- [ ] Showed parameter escaping (arrays, objects)

### Pitfall 5: Node Context Assumptions

**Temptation**: "Some nodes might need workflow context"

**Reality**: If a node can't run independently, it's a design issue.

**What to do if this happens**:
1. Test the node (it will probably work)
2. If it truly needs workflow context, document it
3. Consider if that node should even exist (design smell)

**Expected**: All nodes should be self-contained. This is by design.

---

## 🔍 Investigation TODOs (Things You'll Need to Figure Out)

### TODO 1: MCP Server Detection

**Question**: How to detect if MCP server is running?

**Where to look**:
- `src/pflow/mcp/` - MCP server management code
- `src/pflow/mcp/server_manager.py` - Likely has status checking
- `src/pflow/cli/mcp.py` - CLI commands for MCP management

**What you need**: A way to check if `mcp-slack-composio` server is running before executing `mcp-slack-composio-SLACK_FETCH_CONVERSATION_HISTORY`.

**Error message if not running**:
```
Error: MCP server 'slack-composio' is not running

Start server with:
  pflow mcp sync

Check status:
  pflow mcp list
```

### TODO 2: Registry Node Class Retrieval

**Question**: How to get node class from registry?

**Where to look**:
- `src/pflow/registry/registry.py` - Registry implementation
- Look for methods like `get_node()`, `load_node()`, `instantiate()`

**What you need**:
```python
registry = Registry()
node_class = registry.get_node_class("read-file")  # Returns class, not instance
node = node_class()  # Instantiate
```

**If method doesn't exist**: You may need to look at how workflow compilation does this in `src/pflow/runtime/compiler.py`.

### TODO 3: Output Truncation Threshold

**Question**: What's a reasonable max output size?

**Investigation**:
- Test with large files (read-file with 10MB file)
- Test with API responses (github-list-issues with limit=100)
- See what's actually too much

**Decision**:
- If nothing breaks: Don't add truncation (defer to future)
- If terminal overflows: Add `--max-output-size` flag (default: 10000 chars?)

**My recommendation**: Start without truncation. Add only if needed.

### TODO 4: Error Categories

**Question**: What error categories exist?

**Where to look**:
- `src/pflow/core/exceptions.py` - Exception definitions
- `src/pflow/execution/executor_service.py` - Error categorization

**What you need**: Map exception types to user-friendly messages:
- `FileNotFoundError` → "File not found: {path}"
- `PermissionError` → "Permission denied: {path}"
- `ValidationError` → "Invalid parameter: {param}"
- MCP errors → "MCP server error: {message}"

---

## 💡 The Bigger Picture (Why This Matters)

### Connection to Agent Autonomy

This task isn't just about a CLI command. It's about **enabling agent autonomy**.

**Current state**: Agents need humans to:
- Debug why workflows fail
- Figure out output structures
- Test parameter formats

**After Task 76**: Agents can:
- Test nodes independently
- Discover output structures
- Validate parameters before building
- **Build workflows autonomously**

**This is the completion of Task 71's vision.**

### The Learning Loop

Agents learn by testing:
1. Discover nodes with `registry discover`
2. Get specs with `registry describe`
3. **Test with real data with `registry execute`**
4. Build workflow with confidence
5. Validate structure
6. Execute successfully (fewer iterations)

**Step 3 is what you're building.** It's the missing link.

### Time Savings Projection

**Before Task 76**:
- Average workflow building: 15-20 minutes
- Iterations: 3-4 (guessing params, checking outputs)
- Debug time: 5-10 minutes per issue

**After Task 76**:
- Average workflow building: 8-10 minutes
- Iterations: 1-2 (confident from testing)
- Debug time: 2-3 minutes per issue

**Net savings**: ~50% reduction in workflow development time

**For context**: If an agent builds 10 workflows, that's ~70 minutes saved. That's significant.

---

## 📁 Critical Files to Read

**Read these BEFORE implementing** (in order):

1. **Parameter parsing** (MUST understand):
   - `src/pflow/cli/main.py` lines 1547-1600 (`infer_type`)

2. **Registry commands** (for patterns):
   - `src/pflow/cli/registry.py` entire file
   - Study `describe_nodes()` and `discover_nodes()`

3. **Error handling** (for message patterns):
   - `src/pflow/cli/main.py` lines 1034-1124 (`_handle_workflow_error`)

4. **Output structure** (for --show-structure):
   - `src/pflow/runtime/template_validator.py` lines 162-252 (`_flatten_output_structure`)

5. **Node execution** (to understand run pattern):
   - `src/pflow/runtime/compiler.py` - See how workflows compile and execute nodes
   - `pocketflow/__init__.py` - Node base class implementation

6. **MCP integration** (for MCP node testing):
   - `src/pflow/mcp/server_manager.py` - Server management
   - `src/pflow/cli/mcp.py` - MCP CLI commands

---

## 🎓 What I Learned (That You Can't Get From Code)

### Insight 1: Agents Think Differently

While building Task 71, I learned: **Agents need explicit validation rules, not examples.**

The AGENT_INSTRUCTIONS.md improvements (739 lines) focused on:
- Validation checklists (not tutorials)
- Decision trees (not narratives)
- Required fields (not suggestions)
- Common mistakes with fixes (not general advice)

**Apply this to error messages**: Show what's wrong, what's available, how to fix. No fluff.

### Insight 2: The Token Efficiency Mindset

Agents have limited context. Every token matters.

This influenced the execute command design:
- **Why --show-structure?** So agents don't waste context loading full outputs
- **Why JSON mode?** So agents can parse efficiently
- **Why text mode default?** For human debugging (less common)

**Think from agent perspective**: What's the minimal context they need to succeed?

### Insight 3: Documentation is Product

This took me time to realize: **If agents don't know about a feature, it doesn't exist.**

The execute command is only valuable if:
1. Documented in Pre-Build Checklist (agents check this)
2. Documented in Testing section (agents reference this)
3. Includes examples (agents copy-paste)

**Implementation without documentation is 50% done.**

### Insight 4: Reuse is Elegant Simplicity

Initially, I thought: "Maybe execute needs special parameter handling."

Then I realized: **Consistency is more important than optimization.**

Reusing `infer_type()` ensures agents get same behavior everywhere. That's worth more than "cleaner" code.

**When in doubt, reuse proven patterns.**

---

## 🚀 Final Wisdom: What to Remember

### The Core Truth

**Agents shouldn't need to build workflows to test nodes.**

That's backwards. They should test nodes, THEN build workflows with confidence.

This command enables that. It's simple. It's powerful. It completes Task 71.

### The Implementation Philosophy

1. **Reuse everything possible** (2-3 hours, not 8-10)
2. **Focus on the three output modes** (each serves distinct need)
3. **Make errors agent-friendly** (problem → options → example)
4. **Document thoroughly** (or it's wasted effort)
5. **Test with MCP nodes** (primary use case)

### The Success Criteria

This task is complete when:
- ✅ Command executes any node with params
- ✅ Three output modes work (text/json/structure)
- ✅ Error messages are helpful
- ✅ AGENT_INSTRUCTIONS.md updated (Pre-Build + Testing sections)
- ✅ Tests cover simple/LLM/MCP nodes
- ✅ Documentation includes examples

**If any checklist item is missing, the task is incomplete.**

### The Context You Have

You know:
- Why this task exists (user's question, my analysis)
- How it fits (completes Task 71)
- What to reuse (parameter parsing, error handling, output flattening)
- What to test (MCP nodes are critical)
- What to document (Pre-Build Checklist + Testing section)

**You have everything you need to succeed.**

---

## 🎯 Ready to Begin?

**DO NOT start implementing yet.**

First:
1. Read the task-76.md file
2. Read the critical files I listed
3. Understand the reuse strategy
4. Plan your implementation phases
5. THEN tell the user you're ready to begin

**Your response should be**: "I've read the handover and understand the context. Ready to begin Task 76 implementation."

Good luck! This is high-value, low-risk work. Keep it simple. Reuse proven patterns. Document thoroughly.

You've got this. 🚀
