# Task 46 Handoff Memo: Workflow Export to Zero-Dependency Code

## Context: What Led Here

The user wants to implement Task 46 (Workflow Export) which is listed as **post-MVP** in CLAUDE.md, but they explicitly requested to work on it now. This indicates it's a priority despite being marked for later.

**User's Key Questions** (verbatim):
1. "will this be easy to implement" - They're concerned about complexity
2. "will it work for typescript" - They're thinking about future extensibility

I answered: **Medium complexity** (~1 week for Phase 1), **TypeScript is achievable** (~2-3 days after Python).

**User's Approval**:
- They reviewed the before/after examples and approach
- They asked if there were remaining ambiguities
- I deployed 5 parallel search agents to resolve all ambiguities
- User triggered `/braindump` - they're satisfied with research, ready for implementation

---

## What You Inherit: Complete Research Package

You have **THREE comprehensive documents** in `.taskmaster/tasks/task_46/`:

1. **`starting-context/research-findings.md`** (66KB)
   - IR schema, runtime compilation, node implementations
   - Template system, workflow management, security
   - Existing code generation patterns
   - **Read this first** for foundational understanding

2. **`starting-context/before-after-examples.md`** (20KB)
   - 4 concrete workflow IR → Python code examples
   - Simple shell, file pipeline, error handling, LLM workflow
   - **User has seen and approved these examples**
   - Use these as your target output format

3. **`research/advanced-features-investigation.md`** (33KB)
   - Deep dive on 5 critical features (nested workflows, proxy mappings, namespacing, edge routing, stdin/stdout)
   - Code generation strategies for each
   - Edge cases, testing recommendations, file references
   - **Read this for implementation details**

**Status**: All critical ambiguities resolved. No blockers. Ready to implement.

---

## Critical Discoveries (Non-Obvious Knowledge)

### 1. Proxy Mappings Field is DEAD CODE ⚠️

**Discovery**: The `mappings` field exists in `ir_schema.py` but is **completely unused** in runtime.

```json
// This field exists in schema:
{
  "mappings": {
    "node_id": {
      "input_mappings": {...},
      "output_mappings": {...}
    }
  }
}
```

**Reality**:
- ❌ No code in `compiler.py` reads or processes it
- ❌ No wrapper applies mappings during execution
- ❌ No tests exercise it
- ✅ Automatic namespacing replaced it during Task 9

**Action**: **Ignore this field completely**. If present in IR, log a warning that it's not implemented. Do not waste time trying to handle it.

**Why This Matters**: The schema is NOT the source of truth - the runtime code is. Don't trust the schema blindly.

---

### 2. Nested Workflows are Runtime-Compiled (Cannot Inline)

**Discovery**: Child workflows are loaded and compiled **at runtime**, not at compile time.

**Execution Flow**:
```
Compile time:  Parent IR → WorkflowExecutor node (child NOT compiled)
Runtime:       WorkflowExecutor._run() → loads child.json → compiles → executes
```

**Why You Can't Inline**:
- `workflow_name` requires runtime WorkflowManager lookup (not available at compile time)
- `workflow_ref` with relative paths needs parent directory context
- Templates in `param_mapping` need runtime resolution
- Circular dependency detection requires execution stack

**Code Generation Strategy**: **Generate separate Python functions** for each workflow.

```python
def child_workflow(shared_input: dict) -> dict:
    # Child workflow nodes
    return {"result": shared["node"]["output"]}

def parent_workflow():
    # Parent nodes...
    child_output = child_workflow({"text": shared["data"]})
    shared["processed"] = child_output["result"]
```

**This is not a design choice - it's an architectural requirement.**

---

### 3. Namespacing Defaults to DISABLED

**Discovery**: Despite some test comments saying otherwise, `enable_namespacing` defaults to **false**.

**Two Modes**:

**Disabled (default)**:
```python
shared = {
    "response": "last write wins"  # Collision risk!
}
```

