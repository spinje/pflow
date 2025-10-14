# pflow Guide for AI Agents

## ⚠️ Critical Information

**The planner works but costs money** - Natural language commands trigger the AI planner which makes multiple LLM calls (~$0.02-0.05 per request). Only use it when you need to:
- Debug/test the planner itself
- Generate new workflows from natural language
- Inspect planner behavior via the automatically saved trace

**For regular workflow execution**: Use JSON workflows with --file to avoid LLM costs and get instant execution (<1 second vs 10-30 seconds)

## What Works Right Now

### ✅ Safe Commands

#### 1. Execute JSON Workflows from File
```bash
# This is the RECOMMENDED way to use pflow
uv run pflow --file workflow.json

# Execute saved workflows from ~/.pflow/workflows/
uv run pflow --file ~/.pflow/workflows/my-workflow.json

# With parameters
uv run pflow --file workflow.json param1=value1 param2=value2

# With specific output key
uv run pflow --file workflow.json --output-key result

# With JSON output format (shows ALL outputs)
uv run pflow --file workflow.json --output-format json
```

#### 2. Execute Saved Workflows by Name (⚠️ LIMITED)
```bash
# ONLY works if workflow has NO required inputs or you provide ALL required params
uv run pflow my-saved-workflow  # ⚠️ ERROR if workflow has required inputs!
uv run pflow my-saved-workflow input_file=data.txt  # ✅ Works if input_file is the only required param
```

**WARNING**: If the workflow has required inputs and you don't provide them, you'll get a validation error: "Workflow requires input 'X'"

#### 3. Check Registry/Available Nodes
```bash
# See what nodes are available
uv run python -c "from pflow.registry import Registry; r = Registry(); print(list(r.load().keys()))"
# Current nodes: copy-file, delete-file, git-checkout, git-commit, git-push, git-status, github-create-pr, github-get-issue, github-list-issues, llm, move-file, read-file, write-file
```

### ❌ Commands to AVOID

```bash
# DO NOT USE - These trigger the planner and will hang:
uv run pflow "analyze my data"  # Natural language - AVOID
uv run pflow "read file.txt"    # Natural language - AVOID
```

## Working Example Workflows

### 1. Safe Testing with Echo Node (RECOMMENDED FOR TESTING)
```json
{
  "ir_version": "0.1.0",
  "outputs": {
    "echo": {"type": "string", "description": "The echoed message"},
    "metadata": {"type": "object", "description": "Operation metadata"}
  },
  "nodes": [
    {
      "id": "test",
      "type": "echo",
      "params": {
        "prefix": "Test: ",
        "suffix": " [processed]",
        "uppercase": false
      }
    }
  ],
  "edges": []
}
```

**With Template Variables** (⭐ Test parameter resolution safely):
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "name": {"required": true, "type": "string"}
  },
  "nodes": [{
    "id": "test",
    "type": "echo",
    "params": {"message": "Hello ${name}", "uppercase": true}
  }],
  "edges": []
}
```
Run: `uv run pflow --file test.json name=World`
Output: `HELLO WORLD`

**Why use echo node for testing?**
- ✅ No side effects (safe for testing templates)
- ✅ Test template resolution without touching files/APIs
- ✅ Debug parameter passing instantly
- ✅ See exactly what values were resolved

### 2. File Operations
```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "writer",
      "type": "write-file",
      "params": {
        "file_path": "/tmp/test.txt",
        "content": "Hello, World!"
      }
    }
  ],
  "edges": []
}
```

### 3. Read File (with declared output)
```json
{
  "ir_version": "0.1.0",
  "outputs": {
    "content": {
      "description": "File contents",
      "type": "string",
      "source": "${reader.content}"
    }
  },
  "nodes": [
    {
      "id": "reader",
      "type": "read-file",
      "params": {
        "file_path": "/tmp/test.txt"
      }
    }
  ],
  "edges": []
}
```
**IMPORTANT**: The `source` field is REQUIRED for outputs when namespacing is enabled (default). It maps the namespaced node output (`reader.content`) to the root-level output (`content`)

### 4. Git Status Check
```json
{
  "ir_version": "0.1.0",
  "outputs": {
    "status": {
      "description": "Git status",
      "type": "object",
      "source": "${git.status}"
    }
  },
  "nodes": [
    {
      "id": "git",
      "type": "git-status",
      "params": {}
    }
  ]
}
```

### 5. LLM Node
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "topic": {
      "description": "Topic to write about",
      "type": "string",
      "required": true
    },
    "style": {
      "description": "Writing style",
      "type": "string",
      "required": false,
      "default": "professional"
    },
    "max_words": {
      "description": "Maximum word count",
      "type": "number",
      "required": false,
      "default": 50
    }
  },
  "outputs": {
    "response": {
      "description": "The LLM's response",
      "type": "string",
      "source": "${generate.response}"
    },
    "llm_usage": {
      "description": "Token usage information",
      "type": "object",
      "source": "${generate.llm_usage}"
    }
  },
  "nodes": [
    {
      "id": "generate",
      "type": "llm",
      "params": {
        "prompt": "Write a ${style} explanation about ${topic} in exactly ${max_words} words. Be concise and clear.",
        "model": "gpt-5-nano",
        "temperature": 0.7,
        "max_tokens": 200
      }
    }
  ],
  "edges": []
}
```

> Example how to run: `uv run pflow --file examples/test_llm_templates.json topic="neural networks" style="crazy and dyslectic" max_words=10`

> Note: Always use `gpt-5-nano` when testing to save money

## CLI Options Reference

