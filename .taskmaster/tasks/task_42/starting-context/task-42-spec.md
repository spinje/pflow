# Feature: claude_code_agentic_node

## Objective

Execute AI development tasks via Claude Code SDK with schema-driven outputs.

## Requirements

* Must have `claude-code-sdk` Python package installed
* Must have Claude Code CLI installed via npm
* Must have valid Claude authentication
* Must support Python 3.10 or higher
* Must integrate with pflow's shared store pattern
* Must support template variable resolution
* Must enforce tool permission whitelisting
* Must convert output schemas to system prompts

## Scope

* Does not support streaming responses in v1
* Does not maintain conversation state between invocations
* Does not support custom MCP servers
* Does not allow arbitrary tool execution without whitelist
* Does not modify files outside working directory

## Inputs

* task: str - Development task description from shared["task"] or params
* context: Optional[Union[str, dict]] - Additional context from shared["context"] or params
* output_schema: Optional[dict] - JSON schema defining expected outputs from shared["output_schema"] or params
* working_directory: Optional[str] - Project root from params, defaults to os.getcwd()
* model: str - Claude model identifier from params, defaults to "claude-3-5-sonnet-20241022"
* allowed_tools: list[str] - Permitted tools from params, defaults to ["Read", "Write", "Edit", "Bash"]
* max_turns: int - Maximum conversation turns from params, defaults to 5
* max_thinking_tokens: int - Maximum tokens for reasoning from params, defaults to 8000
* system_prompt: Optional[str] - System instructions from params
* append_system_prompt: Optional[str] - Additional system instructions from params

## Outputs

Returns: str - Action string ("success" or "error")

Side effects:
* Writes dynamic keys to shared store based on output_schema
* If no schema provided, writes to shared["result"]
* If schema provided but parsing fails, writes raw text to shared["result"] and shared["_schema_error"]
* May modify files in working directory via allowed tools
* Logs execution details including tool uses

## Structured Formats

```json
{
  "output_schema": {
    "type": "object",
    "properties": {
      "<key_name>": {
        "type": "<python_type>",
        "description": "<what this output represents>"
      }
    }
  },
  "schema_to_prompt_example": {
    "input_schema": {
      "root_cause": {"type": "str", "description": "The root cause of the bug"},
      "fix_applied": {"type": "str", "description": "Description of the fix"}
    },
    "generated_prompt": "You must structure your final response as valid JSON with these exact keys:\n{\n  \"root_cause\": \"<string: The root cause of the bug>\",\n  \"fix_applied\": \"<string: Description of the fix>\"\n}\n\nProvide ONLY the JSON object in a code block after completing your analysis."
  }
}
```

## State/Flow Changes

* `prep` → `exec` when validation passes
* `exec` → `success` when Claude Code completes successfully
* `exec` → `error` when Claude Code fails or times out
* `error` → `exec_fallback` transforms technical errors to user messages
* `schema_provided` → `prompt_generated` when schema converted to system prompt
* `response_received` → `json_parsed` when valid JSON extracted
* `json_parsed` → `fallback` when JSON parsing fails

## Constraints

* task must be non-empty string ≤ 10000 characters
* working_directory must exist and be accessible
* allowed_tools must be subset of ["Read", "Write", "Edit", "Bash"]
* max_turns must be between 1 and 20
* max_thinking_tokens must be between 1000 and 100000
* output_schema keys must be valid Python identifiers
* timeout fixed at 300 seconds via asyncio wrapper

## Rules

1. If task is missing then raise ValueError with guidance
2. If working_directory does not exist then raise ValueError
3. If Claude Code CLI is not installed then raise ValueError with install command
4. If authentication check fails then raise ValueError with auth command
5. If output_schema provided then convert to JSON format instructions
6. Merge schema instructions with user system_prompt if both exist
7. Build ClaudeCodeOptions with verified parameters
8. Execute query using asyncio.run wrapper with timeout
9. Parse response text blocks into concatenated string
10. If output_schema provided then attempt JSON extraction from response
11. If JSON parsing succeeds then store values in shared using schema keys
12. If JSON parsing fails then store raw text in shared["result"] and error in shared["_schema_error"]
13. Track tool uses in execution metadata
14. If SDK raises CLINotFoundError then transform to install guidance
15. If SDK raises CLIConnectionError then transform to auth guidance
16. If SDK raises ProcessError then include exit code and stderr
17. If asyncio timeout expires then raise with timeout message
18. Return "success" if execution completes
19. Return "error" if execution fails

