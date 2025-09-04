# Bug Report: Shell Command Generation Fails with Multiline Output

## Bug ID
BUG-001

## Date Reported
2025-01-03

## Reporter
Claude (on behalf of user)

## Severity
High - Workflow execution fails, blocking user functionality

## Status
Open

## Summary
When the planner generates a workflow that processes multiline output from a previous shell command, it creates malformed shell syntax that causes execution to fail with exit code 2.

## Description
The workflow planner incorrectly handles multiline output when generating subsequent shell commands. When a shell node outputs multiple lines (e.g., file paths), the next node attempting to process this output receives a malformed command that causes shell syntax errors.

## Steps to Reproduce
1. Run the following command:
   ```bash
   uv run pflow --trace "list all .md files in the current directory then let an llm write an .md file with a summary of all the files and their contents"
   ```

2. Observe the workflow execution

## Expected Behavior
The workflow should:
1. List all markdown files successfully
2. Read the contents of each file
3. Generate a summary using an LLM
4. Write the summary to a new markdown file

## Actual Behavior
The workflow fails at step 2 with:
```
read_file_contents...Command failed with exit code 2
/bin/sh: -c: line 1: syntax error near unexpected token `./CLAUDE.md'
/bin/sh: -c: line 1: `./CLAUDE.md'
```

## Error Details
From the trace file (`/Users/andfal/.pflow/debug/workflow-trace-20250903-150956.json`):

### Node 1: list_md_files (SUCCESS)
```json
{
  "stdout": "./README.md\n./CLAUDE.md\n",
  "stderr": "",
  "exit_code": 0
}
```

### Node 2: read_file_contents (FAILURE)
```json
{
  "stdout": "",
  "stderr": "/bin/sh: -c: line 1: syntax error near unexpected token `./CLAUDE.md'\n/bin/sh: -c: line 1: `./CLAUDE.md'\n",
  "exit_code": 2
}
```

## Root Cause Analysis
The planner appears to be generating a shell command that treats each line of the previous output as a separate statement rather than as arguments to a command.

### Likely Generated Command (WRONG):
```bash
./README.md
./CLAUDE.md
```

### What Should Be Generated:
```bash
for file in ./README.md ./CLAUDE.md; do cat "$file"; done
```
or
```bash
cat ./README.md ./CLAUDE.md
```

## Impact
- Users cannot create workflows that process multiple files listed by a previous command
- Workflows involving file iteration fail unpredictably
- Common use cases like "summarize all files" are blocked

## Workarounds
1. **Simplify the request** to avoid multiline processing:
   ```bash
   uv run pflow "find . -name '*.md' -type f -exec cat {} \; > all_content.txt"
   ```

2. **Break into separate steps**:
   - First save the file list to a file
   - Then process the file in a second workflow

3. **Use explicit file paths** instead of dynamic discovery:
   ```bash
   uv run pflow "cat README.md CLAUDE.md | llm summarize"
   ```

## Related Issues
- This is NOT related to Task 55 (output control implementation)
- May be related to how the planner handles template variables from shell output
- Could be an issue with the shell node's parameter parsing

## Suggested Fix
The planner needs to:
1. Properly escape or format multiline output when using it in subsequent shell commands
2. Consider using proper shell constructs (loops, xargs, etc.) when processing lists
3. Validate generated shell syntax before execution

## Additional Notes
- The workflow execution infrastructure is working correctly
- The issue is specifically in the workflow generation/planning phase
- The shell node itself is functioning properly (it correctly reports the syntax error)

## Attachments
- Workflow trace: `/Users/andfal/.pflow/debug/workflow-trace-20250903-150956.json`
- Full command output provided by user

## Environment
- Platform: darwin
- pflow version: 0.0.1
- Date: 2025-01-03
- Working directory: /Users/andfal/projects/pflow-fix-output-control-interactive

---
*This bug report was generated based on user-reported issue during Task 55 testing*