**Enabled**:
```python
shared = {
    "fetch": {"response": "data1"},
    "process": {"response": "data2"}  # No collision
}
```

**Special Keys** (always root, regardless of mode):
- `__execution__`, `__llm_calls__`, `__warnings__`, etc.
- Pattern: `__*__`

**Code Generation Strategy**:
- Default to **flat** code (simpler, matches runtime default)
- Add `--namespaced` flag for nested dict generation
- Always keep special keys at root level

---

### 4. Template Resolution Happens BEFORE Namespacing

**Execution Order**:
```
Node._run(shared)
  ↓
InstrumentedNodeWrapper (metrics)
  ↓
NamespacedNodeWrapper (creates proxy HERE)
  ↓
TemplateAwareNodeWrapper (resolves templates with FULL access)
  ↓
ActualNode (sees resolved values)
```

**Key Insight**: `TemplateResolver` operates on the **raw shared dict**, not the namespaced proxy. This means:
- Templates can access ANY namespace: `${fetch.response.data}`
- Cross-node references work via templates, not direct reads
- Template resolution must happen before you apply namespacing in generated code

**Code Generation Pattern**:
```python
# 1. Resolve templates (full access to all namespaces)
content = shared["fetch"]["response"]["data"]

# 2. Pass to node
process_node(content=content)

# 3. Node writes to its namespace
shared["process"]["result"] = output
```

---

### 5. Edge Routing Has NO Implicit Fallback

**Discovery**: If a node returns an action with no matching edge, the workflow **terminates** with a warning.

**Only Exception**: `None` auto-converts to `"default"`

**Examples**:
```python
# Node returns "retry" but no "retry" edge
action = node.run()  # Returns "retry"
# Result: Workflow terminates, logs warning

# Node returns None
action = node.run()  # Returns None
# Result: Converted to "default", follows default edge
```

**Code Generation Strategy**:
```python
action = fetch()

if action == "error":  # Explicit actions first
    error_handler()
elif action == "retry":
    retry_node()
else:  # Default edge OR unmatched actions
    if default_edge_exists:
        success_node()
    else:
        logger.warning(f"Action '{action}' has no matching edge")
```

**Alphabetize explicit actions** for deterministic code generation.

---

### 6. Stdin is a Reserved Key (Universal Access)

**Discovery**: `shared["stdin"]` is THE reserved key for stdin. **ALL nodes** can access it, not just the first node.

**Flow**:
```
CLI reads stdin → populate_shared_store() → shared["stdin"] = content
```

**Access Patterns**:
```python
# Method 1: Direct access
stdin = shared.get("stdin")

# Method 2: Template variable
# IR: {"params": {"stdin": "${stdin}"}}
# Resolves to: shared["stdin"]
```

**Three Data Types**:
- Text (<10MB): `shared["stdin"] = "text"`
- Binary (<10MB): `shared["stdin"] = b"bytes"`
- Large file (>10MB): `shared["stdin"] = "/tmp/pflow_stdin_..."`

**Code Generation**:
```python
import sys

def main():
    shared = {}

    # Read stdin if available
    if not sys.stdin.isatty():
        shared["stdin"] = sys.stdin.read()

    # Execute workflow
    execute_workflow(shared)
```

---

## Implementation Strategy (Based on User Feedback)

### Phase 1 Scope (MVP - ~1 week)

**Include**:
- Python export only (TypeScript later)
- Stdlib nodes: shell, file ops (read/write/copy/move/delete), git-*, github-*
- Flat code generation by default
- Template variable resolution
- Edge routing (if/elif/else)
- Nested workflows as functions
- Stdin/stdout handling
- Hybrid credential loading (env vars + pflow settings)

**Exclude** (Phase 2+):
- llm, http nodes (require pip packages)
- MCP nodes (async, server config - complex)
- Caching (not needed for zero-dependency export)
- Optimization passes
- TypeScript generation

