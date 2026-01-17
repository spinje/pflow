# Task 101: Shell Node File Input Parameter for Safe Data Passing

## Description
Add a `files` parameter to the shell node that allows passing template data as temporary files instead of embedding in command strings. This eliminates shell escaping issues when JSON or other structured data contains quotes, apostrophes, or special characters.

## Status
not started

## Dependencies
- Task 41: Implement Shell Node - The shell node must exist before we can extend it with file input capabilities

## Priority
medium

## Details
When shell commands need to process data from previous nodes (via template variables like `${node.output}`), the current approach embeds the data directly into the command string. This breaks when the data contains shell-sensitive characters like quotes or apostrophes.

**The Problem:**
```bash
# Template:
command: "echo '${node.output}' | jq '.'"

# If node.output is: {"message": "it's working"}
# Becomes:
echo '{"message": "it's working"}' | jq '.'
#                    ↑ shell breaks here
```

**Current Workarounds:**
- Use stdin (but only supports ONE input)
- Manually write to temp files in workflow (verbose, error-prone)
- Base64 encode/decode (complex)

**Proposed Solution:**
Add a `files` parameter that automatically writes template data to temp files and exposes paths as environment variables:

```json
{
  "type": "shell",
  "params": {
    "command": "jq -s '.[0] + .[1]' $INPUT1 $INPUT2",
    "files": {
      "INPUT1": "${node1.output}",
      "INPUT2": "${node2.output}"
    }
  }
}
```

### Implementation Approach

1. **In shell node's `prep()` or `exec()`:**
   - For each entry in `files`, resolve the template value
   - Write the value to a temp file (use `tempfile.NamedTemporaryFile`)
   - Store the file path in an environment variable with the specified key

2. **Command execution:**
   - Pass the environment variables when executing the command
   - The command can reference `$INPUT1`, `$INPUT2`, etc.

3. **Cleanup:**
   - Delete temp files after command completes (success or failure)
   - Use try/finally or context manager for reliability

### Key Design Decisions

- **Environment variables over command substitution**: Using `$VAR` in the command is cleaner than replacing placeholders
- **Auto-cleanup**: Temp files are deleted after execution, no manual cleanup needed
- **JSON handling**: If the value is a dict/list, serialize to JSON before writing
- **String handling**: If the value is already a string, write as-is
- **File extension**: Use `.json` for dict/list, `.txt` for strings (helps debugging)

### Example Usage

```json
{
  "id": "process-data",
  "type": "shell",
  "params": {
    "command": "jq -s '.[0] as $imgs | .[1] as $results | ...' $IMAGES $RESULTS",
    "files": {
      "IMAGES": "${download-images.stdout}",
      "RESULTS": "${describe-images.results}"
    }
  }
}
```

This replaces the current pattern of:
```json
{
  "id": "save-to-temp",
  "type": "shell",
  "params": {
    "stdin": "${describe-images.results}",
    "command": "cat > /tmp/results.json && echo '${download-images.stdout}' > /tmp/images.json"
  }
},
{
  "id": "process-data",
  "type": "shell",
  "params": {
    "command": "jq -s '...' /tmp/images.json /tmp/results.json"
  }
}
```

## Test Strategy

### Unit Tests
- Test that `files` parameter creates temp files with correct content
- Test JSON serialization for dict/list values
- Test string values written as-is
- Test environment variables are set correctly
- Test cleanup happens after successful execution
- Test cleanup happens after failed execution
- Test file paths are accessible in command

### Integration Tests
- Test workflow with multiple file inputs
- Test combining `files` with `stdin` (both should work together)
- Test with JSON containing quotes, apostrophes, special characters
- Test with large data (verify no size limits)

### Edge Cases
- Empty files parameter (should work, no files created)
- Empty string value (should create empty file)
- Null value (should skip or create empty file)
- Very long environment variable names
- File write permission errors
