# pflow Guide for AI Agents

## ⚠️ Critical Information

**DO NOT use natural language commands with pflow right now** - The planner is failing and causes 60+ second timeouts. Only use JSON workflows directly if not explicitly testing or debugging the planners llm calls.

**ALSO AVOID**: Running workflows with missing required inputs - this also triggers the planner and hangs!

## What Works Right Now

### ✅ Safe Commands

#### 1. Execute JSON Workflows from File
```bash
# This is the RECOMMENDED way to use pflow
uv run pflow --file workflow.json

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
      "type": "string"
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

### 4. Git Status Check
```json
{
  "ir_version": "0.1.0",
  "outputs": {
    "status": {
      "description": "Git status",
      "type": "object"
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
      "type": "string"
    },
    "llm_usage": {
      "description": "Token usage information",
      "type": "object"
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

## Testing Workflows

### Best Practice: Use Echo Node for Testing
```bash
# 1. Create safe test workflow (no side effects!)
cat > /tmp/test.json << 'EOF'
{
  "ir_version": "0.1.0",
  "outputs": {
    "echo": {"type": "string"},
    "metadata": {"type": "object"}
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
  "outputs": {"result": {"type": "string"}},
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
7. **Workflows can declare outputs** - CLI respects these declarations

## Available Nodes Summary

- **Test**: echo (⭐ SAFE FOR TESTING - no side effects!)
- **File**: read-file, write-file, copy-file, move-file, delete-file
- **Git**: git-status, git-commit, git-push, git-checkout
- **GitHub**: github-list-issues, github-get-issue, github-create-pr
- **LLM**: llm

## DO NOT ATTEMPT

- Natural language commands (planner is broken, that is why we need debugging capabilities)
- Complex multi-step debugging (build simple workflows instead)
- Workflow discovery by description (use exact names)

## Safe Debugging Approach

1. Write simple JSON workflows to test specific things
2. Use --output-format json to get structured data
3. Chain simple commands with shell pipes if needed
4. Save working workflows for reuse

Remember: **JSON workflows execute in <1 second. Natural language hangs for 60+ seconds.**