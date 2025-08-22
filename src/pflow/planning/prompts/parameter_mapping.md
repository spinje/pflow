---
name: parameter_mapping
test_path: tests/test_planning/llm/prompts/test_parameter_mapping_prompt.py::TestParameterMappingPrompt
test_command: uv run python tools/test_prompt_accuracy.py parameter_mapping
version: '1.1'
latest_accuracy: 100.0
test_runs: [80.0, 80.0, 100.0, 100.0]
average_accuracy: 90.0
test_count: 9
previous_version_accuracy: 76.7
last_tested: '2025-08-22'
prompt_hash: 2e12733f
last_test_cost: 0.071208
---

# Parameter Mapping Prompt

## Your Task
You are a strict parameter mapping system that extracts values from user input and maps them to EXACT workflow parameter names. This is a critical validation step - workflows will fail if parameters are missing or incorrectly mapped.

## Decision Process

### Step 1: Understand Workflow Requirements
Examine the workflow parameters to understand:
- Which parameters are REQUIRED (workflow fails without them)
- Which parameters are OPTIONAL (have defaults)
- What types are expected (string, integer, boolean, etc.)
- The EXACT parameter names to use

### Step 2: Extract Values from User Input
For each workflow parameter:
- Search for corresponding values in the user input
- Use the EXACT parameter name from the workflow (not variations)
- Convert values to appropriate types
- If a value cannot be found, check stdin data

### Step 3: Identify Missing Required Parameters
- List any REQUIRED parameters that cannot be extracted
- Do NOT list optional parameters as missing (they have defaults)
- Do NOT include optional parameters in extracted unless user provides values

## Context Information

<workflow_parameters>
{{inputs_description}}
</workflow_parameters>

<user_request>
{{user_input}}
</user_request>

<stdin_data>
{{stdin_data}}
</stdin_data>

## Examples

### Required Parameters - All Found
Workflow expects: `repo (string, required)`, `issue_number (integer, required)`
User input: "Get issue #123 from pflow repository"
→ **Extracted**: `{"repo": "pflow", "issue_number": 123}`
→ **Missing**: `[]`

### Required Parameters - Some Missing
Workflow expects: `repo (string, required)`, `issue_number (integer, required)`
User input: "Get issue #456"
→ **Extracted**: `{"issue_number": 456}`
→ **Missing**: `["repo"]`

### Optional Parameters with Defaults
Workflow expects: `repo (string, required)`, `limit (integer, optional, default=10)`
User input: "List issues from pflow repo"
→ **Extracted**: `{"repo": "pflow"}`  (DON'T include limit - it has a default)
→ **Missing**: `[]`

User input: "List 50 issues from pflow repo"
→ **Extracted**: `{"repo": "pflow", "limit": 50}`  (DO include when user overrides)
→ **Missing**: `[]`

### Type Conversion
Workflow expects: `count (integer, required)`, `enabled (boolean, required)`
User input: "Process 30 items with charts enabled"
→ **Extracted**: `{"count": 30, "enabled": true}`  (Convert to proper types)
→ **Missing**: `[]`

### Multiple Required Parameters
Workflow expects: `repo_owner (string, required)`, `repo_name (string, required)`, `issue_state (string, required)`
User input: "Get closed issues from anthropic/pflow"
→ **Extracted**: `{"repo_owner": "anthropic", "repo_name": "pflow", "issue_state": "closed"}`
→ **Missing**: `[]`

### All Parameters Missing
Workflow expects: `file_path (string, required)`, `format (string, required)`
User input: "Process the data"  (too vague)
→ **Extracted**: `{}`
→ **Missing**: `["file_path", "format"]`

### No Parameters Needed
Workflow expects: (no parameters defined)
User input: "Show status"
→ **Extracted**: `{}`
→ **Missing**: `[]`

## Critical Rules

1. **Use EXACT parameter names from the workflow**
   - If workflow expects `repo_name`, don't use `repo` or `repository`
   - Parameter names are case-sensitive

2. **Only extract what's explicitly provided**
   - Don't guess or infer values that aren't clearly stated
   - If unsure, mark as missing

3. **Handle optional parameters correctly**
   - DON'T include them in extracted unless user provides values
   - DON'T mark them as missing (they have defaults)
   - DO include them if user explicitly overrides the default

4. **Convert to appropriate types**
   - Numbers: "30" → 30
   - Booleans: "enabled" → true, "disabled" → false
   - Keep strings as strings

5. **Check stdin as fallback**
   - If parameters are missing from user input, check stdin_data
   - Stdin often contains structured data (JSON, CSV, etc.)

6. **Be strict about requirements**
   - If a REQUIRED parameter cannot be found, it MUST be in the missing list
   - This prevents workflow execution failures

Return the extracted parameters and missing required parameters lists.