# AI Agent Context for pflow Implementation

> **Purpose**: Provide AI agents with essential context to implement pflow tasks correctly and efficiently.
> **Audience**: AI coding agents working on pflow tasks.
> **Length**: Comprehensive but focused - every line serves a purpose.

## 1. The Vision: Why pflow Exists

### The Problem
Every time you ask an AI agent to perform a multi-step task, it re-reasons through the entire orchestration:
```
"I need to fetch the PR" → thinking → gh pr view
"Now analyze it" → thinking → grep/search
"Time to implement" → thinking → edit files
"Should I test?" → thinking → pytest
```

This costs 1000-2000 tokens and 30-90 seconds EVERY TIME for the SAME workflow.

### The Solution: "Plan Once, Run Forever"
```bash
# First time: AI figures out the workflow (30s, ~$0.10)
pflow "fix github issue 1234"
→ Generates: github-get-issue >> claude-code >> git-commit >> git-push

# Every time after: Instant execution (2s, free)
pflow fix-issue --issue=1234
```

### The 10x Improvement
- **Time**: 30-90s → 2-5s per execution
- **Cost**: $0.10-2.00 → ~$0.00 per execution
- **Reliability**: Variable approaches → Deterministic execution
- **Observability**: Chat logs → Step-by-step traces

pflow is a **workflow compiler** that transforms natural language into permanent, deterministic CLI commands.

## 2. Understanding the Architecture

### What pflow IS and ISN'T

**pflow IS**:
- A CLI tool that makes pocketflow workflows accessible
- A natural language → workflow compiler
- A way to save and reuse AI-generated workflows

