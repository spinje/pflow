# Task 46: Workflow Export to Zero-Dependency Code

## ID
46

## Title
Workflow Export to Zero-Dependency Code

## Description
Implement the ability to export pflow workflows to standalone, zero-dependency code in target languages (starting with Python). This feature transforms pflow from a runtime dependency into a pure development-time tool, allowing users to generate human-readable code that runs without pflow installed.

## Status
not started

## Dependencies
- Task 17: Implement Natural Language Planner System - The export feature needs workflows to already be compiled from natural language into IR format
- Task 24: Implement Workflow Manager - Need the workflow manager to load and resolve workflow IR before exporting
- Task 41: Implement Shell Node - Shell commands in workflows need to be exportable to subprocess calls
- Task 43: MCP Server support - MCP nodes need special handling during export to generate appropriate API calls

## Priority
medium

## Details
The Workflow Export feature will compile pflow workflows (represented as IR JSON) into standalone code files that execute without requiring pflow as a dependency. This addresses a critical concern about vendor lock-in and enables new use cases like embedding workflows in production applications, CI/CD pipelines, and serverless functions.

### Core Functionality
The exporter will:
- Parse the workflow IR (JSON) to understand nodes, edges, and data flow
- Generate equivalent code in the target language (Python first, then TypeScript, Bash)
- Transform the shared store pattern into appropriate variable passing
- Convert template variables (${var}) into language-specific string formatting
- Map each node type to its code generation template
- Handle error propagation and action-based routing

### Key Design Decisions (MVP Approach)
- Start with Python export only (covers 80% of use cases)
- Generate simple, readable code rather than optimized code
- Use standard library functions where possible (subprocess for shell, urllib for HTTP)
- Only import necessary SDKs (e.g., OpenAI SDK for LLM nodes)
- Generate a single file output (no complex module structure)
- Include comments indicating which pflow node generated each section

### Technical Implementation
The three-phase node lifecycle (prep→exec→post) will map to:
- `prep` → Variable extraction and validation code
- `exec` → Core business logic (API calls, file operations, etc.)
- `post` → Result handling and flow control decisions

Example transformation:
```python
# From IR node:
{"id": "fetch", "type": "shell", "params": {"command": "git log --oneline"}}

# To Python code:
def fetch_commits():
    """Node: fetch - Get recent commits"""
    result = subprocess.run(["git", "log", "--oneline"],
                          capture_output=True, text=True)
    if result.returncode == 0:
        shared["commits"] = result.stdout
        return "success"
    else:
        shared["error"] = result.stderr
        return "error"
```

### Node Type Mappings
- `shell` → subprocess.run()
- `read-file` → open() and read()
- `write-file` → open() and write() with parent dir creation
- `llm` → OpenAI/Anthropic SDK calls
- `mcp-*` nodes → Direct API calls or SDK usage
- `workflow` (nested) → Inline the nested workflow's code

### Export Command Interface
```bash
# Basic export
pflow export python my-workflow.py

# With options (future)
pflow export python my-workflow.py --optimize --include-logging

# Other languages (future)
pflow export typescript my-workflow.ts
pflow export bash my-workflow.sh
```

### Integration Points
- Workflow Manager: Load and validate workflow before export
- Template Resolver: Pre-resolve template variables or generate resolution code
- Node Registry: Map node types to code generation templates
- IR Schema: Parse and validate workflow structure

## Test Strategy
The export feature requires comprehensive testing to ensure generated code behaves identically to pflow execution:

### Unit Tests
- Test each node type's code generation (shell, file operations, LLM calls)
- Verify template variable resolution in generated code
- Test error handling code generation
- Validate import statement generation based on used nodes

### Integration Tests
- Export sample workflows and execute the generated code
- Compare output between pflow execution and exported code execution
- Test workflows with various node combinations
- Verify nested workflow export (workflows calling other workflows)
- Test workflows with conditional routing (action-based edges)

### End-to-End Tests
- Export complex real-world workflows (e.g., the TODOs → GitHub issue demo)
- Run exported code in different environments (local, Docker, Lambda simulation)
- Verify zero-dependency claim (no pflow imports in generated code)

### Key Test Scenarios
- Workflow with only shell commands → Pure subprocess code
- Workflow with LLM calls → Includes OpenAI import
- Workflow with error handling → Proper try/catch generation
- Workflow with template variables → Correct string interpolation
- Empty workflow → Minimal valid Python file
- Complex routing → Proper if/else control flow