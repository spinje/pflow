---
name: workflow_generator
test_path: tests/test_planning/llm/prompts/test_workflow_generator_prompt.py::TestWorkflowGeneratorPrompt
test_command: uv run python tools/test_prompt_accuracy.py workflow_generator
version: '2.0'
latest_accuracy: 0.0
test_runs: []
average_accuracy: 0.0
test_count: 13
previous_version_accuracy: 100.0
last_tested: ''
prompt_hash: ''
---

# Workflow Generator

Generate workflow for: {{user_input}}

## Core Concept
Workflows are **data pipelines** where:
- Users provide starting parameters → `inputs` section
- Each node transforms data → produces outputs
- Later nodes reference earlier outputs → `${node_id.output}`

<available_nodes>
{{planning_context}}
</available_nodes>

## Critical Rules

**User provides it** → Declare in `inputs` as `${param_name}`
**Node generates it** → Reference as `${node_id.output_key}`, NEVER in inputs
**Every input declared** → Must be used in node params
**Every node** → Needs a specific purpose (10-200 chars)

## Workflow Patterns

**Simple (2-3 nodes):** `fetch → process → save`
**Standard (4-6 nodes):** `fetch → filter → analyze → format → save → notify`
**Complex (7+ nodes):** `fetch_multiple → combine → analyze → branch_outputs → save_multiple`

*Note: System executes sequentially. Design logical flow even if parallel would be optimal.*

## Compact Example

```json
{
  "ir_version": "0.1.0",
  "nodes": [
    {
      "id": "fetch_data",
      "type": "github-list-issues",
      "purpose": "Get closed issues for changelog",
      "params": {"repo_owner": "${owner}", "repo_name": "${repo}", "state": "closed", "limit": "${count}"}
    },
    {
      "id": "generate",
      "type": "llm",
      "purpose": "Create formatted changelog from issues",
      "params": {"prompt": "Generate changelog from: ${fetch_data.issues}"}
    },
    {
      "id": "save",
      "type": "write-file",
      "purpose": "Save changelog to file",
      "params": {"file_path": "${output_file}", "content": "${generate.response}"}
    }
  ],
  "edges": [
    {"from": "fetch_data", "to": "generate"},
    {"from": "generate", "to": "save"}
  ],
  "inputs": {
    "owner": {"type": "string", "required": true, "description": "Repository owner"},
    "repo": {"type": "string", "required": true, "description": "Repository name"},
    "count": {"type": "integer", "required": false, "default": 30, "description": "Issues to fetch"},
    "output_file": {"type": "string", "required": false, "default": "CHANGELOG.md"}
  },
  "outputs": {
    "changelog": {"description": "Generated changelog file", "source": "${save.file_path}"}
  }
}
```

Key points:
- `${owner}`, `${repo}` are user inputs (declared in inputs)
- `${fetch_data.issues}`, `${generate.response}` are node outputs (NOT in inputs)
- Each node has ONE outgoing edge (sequential execution)

<discovered_parameters>
{{discovered_params_section}}
</discovered_parameters>

{{#if validation_errors}}
## Fix These Errors
{{validation_errors_section}}
- Missing template variables → Add to inputs
- Unused inputs → Remove from inputs
- Wrong node types → Check available nodes
{{/if}}