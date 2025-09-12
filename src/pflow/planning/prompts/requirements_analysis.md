# Requirements Analysis

You are analyzing a user's workflow request to extract abstract operational requirements.

## User Input
{{input_text}}

## Input Type
This input has been templatized: {{is_templatized}}
(If "Yes", values have been replaced with ${param_name} placeholders)

## Your Task

Extract the abstract operational requirements from the user's request. You must:

1. **Identify what needs to be done** (WHAT, not HOW)
2. **Abstract away specific values** but **keep services explicit**
3. **Break down into single-purpose steps** (each step does ONE thing)
4. **Detect if the input is too vague** to create a workflow

## Requirements Extraction Rules

### Abstract Values, Keep Services

✅ CORRECT abstractions:
- "Fetch filtered issues from GitHub repository" (abstracts count/state, keeps GitHub)
- "Send notification to Slack channel" (abstracts channel name, keeps Slack)
- "Read content from configuration file" (abstracts filename)
- "Generate summary report" (abstracts format details)

❌ WRONG abstractions:
- "Fetch 20 closed issues from GitHub" (too specific with values)
- "Fetch ${issue_limit} issues" (don't include template variables)
- "Fetch data from service" (too vague about service)
- "Process information" (too vague about operation)

### Clarity Detection

Input is **too vague** when:
- Missing ACTION: "the deployment", "that thing"
- Missing TARGET: "process it", "handle this"
- Too generic: "do the usual", "the standard process"

Input is **clear enough** when:
- Has clear action + target: "generate changelog", "analyze code"
- Specifies input/output: "read X and produce Y"
- Identifies the service/tool: "fetch from GitHub", "post to Slack"

## Output Requirements

For each requirement step:
- Use imperative form ("Fetch", "Generate", "Send")
- Focus on the operation, not the implementation
- One operation per step
- Keep services/platforms explicit

## Required Capabilities

Identify the high-level capabilities needed:
- Services: github_api, slack_api, email_service
- Operations: text_generation, data_analysis, file_io
- Integrations: git_operations, database_access

## Complexity Indicators

Analyze the workflow complexity:
- has_conditional: Does it require if/then logic?
- has_iteration: Does it require loops or repeated operations?
- has_external_services: Does it interact with external APIs?
- external_services: List specific services (github, slack, etc.)

## Examples

### Example 1: Clear Input
Input: "Get last ${issue_limit} ${issue_state} issues from GitHub repo ${repo_owner}/${repo_name} and create a changelog"

Steps:
1. "Fetch filtered issues from GitHub repository"
2. "Group issues by category"
3. "Generate markdown changelog"
4. "Write changelog to file"

### Example 2: Too Vague
Input: "process the data"

is_clear: false
clarification_needed: "Please specify: 1) What data to process 2) What type of processing 3) Expected output format"

Remember: Extract WHAT needs to be done, not HOW to do it. The planning phase will determine HOW.