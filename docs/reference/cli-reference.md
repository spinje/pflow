# CLI Reference

> **Navigation**: [Index](../index.md) → CLI Reference

## Overview

This document is the authoritative reference for pflow's command-line interface. It covers syntax, operators, flag resolution, shell integration, and composition patterns.

## Table of Contents

- [Basic Syntax](#basic-syntax)
- [The Arrow Operator](#the-arrow-operator)
- [Command Structure](#command-structure)
- [Flag Resolution](#flag-resolution)
- [Template Variables](#template-variables)
- [Shell Pipe Integration](#shell-pipe-integration)
- [Node Syntax](#node-syntax)
- [Command Examples](#command-examples)
- [Flow Composition Patterns](#flow-composition-patterns)
- [Advanced Usage](#advanced-usage)

## Basic Syntax

### Core Command Structure

```
pflow <node> [--flags] => <node> [--flags] => <node> [--flags]
```

- **`pflow`**: The CLI command
- **`<node>`**: Node identifier (e.g., `read-file`, `llm`, `github/get-issue`)
- **`[--flags]`**: Optional parameters for the node
- **`>>`**: Flow composition operator (chains nodes)

### Grammar Definition

```
flow      ::= node ( ">>" node )*
node      ::= node_name ( flag )*
node_name ::= ( namespace "/" )? name ( "@" version )?
flag      ::= "--" key ( "=" value )?
```

## The Arrow Operator

The `>>` operator is pflow's primary composition mechanism, inspired by Unix pipes but operating at a higher level:

- **Sequential execution**: Nodes execute left-to-right
- **Shared store passing**: Each node accesses the same shared store
- **Error propagation**: Failures halt the entire flow
- **Deterministic**: Same inputs always produce same outputs

### Key Differences from Shell Pipes (`|`)

| Feature | Shell Pipe (`\|`) | pflow (`=>`) |
|---------|------------------|--------------|
| Data passing | stdout → stdin | shared store |
| Data format | Text stream | Structured data |
| Error handling | Per-command | Flow-wide |
| Caching | None | Node-level |
| Traceability | Limited | Full provenance |

## Command Structure

### Basic Node Invocation

```bash
pflow read-file --path=input.txt
```

### Chained Flow

```bash
pflow read-file --path=input.txt => llm --prompt="Summarize this"
```

### With Natural Language Planning

```bash
pflow "analyze the Python files in src/ and find security issues"
```

## Flag Resolution

pflow uses a **"Type flags; engine decides"** philosophy:

### Flag Categories

1. **Node Parameters** (`--model`, `--temperature`)
   - Stored in node's `params` dictionary
   - Static throughout execution
   - Can have defaults in node implementation

2. **Shared Store Injection** (`--text`, `--url`)
   - Injected into shared store before execution
   - Available to all nodes in the flow
   - Dynamic data for the run

3. **System Flags** (`--verbose`, `--trace`, `--planner-timeout`)
   - Control execution behavior
   - Not passed to nodes
   - Apply to entire execution
   - Affect logging and diagnostics

### Resolution Algorithm

```python
for flag in cli_flags:
    if flag in SYSTEM_FLAGS:
        apply_system_behavior(flag)
    elif node_expects_in_shared_store(flag):
        shared[flag_key] = flag_value
    else:
        node.params[flag_key] = flag_value
```

### Examples

```bash
# Node parameter (static)
pflow llm --model=claude-sonnet-4-20250514 --temperature=0.7

# Shared store injection (dynamic)
pflow process --text="Hello world"

# Mixed usage
pflow read-file --path=input.txt --encoding=utf-8 => \
      llm --prompt="Analyze this" --model=claude-sonnet-4-20250514
```

## Template Variables

Template variables enable dynamic content resolution using `$variable` syntax:

### Basic Usage

```bash
pflow llm --prompt="Summarize this: $content"
```

### Resolution Order

1. Check shared store for key
2. Check environment variables
3. Error if not found

### Examples

```bash
# From shared store
pflow read-file --path=doc.txt => \
      llm --prompt="Summary of $content"

# From environment
export API_KEY=sk-123
pflow api-call --token=$API_KEY

# In complex prompts
pflow github-get-issue --issue=123 >> \
      llm --prompt="Fix this issue: $issue_title\n\n$issue_body"
```

## Shell Pipe Integration

pflow natively supports Unix shell pipes through the reserved `shared["stdin"]` key:

### Basic Piping

```bash
cat article.md | pflow summarize-text
```

### How It Works

1. Detect input from stdin (when not a TTY)
2. Place content in `shared["stdin"]`
3. Nodes check `stdin` as fallback for primary input
4. Content is hashed and cached like any input

### Advanced Examples

```bash
# Direct piping
kubectl logs my-pod | pflow "extract errors and summarize"

# Chaining with Unix tools
grep ERROR app.log | pflow llm --prompt="Explain these errors"

# Multi-stage pipeline
cat data.json | \
  jq '.items[]' | \
  pflow process-json => \
  write-file --path=output.txt
```

### Node Convention for Stdin

Nodes should check stdin as fallback:

```python
def prep(self, shared):
    # Primary input key first
    text = shared.get("text")

    # Fall back to stdin if available
    if not text and "stdin" in shared:
        text = shared["stdin"]

    if not text:
        raise ValueError("No input text found")
```

## Node Syntax

### Full Node Identifier

```
[namespace/]name[@version]
```

- **namespace**: Optional, defaults to `core/`
- **name**: Required node name
- **version**: Optional, defaults to latest

### Examples

```bash
# Core namespace (implicit)
pflow read-file              # → core/read-file@latest

# Explicit namespace
pflow github/get-issue       # → github/get-issue@latest

# With version
pflow llm@1.0.0             # → core/llm@1.0.0

# Full form
pflow github/create-pr@2.1.0
```

### Resolution Rules

1. No namespace → prepend `core/`
2. No version → use `latest`
3. Check registry for exact match
4. Error if not found

## Command Examples

### File Processing

```bash
# Read, process, write
pflow read-file --path=input.txt >> \
      llm --prompt="Format as JSON" >> \
      write-file --path=output.json
```

### API Integration

```bash
# GitHub workflow
pflow github-get-issue --issue=123 >> \
      llm --prompt="Generate fix for: $issue_body" >> \
      github-create-pr --title="Fix: $issue_title"
```

### Multi-Stage Processing

```bash
# Complex analysis pipeline
pflow read-file --path=logs.txt => \
      llm --prompt="Extract errors" >> \
      llm --prompt="Group by category" >> \
      llm --prompt="Generate report" >> \
      write-file --path=report.md
```

### Natural Language Flows

```bash
# Let planner create the flow
pflow "analyze security vulnerabilities in src/"

# With piped input
git diff | pflow "explain these changes"
```

## Flow Composition Patterns

### Sequential Processing

```bash
pflow A => B => C
# A completes → B runs → C runs
```

### Conditional Paths (v2.0)

```bash
pflow validate => process -fail=> handle-error
# Future: action-based transitions
```

### Parallel Execution (v2.0)

```bash
pflow split => [process-a, process-b] => merge
# Future: parallel node execution
```

### Nested Flows

```bash
# Define reusable flow
pflow --save=analyze "read-file => llm => summarize"

# Use in larger flow
pflow analyze --path=doc.txt => publish
```

## Advanced Usage

### Debugging and Diagnostics

#### Verbose Mode (`--verbose`)

Enable detailed logging for troubleshooting:

```bash
pflow --verbose "analyze data.csv and create a report"
# Shows planner decisions, node execution, and data flow
```

#### Trace Mode (`--trace`)

Save detailed execution trace to JSON file:

```bash
pflow --trace "complex natural language task"
# Saves to ~/.pflow/debug/pflow-trace-TIMESTAMP.json
```

Trace files capture:
- All LLM prompts and responses
- Node execution times
- Planner path taken (reuse vs generate)
- Complete error information

#### Planner Timeout (`--planner-timeout`)

Set maximum time for planner execution (default: 60 seconds):

```bash
pflow --planner-timeout 120 "very complex multi-step workflow"
# Allows up to 2 minutes for planning
```

Automatic trace saving on timeout:
```
⏰ Operation exceeded 120s timeout
📝 Debug trace saved: ~/.pflow/debug/pflow-trace-20250114-104500.json
```

#### Combining Debug Flags

```bash
# Maximum debugging information
pflow --verbose --trace --planner-timeout 90 "debug this workflow"
```

See [Debugging Guide](../features/debugging.md) for detailed trace file analysis.

### Dry Run

```bash
pflow --dry-run expensive-flow => another-node
# Show what would execute without running
```

### Lock File Generation

```bash
pflow --save-lock=flow.lock "analyze codebase"
# Save reproducible flow definition
```

### Using Lock Files

```bash
pflow --from-lock=flow.lock
# Execute previously saved flow
```

## Best Practices

1. **Use Natural Keys**: Choose intuitive flag names that match shared store keys
2. **Explicit Over Implicit**: Specify versions for production flows
3. **Test Incrementally**: Build flows step-by-step, testing each stage
4. **Leverage Piping**: Use shell pipes for ad-hoc text processing
5. **Cache Wisely**: Understand which nodes are cacheable

## Common Patterns

### Text Processing Pipeline

```bash
cat document.pdf | \
  pflow pdf-to-text => \
  llm --prompt="Extract key points" >> \
  write-file --path=summary.md
```

### API Orchestration

```bash
pflow api/get-data --endpoint=/users => \
      transform --format=csv >> \
      upload --bucket=reports
```

### Development Workflow

```bash
pflow github-get-issue --issue=$1 >> \
      claude-code --prompt="Implement fix" >> \
      run-tests >> \
      github-create-pr
```

## Error Handling

### Command-Line Errors

```bash
# Missing required flag
$ pflow read-file
Error: read-file requires --path flag

# Invalid node
$ pflow unknown-node
Error: Node 'unknown-node' not found in registry
```

### Execution Errors

```bash
# Node failure stops flow
$ pflow read-file --path=missing.txt >> process
Error in read-file: File not found: missing.txt
Flow aborted.
```

### Debug Information

```bash
# Use --debug for detailed errors
$ pflow --debug failing-flow
[DEBUG] Starting flow execution
[DEBUG] Node 1/3: read-file
[ERROR] FileNotFoundError: missing.txt
[DEBUG] Stack trace: ...
```

## See Also

- [Node Reference](node-reference.md) - How to implement nodes that work with CLI
- [Execution Reference](execution-reference.md) - Runtime behavior of CLI flows
- [Shared Store](../core-concepts/shared-store.md) - How CLI flags interact with shared store
- [Registry](../core-concepts/registry.md) - Node discovery and versioning
- [Planner](../features/planner.md) - Natural language to CLI compilation
