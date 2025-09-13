# Implementation Analysis for stdin Routing

## Overview

This document provides technical analysis of different implementation approaches considered for stdin routing in pflow workflows, including code examples and rationale for the chosen approach.

## Approaches Considered

### Approach 1: Node-Level Modification (REJECTED)

**Initial Attempt**: Modify read-file node to handle "-" as stdin

```python
# What we tried in read_file.py
def prep(self, shared: dict) -> tuple[str, str, str | None]:
    file_path = shared.get("file_path") or self.params.get("file_path")

    # Handle stdin convention: "-" means read from stdin
    if file_path == "-":
        if "stdin" in shared:
            stdin_content = shared["stdin"]
            return ("-stdin-", encoding, stdin_content)
        else:
            raise ValueError("file_path is '-' but no stdin content available")
```

**Why Rejected:**
- Violates atomic node principle
- Couples nodes to shell conventions
- Requires modifying every file-handling node
- Creates inconsistency across node types
- Not the "pflow way" - nodes should be simple and focused

### Approach 2: Template Function Enhancement (FUTURE)

**Concept**: Add smart template functions

```json
{
  "params": {
    "content": "${stdin_or_file:${file_path}}"
  }
}
```

**Implementation sketch:**
```python
def resolve_template(template: str, context: dict) -> str:
    if template.startswith("${stdin_or_file:"):
        param = extract_param(template)
        if context.get("stdin"):
            return context["stdin"]
        else:
            with open(context[param]) as f:
                return f.read()
```

**Why Deferred:**
- Requires template resolver changes
- More complex than needed for MVP
- Can be added later without breaking changes

### Approach 3: Workflow-Level Routing (POSSIBLE)

**Concept**: Use conditional edges for routing

```json
{
  "nodes": [
    {
      "id": "router",
      "type": "shell",
      "params": {
        "command": "[ -n '${stdin}' ] && echo 'stdin' || echo 'file'"
      }
    }
  ],
  "edges": [
    {"from": "router", "to": "process_stdin", "action": "stdin"},
    {"from": "router", "to": "read_file", "action": "file"}
  ]
}
```

**Why Not Preferred:**
- Makes workflows complex
- Requires users to understand routing
- Not transparent to workflow authors

### Approach 4: Parameter Discovery Intelligence (CHOSEN)

**Concept**: Make parameter discovery map stdin to inputs automatically

**Implementation**: Update parameter_discovery.md prompt

```markdown
### When stdin is present
- If the request mentions "the data" or "the file" without specifying a path
- AND stdin contains data
- Map stdin to the appropriate input parameter: `{"input_file": "${stdin}"}`
```

**Why Chosen:**
- Minimal code changes (just prompt update)
- Preserves node atomicity
- Transparent to users
- Works with existing template system
- Natural language understanding at the right layer

## Code Flow Analysis

### Current Flow (Without stdin Routing)

```
1. User: cat data.csv | pflow "analyze the data"
                ↓
2. CLI: Reads stdin → shared["stdin"] = "csv,content,here..."
                ↓
3. Parameter Discovery: {"data_file": ""} // No file mentioned!
                ↓
4. Workflow Generation:
   {
     "type": "read-file",
     "params": {"file_path": "${data_file}"}  // Empty!
   }
                ↓
5. Execution: FAILS - No file path provided
```

### New Flow (With stdin Routing)

```
1. User: cat data.csv | pflow "analyze the data"
                ↓
2. CLI: Reads stdin → shared["stdin"] = "csv,content,here..."
                ↓
3. Parameter Discovery: {"data_file": "${stdin}"} // SMART ROUTING!
                ↓
4. Workflow Generation:
   {
     "type": "llm",
     "params": {"prompt": "Analyze: ${data_file}"}
   }
                ↓
5. Template Resolution: ${data_file} → ${stdin} → "csv,content,here..."
                ↓
6. Execution: SUCCESS - LLM analyzes the CSV content
```

## Implementation Details

### Files to Modify

1. **src/pflow/planning/prompts/parameter_discovery.md**
   - Add stdin routing logic
   - Include examples
   - Update rules section

### Example Prompt Changes