**Deliverable**: `pflow workflow export <name>` command that generates executable Python scripts.

---

### Code Generation Approach (Concrete Decisions)

**1. Follow Formatter Pattern**

Location: `src/pflow/execution/formatters/export_formatter.py`

**Golden Rule**: Formatters RETURN, never print
```python
def export_workflow_to_python(workflow_ir: dict, ...) -> str:
    """Export workflow to Python code."""
    code = generate_code(workflow_ir)
    return code  # ✅ Return string, don't print
```

**Why**: CLI and MCP both need this. Printing breaks MCP integration.

---

**2. String Building (Not AST Generation)**

Use simple string concatenation for Phase 1:
```python
lines = []
lines.append("#!/usr/bin/env python3")
lines.append('"""Generated by pflow"""')
lines.append("")
lines.append("import subprocess")

# Generate node functions
for node in nodes:
    lines.extend(generate_node_function(node))

return "\n".join(lines)
```

**Why**:
- Simpler to implement and understand
- Easier to debug (just read the code)
- Sufficient for readable output
- Can refactor to AST later if needed

**Don't over-engineer** - the user asked "will this be easy to implement", suggesting they value simplicity.

---

**3. Node Code Templates**

Each node type needs a template:

**Shell Node**:
```python
def {node_id}():
    """Node: {node_id} - {purpose}"""
    try:
        result = subprocess.run(
            {command_args},
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            shared["{node_id}"]["stdout"] = result.stdout
            return "default"
        else:
            shared["{node_id}"]["error"] = result.stderr
            return "error"
    except Exception as e:
        shared["{node_id}"]["error"] = str(e)
        return "error"
```

**File Read Node**:
```python
def {node_id}():
    """Node: {node_id} - {purpose}"""
    try:
        file_path = Path({resolved_path}).expanduser().resolve()
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        shared["{node_id}"]["content"] = content
        return "default"
    except Exception as e:
        shared["{node_id}"]["error"] = str(e)
        return "error"
```

**Pattern**: prep → exec → post combined into single function with try/except.

---

**4. Template Variable Resolution**

**Simple templates** (entire param):
```python
# Template: "${input_file}"
# Becomes: shared.get("input_file")
```

**Nested paths**:
```python
# Template: "${fetch.response.items[0].name}"
# Becomes: shared["fetch"]["response"]["items"][0]["name"]
```

**Complex templates** (part of string):
```python
# Template: "Hello ${name}, count: ${count}"
# Becomes: f"Hello {shared['name']}, count: {shared['count']}"
```

**Implementation**:
```python
def resolve_template(template: str, context: dict) -> str:
    # Extract variables: ${var1}, ${var2}, ...
    variables = extract_template_vars(template)

    # Replace with f-string syntax
    for var in variables:
        # ${fetch.response} → {shared["fetch"]["response"]}
        path = var.split(".")
        access = build_access_code(path)
        template = template.replace(f"${{{var}}}", f"{{{access}}}")

    return template
```

---

**5. Credential Management (Hybrid Approach)**

**Include this helper in generated code**:
```python
def get_credential(key: str) -> str:
    """Load credential from environment or pflow settings."""
    import os
    import json
    from pathlib import Path

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

    raise ValueError(
        f"Credential '{key}' not found.\n"
        f"Set it using: export {key}=<value>\n"
        f"Or: pflow settings set {key} <value>"
    )
```

**Detect credentials**: Use `SENSITIVE_KEYS` set from `security_utils.py` (19 keywords).

**Security header**:
```python
"""
REQUIRED CREDENTIALS:
  - OPENAI_API_KEY: OpenAI API authentication
  - GITHUB_TOKEN: GitHub API access

Setup:
  export OPENAI_API_KEY="sk-..."
  # OR
  pflow settings set OPENAI_API_KEY "sk-..."
"""
```

---

## User Expectations (Explicit and Implicit)

### Explicit (from CLAUDE.md)