## Edge Cases

* task empty string → raise ValueError "No task provided"
* task > 10000 chars → raise ValueError "Task too long"
* working_directory="/etc" → raise ValueError "Restricted directory"
* output_schema with invalid keys → raise ValueError "Invalid schema key"
* output_schema with 50+ keys → raise ValueError "Schema too complex"
* Claude API rate limit → raise ValueError with retry guidance
* Execution timeout at 300s → raise ValueError with timeout message
* No response content → return empty result
* Response has no JSON when schema provided → store raw text with error flag
* Response has invalid JSON → store raw text with parse error details
* Response JSON missing schema keys → store partial results with missing keys as None

## Error Handling

* CLINotFoundError → "Claude Code CLI not installed. Install with: npm install -g @anthropic-ai/claude-code"
* CLIConnectionError → "Failed to connect. Check auth with: claude doctor"
* ProcessError → "Process failed (exit {code}): {stderr}"
* Rate limit in error → "Rate limit exceeded. Wait and retry"
* asyncio.TimeoutError → "Execution timed out after 300 seconds"
* JSON parsing error → Store in shared["_schema_error"] with details
* Missing schema keys → Store None for missing keys
* Authentication subprocess fail → "Not authenticated. Run: claude auth login"

## Non-Functional Criteria

* Execution timeout: 300 seconds maximum via asyncio
* Memory limit: 1GB for response processing
* Log all tool invocations for audit
* Validate all file paths against working directory
* JSON extraction attempts: maximum 3 regex patterns
* Schema prompt injection: prepended to system_prompt

## Examples

### Basic task execution
```python
shared = {"task": "Write a fibonacci function"}
node = ClaudeCodeNode()
prep_res = node.prep(shared)
result = node.exec(prep_res)  # Returns "success"
# shared["result"] contains generated code
```

### With output schema
```python
shared = {
    "task": "Review this code for security issues",
    "output_schema": {
        "risk_level": {"type": "str", "description": "high/medium/low"},
        "issues": {"type": "list", "description": "List of security issues found"}
    }
}
node = ClaudeCodeNode()
# System prompt will include:
# "Structure your response as JSON: {\"risk_level\": \"...\", \"issues\": [...]}"
prep_res = node.prep(shared)
result = node.exec(prep_res)  # Returns "success"
# shared["risk_level"] = "medium"
# shared["issues"] = ["SQL injection on line 42", "No input validation"]
```

### Schema parsing fallback
```python
# If Claude doesn't return valid JSON despite schema:
# shared["result"] = <full text response>
# shared["_schema_error"] = "Failed to parse JSON: ..."
```

## Test Criteria

1. Task missing → ValueError with "No task provided"
2. Task empty string → ValueError with "No task provided"
3. Task > 10000 chars → ValueError with "Task too long"
4. Working directory missing → ValueError with path
5. Working directory restricted → ValueError with "Restricted directory"
6. CLI not installed (subprocess check) → ValueError with install command
7. Authentication failed (subprocess check) → ValueError with auth command
8. Valid task without schema → "success" and shared["result"] populated
9. Valid task with schema → "success" and schema keys in shared
10. Output schema invalid keys → ValueError with details
11. Output schema 50+ keys → ValueError "Schema too complex"
12. Rate limit error → ValueError with retry message
13. Timeout at 300s → ValueError with timeout message
14. CLINotFoundError handling → Correct error transformation
15. CLIConnectionError handling → Correct error transformation
16. ProcessError handling → Includes exit code
17. Tool whitelist enforcement → Only ["Read", "Write", "Edit", "Bash"] allowed
18. Schema to prompt conversion → System prompt contains JSON format
19. Valid JSON response → Values stored in schema keys
20. Invalid JSON response → Raw text in result, error in _schema_error
21. Partial JSON response → Missing keys stored as None
22. No response content → Empty result stored
23. Schema merged with user prompt → Both instructions present