### Essential Flags
```bash
--file <path>           # Execute workflow from JSON file (REQUIRED for now)
--verbose               # Show detailed execution info (useful for debugging!)
--output-format json    # Return ALL outputs as JSON (default: text)
--output-key <key>      # Return specific output key only
--no-trace              # Opt out of trace saving (traces enabled by default)
```

### Parameter Passing
```bash
# Pass workflow inputs as key=value pairs AFTER the command
uv run pflow --file workflow.json input1=value1 input2=42 flag=true
```

### Stdin Integration
```bash
# Pipe data into workflow (accessible as 'stdin' in shared store)
echo "Hello" | uv run pflow --file workflow.json
cat data.txt | uv run pflow --file workflow.json
```

## Output Handling

### Text Format (Default)
- Shows first matching output
- Clean for single values

### JSON Format (--output-format json)
- Shows ALL declared outputs
- Perfect for parsing with jq
- Example: `uv run pflow --file workflow.json --output-format json | jq .result`

## Error Handling

- **Malformed JSON**: Shows immediate syntax error with line/column
- **Missing nodes**: Shows "Unknown node type: X"
- **Execution errors**: Shows actual error, doesn't trigger planner

## Quick Verification

```bash
# Test that pflow is working (uses pre-installed test workflow)
uv run pflow --file ~/.pflow/workflows/test-suite.json
# Expected output: "Workflow executed successfully"

# Test with custom parameters
uv run pflow --file ~/.pflow/workflows/test-suite.json test_name="my-test"

# See verbose execution details
uv run pflow --verbose --file ~/.pflow/workflows/test-suite.json test_name="integration"
# Shows node execution details and parameter injection
```

## Using the Planner (Costs Money!)

```bash
# Generate a workflow from natural language (~$0.02-0.05, takes 10-30s)
uv run pflow "create a file called hello.txt with the content 'Hello World'"

# Planner runs always save a trace—inspect it to see what the planner is doing
uv run pflow "read the README file and summarize it"
# Trace saved to ~/.pflow/debug/workflow-trace-*.json (do not disable tracing during debugging)

# Simple workflow generation (takes 10-30s, costs ~$0.02-0.05)
uv run pflow "generate a random number between 1 and 100"

# Tip: After planner generates a workflow, copy it from debug traces for reuse
# Check ~/.pflow/debug/workflow-trace-*.json for the generated workflow JSON
```

**Remember**: Each planner invocation costs money and takes 10-30 seconds. Traces are saved automatically—use `--file` with JSON workflows for free, instant execution (and avoid `--no-trace` while debugging).

## Testing Workflows

### Best Practice: Use Echo Node for Testing
```bash
# 1. Create safe test workflow (no side effects!)
cat > /tmp/test.json << 'EOF'
{
  "ir_version": "0.1.0",
  "outputs": {
    "echo": {"type": "string", "source": "${test.echo}"},
    "metadata": {"type": "object", "source": "${test.metadata}"}
  },
  "nodes": [
    {"id": "test", "type": "echo", "params": {"prefix": "Test: "}}
  ]
}
EOF

# 2. Run it (fast, no side effects)
uv run pflow --file /tmp/test.json

# 3. Check output with JSON format
uv run pflow --file /tmp/test.json --output-format json
```

### Alternative: File-based Testing
```bash
# Only if you need actual file operations
cat > /tmp/test_file.json << 'EOF'
{
  "ir_version": "0.1.0",
  "outputs": {"result": {"type": "string", "source": "${w.result}"}},
  "nodes": [
    {"id": "w", "type": "write-file", "params": {"file_path": "/tmp/out.txt", "content": "test"}}
  ]
}
EOF

uv run pflow --file /tmp/test_file.json
```

## Key Points for AI Agents

1. **Always use JSON workflows** - Never use natural language commands
2. **Use --file flag** - Most reliable way to execute right now
3. **Provide ALL required inputs** - Missing inputs cause validation error ("Workflow requires input 'X'")
4. **Check node registry** - Only use nodes that exist
5. **Use --output-format json** - For structured output parsing
6. **Template variables work** - Use ${var} in params, pass via CLI (not hardcoded!)
7. **Outputs NEED source field** - Must use `"source": "${node_id.key}"` to map namespaced outputs

## Workflow Storage

- **Saved workflows location**: `~/.pflow/workflows/`
- **Debug traces location**: `~/.pflow/debug/` (saved automatically)
- **Pre-installed test workflow**: `~/.pflow/workflows/test-suite.json` (safe for testing)
- **Note**: Execute saved workflows with --file for instant execution without LLM costs

## Available Nodes Summary

- **Test**: echo (⭐ SAFE FOR TESTING - no side effects!)
- **File**: read-file, write-file, copy-file, move-file, delete-file
- **Git**: git-status, git-commit, git-push, git-checkout
- **GitHub**: github-list-issues, github-get-issue, github-create-pr
- **LLM**: llm

## When to Use vs Avoid the Planner

### Use the Planner When:
- Testing planner improvements or debugging (inspect the automatically saved trace)
- Generating new workflows from natural language descriptions
- You explicitly need to test planner behavior
- Cost is not a concern (research/development)

### Avoid the Planner When:
- Running known workflows (use --file instead)
- Cost matters (each request costs ~$0.02-0.05)
- Speed matters (planner takes 10-30s vs <1s for direct execution)
- You already have the JSON workflow

## Safe Debugging Approach

1. Write simple JSON workflows to test specific things
2. Use --output-format json to get structured data
3. Chain simple commands with shell pipes if needed
4. Save working workflows for reuse

Remember: **JSON workflows execute in <1 second. Natural language hangs for 60+ seconds.**