**pflow is NOT**:
- An execution engine (that's pocketflow)
- A framework on top of a framework
- A replacement for pocketflow

### The Core Flow
```
User Input → CLI → Natural Language Planner → JSON IR → Compiler → pocketflow.Flow → Execution
```

Where:
- **CLI**: Collects the input string (everything after 'pflow')
- **Planner**: LLM interprets and generates workflow structure
- **JSON IR**: Intermediate representation of the workflow
- **Compiler**: Converts IR to executable pocketflow objects
- **pocketflow**: Handles all execution orchestration

### Key Architectural Insight
**pocketflow provides the execution engine**. Don't reimplement:
- Node lifecycle (prep → exec → post)
- Flow orchestration (>> operator)
- Retry mechanisms
- Action-based routing

pflow adds:
- CLI interface
- Natural language planning
- Node discovery
- Workflow persistence

## 3. Critical Implementation Facts

### Registry System
**FACT**: Registry stores metadata ONLY, not class references
```python
# Registry format
{
    "read-file": {
        "module": "pflow.nodes.file.read_file",  # Import path
        "class_name": "ReadFileNode",             # Class name
        "name": "read-file",                      # Node identifier
        "docstring": "...",                       # Full docstring (NOT "description")
        "file_path": "/path/to/file.py"
    }
}
```

**FACT**: Dynamic imports are required
```python
# Components using registry MUST do this:
module = importlib.import_module(registry[node_type]["module"])
NodeClass = getattr(module, registry[node_type]["class_name"])
```

**FACT**: Node naming convention
- Check `class.name` attribute first
- Fallback to kebab-case: `ReadFileNode` → `read-file`

### Virtual Nodes (MCP)
**FACT**: MCP tools use virtual registry entries
- Multiple registry entries can point to the same class (MCPNode)
- Virtual entries use `"file_path": "virtual://mcp"`
- Node names follow pattern: `mcp-{server}-{tool}`
- Example: `mcp-github-create-issue` → MCPNode class

### Node Implementation
**FACT**: All nodes inherit from pocketflow.BaseNode (NOT pocketflow.Node)
```python
from pocketflow import BaseNode  # or Node, which inherits from BaseNode

class MyNode(BaseNode):  # Direct inheritance, no wrapper
    name = "my-node"     # Explicit name attribute
```

**FACT**: Natural interface pattern
```python
# Nodes use intuitive shared store keys
shared["file_path"]  # NOT shared["data"] or shared["input"]
shared["content"]    # NOT shared["output"] or shared["result"]
shared["prompt"]     # NOT shared["text"] or shared["query"]
```

**FACT**: Fail fast principle
```python
def prep(self, shared):
    value = shared.get("required_key")
    if not value:
        raise ValueError("Missing required input: required_key")
```

### Natural Language Planner
**FACT**: MVP routes MOST commands through natural language
```bash
# These go to the LLM planner:
pflow "fix issue 1234"                           # Natural language
pflow read-file --path=data.txt => analyze      # Still natural language!
pflow github-get-issue --issue=1234 => llm      # Still natural language!

# Exception: MCP commands go directly to CLI handlers
pflow mcp add/list/sync/remove                   # Direct CLI execution, no planner
```
- Most commands go through planner in MVP. In v2.0 we will parse more CLI directly.

**FACT**: Template variables are planner-internal
- `${variable}` syntax is for planner use
- NOT resolved at runtime
- Planner ensures variables map to shared store values

**FACT**: The planner is THE core feature (Task 17)
- Enables "find or build" pattern
- Semantic workflow discovery
- Target ≥95% success rate

### Shared Store
**FACT**: Shared store is just a dict
```python
# No SharedStore class needed!
shared = {}  # That's it

# Validation is just functions
def validate_shared_store(shared: dict) -> bool:
    if "stdin" in shared and not isinstance(shared["stdin"], str):
        raise ValueError("stdin must be string")
    return True
```

**FACT**: Common shared store keys
- `stdin` - Input from shell pipes
- `file_path`, `content` - File operations
- `prompt`, `response` - LLM operations
- `issue_number`, `repo` - GitHub operations

### Compiler
**FACT**: IR compilation is object instantiation
```python
# Don't generate Python code strings!
# Do instantiate pocketflow objects:
def compile_ir_to_flow(ir_json, registry):
    # 1. Import node classes dynamically
    # 2. Instantiate nodes
    # 3. Connect with >> operator
    # 4. Return pocketflow.Flow
```

**FACT**: Compiler can inject metadata for virtual nodes
- For MCP nodes starting with "mcp-", compiler injects:
  - `__mcp_server__`: Server name from node type
  - `__mcp_tool__`: Tool name from node type
- Follows same pattern as `__registry__` injection for WorkflowExecutor
- Parameters are copied before modification to avoid side effects

### JSON Workflow Requirements
**FACT**: JSON workflows MUST include ir_version
- Required field: `"ir_version": "0.1.0"`
- Without this, CLI won't recognize it as a workflow
- Common mistake: putting name/description at root instead of in metadata
- Node outputs are namespaced under node IDs (e.g., `node-id.result`)
- Full schema documentation: [core-concepts/schemas.md](../core-concepts/schemas.md)
- Working examples: [examples/core/minimal.json](../../examples/core/minimal.json)
- User guide: [docs/json-workflows.md](../json-workflows.md)

## 4. Common Pitfalls & Solutions

### Pitfall: Trying to reimplement execution
**Wrong**:
```python
class ExecutionEngine:
    def run_nodes(self, nodes):
        # Don't do this!
```

**Right**:
```python
from pocketflow import Flow
flow = Flow(start=first_node)
result = flow.run(shared)
```

### Pitfall: Creating wrapper classes
**Wrong**:
```python
class PflowNode(pocketflow.BaseNode):
    pass  # Pointless wrapper
```

**Right**:
```python
from pocketflow import BaseNode
class ReadFileNode(BaseNode):
    # Direct inheritance
```

### Pitfall: Registry field confusion
**Wrong**:
```python
description = registry[node]["description"]  # Field doesn't exist!
```

**Right**:
```python
docstring = registry[node]["docstring"]      # Full docstring
# Parse first line for description if needed
```

### Pitfall: Storing class references
**Wrong**:
```python
registry[node_name] = NodeClass  # Don't store classes!
```

**Right**:
```python
registry[node_name] = {
    "module": "pflow.nodes.example",
    "class_name": "ExampleNode"
}
```

### Pitfall: Function signature mismatches
**Wrong**:
```python
def extract_metadata(node_cls):  # Wrong parameter name!
```

**Right**:
```python
def extract_metadata(node_class: Type[Node], include_source: bool = False):
    # Exact signature from handoff document
```

## 5. Essential Patterns

### Dynamic Import Pattern
```python
def import_node_class(node_type: str, registry: dict) -> Type[BaseNode]:
    """The pattern used everywhere for loading nodes."""
    try:
        module_path = registry[node_type]["module"]
        class_name = registry[node_type]["class_name"]

        module = importlib.import_module(module_path)
        NodeClass = getattr(module, class_name)

        if not issubclass(NodeClass, BaseNode):
            raise TypeError(f"{class_name} must inherit from BaseNode")

        return NodeClass
    except ImportError as e:
        logger.warning(f"Failed to import {module_path}: {e}")
        raise
    except AttributeError as e:
        logger.error(f"Class {class_name} not found in {module_path}")
        raise
```

### Node Implementation Pattern
```python
from pocketflow import BaseNode

class GitHubGetIssueNode(BaseNode):
    """Fetch GitHub issue details.

    Reads:
        - issue_number: Issue number to fetch
        - repo: Repository (org/name format)

    Writes:
        - issue: Complete issue data
        - issue_title: Issue title for templates
    """

    name = "github-get-issue"

    def prep(self, shared):
        # Read from params (template resolution handles shared store wiring)
        issue_number = self.params.get("issue_number")
        repo = self.params.get("repo")

        if not issue_number:
            raise ValueError("Missing required parameter: issue_number")
        if not repo:
            raise ValueError("Missing required parameter: repo")

        return {"issue_number": issue_number, "repo": repo}

    def exec(self, prep_res):
        # Pure business logic - no side effects
        # Don't catch exceptions!
        response = fetch_from_github(prep_res["issue_number"], prep_res["repo"])
        return response

    def post(self, shared, prep_res, exec_res):
        # Write results
        shared["issue"] = exec_res
        shared["issue_title"] = exec_res.get("title", "")
        return "default"
```

### Error Handling Pattern
```python
# Let exceptions bubble up for pocketflow to handle
def exec(self, prep_res):
    # DON'T DO THIS:
    # try:
    #     result = operation()
    # except Exception:
    #     return None

    # DO THIS:
    result = operation()  # Let it fail
    return result
```

### Test Pattern
```python
def test_github_get_issue():
    """Test pattern used across all nodes."""
    node = GitHubGetIssueNode()
    node.set_params({"github_token": "fake"})

    # Mock external calls
    with patch('requests.get') as mock_get:
        mock_get.return_value.json.return_value = {"title": "Test Issue"}

        shared = {"issue_number": "123", "repo": "org/repo"}
        node.run(shared)  # pocketflow handles lifecycle

        assert shared["issue"]["title"] == "Test Issue"
        assert shared["issue_title"] == "Test Issue"
```

## 6. Task Implementation Guide

### Reading Task Descriptions
Tasks often contain:
1. **What to build** - The actual requirement
2. **Implementation hints** - Specific approaches
3. **Warnings** - Common mistakes to avoid
4. **References** - Related documentation

Pay special attention to:
- "CRITICAL" or "IMPORTANT" markers
- Specific function signatures
- Output format examples
- Test strategy requirements

### Understanding Dependencies
```python
# If task depends on Task 5 (registry), you'll use:
registry_data = load_registry()  # From Task 5

# If task depends on Task 7 (metadata extractor), you'll use:
from pflow.metadata_extractor import extract_metadata  # From Task 7
```

### Verifying Assumptions
Common assumptions to verify:
1. **Line numbers** - Referenced lines may have changed
2. **Module locations** - Check if paths match task description
3. **Function signatures** - Handoff documents are contracts
4. **Data structures** - Verify formats between dependent tasks

### Common Task Patterns
- **"Create X with Y function"** - Implement exactly as specified
- **"Use Task N's output"** - Check what Task N actually produces
- **"Reference: doc.md"** - Read the referenced documentation
- **"Mock X for testing"** - Don't implement X, just mock it

## 7. Quick Reference

### Component Locations
```
src/pflow/
├── cli/main.py              # CLI entry point
├── cli/mcp.py              # MCP CLI commands
├── registry/scanner.py      # Node discovery (NOT planning/scanner.py!)
├── registry/metadata_extractor.py  # Metadata extraction
├── planning/                # Natural language planner
├── runtime/compiler.py      # IR → pocketflow.Flow
├── mcp/                     # MCP integration
│   ├── manager.py          # Server configuration
│   ├── discovery.py        # Tool discovery
│   └── registrar.py        # Registry updates
├── nodes/                   # Platform nodes
│   ├── file/               # File operations
│   ├── github/             # GitHub operations
│   ├── git/                # Git operations
│   ├── mcp/                # MCP node implementation
│   │   └── node.py        # Universal MCPNode
│   └── llm.py              # General LLM node
└── core/                    # Core utilities
    ├── ir_schema.py        # JSON IR schema
    └── proxy.py            # NodeAwareSharedStore
```

### Key Function Signatures
```python
# From various handoffs - these are contracts!
scan_for_nodes(directories: List[str]) -> Dict[str, NodeInfo]
extract_metadata(node_class: Type[Node], include_source: bool = False) -> Dict[str, Any]
compile_ir_to_flow(ir_json: dict, registry: dict) -> Flow
build_context(registry_metadata: Dict[str, Dict[str, Any]]) -> str
validate_shared_store(shared: dict) -> bool
```

### CLI Behavior in MVP
```bash
# Most things after 'pflow' go to planner
pflow <anything here is natural language>

# Exception: MCP subcommands are handled directly
pflow mcp add/list/sync/remove  # Direct CLI handler, no planner

# Future v2.0 will parse more CLI directly
# MVP sends most commands to LLM for interpretation
```

### Performance Targets
- Planning: ≤800ms
- Execution overhead: ≤2s vs raw Python
- Success rate: ≥95% for NL → workflow
- User approval: ≥90% for generated workflows

## 8. Before You Start Checklist

### Essential Reading
- [ ] Read your task description completely
- [ ] Check task dependencies
- [ ] Read any handoff documents mentioned
- [ ] Note specific warnings or "CRITICAL" sections

### Key Principles to Internalize
- [ ] pocketflow IS the execution engine
- [ ] Registry stores metadata only
- [ ] Shared store is just a dict
- [ ] Everything goes through natural language in MVP
- [ ] Function signatures in handoffs are contracts

### Verify Your Understanding
- [ ] Can you explain why we don't need an execution engine?
- [ ] Do you know how to dynamically import from registry?
- [ ] Can you write a basic node following the pattern?
- [ ] Do you understand what the planner does?

---

## Summary

You're implementing a **workflow compiler** that makes AI agents 10x more efficient. The architecture is intentionally simple:
- **CLI** collects input
- **Planner** generates workflows
- **Compiler** creates pocketflow objects
- **pocketflow** executes everything

Most implementation errors come from:
1. Trying to build what pocketflow already provides
2. Not understanding that registry stores metadata only
3. Creating unnecessary abstractions
4. Not following the patterns exactly

When in doubt:
- Check if pocketflow already does it
- Keep it simple
- Follow the patterns
- Read the handoff documents

Remember: You're building a CLI tool that compiles natural language into workflows. Everything else is just supporting that core mission.
