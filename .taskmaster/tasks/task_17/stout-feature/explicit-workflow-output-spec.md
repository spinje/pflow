# Feature: explicit_workflow_output

## Objective
Add stdout node that outputs workflow results explicitly.

## Requirements
- Node registry system exists and can register new nodes
- Template variable resolution system is operational
- CLI can execute workflows with shared store
- JSON IR validation system accepts new node types

## Scope
- Does not modify existing node output behavior
- Does not change shared store structure
- Does not implement formatted output tables
- Does not handle binary data output
- Does not add stderr node type
- Does not modify planner to auto-add output nodes
- Does not implement output redirection to files

## Inputs
- `content`: str - Text to output (supports template variables like $node.data)
- `format`: str = "text" - Output format (text|json|yaml)
- `stream`: str = "stdout" - Output stream (stdout|stderr)

## Outputs
Side effects: Writes content to specified stream (stdout or stderr)
Returns: "success" action string
Shared store additions: {"output_written": True}

## Rules
1. If content parameter is empty string then output empty line
2. If content contains template variables then resolve before output
3. If format is "json" and content is dict/list then output formatted JSON
4. If format is "json" and content is string then output string as-is
5. If format is "yaml" and content is dict/list then output formatted YAML
6. If format is "yaml" and content is string then output string as-is
7. If format is "text" then output content as-is
8. If stream is "stdout" then write to standard output
9. If stream is "stderr" then write to standard error
10. If template variable resolution fails then output empty string
11. Set shared["output_written"] to True after successful output
12. Return "success" after output completes

## Edge Cases
- content is None → output empty string
- content contains invalid template variable → output partial resolution
- format value not in (text|json|yaml) → default to text
- stream value not in (stdout|stderr) → default to stdout
- content is binary data → raise TypeError
- JSON serialization fails → output string representation
- YAML serialization fails → output string representation
- shared store not provided → use empty dict
- template variable references missing key → replace with empty string

## Test Criteria
1. Basic text output
   - Setup: params={"content": "Hello World"}
   - Expected: "Hello World" written to stdout

2. Template variable resolution
   - Setup: shared={"result": "42"}, params={"content": "Answer: $result"}
   - Expected: "Answer: 42" written to stdout

3. JSON formatting dict
   - Setup: shared={"data": {"key": "value"}}, params={"content": "$data", "format": "json"}
   - Expected: '{\n  "key": "value"\n}' written to stdout

4. JSON formatting string
   - Setup: params={"content": "plain text", "format": "json"}
   - Expected: "plain text" written to stdout

5. Stderr output
   - Setup: params={"content": "Error!", "stream": "stderr"}
   - Expected: "Error!" written to stderr

6. Empty content
   - Setup: params={"content": ""}
   - Expected: "\n" written to stdout

7. Missing template variable
   - Setup: params={"content": "Value: $missing"}
   - Expected: "Value: " written to stdout

8. Invalid format defaults
   - Setup: params={"content": "test", "format": "xml"}
   - Expected: "test" written to stdout

9. Output confirmation
   - Setup: params={"content": "test"}
   - Expected: shared["output_written"] == True

10. Success return
    - Setup: params={"content": "test"}
    - Expected: returns "success"

## Notes (Why)
- Explicit output follows Unix philosophy of making behavior visible
- Template variable support enables dynamic output from any workflow data
- Format options allow structured data output for piping
- Single node type keeps implementation simple
- Stream selection enables error reporting patterns
- Output confirmation flag enables downstream nodes to verify output occurred