## Notes (Why)

* Schema-as-system-prompt enables structured outputs without SDK support
* JSON format instructions guide Claude to produce parseable output
* Fallback to raw text ensures no data loss when parsing fails
* SDK chosen over CLI for structured responses and better error handling
* Asyncio wrapper with timeout prevents hanging on complex tasks
* Tool whitelisting prevents unintended system modifications
* Authentication check via subprocess ensures setup validation
* Schema complexity limit prevents overly complex prompts

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1, 2                      |
| 2      | 4, 5                      |
| 3      | 6                         |
| 4      | 7                         |
| 5      | 18                        |
| 6      | 23                        |
| 7      | 8, 9                      |
| 8      | 13                        |
| 9      | 8, 9                      |
| 10     | 19, 20                    |
| 11     | 19                        |
| 12     | 20, 21                    |
| 13     | 17                        |
| 14     | 14                        |
| 15     | 15                        |
| 16     | 16                        |
| 17     | 13                        |
| 18     | 8, 9, 19                  |
| 19     | 12, 13, 14, 15, 16        |

## Versioning & Evolution

* Version: 2.0.0
* Changelog:
  * 2.0.0 - Fixed parameter names, removed temperature, schema-as-prompt approach
  * 1.0.0 - Initial specification with incorrect assumptions

## Epistemic Appendix

### Assumptions & Unknowns

* Assumes Claude will follow JSON format instructions when provided in system prompt
* Assumes subprocess.run(["claude", "doctor"]) returns non-zero on auth failure
* Unknown: Exact error messages from CLIConnectionError
* Unknown: Whether Claude Code respects max_thinking_tokens parameter
* Assumes 300 seconds is sufficient for most development tasks

### Conflicts & Resolutions

* Temperature parameter doesn't exist in SDK. Resolution: Removed from spec
* SDK has max_thinking_tokens not max_tokens. Resolution: Fixed parameter name
* Dynamic schema extraction unreliable. Resolution: Use schema-as-system-prompt approach
* Tool names uncertain. Resolution: Limited to verified set ["Read", "Write", "Edit", "Bash"]

### Decision Log / Tradeoffs

* Schema-as-prompt over native structured output: Works with current SDK vs waiting for feature
* JSON parsing with fallback: Data preservation vs strict typing
* Subprocess auth check: Simple verification vs additional dependency
* 300-second timeout: Prevents hanging vs may cut off complex tasks
* Tool whitelist restriction: Security vs functionality (chose security)

### Ripple Effects / Impact Map

* Downstream nodes must handle both schema keys and _schema_error flag
* Planner must generate appropriate output schemas with descriptions
* Testing requires mocking both SDK responses and subprocess calls
* Documentation must explain schema-to-prompt conversion
* Future SDK updates may provide native structured output support

### Residual Risks & Confidence

* Risk: Claude ignores JSON instructions. Mitigation: Fallback to raw text. Confidence: Medium
* Risk: Subprocess auth check incorrect. Mitigation: Also catch SDK auth errors. Confidence: High
* Risk: JSON regex parsing fails. Mitigation: Multiple patterns, fallback. Confidence: High
* Risk: Tool names change in SDK. Mitigation: Conservative list. Confidence: High
* Overall confidence in specification: High

### Epistemic Audit (Checklist Answers)

1. Assumptions: JSON instruction following, auth check behavior, timeout sufficiency
2. Breakage if wrong: Schema parsing unreliable, auth check may pass incorrectly
3. Robustness over elegance: Chose explicit fallbacks over assuming success
4. Rule-Test mapping: Complete (see Compliance Matrix)
5. Ripple effects: Affects downstream nodes, planner, testing, future SDK integration
6. Uncertainty: JSON instruction effectiveness. Confidence: High with fallback strategy