1. **"Show Before You Code"** principle
   - The user emphasized this in CLAUDE.md: "Show concrete before/after examples BEFORE implementing"
   - **I already did this** - user reviewed `before-after-examples.md`
   - You should continue this pattern for any design decisions

2. **Test-as-you-go strategy**
   - From CLAUDE.md: "Create tests AS YOU CODE, not as separate tasks"
   - Every new function needs test cases
   - Focus on quality over quantity
   - A task without tests is INCOMPLETE

3. **Run `make test` and `make check` before finalizing**
   - Ensure code quality and type safety
   - These must pass before considering task done

### Implicit (from conversation)

1. **Readable code over clever code**
   - User asked "will this be easy to implement" - they value simplicity
   - Don't over-engineer
   - Boring, obvious code is better than sophisticated abstractions

2. **Zero pflow dependencies**
   - This is the whole point of "zero-dependency export"
   - Generated code should use stdlib + pip packages only
   - No `import pflow` anywhere

3. **Type hints throughout**
   - Follow existing codebase patterns
   - Use modern Python type hints (list[str], dict[str, Any], etc.)

4. **Executable without modifications**
   - `python exported.py --input file.txt` should just work
   - No setup, no configuration, no additional files

5. **Compact code**
   - Target: ~80-200 lines for typical workflows
   - Don't generate bloat

---

## Traps and Gotchas (Learn from My Mistakes)

### 1. Don't Trust the IR Schema Blindly

**Trap**: Seeing `mappings` field in schema and thinking you need to implement it.

**Reality**: Runtime code is source of truth. If something isn't in `compiler.py` or used in tests, it's probably dead code.

**Action**: Always cross-reference schema with runtime implementation.

---

### 2. Don't Try to Inline Nested Workflows

**Trap**: Seeing `workflow_ir` parameter and thinking you can inline the workflow dict.

**Reality**: Even with inline dict, you need separate compilation because:
- Template resolution needs separate context
- Storage isolation requires separate shared dict
- Circular detection needs execution stack

**Action**: Always generate separate functions.

---

### 3. Don't Assume Namespacing is Enabled

**Trap**: Generating namespaced code `shared["node_id"]["key"]` by default.

**Reality**: `enable_namespacing` defaults to `false` in most workflows.

**Action**: Check the flag, generate flat by default, offer `--namespaced` option.

---

### 4. Don't Forget Special Keys Bypass Namespacing

**Trap**: Generating `shared["__execution__"]` inside a namespace.

**Reality**: Keys matching `__*__` pattern always go to root level.

**Action**: Detect pattern, always write to root:
```python
if key.startswith("__") and key.endswith("__"):
    shared[key] = value  # Root level
else:
    shared[node_id][key] = value  # Namespaced
```

---

### 5. Don't Generate Nodes Without Error Handling

**Trap**: Copying node code that doesn't have try/except (nodes rely on PocketFlow for error handling).

**Reality**: Standalone code needs its own error handling.

**Action**: Wrap every node function in try/except, return "error" action on failure.

---

### 6. Don't Hardcode Secrets

**Trap**: Resolving `${OPENAI_API_KEY}` to actual key value during export.

**Reality**: Generated code should load credentials at runtime.

**Action**: Use `get_credential()` helper function in generated code.

---

### 7. Don't Forget Binary Data Handling

**Trap**: Assuming all data is UTF-8 text.

**Reality**: Nodes handle binary data via base64 encoding.

**Action**: Include base64 import and encoding/decoding logic:
```python
import base64

if encoding == "base64":
    content = base64.b64decode(shared["node"]["content"])
```

---

### 8. Don't Use Wrong Template Syntax

**Trap**: Looking at old code with `$variable` syntax.

**Reality**: Template syntax changed in Task 35 to `${variable}` with curly braces.

**Action**: Only match `${...}` pattern, never `$...`.

---

## Files and Documentation (Critical References)

### Primary Implementation Files

