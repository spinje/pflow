# Workflow System Overview

## How Workflows Work

Workflows are **DATA PIPELINES** where:
1. **Users provide STARTING PARAMETERS** → These go in the "inputs" section
2. **Each node TRANSFORMS data** → Produces outputs for next nodes
3. **Later nodes CONSUME earlier outputs** → Using ${node_id.output_key} references
4. **The "inputs" section is the workflow's API** → What users can configure when running

Think of it like a recipe: inputs are the ingredients users bring, nodes are the cooking steps, and each step produces something the next step uses.

## Core Pattern Rules

**🔴 If user provides it** → MUST go in "inputs" section as `${param_name}`
**🔴 If a node generates it** → MUST reference as `${node_id.output_key}`, NEVER in inputs
**🔴 If you declare an input** → You MUST use it as `${param}` in node params
**🔴 If you use `${variable}`** → It MUST be declared in inputs OR be a node output

## Input Creation Guidelines

**Only create inputs for user-provided values:**
- User says "write hello to file.txt" → Create inputs for content ("hello") and file_path ("file.txt")
- Do NOT create inputs for optional parameters unless user mentioned them
- Use hardcoded values for defaults: `"encoding": "utf-8"` not `"encoding": "${encoding}"`

## Critical: Sequential Execution Only

**Every node can have ONLY ONE outgoing edge.** The system executes workflows sequentially, not in parallel.

**❌ WRONG (parallel - not supported):**
```
filter_data → analyze_trends
           ↘ generate_visualization
```

**✅ CORRECT (sequential - required):**
```
filter_data → analyze_trends → generate_visualization
```

If multiple operations need the same data, pass it through the chain:
- Second operation can reference BOTH the original data AND first operation's output
- Example: `generate_viz` can use both `${filter_data.content}` AND `${analyze_trends.response}`

## Node Outputs

Each node produces outputs that can be referenced by subsequent nodes:

### Common Output Patterns:
- **read-file**: `content` (string) - the file contents
- **write-file**: `file_path` (string) - where file was written
- **llm**: `response` (string) - the LLM's generated text
- **github-list-issues**: `issues` (array) - list of issue objects
- **github-create-issue**: `issue` (object) - created issue details
- **git-commit**: `commit_hash` (string) - the commit SHA
- **shell**: `stdout` (string), `stderr` (string), `exit_code` (int)
- **http**: `response` (object) - response with body, headers, status

### Referencing Outputs:
- Use `${node_id.output_key}` format
- Default output (if node has single main output): `${node_id.output}`
- Specific outputs: `${shell_cmd.stdout}`, `${shell_cmd.exit_code}`
- Nested data: `${fetch_data.response.body}`

## Workflow Input Format

Each input MUST be a structured object with metadata:

```json
"param_name": {
  "type": "string",              // Required: string, number, boolean, array, object
  "description": "Clear explanation of what this parameter is for",
  "required": true,               // Required: true or false
  "default": "optional default"   // Optional: only if required is false
}
```

**Never use simple strings:**
```json
"param_name": "Description"  // ❌ WRONG - must be object with type/description/required
```

## Complete Example Workflow

Here's a real workflow showing inputs, nodes with outputs, and complete data flow:

```json
{
  "inputs": {
    "repo_name": {
      "type": "string",
      "description": "GitHub repository in format owner/repo",
      "required": true
    },
    "issue_limit": {
      "type": "number",
      "description": "Maximum number of issues to analyze",
      "required": false,
      "default": 10
    },
    "output_file": {
      "type": "string",
      "description": "Path where the report will be saved",
      "required": true
    }
  },
  "nodes": [
    {
      "id": "fetch_issues",
      "type": "github-list-issues",
      "purpose": "Fetch recent issues from the repository",
      "params": {
        "repository": "${repo_name}",        // Uses workflow input
        "limit": "${issue_limit}",            // Uses workflow input with default
        "state": "all",                       // Hardcoded value (not from user)
        "sort": "created"                     // Hardcoded value
      }
      // Outputs: { "issues": [...] }
    },
    {
      "id": "analyze_patterns",
      "type": "llm",
      "purpose": "Analyze issue patterns and create insights",
      "params": {
        "prompt": "Analyze these GitHub issues and identify patterns, frequent contributors, and trends:\n\n${fetch_issues.issues}",
        "model": "gpt-4",
        "temperature": 0.3
      }
      // Outputs: { "response": "Analysis text..." }
    },
    {
      "id": "format_report",
      "type": "llm",
      "purpose": "Format analysis as markdown report",
      "params": {
        "prompt": "Convert this analysis into a well-formatted markdown report with sections:\n\n${analyze_patterns.response}",
        "model": "gpt-3.5-turbo"
      }
      // Outputs: { "response": "# Report\n..." }
    },
    {
      "id": "save_report",
      "type": "write-file",
      "purpose": "Save the formatted report to file",
      "params": {
        "file_path": "${output_file}",       // Uses workflow input
        "content": "${format_report.response}", // Uses previous node output
        "encoding": "utf-8"                  // Hardcoded default
      }
      // Outputs: { "file_path": "report.md" }
    }
  ],
  "start_node": "fetch_issues",
  "edges": [
    {"from": "fetch_issues", "to": "analyze_patterns"},
    {"from": "analyze_patterns", "to": "format_report"},
    {"from": "format_report", "to": "save_report"}
  ],
}
```

### Data Flow Visualization:

```
User Inputs:                     Node Outputs:
┌─────────────┐                 ┌──────────────┐
│ repo_name   │──────┐          │ fetch_issues │
│ issue_limit │──────┼─────────▶│ → issues[]   │
│ output_file │──┐   │          └──────┬───────┘
└─────────────┘  │   │                 │
                 │   │          ┌───────▼────────┐
                 │   │          │ analyze_patterns│
                 │   │          │ → response      │
                 │   │          └────────┬────────┘
                 │   │                   │
                 │   │          ┌────────▼────────┐
                 │   │          │ format_report   │
                 │   │          │ → response      │
                 │   │          └────────┬────────┘
                 │   │                   │
                 │   └──────────┬────────▼────────┐
                 └─────────────▶│ save_report     │
                                │ → file_path     │
                                └─────────────────┘
```

### Key Observations from Example:

1. **Inputs**: Only values the user provides (repo_name, issue_limit, output_file)
2. **Node Outputs**: Each node produces data for the next (issues → response → response → file_path)
3. **References**: Later nodes reference earlier outputs using `${node_id.output_key}`
4. **Hardcoded Values**: Parameters not from user are hardcoded (encoding, model, temperature)
5. **Sequential Flow**: Each node has exactly one successor, forming a chain