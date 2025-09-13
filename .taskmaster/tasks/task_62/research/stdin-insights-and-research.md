# stdin Research and Insights for Task 62

## Executive Summary

This document captures all research, insights, and critical learnings about stdin handling in pflow workflows, gathered during the investigation for Task 62. The core insight: **stdin routing should be handled intelligently at the planner level, not by modifying individual nodes**.

## The Core Problem

### User Expectation vs System Reality

**What users expect:**
```bash
# This should "just work"
cat data.csv | pflow "analyze the data"
echo "Hello World" | pflow my-workflow.json file_path=???
```

**What actually happens:**
- Workflow expects `file_path` parameter
- stdin content goes to `shared["stdin"]`
- Node looking for `file_path` ignores stdin
- Workflow fails with "file not found"

### The Semantic Mismatch

There's a fundamental disconnect between:
- **User intent**: "Process this piped data"
- **Workflow expectation**: "Give me a file path"

This mismatch occurs because workflows are designed for file-based operations but users naturally want to pipe data through stdin in Unix-style pipelines.

## Current pflow stdin Handling

### How stdin Data Flows Today

1. **Detection** (`src/pflow/core/shell_integration.py`):
   - `detect_stdin()` checks if stdin is piped (not TTY)
   - `stdin_has_data()` uses `select.select()` to avoid hanging in non-TTY environments
   - This was fixed in our bugfix for Claude Code environment

2. **Reading** (`src/pflow/cli/main.py`):
   - `_read_stdin_data()` reads stdin content
   - Handles text, binary, and large files (temp file creation)

3. **Storage** in shared store:
   - Text: `shared["stdin"]`
   - Binary: `shared["stdin_binary"]`
   - Large files: `shared["stdin_path"]` (temp file path)

4. **Planner Awareness** (`src/pflow/planning/nodes.py`):
   ```python
   # Lines 505-510
   if shared.get("stdin"):
       stdin_info = {"type": "text", "preview": str(shared["stdin"])[:500]}
   elif shared.get("stdin_binary"):
       stdin_info = {"type": "binary", "size": str(len(shared["stdin_binary"]))}
   elif shared.get("stdin_path"):
       stdin_info = {"type": "file", "path": shared["stdin_path"]}
   ```

### Current Parameter Discovery

The parameter discovery prompt (`src/pflow/planning/prompts/parameter_discovery.md`) already:
- Receives `stdin_info` in its context
- Has rules about recognizing stdin (lines 124-126)
- Has examples showing empty parameters when data comes from stdin (line 100-101)

**BUT** it doesn't intelligently map stdin to workflow inputs when appropriate.

## Critical Insights

### Insight 1: Nodes Must Remain Atomic

**Why this matters:**
- Nodes shouldn't know or care where data comes from
- Coupling nodes to input methods breaks composability
- Each node should do ONE thing well

**What this means:**
- ❌ WRONG: Modify read-file node to handle "-" as stdin
- ✅ RIGHT: Let workflow/planner route data appropriately

### Insight 2: The Unix "-" Convention is a Shell Convention

The "-" meaning stdin is a **shell convention**, not a universal truth:
- Tools like `cat`, `tar`, `grep` understand "-"
- But this is their choice, not a requirement
- Forcing all nodes to understand "-" couples them to shell semantics

### Insight 3: Intelligence Belongs at the Planning Layer

The planner is the right place for adaptation because:
- It understands user intent from natural language
- It knows what data is available (stdin, files, etc.)
- It can make intelligent routing decisions
- It generates the workflow that connects everything

### Insight 4: Template Variables are the Solution

Using template variables like `${stdin}` provides:
- Clean separation of concerns
- Declarative workflows
- Data-source agnostic nodes
- Flexibility at resolution time

## Research from Simon Willison's LLM

### What LLM Does

```python
# Simple stdin detection
if not sys.stdin.isatty():
    stdin_prompt = sys.stdin.read()
```

### Key Differences

1. **LLM is designed for stdin input** - it's a core feature
2. **LLM would also hang in Claude Code** - same issue we fixed
3. **LLM doesn't need adaptation** - stdin is primary input method

### Lessons Learned

- Our `select.select()` approach is more robust for edge environments
- Simple `isatty()` check works in normal terminals
- The "-" convention is tool-specific, not universal

## Solution Architecture

### The Right Approach: Smart Parameter Discovery

When the planner sees:
- **stdin present**: `{"type": "text", "preview": "col1,col2..."}`
- **User says**: "analyze the data" (no file path specified)
- **Workflow expects**: `input_file` parameter