**Core Runtime (understand these first)**:
- `src/pflow/runtime/compiler.py` - How IR becomes executable Flow
  - Lines 1116-1228: `compile_ir_to_flow()` - main compilation function
  - Lines 573-673: `_create_single_node()` - node instantiation with wrappers
  - Lines 745-809: `_wire_nodes()` - edge-based routing setup

**Nested Workflows**:
- `src/pflow/runtime/workflow_executor.py` - Complete WorkflowExecutor implementation
  - Lines 82-120: Three loading methods (name/path/inline)
  - Lines 260-281: Parameter mapping resolution
  - Lines 283-327: Storage isolation modes

**Namespacing**:
- `src/pflow/runtime/namespaced_store.py` - NamespacedSharedStore proxy
  - Lines 43-56: Write interception (`__setitem__`)
  - Lines 57-85: Read fallback (`__getitem__`)

**Template Resolution**:
- `src/pflow/runtime/template_resolver.py` - Template variable resolution
  - Lines 26-28: Regex pattern for `${variable}`
  - Lines 385-450: Resolution algorithm with type preservation

**Stdin/Stdout**:
- `src/pflow/core/shell_integration.py` - Stdin reading and population
  - Lines 145-198: `read_stdin_enhanced()` function
  - Lines 200-210: `populate_shared_store()` function

**Existing Formatters** (pattern to follow):
- `src/pflow/execution/formatters/success_formatter.py` - Return-based pattern
- `src/pflow/execution/formatters/error_formatter.py` - Sanitization example
- `src/pflow/execution/formatters/node_output_formatter.py` - Multiple modes

### Node Implementations (for code templates)

**Shell Node**:
- `src/pflow/nodes/shell/shell.py`
  - Lines 426-430: Stdin parameter handling
  - Lines 352-378: `_adapt_stdin_to_string()` - type conversion

**File Nodes**:
- `src/pflow/nodes/file/read_file.py` - File reading with encoding
- `src/pflow/nodes/file/write_file.py` - Atomic writes with temp file

**Git Nodes**:
- `src/pflow/nodes/git/` - Multiple git operations (status, commit, push, etc.)

**GitHub Nodes**:
- `src/pflow/nodes/github/` - GitHub API operations (uses `gh` CLI tool)

### Examples and Tests

**Workflow Examples**:
- `examples/core/minimal.json` - Simplest possible workflow
- `examples/core/error-handling.json` - Complex routing with retry
- `examples/nested/main-workflow.json` - Nested workflow example
- `examples/interfaces/run_text_analyzer_stdin.json` - Stdin example

**Tests to Reference**:
- `tests/test_runtime/test_workflow_executor/` - Nested workflow tests
- `tests/test_runtime/test_namespacing.py` - Namespacing behavior
- `tests/test_integration/` - End-to-end workflow tests

---

## Testing Strategy (Equivalence is Key)

### Unit Tests

Create: `tests/test_execution/formatters/test_export_formatter.py`

**Test each component**:
```python
def test_generate_shell_node():
    """Test shell node code generation."""
    node_ir = {"id": "test", "type": "shell", "params": {"command": "echo hello"}}
    code = generate_node_code(node_ir)
    assert "subprocess.run" in code
    assert '["echo", "hello"]' in code

def test_generate_edge_routing():
    """Test if/elif/else generation from edges."""
    edges = [
        {"from": "node", "to": "success", "action": "default"},
        {"from": "node", "to": "error", "action": "error"}
    ]
    code = generate_routing_code("node", edges)
    assert "if action == \"error\":" in code
    assert "else:" in code  # Default edge
```

### Integration Tests

Create: `tests/test_integration/test_workflow_export.py`

**Test equivalence**:
```python
def test_exported_code_matches_pflow_execution():
    """Ensure exported code produces same output as pflow."""
    workflow_ir = {...}

    # Run via pflow
    pflow_output = execute_workflow_via_pflow(workflow_ir)

    # Export and run standalone
    python_code = export_workflow_to_python(workflow_ir)
    exported_output = execute_python_code(python_code)

    # Compare
    assert pflow_output == exported_output
```