```diff
## Important Rules

1. **Parameter names should be descriptive but generic**
   - Good: `output_file`, `repo_name`, `issue_count`
   - Bad: `pflow_repo_name`, `january_report`, `csv_filename`

2. **Never include the value in the parameter name**
   - Good: `{"backup_dir": "backups/2024-01-15/"}`
   - Bad: `{"2024_01_15_backup": "backups/2024-01-15/"}`

3. **Never extract prompts or instructions as parameters**
   - Extract: topics, lengths, styles as separate parameters
   - Don't extract: "Write a story about..." as a prompt parameter

4. **Keep values exactly as specified**
   - If user says "30", extract "30" (not "thirty")
   - If user says "Python files", extract "Python files" (not "*.py")

5. **When stdin is present**
   - Recognize that parameters may come from piped data
   - Extract only parameters explicitly mentioned in the request
+  - If user refers to "the data", "the file", "the input" without a path:
+    Map stdin to that parameter: `{"input_data": "${stdin}"}`

+## stdin Routing Examples
+
+### With stdin Present
+- "Process the data" + stdin
+  → `{"data": "${stdin}"}`
+
+- "Analyze the CSV" + stdin (CSV content)
+  → `{"csv_input": "${stdin}"}`
+
+- "Transform the input and save to output.json" + stdin
+  → `{"input_data": "${stdin}", "output_file": "output.json"}`
+
+### stdin Override Cases
+- "Process data.csv" + stdin present
+  → `{"data_file": "data.csv"}` (explicit path wins)
+
+- "Read from /tmp/data.txt" + stdin present
+  → `{"input_file": "/tmp/data.txt"}` (explicit path wins)
```

## Test Cases

### Unit Test: Parameter Discovery

```python
def test_parameter_discovery_routes_stdin():
    """Test that parameter discovery maps stdin to inputs."""

    # Setup
    user_input = "analyze the data and save results"
    stdin_info = {"type": "text", "preview": "col1,col2,col3..."}

    # Execute parameter discovery
    params = discover_parameters(user_input, stdin_info=stdin_info)

    # Assert
    assert params == {
        "data": "${stdin}",
        "output_file": "results"  # Inferred from "save results"
    }

def test_explicit_path_overrides_stdin():
    """Test that explicit paths override stdin routing."""

    # Setup
    user_input = "analyze data.csv"
    stdin_info = {"type": "text", "preview": "other,data"}

    # Execute
    params = discover_parameters(user_input, stdin_info=stdin_info)

    # Assert
    assert params == {"data_file": "data.csv"}
    # stdin is ignored when explicit path given
```

### Integration Test: Full Pipeline

```python
def test_stdin_workflow_execution():
    """Test complete flow from stdin to execution."""

    # Setup stdin
    stdin_data = "Name,Age\nAlice,30\nBob,25"

    # Natural language request
    request = "count the rows in the data"

    # Execute planner
    workflow = plan_workflow(request, stdin=stdin_data)

    # Verify parameter mapping
    assert "${stdin}" in str(workflow)

    # Execute workflow
    result = execute_workflow(workflow, stdin=stdin_data)

    # Verify result
    assert "3 rows" in result or "2 rows" in result  # Header handling varies
```

## Edge Cases and Handling

### Edge Case 1: Multiple Input Parameters

**Scenario**: Workflow needs multiple inputs but only stdin available

```python
# User: "merge the files"
# Workflow expects: file1, file2
# stdin contains: single file content
```

**Handling**: Parameter discovery should recognize insufficiency and request explicit paths

### Edge Case 2: Type Mismatch

**Scenario**: Binary stdin but workflow expects text

```python
# stdin contains: b'\x89PNG\r\n\x1a\n' (image data)
# User: "analyze the text"
```

**Handling**: Parameter discovery checks stdin_info type and doesn't route incompatible data

### Edge Case 3: Ambiguous References

**Scenario**: User mentions both stdin and files

```python
# User: "compare the piped data with baseline.csv"
# stdin contains: new data
```

**Handling**: Map stdin to first parameter, explicit path to second

## Performance Considerations

### No Performance Impact

- Parameter discovery already receives stdin_info
- No additional processing required
- Template resolution unchanged
- No runtime overhead

### Memory Efficiency

- stdin already in shared store
- No duplication when using `${stdin}`
- Template resolution uses references

## Rollback Plan

If this approach causes issues:

1. **Immediate**: Remove stdin routing logic from prompt
2. **No code changes needed**: Just prompt reversion
3. **Users can still**: Explicitly handle stdin in workflows
4. **Alternative**: Document manual stdin workflow patterns

## Success Metrics

### Quantitative
- Parameter discovery prompt accuracy remains >90%
- No increase in workflow generation failures
- Reduced user-reported stdin issues

### Qualitative
- Users can naturally pipe data without thinking about it
- Workflows become more Unix-friendly
- Reduced friction in CLI usage

## Related Systems

### How Other Tools Handle This

**jq**: Always expects stdin
```bash
echo '{"key": "value"}' | jq .key
```

**awk/sed**: Always process stdin or files
```bash
cat file | awk '{print $1}'
awk '{print $1}' file  # Same behavior
```

**Our approach**: Intelligent routing based on context
```bash
cat data | pflow "analyze"  # Just works
pflow "analyze data.csv"    # Also just works
```

## Conclusion

The parameter discovery approach is:
- **Minimal**: Only requires prompt changes
- **Powerful**: Solves the entire stdin routing problem
- **Clean**: Maintains separation of concerns
- **Natural**: Users don't need to think about it

This is the "pflow way" - intelligent planning that makes workflows just work.