The parameter discovery should:
1. Recognize stdin is available
2. See user refers to "the data" generically
3. Map stdin to the input: `{"input_file": "${stdin}"}`

### Template Resolution Flow

```
User Input: "process the data"
     ↓
Parameter Discovery: {"data_file": "${stdin}"}
     ↓
Workflow Generation: params: {"content": "${data_file}"}
     ↓
Template Resolution: "${data_file}" → "${stdin}" → actual stdin content
     ↓
Node Execution: Receives content, doesn't know it came from stdin
```

### When to Route stdin

**DO route stdin when:**
- User says "the data", "the file", "the input" without path
- stdin contains data that matches expected input type
- No explicit file path is provided

**DON'T route stdin when:**
- User specifies explicit file path
- stdin type doesn't match expected input (e.g., binary stdin for text processor)
- Multiple inputs expected and stdin can only fill one

## Implementation Considerations

### Changes Needed

1. **Update parameter_discovery.md prompt:**
   - Add stdin routing logic
   - Include examples of stdin mapping
   - Clarify when to use stdin vs request file path

2. **No changes to:**
   - Individual nodes (remain atomic)
   - Template resolver (already handles `${stdin}`)
   - Workflow executor (already resolves templates)

### Example Prompt Addition

```markdown
### When stdin is present
- If the request mentions "the data", "the file", or "the input" without a specific path
- AND stdin contains appropriate data
- Map stdin to the parameter: `{"input_file": "${stdin}"}`
- This allows workflows to process piped data seamlessly

Examples:
- "Process the data" + stdin → `{"data_file": "${stdin}"}`
- "Analyze the CSV" + stdin → `{"csv_input": "${stdin}"}`
- "Transform the input" + stdin → `{"input_data": "${stdin}"}`
```

### Edge Cases to Handle

1. **Ambiguity**: "Process the data from file.txt" with stdin present
   - Solution: Prefer explicit path over stdin

2. **Type mismatch**: Binary stdin but workflow expects text
   - Solution: Parameter discovery should check stdin type

3. **Multiple inputs**: Workflow needs multiple files
   - Solution: stdin can only fill one parameter

## Future Possibilities

### Template Functions (Post-MVP)

```python
# Advanced template resolution
"${stdin_or_file:${file_path}}"  # Use stdin if available, else read file
"${stdin|json}"                   # Parse stdin as JSON
"${stdin|lines}"                  # Split stdin into array of lines
```

### Workflow-Level Adaptation (Post-MVP)

```json
{
  "inputs": {
    "data": {
      "type": "string",
      "source": ["stdin", "file"],  // Accept either
      "required": true
    }
  }
}
```

## Testing Strategy

### Prompt Testing Scenarios

1. **Basic stdin routing:**
   - Input: "analyze the data" + stdin present
   - Expected: `{"data": "${stdin}"}`

2. **Explicit path overrides:**
   - Input: "analyze data.csv" + stdin present
   - Expected: `{"data": "data.csv"}`

3. **No stdin available:**
   - Input: "analyze the data" + no stdin
   - Expected: `{"data": ""}` or request for file path

### Integration Testing

- Full planner flow with piped data
- Verify workflow generation uses stdin correctly
- Test with various node types expecting file inputs

## Key Principles to Remember

1. **Nodes stay atomic** - They process data, not worry about sources
2. **Planner adds intelligence** - It understands context and routes appropriately
3. **Templates provide flexibility** - `${stdin}` works anywhere
4. **User intent matters most** - System should adapt to user, not vice versa
5. **Explicit overrides implicit** - Named files beat stdin inference

## Common Pitfalls to Avoid

### ❌ Anti-Pattern: Node-Level stdin Handling
```python
# WRONG: Coupling node to input method
if file_path == "-":
    content = shared["stdin"]
```

### ❌ Anti-Pattern: Hardcoding stdin Checks
```python
# WRONG: Rigid stdin detection
if "stdin" in shared and not file_path:
    use_stdin()
```

### ✅ Correct Pattern: Parameter-Level Routing
```python
# RIGHT: Let parameters handle it
params = {"input": "${stdin}"}  # Planner decides
```

## Conclusion

The key insight is that **stdin routing is a parameter discovery problem, not a node implementation problem**. By making the planner's parameter discovery smart enough to map stdin to appropriate workflow inputs, we:

1. Keep nodes atomic and focused
2. Enable seamless stdin/file workflows
3. Maintain clean separation of concerns
4. Follow Unix philosophy of composability

This approach requires minimal changes (just prompt updates) while providing maximum flexibility for users who want to pipe data through pflow workflows.