**Test all node types**:
```python
def test_export_shell_node():
    """Test shell node export and execution."""

def test_export_file_nodes():
    """Test read/write/copy/move/delete nodes."""

def test_export_git_nodes():
    """Test git operation nodes."""

def test_export_github_nodes():
    """Test github API nodes."""
```

### End-to-End Tests

**Test real workflows**:
```python
def test_export_real_workflow():
    """Export and execute actual saved workflow."""
    workflow_name = "fix-issue"  # Real workflow from ~/.pflow/workflows/

    # Export
    code = export_workflow(workflow_name)

    # Write to temp file
    temp_file = Path("/tmp/exported_workflow.py")
    temp_file.write_text(code)

    # Make executable
    temp_file.chmod(0o755)

    # Execute
    result = subprocess.run([sys.executable, str(temp_file)], ...)
    assert result.returncode == 0
```

### What to Test

- ✅ Template variable resolution (simple, nested, array access)
- ✅ Edge routing (linear, branch, loop, convergence)
- ✅ Nested workflows (all 3 loading methods)
- ✅ Namespacing (enabled/disabled modes)
- ✅ Stdin/stdout handling
- ✅ Error handling and recovery
- ✅ Binary data handling
- ✅ Credential loading (mock env vars and settings file)
- ✅ Large workflows (10+ nodes)
- ✅ Edge cases (circular refs, missing files, unmatched actions)

---

## Open Questions (Things I'm Not Sure About)

### 1. Should We Generate Type Hints in Exported Code?

**Trade-off**:
- Pro: Better code quality, matches pflow style
- Con: More verbose, harder to generate correctly

**My recommendation**: Yes, include type hints. User asked about TypeScript support, suggesting they value types.

**Decision needed**: Confirm with user or default to yes.

---

### 2. How to Handle MCP Nodes in Phase 1?

**Options**:
1. Skip completely (error if found)
2. Generate comment placeholder
3. Generate code that calls `pflow` CLI as subprocess (proxy approach)

**My recommendation**: Option 2 (comment placeholder with warning).

**Decision needed**: User hasn't specified.

---

### 3. Should Exported Code Include Metrics/Timing?

**Trade-off**:
- Pro: Useful for debugging, matches pflow execution
- Con: Adds complexity, not zero-dependency (depends on time module, but that's stdlib)

**My recommendation**: Skip for Phase 1. Keep it minimal.

**Decision needed**: User hasn't specified, but simplicity seems valued.

---

### 4. How to Handle Workflows with LLM Nodes in Phase 1?

LLM nodes require `pip install llm`. Should we:
1. Error and refuse to export
2. Generate code with TODO comment
3. Generate code with pip install instructions

**My recommendation**: Option 3 (generate code + requirements.txt + instructions).

**Decision needed**: This might be Phase 2, but it's close to boundary.

---

### 5. Should We Use Jinja2 for Templates or String Building?

**Trade-off**:
- Jinja2: More powerful, better for multi-language (TypeScript later)
- String: Simpler, no dependencies, easier to debug

**My recommendation**: String building for Phase 1, refactor to Jinja2 when adding TypeScript.

**Decision needed**: This affects architecture from day 1.

---

## Final Checklist (Before You Start Coding)

### Phase 1: Research Review
- [ ] Read all three documents:
  - [ ] `starting-context/research-findings.md` (foundational)
  - [ ] `starting-context/before-after-examples.md` (target output)
  - [ ] `research/advanced-features-investigation.md` (implementation details)
- [ ] Understand the 5 critical discoveries (proxy mappings, nested workflows, etc.)
- [ ] Review the before/after examples - these are your target
- [ ] Check the node implementations in `src/pflow/nodes/`

### Phase 2: Architecture Decisions
- [ ] Confirm: String building vs Jinja2 templates
- [ ] Confirm: Flat vs namespaced code by default
- [ ] Confirm: How to handle MCP nodes (skip/placeholder/error)
- [ ] Confirm: Include type hints in generated code?
- [ ] Confirm: Handle LLM nodes in Phase 1 or defer to Phase 2?

### Phase 3: Implementation Setup
- [ ] Create `src/pflow/execution/formatters/export_formatter.py`
- [ ] Follow formatter pattern (return-based, type-safe)
- [ ] Create test file: `tests/test_execution/formatters/test_export_formatter.py`
- [ ] Set up node code template functions (one per node type)

### Phase 4: Core Implementation
- [ ] IR parsing and validation
- [ ] Template variable resolution → Python code
- [ ] Node code generation (shell, file, git, github)
- [ ] Edge routing → if/elif/else generation
- [ ] Nested workflows → separate function generation
- [ ] Stdin/stdout handling
- [ ] Credential management (hybrid approach)

### Phase 5: CLI Integration
- [ ] Add `export` subcommand to `src/pflow/cli/commands/workflow.py`
- [ ] Accept workflow name, output file path
- [ ] Add `--namespaced` flag
- [ ] Add `--format` for future TypeScript support (default: python)

### Phase 6: Testing
- [ ] Write unit tests (code generation components)
- [ ] Write integration tests (pflow execution vs exported code)
- [ ] Write E2E tests (real workflows from examples/)
- [ ] Test equivalence for all node types
- [ ] Test edge cases (circular refs, missing files, etc.)

### Phase 7: Quality Gates
- [ ] Run `make test` - all tests pass
- [ ] Run `make check` - linting and type checking pass
- [ ] Manually test exported code execution
- [ ] Verify zero pflow dependencies in generated code
- [ ] Verify generated code is readable and well-commented

### Phase 8: Documentation
- [ ] Update `architecture/features/` with workflow-export.md
- [ ] Add examples to `examples/export/`
- [ ] Update CLAUDE.md task status
- [ ] CLI help text is clear and helpful

---

## Most Important Things to Remember

1. **Proxy mappings is dead code** - ignore it completely
2. **Nested workflows must be functions** - cannot inline (architectural constraint)
3. **Template resolution before namespacing** - affects code generation order
4. **Namespacing defaults to false** - generate flat by default
5. **No implicit fallback in routing** - only None → "default"
6. **Stdin is universal access** - all nodes can read `shared["stdin"]`
7. **Follow formatter pattern** - return strings, don't print
8. **Test equivalence** - exported code must match pflow execution
9. **Show before you code** - user values seeing output examples first
10. **Keep it simple** - user asked "will this be easy", value simplicity over sophistication

---

## What Success Looks Like

You'll know you're done when:

✅ `pflow workflow export simple-shell` generates valid Python code
✅ Generated code executes without errors: `python exported.py`
✅ Output matches `pflow run simple-shell.json`
✅ No `import pflow` anywhere in generated code
✅ Code is readable with comments and docstrings
✅ `make test` and `make check` both pass
✅ All Phase 1 node types supported (shell, file, git, github)
✅ Nested workflows generate as separate functions
✅ Template variables resolve correctly
✅ Edge routing generates correct if/elif/else
✅ Stdin/stdout handling works
✅ Credentials load via hybrid approach (env + settings)

---

## Ready to Implement

**DO NOT start implementing yet**. First:

1. Read all three research documents thoroughly
2. Review the before/after examples - these are your target
3. Understand the 5 critical discoveries
4. Make architecture decisions (string vs Jinja2, etc.)
5. Come back to this handoff and check you understand everything

**Then** start with the checklist above.

When you're ready to begin implementation, respond: **"I have read the handoff memo and all research documents. I understand the critical discoveries and am ready to begin implementation."**

Good luck! The research is solid, the path is clear, and the user is excited about this feature.
